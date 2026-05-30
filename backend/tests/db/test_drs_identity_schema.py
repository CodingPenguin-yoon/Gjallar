from pathlib import Path

from sqlalchemy import create_engine, inspect


def test_drs_identity_models_are_registered_in_metadata():
    from app.db.models import Base

    assert "vm_identities" in Base.metadata.tables
    assert "vm_identity_observations" in Base.metadata.tables
    assert "vm_migration_policies" in Base.metadata.tables
    assert "vm_migration_policy_events" in Base.metadata.tables
    assert "operation_locks" in Base.metadata.tables
    assert "drs_approval_packets" in Base.metadata.tables
    assert "drs_migration_jobs" in Base.metadata.tables
    assert "drs_reconciliation_events" in Base.metadata.tables
    assert {"cluster_id", "stable_fingerprint"} <= set(Base.metadata.tables["vm_identities"].columns.keys())
    assert {"vm_identity_id", "policy"} <= set(Base.metadata.tables["vm_migration_policies"].columns.keys())
    assert {
        "event_id",
        "vm_identity_id",
        "policy_id",
        "old_policy",
        "new_policy",
        "reason",
        "source",
        "actor_user_id",
        "actor_username",
        "actor_role",
        "request_id",
        "cluster_id",
        "node_id",
        "vmid",
        "fingerprint_hash",
        "observed_at",
        "expected_observation",
        "current_observation",
        "validation_result",
    } <= set(Base.metadata.tables["vm_migration_policy_events"].columns.keys())
    assert {
        "ck_vm_migration_policy_events_old_policy",
        "ck_vm_migration_policy_events_new_policy",
        "ck_vm_migration_policy_events_source",
    } <= {constraint.name for constraint in Base.metadata.tables["vm_migration_policy_events"].constraints}
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
        "uq_operation_locks_open_scope",
    } <= {index.name for index in Base.metadata.tables["operation_locks"].indexes}
    assert {
        "approval_packet_id",
        "packet_status",
        "job_id",
        "recommendation_id",
        "vm_identity_id",
        "source_node_id",
        "target_node_id",
        "actor_user_id",
        "warning_acknowledged",
        "warning_codes",
        "warnings",
        "recommendation_checksum",
        "final_precheck_checksum",
        "approval_packet_checksum",
        "final_precheck_summary",
        "lock_evidence",
    } <= set(Base.metadata.tables["drs_approval_packets"].columns.keys())
    assert {
        "job_id",
        "approval_packet_id",
        "recommendation_id",
        "vm_identity_id",
        "status",
        "runnable",
        "proxmox_mutation_enabled",
        "side_effects",
        "runnable_blockers",
        "final_precheck_summary",
        "lock_evidence",
        "approved_actor",
        "job_intent_artifact_id",
        "proxmox_upid",
        "proxmox_task_node",
        "migration_started_at",
        "migration_finished_at",
        "task_status",
        "task_exitstatus",
        "task_result",
        "task_metadata",
        "task_log_excerpt",
        "post_check_status",
        "post_check_evidence",
        "post_check_completed_at",
        "execution_evidence",
        "operation_lock_ids",
        "reconciliation_reason",
    } <= set(Base.metadata.tables["drs_migration_jobs"].columns.keys())
    assert {
        "event_id",
        "job_id",
        "event_type",
        "status",
        "reason",
        "evidence",
    } <= set(Base.metadata.tables["drs_reconciliation_events"].columns.keys())
    assert "ck_drs_approval_packets_packet_status" in {
        constraint.name for constraint in Base.metadata.tables["drs_approval_packets"].constraints
    }
    assert {
        "ck_drs_migration_jobs_status",
        "uq_drs_migration_jobs_approval_packet_id",
    } <= {constraint.name for constraint in Base.metadata.tables["drs_migration_jobs"].constraints}
    assert {
        "ix_drs_approval_packets_recommendation",
        "ix_drs_approval_packets_identity",
        "ix_drs_approval_packets_route",
        "ix_drs_migration_jobs_recommendation",
        "ix_drs_migration_jobs_identity_status",
        "ix_drs_migration_jobs_route_status",
        "ix_drs_reconciliation_events_job_created",
        "ix_drs_reconciliation_events_status",
        "ix_vm_migration_policy_events_identity_created",
        "ix_vm_migration_policy_events_policy_created",
        "ix_vm_migration_policy_events_actor_created",
        "ix_vm_migration_policy_events_locator_created",
    } <= (
        {index.name for index in Base.metadata.tables["drs_approval_packets"].indexes}
        | {index.name for index in Base.metadata.tables["drs_migration_jobs"].indexes}
        | {index.name for index in Base.metadata.tables["drs_reconciliation_events"].indexes}
        | {index.name for index in Base.metadata.tables["vm_migration_policy_events"].indexes}
    )


