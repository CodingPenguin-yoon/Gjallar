from dataclasses import replace

import pytest


VALID_EXECUTE_PAYLOAD = {"drs_live_migration_acknowledged": True}


class ExecutionDrsAdapter:
    source = "stub_read_only"

    def __init__(self):
        from app.proxmox.models import (
            DiskInventory,
            GuestAgentInventory,
            InventorySnapshot,
            NetworkInventory,
            NicBridgeEvidenceInventory,
            NodeInventory,
            StorageInventory,
            VmInventory,
        )

        self._snapshot_type = InventorySnapshot
        self._storages = (
            StorageInventory("shared-nfs", "node-a", "nfs", 1024, 600, ("images",)),
            StorageInventory("shared-nfs", "node-b", "nfs", 1024, 700, ("images",)),
        )
        self._networks = (
            NetworkInventory("vmbr0", "node-a", active=True),
            NetworkInventory("vmbr0", "node-b", active=True),
        )
        self._nodes = (
            NodeInventory(
                "node-a",
                "node-a",
                "online",
                32,
                131072,
                cpu_usage_percent=82,
                memory_used_mb=98304,
                memory_usage_percent=75,
                storage=tuple(item for item in self._storages if item.node_id == "node-a"),
                networks=tuple(item for item in self._networks if item.node_id == "node-a"),
            ),
            NodeInventory(
                "node-b",
                "node-b",
                "online",
                32,
                131072,
                cpu_usage_percent=31,
                memory_used_mb=52428,
                memory_usage_percent=40,
                storage=tuple(item for item in self._storages if item.node_id == "node-b"),
                networks=tuple(item for item in self._networks if item.node_id == "node-b"),
            ),
        )
        self._vm = VmInventory(
            vmid=101,
            name="app-01",
            node_id="node-a",
            status="running",
            template=False,
            cpu=2,
            memory_mb=8192,
            disk_gb=40,
            guest_agent=GuestAgentInventory(available=True),
            storage_id="shared-nfs",
            smbios1="uuid=11111111-2222-3333-4444-555555555555",
            vmgenid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            mac_addresses=("aa:bb:cc:dd:ee:ff",),
            nic_bridge_evidence=(
                NicBridgeEvidenceInventory(
                    interface_name="net0",
                    bridge_id="vmbr0",
                    model="virtio",
                    mac_address="aa:bb:cc:dd:ee:ff",
                ),
            ),
            disks=(
                DiskInventory(
                    device="scsi0",
                    bus="scsi",
                    index=0,
                    size_gb=40,
                    storage_id="shared-nfs",
                    volume_id="shared-nfs:vm-101-disk-0",
                    volume="vm-101-disk-0",
                    boot=True,
                ),
            ),
        )

    def snapshot(self):
        return self._snapshot_type(
            source=self.source,
            observed_at="2026-05-30T00:00:00+00:00",
            nodes=self._nodes,
            vms=(self._vm,),
            templates=(),
            connection={"source": self.source, "cluster_id": "cluster-a"},
        )

    def list_nodes(self):
        return list(self._nodes)

    def list_vms(self):
        return [self._vm]

    def list_storage(self, node_id=None):
        return [item for item in self._storages if node_id is None or item.node_id == node_id]

    def list_networks(self, node_id=None):
        return [item for item in self._networks if node_id is None or item.node_id == node_id]

    def set_vm_status(self, status):
        self._vm = replace(self._vm, status=status)


