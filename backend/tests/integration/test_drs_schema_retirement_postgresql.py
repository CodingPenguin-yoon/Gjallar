"""Opt-in PostgreSQL contracts for the DRS schema retirement migration."""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateSchema, DropSchema


pytestmark = pytest.mark.postgresql


DRS_TABLES = {
    "vm_identities",
    "vm_identity_observations",
    "vm_migration_policies",
    "vm_migration_policy_events",
    "drs_approval_packets",
    "drs_migration_jobs",
    "drs_reconciliation_events",
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


def _postgres_url() -> str:
    configured = str(os.getenv("GJALLAR_POSTGRES_TEST_URL") or "").strip()
    if not configured:
        pytest.skip("GJALLAR_POSTGRES_TEST_URL is not configured")
    lowered = configured.lower()
    if lowered.startswith("postgresql://"):
        return f"postgresql+psycopg://{configured[len('postgresql://') :]}"
    if lowered.startswith("postgres://"):
        return f"postgresql+psycopg://{configured[len('postgres://') :]}"
    return configured


def _schema_url(database_url: str, schema_name: str) -> str:
    url = make_url(database_url)
    query = dict(url.query)
    existing_options = str(query.get("options") or "").strip()
    query["options"] = f"{existing_options} -csearch_path={schema_name}".strip()
    return url.set(query=query).render_as_string(hide_password=False)


@contextmanager
def _isolated_migration_database(monkeypatch):
    from alembic.config import Config

    from app.db.session import reset_session_cache

    base_url = _postgres_url()
    schema_name = f"gjallar_drs_retirement_{uuid.uuid4().hex}"
    admin_engine = create_engine(base_url, future=True, pool_pre_ping=True)
    schema_created = False
    try:
        with admin_engine.begin() as connection:
            connection.execute(CreateSchema(schema_name))
        schema_created = True

        isolated_url = _schema_url(base_url, schema_name)
        monkeypatch.setenv("GJALLAR_DATABASE_URL", isolated_url)
        monkeypatch.delenv("GJALLAR_ALLOW_SQLITE_FOR_TESTS", raising=False)
        reset_session_cache()
        config = Config(str(Path("backend/alembic.ini").resolve()))
        yield schema_name, isolated_url, config
    finally:
        reset_session_cache()
        if schema_created:
            with admin_engine.begin() as connection:
                connection.execute(DropSchema(schema_name, cascade=True, if_exists=True))
        admin_engine.dispose()


def _insert_0028_lock(
    connection,
    *,
    lock_id: str,
    operation_type: str,
    status: str = "released",
) -> None:
    connection.execute(
        text(
            "insert into operation_locks "
            "(operation_lock_id, operation_type, scope_type, scope_key, status, cluster_id, vmid, "
            "owner_id, reason, evidence, created_at, updated_at) values "
            "(:lock_id, :operation_type, 'proxmox_locator', :scope_key, :status, "
            "'schema-test', 306, :owner_id, 'schema_test', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {
            "lock_id": lock_id,
            "operation_type": operation_type,
            "scope_key": f"schema-test|proxmox_locator|{lock_id}",
            "status": status,
            "owner_id": f"operation-{lock_id}",
        },
    )


def _insert_historical_job_and_artifact(connection) -> None:
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


def _assert_postgresql_generic_lock_contract(inspector) -> None:
    assert {
        column["name"] for column in inspector.get_columns("operation_locks")
    } == GENERIC_LOCK_COLUMNS

    indexes = {index["name"]: index for index in inspector.get_indexes("operation_locks")}
    assert set(indexes) == GENERIC_LOCK_INDEXES | {"uq_operation_locks_open_configuration"}
    open_locator = indexes["uq_operation_locks_open_locator"]
    assert open_locator["unique"] is True
    predicate = str(open_locator.get("dialect_options", {}).get("postgresql_where") or "")
    assert "proxmox_locator" in predicate
    assert all(status in predicate for status in ("active", "stale", "reconciliation_required"))
    open_configuration = indexes["uq_operation_locks_open_configuration"]
    assert open_configuration["unique"] is True
    host_predicate = str(open_configuration.get("dialect_options", {}).get("postgresql_where") or "")
    assert "proxmox_configuration" in host_predicate
    assert all(status in host_predicate for status in ("active", "stale", "reconciliation_required"))

    checks = {
        constraint["name"]: constraint["sqltext"]
        for constraint in inspector.get_check_constraints("operation_locks")
    }
    assert set(checks) == {
        "ck_operation_locks_operation_type",
        "ck_operation_locks_scope_type",
        "ck_operation_locks_status",
        "ck_operation_locks_host_binding",
    }
    operation_type_check = checks["ck_operation_locks_operation_type"]
    assert "drs_migration" not in operation_type_check
    assert all(
        operation_type in operation_type_check
        for operation_type in ("vm_start", "vm_create", "guided_qm_vm_unlock", "vm_shutdown")
    )
    scope_check = checks["ck_operation_locks_scope_type"]
    assert "proxmox_locator" in scope_check
    assert "proxmox_configuration" in scope_check
    host_binding = checks["ck_operation_locks_host_binding"]
    assert all(value in host_binding for value in ("host_storage", "host_network", "vmid IS NULL"))
    assert "vm_identity" not in scope_check
    assert "route" not in scope_check
    assert inspector.get_foreign_keys("operation_locks") == []


def test_postgresql_0028_to_head_preserves_shared_rows_and_generic_lock_contract(monkeypatch):
    from alembic.command import upgrade

    with _isolated_migration_database(monkeypatch) as (schema_name, database_url, config):
        upgrade(config, "20260721_0028")

        engine = create_engine(database_url, future=True, pool_pre_ping=True)
        try:
            with engine.begin() as connection:
                assert connection.execute(text("select current_schema()")).scalar_one() == schema_name
                _insert_0028_lock(connection, lock_id="retained-lock", operation_type="vm_start")
                _insert_historical_job_and_artifact(connection)
        finally:
            engine.dispose()

        upgrade(config, "head")

        engine = create_engine(database_url, future=True, pool_pre_ping=True)
        try:
            inspector = inspect(engine)
            table_names = set(inspector.get_table_names())
            assert DRS_TABLES.isdisjoint(table_names)
            assert {"operation_locks", "job_runs", "job_artifacts"} <= table_names
            _assert_postgresql_generic_lock_contract(inspector)

            with engine.connect() as connection:
                assert connection.execute(
                    text(
                        "select operation_type, scope_type, status from operation_locks "
                        "where operation_lock_id = 'retained-lock'"
                    )
                ).one() == ("vm_start", "proxmox_locator", "released")
                assert connection.execute(
                    text("select job_type, status from job_runs where job_id = 'retained-job'")
                ).one() == ("drs_migration", "completed")
                assert connection.execute(
                    text("select job_id, type from job_artifacts where artifact_id = 'retained-artifact'")
                ).one() == ("retained-job", "historical")

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
            with pytest.raises(IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "insert into operation_locks "
                            "(operation_lock_id, operation_type, scope_type, scope_key, status, cluster_id, vmid, "
                            "owner_id, reason, evidence, created_at, updated_at) values "
                            "('retired-type', 'drs_migration', 'proxmox_locator', "
                            "'schema-test|proxmox_locator|1000', 'released', 'schema-test', 1000, "
                            "'operation-retired', 'schema_test', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                        )
                    )
        finally:
            engine.dispose()


@pytest.mark.parametrize("retained_kind", ("drs_table", "drs_lock"))
def test_postgresql_0028_to_head_refuses_retained_drs_state_before_ddl(monkeypatch, retained_kind):
    from alembic.command import upgrade

    with _isolated_migration_database(monkeypatch) as (_schema_name, database_url, config):
        upgrade(config, "20260721_0028")

        engine = create_engine(database_url, future=True, pool_pre_ping=True)
        try:
            with engine.begin() as connection:
                if retained_kind == "drs_table":
                    connection.execute(
                        text(
                            "insert into vm_identities "
                            "(vm_identity_id, cluster_id, stable_fingerprint, identity_status, "
                            "first_seen_at, last_seen_at) values "
                            "('retained-identity', 'schema-test', 'retained-fingerprint', 'active', "
                            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                        )
                    )
                else:
                    _insert_0028_lock(
                        connection,
                        lock_id="retained-drs-lock",
                        operation_type="drs_migration",
                    )
        finally:
            engine.dispose()

        expected_retained = "vm_identities=1" if retained_kind == "drs_table" else "operation_locks=1"
        with pytest.raises(RuntimeError, match=expected_retained):
            upgrade(config, "head")

        engine = create_engine(database_url, future=True, pool_pre_ping=True)
        try:
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
            with engine.connect() as connection:
                assert (
                    connection.execute(
                        text("select version_num from alembic_version")
                    ).scalar_one()
                    == "20260721_0028"
                )
                if retained_kind == "drs_table":
                    assert connection.execute(text("select count(*) from vm_identities")).scalar_one() == 1
                    assert connection.execute(text("select count(*) from operation_locks")).scalar_one() == 0
                else:
                    assert connection.execute(text("select count(*) from vm_identities")).scalar_one() == 0
                    assert connection.execute(text("select count(*) from operation_locks")).scalar_one() == 1
        finally:
            engine.dispose()
