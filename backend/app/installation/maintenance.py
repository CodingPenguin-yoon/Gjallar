"""Fresh managed DB initialization and read-only serve checks.

No public HTTP endpoint. Only the installation host invokes this command.
A separate marker identifies databases that this initializer created while empty.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import uuid

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Column, Integer, MetaData, String, Table, inspect, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.auth.users import create_first_installation_admin
from app.db.session import get_engine
from app.db.seed_create_vm_profiles import seed_create_vm_profiles

metadata = MetaData()
installation = Table(
    "gjallar_installation", metadata,
    Column("singleton", Integer, primary_key=True),
    Column("installation_id", String(36), nullable=False),
    Column("state", String(32), nullable=False),
)
LOCK_ID = 73106429381741


class InstallationError(RuntimeError):
    pass


def identity():
    try:
        return str(uuid.UUID(os.environ["GJALLAR_INSTALLATION_ID"]))
    except (KeyError, ValueError):
        raise InstallationError("설치 identity가 없거나 올바르지 않습니다.") from None


def alembic_config():
    backend = Path(__file__).resolve().parents[2]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    return config


def check_revision(connection):
    expected = set(ScriptDirectory.from_config(alembic_config()).get_heads())
    actual = set(MigrationContext.configure(connection).get_current_heads())
    if actual != expected:
        raise InstallationError("DB revision 불일치. 기존 DB는 backup·별도 migration 승인 후 업그레이드하세요.")


def marker(connection, expected_id):
    if not inspect(connection).has_table(installation.name):
        raise InstallationError("관리형 새 설치로 확인되지 않은 DB입니다. 자동 초기화하지 않습니다.")
    rows = connection.execute(select(installation)).mappings().all()
    if len(rows) != 1 or rows[0]["installation_id"] != expected_id:
        raise InstallationError("DB와 설치 identity가 다릅니다. 기존 DB를 보존하고 설정을 복구하세요.")
    return rows[0]


@contextmanager
def maintenance_lock(engine):
    with engine.connect() as connection:
        postgres = engine.dialect.name == "postgresql"
        if postgres:
            acquired = connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_ID})
            connection.commit()
            if not acquired:
                raise InstallationError("다른 설치 초기화가 실행 중입니다.")
        try:
            yield connection
        finally:
            if postgres:
                connection.rollback()
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_ID})
                connection.commit()


def initialize_schema():
    expected_id = identity()
    engine = get_engine()
    with maintenance_lock(engine) as connection:
        tables = set(inspect(connection).get_table_names())
        if installation.name not in tables:
            if tables or inspect(connection).get_view_names():
                raise InstallationError("빈 DB가 아닙니다. 기존 DB에는 초기화를 적용하지 않습니다.")
            installation.create(connection)
            connection.execute(installation.insert().values(singleton=1, installation_id=expected_id, state="initializing"))
            connection.commit()
        state = marker(connection, expected_id)["state"]
        connection.commit()
        if state in {"schema_ready", "ready"}:
            check_revision(connection)
            return state
        if state != "initializing":
            raise InstallationError("알 수 없는 초기화 상태입니다.")
        # Only this marker's interrupted fresh initialization may run migrations.
        command.upgrade(alembic_config(), "head")
        check_revision(connection)
        seed_create_vm_profiles()
        connection.execute(installation.update().where(installation.c.singleton == 1).values(state="schema_ready"))
        connection.commit()
        return "schema_ready"


def setup_admin(payload):
    from app.db.session import session_scope
    expected_id = identity()
    with session_scope() as session:
        if session.get_bind().dialect.name == "postgresql":
            # Blocks every users INSERT, including existing admin APIs/legacy CLI.
            session.execute(text("LOCK TABLE users IN EXCLUSIVE MODE"))
        else:
            session.execute(text("BEGIN IMMEDIATE"))
        row = marker(session.connection(), expected_id)
        check_revision(session.connection())
        if row["state"] == "ready":
            return "already_initialized"
        if row["state"] != "schema_ready":
            raise InstallationError("schema 초기화를 먼저 완료하세요.")
        # History in an otherwise zero-user DB must never be interpreted as fresh.
        for name in inspect(session.connection()).get_table_names():
            if name in {installation.name, "alembic_version", "users", "create_vm_profiles"}:
                continue
            table = Table(name, MetaData(), autoload_with=session.connection())
            if session.execute(select(table).limit(1)).first() is not None:
                raise InstallationError("기존 업무 이력이 있어 최초 계정을 생성하지 않습니다.")
        if (not isinstance(payload, dict) or set(payload) != {"username", "password"}
                or not all(isinstance(value, str) and value for value in payload.values())):
            raise InstallationError("관리자 입력이 올바르지 않습니다.")
        create_first_installation_admin(session, username=payload["username"], password=payload["password"])
        session.execute(installation.update().where(installation.c.singleton == 1).values(state="ready"))
        return "created"


def status():
    with get_engine().connect() as connection:
        row = marker(connection, identity())
        check_revision(connection)
        return row["state"]


def require_ready():
    if status() != "ready":
        raise InstallationError("최초 관리자 초기화가 완료되지 않았습니다.")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv == ["init-schema"]:
            result = initialize_schema()
        elif argv == ["setup-admin"]:
            result = setup_admin(json.loads(sys.stdin.read(65537)))
        elif argv == ["status"]:
            result = status()
        elif argv == ["check-ready"]:
            require_ready()
            result = "ready"
        else:
            raise InstallationError("지원하지 않는 설치 명령입니다.")
        print(json.dumps({"ok": True, "state": result}))
        return 0
    except InstallationError as exc:
        print(json.dumps({"ok": False, "message": str(exc)}, ensure_ascii=True))
        return 1
    except (SQLAlchemyError, OSError, ValueError, RuntimeError):
        # DB/driver/input errors may contain credentials. Never echo their text.
        print(json.dumps({"ok": False, "message": "초기화 실패. DB·계정·설정은 보존됩니다. 연결·revision·초기화 상태를 확인하세요."}, ensure_ascii=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
