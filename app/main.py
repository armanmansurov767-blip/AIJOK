"""Веб-приложение DocAgent (FastAPI): портал студента, кабинет сотрудника, API."""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import secrets
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agent, doctypes
from .config import Settings, load_dotenv
from .db import Database, add_event, now
from .extract import ACCEPT, FileRejected, detect, extract_text, safe_filename
from .security import (RateLimiter, create_session, drop_session, drop_user_sessions, hash_password,
                       password_problem, session_user, verify_password)

log = logging.getLogger("docagent")
STATIC = Path(__file__).with_name("static")
COOKIE = "docagent_session"
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
NAME_RE = re.compile(r"^[A-Za-zА-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі' -]{1,60}$")
GROUP_RE = re.compile(r"^[A-ZА-ЯЁӘҒҚҢӨҰҮҺІ0-9][A-ZА-ЯЁӘҒҚҢӨҰҮҺІ0-9 ./-]{0,19}$")

STATUS_LABEL = {
    "received": "Принято",
    "processing": "Агент обрабатывает",
    "review": "Нужна проверка",
    "confirm": "Ждёт подтверждения",
    "sent": "Ответ отправлен",
    "returned": "Возвращено на доработку",
}
STUDENT_STATUS = {
    "received": "Принято, ждёт обработки",
    "processing": "Обрабатывается",
    "review": "Проверяет сотрудник",
    "confirm": "Сотрудник готовит ответ",
    "sent": "Ответ получен",
    "returned": "Нужно доработать",
}


def request_no(app_id: int) -> str:
    return f"З-{app_id:05d}"


class LoginIn(BaseModel):
    login: str
    password: str


class PasswordIn(BaseModel):
    old: str
    new: str


class FixIn(BaseModel):
    type: str | None = None
    fields: dict = {}


class ReplyIn(BaseModel):
    text: str


class SendIn(BaseModel):
    text: str | None = None


class ReturnIn(BaseModel):
    message: str


class UserIn(BaseModel):
    login: str
    name: str
    role: str = "staff"
    password: str


