"""Чтение без ИИ: правила и регулярные выражения.

Используется, когда ИИ выключен или недоступен. Всё, что найдено правилами, помечается
как «low»: такие заявления всегда проверяет сотрудник.
"""
from __future__ import annotations

import re

from . import doctypes

CYR = "А-ЯЁ"
cyr = "а-яё"

_RE_GROUP = re.compile(r"групп[ыаеу]?\s*[:№]?\s*([%sA-Z]{1,6}\s?-?\s?\d{1,3}(?:\s?[/-]\s?\d{1,2})?)" % CYR, re.I)
_RE_GROUP_BARE = re.compile(r"\b([%s]{1,5}-\d{2,3}(?:/\d{1,2})?)\b" % CYR)
_RE_COURSE = re.compile(r"(\d)\s*(?:-?(?:го|й|ого))?\s*курс", re.I)
_RE_COURSE_WORD = re.compile(r"(перв|втор|трет|четв[её]рт|пят|шест)\w*\s+курс", re.I)
_RE_DATE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b")
_RE_FIO = re.compile(r"\b([%s][%s]+(?:-[%s][%s]+)?)\s+([%s][%s]+)\s+([%s][%s]+(?:вич|вна|чна|ична|улы|кызы|оглы|қызы))\b"
                     % (CYR, cyr, CYR, cyr, CYR, cyr, CYR, cyr))
_RE_FIO2 = re.compile(r"(?:от\s+)?(?:студент\w*|обучающ\w*)[^\n]{0,40}?\n?\s*([%s][%s]+\s+[%s][%s]+(?:\s+[%s][%s]+)?)"
                      % (CYR, cyr, CYR, cyr, CYR, cyr))
_RE_PURPOSE = re.compile(r"((?:в связи с|по причине|по семейным|по состоянию|для предоставления|для)\s[^.\n]{3,200})", re.I)
_RE_PROSHU = re.compile(r"(прошу[^.\n]{3,300})", re.I)
_RE_SIGN = re.compile(r"подпис\w*\s*[:_]*\s*([^\s_][^\n]{0,40})", re.I)

_WORD_NUM = {"перв": "1", "втор": "2", "трет": "3", "четв": "4", "пят": "5", "шест": "6"}

# Склонение ФИО в «от кого»: Садыкова Нурлана Ерболатовича -> не исправляем, просто помечаем low.


def _field(value: str) -> dict:
    value = (value or "").strip(" ,.;:")
    return {"value": value, "confidence": "low" if value else "missing"}


def guess_type(text: str) -> tuple[str, str]:
    low = text.lower()
    best, score = doctypes.other_name(), 0
    for name, words in doctypes.keyword_table():
        s = sum(low.count(w) for w in words)
        if s > score:
            best, score = name, s
    return best, "low"


def read(text: str) -> dict:
    """Возвращает словарь того же вида, что и ответ модели."""
    t = text or ""
    group = ""
    m = _RE_GROUP.search(t) or _RE_GROUP_BARE.search(t)
    if m:
        group = re.sub(r"\s+", "", m.group(1)).upper()

    course = ""
    m = _RE_COURSE.search(t)
    if m:
        course = m.group(1)
    else:
        m = _RE_COURSE_WORD.search(t)
        if m:
            for k, v in _WORD_NUM.items():
                if m.group(1).lower().startswith(k):
                    course = v

    date = ""
    dates = _RE_DATE.findall(t)
    if dates:
        d, mo, y = dates[-1]
        date = f"{int(d):02d}.{int(mo):02d}.{y}"

    fio = ""
    m = _RE_FIO.search(t)
    if m:
        fio = " ".join(m.groups())
    else:
        m = _RE_FIO2.search(t)
        if m:
            fio = m.group(1)

    purpose = ""
    m = _RE_PURPOSE.search(t)
    if m:
        purpose = m.group(1)
    else:
        m = _RE_PROSHU.search(t)
        if m:
            purpose = m.group(1)

    sign = ""
    m = _RE_SIGN.search(t)
    if m and re.search(r"[%s%sA-Za-z]" % (CYR, cyr), m.group(1)):
        sign = "есть"

    type_name, type_conf = guess_type(t)
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    summary = (purpose or (lines[0] if lines else ""))[:200]
    return {
        "doc_kind": "заявление" if "заявлен" in t.lower() else "иной документ",
        "type": type_name,
        "type_confidence": type_conf,
        "fields": {
            "fio": _field(fio),
            "group": _field(group),
            "course": _field(course),
            "purpose": _field(purpose),
            "date": _field(date),
            "sign": _field(sign),
        },
        "summary": summary,
        "warnings": ["Документ прочитан правилами без ИИ: проверьте все поля."],
    }
