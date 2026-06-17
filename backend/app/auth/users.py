"""User service functions and local account CLI."""

from __future__ import annotations

import argparse
import getpass
import os
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select, text, update

from app.auth.passwords import hash_password, verify_password
from app.auth.roles import VALID_ROLES, AuthenticatedUser, normalize_role
from app.db.models import SessionRecord, UserRecord
from app.db.session import session_scope

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.@-]{1,80}$")
BOOTSTRAP_ADMIN_USERNAME_ENV = "GJALLAR_BOOTSTRAP_ADMIN_USERNAME"
BOOTSTRAP_ADMIN_PASSWORD_ENV = "GJALLAR_BOOTSTRAP_ADMIN_PASSWORD"


@dataclass(frozen=True)
class UserSummary:
    user_id: str
    username: str
    role: str
    enabled: bool
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None


@dataclass(frozen=True)
class UserOperationResult:
    user: AuthenticatedUser
    revoked_sessions: int = 0
    current_session_preserved: bool = False


@dataclass(frozen=True)
class BootstrapAdminResult:
    username: str | None
    status: str
    created: bool = False


class UserNotFoundError(ValueError):
    """Raised when an account operation targets a missing local user."""


class DuplicateUserError(ValueError):
    """Raised when an account operation would create a duplicate username."""


class LastEnabledAdminError(ValueError):
    """Raised when an account operation would remove the last enabled admin."""


class CurrentPasswordInvalidError(ValueError):
    """Raised when a self-service password change fails current-password verification."""


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


def _validated_password(password: str) -> str:
    value = str(password or "")
    if not value:
        raise ValueError("Password must not be empty")
    return value


def _user_summary(row: UserRecord) -> UserSummary:
    return UserSummary(
        user_id=str(row.user_id),
        username=str(row.username),
        role=normalize_role(row.role),
        enabled=bool(row.enabled),
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_login_at=row.last_login_at,
    )


def _get_user_or_raise(session, username: str) -> UserRecord:
    normalized_username = normalize_username(username)
    row = session.scalar(select(UserRecord).where(UserRecord.username == normalized_username))
    if row is None:
        raise UserNotFoundError(f"Unknown user: {normalized_username}")
    return row


def _enabled_admin_count(session) -> int:
    count = session.scalar(
        select(func.count())
        .select_from(UserRecord)
        .where(UserRecord.role == "admin")
        .where(UserRecord.enabled.is_(True))
    )
    return int(count or 0)


def _is_enabled_admin(row: UserRecord) -> bool:
    return bool(row.enabled) and normalize_role(row.role) == "admin"


def _serialize_enabled_admin_guard(session) -> None:
    if session.get_bind().dialect.name == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))
        return
    session.scalars(
        select(UserRecord)
        .where(UserRecord.role == "admin")
        .where(UserRecord.enabled.is_(True))
        .with_for_update()
    ).all()


def _ensure_not_last_enabled_admin(session, row: UserRecord, *, action: str) -> None:
    if not _is_enabled_admin(row):
        return
    if _enabled_admin_count(session) <= 1:
        raise LastEnabledAdminError(f"Cannot {action} the last enabled admin user: {row.username}")


def _revoke_active_sessions(session, *, user_id: str, revoked_at: datetime) -> int:
    result = session.execute(
        update(SessionRecord)
        .where(SessionRecord.user_id == user_id)
        .where(SessionRecord.revoked_at.is_(None))
        .where(SessionRecord.expires_at > revoked_at)
        .values(revoked_at=revoked_at)
    )
    return max(int(result.rowcount or 0), 0)


def _revoke_other_active_sessions(
    session,
    *,
    user_id: str,
    revoked_at: datetime,
    current_session_id: str | None,
) -> int:
    query = (
        update(SessionRecord)
        .where(SessionRecord.user_id == user_id)
        .where(SessionRecord.revoked_at.is_(None))
        .where(SessionRecord.expires_at > revoked_at)
    )
    if current_session_id:
        query = query.where(SessionRecord.session_id != current_session_id)
    result = session.execute(query.values(revoked_at=revoked_at))
    return max(int(result.rowcount or 0), 0)


def create_user(*, username: str, password: str, role: str, enabled: bool = True) -> AuthenticatedUser:
    normalized_username = normalize_username(username)
    normalized_role = normalize_role(role)
    password_hash = hash_password(_validated_password(password))
    now = _now()
    with session_scope() as session:
        existing = session.scalar(select(UserRecord).where(UserRecord.username == normalized_username))
        if existing is not None:
            raise DuplicateUserError(f"User already exists: {normalized_username}")
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