class FakeDrsMigrationClient:
    def __init__(
        self,
        *,
        live_precheck=None,
        task_result="ok",
        upid="UPID:node-a:0001:migrate",
        vm_status=None,
        vm_config=None,
        active_tasks=None,
        raise_status=False,
        raise_config=False,
        raise_active_tasks=False,
        migrate_error=None,
    ):
        self.live_precheck = live_precheck or _passing_live_precheck()
        self.task_result = task_result
        self.upid = upid
        self.vm_status = vm_status if vm_status is not None else {"status": "running", "node": "node-b", "name": "app-01"}
        self.vm_config = vm_config if vm_config is not None else {
            "name": "app-01",
            "smbios1": "uuid=11111111-2222-3333-4444-555555555555",
            "vmgenid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "net0": "virtio=aa:bb:cc:dd:ee:ff,bridge=vmbr0",
            "scsi0": "shared-nfs:vm-101-disk-0,size=40G",
        }
        self.active_tasks = active_tasks if active_tasks is not None else []
        self.raise_status = raise_status
        self.raise_config = raise_config
        self.raise_active_tasks = raise_active_tasks
        self.migrate_error = migrate_error
        self.migrate_calls = []
        self.preview_mutation_calls = []

    def collect_live_precheck(self, *, source_node, target_node, vmid):
        return self.live_precheck

    def migrate_vm(self, *, source_node, target_node, vmid):
        self.migrate_calls.append({"source_node": source_node, "target_node": target_node, "vmid": vmid})
        if self.migrate_error:
            from app.proxmox.drs_migration import DrsProxmoxMigrationError

            raise DrsProxmoxMigrationError(
                self.migrate_error,
                details={"source_node": source_node, "target_node": target_node, "vmid": vmid},
            )
        return self.upid

    def poll_task_status(self, *, node, upid):
        if self.task_result == "running":
            return {
                "result": "running",
                "status": {"status": "running", "upid": upid},
                "polls": [{"status": "running"}],
                "log": [{"n": 1, "t": "migration running"}],
            }
        return {
            "result": self.task_result,
            "status": {"status": "stopped", "exitstatus": "OK" if self.task_result == "ok" else "ERROR"},
            "polls": [{"status": "stopped"}],
            "log": [{"n": 1, "t": "migration done"}],
        }

    def get_task_status(self, *, node, upid):
        if self.task_result == "running":
            return {"upid": upid, "node": node, "status": "running", "type": "qmigrate", "id": "101"}
        return {
            "upid": upid,
            "node": node,
            "status": "stopped",
            "exitstatus": "OK" if self.task_result == "ok" else "ERROR",
            "type": "qmigrate",
            "id": "101",
        }

    def get_vm_status(self, *, node, vmid):
        if self.raise_status:
            from app.proxmox.drs_migration import DrsProxmoxMigrationError

            raise DrsProxmoxMigrationError("missing VM status", details={"node": node, "vmid": vmid})
        return dict(self.vm_status)

    def get_vm_config(self, *, node, vmid):
        if self.raise_config:
            from app.proxmox.drs_migration import DrsProxmoxMigrationError

            raise DrsProxmoxMigrationError("missing VM config", details={"node": node, "vmid": vmid})
        return dict(self.vm_config)

    def list_active_tasks(self, *, node, vmid):
        if self.raise_active_tasks:
            from app.proxmox.drs_migration import DrsProxmoxMigrationError

            raise DrsProxmoxMigrationError("active task evidence unavailable", details={"node": node, "vmid": vmid})
        return list(self.active_tasks)


def _passing_live_precheck():
    return {
        "status": "pass",
        "blockers": [],
        "checks": {
            "proxmox_active_task": {"status": "pass", "evidence": {"count": 0}},
            "proxmox_cluster_quorum": {"status": "pass", "evidence": {"cluster": {"quorate": 1}}},
            "proxmox_ha_state": {"status": "pass", "evidence": {"managed": False}},
            "proxmox_migration_preconditions": {
                "status": "pass",
                "evidence": {"running": True, "allowed_nodes": ["node-b"]},
            },
        },
    }


def _first_recommendation(adapter):
    from app.drs.advisor import build_drs_advisor_model

    return build_drs_advisor_model(adapter, risks=[])["recommendations"][0]


def _set_policy(vm_identity_id, policy):
    from app.db.models import VmMigrationPolicyRecord
    from app.db.session import session_scope

    with session_scope() as session:
        existing = session.query(VmMigrationPolicyRecord).filter_by(vm_identity_id=vm_identity_id).one_or_none()
        if existing is None:
            session.add(
                VmMigrationPolicyRecord(
                    policy_id=f"policy-{vm_identity_id}",
                    vm_identity_id=vm_identity_id,
                    policy=policy,
                    reason=f"{policy} in execution test",
                    source="manual",
                    updated_by="test",
                )
            )
        else:
            existing.policy = policy
            existing.reason = f"{policy} in execution test"


def _approved_job(adapter):
    from app.drs.advisor import build_drs_check_result
    from app.drs.approval import create_approval_packet_and_job_intent

    first = _first_recommendation(adapter)
    _set_policy(first["identity_evidence"]["vm_identity_id"], "allowed")
    recommendation = _first_recommendation(adapter)
    check = build_drs_check_result(adapter, recommendation["id"], risks=[], payload={"recommendation": recommendation})
    result = create_approval_packet_and_job_intent(
        check,
        payload={},
        actor={"user_id": "operator-1", "username": "operator", "role": "operator"},
    )
    return result["job_intent"]["job_id"], recommendation


