"""База данных SQLite: схема и небольшие помощники."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  login TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin', 'staff')),
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS applications (
  id INTEGER PRIMARY KEY,
  public_token TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL,
  student_email TEXT NOT NULL DEFAULT '',
  student_name TEXT NOT NULL DEFAULT '',
  text_input TEXT NOT NULL DEFAULT '',
  doc_kind TEXT NOT NULL DEFAULT '',
  type TEXT NOT NULL DEFAULT '',
  type_confidence TEXT NOT NULL DEFAULT '',
  fields_json TEXT NOT NULL DEFAULT '{}',
  summary TEXT NOT NULL DEFAULT '',
  warnings_json TEXT NOT NULL DEFAULT '[]',
  issues_json TEXT NOT NULL DEFAULT '[]',
  reader TEXT NOT NULL DEFAULT '',
  reader_note TEXT NOT NULL DEFAULT '',
  manual INTEGER NOT NULL DEFAULT 0,
  reg_no TEXT UNIQUE,
  registered_at TEXT,
  owner TEXT NOT NULL DEFAULT '',
  reply_text TEXT NOT NULL DEFAULT '',
  student_message TEXT NOT NULL DEFAULT '',
  sent_at TEXT,
  handled_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_app_status ON applications(status);
CREATE TABLE IF NOT EXISTS files (
  id INTEGER PRIMARY KEY,
  application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
  stored_name TEXT NOT NULL,
  original_name TEXT NOT NULL,
  kind TEXT NOT NULL,
  mime TEXT NOT NULL,
  size INTEGER NOT NULL,
  pages INTEGER,
  extracted_text TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
  at TEXT NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  details TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_events_app ON events(application_id);
CREATE TABLE IF NOT EXISTS counters (
  name TEXT PRIMARY KEY,
  value INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS outbox (
  id INTEGER PRIMARY KEY,
  application_id INTEGER REFERENCES applications(id) ON DELETE SET NULL,
  to_email TEXT NOT NULL,
  subject TEXT NOT NULL,
  body TEXT NOT NULL,
  status TEXT NOT NULL,
  error TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()   # одна запись за раз; чтение параллельно
        with self.connect() as con:
            con.executescript(SCHEMA)

    def _open(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA busy_timeout = 30000")
        return con

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        con = self._open()
        try:
            yield con
        finally:
            con.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Транзакция на запись."""
        with self._lock:
            con = self._open()
            try:
                con.execute("BEGIN IMMEDIATE")
                yield con
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise
            finally:
                con.close()

    def one(self, sql: str, args: tuple = ()) -> sqlite3.Row | None:
        with self.connect() as con:
            return con.execute(sql, args).fetchone()

    def all(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute(sql, args).fetchall()


def next_counter(con: sqlite3.Connection, name: str) -> int:
    con.execute("INSERT INTO counters(name, value) VALUES (?, 0) ON CONFLICT(name) DO NOTHING", (name,))
    con.execute("UPDATE counters SET value = value + 1 WHERE name = ?", (name,))
    return con.execute("SELECT value FROM counters WHERE name = ?", (name,)).fetchone()[0]


def add_event(con: sqlite3.Connection, app_id: int, actor: str, action: str, details: Any = "") -> None:
    if not isinstance(details, str):
        details = json.dumps(details, ensure_ascii=False)
    con.execute("INSERT INTO events(application_id, at, actor, action, details) VALUES (?, ?, ?, ?, ?)",
                (app_id, now(), actor, action, details))
