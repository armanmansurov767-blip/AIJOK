"""Команды DocAgent.

  python -m app serve [--host 127.0.0.1] [--port 8000]   запустить сервер
  python -m app create-user --login admin --name "Имя" [--role admin]   создать сотрудника
  python -m app evaluate [--dir eval] [--rules]           замерить точность на размеченных примерах
"""
from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys

from .config import Settings, load_dotenv


def _create_user(args) -> int:
    from .db import Database, now
    from .security import hash_password, password_problem

    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    if db.one("SELECT 1 FROM users WHERE login = ?", (args.login,)):
        print(f"Сотрудник с логином {args.login} уже есть.", file=sys.stderr)
        return 1
    password = os.environ.get("DOCAGENT_NEW_PASSWORD") or getpass.getpass("Пароль: ")
    problem = password_problem(password)
    if problem:
        print(problem, file=sys.stderr)
        return 1
    if not os.environ.get("DOCAGENT_NEW_PASSWORD") and getpass.getpass("Повторите пароль: ") != password:
        print("Пароли не совпадают.", file=sys.stderr)
        return 1
    with db.tx() as con:
        con.execute("INSERT INTO users(login, name, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
                    (args.login, args.name, hash_password(password), args.role, now()))
    print(f"Создан сотрудник {args.login} ({args.role}).")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="python -m app", description="DocAgent")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="запустить веб-сервер")
    s.add_argument("--host", default=os.environ.get("DOCAGENT_HOST", "127.0.0.1"))
    s.add_argument("--port", type=int, default=int(os.environ.get("PORT", os.environ.get("DOCAGENT_PORT", "8000"))))

    u = sub.add_parser("create-user", help="создать сотрудника")
    u.add_argument("--login", required=True)
    u.add_argument("--name", required=True)
    u.add_argument("--role", choices=["admin", "staff"], default="staff")

    e = sub.add_parser("evaluate", help="замер точности на размеченных примерах")
    e.add_argument("--dir", default="eval")
    e.add_argument("--rules", action="store_true", help="читать правилами, без ИИ")
    e.add_argument("--limit", type=int, default=0)

    args = p.parse_args(argv)
    if args.cmd == "serve":
        import uvicorn

        from .main import create_app

        uvicorn.run(create_app(), host=args.host, port=args.port, proxy_headers=True)
        return 0
    if args.cmd == "create-user":
        return _create_user(args)
    if args.cmd == "evaluate":
        from .evaluate import run

        return run(args.dir, use_ai=not args.rules, limit=args.limit)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