def _mutate_approval_binding(job_id, case):
    from app.db.models import DrsApprovalPacketRecord, DrsMigrationJobRecord
    from app.db.session import session_scope

    with session_scope() as session:
        job = session.get(DrsMigrationJobRecord, job_id)
        packet = session.get(DrsApprovalPacketRecord, job.approval_packet_id)
        if case == "packet_not_approved":
            packet.packet_status = "blocked"
        elif case == "job_cancelled":
            job.status = "cancelled"
        elif case == "job_not_pending":
            job.status = "running"
        elif case == "job_already_has_upid":
            job.proxmox_upid = "UPID:node-a:already:migrate"
            job.proxmox_task_node = "node-a"
        elif case == "checksum_artifact_mismatch":
            packet.final_precheck_checksum = "sha256:does-not-match"
        else:
            raise AssertionError(f"unknown approval binding case: {case}")


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"drs_live_migration_acknowledged": False},
        {"drs_live_migration_acknowledged": None},
        {"drs_live_migration_acknowledged": "true"},
        {"drs_live_migration_acknowledged": 1},
        {"drsLiveMigrationAcknowledged": True},
        {"proxmox_mutation_acknowledged": True},
    ],
)
def test_execute_ack_gate_blocks_before_client_factory_locks_and_job_mutation(payload):
    from app.db.models import DrsMigrationJobRecord, OperationLockRecord
    from app.db.session import session_scope
    from app.drs.execution import DrsMigrationExecutionError, execute_drs_migration_job

    adapter = ExecutionDrsAdapter()
    job_id, _ = _approved_job(adapter)
    client = FakeDrsMigrationClient()
    called = False

    def fail_factory():
        nonlocal called
        called = True
        return client

    with pytest.raises(DrsMigrationExecutionError) as raised:
        execute_drs_migration_job(
            job_id,
            actor={"user_id": "operator-1", "username": "operator", "role": "operator"},
            inventory_adapter=adapter,
            payload=payload,
            risks=[],
            client_factory=fail_factory,
        )

    assert raised.value.status_code == 409
    assert raised.value.code == "DRS_EXECUTION_ACK_REQUIRED"
    assert raised.value.detail == {
        "job_id": job_id,
        "required_acknowledgement": "drs_live_migration_acknowledged",
        "proxmox_mutation_enabled": False,
        "side_effects": [],
    }
    assert called is False
    assert client.migrate_calls == []
    with session_scope() as session:
        job = session.get(DrsMigrationJobRecord, job_id)
        assert job.status == "pending"
        assert job.side_effects == []
        assert job.proxmox_upid is None
        assert job.proxmox_task_node is None
        assert job.operation_lock_ids == []
        assert session.query(OperationLockRecord).all() == []


@pytest.mark.parametrize(
    ("case", "expected_blocker"),
    [
        ("packet_not_approved", "approval_packet_not_approved"),
        ("job_cancelled", "job_cancelled"),
        ("job_not_pending", "job_not_pending"),
        ("job_already_has_upid", "job_already_has_upid"),
        ("checksum_artifact_mismatch", "final_precheck_checksum_artifact_mismatch"),
    ],
)
def test_approval_binding_blockers_stop_before_client_factory(case, expected_blocker):
    from app.db.models import OperationLockRecord
    from app.db.session import session_scope
    from app.drs.execution import DrsMigrationExecutionError, execute_drs_migration_job

    adapter = ExecutionDrsAdapter()
    job_id, _ = _approved_job(adapter)
    _mutate_approval_binding(job_id, case)
    called = False

    def fail_factory():
        nonlocal called
        called = True
        raise AssertionError("client factory must not be called when approval binding blocks")

    with pytest.raises(DrsMigrationExecutionError) as raised:
        execute_drs_migration_job(
            job_id,
            actor={"user_id": "operator-1", "username": "operator", "role": "operator"},
            inventory_adapter=adapter,
            payload=VALID_EXECUTE_PAYLOAD,
            risks=[],
            client_factory=fail_factory,
        )

    assert raised.value.code == "DRS_EXECUTION_APPROVAL_BLOCKED"
    assert expected_blocker in raised.value.detail["blockers"]
    assert raised.value.detail["side_effects"] == []
    assert called is False
    with session_scope() as session:
        locks = session.query(OperationLockRecord).all()
        assert locks == []


def test_final_precheck_policy_regression_blocks_before_client_factory():
    from app.drs.execution import DrsMigrationExecutionError, execute_drs_migration_job

    adapter = ExecutionDrsAdapter()
    job_id, recommendation = _approved_job(adapter)
    _set_policy(recommendation["identity_evidence"]["vm_identity_id"], "blocked")

    def fail_factory():
        raise AssertionError("client factory must not be called when fresh final precheck blocks")

    with pytest.raises(DrsMigrationExecutionError) as raised:
        execute_drs_migration_job(
            job_id,
            actor={"user_id": "operator-1", "username": "operator", "role": "operator"},
            inventory_adapter=adapter,
            payload=VALID_EXECUTE_PAYLOAD,
            risks=[],
            client_factory=fail_factory,
        )

    assert raised.value.code == "DRS_EXECUTION_FINAL_PRECHECK_BLOCKED"
    assert "migration_policy_blocked" in raised.value.detail["blockers"]
    drs_evidence = raised.value.detail["job_run"]["details"]["drs_evidence"]
    assert drs_evidence["read_only"] is True
    assert drs_evidence["allowed_actions"] == []
    assert drs_evidence["current_mutation_controls"] == []
    assert drs_evidence["execution_acknowledgement"] == {
        "field": "drs_live_migration_acknowledged",
        "value": True,
    }
    assert drs_evidence["historical_execution"]["proxmox_mutation_recorded"] is False
    assert drs_evidence["final_precheck_summary"]["status"] == "blocked"
    assert "migration_policy_blocked" in drs_evidence["blockers"]
    assert "migration_policy_blocked" in drs_evidence["final_precheck_summary"]["blockers"]


