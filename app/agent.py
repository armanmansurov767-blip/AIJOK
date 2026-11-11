"""Агент DocAgent: чтение → тип → поля → проверка → журнал → проект ответа.

Ответ студенту уходит только после подтверждения сотрудником (см. send_reply).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from . import doctypes, llm, rules
from .config import Settings
from .db import Database, add_event, next_counter, now
from .extract import extract_text

log = logging.getLogger("docagent.agent")

STATUSES = ("received", "processing", "review", "confirm", "sent", "returned")
CONF = ("high", "low", "missing")
_DATE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})$")


class ActionError(ValueError):
    """Действие сотрудника нельзя выполнить. message показывается в интерфейсе."""


# ---------- нормализация ответа читателя ----------

def _valid_date(v: str) -> bool:
    m = _DATE.match(v)
    if not m:
        return False
    try:
        datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        return True
    except ValueError:
        return False


def normalize(raw: dict) -> dict:
    fields_in = raw.get("fields") if isinstance(raw.get("fields"), dict) else {}
    fields = {}
    for k in doctypes.KEYS:
        e = fields_in.get(k) if isinstance(fields_in.get(k), dict) else {}
        v = e.get("value")
        v = "" if v is None else str(v).strip()
        c = e.get("confidence") if e.get("confidence") in CONF else "low"
        if not v:
            c = "missing"
        if c == "missing":
            v = ""
        if k == "date" and v and not _valid_date(v):
            c = "low"
        if k == "course" and v:
            m = re.search(r"\d+", v)
            v = m.group(0) if m else v
            if not re.fullmatch(r"[1-6]", v):
                c = "low"
        if k == "sign" and v:
            v = "есть"
        if k == "fio" and v and len(v.split()) < 2:
            c = "low"
        fields[k] = {"v": v[:300], "c": c}
    type_name = raw.get("type") if raw.get("type") in doctypes.all_names() else doctypes.other_name()
    type_conf = raw.get("type_confidence") if raw.get("type_confidence") in ("high", "low") else "low"
    if raw.get("type") not in doctypes.all_names():
        type_conf = "low"
    warnings = raw.get("warnings") if isinstance(raw.get("warnings"), list) else []
    return {
        "doc_kind": str(raw.get("doc_kind") or "")[:40],
        "type": type_name,
        "type_confidence": type_conf,
        "fields": fields,
        "summary": str(raw.get("summary") or "")[:600],
        "warnings": [str(w)[:300] for w in warnings][:10],
    }


def compute_issues(type_name: str, type_conf: str, fields: dict) -> list[dict]:
    issues = []
    if type_name == doctypes.other_name():
        issues.append({"key": "type", "reason": "Тип не определён: выберите тип"})
    elif type_conf == "low":
        issues.append({"key": "type", "reason": "Агент не уверен в типе"})
    for k in doctypes.required(type_name):
        f = fields.get(k) or {"v": "", "c": "missing"}
        if f["c"] == "missing":
            issues.append({"key": k, "reason": "Нет в документе"})
        elif f["c"] == "low":
            issues.append({"key": k, "reason": "Агент не уверен"})
    return issues


def first_name(fio: str) -> str:
    parts = fio.split()
    return " ".join(parts[1:]) if len(parts) > 1 else (parts[0] if parts else "студент")


def draft_reply(settings: Settings, app) -> str:
    fields = json.loads(app["fields_json"])
    tpl = doctypes.reply_template(app["type"])
    values = {
        "name": first_name(fields.get("fio", {}).get("v", "")),
        "type": app["type"],
        "no": app["reg_no"] or "",
        "owner": app["owner"] or doctypes.owner(app["type"]),
        "org": settings.org_name,
    }
    try:
        return tpl.format(**values)
    except (KeyError, IndexError, ValueError):
        return doctypes.reply_template("").format(**values)


# ---------- обработка ----------

def _load_inputs(settings: Settings, db: Database, app_id: int) -> tuple[list[llm.InputDoc], list]:
    rows = db.all("SELECT * FROM files WHERE application_id = ? ORDER BY id", (app_id,))
    docs = []
    for r in rows:
        data = (settings.upload_dir / r["stored_name"]).read_bytes()
        docs.append(llm.InputDoc(name=r["original_name"], kind=r["kind"], mime=r["mime"], data=data,
                                 text=r["extracted_text"]))
    return docs, rows


def _register(settings: Settings, con, app_id: int, actor: str) -> None:
    app = con.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
    owner = doctypes.owner(app["type"])
    if app["reg_no"]:
        con.execute("UPDATE applications SET owner = ?, updated_at = ? WHERE id = ?", (owner, now(), app_id))
    else:
        year = datetime.now().year
        n = next_counter(con, f"reg-{year}")
        reg_no = f"ВХ-{year}-{n:04d}"
        con.execute("UPDATE applications SET reg_no = ?, registered_at = ?, owner = ?, updated_at = ? WHERE id = ?",
                    (reg_no, now(), owner, now(), app_id))
        add_event(con, app_id, actor, "registered", {"reg_no": reg_no, "owner": owner})
    app = con.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
    con.execute("UPDATE applications SET reply_text = ?, status = 'confirm', updated_at = ? WHERE id = ?",
                (draft_reply(settings, app), now(), app_id))
    add_event(con, app_id, "agent", "draft_ready", "")


def process(settings: Settings, db: Database, app_id: int) -> None:
    """Полный проход агента по заявлению. Безопасно вызывать повторно (переобработка)."""
    with db.tx() as con:
        app = con.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
        if app is None or app["status"] in ("sent", "returned"):
            return
        con.execute("UPDATE applications SET status = 'processing', updated_at = ? WHERE id = ?", (now(), app_id))
        add_event(con, app_id, "agent", "processing", "")

    try:
        docs, _rows = _load_inputs(settings, db, app_id)
        text_input = app["text_input"]
        reader, note = "rules", ""
        raw = None
        if settings.ai_enabled:
            try:
                raw = llm.read_documents(settings, docs, text_input)
                reader = "ai:" + settings.model
            except llm.ReaderError as e:
                note = str(e)
                log.warning("AI reader failed for application %s: %s", app_id, e)
        else:
            note = "ИИ выключен: документ прочитан правилами."
        if raw is None:
            all_text = "\n\n".join([d.text for d in docs if d.text] + ([text_input] if text_input else []))
            raw = rules.read(all_text)
            if not all_text.strip():
                raw["warnings"].append("В файлах нет текстового слоя (скан или фото). Без ИИ поля нужно ввести вручную.")
        result = normalize(raw)
        if reader == "rules":
            for f in result["fields"].values():
                if f["c"] == "high":
                    f["c"] = "low"
            result["type_confidence"] = "low"
        issues = compute_issues(result["type"], result["type_confidence"], result["fields"])
    except Exception as e:  # noqa: BLE001 - заявление не должно потеряться из-за ошибки
        log.exception("Processing failed for application %s", app_id)
        with db.tx() as con:
            con.execute("UPDATE applications SET status = 'review', reader_note = ?, issues_json = ?, manual = 1, "
                        "updated_at = ? WHERE id = ?",
                        ("Ошибка обработки: " + str(e)[:300],
                         json.dumps([{"key": "type", "reason": "Обработка не удалась: проверьте вручную"}], ensure_ascii=False),
                         now(), app_id))
            add_event(con, app_id, "agent", "error", str(e)[:300])
        return

    with db.tx() as con:
        cur = con.execute("SELECT status FROM applications WHERE id = ?", (app_id,)).fetchone()
        if cur is None or cur["status"] != "processing":
            return  # пока шла обработка, заявление закрыли
        con.execute(
            "UPDATE applications SET doc_kind = ?, type = ?, type_confidence = ?, fields_json = ?, summary = ?, "
            "warnings_json = ?, issues_json = ?, reader = ?, reader_note = ?, manual = ?, updated_at = ? WHERE id = ?",
            (result["doc_kind"], result["type"], result["type_confidence"],
             json.dumps(result["fields"], ensure_ascii=False), result["summary"],
             json.dumps(result["warnings"], ensure_ascii=False), json.dumps(issues, ensure_ascii=False),
             reader, note, 1 if issues else 0, now(), app_id))
        add_event(con, app_id, "agent", "read", {"reader": reader, "type": result["type"], "issues": [i["key"] for i in issues]})
        if issues:
            con.execute("UPDATE applications SET status = 'review', updated_at = ? WHERE id = ?", (now(), app_id))
            add_event(con, app_id, "agent", "needs_review", [i["key"] for i in issues])
        else:
            _register(settings, con, app_id, "agent")


def reextract_files(settings: Settings, db: Database, app_id: int) -> None:
    """Повторно извлекает текст из файлов (например, после обновления библиотек)."""
    for r in db.all("SELECT * FROM files WHERE application_id = ?", (app_id,)):
        data = (settings.upload_dir / r["stored_name"]).read_bytes()
        text, pages = extract_text(r["kind"], data)
        with db.tx() as con:
            con.execute("UPDATE files SET extracted_text = ?, pages = ? WHERE id = ?", (text, pages, r["id"]))


# ---------- действия сотрудника ----------

def _get_for_update(con, app_id: int):
    app = con.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
    if app is None:
        raise ActionError("Заявление не найдено.")
    return app


def validate_value(key: str, value) -> str:
    if key == "sign":
        return "есть" if value in (True, "есть", "true", "1", 1) else ""
    v = ("" if value is None else str(value)).strip()
    if key == "date":
        if not _valid_date(v):
            raise ActionError("Дата: формат ДД.ММ.ГГГГ, например 09.11.2026.")
    elif key == "course":
        if not re.fullmatch(r"[1-6]", v):
            raise ActionError("Курс: одна цифра от 1 до 6.")
    elif key == "fio":
        if len(v.split()) < 2 or len(v) > 150:
            raise ActionError("ФИО: фамилия и имя (и отчество, если есть).")
    elif key in ("group", "purpose"):
        if not v or len(v) > 300:
            raise ActionError(doctypes.labels()[key] + ": заполните поле.")
    return v


def apply_fixes(settings: Settings, db: Database, app_id: int, actor: str, user_id: int,
                type_name: str | None, values: dict) -> None:
    with db.tx() as con:
        app = _get_for_update(con, app_id)
        if app["status"] not in ("review", "confirm"):
            raise ActionError("Поля можно менять только до отправки ответа.")
        fields = json.loads(app["fields_json"]) or {k: {"v": "", "c": "missing"} for k in doctypes.KEYS}
        changed = {}
        new_type = app["type"]
        new_conf = app["type_confidence"]
        if type_name is not None and type_name != "":
            if type_name not in doctypes.names():
                raise ActionError("Выберите тип из списка.")
            if type_name != app["type"] or app["type_confidence"] != "fixed":
                changed["type"] = type_name
            new_type, new_conf = type_name, "fixed"
        for k, v in (values or {}).items():
            if k not in doctypes.KEYS:
                raise ActionError("Неизвестное поле: " + str(k))
            if k == "sign" and v in (False, "", None, "нет"):
                fields[k] = {"v": "", "c": "missing"}
                changed[k] = ""
                continue
            clean = validate_value(k, v)
            fields[k] = {"v": clean, "c": "fixed"}
            changed[k] = clean
        if not changed:
            return
        issues = compute_issues(new_type, new_conf, fields)
        con.execute("UPDATE applications SET type = ?, type_confidence = ?, fields_json = ?, issues_json = ?, "
                    "manual = 1, handled_by = ?, updated_at = ? WHERE id = ?",
                    (new_type, new_conf, json.dumps(fields, ensure_ascii=False), json.dumps(issues, ensure_ascii=False),
                     user_id, now(), app_id))
        add_event(con, app_id, actor, "fixed", changed)
        if app["status"] == "confirm":
            if issues:
                con.execute("UPDATE applications SET status = 'review', updated_at = ? WHERE id = ?", (now(), app_id))
            else:
                if "type" in changed:
                    con.execute("UPDATE applications SET owner = ? WHERE id = ?", (doctypes.owner(new_type), app_id))
                app2 = con.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
                con.execute("UPDATE applications SET reply_text = ? WHERE id = ?", (draft_reply(settings, app2), app_id))


def resume(settings: Settings, db: Database, app_id: int, actor: str, user_id: int) -> None:
    with db.tx() as con:
        app = _get_for_update(con, app_id)
        if app["status"] != "review":
            raise ActionError("Заявление не ждёт проверки.")
        if json.loads(app["issues_json"]):
            raise ActionError("Сначала исправьте все отмеченные поля.")
        con.execute("UPDATE applications SET handled_by = ?, updated_at = ? WHERE id = ?", (user_id, now(), app_id))
        add_event(con, app_id, actor, "checked", "")
        _register(settings, con, app_id, actor)


def save_reply(db: Database, app_id: int, actor: str, text: str) -> None:
    text = (text or "").strip()
    if not text:
        raise ActionError("Текст ответа пустой.")
    if len(text) > 5000:
        raise ActionError("Ответ слишком длинный (больше 5000 символов).")
    with db.tx() as con:
        app = _get_for_update(con, app_id)
        if app["status"] != "confirm":
            raise ActionError("Ответ можно менять, пока он не отправлен.")
        if text != app["reply_text"]:
            con.execute("UPDATE applications SET reply_text = ?, updated_at = ? WHERE id = ?", (text, now(), app_id))
            add_event(con, app_id, actor, "reply_edited", "")


def mark_sent(db: Database, app_id: int, actor: str, user_id: int, text: str | None) -> dict:
    with db.tx() as con:
        app = _get_for_update(con, app_id)
        if app["status"] != "confirm":
            raise ActionError("Ответ уже отправлен или заявление не готово.")
        reply = (text if text is not None else app["reply_text"]).strip()
        if not reply:
            raise ActionError("Текст ответа пустой.")
        if len(reply) > 5000:
            raise ActionError("Ответ слишком длинный (больше 5000 символов).")
        con.execute("UPDATE applications SET status = 'sent', reply_text = ?, sent_at = ?, handled_by = ?, "
                    "updated_at = ? WHERE id = ?", (reply, now(), user_id, now(), app_id))
        add_event(con, app_id, actor, "sent", "")
        return dict(con.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone())


def mark_returned(db: Database, app_id: int, actor: str, user_id: int, message: str) -> dict:
    message = (message or "").strip()
    if len(message) < 5:
        raise ActionError("Напишите студенту, что нужно исправить.")
    if len(message) > 3000:
        raise ActionError("Сообщение слишком длинное.")
    with db.tx() as con:
        app = _get_for_update(con, app_id)
        if app["status"] in ("sent", "returned"):
            raise ActionError("Заявление уже закрыто.")
        con.execute("UPDATE applications SET status = 'returned', student_message = ?, sent_at = ?, handled_by = ?, "
                    "updated_at = ? WHERE id = ?", (message, now(), user_id, now(), app_id))
        add_event(con, app_id, actor, "returned", message[:300])
        return dict(con.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone())
