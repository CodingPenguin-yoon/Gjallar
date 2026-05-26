"""User service functions and local account CLI."""

from __future__ import annotations

import argparse
import getpass
import os
import re
import sys
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.auth.passwords import hash_password, verify_password
from app.auth.roles import VALID_ROLES, AuthenticatedUser, normalize_role
from app.db.models import UserRecord
from app.db.session import session_scope

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.@-]{1,80}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_username(username: str) -> str:
    normalized = str(username or "").strip()
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise ValueError("Username must be 1-80 characters using letters, numbers, dot, dash, underscore, or @")
    return normalized


def actor_from_user(row: UserRecord) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=str(row.user_id),
        username=str(row.username),
        role=normalize_role(row.role),
    )


def create_user(*, username: str, password: str, role: str, enabled: bool = True) -> AuthenticatedUser:
    normalized_username = normalize_username(username)
    normalized_role = normalize_role(role)
    password_hash = hash_password(password)
    now = _now()
    with session_scope() as session:
        existing = session.scalar(select(UserRecord).where(UserRecord.username == normalized_username))
        if existing is not None:
            raise ValueError(f"User already exists: {normalized_username}")
        row = UserRecord(
            user_id=f"user_{uuid.uuid4().hex}",
            username=normalized_username,
            password_hash=password_hash,
            role=normalized_role,
            enabled=enabled,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.flush()
        return actor_from_user(row)


def create_admin(*, username: str, password: str) -> AuthenticatedUser:
    return create_user(username=username, password=password, role="admin", enabled=True)


def authenticate_user(*, username: str, password: str) -> AuthenticatedUser | None:
    try:
        normalized_username = normalize_username(username)
    except ValueError:
        return None

    with session_scope() as session:
        row = session.scalar(select(UserRecord).where(UserRecord.username == normalized_username))
        if row is None or row.enabled is not True:
            return None
        if not verify_password(password, row.password_hash):
            return None
        row.last_login_at = _now()
        row.updated_at = row.last_login_at
        session.flush()
        return actor_from_user(row)


def _password_from_args(args: argparse.Namespace) -> str:
    if args.password:
        return str(args.password)
    if args.password_env:
        value = os.getenv(args.password_env)
        if value:
            return value
        raise SystemExit(f"Environment variable {args.password_env} is empty or unset")
    first = getpass.getpass("Password: ")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        raise SystemExit("Passwords do not match")
    return first


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gjallar local user administration")
    subcommands = parser.add_subparsers(dest="command", required=True)

    create_admin_parser = subcommands.add_parser("create-admin", help="Create the first local admin user")
    create_admin_parser.add_argument("--username", required=True)
    create_admin_parser.add_argument("--password", help="Password value. Prefer prompt or --password-env outside tests.")
    create_admin_parser.add_argument("--password-env", help="Environment variable containing the password")

    create_user_parser = subcommands.add_parser("create-user", help="Create a local user with a selected role")
    create_user_parser.add_argument("--username", required=True)
    create_user_parser.add_argument("--role", required=True, choices=VALID_ROLES)
    create_user_parser.add_argument("--password", help="Password value. Prefer prompt or --password-env outside tests.")
    create_user_parser.add_argument("--password-env", help="Environment variable containing the password")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "create-admin":
        actor = create_admin(username=args.username, password=_password_from_args(args))
        print(f"created admin user {actor.username} ({actor.user_id})")
        return 0
    if args.command == "create-user":
        actor = create_user(username=args.username, password=_password_from_args(args), role=args.role)
        print(f"created {actor.role} user {actor.username} ({actor.user_id})")
        return 0
    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