def _bootstrap_admin_credentials_from_env() -> tuple[str, str] | None:
    username = os.getenv(BOOTSTRAP_ADMIN_USERNAME_ENV)
    password = os.getenv(BOOTSTRAP_ADMIN_PASSWORD_ENV)
    username_configured = username is not None and bool(str(username).strip())
    password_configured = password is not None and bool(str(password))
    if not username_configured and not password_configured:
        return None
    if not username_configured:
        raise ValueError(f"{BOOTSTRAP_ADMIN_USERNAME_ENV} is required when {BOOTSTRAP_ADMIN_PASSWORD_ENV} is set")
    if not password_configured:
        raise ValueError(f"{BOOTSTRAP_ADMIN_PASSWORD_ENV} is required when {BOOTSTRAP_ADMIN_USERNAME_ENV} is set")
    return normalize_username(str(username)), _validated_password(str(password))


def bootstrap_admin_from_env() -> BootstrapAdminResult:
    """Create the first configured admin account without changing existing users."""
    credentials = _bootstrap_admin_credentials_from_env()
    if credentials is None:
        return BootstrapAdminResult(username=None, status="not_configured")
    username, password = credentials
    now = _now()
    with session_scope() as session:
        existing = session.scalar(select(UserRecord).where(UserRecord.username == username))
        if existing is not None:
            if _is_enabled_admin(existing):
                return BootstrapAdminResult(username=username, status="already_exists")
            raise ValueError(
                f"{BOOTSTRAP_ADMIN_USERNAME_ENV} targets an existing user that is not an enabled admin: {username}"
            )
        row = UserRecord(
            user_id=f"user_{uuid.uuid4().hex}",
            username=username,
            password_hash=hash_password(password),
            role="admin",
            enabled=True,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.flush()
        return BootstrapAdminResult(username=username, status="created", created=True)


def list_users() -> list[UserSummary]:
    with session_scope() as session:
        rows = session.scalars(select(UserRecord).order_by(UserRecord.username)).all()
        return [_user_summary(row) for row in rows]


def get_user_summary(*, username: str) -> UserSummary:
    with session_scope() as session:
        return _user_summary(_get_user_or_raise(session, username))


def set_user_role(*, username: str, role: str) -> AuthenticatedUser:
    normalized_role = normalize_role(role)
    now = _now()
    with session_scope() as session:
        if normalized_role != "admin":
            _serialize_enabled_admin_guard(session)
        row = _get_user_or_raise(session, username)
        if normalized_role != "admin":
            _ensure_not_last_enabled_admin(session, row, action="demote")
        row.role = normalized_role
        row.updated_at = now
        session.flush()
        return actor_from_user(row)


def disable_user(*, username: str) -> UserOperationResult:
    now = _now()
    with session_scope() as session:
        _serialize_enabled_admin_guard(session)
        row = _get_user_or_raise(session, username)
        _ensure_not_last_enabled_admin(session, row, action="disable")
        row.enabled = False
        row.updated_at = now
        revoked_sessions = _revoke_active_sessions(session, user_id=row.user_id, revoked_at=now)
        session.flush()
        return UserOperationResult(user=actor_from_user(row), revoked_sessions=revoked_sessions)


def reset_password(*, username: str, password: str) -> UserOperationResult:
    now = _now()
    password_hash = hash_password(_validated_password(password))
    with session_scope() as session:
        row = _get_user_or_raise(session, username)
        row.password_hash = password_hash
        row.updated_at = now
        revoked_sessions = _revoke_active_sessions(session, user_id=row.user_id, revoked_at=now)
        session.flush()
        return UserOperationResult(user=actor_from_user(row), revoked_sessions=revoked_sessions)


def change_own_password(
    *,
    actor: AuthenticatedUser,
    current_password: str,
    new_password: str,
    current_session_id: str | None,
) -> UserOperationResult:
    now = _now()
    validated_new_password = _validated_password(new_password)
    with session_scope() as session:
        row = session.get(UserRecord, actor.user_id)
        if row is None or row.enabled is not True:
            raise UserNotFoundError("Unknown user")
        if not verify_password(current_password, row.password_hash):
            raise CurrentPasswordInvalidError("Current password is invalid")
        row.password_hash = hash_password(validated_new_password)
        row.updated_at = now
        revoked_sessions = _revoke_other_active_sessions(
            session,
            user_id=row.user_id,
            revoked_at=now,
            current_session_id=current_session_id,
        )
        session.flush()
        return UserOperationResult(
            user=actor_from_user(row),
            revoked_sessions=revoked_sessions,
            current_session_preserved=bool(current_session_id),
        )


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
    if getattr(args, "password", None) is not None:
        return _validated_password(str(args.password))
    if args.password_env:
        value = os.getenv(args.password_env)
        if value:
            return _validated_password(value)
        raise ValueError(f"Environment variable {args.password_env} is empty or unset")
    first = getpass.getpass("Password: ")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        raise ValueError("Passwords do not match")
    return _validated_password(first)


def _format_timestamp(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.isoformat()


def _print_user_list(users: list[UserSummary]) -> None:
    print("username\trole\tenabled\tcreated_at\tupdated_at\tlast_login_at")
    for user in users:
        print(
            f"{user.username}\t{user.role}\t{str(user.enabled).lower()}\t"
            f"{_format_timestamp(user.created_at)}\t{_format_timestamp(user.updated_at)}\t"
            f"{_format_timestamp(user.last_login_at)}"
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gjallar local user administration")
    subcommands = parser.add_subparsers(dest="command", required=True)

    create_admin_parser = subcommands.add_parser("create-admin", help="Create the first local admin user")
    create_admin_parser.add_argument("--username", required=True)
    create_admin_parser.add_argument("--password", help=argparse.SUPPRESS)
    create_admin_parser.add_argument("--password-env", help="Environment variable containing the password")

    create_user_parser = subcommands.add_parser("create-user", help="Create a local user with a selected role")
    create_user_parser.add_argument("--username", required=True)
    create_user_parser.add_argument("--role", required=True, choices=VALID_ROLES)
    create_user_parser.add_argument("--password", help=argparse.SUPPRESS)
    create_user_parser.add_argument("--password-env", help="Environment variable containing the password")

    subcommands.add_parser("list-users", help="List local users without secrets")

    set_role_parser = subcommands.add_parser("set-role", help="Update a local user's role")
    set_role_parser.add_argument("--username", required=True)
    set_role_parser.add_argument("--role", required=True, choices=VALID_ROLES)

    disable_user_parser = subcommands.add_parser("disable-user", help="Disable a local user and revoke sessions")
    disable_user_parser.add_argument("--username", required=True)

    reset_password_parser = subcommands.add_parser("reset-password", help="Reset a local user's password and revoke sessions")
    reset_password_parser.add_argument("--username", required=True)
    reset_password_parser.add_argument("--password", help=argparse.SUPPRESS)
    reset_password_parser.add_argument("--password-env", help="Environment variable containing the password")

    subcommands.add_parser(
        "bootstrap-admin-from-env",
        help="Create the configured bootstrap admin if it does not already exist",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "create-admin":
            actor = create_admin(username=args.username, password=_password_from_args(args))
            print(f"created admin user {actor.username} ({actor.user_id})")
            return 0
        if args.command == "bootstrap-admin-from-env":
            result = bootstrap_admin_from_env()
            if result.status == "not_configured":
                print(
                    f"bootstrap admin not configured; set {BOOTSTRAP_ADMIN_USERNAME_ENV} and "
                    f"{BOOTSTRAP_ADMIN_PASSWORD_ENV} to enable"
                )
                return 0
            if result.status == "already_exists":
                print(f"bootstrap admin user {result.username} already exists")
                return 0
            print(f"created bootstrap admin user {result.username}")
            return 0
        if args.command == "create-user":
            actor = create_user(username=args.username, password=_password_from_args(args), role=args.role)
            print(f"created {actor.role} user {actor.username} ({actor.user_id})")
            return 0
        if args.command == "list-users":
            _print_user_list(list_users())
            return 0
        if args.command == "set-role":
            actor = set_user_role(username=args.username, role=args.role)
            print(f"updated user {actor.username} role to {actor.role}")
            return 0
        if args.command == "disable-user":
            result = disable_user(username=args.username)
            print(f"disabled user {result.user.username}; revoked {result.revoked_sessions} session(s)")
            return 0
        if args.command == "reset-password":
            result = reset_password(username=args.username, password=_password_from_args(args))
            print(f"reset password for user {result.user.username}; revoked {result.revoked_sessions} session(s)")
            return 0
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
