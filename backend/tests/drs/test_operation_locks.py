from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError


def _open_lock(lock_id: str, *, status: str = "active", scope_key: str = "cluster-a|vm_identity|unknown"):
    from app.db.models import OperationLockRecord

    now = datetime.now(timezone.utc)
    return OperationLockRecord(
        operation_lock_id=lock_id,
        operation_type="drs_migration",
        scope_type="vm_identity",
        scope_key=scope_key,
        status=status,
        cluster_id="cluster-a",
        vm_identity_id=None,
        vmid=101,
        source_node_id="node-a",
        target_node_id="node-b",
        owner_id="test",
        reason=f"{status} lock in test",
        evidence={"source": "test"},
        created_at=now,
        updated_at=now,
        released_at=now if status == "released" else None,
    )


def test_partial_unique_index_blocks_duplicate_open_scope_but_allows_released_history():
    from app.db.session import session_scope

    with session_scope() as session:
        session.add(_open_lock("released-1", status="released"))
        session.add(_open_lock("released-2", status="released"))
        session.flush()

    with session_scope() as session:
        session.add(_open_lock("active-1", status="active"))
        session.flush()

    with pytest.raises(IntegrityError):
        with session_scope() as session:
            session.add(_open_lock("stale-1", status="stale"))
            session.flush()


def test_acquire_drs_operation_locks_turns_unique_race_into_blocked_result(monkeypatch):
    from app.db.session import session_scope
    from app.drs import operation_locks as locks_module
    from app.drs.operation_locks import acquire_drs_operation_locks, identity_scope_key

    scope_key = identity_scope_key("cluster-a", None)
    with session_scope() as session:
        session.add(_open_lock("race-winner", status="active", scope_key=scope_key))
        session.flush()

    original_query = locks_module.query_open_locks_for_scopes
    calls = 0

    def stale_first_read(session, scopes, *, operation_type=locks_module.DRS_MIGRATION_OPERATION_TYPE):
        nonlocal calls
        calls += 1
        if calls == 1:
            return []
        return original_query(session, scopes, operation_type=operation_type)

    monkeypatch.setattr(locks_module, "query_open_locks_for_scopes", stale_first_read)

    with session_scope() as session:
        result = acquire_drs_operation_locks(
            session,
            cluster_id="cluster-a",
            vm_identity_id=None,
            vmid=101,
            source_node_id="node-a",
            target_node_id="node-b",
            owner_id="operator-1",
            reason="race loser",
            evidence={"source": "test"},
        )

    assert result["acquired"] is False
    assert result["locks"] == []
    assert result["lock_ids"] == []
    assert result["matching_locks"][0]["operation_lock_id"] == "race-winner"
    assert result["matching_statuses"] == ["active"]
    assert result["blockers"] == ["operation_lock_active"]


def test_drs_locator_scope_is_blocked_by_other_operation_type():
    from app.db.models import OperationLockRecord
    from app.db.session import session_scope
    from app.drs.operation_locks import acquire_drs_operation_locks

    now = datetime.now(timezone.utc)
    with session_scope() as session:
        session.add(
            OperationLockRecord(
                operation_lock_id="vm-start-lock-101",
                operation_type="vm_start",
                scope_type="proxmox_locator",
                scope_key="cluster-a|proxmox_locator|101",
                status="active",
                cluster_id="cluster-a",
                vmid=101,
                owner_id="operation-start-101",
                reason="vm_start_dispatch",
                evidence={"operation_id": "operation-start-101"},
                created_at=now,
                updated_at=now,
            )
        )

    with session_scope() as session:
        result = acquire_drs_operation_locks(
            session,
            cluster_id="cluster-a",
            vm_identity_id=None,
            vmid=101,
            source_node_id="node-a",
            target_node_id="node-b",
            owner_id="drs-job-101",
            reason="drs migration",
            evidence={"source": "test"},
        )

    assert result["acquired"] is False
    assert result["matching_locks"][0]["operation_type"] == "vm_start"
    assert result["matching_locks"][0]["owner_id"] == "operation-start-101"