def test_live_precheck_block_does_not_call_migration_mutation():
    from app.drs.execution import DrsMigrationExecutionError, execute_drs_migration_job

    adapter = ExecutionDrsAdapter()
    job_id, _ = _approved_job(adapter)
    client = FakeDrsMigrationClient(
        live_precheck={
            "status": "blocked",
            "blockers": ["proxmox_active_task_conflict"],
            "checks": {
                "proxmox_active_task": {"status": "failed", "blocker": "proxmox_active_task_conflict"},
                "proxmox_cluster_quorum": {"status": "pass"},
                "proxmox_ha_state": {"status": "pass"},
                "proxmox_migration_preconditions": {"status": "pass"},
            },
        }
    )

    with pytest.raises(DrsMigrationExecutionError) as raised:
        execute_drs_migration_job(
            job_id,
            actor={"user_id": "operator-1", "username": "operator", "role": "operator"},
            inventory_adapter=adapter,
            payload=VALID_EXECUTE_PAYLOAD,
            risks=[],
            client_factory=lambda: client,
        )

    assert raised.value.code == "DRS_EXECUTION_LIVE_PRECHECK_BLOCKED"
    assert client.migrate_calls == []


def test_operation_lock_block_does_not_call_migration_mutation():
    from datetime import datetime, timezone

    from app.db.models import OperationLockRecord
    from app.db.session import session_scope
    from app.drs.execution import DrsMigrationExecutionError, execute_drs_migration_job
    from app.drs.operation_locks import identity_scope_key

    adapter = ExecutionDrsAdapter()
    job_id, recommendation = _approved_job(adapter)
    cluster_id = recommendation["identity_evidence"]["fingerprint_components"]["locator"]["cluster_id"]
    vm_identity_id = recommendation["identity_evidence"]["vm_identity_id"]
    class LockingClient(FakeDrsMigrationClient):
        def collect_live_precheck(self, *, source_node, target_node, vmid):
            now = datetime.now(timezone.utc)
            with session_scope() as session:
                session.add(
                    OperationLockRecord(
                        operation_lock_id="lock-existing-active",
                        operation_type="drs_migration",
                        scope_type="vm_identity",
                        scope_key=identity_scope_key(cluster_id, vm_identity_id),
                        status="active",
                        cluster_id=cluster_id,
                        vm_identity_id=vm_identity_id,
                        vmid=101,
                        source_node_id="node-a",
                        target_node_id="node-b",
                        owner_id="other-operator",
                        reason="existing active lock",
                        evidence={"source": "test"},
                        created_at=now,
                        updated_at=now,
                    )
                )
            return super().collect_live_precheck(source_node=source_node, target_node=target_node, vmid=vmid)

    client = LockingClient()

    with pytest.raises(DrsMigrationExecutionError) as raised:
        execute_drs_migration_job(
            job_id,
            actor={"user_id": "operator-1", "username": "operator", "role": "operator"},
            inventory_adapter=adapter,
            payload=VALID_EXECUTE_PAYLOAD,
            risks=[],
            client_factory=lambda: client,
        )

    assert raised.value.code == "DRS_EXECUTION_LOCK_BLOCKED"
    assert "operation_lock_active" in raised.value.detail["blockers"]
    assert client.migrate_calls == []


def test_task_ok_with_matching_postcheck_completes_and_releases_locks():
    import json

    from app.db.models import DrsMigrationJobRecord, OperationLockRecord
    from app.db.session import session_scope
    from app.drs.execution import execute_drs_migration_job
    from app.jobs.artifacts import read_artifact_text

    adapter = ExecutionDrsAdapter()
    job_id, _ = _approved_job(adapter)
    client = FakeDrsMigrationClient(task_result="ok")

    result = execute_drs_migration_job(
        job_id,
        actor={"user_id": "operator-1", "username": "operator", "role": "operator"},
        inventory_adapter=adapter,
        payload=VALID_EXECUTE_PAYLOAD,
        risks=[],
        client_factory=lambda: client,
    )

    assert result["status"] == "completed"
    assert result["needs_reconciliation"] is False
    assert result["reconciliation_reason"] is None
    assert result["proxmox_upid"] == "UPID:node-a:0001:migrate"
    assert result["post_check_status"] == "completed"
    assert result["post_check"]["expected"]["target_node_id"] == "node-b"
    assert result["post_check"]["observed"]["node_id"] == "node-b"
    assert result["post_check"]["observed"]["power_state"] == "running"
    drs_evidence = result["job_run"]["details"]["drs_evidence"]
    assert drs_evidence["read_only"] is True
    assert drs_evidence["allowed_actions"] == []
    assert drs_evidence["current_mutation_controls"] == []
    assert drs_evidence["execution_acknowledgement"] == {
        "field": "drs_live_migration_acknowledged",
        "value": True,
    }
    assert drs_evidence["historical_execution"]["proxmox_mutation_recorded"] is True
    assert "proxmox_migrate_invoked" in drs_evidence["historical_execution"]["side_effects"]
    assert drs_evidence["task"]["upid"] == "UPID:node-a:0001:migrate"
    assert drs_evidence["task"]["result"] == "ok"
    assert drs_evidence["task"]["exitstatus"] == "OK"
    assert drs_evidence["post_check"]["status"] == "pass"
    assert drs_evidence["post_check"]["fingerprint"]["matches"] is True
    assert {lock["status"] for lock in drs_evidence["operation_lock"]["locks"]} == {"released"}
    assert client.migrate_calls == [{"source_node": "node-a", "target_node": "node-b", "vmid": 101}]
    artifact_payload = json.loads(read_artifact_text(result["artifact"]))
    assert artifact_payload["post_check"]["expected"]["vmid"] == 101
    assert artifact_payload["post_check"]["observed"]["stable_fingerprint"] == result["post_check"]["expected"]["stable_fingerprint"]
    with session_scope() as session:
        job = session.get(DrsMigrationJobRecord, job_id)
        assert job.status == "completed"
        assert job.proxmox_upid == "UPID:node-a:0001:migrate"
        assert job.post_check_status == "completed"
        locks = session.query(OperationLockRecord).filter(OperationLockRecord.owner_id == "operator-1").all()
        assert len(locks) == 3
        assert {lock.status for lock in locks} == {"released"}


