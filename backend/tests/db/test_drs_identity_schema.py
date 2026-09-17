from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


DRS_TABLES = {
    "vm_identities",
    "vm_identity_observations",
    "vm_migration_policies",
    "vm_migration_policy_events",
    "drs_approval_packets",
    "drs_migration_jobs",
    "drs_reconciliation_events",
}
SHARED_TABLES = {"operation_locks", "job_runs", "job_artifacts"}
GENERIC_OPERATION_TYPES = {
    "vm_start",
    "vm_create",
    "guided_qm_vm_unlock",
    "vm_shutdown",
}
GENERIC_LOCK_COLUMNS = {
    "operation_lock_id",
    "operation_type",
    "scope_type",
    "scope_key",
    "status",
    "cluster_id",
    "vmid",
    "owner_id",
    "reason",
    "evidence",
    "created_at",
    "updated_at",
    "expires_at",
    "released_at",
}
GENERIC_LOCK_INDEXES = {
    "ix_operation_locks_scope_status",
    "ix_operation_locks_expires_at",
    "uq_operation_locks_open_locator",
}


def _migration_config(tmp_path, monkeypatch, name: str):
    from alembic.config import Config

    from app.db.session import reset_session_cache

    database_url = f"sqlite:///{tmp_path / name}"
    monkeypatch.setenv("GJALLAR_DATABASE_URL", database_url)
    monkeypatch.setenv("GJALLAR_ALLOW_SQLITE_FOR_TESTS", "1")
    reset_session_cache()
    return database_url, Config(str(Path("backend/alembic.ini").resolve()))


def _insert_lock(
    connection,
    *,
    lock_id: str,
    operation_type: str,
    status: str = "released",
    scope_type: str = "proxmox_locator",
    source_node_id: str | None = None,
    target_node_id: str | None = None,
) -> None:
    connection.execute(
        text(
            "insert into operation_locks "
            "(operation_lock_id, operation_type, scope_type, scope_key, status, cluster_id, vmid, "
            "source_node_id, target_node_id, owner_id, reason, evidence, created_at, updated_at) values "
            "(:lock_id, :operation_type, :scope_type, :scope_key, :status, 'schema-test', 306, "
            ":source_node_id, :target_node_id, :owner_id, 'schema_test', '{}', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {
            "lock_id": lock_id,
            "operation_type": operation_type,
            "scope_type": scope_type,
            "scope_key": f"schema-test|{scope_type}|{lock_id}",
            "status": status,
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
            "owner_id": f"operation-{lock_id}",
        },
    )


def _assert_generic_lock_contract(inspector) -> None:
    assert {column["name"] for column in inspector.get_columns("operation_locks")} == GENERIC_LOCK_COLUMNS
    assert {index["name"] for index in inspector.get_indexes("operation_locks")} == GENERIC_LOCK_INDEXES
    assert inspector.get_foreign_keys("operation_locks") == []

    checks = {constraint["name"]: constraint["sqltext"] for constraint in inspector.get_check_constraints("operation_locks")}
    assert set(checks) == {
        "ck_operation_locks_operation_type",
        "ck_operation_locks_scope_type",
        "ck_operation_locks_status",
    }
    assert "drs_migration" not in checks["ck_operation_locks_operation_type"]
    assert all(operation_type in checks["ck_operation_locks_operation_type"] for operation_type in GENERIC_OPERATION_TYPES)
    assert "proxmox_locator" in checks["ck_operation_locks_scope_type"]
    assert "vm_identity" not in checks["ck_operation_locks_scope_type"]
    assert "route" not in checks["ck_operation_locks_scope_type"]


