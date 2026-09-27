"""Команды обслуживания: учётные записи и свёртки.

    python -m app.cli create-user --login operator
    python -m app.cli list-users
    python -m app.cli set-password --login operator
    python -m app.cli rollup
"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from app.core.db import init_database, session_scope
from app.core.logging import configure_logging
from app.core.security import hash_password
from app.models import User
from app.services.aggregation import rebuild_rollups


def _ask_password() -> str:
    password = getpass.getpass("Пароль: ")
    repeat = getpass.getpass("Повторите: ")
    if password != repeat:
        print("Пароли не совпадают.")
        raise SystemExit(1)
    if len(password) < 8:
        print("Пароль короче 8 символов.")
        raise SystemExit(1)
    return password


def create_user(args: argparse.Namespace) -> int:
    with session_scope() as session:
        if session.scalar(select(User).where(User.login == args.login)):
            print(f"Пользователь {args.login} уже есть.")
            return 1
        session.add(
            User(
                login=args.login,
                password_hash=hash_password(_ask_password()),
                display_name=args.name or args.login,
                profile=args.profile,
            )
        )
    print(f"Пользователь {args.login} создан.")
    return 0


def set_password(args: argparse.Namespace) -> int:
    with session_scope() as session:
        user = session.scalar(select(User).where(User.login == args.login))
        if user is None:
            print(f"Пользователь {args.login} не найден.")
            return 1
        user.password_hash = hash_password(_ask_password())
    print("Пароль изменён.")
    return 0


def list_users(_args: argparse.Namespace) -> int:
    with session_scope() as session:
        users = session.scalars(select(User).order_by(User.id)).all()
    if not users:
        print("Пользователей нет.")
        return 0
    for user in users:
        last = user.last_login_at.strftime("%d.%m.%Y %H:%M") if user.last_login_at else "не входил"
        print(f"  {user.id:>3}  {user.login:<20} {user.profile:<10} вход: {last}")
    return 0


def rollup(_args: argparse.Namespace) -> int:
    with session_scope() as session:
        result = rebuild_rollups(session)
    print(f"Свёртки обновлены: минут {result['minutes']}, часов {result['hours']}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    init_database()

    parser = argparse.ArgumentParser(description="Обслуживание UniFlow")
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create-user", help="создать пользователя")
    create.add_argument("--login", required=True)
    create.add_argument("--name")
    create.add_argument("--profile", default="ops",
                        choices=["ops", "security", "manager", "admin"])
    create.set_defaults(handler=create_user)

    password = commands.add_parser("set-password", help="сменить пароль")
    password.add_argument("--login", required=True)
    password.set_defaults(handler=set_password)

    listing = commands.add_parser("list-users", help="список пользователей")
    listing.set_defaults(handler=list_users)

    rollups = commands.add_parser("rollup", help="пересобрать свёртки")
    rollups.set_defaults(handler=rollup)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
