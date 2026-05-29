"""Contract tests for the read-only /api/v1 DRS Advisor surface."""

import contextlib
import io
import unittest
from unittest.mock import patch

from fastapi import HTTPException


class ApiV1DrsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            from app.main import app
        cls.paths = {getattr(route, "path", "") for route in app.routes}

    def test_drs_routes_exist_under_api_v1_without_mutation_routes(self):
        expected = {
            "/api/v1/drs/summary",
            "/api/v1/drs/recommendations",
            "/api/v1/drs/recommendations/{recommendation_id}",
            "/api/v1/drs/recommendations/{recommendation_id}/check",
            "/api/v1/drs/recommendations/{recommendation_id}/approval-packets",
        }
        self.assertEqual([], sorted(expected - self.paths))
        self.assertNotIn("/api/v1/drs/recommendations/{recommendation_id}/check-now", self.paths)
        self.assertNotIn("/api/v1/drs/recommendations/{recommendation_id}/approve", self.paths)
        self.assertNotIn("/api/v1/drs/recommendations/{recommendation_id}/migrate", self.paths)
        self.assertNotIn("/api/v1/drs/recommendations/{recommendation_id}/migration", self.paths)
        self.assertNotIn("/api/v1/drs/recommendations/{recommendation_id}/live-migrate", self.paths)

    def test_recommendations_are_read_only_and_filter_candidates(self):
        from app.api.v1 import router as v1_router

        with patch.object(v1_router, "_inventory_adapter", return_value=_adapter()), patch.object(
            v1_router,
            "_drs_risks",
            return_value=[{"level": "red", "vmid": 104, "code": "vm_blocked"}],
        ):
            response = v1_router.list_drs_recommendations()

        self.assertTrue(response["ok"])
        data = response["data"]
        recommendations = data["recommendations"]
        self.assertEqual([101], [item["vmid"] for item in recommendations])
        self.assertTrue(data["read_only"])
        self.assertFalse(data["executable"])
        self.assertEqual([], data["allowed_actions"])
        self.assertEqual(70, data["thresholds"]["hot"])
        self.assertEqual(85, data["thresholds"]["critical"])
        self.assertEqual(25, data["thresholds"]["source_target_delta"])
        recommendation = recommendations[0]
        self.assertFalse(recommendation["executable"])
        self.assertFalse(recommendation["execution"]["available"])
        self.assertEqual([], recommendation["execution"]["allowed_actions"])
        self.assertEqual(
            {"migration_policy_unknown", "policy_unknown", "final_precheck_not_run"},
            set(recommendation["blockers"]),
        )
        self.assertEqual("high", recommendation["identity_evidence"]["match_confidence"])
        self.assertEqual("unknown", recommendation["policy_evidence"]["policy"])
        self.assertEqual(2, data["summary"]["running_candidate_vms"])
        self.assertEqual(1, data["summary"]["excluded_red_risk_vms"])

    def test_blockers_include_policy_route_local_and_passthrough(self):
        from app.api.v1 import router as v1_router

        adapter = _adapter(
            storage_id="local-lvm",
            storage_type="lvmthin",
            target_network=False,
            vm_tags=("gpu", "prod"),
        )
        with patch.object(v1_router, "_inventory_adapter", return_value=adapter), patch.object(
            v1_router,
            "_drs_risks",
            return_value=[],
        ):
            recommendation = v1_router.list_drs_recommendations()["data"]["recommendations"][0]

        self.assertNotIn("vm_identity_unknown", recommendation["blockers"])
        self.assertNotIn("metadata_missing", recommendation["blockers"])
        self.assertIn("migration_policy_unknown", recommendation["blockers"])
        self.assertIn("policy_unknown", recommendation["blockers"])
        self.assertIn("final_precheck_not_run", recommendation["blockers"])
        self.assertIn("route_unknown", recommendation["blockers"])
        self.assertIn("local_storage_dependency", recommendation["blockers"])
        self.assertIn("passthrough_device_dependency", recommendation["blockers"])
        self.assertEqual(["gpu"], recommendation["evidence"]["passthrough"]["matched_tags"])
        self.assertFalse(recommendation["evidence"]["route"]["network_evidence_sufficient"])

    def test_target_over_threshold_blocks_projected_critical_target_pressure(self):
        from app.api.v1 import router as v1_router

        adapter = _adapter(source_cpu=99, source_memory=96, target_cpu=74, target_memory=74)
        with patch.object(v1_router, "_inventory_adapter", return_value=adapter), patch.object(
            v1_router,
            "_drs_risks",
            return_value=[{"level": "red", "vmid": 104, "code": "vm_blocked"}],
        ):
            recommendation = v1_router.list_drs_recommendations()["data"]["recommendations"][0]

        self.assertIn("target_over_threshold", recommendation["blockers"])
        self.assertGreaterEqual(
            recommendation["estimated_effect"]["target_pressure_after"],
            recommendation["thresholds"]["critical"],
        )
        self.assertTrue(recommendation["evidence"]["target_over_threshold"]["blocked"])
        self.assertFalse(recommendation["executable"])
        self.assertFalse(recommendation["execution"]["available"])

    def test_route_unknown_when_only_unrelated_target_storage_has_free_space(self):
        from app.api.v1 import router as v1_router

        adapter = _adapter(
            target_storage_free=10,
            extra_target_storage_id="spacious-nfs",
            extra_target_storage_free=1000,
        )
        with patch.object(v1_router, "_inventory_adapter", return_value=adapter), patch.object(
            v1_router,
            "_drs_risks",
            return_value=[{"level": "red", "vmid": 104, "code": "vm_blocked"}],
        ):
            recommendation = v1_router.list_drs_recommendations()["data"]["recommendations"][0]

        self.assertIn("route_unknown", recommendation["blockers"])
        self.assertFalse(recommendation["evidence"]["route"]["storage_evidence_sufficient"])
        self.assertIn("shared-nfs", recommendation["evidence"]["route"]["target_storage_ids"])
        self.assertIn("spacious-nfs", recommendation["evidence"]["route"]["target_storage_ids"])
        self.assertFalse(recommendation["executable"])

    def test_detail_404s_unknown_recommendation_id(self):
        from app.api.v1 import router as v1_router

        with patch.object(v1_router, "_inventory_adapter", return_value=_adapter()), patch.object(
            v1_router,
            "_drs_risks",
            return_value=[],
        ):
            with self.assertRaises(HTTPException) as context:
                v1_router.get_drs_recommendation("missing")

        self.assertEqual(404, context.exception.status_code)

    def test_check_recalculates_reference_only_without_job_writes(self):
        from app.api.v1 import router as v1_router

        adapter = _adapter()
        with patch.object(v1_router, "_inventory_adapter", return_value=adapter), patch.object(
            v1_router,
            "_drs_risks",
            return_value=[],
        ), patch.object(v1_router, "record_job_run") as record_job_run:
            recommendation_id = v1_router.list_drs_recommendations()["data"]["recommendations"][0]["id"]
            response = v1_router.check_drs_recommendation(recommendation_id, {})

        self.assertTrue(response["ok"])
        data = response["data"]
        self.assertEqual(recommendation_id, data["recommendation_id"])
        self.assertTrue(data["read_only"])
        self.assertFalse(data["executable"])
        self.assertTrue(data["check"]["reference_only"])
        self.assertTrue(data["check"]["recalculated"])
        self.assertFalse(data["execution"]["available"])
        self.assertEqual([], data["allowed_actions"])
        self.assertFalse(data["approval_readiness"]["runnable"])
        self.assertFalse(data["approval_readiness"]["proxmox_mutation_enabled"])
        self.assertEqual([], data["approval_readiness"]["allowed_actions"])
        self.assertEqual("drs_migration", data["check"]["checks"]["operation_lock"]["evidence"]["operation_type"])
        self.assertIn("proxmox_conflicts", data["check"]["checks"])
        record_job_run.assert_not_called()

    def test_approval_packet_route_creates_local_non_runnable_job_without_proxmox_mutation(self):
        from app.api.v1 import router as v1_router
        from app.auth.roles import AuthenticatedUser

        adapter = _adapter()
        actor = AuthenticatedUser(user_id="operator-1", username="operator", role="operator")
        with patch.object(v1_router, "_inventory_adapter", return_value=adapter), patch.object(
            v1_router,
            "_drs_risks",
            return_value=[{"level": "red", "vmid": 104, "code": "vm_blocked"}],
        ), patch.object(v1_router, "get_default_proxmox_mutation_client") as mutation_client, patch.object(
            v1_router,
            "run_proxmox_create",
        ) as create_mutation:
            recommendation = v1_router.list_drs_recommendations()["data"]["recommendations"][0]
            _set_policy(recommendation["identity_evidence"]["vm_identity_id"], "allowed")
            recommendation = v1_router.list_drs_recommendations()["data"]["recommendations"][0]
            response = v1_router.create_drs_approval_packet(
                recommendation["id"],
                {
                    "recommendation": recommendation,
                    "actor": {"user_id": "payload-user", "username": "payload", "role": "admin"},
                    "source_node_id": "payload-source",
                    "target_node_id": "payload-target",
                    "vmid": 999,
                    "blockers": ["payload-blocker"],
                },
                actor=actor,
            )

        self.assertTrue(response["ok"])
        self.assertEqual("drs_local_approval_packet_no_mutation", response["meta"]["mode"])
        data = response["data"]
        self.assertFalse(data["executable"])
        self.assertEqual([], data["allowed_actions"])
        self.assertFalse(data["runnable"])
        self.assertFalse(data["proxmox_mutation_enabled"])
        self.assertEqual([], data["side_effects"])
        self.assertEqual("approved", data["approval_packet"]["packet_status"])
        self.assertEqual(recommendation["id"], data["approval_packet"]["recommendation_id"])
        self.assertEqual(recommendation["identity_evidence"]["vm_identity_id"], data["approval_packet"]["vm_identity_id"])
        self.assertEqual(recommendation["source_node_id"], data["approval_packet"]["source_node_id"])
        self.assertEqual(recommendation["target_node_id"], data["approval_packet"]["target_node_id"])
        self.assertEqual("operator", data["approval_packet"]["actor_username"])
        self.assertEqual("operator", data["job_intent"]["approved_actor"]["username"])
        self.assertEqual("pending", data["job_intent"]["status"])
        self.assertFalse(data["job_intent"]["runnable"])
        self.assertFalse(data["job_intent"]["proxmox_mutation_enabled"])
        self.assertEqual([], data["job_intent"]["side_effects"])
        self.assertIn("live_migration_execution_not_implemented", data["job_intent"]["runnable_blockers"])
        self.assertEqual("would_pass", data["job_intent"]["final_precheck_summary"]["status"])
        mutation_client.assert_not_called()
        create_mutation.assert_not_called()