def test_alembic_head_creates_drs_identity_policy_and_operation_lock_tables(tmp_path, monkeypatch):
    from alembic.command import upgrade
    from alembic.config import Config

    from app.db.session import reset_session_cache

    db_path = tmp_path / "alembic-drs.db"
    database_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("GJALLAR_DATABASE_URL", database_url)
    reset_session_cache()

    config = Config(str(Path("backend/alembic.ini").resolve()))
    upgrade(config, "20260531_0024")

    engine = create_engine(database_url, future=True)
    inspector = inspect(engine)
    try:
        assert inspector.has_table("vm_identities")
        assert inspector.has_table("vm_identity_observations")
        assert inspector.has_table("vm_migration_policies")
        assert inspector.has_table("vm_migration_policy_events")
        assert inspector.has_table("operation_locks")
        assert inspector.has_table("drs_approval_packets")
        assert inspector.has_table("drs_migration_jobs")
        assert inspector.has_table("drs_reconciliation_events")
        migration_columns = {column["name"] for column in inspector.get_columns("drs_migration_jobs")}
        assert {
            "proxmox_upid",
            "proxmox_task_node",
            "task_status",
            "task_exitstatus",
            "task_result",
            "task_metadata",
            "task_log_excerpt",
            "post_check_status",
            "post_check_evidence",
            "post_check_completed_at",
            "execution_evidence",
            "operation_lock_ids",
            "reconciliation_reason",
        } <= migration_columns
        event_columns = {column["name"] for column in inspector.get_columns("drs_reconciliation_events")}
        assert {"event_id", "job_id", "event_type", "status", "reason", "evidence"} <= event_columns
        policy_event_columns = {column["name"] for column in inspector.get_columns("vm_migration_policy_events")}
        assert {
            "event_id",
            "vm_identity_id",
            "policy_id",
            "old_policy",
            "new_policy",
            "reason",
            "source",
            "actor_user_id",
            "actor_username",
            "actor_role",
            "request_id",
            "cluster_id",
            "node_id",
            "vmid",
            "fingerprint_hash",
            "observed_at",
            "expected_observation",
            "current_observation",
            "validation_result",
        } <= policy_event_columns
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
            "uq_operation_locks_open_scope",
        } <= {index["name"] for index in inspector.get_indexes("operation_locks")}
        assert next(
            index for index in inspector.get_indexes("operation_locks") if index["name"] == "uq_operation_locks_open_scope"
        )["unique"] == 1
        assert {
            "ck_operation_locks_operation_type",
            "ck_operation_locks_scope_type",
            "ck_operation_locks_status",
        } <= {constraint["name"] for constraint in inspector.get_check_constraints("operation_locks")}
        assert "uq_drs_approval_packets_job_id" in {
            constraint["name"] for constraint in inspector.get_unique_constraints("drs_approval_packets")
        }
        assert "uq_drs_migration_jobs_approval_packet_id" in {
            constraint["name"] for constraint in inspector.get_unique_constraints("drs_migration_jobs")
        }
        assert {
            "ck_drs_approval_packets_packet_status",
        } <= {constraint["name"] for constraint in inspector.get_check_constraints("drs_approval_packets")}
        assert {
            "ck_drs_migration_jobs_status",
        } <= {constraint["name"] for constraint in inspector.get_check_constraints("drs_migration_jobs")}
        assert {
            "ix_drs_approval_packets_recommendation",
            "ix_drs_approval_packets_identity",
            "ix_drs_approval_packets_route",
        } <= {index["name"] for index in inspector.get_indexes("drs_approval_packets")}
        assert {
            "ix_drs_migration_jobs_recommendation",
            "ix_drs_migration_jobs_identity_status",
            "ix_drs_migration_jobs_route_status",
        } <= {index["name"] for index in inspector.get_indexes("drs_migration_jobs")}
        assert {
            "ix_drs_reconciliation_events_job_id",
            "ix_drs_reconciliation_events_job_created",
            "ix_drs_reconciliation_events_status",
        } <= {index["name"] for index in inspector.get_indexes("drs_reconciliation_events")}
        assert {
            "ix_vm_migration_policy_events_vm_identity_id",
            "ix_vm_migration_policy_events_policy_id",
            "ix_vm_migration_policy_events_identity_created",
            "ix_vm_migration_policy_events_policy_created",
            "ix_vm_migration_policy_events_actor_created",
            "ix_vm_migration_policy_events_locator_created",
        } <= {index["name"] for index in inspector.get_indexes("vm_migration_policy_events")}
        assert {
            "ck_vm_migration_policy_events_old_policy",
            "ck_vm_migration_policy_events_new_policy",
            "ck_vm_migration_policy_events_source",
        } <= {constraint["name"] for constraint in inspector.get_check_constraints("vm_migration_policy_events")}
    finally:
        engine.dispose()
        reset_session_cache()
