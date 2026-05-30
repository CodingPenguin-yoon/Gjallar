from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest
from sqlalchemy import select


class PolicyAdapter:
    source = "policy_stub_read_only"

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
        self._storage_id = "shared-nfs"
        self._storages = (
            StorageInventory(self._storage_id, "node-a", "nfs", 1024, 600, ("images",)),
            StorageInventory(self._storage_id, "node-b", "nfs", 1024, 700, ("images",)),
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
        self._vms = (
            VmInventory(
                vmid=101,
                name="app-01",
                node_id="node-a",
                status="running",
                template=False,
                cpu=2,
                memory_mb=8192,
                disk_gb=40,
                guest_agent=GuestAgentInventory(available=True),
                storage_id=self._storage_id,
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
                        storage_id=self._storage_id,
                        volume_id=f"{self._storage_id}:vm-101-disk-0",
                        volume="vm-101-disk-0",
                        boot=True,
                    ),
                ),
            ),
            VmInventory(
                vmid=102,
                name="medium-identity",
                node_id="node-a",
                status="running",
                template=False,
                cpu=1,
                memory_mb=2048,
                disk_gb=20,
                guest_agent=GuestAgentInventory(available=True),
                storage_id="unknown",
                mac_addresses=("aa:bb:cc:dd:ee:01",),
                nic_bridge_evidence=(
                    NicBridgeEvidenceInventory(
                        interface_name="net0",
                        bridge_id="vmbr0",
                        model="virtio",
                        mac_address="aa:bb:cc:dd:ee:01",
                    ),
                ),
            ),
            VmInventory(
                vmid=9000,
                name="template",
                node_id="node-a",
                status="running",
                template=True,
                cpu=1,
                memory_mb=1024,
                disk_gb=10,
                guest_agent=GuestAgentInventory(available=False),
            ),
        )

    def snapshot(self):
        return self._snapshot_type(
            source=self.source,
            observed_at="2026-05-31T00:00:00+00:00",
            nodes=self._nodes,
            vms=self._vms,
            templates=(),
            connection={"source": self.source, "cluster_id": "cluster-a"},
        )

    def list_nodes(self):
        return list(self._nodes)

    def list_vms(self):
        return list(self._vms)

    def list_storage(self, node_id=None):
        return [item for item in self._storages if node_id is None or item.node_id == node_id]

    def list_networks(self, node_id=None):
        return [item for item in self._networks if node_id is None or item.node_id == node_id]

    def retire_high_identity(self, vm_identity_id: str):
        from app.db.models import VmIdentityRecord
        from app.db.session import session_scope

        with session_scope() as session:
            identity = session.get(VmIdentityRecord, vm_identity_id)
            identity.identity_status = "retired"

    def move_high_vm(self):
        self._vms = tuple(
            replace(vm, node_id="node-b") if vm.vmid == 101 else vm
            for vm in self._vms
        )


def _actor():
    from app.auth.roles import AuthenticatedUser

    return AuthenticatedUser(user_id="operator-1", username="operator", role="operator")


def _policy_model(adapter):
    from app.drs.policies import list_drs_policy_items

    return list_drs_policy_items(adapter, risks=[])


def _high_item(adapter):
    model = _policy_model(adapter)
    return next(item for item in model["items"] if item["identity_confidence"] == "high")


def _update_payload(item, policy="allowed", reason="classified for DRS testing", **extra):
    return {
        "policy": policy,
        "reason": reason,
        "policy_change_acknowledged": True,
        "expected_observation": item["expected_observation"],
        **extra,
    }


def _policy_event_count():
    from app.db.models import VmMigrationPolicyEventRecord
    from app.db.session import session_scope

    with session_scope() as session:
        return len(session.scalars(select(VmMigrationPolicyEventRecord)).all())


def _policy_count():
    from app.db.models import VmMigrationPolicyRecord
    from app.db.session import session_scope

    with session_scope() as session:
        return len(session.scalars(select(VmMigrationPolicyRecord)).all())


def test_policy_read_model_includes_current_non_template_vms_and_write_blockers():
    adapter = PolicyAdapter()
    model = _policy_model(adapter)

    assert model["read_only"] is True
    assert model["executable"] is False
    assert model["allowed_actions"] == []
    assert model["coverage"]["total_non_template_vms"] == 2
    assert {item["current_locator"]["vmid"] for item in model["items"]} == {101, 102}

    high = next(item for item in model["items"] if item["current_locator"]["vmid"] == 101)
    uncertain = next(item for item in model["items"] if item["current_locator"]["vmid"] == 102)
    assert high["vm_identity_id"]
    assert high["identity_confidence"] == "high"
    assert high["policy"]["value"] == "unknown"
    assert high["policy_write_allowed"] is True
    assert high["expected_observation"]["cluster_id"] == "cluster-a"
    assert high["expected_observation"]["fingerprint_hash"].startswith("sha256:")
    assert high["latest_observation"]["observation_id"]
    assert "migration_policy_unknown" in high["drs_blocker_impact"]["policy_blockers"]
    assert uncertain["vm_identity_id"] is None
    assert uncertain["policy_write_allowed"] is False
    assert "policy_write_identity_uncertain" in uncertain["policy_write_blockers"]


