"""Настройки DocAgent. Всё берётся из переменных окружения (или файла .env рядом с проектом).

Ключи и пароли в коде не хранятся.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path = BASE_DIR / ".env") -> None:
    """Минимальный загрузчик .env: KEY=VALUE, без перезаписи уже заданных переменных."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on", "да")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _ai_default() -> bool:
    mode = os.environ.get("DOCAGENT_AI", "auto").strip().lower()
    if mode in ("off", "0", "false", "no"):
        return False
    if mode in ("on", "1", "true", "yes"):
        return True
    # auto: включаем, если видны учётные данные Anthropic
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    return (Path.home() / ".config" / "anthropic").is_dir()


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("DOCAGENT_DATA_DIR", BASE_DIR / "data")))
    org_name: str = field(default_factory=lambda: os.environ.get("DOCAGENT_ORG_NAME", "Учебная часть"))
    public_url: str = field(default_factory=lambda: os.environ.get("DOCAGENT_PUBLIC_URL", "http://localhost:8000").rstrip("/"))

    ai_enabled: bool = field(default_factory=_ai_default)
    model: str = field(default_factory=lambda: os.environ.get("DOCAGENT_MODEL", "claude-opus-5-5"))
    effort: str = field(default_factory=lambda: os.environ.get("DOCAGENT_EFFORT", "medium"))
    ai_timeout: int = field(default_factory=lambda: _int("DOCAGENT_AI_TIMEOUT", 180))

    max_files: int = field(default_factory=lambda: _int("DOCAGENT_MAX_FILES", 5))
    max_file_mb: int = field(default_factory=lambda: _int("DOCAGENT_MAX_FILE_MB", 15))
    max_image_mb: int = 5          # предел API для одного изображения
    max_total_mb: int = field(default_factory=lambda: _int("DOCAGENT_MAX_TOTAL_MB", 25))
    max_text_chars: int = field(default_factory=lambda: _int("DOCAGENT_MAX_TEXT_CHARS", 150_000))
    max_pdf_pages: int = field(default_factory=lambda: _int("DOCAGENT_MAX_PDF_PAGES", 100))

    secure_cookies: bool = field(default_factory=lambda: _bool("DOCAGENT_SECURE_COOKIES", False))
    session_hours: int = field(default_factory=lambda: _int("DOCAGENT_SESSION_HOURS", 12))
    workers: int = field(default_factory=lambda: _int("DOCAGENT_WORKERS", 2))
    # В тестах обработка идёт сразу, без фонового потока.
    sync_processing: bool = False

    @property
    def db_path(self) -> Path:
        return self.data_dir / "docagent.sqlite3"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
