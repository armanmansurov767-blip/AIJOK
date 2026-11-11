"""Справочник типов документов (app/doc_types.json)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

PATH = Path(__file__).with_name("doc_types.json")

KEYS = ["fio", "group", "course", "purpose", "date", "sign"]


@lru_cache(maxsize=1)
def _load() -> dict:
    data = json.loads(PATH.read_text(encoding="utf-8"))
    names = [t["name"] for t in data["types"]]
    if len(set(names)) != len(names):
        raise ValueError("В doc_types.json повторяются названия типов")
    for t in data["types"]:
        bad = [k for k in t.get("required", []) if k not in KEYS]
        if bad:
            raise ValueError(f"Тип «{t['name']}»: неизвестные поля {bad}")
    return data


def labels() -> dict:
    return dict(_load()["fields"])


def other_name() -> str:
    return _load()["other"]["name"]


def names() -> list[str]:
    return [t["name"] for t in _load()["types"]]


def all_names() -> list[str]:
    return names() + [other_name()]


def get(name: str) -> dict | None:
    for t in _load()["types"]:
        if t["name"] == name:
            return t
    return None


def owner(name: str) -> str:
    t = get(name)
    return t["owner"] if t else _load()["other"]["owner"]


def required(name: str) -> list[str]:
    t = get(name)
    return list(t["required"]) if t else list(KEYS)


def reply_template(name: str) -> str:
    t = get(name)
    if t and t.get("reply"):
        return t["reply"]
    return ("Здравствуйте, {name}!\n\nВаш документ «{type}» принят и зарегистрирован под номером {no}. "
            "Его рассмотрит: {owner}.\n\n{org}")


def keyword_table() -> list[tuple[str, list[str]]]:
    return [(t["name"], [k.lower() for k in t.get("keywords", [])]) for t in _load()["types"]]


def public_list() -> list[dict]:
    return [{"name": t["name"], "owner": t["owner"], "required": t["required"]} for t in _load()["types"]]
