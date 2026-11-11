"""Пароли, сессии сотрудников, ограничение частоты запросов."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from .db import Database, now

_N, _R, _P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt$%d$%d$%d$%s$%s" % (_N, _R, _P, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, dk_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(dk_b64)
        dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected))
        return hmac.compare_digest(dk, expected)
    except (ValueError, TypeError):
        return False


def password_problem(password: str) -> str:
    if len(password) < 10:
        return "Пароль должен быть не короче 10 символов."
    if password.lower() == password or not any(c.isdigit() for c in password):
        return "Пароль должен содержать заглавную букву и цифру."
    return ""


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def create_session(db: Database, user_id: int, hours: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(hours=hours)).replace(microsecond=0).isoformat()
    with db.tx() as con:
        con.execute("DELETE FROM sessions WHERE expires_at < ?", (now(),))
        con.execute("INSERT INTO sessions(token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                    (_token_hash(token), user_id, now(), expires))
    return token


def session_user(db: Database, token: str | None):
    if not token or len(token) > 200:
        return None
    return db.one(
        "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = ? AND s.expires_at > ? AND u.active = 1",
        (_token_hash(token), now()))


def drop_session(db: Database, token: str | None) -> None:
    if token:
        with db.tx() as con:
            con.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def drop_user_sessions(db: Database, user_id: int) -> None:
    with db.tx() as con:
        con.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


class RateLimiter:
    """Простое ограничение «не больше N событий за окно» в памяти процесса."""

    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def _trim(self, q: deque, t: float) -> None:
        while q and q[0] <= t - self.window:
            q.popleft()

    def blocked(self, key: str) -> bool:
        t = time.monotonic()
        with self._lock:
            q = self._hits[key]
            self._trim(q, t)
            return len(q) >= self.limit

    def hit(self, key: str) -> None:
        t = time.monotonic()
        with self._lock:
            q = self._hits[key]
            self._trim(q, t)
            q.append(t)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)
