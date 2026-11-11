"""Сквозные сценарии: студент → агент → сотрудник → ответ."""
import json
from datetime import datetime

from app import llm, rules
from conftest import GOOD, SAMPLE_TEXT, F, H, submit


def detail(c, app_id):
    r = c.get(f"/api/staff/applications/{app_id}")
    assert r.status_code == 200, r.text
    return r.json()


def only_id(c):
    items = c.get("/api/staff/applications?status=").json()["items"]
    assert len(items) == 1
    return items[0]["id"]


def test_meta(client):
    m = client.get("/api/meta").json()
    assert m["org"] == "Тестовый колледж"
    assert ".pdf" in m["accept"] and ".docx" in m["accept"] and ".jpg" in m["accept"]
    assert "Пересдача экзамена" in m["types"]


def test_pages_served(client):
    for path in ("/", "/staff", "/status/abcdefghijklmnopqrstuvwxyz"):
        r = client.get(path)
        assert r.status_code == 200 and "<!DOCTYPE html>" in r.text
    r = client.get("/")
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_clean_path_to_reply(client, staff, reader):
    r = submit(client, text=SAMPLE_TEXT)
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    assert r.json()["kind"] == "Пересдача экзамена" and "number" not in r.json()

    pub = client.get(f"/api/public/{token}").json()
    assert pub["status"] == "confirm"
    assert pub["status_label"] == "Сотрудник готовит ответ"
    assert pub["reply"] == ""                       # до подтверждения ответа нет
    year = datetime.now().year
    assert pub["reg_no"] == f"ВХ-{year}-0001"
    assert pub["owner"] == "Деканат"
    assert pub["name"] == "Садыков Нурлан" and pub["group"] == "ИС-24/2"

    sent_text = reader.calls[0]["text"]
    assert sent_text.startswith("Декану факультета\nот студента группы ИС-24/2\nСадыков Нурлан\n\nЗАЯВЛЕНИЕ")
    assert SAMPLE_TEXT in sent_text and sent_text.endswith("Дата: " + datetime.now().strftime("%d.%m.%Y"))
    assert reader.calls[0]["form"] == {"surname": "Садыков", "first_name": "Нурлан", "group": "ИС-24/2",
                                       "kind": "Пересдача экзамена"}
    app_id = only_id(staff)
    d = detail(staff, app_id)
    assert d["status"] == "confirm" and not d["manual"]
    assert "Нурлан Ерболатович" in d["reply_text"] and d["reg_no"] in d["reply_text"]
    assert d["reader"] == "ai:claude-opus-5-5"

    edited = d["reply_text"] + "\nДобавлено сотрудником."
    r = staff.post(f"/api/staff/applications/{app_id}/send", json={"text": edited}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "sent"

    pub = client.get(f"/api/public/{token}").json()
    assert pub["status"] == "sent" and pub["reply"].endswith("Добавлено сотрудником.")

    # повторно отправить нельзя
    r = staff.post(f"/api/staff/applications/{app_id}/send", json={}, headers=H)
    assert r.status_code == 400


def test_missing_fields_go_to_review_and_staff_fixes(client, staff, reader):
    resp = json.loads(json.dumps(GOOD))
    resp["fields"]["date"] = F("", "missing")
    resp["fields"]["group"] = F("ПО-22", "low")
    reader.response = resp
    token = submit(client, text=SAMPLE_TEXT).json()["token"]
    assert client.get(f"/api/public/{token}").json()["status_label"] == "Проверяет сотрудник"

    app_id = only_id(staff)
    d = detail(staff, app_id)
    assert d["status"] == "review"
    assert [i["key"] for i in d["issues_list"]] == ["group"]
    assert d["fields"]["date"] == {"v": datetime.now().strftime("%d.%m.%Y"), "c": "form"}   # дата подачи
    assert d["fields"]["sign"]["c"] == "high"
    assert d["reg_no"] == ""

    r = staff.post(f"/api/staff/applications/{app_id}/resume", headers=H)
    assert r.status_code == 400 and "исправьте" in r.json()["error"]

    r = staff.patch(f"/api/staff/applications/{app_id}/fields", json={"fields": {"date": "31.02.2026"}}, headers=H)
    assert r.status_code == 400 and "ДД.ММ.ГГГГ" in r.json()["error"]
    r = staff.patch(f"/api/staff/applications/{app_id}/fields", json={"fields": {"course": "9"}}, headers=H)
    assert r.status_code == 400

    r = staff.patch(f"/api/staff/applications/{app_id}/fields",
                    json={"fields": {"date": "10.11.2026", "group": "ПО-22"}}, headers=H)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["issues_list"] == [] and d["fields"]["date"] == {"v": "10.11.2026", "c": "fixed"}

    d = staff.post(f"/api/staff/applications/{app_id}/resume", headers=H).json()
    assert d["status"] == "confirm" and d["manual"] and d["reg_no"]
    journal = staff.get("/api/staff/journal").json()["items"]
    assert journal[0]["manual"] is True and journal[0]["date"] == "10.11.2026"


def test_unknown_type_needs_staff_choice(client, staff, reader):
    resp = json.loads(json.dumps(GOOD))
    resp["type"] = "Другое"
    reader.response = resp
    submit(client, text=SAMPLE_TEXT, kind="Другое")
    app_id = only_id(staff)
    d = detail(staff, app_id)
    assert [i["key"] for i in d["issues_list"]] == ["type"]
    assert "Другое" not in d["types"]
    r = staff.patch(f"/api/staff/applications/{app_id}/fields", json={"type": "Другое"}, headers=H)
    assert r.status_code == 400
    d = staff.patch(f"/api/staff/applications/{app_id}/fields", json={"type": "Академический отпуск"}, headers=H).json()
    assert d["issues_list"] == []
    d = staff.post(f"/api/staff/applications/{app_id}/resume", headers=H).json()
    assert d["owner"] == "Деканат" and d["type"] == "Академический отпуск"


def test_change_type_in_confirm_updates_owner_and_reply(client, staff, reader):
    submit(client, text=SAMPLE_TEXT)
    app_id = only_id(staff)
    d = staff.patch(f"/api/staff/applications/{app_id}/fields", json={"type": "Материальная помощь"}, headers=H).json()
    assert d["status"] == "confirm" and d["owner"] == "Студенческий отдел"
    assert "Материальная помощь" in d["reply_text"]


def test_return_to_student(client, staff, reader):
    token = submit(client, text=SAMPLE_TEXT).json()["token"]
    app_id = only_id(staff)
    r = staff.post(f"/api/staff/applications/{app_id}/return", json={"message": "ok"}, headers=H)
    assert r.status_code == 400
    r = staff.post(f"/api/staff/applications/{app_id}/return",
                   json={"message": "Нет подписи. Подпишите и отправьте заново."}, headers=H)
    assert r.status_code == 200 and r.json()["status"] == "returned"
    pub = client.get(f"/api/public/{token}").json()
    assert pub["status"] == "returned" and "Нет подписи" in pub["message"] and pub["reply"] == ""
    # закрытое заявление не меняется
    assert staff.patch(f"/api/staff/applications/{app_id}/fields", json={"fields": {"course": "3"}}, headers=H).status_code == 400


def test_ai_error_falls_back_to_rules(client, staff, reader):
    reader.error = llm.ReaderError("Слишком много запросов к модели. Повторите обработку позже.")
    submit(client, text=SAMPLE_TEXT)
    app_id = only_id(staff)
    d = detail(staff, app_id)
    assert d["status"] == "review"
    assert d["reader"] == "rules" and "Слишком много запросов" in d["reader_note"]
    assert d["fields"]["group"] == {"v": "ИС-24/2", "c": "high"}   # совпала с формой
    assert d["fields"]["date"] == {"v": datetime.now().strftime("%d.%m.%Y"), "c": "form"}
    assert d["type"] == "Пересдача экзамена"

    # после восстановления ИИ можно прочитать заново
    reader.error = None
    d = staff.post(f"/api/staff/applications/{app_id}/reprocess", headers=H).json()
    assert d["status"] == "confirm" and d["reader"].startswith("ai:")


def test_ai_disabled_uses_rules(settings, reader):
    from fastapi.testclient import TestClient
    from app.main import create_app

    settings.ai_enabled = False
    a = create_app(settings)
    with TestClient(a) as c:
        assert c.get("/api/meta").json()["ai"] is False
        token = submit(c, text=SAMPLE_TEXT).json()["token"]
        row = a.state.db.one("SELECT * FROM applications WHERE public_token = ?", (token,))
        assert row["status"] == "review" and row["reader"] == "rules"
        fields = json.loads(row["fields_json"])
        assert fields["group"]["c"] == "high"                      # подтверждена формой
        assert fields["date"]["c"] == "form" and fields["sign"]["c"] == "form"   # подано через форму
        assert row["type"] == "Пересдача экзамена" and row["type_confidence"] in ("high", "form")
        assert all(f["c"] in ("low", "missing", "high") for f in fields.values() if f["c"] != "form")
        assert fields["purpose"]["c"] == "low"     # без ИИ суть всегда проверяет сотрудник
    assert reader.calls == []


def test_crash_in_processing_keeps_application(client, staff, reader):
    reader.response = lambda docs, text: 1 / 0
    token = submit(client, text=SAMPLE_TEXT).json()["token"]
    app_id = only_id(staff)
    d = detail(staff, app_id)
    assert d["status"] == "review" and "Ошибка обработки" in d["reader_note"]
    assert client.get(f"/api/public/{token}").json()["status"] == "review"


def test_late_result_after_close_is_ignored(client, staff, reader, settings):
    from app import agent

    submit(client, text=SAMPLE_TEXT)
    app_id = only_id(staff)
    staff.post(f"/api/staff/applications/{app_id}/return", json={"message": "Нужна другая форма."}, headers=H)
    agent.process(settings, client.app.state.db, app_id)
    assert detail(staff, app_id)["status"] == "returned"


def test_requeue_on_startup(settings, reader):
    from fastapi.testclient import TestClient
    from app.db import now
    from app.main import create_app

    a = create_app(settings)
    with a.state.db.tx() as con:
        con.execute("INSERT INTO applications(public_token, status, text_input, created_at, updated_at) "
                    "VALUES ('t' || hex(randomblob(12)), 'received', ?, ?, ?)", (SAMPLE_TEXT, now(), now()))
    with TestClient(a):
        pass
    assert a.state.db.one("SELECT status FROM applications")["status"] == "confirm"


def test_registration_numbers_increase(client, staff, reader):
    for _ in range(3):
        submit(client, text=SAMPLE_TEXT)
    nos = [r["reg_no"] for r in staff.get("/api/staff/journal").json()["items"]]
    year = datetime.now().year
    assert nos == [f"ВХ-{year}-0001", f"ВХ-{year}-0002", f"ВХ-{year}-0003"]


def test_journal_csv_escapes_formulas(client, staff, reader):
    resp = json.loads(json.dumps(GOOD))
    reader.response = resp
    submit(client, text=SAMPLE_TEXT)
    app_id = only_id(staff)
    staff.patch(f"/api/staff/applications/{app_id}/fields", json={"fields": {"fio": "=HYPERLINK(\"http://x\") Иванов"}}, headers=H)
    r = staff.get("/api/staff/journal?format=csv")
    assert r.status_code == 200
    assert r.text.startswith("﻿")
    assert "\"'=HYPERLINK" in r.text and ";=HYPERLINK" not in r.text and ";\"=HYPERLINK" not in r.text


def test_stats(client, staff, reader):
    submit(client, text=SAMPLE_TEXT)
    s = staff.get("/api/staff/stats").json()
    assert s["total"] == 1 and s["by_status"]["confirm"] == 1 and s["ai"] is True
    assert s["by_type"] == [{"type": "Пересдача экзамена", "n": 1}]


def test_rules_reader_on_sample():
    r = rules.read(SAMPLE_TEXT)
    f = r["fields"]
    assert r["type"] == "Пересдача экзамена"
    assert f["group"]["value"] == "ИС-24/2" and f["course"]["value"] == "2"
    assert f["date"]["value"] == "09.11.2026" and f["sign"]["value"] == "есть"
    assert f["fio"]["value"] == "Садыкова Нурлана Ерболатовича"    # без ИИ падеж не меняется: поэтому low
    assert all(v["confidence"] in ("low", "missing") for v in f.values())


def test_form_fills_missing_fields(client, staff, reader):
    resp = json.loads(json.dumps(GOOD))
    resp["fields"]["fio"] = F("", "missing")
    resp["fields"]["group"] = F("", "missing")
    reader.response = resp
    submit(client, text=SAMPLE_TEXT)
    d = detail(staff, only_id(staff))
    assert d["fields"]["fio"] == {"v": "Садыков Нурлан", "c": "form"}
    assert d["fields"]["group"] == {"v": "ИС-24/2", "c": "form"}
    assert d["status"] == "confirm" and d["student_group"] == "ИС-24/2"


def test_form_mismatch_goes_to_review(client, staff, reader):
    submit(client, text=SAMPLE_TEXT, surname="Другой", group="ЭК-31")
    d = detail(staff, only_id(staff))
    assert d["status"] == "review"
    assert sorted(i["key"] for i in d["issues_list"]) == ["fio", "group"]
    assert any("не совпадает с формой" in w for w in d["warnings"])


def test_form_genitive_surname_matches(client, staff, reader):
    reader.error = llm.ReaderError("нет ключа")   # правила: ФИО в родительном падеже
    submit(client, text=SAMPLE_TEXT)
    d = detail(staff, only_id(staff))
    assert not any("ФИО в документе" in w for w in d["warnings"])
    assert d["fields"]["group"]["c"] == "high"     # документ и форма совпали



def test_chosen_kind_wins_over_weak_guess(client, staff, reader):
    resp = json.loads(json.dumps(GOOD))
    resp["type"], resp["type_confidence"] = "Материальная помощь", "low"
    reader.response = resp
    submit(client, text="Прошу выдать мне справку с места учёбы.", kind="Справка с места учёбы")
    d = detail(staff, only_id(staff))
    assert d["type"] == "Справка с места учёбы" and d["type_confidence"] == "form"
    assert d["student_kind"] == "Справка с места учёбы" and d["owner"] == "Учебная часть"


def test_kind_conflict_goes_to_staff(client, staff, reader):
    submit(client, text=SAMPLE_TEXT, kind="Справка с места учёбы")     # модель уверенно видит пересдачу
    d = detail(staff, only_id(staff))
    assert d["status"] == "review" and [i["key"] for i in d["issues_list"]] == ["type"]
    assert any("похоже на «Пересдача экзамена»" in w for w in d["warnings"])


def test_kind_required_and_wording_in_meta(client):
    assert submit(client, text=SAMPLE_TEXT, kind="").status_code == 400
    assert submit(client, text=SAMPLE_TEXT, kind="Несуществующий").status_code == 400
    kinds = client.get("/api/meta").json()["kinds"]
    spravka = next(k for k in kinds if k["name"] == "Справка с места учёбы")
    assert spravka["addressee"] == "Начальнику учебной части" and spravka["wording"].startswith("Прошу выдать")
    assert kinds[-1]["name"] == "Другое"


def test_file_only_does_not_invent_date(client, staff, reader):
    from conftest import make_docx

    resp = json.loads(json.dumps(GOOD))
    resp["fields"]["date"] = F("", "missing")
    resp["fields"]["sign"] = F("", "missing")
    reader.response = resp
    submit(client, files=[("files", ("z.docx", make_docx("Заявление"), "application/octet-stream"))])
    d = detail(staff, only_id(staff))
    assert d["text_input"] == ""
    assert sorted(i["key"] for i in d["issues_list"]) == ["date", "sign"]
