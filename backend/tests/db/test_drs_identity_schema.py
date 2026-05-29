from pathlib import Path

from sqlalchemy import create_engine, inspect


def test_drs_identity_models_are_registered_in_metadata():
    from app.db.models import Base

    assert "vm_identities" in Base.metadata.tables
    assert "vm_identity_observations" in Base.metadata.tables
    assert "vm_migration_policies" in Base.metadata.tables
    assert "operation_locks" in Base.metadata.tables
    assert {"cluster_id", "stable_fingerprint"} <= set(Base.metadata.tables["vm_identities"].columns.keys())
    assert {"vm_identity_id", "policy"} <= set(Base.metadata.tables["vm_migration_policies"].columns.keys())
    assert {
        "operation_lock_id",
        "operation_type",
        "scope_type",
        "scope_key",
        "status",
        "cluster_id",
        "vm_identity_id",
        "vmid",
        "source_node_id",
        "target_node_id",
        "evidence",
    } <= set(Base.metadata.tables["operation_locks"].columns.keys())
    assert {
        "ck_operation_locks_operation_type",
        "ck_operation_locks_scope_type",
        "ck_operation_locks_status",
    } <= {constraint.name for constraint in Base.metadata.tables["operation_locks"].constraints}
    assert {
        "ix_operation_locks_scope_status",
        "ix_operation_locks_cluster_identity_status",
        "ix_operation_locks_locator_status",
        "ix_operation_locks_route_status",
        "ix_operation_locks_expires_at",
    } <= {index.name for index in Base.metadata.tables["operation_locks"].indexes}


def test_alembic_head_creates_drs_identity_policy_and_operation_lock_tables(tmp_path, monkeypatch):
    from alembic.command import upgrade
    from alembic.config import Config

    from app.db.session import reset_session_cache

    db_path = tmp_path / "alembic-drs.db"
    database_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("GJALLAR_DATABASE_URL", database_url)
    reset_session_cache()

    config = Config(str(Path("backend/alembic.ini").resolve()))
    upgrade(config, "20260528_0020")

    engine = create_engine(database_url, future=True)
    inspector = inspect(engine)
    try:
        assert inspector.has_table("vm_identities")
        assert inspector.has_table("vm_identity_observations")
        assert inspector.has_table("vm_migration_policies")
        assert inspector.has_table("operation_locks")
        assert "uq_vm_identities_cluster_fingerprint" in {
            constraint["name"] for constraint in inspector.get_unique_constraints("vm_identities")
        }
        assert "uq_vm_migration_policies_vm_identity_id" in {
            constraint["name"] for constraint in inspector.get_unique_constraints("vm_migration_policies")
        }
        assert {
            "ix_operation_locks_scope_status",
            "ix_operation_locks_cluster_identity_status",
            "ix_operation_locks_locator_status",
            "ix_operation_locks_route_status",
            "ix_operation_locks_expires_at",
        } <= {index["name"] for index in inspector.get_indexes("operation_locks")}
        assert {
            "ck_operation_locks_operation_type",
            "ck_operation_locks_scope_type",
            "ck_operation_locks_status",
        } <= {constraint["name"] for constraint in inspector.get_check_constraints("operation_locks")}
    finally:
        engine.dispose()
        reset_session_cache()