def test_task_ok_postcheck_ignores_cloudinit_cdrom_volume_for_identity_fingerprint():
    from app.db.models import DrsMigrationJobRecord, OperationLockRecord
    from app.db.session import session_scope
    from app.drs.execution import execute_drs_migration_job

    adapter = ExecutionDrsAdapter()
    job_id, _ = _approved_job(adapter)
    client = FakeDrsMigrationClient(
        task_result="ok",
        vm_config={
            "name": "app-01",
            "smbios1": "uuid=11111111-2222-3333-4444-555555555555",
            "vmgenid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "net0": "virtio=aa:bb:cc:dd:ee:ff,bridge=vmbr0",
            "ide2": "shared-nfs:vm-101-cloudinit.qcow2,media=cdrom,size=4M",
            "scsi0": "shared-nfs:vm-101-disk-0,size=40G",
        },
    )

    result = execute_drs_migration_job(
        job_id,
        actor={"user_id": "operator-1", "username": "operator", "role": "operator"},
        inventory_adapter=adapter,
        payload=VALID_EXECUTE_PAYLOAD,
        risks=[],
        client_factory=lambda: client,
    )

    disk_volume_ids = result["post_check"]["observed"]["fingerprint_components"]["disk_volume_ids"]
    assert result["status"] == "completed"
    assert disk_volume_ids == ["shared-nfs:vm-101-disk-0"]
    assert result["post_check"]["observed"]["stable_fingerprint"] == result["post_check"]["expected"]["stable_fingerprint"]
    with session_scope() as session:
        job = session.get(DrsMigrationJobRecord, job_id)
        assert job.status == "completed"
        locks = session.query(OperationLockRecord).filter(OperationLockRecord.owner_id == "operator-1").all()
        assert {lock.status for lock in locks} == {"released"}


@pytest.mark.parametrize(
    ("client_kwargs", "expected_reason"),
    [
        ({"vm_status": {"status": "running", "node": "node-a", "name": "app-01"}}, "post_check_target_mismatch"),
        ({"vm_status": {"status": "stopped", "node": "node-b", "name": "app-01"}}, "post_check_power_mismatch"),
        (
            {
                "vm_config": {
                    "name": "app-01",
                    "smbios1": "uuid=99999999-2222-3333-4444-555555555555",
                    "vmgenid": "bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "net0": "virtio=aa:bb:cc:dd:ee:ff,bridge=vmbr0",
                    "scsi0": "shared-nfs:vm-101-disk-0,size=40G",
                }
            },
            "fingerprint_mismatch",
        ),
        ({"active_tasks": [{"upid": "UPID:node-b:9999:task", "status": "running", "type": "qmigrate"}]}, "post_check_active_task_conflict"),
        ({"raise_status": True}, "post_check_vm_missing"),
        ({"raise_config": True}, "post_check_config_unavailable"),
        ({"raise_active_tasks": True}, "post_check_active_task_evidence_unavailable"),
    ],
)
def test_task_ok_postcheck_mismatch_needs_reconciliation_locks_and_event(client_kwargs, expected_reason):
    from app.db.models import DrsMigrationJobRecord, DrsReconciliationEventRecord, OperationLockRecord
    from app.db.session import session_scope
    from app.drs.execution import execute_drs_migration_job

    adapter = ExecutionDrsAdapter()
    job_id, _ = _approved_job(adapter)
    client = FakeDrsMigrationClient(task_result="ok", **client_kwargs)

    result = execute_drs_migration_job(
        job_id,
        actor={"user_id": "operator-1", "username": "operator", "role": "operator"},
        inventory_adapter=adapter,
        payload=VALID_EXECUTE_PAYLOAD,
        risks=[],
        client_factory=lambda: client,
    )

    assert result["status"] == "needs_reconciliation"
    assert result["post_check_status"] == "needs_reconciliation"
    assert result["reconciliation_reason"] == expected_reason
    assert expected_reason in result["post_check"]["blockers"]
    drs_evidence = result["job_run"]["details"]["drs_evidence"]
    assert drs_evidence["read_only"] is True
    assert drs_evidence["allowed_actions"] == []
    assert drs_evidence["current_mutation_controls"] == []
    assert drs_evidence["task"]["upid"] == "UPID:node-a:0001:migrate"
    assert drs_evidence["task"]["result"] == "ok"
    assert drs_evidence["post_check"]["status"] == "needs_reconciliation"
    assert expected_reason in drs_evidence["post_check"]["blockers"]
    assert drs_evidence["reconciliation"]["required"] is True
    assert drs_evidence["reconciliation"]["reason"] == expected_reason
    assert drs_evidence["reconciliation"]["events"]
    assert {lock["status"] for lock in drs_evidence["operation_lock"]["locks"]} == {"reconciliation_required"}
    with session_scope() as session:
        job = session.get(DrsMigrationJobRecord, job_id)
        assert job.status == "needs_reconciliation"
        assert job.post_check_status == "needs_reconciliation"
        locks = session.query(OperationLockRecord).filter(OperationLockRecord.owner_id == "operator-1").all()
        assert len(locks) == 3
        assert {lock.status for lock in locks} == {"reconciliation_required"}
        events = session.query(DrsReconciliationEventRecord).filter_by(job_id=job_id).all()
        assert len(events) == 1
        assert events[0].reason == expected_reason