def test_drs_models_are_retired_from_metadata_while_shared_contracts_remain():
    from app.db.models import Base
    from app.operations.locks.domain import SUPPORTED_TARGET_OPERATION_TYPES

    assert DRS_TABLES.isdisjoint(Base.metadata.tables)
    assert SHARED_TABLES <= set(Base.metadata.tables)
    assert set(SUPPORTED_TARGET_OPERATION_TYPES) == GENERIC_OPERATION_TYPES

    locks = Base.metadata.tables["operation_locks"]
    assert set(locks.columns.keys()) == GENERIC_LOCK_COLUMNS
    assert {index.name for index in locks.indexes} == GENERIC_LOCK_INDEXES
    assert {constraint.name for constraint in locks.constraints if constraint.name} == {
        "ck_operation_locks_operation_type",
        "ck_operation_locks_scope_type",
        "ck_operation_locks_status",
    }


def test_alembic_baseline_to_head_retires_drs_and_keeps_generic_lock_invariants(tmp_path, monkeypatch):
    from alembic.command import upgrade

    from app.db.session import reset_session_cache

    database_url, config = _migration_config(tmp_path, monkeypatch, "alembic-drs-retirement.db")
    upgrade(config, "head")

    engine = create_engine(database_url, future=True)
    inspector = inspect(engine)
    try:
        table_names = set(inspector.get_table_names())
        assert DRS_TABLES.isdisjoint(table_names)
        assert SHARED_TABLES <= table_names
        _assert_generic_lock_contract(inspector)

        with engine.begin() as connection:
            for index, operation_type in enumerate(sorted(GENERIC_OPERATION_TYPES), start=1):
                connection.execute(
                    text(
                        "insert into operation_locks "
                        "(operation_lock_id, operation_type, scope_type, scope_key, status, cluster_id, vmid, "
                        "owner_id, reason, evidence, created_at, updated_at) values "
                        "(:lock_id, :operation_type, 'proxmox_locator', :scope_key, 'released', "
                        "'schema-test', :vmid, :owner_id, 'schema_test', '{}', "
                        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    ),
                    {
                        "lock_id": f"generic-lock-{index}",
                        "operation_type": operation_type,
                        "scope_key": f"schema-test|proxmox_locator|{300 + index}",
                        "vmid": 300 + index,
                        "owner_id": f"generic-operation-{index}",
                    },
                )

        with engine.begin() as connection:
            connection.execute(
                text(
                    "insert into operation_locks "
                    "(operation_lock_id, operation_type, scope_type, scope_key, status, cluster_id, vmid, "
                    "owner_id, reason, evidence, created_at, updated_at) values "
                    "('open-a', 'vm_start', 'proxmox_locator', 'schema-test|proxmox_locator|999', "
                    "'active', 'schema-test', 999, 'operation-a', 'schema_test', '{}', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "insert into operation_locks "
                        "(operation_lock_id, operation_type, scope_type, scope_key, status, cluster_id, vmid, "
                        "owner_id, reason, evidence, created_at, updated_at) values "
                        "('open-b', 'vm_shutdown', 'proxmox_locator', "
                        "'schema-test|proxmox_locator|999', 'reconciliation_required', 'schema-test', 999, "
                        "'operation-b', 'schema_test', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    )
                )
    finally:
        engine.dispose()
        reset_session_cache()


def test_0028_to_head_preserves_generic_locks_jobs_and_artifacts(tmp_path, monkeypatch):
    from alembic.command import upgrade

    from app.db.session import reset_session_cache

    database_url, config = _migration_config(tmp_path, monkeypatch, "alembic-drs-generic-preservation.db")
    upgrade(config, "20260721_0028")

    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            _insert_lock(connection, lock_id="retained-lock", operation_type="vm_start")
            connection.execute(
                text(
                    "insert into job_runs "
                    "(job_id, job_type, status, target_id, risk_level, started_at, finished_at, current_stage, "
                    "message, progress_percent, steps, risks, details, artifact_count, risk_count, updated_at) "
                    "values ('retained-job', 'drs_migration', 'completed', 'vmid:306', 'high', "
                    "'2026-08-24T00:00:00+00:00', '2026-08-24T00:01:00+00:00', 'post_check', "
                    "'historical job', 100, '[]', '[]', '{}', 1, 0, '2026-08-24T00:01:00+00:00')"
                )
            )
            connection.execute(
                text(
                    "insert into job_artifacts "
                    "(artifact_id, job_id, type, path, checksum, content_type, content_text, size_bytes, "
                    "storage_backend, created_at, updated_at) values "
                    "('retained-artifact', 'retained-job', 'historical', 'db://retained-artifact', "
                    "'checksum', 'application/json', '{}', 2, 'db', "
                    "'2026-08-24T00:00:00+00:00', '2026-08-24T00:00:00+00:00')"
                )
            )
        engine.dispose()

        upgrade(config, "head")

        engine = create_engine(database_url, future=True)
        inspector = inspect(engine)
        assert DRS_TABLES.isdisjoint(inspector.get_table_names())
        _assert_generic_lock_contract(inspector)
        with engine.connect() as connection:
            assert connection.execute(
                text("select operation_type, scope_type, status from operation_locks where operation_lock_id = 'retained-lock'")
            ).one() == ("vm_start", "proxmox_locator", "released")
            assert connection.execute(
                text("select job_type, status from job_runs where job_id = 'retained-job'")
            ).one() == ("drs_migration", "completed")
            assert connection.execute(
                text("select job_id, type from job_artifacts where artifact_id = 'retained-artifact'")
            ).one() == ("retained-job", "historical")
    finally:
        engine.dispose()
        reset_session_cache()


def test_0028_to_head_refuses_drs_table_rows_before_any_ddl(tmp_path, monkeypatch):
    from alembic.command import upgrade

    from app.db.session import reset_session_cache

    database_url, config = _migration_config(tmp_path, monkeypatch, "alembic-drs-row-guard.db")
    upgrade(config, "20260721_0028")

    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "insert into vm_identities "
                    "(vm_identity_id, cluster_id, stable_fingerprint, identity_status, first_seen_at, last_seen_at) "
                    "values ('retained-identity', 'schema-test', 'retained-fingerprint', 'active', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
        engine.dispose()

        with pytest.raises(RuntimeError, match="vm_identities=1"):
            upgrade(config, "head")

        engine = create_engine(database_url, future=True)
        inspector = inspect(engine)
        assert DRS_TABLES <= set(inspector.get_table_names())
        assert "vm_identity_id" in {column["name"] for column in inspector.get_columns("operation_locks")}
        with engine.connect() as connection:
            assert connection.execute(text("select count(*) from vm_identities")).scalar_one() == 1
            assert connection.execute(text("select version_num from alembic_version")).scalar_one() == "20260721_0028"
    finally:
        engine.dispose()
        reset_session_cache()


def test_0028_to_head_refuses_drs_lock_rows_before_any_ddl(tmp_path, monkeypatch):
    from alembic.command import upgrade

    from app.db.session import reset_session_cache

    database_url, config = _migration_config(tmp_path, monkeypatch, "alembic-drs-lock-guard.db")
    upgrade(config, "20260721_0028")

    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            _insert_lock(connection, lock_id="retained-drs-lock", operation_type="drs_migration")
        engine.dispose()

        with pytest.raises(RuntimeError, match="operation_locks=1"):
            upgrade(config, "head")

        engine = create_engine(database_url, future=True)
        inspector = inspect(engine)
        assert DRS_TABLES <= set(inspector.get_table_names())
        assert "source_node_id" in {column["name"] for column in inspector.get_columns("operation_locks")}
        with engine.connect() as connection:
            assert connection.execute(text("select count(*) from operation_locks")).scalar_one() == 1
            assert connection.execute(text("select version_num from alembic_version")).scalar_one() == "20260721_0028"
    finally:
        engine.dispose()
        reset_session_cache()


def test_sqlite_0029_failure_rolls_back_the_whole_revision_and_can_retry(tmp_path, monkeypatch):
    from alembic.command import upgrade
    from alembic.operations import Operations

    from app.db.session import reset_session_cache

    database_url, config = _migration_config(tmp_path, monkeypatch, "alembic-drs-atomic-rollback.db")
    upgrade(config, "20260721_0028")

    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            _insert_lock(connection, lock_id="retry-lock", operation_type="vm_start")
            connection.execute(
                text(
                    "insert into job_runs "
                    "(job_id, job_type, status, target_id, risk_level, started_at, finished_at, current_stage, "
                    "message, progress_percent, steps, risks, details, artifact_count, risk_count, updated_at) "
                    "values ('retry-job', 'drs_migration', 'completed', 'vmid:306', 'high', "
                    "'2026-08-24T00:00:00+00:00', '2026-08-24T00:01:00+00:00', 'post_check', "
                    "'historical job', 100, '[]', '[]', '{}', 0, 0, '2026-08-24T00:01:00+00:00')"
                )
            )
        engine.dispose()

        original_drop_table = Operations.drop_table
        dropped_tables: list[str] = []

        def fail_after_first_drop(self, table_name, *args, **kwargs):
            result = original_drop_table(self, table_name, *args, **kwargs)
            dropped_tables.append(str(table_name))
            if len(dropped_tables) == 1:
                raise RuntimeError("injected DRS retirement DDL failure")
            return result

        with monkeypatch.context() as fault:
            fault.setattr(Operations, "drop_table", fail_after_first_drop)
            with pytest.raises(RuntimeError, match="injected DRS retirement DDL failure"):
                upgrade(config, "20260824_0029")

        assert dropped_tables == ["drs_reconciliation_events"]

        engine = create_engine(database_url, future=True)
        inspector = inspect(engine)
        assert DRS_TABLES <= set(inspector.get_table_names())
        lock_columns = {column["name"] for column in inspector.get_columns("operation_locks")}
        assert {"vm_identity_id", "source_node_id", "target_node_id"} <= lock_columns
        lock_indexes = {index["name"] for index in inspector.get_indexes("operation_locks")}
        assert {
            "uq_operation_locks_open_scope",
            "ix_operation_locks_cluster_identity_status",
            "ix_operation_locks_locator_status",
            "ix_operation_locks_route_status",
        } <= lock_indexes
        lock_checks = {
            constraint["name"]: constraint["sqltext"]
            for constraint in inspector.get_check_constraints("operation_locks")
        }
        assert "drs_migration" in lock_checks["ck_operation_locks_operation_type"]
        assert "vm_identity" in lock_checks["ck_operation_locks_scope_type"]
        with engine.connect() as connection:
            assert connection.execute(text("select version_num from alembic_version")).scalar_one() == "20260721_0028"
            assert connection.execute(text("select count(*) from operation_locks")).scalar_one() == 1
            assert connection.execute(text("select count(*) from job_runs where job_id = 'retry-job'")).scalar_one() == 1
        engine.dispose()

        upgrade(config, "20260824_0029")

        engine = create_engine(database_url, future=True)
        inspector = inspect(engine)
        assert DRS_TABLES.isdisjoint(inspector.get_table_names())
        _assert_generic_lock_contract(inspector)
        with engine.connect() as connection:
            assert connection.execute(text("select version_num from alembic_version")).scalar_one() == "20260824_0029"
            assert connection.execute(text("select count(*) from operation_locks")).scalar_one() == 1
            assert connection.execute(text("select count(*) from job_runs where job_id = 'retry-job'")).scalar_one() == 1
    finally:
        engine.dispose()
        reset_session_cache()


def test_drs_schema_retirement_downgrade_requires_roll_forward(tmp_path, monkeypatch):
    from alembic.command import downgrade, upgrade

    from app.db.session import reset_session_cache

    database_url, config = _migration_config(tmp_path, monkeypatch, "alembic-drs-roll-forward.db")
    upgrade(config, "20260824_0029")

    with pytest.raises(RuntimeError, match="roll-forward only"):
        downgrade(config, "20260721_0028")

    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        assert DRS_TABLES.isdisjoint(inspector.get_table_names())
        with engine.connect() as connection:
            assert connection.execute(text("select version_num from alembic_version")).scalar_one() == "20260824_0029"
    finally:
        engine.dispose()
        reset_session_cache()
