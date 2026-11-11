"""Генерирует набор вымышленных размеченных заявлений для замера точности.

  .venv/bin/python eval/make_eval_set.py

Создаёт 30 файлов (TXT, DOCX, RTF) и labels.json. Все люди и данные вымышлены.
Свои настоящие (обезличенные) примеры можно добавить в эту же папку и в labels.json вручную.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent

# (именительный, родительный, пол)
PEOPLE = [
    ("Садыков Нурлан Ерболатович", "Садыкова Нурлана Ерболатовича", "м"),
    ("Тестова Айдана Ерлановна", "Тестовой Айданы Ерлановны", "ж"),
    ("Образцов Данияр Маратович", "Образцова Данияра Маратовича", "м"),
    ("Примерова Мария Сергеевна", "Примеровой Марии Сергеевны", "ж"),
    ("Демонстров Ерлан Бауыржанович", "Демонстрова Ерлана Бауыржановича", "м"),
    ("Условная Камила Тимуровна", "Условной Камилы Тимуровны", "ж"),
    ("Пробный Арсений Олегович", "Пробного Арсения Олеговича", "м"),
    ("Макетова Дана Асхатовна", "Макетовой Даны Асхатовны", "ж"),
    ("Черновиков Тимур Русланович", "Черновикова Тимура Руслановича", "м"),
    ("Шаблонова Алина Викторовна", "Шаблоновой Алины Викторовны", "ж"),
    ("Эскизов Руслан Каиратович", "Эскизова Руслана Каиратовича", "м"),
    ("Набросова Жанна Ильинична", "Набросовой Жанны Ильиничны", "ж"),
]
GROUPS = ["ИС-24/2", "ПО-22", "ЭК-31", "ЮР-11", "БД-23/1", "ИС-26/23", "ДМ-24/3"]

CASES = [
    ("Справка с места учёбы", "Начальнику учебной части", "Прошу выдать мне справку с места учёбы {p}.",
     ["для предоставления по месту требования", "для предоставления в военкомат", "для оформления социальной выплаты"]),
    ("Академический отпуск", "Декану факультета", "Прошу предоставить мне академический отпуск {p}.",
     ["по семейным обстоятельствам", "по состоянию здоровья", "в связи с призывом на военную службу"]),
    ("Пересдача экзамена", "Декану факультета", "Прошу разрешить мне пересдачу экзамена по дисциплине «Базы данных» {p}.",
     ["в связи с совпадением двух экзаменов по расписанию", "в связи с болезнью в день экзамена"]),
    ("Материальная помощь", "Начальнику студенческого отдела", "Прошу рассмотреть вопрос об оказании мне материальной помощи {p}.",
     ["в связи с трудным материальным положением", "в связи с утратой кормильца"]),
    ("Место в общежитии", "Начальнику студенческого отдела", "Прошу предоставить мне место в общежитии {p}.",
     ["в связи с проживанием в другом городе", "в связи с переездом семьи"]),
    ("Перевод", "Декану факультета", "Прошу перевести меня в другую группу {p}.",
     ["в связи с изменением графика работы", "в связи с переводом на другую специализацию"]),
    ("Индивидуальный график обучения", "Начальнику учебной части", "Прошу установить мне индивидуальный график обучения {p}.",
     ["в связи с участием в спортивных сборах", "в связи с работой по специальности"]),
]


def render(case, person, group, course, purpose, date, signed, variant) -> str:
    type_name, addressee, body, _ = case
    nom, gen, sex = person
    studword = "студента" if sex == "м" else "студентки"
    lines = [addressee]
    if variant == 0:
        lines += [f"от {studword} группы {group}, {course} курса", gen]
    elif variant == 1:
        lines += [f"{studword.capitalize()} {course} курса группы {group}", nom]
    else:
        lines += [f"от {gen}, {studword} {course} курса, группа {group}"]
    lines += ["", "ЗАЯВЛЕНИЕ", "", body.format(p=purpose), ""]
    tail = f"Дата: {date}" if date else "Дата: ________"
    surname, first = nom.split()[0], nom.split()[1]
    tail += f"        Подпись: {first[0]}. {surname}" if signed else "        Подпись: ________"
    lines.append(tail)
    return "\n".join(lines)


def write_docx(path: Path, text: str) -> None:
    import docx

    d = docx.Document()
    for line in text.split("\n"):
        d.add_paragraph(line)
    d.save(path)


def write_rtf(path: Path, text: str) -> None:
    def enc(s: str) -> str:
        out = []
        for ch in s:
            code = ord(ch)
            out.append(ch if code < 128 else "\\u%d?" % (code if code < 32768 else code - 65536))
        return "".join(out)
    body = "\\par\n".join(enc(line) for line in text.split("\n"))
    path.write_text("{\\rtf1\\ansi\\deff0 {\\fonttbl {\\f0 Times New Roman;}}\\f0\\fs24\n" + body + "\\par\n}", encoding="ascii")


def main() -> None:
    rnd = random.Random(2026)
    labels = {}
    for i in range(30):
        case = CASES[i % len(CASES)]
        person = PEOPLE[i % len(PEOPLE)]
        group = rnd.choice(GROUPS)
        course = str(rnd.randint(1, 4))
        purpose = rnd.choice(case[3])
        date = f"{rnd.randint(1, 28):02d}.{rnd.randint(9, 11):02d}.2026"
        signed = True
        # каждый пятый без даты, каждый седьмой без подписи
        if i % 5 == 4:
            date = ""
        if i % 7 == 6:
            signed = False
        text = render(case, person, group, course, purpose, date, signed, i % 3)
        ext = [".txt", ".docx", ".rtf"][i % 3]
        name = f"{i + 1:02d}{ext}"
        path = HERE / name
        if ext == ".txt":
            path.write_text(text, encoding="utf-8")
        elif ext == ".docx":
            write_docx(path, text)
        else:
            write_rtf(path, text)
        labels[name] = {
            "type": case[0],
            "fields": {"fio": person[0], "group": group, "course": course, "purpose": purpose,
                       "date": date, "sign": "есть" if signed else ""},
        }
    (HERE / "labels.json").write_text(json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Готово: {len(labels)} примеров в {HERE}")


if __name__ == "__main__":
    main()