@pytest.mark.parametrize(
    ("task_result", "expected_reason"),
    [
        ("failed", "task_failed"),
        ("timeout", "task_timeout"),
        ("ambiguous", "task_ambiguous"),
    ],
)
def test_terminal_task_uncertainty_needs_reconciliation_locks_and_event(task_result, expected_reason):
    from app.db.models import DrsMigrationJobRecord, DrsReconciliationEventRecord, OperationLockRecord
    from app.db.session import session_scope
    from app.drs.execution import execute_drs_migration_job

    adapter = ExecutionDrsAdapter()
    job_id, _ = _approved_job(adapter)
    client = FakeDrsMigrationClient(task_result=task_result)

    result = execute_drs_migration_job(
        job_id,
        actor={"user_id": "operator-1", "username": "operator", "role": "operator"},
        inventory_adapter=adapter,
        payload=VALID_EXECUTE_PAYLOAD,
        risks=[],
        client_factory=lambda: client,
    )

    assert result["status"] == "needs_reconciliation"
    assert result["needs_reconciliation"] is True
    assert result["reconciliation_reason"] == expected_reason
    assert result["task_result"] == task_result
    assert result["proxmox_upid"] == "UPID:node-a:0001:migrate"
    assert result["post_check_status"] is None
    assert "proxmox_task_polled" in result["side_effects"]
    with session_scope() as session:
        job = session.get(DrsMigrationJobRecord, job_id)
        assert job.status == "needs_reconciliation"
        assert job.proxmox_upid == "UPID:node-a:0001:migrate"
        assert job.task_result == task_result
        assert job.reconciliation_reason == expected_reason
        locks = session.query(OperationLockRecord).filter(OperationLockRecord.owner_id == "operator-1").all()
        assert len(locks) == 3
        assert {lock.status for lock in locks} == {"reconciliation_required"}
        assert not any(lock.status == "released" for lock in locks)
        events = session.query(DrsReconciliationEventRecord).filter_by(job_id=job_id).all()
        assert len(events) == 1
        assert events[0].reason == expected_reason
        assert events[0].evidence["upid"] == "UPID:node-a:0001:migrate"
        assert events[0].evidence["task_result"] == task_result


def test_running_task_keeps_active_locks_and_running_job():
    from app.db.models import DrsMigrationJobRecord, OperationLockRecord
    from app.db.session import session_scope
    from app.drs.execution import execute_drs_migration_job

    adapter = ExecutionDrsAdapter()
    job_id, _ = _approved_job(adapter)
    client = FakeDrsMigrationClient(task_result="running")

    result = execute_drs_migration_job(
        job_id,
        actor={"user_id": "operator-1", "username": "operator", "role": "operator"},
        inventory_adapter=adapter,
        payload=VALID_EXECUTE_PAYLOAD,
        risks=[],
        client_factory=lambda: client,
    )

    assert result["status"] == "running"
    assert result["needs_reconciliation"] is False
    with session_scope() as session:
        job = session.get(DrsMigrationJobRecord, job_id)
        assert job.status == "running"
        locks = session.query(OperationLockRecord).filter(OperationLockRecord.owner_id == "operator-1").all()
        assert len(locks) == 3
        assert {lock.status for lock in locks} == {"active"}


def test_local_reconcile_ack_blocks_before_client_and_db_work():
    from app.db.models import DrsMigrationJobRecord, OperationLockRecord
    from app.db.session import session_scope
    from app.drs.execution import DrsMigrationExecutionError, execute_drs_migration_job, reconcile_drs_migration_job

    adapter = ExecutionDrsAdapter()
    job_id, _ = _approved_job(adapter)
    execute_drs_migration_job(
        job_id,
        actor={"user_id": "operator-1", "username": "operator", "role": "operator"},
        inventory_adapter=adapter,
        payload=VALID_EXECUTE_PAYLOAD,
        risks=[],
        client_factory=lambda: FakeDrsMigrationClient(task_result="running"),
    )
    called = False

    def fail_factory():
        nonlocal called
        called = True
        raise AssertionError("client factory must not be called without reconciliation ack")

    with pytest.raises(DrsMigrationExecutionError) as raised:
        reconcile_drs_migration_job(
            job_id,
            actor={"user_id": "operator-1", "username": "operator", "role": "operator"},
            payload={"drs_reconciliation_acknowledged": "true"},
            client_factory=fail_factory,
        )

    assert raised.value.code == "DRS_RECONCILIATION_ACK_REQUIRED"
    assert called is False
    with session_scope() as session:
        job = session.get(DrsMigrationJobRecord, job_id)
        assert job.status == "running"
        locks = session.query(OperationLockRecord).filter(OperationLockRecord.owner_id == "operator-1").all()
        assert {lock.status for lock in locks} == {"active"}


