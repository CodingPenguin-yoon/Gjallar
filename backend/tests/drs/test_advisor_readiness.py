from dataclasses import replace
from datetime import datetime, timezone

import pytest


class MutableDrsAdapter:
    source = "stub_read_only"

    def __init__(self, *, identity_mode="high", vm_status="running", policy_storage="shared-nfs", config_lock=""):
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
        self._storage_id = policy_storage
        self._storages = (
            StorageInventory(policy_storage, "node-a", "nfs", 1024, 600, ("images",)),
            StorageInventory(policy_storage, "node-b", "nfs", 1024, 700, ("images",)),
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
        smbios1 = "uuid=11111111-2222-3333-4444-555555555555" if identity_mode == "high" else ""
        vmgenid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" if identity_mode == "high" else ""
        mac_addresses = ("aa:bb:cc:dd:ee:ff",) if identity_mode in {"high", "medium"} else ()
        disks = ()
        storage_id = "unknown"
        if identity_mode == "high":
            storage_id = policy_storage
            disks = (
                DiskInventory(
                    device="scsi0",
                    bus="scsi",
                    index=0,
                    size_gb=40,
                    storage_id=policy_storage,
                    volume_id=f"{policy_storage}:vm-101-disk-0",
                    volume="vm-101-disk-0",
                    boot=True,
                ),
            )
        self._vm = VmInventory(
            vmid=101,
            name="app-01",
            node_id="node-a",
            status=vm_status,
            template=False,
            cpu=2,
            memory_mb=8192,
            disk_gb=40,
            guest_agent=GuestAgentInventory(available=True),
            storage_id=storage_id,
            smbios1=smbios1,
            vmgenid=vmgenid,
            mac_addresses=mac_addresses,
            nic_bridge_evidence=(
                NicBridgeEvidenceInventory(
                    interface_name="net0",
                    bridge_id="vmbr0",
                    model="virtio",
                    mac_address=mac_addresses[0] if mac_addresses else "",
                ),
            ),
            disks=disks,
            config_lock=config_lock,
        )

    def snapshot(self):
        return self._snapshot_type(
            source=self.source,
            observed_at="2026-05-28T00:00:00+00:00",
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


def _first_recommendation(adapter):
    from app.drs.advisor import build_drs_advisor_model

    return build_drs_advisor_model(adapter, risks=[])["recommendations"][0]


def _set_policy(vm_identity_id, policy):
    from app.db.models import VmMigrationPolicyRecord
    from app.db.session import session_scope

    with session_scope() as session:
        session.add(
            VmMigrationPolicyRecord(
                policy_id=f"policy-{policy}",
                vm_identity_id=vm_identity_id,
                policy=policy,
                reason=f"{policy} in test",
                source="manual",
                updated_by="test",
            )
        )


def _set_operation_lock(recommendation, status, *, scope_type="vm_identity", source_node_id=None):
    from app.db.models import OperationLockRecord
    from app.db.session import session_scope
    from app.drs.operation_locks import identity_scope_key, locator_scope_key, route_scope_key

    cluster_id = recommendation["identity_evidence"]["fingerprint_components"]["locator"]["cluster_id"]
    vm_identity_id = recommendation["identity_evidence"]["vm_identity_id"]
    vmid = recommendation["vmid"]
    lock_source_node_id = source_node_id or recommendation["source_node_id"]
    target_node_id = recommendation["target_node_id"]
    if scope_type == "vm_identity":
        scope_key = identity_scope_key(cluster_id, vm_identity_id)
    elif scope_type == "proxmox_locator":
        scope_key = locator_scope_key(cluster_id, vmid)
    else:
        scope_key = route_scope_key(cluster_id, lock_source_node_id, target_node_id)
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        session.add(
            OperationLockRecord(
                operation_lock_id=f"lock-{status}-{scope_type}",
                operation_type="drs_migration",
                scope_type=scope_type,
                scope_key=scope_key,
                status=status,
                cluster_id=cluster_id,
                vm_identity_id=vm_identity_id,
                vmid=vmid,
                source_node_id=lock_source_node_id,
                target_node_id=target_node_id,
                owner_id="test",
                reason=f"{status} lock in test",
                evidence={"source": "test", "recommendation_id": recommendation["id"]},
                created_at=now,
                updated_at=now,
                released_at=now if status == "released" else None,
            )
        )


def test_unknown_and_medium_identity_block_recommendations():
    unknown = _first_recommendation(MutableDrsAdapter(identity_mode="unknown"))
    medium = _first_recommendation(MutableDrsAdapter(identity_mode="medium"))

    assert "vm_identity_unknown" in unknown["blockers"]
    assert "identity_unknown" in unknown["blockers"]
    assert unknown["identity_evidence"]["match_confidence"] == "unknown"
    assert "vm_identity_uncertain" in medium["blockers"]
    assert medium["identity_evidence"]["match_confidence"] == "medium"


def test_high_identity_defaults_to_unknown_migration_policy_blocker():
    recommendation = _first_recommendation(MutableDrsAdapter(identity_mode="high"))

    assert recommendation["identity_evidence"]["match_confidence"] == "high"
    assert recommendation["policy_evidence"]["policy"] == "unknown"
    assert "migration_policy_unknown" in recommendation["blockers"]
    assert "policy_unknown" in recommendation["blockers"]
    assert recommendation["executable"] is False
    assert recommendation["allowed_actions"] == []


def test_restricted_and_blocked_policy_add_canonical_blockers():
    adapter = MutableDrsAdapter(identity_mode="high")
    first = _first_recommendation(adapter)
    vm_identity_id = first["identity_evidence"]["vm_identity_id"]

    _set_policy(vm_identity_id, "restricted")
    restricted = _first_recommendation(adapter)
    assert "migration_policy_restricted" in restricted["blockers"]

    from app.db.models import VmMigrationPolicyRecord
    from app.db.session import session_scope

    with session_scope() as session:
        row = session.get(VmMigrationPolicyRecord, "policy-restricted")
        assert row is not None
        row.policy = "blocked"
    blocked = _first_recommendation(adapter)
    assert "migration_policy_blocked" in blocked["blockers"]


def test_allowed_policy_can_reach_read_only_final_precheck_would_pass():
    from app.drs.advisor import build_drs_check_result

    adapter = MutableDrsAdapter(identity_mode="high")
    first = _first_recommendation(adapter)
    _set_policy(first["identity_evidence"]["vm_identity_id"], "allowed")
    recommendation = _first_recommendation(adapter)

    result = build_drs_check_result(
        adapter,
        recommendation["id"],
        risks=[],
        payload={"recommendation": recommendation},
    )

    assert result["executable"] is False
    assert result["allowed_actions"] == []
    assert result["would_be_executable"] is True
    assert result["identity_evidence"]["match_confidence"] == "high"
    assert result["policy_evidence"]["policy"] == "allowed"
    operation_lock = result["check"]["checks"]["operation_lock"]
    assert operation_lock["status"] == "pass"
    assert operation_lock["evidence"]["operation_type"] == "drs_migration"
    assert len(operation_lock["evidence"]["checked_scopes"]) == 3
    assert operation_lock["evidence"]["matching_locks"] == []
    checks = result["check"]["checks"]
    assert checks["proxmox_conflicts"]["status"] == "not_collected"
    assert checks["proxmox_config_lock"]["status"] == "pass"
    assert checks["proxmox_active_task"]["status"] == "not_collected"
    assert checks["proxmox_ha_state"]["status"] == "not_collected"
    assert checks["proxmox_cluster_quorum"]["status"] == "not_collected"
    conflicts = checks["proxmox_conflicts"]["evidence"]
    assert conflicts["config_lock"]["status"] == "pass"
    assert conflicts["active_task"]["status"] == "not_collected"
    assert conflicts["ha_state"]["status"] == "not_collected"
    assert conflicts["cluster_quorum"]["status"] == "not_collected"


@pytest.mark.parametrize(
    ("status", "expected_blocker"),
    [
        ("active", "operation_lock_active"),
        ("stale", "operation_lock_stale"),
        ("reconciliation_required", "operation_lock_reconciliation_required"),
    ],
)
def test_open_operation_locks_block_final_precheck(status, expected_blocker):
    from app.drs.advisor import build_drs_check_result

    adapter = MutableDrsAdapter(identity_mode="high")
    first = _first_recommendation(adapter)
    _set_policy(first["identity_evidence"]["vm_identity_id"], "allowed")
    recommendation = _first_recommendation(adapter)
    _set_operation_lock(recommendation, status)

    result = build_drs_check_result(
        adapter,
        recommendation["id"],
        risks=[],
        payload={"recommendation": recommendation},
    )

    assert result["would_be_executable"] is False
    assert expected_blocker in result["blockers"]
    assert "drs_final_precheck_failed" in result["blockers"]
    operation_lock = result["check"]["checks"]["operation_lock"]
    assert operation_lock["status"] == "failed"
    assert operation_lock["evidence"]["matching_locks"][0]["status"] == status


def test_locator_operation_lock_matches_cluster_and_vmid_not_source_node():
    from app.drs.advisor import build_drs_check_result

    adapter = MutableDrsAdapter(identity_mode="high")
    first = _first_recommendation(adapter)
    _set_policy(first["identity_evidence"]["vm_identity_id"], "allowed")
    recommendation = _first_recommendation(adapter)
    _set_operation_lock(
        recommendation,
        "active",
        scope_type="proxmox_locator",
        source_node_id="different-source-node",
    )

    result = build_drs_check_result(
        adapter,
        recommendation["id"],
        risks=[],
        payload={"recommendation": recommendation},
    )

    operation_lock = result["check"]["checks"]["operation_lock"]
    locator_scope = next(
        item for item in operation_lock["evidence"]["checked_scopes"] if item["scope_type"] == "proxmox_locator"
    )
    matching_lock = operation_lock["evidence"]["matching_locks"][0]
    assert result["would_be_executable"] is False
    assert "operation_lock_active" in result["blockers"]
    assert locator_scope["scope_key"] == "cluster-a|proxmox_locator|101"
    assert recommendation["source_node_id"] not in locator_scope["scope_key"]
    assert matching_lock["scope_type"] == "proxmox_locator"
    assert matching_lock["source_node_id"] == "different-source-node"


def test_released_operation_lock_does_not_block_final_precheck():
    from app.drs.advisor import build_drs_check_result

    adapter = MutableDrsAdapter(identity_mode="high")
    first = _first_recommendation(adapter)
    _set_policy(first["identity_evidence"]["vm_identity_id"], "allowed")
    recommendation = _first_recommendation(adapter)
    _set_operation_lock(recommendation, "released", scope_type="route")

    result = build_drs_check_result(
        adapter,
        recommendation["id"],
        risks=[],
        payload={"recommendation": recommendation},
    )

    assert result["would_be_executable"] is True
    assert result["check"]["checks"]["operation_lock"]["status"] == "pass"
    assert result["check"]["checks"]["operation_lock"]["evidence"]["matching_locks"] == []


def test_config_lock_blocks_final_precheck_and_reports_unsupported_evidence():
    from app.drs.advisor import build_drs_check_result

    adapter = MutableDrsAdapter(identity_mode="high", config_lock="backup")
    first = _first_recommendation(adapter)
    _set_policy(first["identity_evidence"]["vm_identity_id"], "allowed")
    recommendation = _first_recommendation(adapter)

    result = build_drs_check_result(
        adapter,
        recommendation["id"],
        risks=[],
        payload={"recommendation": recommendation},
    )

    assert result["would_be_executable"] is False
    assert "vm_config_lock" in result["blockers"]
    checks = result["check"]["checks"]
    conflicts = checks["proxmox_conflicts"]
    assert checks["proxmox_config_lock"]["status"] == "failed"
    assert checks["proxmox_active_task"]["status"] == "not_collected"
    assert checks["proxmox_ha_state"]["status"] == "not_collected"
    assert checks["proxmox_cluster_quorum"]["status"] == "not_collected"
    assert conflicts["status"] == "failed"
    assert checks["proxmox_config_lock"]["evidence"] == {
        "status": "conflict",
        "blocking": True,
        "source": "vm_config.lock",
        "lock": "backup",
    }
    assert conflicts["evidence"]["active_task"]["status"] == "not_collected"
    assert conflicts["evidence"]["ha_state"]["status"] == "not_collected"
    assert conflicts["evidence"]["cluster_quorum"]["status"] == "not_collected"


def test_stale_or_changed_vm_state_blocks_final_precheck_result():
    from app.drs.advisor import build_drs_check_result

    adapter = MutableDrsAdapter(identity_mode="high")
    first = _first_recommendation(adapter)
    _set_policy(first["identity_evidence"]["vm_identity_id"], "allowed")
    recommendation = _first_recommendation(adapter)
    adapter.set_vm_status("stopped")

    result = build_drs_check_result(
        adapter,
        recommendation["id"],
        risks=[],
        payload={"recommendation": recommendation},
    )

    assert result["executable"] is False
    assert result["would_be_executable"] is False
    assert "stale_recommendation" in result["blockers"]
    assert "drs_final_precheck_failed" in result["blockers"]
    assert result["check"]["checks"]["vm_state"]["status"] == "failed"
