"""Schema and migration contracts for common Operations persistence."""

from pathlib import Path

from sqlalchemy import create_engine, inspect, text


def test_operations_models_register_owned_tables_and_constraints():
    from app.db.metadata import Base

    operations = Base.metadata.tables["operations"]
    events = Base.metadata.tables["operation_events"]
    recovery = Base.metadata.tables["operation_recovery_items"]
    locks = Base.metadata.tables["operation_locks"]

    assert {
        "operation_id",
        "operation_type",
        "execution_mode",
        "status",
        "target_type",
        "target_id",
        "idempotency_key",
        "intent_digest",
        "plan_digest",
        "current_stage",
        "details",
        "expires_at",
        "version",
        "last_event_checksum",
    } <= set(operations.columns.keys())
    assert {
        "event_id",
        "operation_id",
        "sequence",
        "event_type",
        "from_status",
        "to_status",
        "stage",
        "payload",
        "previous_checksum",
        "checksum",
    } <= set(events.columns.keys())
    assert {
        "ck_operations_execution_mode",
        "ck_operations_status",
        "uq_operations_scoped_idempotency",
    } <= {constraint.name for constraint in operations.constraints}
    assert "uq_operation_events_operation_sequence" in {constraint.name for constraint in events.constraints}
    assert {
        "operation_id",
        "recovery_kind",
        "status",
        "available_at",
        "lease_owner",
        "lease_token",
        "lease_generation",
        "lease_expires_at",
        "attempt_count",
        "details",
    } <= set(recovery.columns.keys())
    assert "ck_operation_recovery_items_status" in {constraint.name for constraint in recovery.constraints}
    assert "uq_operation_locks_open_locator" in {index.name for index in locks.indexes}


def test_alembic_head_adds_operations_projection_and_event_tables(tmp_path, monkeypatch):
    from alembic.command import upgrade
    from alembic.config import Config

    from app.db.session import reset_session_cache

    db_path = tmp_path / "alembic-operations.db"
    database_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("GJALLAR_DATABASE_URL", database_url)
    reset_session_cache()

    config = Config(str(Path("backend/alembic.ini").resolve()))
    upgrade(config, "head")

    engine = create_engine(database_url, future=True)
    inspector = inspect(engine)
    try:
        assert inspector.has_table("operations")
        assert inspector.has_table("operation_events")
        assert inspector.has_table("operation_recovery_items")
        assert "uq_operations_scoped_idempotency" in {
            constraint["name"] for constraint in inspector.get_unique_constraints("operations")
        }
        assert "uq_operation_events_operation_sequence" in {
            constraint["name"] for constraint in inspector.get_unique_constraints("operation_events")
        }
        assert {
            "ix_operations_status_updated",
            "ix_operations_target_status",
            "ix_operations_actor_created",
        } <= {index["name"] for index in inspector.get_indexes("operations")}
        assert {
            "ix_operation_events_operation_created",
            "ix_operation_events_type_created",
        } <= {index["name"] for index in inspector.get_indexes("operation_events")}
        assert {
            "ix_operation_recovery_items_due",
            "ix_operation_recovery_items_lease",
        } <= {index["name"] for index in inspector.get_indexes("operation_recovery_items")}
        assert "uq_operation_locks_open_locator" in {
            index["name"] for index in inspector.get_indexes("operation_locks")
        }
        with engine.begin() as connection:
            connection.execute(
                text(
                    "insert into operation_locks "
                    "(operation_lock_id, operation_type, scope_type, scope_key, status, cluster_id, vmid, "
                    "owner_id, reason, evidence, created_at, updated_at) values "
                    "(:lock_id, 'vm_shutdown', 'proxmox_locator', :scope_key, 'released', 'schema-test', "
                    "306, 'operation-schema-test', 'schema_test', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"lock_id": "schema-vm-shutdown-lock", "scope_key": "schema-test|proxmox_locator|306"},
            )
    finally:
        engine.dispose()
        reset_session_cache()