def test_local_reconcile_running_task_keeps_job_running_and_does_not_migrate_again():
    from app.db.models import DrsMigrationJobRecord, OperationLockRecord
    from app.db.session import session_scope
    from app.drs.execution import execute_drs_migration_job, reconcile_drs_migration_job

    adapter = ExecutionDrsAdapter()
    job_id, _ = _approved_job(adapter)
    execute_drs_migration_job(
        job_id,
        actor={"user_id": "operator-1", "username": "operator", "role": "operator"},
        inventory_adapter=adapter,
        payload=VALID_EXECUTE_PAYLOAD,
        risks=[],
        client_factory=lambda: FakeDrsMigrationClient(task_result="running"),
    )
    followup_client = FakeDrsMigrationClient(task_result="running")

    result = reconcile_drs_migration_job(
        job_id,
        actor={"user_id": "operator-1", "username": "operator", "role": "operator"},
        payload={"drs_reconciliation_acknowledged": True},
        client_factory=lambda: followup_client,
    )

    assert result["status"] == "running"
    assert result["proxmox_mutation_enabled"] is False
    assert result["corrective_mutation_enabled"] is False
    assert followup_client.migrate_calls == []
    with session_scope() as session:
        job = session.get(DrsMigrationJobRecord, job_id)
        assert job.status == "running"
        locks = session.query(OperationLockRecord).filter(OperationLockRecord.owner_id == "operator-1").all()
        assert {lock.status for lock in locks} == {"active"}


def test_local_reconcile_task_ok_postcheck_pass_completes_and_releases_existing_locks():
    from app.db.models import DrsMigrationJobRecord, DrsReconciliationEventRecord, OperationLockRecord
    from app.db.session import session_scope
    from app.drs.execution import execute_drs_migration_job, reconcile_drs_migration_job

    adapter = ExecutionDrsAdapter()
    job_id, _ = _approved_job(adapter)
    execute_drs_migration_job(
        job_id,
        actor={"user_id": "operator-1", "username": "operator", "role": "operator"},
        inventory_adapter=adapter,
        payload=VALID_EXECUTE_PAYLOAD,
        risks=[],
        client_factory=lambda: FakeDrsMigrationClient(
            task_result="ok",
            vm_config={
                "name": "app-01",
                "smbios1": "uuid=99999999-2222-3333-4444-555555555555",
                "vmgenid": "bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee",
                "net0": "virtio=aa:bb:cc:dd:ee:ff,bridge=vmbr0",
                "scsi0": "shared-nfs:vm-101-disk-0,size=40G",
            },
        ),
    )
    followup_client = FakeDrsMigrationClient(task_result="ok")

    result = reconcile_drs_migration_job(
        job_id,
        actor={"user_id": "operator-1", "username": "operator", "role": "operator"},
        payload={"drs_reconciliation_acknowledged": True},
        client_factory=lambda: followup_client,
    )

    assert result["status"] == "completed"
    assert result["needs_reconciliation"] is False
    assert result["resolved_reconciliation_events"]
    assert followup_client.migrate_calls == []
    with session_scope() as session:
        job = session.get(DrsMigrationJobRecord, job_id)
        assert job.status == "completed"
        assert job.post_check_status == "completed"
        locks = session.query(OperationLockRecord).filter(OperationLockRecord.owner_id == "operator-1").all()
        assert {lock.status for lock in locks} == {"released"}
        events = session.query(DrsReconciliationEventRecord).filter_by(job_id=job_id).all()
        assert {event.status for event in events} == {"resolved"}


def test_local_reconcile_task_failed_marks_existing_locks_reconciliation_required():
    from app.db.models import DrsMigrationJobRecord, DrsReconciliationEventRecord, OperationLockRecord
    from app.db.session import session_scope
    from app.drs.execution import execute_drs_migration_job, reconcile_drs_migration_job

    adapter = ExecutionDrsAdapter()
    job_id, _ = _approved_job(adapter)
    execute_drs_migration_job(
        job_id,
        actor={"user_id": "operator-1", "username": "operator", "role": "operator"},
        inventory_adapter=adapter,
        payload=VALID_EXECUTE_PAYLOAD,
        risks=[],
        client_factory=lambda: FakeDrsMigrationClient(task_result="running"),
    )
    followup_client = FakeDrsMigrationClient(task_result="failed")

    result = reconcile_drs_migration_job(
        job_id,
        actor={"user_id": "operator-1", "username": "operator", "role": "operator"},
        payload={"drs_reconciliation_acknowledged": True},
        client_factory=lambda: followup_client,
    )

    assert result["status"] == "needs_reconciliation"
    assert result["reconciliation_reason"] == "task_failed"
    assert followup_client.migrate_calls == []
    with session_scope() as session:
        job = session.get(DrsMigrationJobRecord, job_id)
        assert job.status == "needs_reconciliation"
        locks = session.query(OperationLockRecord).filter(OperationLockRecord.owner_id == "operator-1").all()
        assert {lock.status for lock in locks} == {"reconciliation_required"}
        events = session.query(DrsReconciliationEventRecord).filter_by(job_id=job_id).all()
        assert len(events) == 1
        assert events[0].reason == "task_failed"


