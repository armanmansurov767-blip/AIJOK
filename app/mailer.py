"""Отправка писем студентам. Без настроек SMTP письмо сохраняется в outbox и видно на странице статуса."""
from __future__ import annotations

import logging
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from .config import Settings
from .db import Database, now

log = logging.getLogger("docagent.mail")

EMAIL_RE = re.compile(r"^[^@\s<>\"',;]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$")


def valid_email(v: str) -> bool:
    return bool(EMAIL_RE.match(v or ""))


def send(settings: Settings, db: Database, app_id: int | None, to: str, subject: str, body: str) -> str:
    """Возвращает статус: sent | not_configured | failed | no_address."""
    if not to or not valid_email(to):
        status, error = "no_address", ""
    elif not settings.smtp_enabled:
        status, error = "not_configured", ""
    else:
        msg = EmailMessage()
        msg["From"] = formataddr((settings.org_name, settings.smtp_from))
        msg["To"] = to
        msg["Subject"] = subject.replace("\n", " ")[:200]
        msg.set_content(body)
        try:
            if settings.smtp_ssl:
                server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30,
                                          context=ssl.create_default_context())
            else:
                server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)
                server.starttls(context=ssl.create_default_context())
            with server:
                if settings.smtp_user:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(msg)
            status, error = "sent", ""
        except (smtplib.SMTPException, OSError) as e:
            log.warning("SMTP send failed: %s", e)
            status, error = "failed", str(e)[:300]
    with db.tx() as con:
        con.execute("INSERT INTO outbox(application_id, to_email, subject, body, status, error, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)", (app_id, to or "", subject, body, status, error, now()))
    return status
