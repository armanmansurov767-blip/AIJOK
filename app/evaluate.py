"""Замер точности агента на размеченных примерах (папка eval/, см. eval/README.md).

Каждый пример это файл заявления и запись в eval/labels.json с правильными ответами.
Запуск с ИИ тратит запросы к API: по одному на пример.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import agent, doctypes, llm, rules
from .config import BASE_DIR, Settings
from .extract import detect, extract_text


def _norm(v: str) -> str:
    return re.sub(r"\s+", " ", (v or "").replace("ё", "е").replace("Ё", "Е")).strip(" .,;").casefold()


def _purpose_ok(pred: str, gold: str) -> bool:
    if not gold:
        return not pred
    a = set(re.findall(r"\w{4,}", _norm(pred)))
    b = set(re.findall(r"\w{4,}", _norm(gold)))
    return bool(b) and len(a & b) / len(b) >= 0.6


def field_ok(key: str, pred: str, gold: str) -> bool:
    if key == "purpose":
        return _purpose_ok(pred, gold)
    return _norm(pred) == _norm(gold)


def run(directory: str = "eval", use_ai: bool = True, limit: int = 0) -> int:
    d = Path(directory)
    if not d.is_absolute():
        d = BASE_DIR / d
    labels_path = d / "labels.json"
    if not labels_path.is_file():
        print(f"Нет файла {labels_path}. Сначала: python eval/make_eval_set.py")
        return 1
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    settings = Settings()
    if use_ai and not settings.ai_enabled:
        print("ИИ не настроен (нет ANTHROPIC_API_KEY). Запустите с --rules или задайте ключ.")
        return 1
    items = sorted(labels.items())
    if limit:
        items = items[:limit]

    per_field = {k: [0, 0] for k in doctypes.KEYS}
    type_hits = route_hits = 0
    times = []
    rows = []
    for name, gold in items:
        data = (d / name).read_bytes()
        det = detect(name, data)
        text, _ = extract_text(det.kind, data)
        doc = llm.InputDoc(name=name, kind=det.kind, mime=det.mime, data=data, text=text)
        t0 = time.monotonic()
        try:
            raw = llm.read_documents(settings, [doc], "") if use_ai else rules.read(text)
            err = ""
        except llm.ReaderError as e:
            raw, err = {"fields": {}}, str(e)
        times.append(time.monotonic() - t0)
        res = agent.normalize(raw)
        if not use_ai:
            for f in res["fields"].values():
                if f["c"] == "high":
                    f["c"] = "low"
            res["type_confidence"] = "low"
        issues = agent.compute_issues(res["type"], res["type_confidence"], res["fields"])
        gold_missing = [k for k in doctypes.required(gold["type"]) if not gold["fields"].get(k)]
        expect_review = bool(gold_missing)
        got_review = bool(issues)
        route_hits += expect_review == got_review
        type_hits += res["type"] == gold["type"]
        wrong = []
        for k in doctypes.KEYS:
            ok = field_ok(k, res["fields"][k]["v"], gold["fields"].get(k, ""))
            per_field[k][0] += ok
            per_field[k][1] += 1
            if not ok:
                wrong.append(f"{k}: «{res['fields'][k]['v']}» вместо «{gold['fields'].get(k, '')}»")
        rows.append({"file": name, "type_ok": res["type"] == gold["type"], "pred_type": res["type"],
                     "route_ok": expect_review == got_review, "wrong": wrong, "error": err,
                     "seconds": round(times[-1], 2)})
        mark = "ok " if not wrong and res["type"] == gold["type"] else "ERR"
        print(f"{mark} {name}: тип {'✓' if res['type'] == gold['type'] else '✗ ' + res['type']}"
              + (f"; {'; '.join(wrong)}" if wrong else "") + (f"; ошибка: {err}" if err else ""))

    n = len(items)
    print("\nИтог на", n, "примерах", "(ИИ: " + settings.model + ")" if use_ai else "(правила, без ИИ)")
    print(f"  тип документа: {type_hits}/{n} = {type_hits / n:.0%}")
    total_ok = total = 0
    for k, (ok, cnt) in per_field.items():
        total_ok += ok
        total += cnt
        print(f"  {doctypes.labels()[k]:<16} {ok}/{cnt} = {ok / cnt:.0%}")
    print(f"  все поля:        {total_ok}/{total} = {total_ok / total:.0%}")
    print(f"  маршрут (проверка сотрудником нужна / не нужна): {route_hits}/{n} = {route_hits / n:.0%}")
    print(f"  время на документ: среднее {sum(times) / n:.1f} с, максимум {max(times):.1f} с")
    report = d / f"report-{'ai' if use_ai else 'rules'}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    report.write_text(json.dumps({"model": settings.model if use_ai else "rules", "n": n, "type_acc": type_hits / n,
                                  "field_acc": {k: v[0] / v[1] for k, v in per_field.items()},
                                  "route_acc": route_hits / n, "avg_seconds": sum(times) / n, "rows": rows},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    print("Отчёт:", report)
    return 0