def test_reconciliation_preview_is_read_only_and_does_not_reenter_migration():
    from app.db.models import DrsMigrationJobRecord
    from app.db.session import session_scope
    from app.drs.execution import build_drs_migration_reconciliation_preview

    adapter = ExecutionDrsAdapter()
    job_id, _ = _approved_job(adapter)
    with session_scope() as session:
        job = session.get(DrsMigrationJobRecord, job_id)
        job.status = "running"
        job.proxmox_upid = "UPID:node-a:0001:migrate"
        job.proxmox_task_node = "node-a"

    client = FakeDrsMigrationClient(task_result="ok")
    result = build_drs_migration_reconciliation_preview(
        job_id,
        actor={"user_id": "operator-1", "username": "operator", "role": "operator"},
        client_factory=lambda: client,
    )

    assert result["read_only"] is True
    assert result["proxmox_mutation_enabled"] is False
    assert result["side_effects"] == []
    assert result["would_mark_completed"] is True
    assert result["task"]["result"] == "ok"
    assert result["post_check"]["status"] == "pass"
    assert client.migrate_calls == []


def test_missing_upid_becomes_needs_reconciliation_and_marks_locks():
    from app.db.models import DrsMigrationJobRecord, DrsReconciliationEventRecord, OperationLockRecord
    from app.db.session import session_scope
    from app.drs.execution import execute_drs_migration_job

    adapter = ExecutionDrsAdapter()
    job_id, _ = _approved_job(adapter)
    client = FakeDrsMigrationClient(upid="")

    result = execute_drs_migration_job(
        job_id,
        actor={"user_id": "operator-1", "username": "operator", "role": "operator"},
        inventory_adapter=adapter,
        payload=VALID_EXECUTE_PAYLOAD,
        risks=[],
        client_factory=lambda: client,
    )

    assert result["status"] == "needs_reconciliation"
    assert result["reconciliation_reason"] == "missing_upid"
    with session_scope() as session:
        job = session.get(DrsMigrationJobRecord, job_id)
        assert job.status == "needs_reconciliation"
        assert job.proxmox_upid is None
        assert job.task_result == "missing_upid"
        locks = session.query(OperationLockRecord).filter(OperationLockRecord.owner_id == "operator-1").all()
        assert len(locks) == 3
        assert {lock.status for lock in locks} == {"reconciliation_required"}
        events = session.query(DrsReconciliationEventRecord).filter_by(job_id=job_id).all()
        assert len(events) == 1
        assert events[0].event_type == "ambiguous_evidence"


def test_migration_request_failure_after_locks_needs_reconciliation_without_release():
    from app.db.models import DrsMigrationJobRecord, DrsReconciliationEventRecord, OperationLockRecord
    from app.db.session import session_scope
    from app.drs.execution import execute_drs_migration_job

    adapter = ExecutionDrsAdapter()
    job_id, _ = _approved_job(adapter)
    client = FakeDrsMigrationClient(migrate_error="migration request failed")

    result = execute_drs_migration_job(
        job_id,
        actor={"user_id": "operator-1", "username": "operator", "role": "operator"},
        inventory_adapter=adapter,
        payload=VALID_EXECUTE_PAYLOAD,
        risks=[],
        client_factory=lambda: client,
    )

    assert result["status"] == "needs_reconciliation"
    assert result["reconciliation_reason"] == "migration_request_failed"
    assert result["job"]["task_result"] == "mutation_failed"
    assert result["job"]["proxmox_upid"] is None
    assert "proxmox_migrate_request_failed" in result["side_effects"]
    assert client.migrate_calls == [{"source_node": "node-a", "target_node": "node-b", "vmid": 101}]
    with session_scope() as session:
        job = session.get(DrsMigrationJobRecord, job_id)
        assert job.status == "needs_reconciliation"
        assert job.proxmox_upid is None
        assert job.task_result == "mutation_failed"
        assert job.reconciliation_reason == "migration_request_failed"
        locks = session.query(OperationLockRecord).filter(OperationLockRecord.owner_id == "operator-1").all()
        assert len(locks) == 3
        assert {lock.status for lock in locks} == {"reconciliation_required"}
        assert not any(lock.status == "released" for lock in locks)
        events = session.query(DrsReconciliationEventRecord).filter_by(job_id=job_id).all()
        assert len(events) == 1
        assert events[0].reason == "migration_request_failed"
        assert events[0].evidence["task_result"] == "mutation_failed"