class UserPatch(BaseModel):
    active: bool | None = None
    role: str | None = None
    password: str | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        load_dotenv()
        settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    executor = ThreadPoolExecutor(max_workers=max(1, settings.workers), thread_name_prefix="docagent")
    login_limiter = RateLimiter(limit=8, window_seconds=15 * 60)
    submit_limiter = RateLimiter(limit=20, window_seconds=60 * 60)

    def run_agent(app_id: int) -> None:
        try:
            agent.process(settings, db, app_id)
        except Exception:  # noqa: BLE001
            log.exception("agent crashed on application %s", app_id)

    def schedule(app_id: int) -> None:
        if settings.sync_processing:
            run_agent(app_id)
        else:
            executor.submit(run_agent, app_id)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Заявления, которые не успели обработать до перезапуска, ставим в очередь снова.
        for row in db.all("SELECT id FROM applications WHERE status IN ('received', 'processing') ORDER BY id"):
            schedule(row["id"])
        yield
        executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="DocAgent", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.settings = settings
    app.state.db = db

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' blob: data:; frame-src 'self' blob:; object-src 'self'; "
            "style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'self'")
        if request.url.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    def ip_of(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    # ---------- auth ----------

    def current_user(request: Request):
        user = session_user(db, request.cookies.get(COOKIE))
        if user is None:
            raise HTTPException(401, "Войдите в кабинет сотрудника.")
        if request.method not in ("GET", "HEAD") and request.headers.get("x-requested-with") != "DocAgent":
            raise HTTPException(403, "Запрос отклонён.")
        return user

    def admin_user(user=Depends(current_user)):
        if user["role"] != "admin":
            raise HTTPException(403, "Нужны права администратора.")
        return user

    def actor(user) -> str:
        return "staff:" + user["login"]

    def action(fn, *args):
        try:
            return fn(*args)
        except agent.ActionError as e:
            raise HTTPException(400, str(e)) from e

    # ---------- pages ----------

    @app.get("/", include_in_schema=False)
    def page_student():
        return FileResponse(STATIC / "student.html")

    @app.get("/status/{token}", include_in_schema=False)
    def page_status(token: str):
        return FileResponse(STATIC / "student.html")

    @app.get("/staff", include_in_schema=False)
    def page_staff():
        return FileResponse(STATIC / "staff.html")

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        db.one("SELECT 1")
        return {"ok": True}

    # ---------- public API ----------

    @app.get("/api/meta")
    def meta():
        return {
            "org": settings.org_name,
            "ai": settings.ai_enabled,
            "accept": ACCEPT,
            "max_files": settings.max_files,
            "max_file_mb": settings.max_file_mb,
            "max_image_mb": settings.max_image_mb,
            "types": doctypes.names(),
            "kinds": doctypes.form_choices(),
        }

    async def _read_limited(f: UploadFile, limit: int) -> bytes:
        chunks, size = [], 0
        while True:
            chunk = await f.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise FileRejected(f"Файл «{safe_filename(f.filename or '')}» больше {limit // (1024 * 1024)} МБ.")
            chunks.append(chunk)
        return b"".join(chunks)

    @app.post("/api/applications")
    async def submit(request: Request,
                     files: list[UploadFile] = File(default=[]),
                     text: str = Form(""),
                     kind: str = Form(""),
                     surname: str = Form(""),
                     first_name: str = Form(""),
                     group: str = Form("")):
        ip = ip_of(request)
        if submit_limiter.blocked(ip):
            raise HTTPException(429, "Слишком много заявлений с этого адреса. Попробуйте через час.")
        surname = " ".join(surname.split())
        first_name = " ".join(first_name.split())
        group = " ".join(group.split()).upper()
        if not NAME_RE.match(surname):
            raise HTTPException(400, "Укажите фамилию (только буквы, до 60 символов).")
        if not NAME_RE.match(first_name):
            raise HTTPException(400, "Укажите имя (только буквы, до 60 символов).")
        if not GROUP_RE.match(group):
            raise HTTPException(400, "Укажите группу, например ИС-24/2.")
        if kind not in doctypes.all_names():
            raise HTTPException(400, "Выберите вид заявления.")
        text = text.strip()
        if len(text) > 20000:
            raise HTTPException(400, "Текст слишком длинный: больше 20 000 символов. Приложите его файлом.")
        files = [f for f in files if f.filename]
        if not files and len(text) < 10:
            raise HTTPException(400, "Напишите текст заявления или приложите файл.")
        if len(files) > settings.max_files:
            raise HTTPException(400, f"Можно приложить не больше {settings.max_files} файлов.")

        prepared = []
        total = 0
        try:
            for f in files:
                data = await _read_limited(f, settings.max_file_mb * 1024 * 1024)
                det = detect(f.filename, data)
                if det.kind == "image" and len(data) > settings.max_image_mb * 1024 * 1024:
                    raise FileRejected(f"Фото «{safe_filename(f.filename)}» больше {settings.max_image_mb} МБ. Уменьшите его.")
                total += len(data)
                if total > settings.max_total_mb * 1024 * 1024:
                    raise FileRejected(f"Все файлы вместе больше {settings.max_total_mb} МБ.")
                try:
                    extracted, pages = await run_in_threadpool(extract_text, det.kind, data)
                except FileRejected:
                    raise
                except Exception as e:  # noqa: BLE001
                    raise FileRejected(f"Не удалось открыть файл «{safe_filename(f.filename)}». Он повреждён?") from e
                if pages and pages > settings.max_pdf_pages:
                    raise FileRejected(f"В PDF «{safe_filename(f.filename)}» {pages} страниц, можно не больше {settings.max_pdf_pages}.")
                prepared.append((safe_filename(f.filename), det, data, extracted, pages))
        except FileRejected as e:
            raise HTTPException(400, str(e)) from e

        submit_limiter.hit(ip)
        token = secrets.token_urlsafe(24)
        stored = []
        for (fname, det, data, _t, _p) in prepared:
            sname = secrets.token_hex(16) + det.ext
            (settings.upload_dir / sname).write_bytes(data)
            stored.append(sname)
        form_date = datetime.now().strftime("%d.%m.%Y") if text else ""
        full_text = doctypes.compose_text(kind, surname, first_name, group, text, form_date) if text else ""
        with db.tx() as con:
            cur = con.execute(
                "INSERT INTO applications(public_token, status, student_name, student_surname, student_first, "
                "student_group, student_kind, form_date, text_input, created_at, updated_at) "
                "VALUES (?, 'received', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (token, f"{surname} {first_name}", surname, first_name, group, kind, form_date, full_text, now(), now()))
            app_id = cur.lastrowid
            for (fname, det, data, extracted, pages), sname in zip(prepared, stored):
                con.execute("INSERT INTO files(application_id, stored_name, original_name, kind, mime, size, pages, "
                            "extracted_text, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (app_id, sname, fname, det.kind, det.mime, len(data), pages, extracted, now()))
            add_event(con, app_id, "student", "submitted",
                      {"files": [p[0] for p in prepared], "text": bool(text)})
        schedule(app_id)
        return {"token": token, "status_url": f"/status/{token}", "kind": kind}

    @app.get("/api/public/{token}")
    def public_status(token: str):
        if not TOKEN_RE.match(token):
            raise HTTPException(404, "Обращение не найдено.")
        a = db.one("SELECT * FROM applications WHERE public_token = ?", (token,))
        if a is None:
            raise HTTPException(404, "Обращение не найдено.")
        files = db.all("SELECT original_name FROM files WHERE application_id = ? ORDER BY id", (a["id"],))
        registered = bool(a["reg_no"])
        return {
            "kind": a["student_kind"],
            "created_at": a["created_at"],
            "status": a["status"],
            "status_label": STUDENT_STATUS.get(a["status"], a["status"]),
            "type": a["type"] if registered else "",
            "reg_no": a["reg_no"] or "",
            "owner": a["owner"] if registered else "",
            "reply": a["reply_text"] if a["status"] == "sent" else "",
            "message": a["student_message"] if a["status"] == "returned" else "",
            "answered_at": a["sent_at"] if a["status"] in ("sent", "returned") else "",
            "files": [f["original_name"] for f in files],
            "has_text": bool(a["text_input"]),
            "name": a["student_name"],
            "group": a["student_group"],
        }

    # ---------- staff: auth ----------

    @app.post("/api/auth/login")
    def login(body: LoginIn, request: Request):
        if request.headers.get("x-requested-with") != "DocAgent":
            raise HTTPException(403, "Запрос отклонён.")
        key_ip, key_login = "ip:" + ip_of(request), "login:" + body.login.strip().lower()
        if login_limiter.blocked(key_ip) or login_limiter.blocked(key_login):
            raise HTTPException(429, "Слишком много попыток входа. Подождите 15 минут.")
        user = db.one("SELECT * FROM users WHERE login = ? AND active = 1", (body.login.strip(),))
        if user is None or not verify_password(body.password, user["password_hash"]):
            login_limiter.hit(key_ip)
            login_limiter.hit(key_login)
            raise HTTPException(401, "Неверный логин или пароль.")
        login_limiter.reset(key_login)
        token = create_session(db, user["id"], settings.session_hours)
        resp = JSONResponse({"login": user["login"], "name": user["name"], "role": user["role"]})
        resp.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=settings.secure_cookies,
                        max_age=settings.session_hours * 3600, path="/")
        return resp

    @app.post("/api/auth/logout")
    def logout(request: Request):
        drop_session(db, request.cookies.get(COOKIE))
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE, path="/")
        return resp

    @app.get("/api/auth/me")
    def me(user=Depends(current_user)):
        return {"login": user["login"], "name": user["name"], "role": user["role"]}

    @app.post("/api/auth/password")
    def change_password(body: PasswordIn, user=Depends(current_user)):
        if not verify_password(body.old, user["password_hash"]):
            raise HTTPException(400, "Старый пароль неверный.")
        problem = password_problem(body.new)
        if problem:
            raise HTTPException(400, problem)
        with db.tx() as con:
            con.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(body.new), user["id"]))
        return {"ok": True}

    # ---------- staff: applications ----------

    def _summary_row(a) -> dict:
        fields = json.loads(a["fields_json"] or "{}")
        return {
            "id": a["id"],
            "number": request_no(a["id"]),
            "status": a["status"],
            "status_label": STATUS_LABEL.get(a["status"], a["status"]),
            "type": a["type"],
            "fio": (fields.get("fio") or {}).get("v", "") or a["student_name"],
            "group": (fields.get("group") or {}).get("v", "") or a["student_group"],
            "reg_no": a["reg_no"] or "",
            "issues": len(json.loads(a["issues_json"] or "[]")),
            "manual": bool(a["manual"]),
            "reader": a["reader"],
            "created_at": a["created_at"],
            "updated_at": a["updated_at"],
        }

    @app.get("/api/staff/applications")
    def list_applications(status: str = "", q: str = "", limit: int = 200, user=Depends(current_user)):
        sql = "SELECT * FROM applications"
        args: list = []
        where = []
        if status == "open":
            where.append("status IN ('received', 'processing', 'review', 'confirm')")
        elif status == "closed":
            where.append("status IN ('sent', 'returned')")
        elif status:
            if status not in agent.STATUSES:
                raise HTTPException(400, "Неизвестный статус.")
            where.append("status = ?")
            args.append(status)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(max(1, min(limit, 1000)))
        rows = [_summary_row(a) for a in db.all(sql, tuple(args))]
        if q.strip():
            ql = q.strip().lower()
            rows = [r for r in rows if ql in " ".join([r["number"], r["fio"], r["group"], r["type"], r["reg_no"]]).lower()]
        counts = {s: 0 for s in agent.STATUSES}
        for r in db.all("SELECT status, COUNT(*) AS n FROM applications GROUP BY status"):
            counts[r["status"]] = r["n"]
        return {"items": rows, "counts": counts}

    def _get_app(app_id: int):
        a = db.one("SELECT * FROM applications WHERE id = ?", (app_id,))
        if a is None:
            raise HTTPException(404, "Заявление не найдено.")
        return a

    @app.get("/api/staff/applications/{app_id}")
    def get_application(app_id: int, user=Depends(current_user)):
        a = _get_app(app_id)
        files = db.all("SELECT id, original_name, kind, mime, size, pages, extracted_text FROM files "
                       "WHERE application_id = ? ORDER BY id", (app_id,))
        events = db.all("SELECT at, actor, action, details FROM events WHERE application_id = ? ORDER BY id", (app_id,))
        handler = db.one("SELECT name FROM users WHERE id = ?", (a["handled_by"],)) if a["handled_by"] else None
        return {
            **_summary_row(a),
            "student_name": a["student_name"],
            "student_group": a["student_group"],
            "student_kind": a["student_kind"],
            "text_input": a["text_input"],
            "doc_kind": a["doc_kind"],
            "type_confidence": a["type_confidence"],
            "fields": json.loads(a["fields_json"] or "{}"),
            "labels": doctypes.labels(),
            "required": doctypes.required(a["type"]) if a["type"] else [],
            "issues_list": json.loads(a["issues_json"] or "[]"),
            "warnings": json.loads(a["warnings_json"] or "[]"),
            "summary": a["summary"],
            "reader_note": a["reader_note"],
            "owner": a["owner"],
            "reply_text": a["reply_text"],
            "student_message": a["student_message"],
            "sent_at": a["sent_at"],
            "registered_at": a["registered_at"],
            "handled_by": handler["name"] if handler else "",
            "types": doctypes.names(),
            "files": [{"id": f["id"], "name": f["original_name"], "kind": f["kind"], "mime": f["mime"],
                       "size": f["size"], "pages": f["pages"], "text": f["extracted_text"]} for f in files],
            "events": [dict(e) for e in events],
            "public_url": f"{settings.public_url}/status/{a['public_token']}",
        }

    @app.get("/api/staff/files/{file_id}")
    def get_file(file_id: int, download: int = 0, user=Depends(current_user)):
        f = db.one("SELECT * FROM files WHERE id = ?", (file_id,))
        if f is None:
            raise HTTPException(404, "Файл не найден.")
        path = settings.upload_dir / f["stored_name"]
        if not path.is_file():
            raise HTTPException(404, "Файл не найден на диске.")
        inline = f["kind"] in ("pdf", "image") and not download
        media = f["mime"] if f["kind"] in ("pdf", "image") else "application/octet-stream"
        resp = FileResponse(path, media_type=media, filename=f["original_name"],
                            content_disposition_type="inline" if inline else "attachment")
        if f["kind"] == "pdf":
            # Встроенному просмотрщику PDF в браузере нельзя ставить строгий CSP: он перестаёт отображать файл.
            resp.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
        else:
            resp.headers["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src 'self'"
        return resp

    @app.patch("/api/staff/applications/{app_id}/fields")
    def fix_fields(app_id: int, body: FixIn, user=Depends(current_user)):
        _get_app(app_id)
        action(agent.apply_fixes, settings, db, app_id, actor(user), user["id"], body.type, body.fields)
        return get_application(app_id, user)

    @app.post("/api/staff/applications/{app_id}/resume")
    def resume(app_id: int, user=Depends(current_user)):
        _get_app(app_id)
        action(agent.resume, settings, db, app_id, actor(user), user["id"])
        return get_application(app_id, user)

    @app.put("/api/staff/applications/{app_id}/reply")
    def save_reply(app_id: int, body: ReplyIn, user=Depends(current_user)):
        _get_app(app_id)
        action(agent.save_reply, db, app_id, actor(user), body.text)
        return get_application(app_id, user)

    @app.post("/api/staff/applications/{app_id}/send")
    def send_reply(app_id: int, body: SendIn, user=Depends(current_user)):
        _get_app(app_id)
        action(agent.mark_sent, db, app_id, actor(user), user["id"], body.text)
        return get_application(app_id, user)

    @app.post("/api/staff/applications/{app_id}/return")
    def return_to_student(app_id: int, body: ReturnIn, user=Depends(current_user)):
        _get_app(app_id)
        action(agent.mark_returned, db, app_id, actor(user), user["id"], body.message)
        return get_application(app_id, user)

    @app.post("/api/staff/applications/{app_id}/reprocess")
    def reprocess(app_id: int, user=Depends(current_user)):
        a = _get_app(app_id)
        if a["status"] in ("sent", "returned", "processing"):
            raise HTTPException(400, "Это заявление нельзя переобработать сейчас.")
        with db.tx() as con:
            con.execute("UPDATE applications SET status = 'received', updated_at = ? WHERE id = ?", (now(), app_id))
            add_event(con, app_id, actor(user), "reprocess", "")
        schedule(app_id)
        return get_application(app_id, user)

    # ---------- staff: journal & stats ----------

    def _journal_rows():
        out = []
        for a in db.all("SELECT * FROM applications WHERE reg_no IS NOT NULL ORDER BY registered_at, id"):
            f = json.loads(a["fields_json"] or "{}")
            out.append({
                "reg_no": a["reg_no"], "registered_at": a["registered_at"], "number": request_no(a["id"]),
                "id": a["id"], "type": a["type"], "fio": (f.get("fio") or {}).get("v", ""),
                "group": (f.get("group") or {}).get("v", ""), "course": (f.get("course") or {}).get("v", ""),
                "date": (f.get("date") or {}).get("v", ""), "owner": a["owner"],
                "status": STATUS_LABEL.get(a["status"], a["status"]), "manual": bool(a["manual"]),
                "sent_at": a["sent_at"] or "",
            })
        return out

    @app.get("/api/staff/journal")
    def journal(format: str = "json", user=Depends(current_user)):
        rows = _journal_rows()
        if format != "csv":
            return {"items": rows}
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(["Рег. номер", "Дата регистрации", "Обращение", "Тип", "ФИО", "Группа", "Курс", "Дата документа",
                    "Ответственный", "Статус", "Ручная проверка", "Ответ отправлен"])

        def cell(v):
            s = str(v)
            return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s

        for r in rows:
            w.writerow([cell(x) for x in (r["reg_no"], r["registered_at"], r["number"], r["type"], r["fio"], r["group"],
                                          r["course"], r["date"], r["owner"], r["status"], "да" if r["manual"] else "нет",
                                          r["sent_at"])])
        return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": "attachment; filename=\"journal.csv\""})

    @app.get("/api/staff/stats")
    def stats(user=Depends(current_user)):
        total = db.one("SELECT COUNT(*) AS n FROM applications")["n"]
        by_status = {r["status"]: r["n"] for r in db.all("SELECT status, COUNT(*) AS n FROM applications GROUP BY status")}
        by_type = [dict(r) for r in db.all("SELECT type, COUNT(*) AS n FROM applications WHERE type != '' GROUP BY type ORDER BY n DESC")]
        done = db.one("SELECT COUNT(*) AS n, SUM(manual) AS m FROM applications WHERE reg_no IS NOT NULL")
        return {
            "total": total,
            "by_status": by_status,
            "by_type": by_type,
            "registered": done["n"],
            "manual": done["m"] or 0,
            "ai": settings.ai_enabled,
            "model": settings.model if settings.ai_enabled else "",
        }

    # ---------- staff: users (admin) ----------

    @app.get("/api/staff/users")
    def users(user=Depends(admin_user)):
        return {"items": [dict(r) for r in db.all("SELECT id, login, name, role, active, created_at FROM users ORDER BY id")]}

    @app.post("/api/staff/users")
    def create_user(body: UserIn, user=Depends(admin_user)):
        login_ = body.login.strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]{3,40}", login_):
            raise HTTPException(400, "Логин: 3–40 латинских букв, цифр, точек, дефисов.")
        if not body.name.strip():
            raise HTTPException(400, "Укажите имя сотрудника.")
        if body.role not in ("admin", "staff"):
            raise HTTPException(400, "Роль: admin или staff.")
        problem = password_problem(body.password)
        if problem:
            raise HTTPException(400, problem)
        if db.one("SELECT 1 FROM users WHERE login = ?", (login_,)):
            raise HTTPException(400, "Такой логин уже есть.")
        with db.tx() as con:
            con.execute("INSERT INTO users(login, name, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
                        (login_, body.name.strip()[:100], hash_password(body.password), body.role, now()))
        return users(user)

    @app.patch("/api/staff/users/{user_id}")
    def update_user(user_id: int, body: UserPatch, user=Depends(admin_user)):
        target = db.one("SELECT * FROM users WHERE id = ?", (user_id,))
        if target is None:
            raise HTTPException(404, "Сотрудник не найден.")
        if target["id"] == user["id"] and (body.active is False or (body.role and body.role != "admin")):
            raise HTTPException(400, "Нельзя отключить себя или снять с себя права администратора.")
        with db.tx() as con:
            if body.active is not None:
                con.execute("UPDATE users SET active = ? WHERE id = ?", (1 if body.active else 0, user_id))
            if body.role is not None:
                if body.role not in ("admin", "staff"):
                    raise HTTPException(400, "Роль: admin или staff.")
                con.execute("UPDATE users SET role = ? WHERE id = ?", (body.role, user_id))
            if body.password:
                problem = password_problem(body.password)
                if problem:
                    raise HTTPException(400, problem)
                con.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(body.password), user_id))
        if body.active is False or body.password:
            drop_user_sessions(db, user_id)
        return users(user)

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _exc: RequestValidationError):
        return JSONResponse({"error": "Некорректные данные запроса."}, status_code=422)

    return app