def _adapter(
    *,
    storage_id="shared-nfs",
    storage_type="nfs",
    target_network=True,
    vm_tags=(),
    source_cpu=82,
    source_memory=75,
    target_cpu=31,
    target_memory=40,
    target_storage_free=700,
    extra_target_storage_id=None,
    extra_target_storage_free=0,
):
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

    class StubDrsAdapter:
        source = "stub_read_only"

        def __init__(self):
            storages = [
                StorageInventory(storage_id, "node-a", storage_type, 1024, 600, ("images",)),
                StorageInventory(storage_id, "node-b", storage_type, 1024, target_storage_free, ("images",)),
            ]
            if extra_target_storage_id:
                storages.append(
                    StorageInventory(extra_target_storage_id, "node-b", "nfs", 2048, extra_target_storage_free, ("images",))
                )
            self._storages = tuple(storages)
            self._networks = (
                NetworkInventory("vmbr0", "node-a", active=True),
                *(() if not target_network else (NetworkInventory("vmbr0", "node-b", active=True),)),
            )
            self._nodes = (
                NodeInventory(
                    "node-a",
                    "node-a",
                    "online",
                    32,
                    131072,
                    cpu_usage_percent=source_cpu,
                    memory_used_mb=98304,
                    memory_usage_percent=source_memory,
                    storage=tuple(item for item in self._storages if item.node_id == "node-a"),
                    networks=tuple(item for item in self._networks if item.node_id == "node-a"),
                ),
                NodeInventory(
                    "node-b",
                    "node-b",
                    "online",
                    32,
                    131072,
                    cpu_usage_percent=target_cpu,
                    memory_used_mb=52428,
                    memory_usage_percent=target_memory,
                    storage=tuple(item for item in self._storages if item.node_id == "node-b"),
                    networks=tuple(item for item in self._networks if item.node_id == "node-b"),
                ),
            )
            self._vms = (
                _vm(101, "app-01", "running", False, storage_id, vm_tags),
                _vm(102, "stopped-01", "stopped", False, storage_id, ()),
                _vm(103, "template-01", "running", True, storage_id, ()),
                _vm(104, "red-risk-01", "running", False, storage_id, ()),
            )

        def snapshot(self):
            return InventorySnapshot(
                source=self.source,
                observed_at="2026-05-21T00:00:00+09:00",
                nodes=self._nodes,
                vms=self._vms,
                templates=(),
                connection={"source": self.source},
            )

        def list_nodes(self):
            return list(self._nodes)

        def list_vms(self):
            return list(self._vms)

        def list_storage(self, node_id=None):
            return [item for item in self._storages if node_id is None or item.node_id == node_id]

        def list_networks(self, node_id=None):
            return [item for item in self._networks if node_id is None or item.node_id == node_id]

    def _vm(vmid, name, status, template, vm_storage_id, tags):
        return VmInventory(
            vmid=vmid,
            name=name,
            node_id="node-a",
            status=status,
            template=template,
            cpu=2,
            memory_mb=8192,
            disk_gb=40,
            guest_agent=GuestAgentInventory(available=True),
            tags=tuple(tags),
            storage_id=vm_storage_id,
            nic_bridge_evidence=(
                NicBridgeEvidenceInventory(interface_name="net0", bridge_id="vmbr0", model="virtio"),
            ),
            disks=(
                DiskInventory(
                    device="scsi0",
                    bus="scsi",
                    index=0,
                    size_gb=40,
                    storage_id=vm_storage_id,
                    volume_id=f"{vm_storage_id}:vm-{vmid}-disk-0",
                    volume=f"vm-{vmid}-disk-0",
                    boot=True,
                ),
            ),
        )

    return StubDrsAdapter()


def _set_policy(vm_identity_id, policy):
    from app.db.models import VmMigrationPolicyRecord
    from app.db.session import session_scope

    with session_scope() as session:
        session.add(
            VmMigrationPolicyRecord(
                policy_id=f"policy-{policy}-{vm_identity_id}",
                vm_identity_id=vm_identity_id,
                policy=policy,
                reason=f"{policy} in API contract test",
                source="manual",
                updated_by="test",
            )
        )


if __name__ == "__main__":
    unittest.main()