def test_valid_update_uses_trusted_actor_audits_and_reflects_allowed_in_drs_gates():
    from app.db.models import VmMigrationPolicyEventRecord, VmMigrationPolicyRecord
    from app.db.session import session_scope
    from app.drs.advisor import build_drs_advisor_model, build_drs_check_result
    from app.drs.policies import update_drs_policy

    adapter = PolicyAdapter()
    item = _high_item(adapter)
    response = update_drs_policy(
        adapter,
        item["vm_identity_id"],
        _update_payload(
            item,
            actor={"user_id": "spoof", "username": "spoof", "role": "admin"},
            source="tag",
            updated_by="spoof",
        ),
        actor=_actor(),
        risks=[],
    )

    assert response["audit_event_created"] is True
    assert response["audit_event_id"]
    assert response["actor"] == {"user_id": "operator-1", "username": "operator", "role": "operator"}
    assert response["new_policy"]["policy"] == "allowed"
    assert response["policy_item"]["policy"]["value"] == "allowed"
    assert response["check_impact"]["executable"] is False
    assert response["check_impact"]["allowed_actions"] == []

    with session_scope() as session:
        policy = session.scalars(select(VmMigrationPolicyRecord)).one()
        event = session.scalars(select(VmMigrationPolicyEventRecord)).one()
        assert policy.vm_identity_id == item["vm_identity_id"]
        assert policy.policy == "allowed"
        assert policy.source == "manual"
        assert policy.updated_by == "operator"
        assert event.old_policy == "unknown"
        assert event.new_policy == "allowed"
        assert event.source == "manual"
        assert event.actor_user_id == "operator-1"
        assert event.actor_username == "operator"
        assert event.actor_role == "operator"
        assert event.expected_observation["cluster_id"] == "cluster-a"
        assert event.current_observation["fingerprint_hash"] == item["expected_observation"]["fingerprint_hash"]

    recommendation = next(
        rec
        for rec in build_drs_advisor_model(adapter, risks=[])["recommendations"]
        if rec["identity_evidence"]["vm_identity_id"] == item["vm_identity_id"]
    )
    assert recommendation["policy_evidence"]["policy"] == "allowed"
    assert "migration_policy_unknown" not in recommendation["blockers"]
    assert recommendation["executable"] is False
    assert recommendation["allowed_actions"] == []

    check = build_drs_check_result(adapter, recommendation["id"], risks=[], payload={"recommendation": recommendation})
    assert check["policy_evidence"]["policy"] == "allowed"
    assert check["would_be_executable"] is True
    assert check["executable"] is False
    assert check["allowed_actions"] == []


@pytest.mark.parametrize(
    ("payload_update", "expected_code"),
    [
        ({"policy_change_acknowledged": False}, "DRS_POLICY_ACK_REQUIRED"),
        ({"reason": ""}, "DRS_POLICY_REASON_REQUIRED"),
        ({"policy": "invalid"}, "DRS_POLICY_INVALID_VALUE"),
    ],
)
def test_update_validation_rejects_ack_reason_and_policy_without_mutation(payload_update, expected_code):
    from app.drs.policies import DrsPolicyServiceError, update_drs_policy

    adapter = PolicyAdapter()
    item = _high_item(adapter)
    payload = _update_payload(item)
    payload.update(payload_update)

    with pytest.raises(DrsPolicyServiceError) as exc:
        update_drs_policy(adapter, item["vm_identity_id"], payload, actor=_actor(), risks=[])

    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == expected_code
    assert _policy_count() == 0
    assert _policy_event_count() == 0


def test_stale_or_mismatched_expected_observation_rejects_without_mutation():
    from app.drs.policies import DrsPolicyServiceError, update_drs_policy

    adapter = PolicyAdapter()
    item = _high_item(adapter)
    expected = dict(item["expected_observation"])
    expected["node_id"] = "node-stale"

    with pytest.raises(DrsPolicyServiceError) as exc:
        update_drs_policy(
            adapter,
            item["vm_identity_id"],
            {
                "policy": "allowed",
                "reason": "stale guard",
                "policy_change_acknowledged": True,
                "expected_observation": expected,
            },
            actor=_actor(),
            risks=[],
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "DRS_POLICY_EXPECTED_OBSERVATION_MISMATCH"
    assert "node_id" in exc.value.detail["mismatches"]
    assert _policy_count() == 0
    assert _policy_event_count() == 0


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("cluster_id", "cluster-stale"),
        ("vmid", 9999),
        ("fingerprint_hash", "sha256:stale"),
        ("observed_at", "2026-05-30T00:00:00+00:00"),
    ],
)
def test_expected_observation_guard_field_mismatches_reject_without_mutation(field, replacement):
    from app.drs.policies import DrsPolicyServiceError, update_drs_policy

    adapter = PolicyAdapter()
    item = _high_item(adapter)
    expected = dict(item["expected_observation"])
    expected[field] = replacement

    with pytest.raises(DrsPolicyServiceError) as exc:
        update_drs_policy(
            adapter,
            item["vm_identity_id"],
            {
                "policy": "allowed",
                "reason": f"{field} guard mismatch",
                "policy_change_acknowledged": True,
                "expected_observation": expected,
            },
            actor=_actor(),
            risks=[],
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "DRS_POLICY_EXPECTED_OBSERVATION_MISMATCH"
    assert field in exc.value.detail["mismatches"]
    assert _policy_count() == 0
    assert _policy_event_count() == 0


def test_retired_or_non_high_current_identity_blocks_policy_write():
    from app.drs.policies import DrsPolicyServiceError, update_drs_policy

    adapter = PolicyAdapter()
    item = _high_item(adapter)
    adapter.retire_high_identity(item["vm_identity_id"])

    next_item = next(
        candidate
        for candidate in _policy_model(adapter)["items"]
        if candidate["vm_identity_id"] == item["vm_identity_id"]
    )
    assert next_item["policy_write_allowed"] is False
    assert "policy_write_identity_retired" in next_item["policy_write_blockers"]
    assert "policy_write_latest_observation_not_high" in next_item["policy_write_blockers"]
    with pytest.raises(DrsPolicyServiceError) as exc:
        update_drs_policy(adapter, next_item["vm_identity_id"], _update_payload(next_item), actor=_actor(), risks=[])

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "DRS_POLICY_IDENTITY_NOT_ACTIVE"
    assert _policy_count() == 0
    assert _policy_event_count() == 0


def test_idempotent_same_policy_reason_does_not_create_second_audit_event():
    from app.drs.policies import update_drs_policy

    adapter = PolicyAdapter()
    item = _high_item(adapter)
    first = update_drs_policy(adapter, item["vm_identity_id"], _update_payload(item), actor=_actor(), risks=[])
    second_item = _high_item(adapter)
    second = update_drs_policy(adapter, second_item["vm_identity_id"], _update_payload(second_item), actor=_actor(), risks=[])

    assert first["audit_event_created"] is True
    assert second["idempotent"] is True
    assert second["audit_event_created"] is False
    assert second["audit_event_id"] is None
    assert _policy_count() == 1
    assert _policy_event_count() == 1


def test_unknown_restricted_and_blocked_policies_keep_drs_blocked():
    from app.drs.advisor import build_drs_advisor_model, build_drs_check_result
    from app.drs.policies import update_drs_policy

    adapter = PolicyAdapter()
    item = _high_item(adapter)
    update_drs_policy(adapter, item["vm_identity_id"], _update_payload(item), actor=_actor(), risks=[])

    for policy, expected_blocker in [
        ("restricted", "migration_policy_restricted"),
        ("blocked", "migration_policy_blocked"),
        ("unknown", "migration_policy_unknown"),
    ]:
        item = _high_item(adapter)
        reason = "" if policy == "unknown" else f"{policy} policy test"
        update_drs_policy(adapter, item["vm_identity_id"], _update_payload(item, policy=policy, reason=reason), actor=_actor(), risks=[])
        recommendation = next(
            rec
            for rec in build_drs_advisor_model(adapter, risks=[])["recommendations"]
            if rec["identity_evidence"]["vm_identity_id"] == item["vm_identity_id"]
        )
        check = build_drs_check_result(adapter, recommendation["id"], risks=[], payload={"recommendation": recommendation})
        assert expected_blocker in recommendation["blockers"]
        assert expected_blocker in check["blockers"]
        assert check["would_be_executable"] is False
        assert check["executable"] is False
        assert check["allowed_actions"] == []


def test_policy_and_audit_event_are_atomic_when_audit_insert_fails(monkeypatch):
    from app.db.models import VmMigrationPolicyEventRecord, VmMigrationPolicyRecord
    from app.db.session import session_scope
    from app.drs import policies as policy_service

    adapter = PolicyAdapter()
    item = _high_item(adapter)
    expected = item["expected_observation"]
    observed_at = datetime.fromisoformat(expected["observed_at"])
    with session_scope() as session:
        session.add(
            VmMigrationPolicyEventRecord(
                event_id="fixed-event",
                vm_identity_id=item["vm_identity_id"],
                policy_id=None,
                old_policy="unknown",
                new_policy="unknown",
                reason="preexisting event",
                source="manual",
                actor_user_id="test",
                actor_username="test",
                actor_role="operator",
                request_id="preexisting",
                cluster_id=expected["cluster_id"],
                node_id=expected["node_id"],
                vmid=expected["vmid"],
                fingerprint_hash=expected["fingerprint_hash"],
                observed_at=observed_at,
                expected_observation=expected,
                current_observation=expected,
                validation_result={"status": "preexisting"},
            )
        )
    monkeypatch.setattr(policy_service, "_event_id", lambda: "fixed-event")

    with pytest.raises(Exception):
        policy_service.update_drs_policy(adapter, item["vm_identity_id"], _update_payload(item), actor=_actor(), risks=[])

    with session_scope() as session:
        assert session.scalars(select(VmMigrationPolicyRecord)).all() == []
        assert len(session.scalars(select(VmMigrationPolicyEventRecord)).all()) == 1
