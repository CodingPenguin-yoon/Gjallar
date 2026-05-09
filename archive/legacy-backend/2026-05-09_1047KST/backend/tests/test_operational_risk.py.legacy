import inspect
import io
import time
import unittest
from contextlib import redirect_stdout

from app.domains.proxmox import service as proxmox_service_module
from app.domains.proxmox.risk import apply_risk_overrides, build_operational_risk_dashboard
from app.domains.proxmox.service import ProxmoxService, VMInventorySnapshot


class OperationalRiskDashboardTest(unittest.TestCase):
    def _set_cluster_snapshot(self, service, vms, *, complete=True):
        service._get_all_vms_inventory_snapshot = lambda: VMInventorySnapshot(
            items=vms,
            complete=complete,
            scope="cluster",
        )

    def test_builds_read_only_operational_risk_summary(self):
        now = 1_700_000_000
        vms = [
            {
                "node": "node-a",
                "vmid": 101,
                "name": "app-01",
                "status": "running",
                "tags": [],
                "description": "",
                "configured_ipv4_addresses": ["192.0.2.10"],
                "guest_agent_ipv4_addresses": [],
            },
            {
                "node": "node-a",
                "vmid": 102,
                "name": "db-01",
                "status": "running",
                "tags": ["owner:yoon", "env:prod"],
                "guest_agent_ipv4_addresses": ["192.0.2.11"],
            },
        ]
        nodes = [
            {
                "node": "node-a",
                "status": "online",
                "storages": [
                    {"name": "vm-storage", "usage_percent": 92.5, "available_gb": 80, "total_gb": 1000}
                ],
            }
        ]
        snapshots = {
            "node-a/101": [
                {"name": "current"},
                {"name": "before-upgrade", "snaptime": now - 31 * 86400},
            ],
            "node-a/102": [],
        }
        backups = {
            "node-a/101": [],
            "node-a/102": [{"type": "vzdump", "status": "OK", "endtime": now - 2 * 86400}],
        }

        dashboard = build_operational_risk_dashboard(
            vms,
            nodes,
            snapshots_by_vm=snapshots,
            backup_tasks_by_vm=backups,
            now=now,
        )

        self.assertEqual(dashboard["status"], "critical")
        self.assertEqual(dashboard["summary"]["critical"], 2)
        self.assertEqual(dashboard["summary"]["warning"], 2)
        self.assertEqual(dashboard["summary"]["info"], 2)
        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertIn("storage:node-a:vm-storage:capacity", risk_ids)
        self.assertIn("vm:node-a/101:guest-agent", risk_ids)
        self.assertIn("vm:node-a/101:owner-tag", risk_ids)
        self.assertIn("vm:node-a/101:snapshot:before-upgrade", risk_ids)
        self.assertIn("vm:node-a/101:backup-recency", risk_ids)
        self.assertIn("vm:node-a/102:compliance:prod-explicit-backup-profile", risk_ids)
        self.assertNotIn("vm:node-a/102:backup-recency", risk_ids)

    def test_incidental_tag_without_owner_or_environment_still_reports_governance_risk(self):
        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 201,
                    "name": "tagged-but-unowned",
                    "status": "running",
                    "tags": ["linux", "docker"],
                    "description": "",
                    "guest_agent_ipv4_addresses": ["192.0.2.20"],
                }
            ],
            [{"node": "node-a", "status": "online", "storages": []}],
            snapshots_by_vm={"node-a/201": []},
            backup_tasks_by_vm={
                "node-a/201": [{"type": "vzdump", "status": "OK", "endtime": 1_700_000_000}]
            },
            now=1_700_000_000,
        )

        risk = next(item for item in dashboard["risk_items"] if item["id"] == "vm:node-a/201:owner-tag")
        self.assertEqual(risk["category"], "governance")
        self.assertEqual(risk["evidence"]["missing_metadata"], ["owner_or_team", "environment"])
        self.assertEqual(risk["evidence"]["incidental_tags"], ["linux", "docker"])

    def test_owner_and_environment_taxonomy_clears_governance_risk(self):
        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 202,
                    "name": "well-owned",
                    "status": "running",
                    "tags": ["owner:yoon", "env:prod", "linux"],
                    "guest_agent_ipv4_addresses": ["192.0.2.21"],
                }
            ],
            [{"node": "node-a", "status": "online", "storages": []}],
            snapshots_by_vm={"node-a/202": []},
            backup_tasks_by_vm={
                "node-a/202": [{"type": "vzdump", "status": "OK", "endtime": 1_700_000_000}]
            },
            now=1_700_000_000,
        )

        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertNotIn("vm:node-a/202:owner-tag", risk_ids)

    def test_description_owner_and_simple_environment_tag_clear_governance_risk(self):
        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 203,
                    "name": "described-owner",
                    "status": "running",
                    "tags": ["lab"],
                    "description": "Owner: homelab",
                    "guest_agent_ipv4_addresses": ["192.0.2.22"],
                }
            ],
            [{"node": "node-a", "status": "online", "storages": []}],
            snapshots_by_vm={"node-a/203": []},
            backup_tasks_by_vm={
                "node-a/203": [{"type": "vzdump", "status": "OK", "endtime": 1_700_000_000}]
            },
            now=1_700_000_000,
        )

        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertNotIn("vm:node-a/203:owner-tag", risk_ids)

    def test_notes_owner_marker_counts_even_when_description_is_generic(self):
        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 204,
                    "name": "notes-owned",
                    "status": "running",
                    "tags": ["env:prod"],
                    "description": "General service notes without owner marker",
                    "notes": "team:infra",
                    "guest_agent_ipv4_addresses": ["192.0.2.23"],
                }
            ],
            [{"node": "node-a", "status": "online", "storages": []}],
            snapshots_by_vm={"node-a/204": []},
            backup_tasks_by_vm={
                "node-a/204": [{"type": "vzdump", "status": "OK", "endtime": 1_700_000_000}]
            },
            now=1_700_000_000,
        )

        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertNotIn("vm:node-a/204:owner-tag", risk_ids)

    def test_alternate_owner_and_environment_separators_clear_governance_risk(self):
        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 205,
                    "name": "alternate-separators",
                    "status": "running",
                    "tags": ["owned_by=platform", "env/prod"],
                    "guest_agent_ipv4_addresses": ["192.0.2.24"],
                }
            ],
            [{"node": "node-a", "status": "online", "storages": []}],
            snapshots_by_vm={"node-a/205": []},
            backup_tasks_by_vm={
                "node-a/205": [{"type": "vzdump", "status": "OK", "endtime": 1_700_000_000}]
            },
            now=1_700_000_000,
        )

        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertNotIn("vm:node-a/205:owner-tag", risk_ids)

    def test_prod_vm_without_explicit_backup_profile_reports_compliance_risk(self):
        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 206,
                    "name": "prod-with-default-profile",
                    "status": "running",
                    "tags": ["owner:yoon", "env:prod"],
                    "guest_agent_ipv4_addresses": ["192.0.2.206"],
                }
            ],
            [{"node": "node-a", "status": "online", "storages": []}],
            snapshots_by_vm={"node-a/206": []},
            backup_tasks_by_vm={"node-a/206": []},
            now=1_700_000_000,
        )

        risk = next(
            item
            for item in dashboard["risk_items"]
            if item["id"] == "vm:node-a/206:compliance:prod-explicit-backup-profile"
        )
        self.assertEqual(risk["category"], "compliance")
        self.assertEqual(risk["severity"], "info")
        self.assertEqual(risk["evidence"]["policy_id"], "default")
        self.assertEqual(risk["evidence"]["rule_id"], "prod-explicit-backup-profile")
        self.assertEqual(risk["evidence"]["rpo_rto_profile_source"], "default")
        self.assertIn("prod", risk["evidence"]["required_environment_values"])
        self.assertIn("critical", risk["evidence"]["accepted_backup_profile_values"])
        self.assertEqual(dashboard["evidence"]["compliance_policy_collected"], True)
        self.assertEqual(dashboard["evidence"]["compliance_policy_source"], "default")
        self.assertIn("prod-explicit-backup-profile", dashboard["evidence"]["compliance_policy_rules"])

    def test_prod_vm_with_explicit_backup_profile_clears_compliance_risk(self):
        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 207,
                    "name": "prod-with-policy",
                    "status": "running",
                    "tags": ["owner:yoon", "env:production", "rpo-profile:critical"],
                    "guest_agent_ipv4_addresses": ["192.0.2.207"],
                }
            ],
            [{"node": "node-a", "status": "online", "storages": []}],
            snapshots_by_vm={"node-a/207": []},
            backup_tasks_by_vm={"node-a/207": []},
            now=1_700_000_000,
        )

        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertNotIn("vm:node-a/207:compliance:prod-explicit-backup-profile", risk_ids)

    def test_prod_vm_with_accepted_backup_profile_aliases_clear_compliance_risk(self):
        accepted_cases = [
            ("backup-profile", "standard", ":"),
            ("recovery-profile", "relaxed", "="),
            ("rpo-profile", "critical", ":"),
            ("rpo-rto-profile", "standard", "/"),
        ]
        for offset, (key, value, separator) in enumerate(accepted_cases, start=1):
            vmid = 220 + offset
            with self.subTest(tag=f"{key}{separator}{value}"):
                dashboard = build_operational_risk_dashboard(
                    [
                        {
                            "node": "node-a",
                            "vmid": vmid,
                            "name": f"prod-profile-alias-{offset}",
                            "status": "running",
                            "tags": ["owner:yoon", "env:prod", f"{key}{separator}{value}"],
                            "guest_agent_ipv4_addresses": [f"192.0.2.{vmid}"],
                        }
                    ],
                    [{"node": "node-a", "status": "online", "storages": []}],
                    snapshots_by_vm={f"node-a/{vmid}": []},
                    backup_tasks_by_vm={f"node-a/{vmid}": []},
                    now=1_700_000_000,
                )

                risk_ids = {item["id"] for item in dashboard["risk_items"]}
                self.assertNotIn(
                    f"vm:node-a/{vmid}:compliance:prod-explicit-backup-profile",
                    risk_ids,
                )

    def test_valid_backup_profile_candidate_after_invalid_candidate_clears_compliance_risk(self):
        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 225,
                    "name": "prod-valid-profile-after-invalid",
                    "status": "running",
                    "tags": [
                        "owner:yoon",
                        "env:prod",
                        "rpo-profile:gold",
                        "backup-profile:standard",
                    ],
                    "guest_agent_ipv4_addresses": ["192.0.2.225"],
                }
            ],
            [{"node": "node-a", "status": "online", "storages": []}],
            snapshots_by_vm={"node-a/225": []},
            backup_tasks_by_vm={"node-a/225": []},
            now=1_700_000_000,
        )

        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertNotIn("vm:node-a/225:compliance:prod-explicit-backup-profile", risk_ids)

    def test_non_prod_vm_without_explicit_backup_profile_skips_first_compliance_rule(self):
        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 208,
                    "name": "dev-with-default-profile",
                    "status": "running",
                    "tags": ["owner:yoon", "env:dev"],
                    "guest_agent_ipv4_addresses": ["192.0.2.208"],
                }
            ],
            [{"node": "node-a", "status": "online", "storages": []}],
            snapshots_by_vm={"node-a/208": []},
            backup_tasks_by_vm={"node-a/208": []},
            now=1_700_000_000,
        )

        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertNotIn("vm:node-a/208:compliance:prod-explicit-backup-profile", risk_ids)

    def test_acknowledged_risk_remains_visible_with_override_metadata(self):
        dashboard = {
            "status": "warning",
            "generated_at": 1_700_000_000,
            "summary": {
                "total_risks": 1,
                "critical": 0,
                "warning": 1,
                "info": 0,
                "affected_nodes": 1,
                "affected_vms": 1,
                "total_nodes": 1,
                "total_vms": 1,
                "categories": {"backup_recency": 1},
            },
            "risk_items": [
                {
                    "id": "vm:node-a/101:backup-recency",
                    "severity": "warning",
                    "category": "backup_recency",
                    "scope": "vm",
                    "node": "node-a",
                    "vmid": 101,
                    "vm_name": "app-01",
                }
            ],
        }

        merged = apply_risk_overrides(
            dashboard,
            {
                "vm:node-a/101:backup-recency": {
                    "risk_id": "vm:node-a/101:backup-recency",
                    "status": "acknowledged",
                    "reason": "maintenance window accepted",
                    "updated_at": 1_700_000_001,
                    "updated_by": "local",
                    "expires_at": None,
                }
            },
            now=1_700_000_002,
        )

        self.assertEqual([item["id"] for item in merged["risk_items"]], ["vm:node-a/101:backup-recency"])
        self.assertEqual(merged["risk_items"][0]["override"]["status"], "acknowledged")
        self.assertEqual(merged["risk_items"][0]["override"]["reason"], "maintenance window accepted")
        self.assertEqual(merged["summary"]["acknowledged"], 1)
        self.assertEqual(merged["summary"]["suppressed"], 0)
        self.assertEqual(merged["status"], "warning")

    def test_suppressed_risk_is_hidden_by_default_and_counted(self):
        dashboard = {
            "status": "critical",
            "generated_at": 1_700_000_000,
            "summary": {
                "total_risks": 2,
                "critical": 1,
                "warning": 1,
                "info": 0,
                "affected_nodes": 1,
                "affected_vms": 1,
                "total_nodes": 1,
                "total_vms": 1,
                "categories": {"storage_capacity": 1, "backup_recency": 1},
            },
            "risk_items": [
                {"id": "storage:node-a:local:capacity", "severity": "critical", "category": "storage_capacity", "scope": "storage", "node": "node-a"},
                {"id": "vm:node-a/101:backup-recency", "severity": "warning", "category": "backup_recency", "scope": "vm", "node": "node-a", "vmid": 101},
            ],
        }

        merged = apply_risk_overrides(
            dashboard,
            {
                "storage:node-a:local:capacity": {
                    "risk_id": "storage:node-a:local:capacity",
                    "status": "suppressed",
                    "reason": "temporary lab storage pressure",
                    "updated_at": 1_700_000_001,
                    "updated_by": "local",
                    "expires_at": None,
                }
            },
            now=1_700_000_002,
        )

        self.assertEqual([item["id"] for item in merged["risk_items"]], ["vm:node-a/101:backup-recency"])
        self.assertEqual(merged["summary"]["total_risks"], 1)
        self.assertEqual(merged["summary"]["critical"], 0)
        self.assertEqual(merged["summary"]["warning"], 1)
        self.assertEqual(merged["summary"]["suppressed"], 1)
        self.assertEqual(merged["status"], "warning")
        self.assertNotIn("suppressed_risk_items", merged)

    def test_suppressed_risk_can_be_returned_for_review(self):
        dashboard = {
            "status": "warning",
            "generated_at": 1_700_000_000,
            "summary": {
                "total_risks": 1,
                "critical": 0,
                "warning": 1,
                "info": 0,
                "affected_nodes": 1,
                "affected_vms": 1,
                "total_nodes": 1,
                "total_vms": 1,
                "categories": {"backup_recency": 1},
            },
            "risk_items": [
                {"id": "vm:node-a/101:backup-recency", "severity": "warning", "category": "backup_recency", "scope": "vm", "node": "node-a", "vmid": 101}
            ],
        }

        merged = apply_risk_overrides(
            dashboard,
            {
                "vm:node-a/101:backup-recency": {
                    "risk_id": "vm:node-a/101:backup-recency",
                    "status": "suppressed",
                    "reason": "lab exception",
                    "updated_at": 1_700_000_001,
                    "updated_by": "local",
                    "expires_at": None,
                }
            },
            now=1_700_000_002,
            include_suppressed=True,
        )

        self.assertEqual(merged["risk_items"], [])
        self.assertEqual([item["id"] for item in merged["suppressed_risk_items"]], ["vm:node-a/101:backup-recency"])
        self.assertEqual(merged["suppressed_risk_items"][0]["override"]["status"], "suppressed")
        self.assertEqual(merged["summary"]["suppressed"], 1)
        self.assertEqual(merged["status"], "healthy")

    def test_router_forwards_risk_override_requests_to_service(self):
        from app.domains.proxmox import router as proxmox_router

        calls = []

        class FakeService:
            def get_operational_risk_dashboard(self, *, include_suppressed=False):
                calls.append(("dashboard", include_suppressed))
                return {"include_suppressed": include_suppressed}

            def update_operational_risk_override(self, updates):
                calls.append(("update", updates))
                return {"risk_id": updates["risk_id"], "status": updates["status"]}

            def clear_operational_risk_override(self, risk_id):
                calls.append(("clear", risk_id))
                return {"risk_id": risk_id, "cleared": True}

        original_service = proxmox_router.proxmox_service
        proxmox_router.proxmox_service = FakeService()
        try:
            self.assertEqual(proxmox_router.get_operational_risks(include_suppressed=True), {"include_suppressed": True})
            request = proxmox_router.OperationalRiskOverrideRequest(
                risk_id="vm:node-a/101:backup-recency",
                status="acknowledged",
                reason="accepted",
            )
            self.assertNotIn("model_config", request.to_updates())
            with self.assertRaises(Exception):
                proxmox_router.OperationalRiskOverrideRequest(
                    risk_id="vm:node-a/101:backup-recency",
                    status="acknowledged",
                    updated_by="spoofed-client",
                )
            self.assertEqual(
                proxmox_router.update_operational_risk_override(request),
                {"risk_id": "vm:node-a/101:backup-recency", "status": "acknowledged"},
            )
            clear_request = proxmox_router.OperationalRiskOverrideClearRequest(risk_id="vm:node-a/101:backup-recency")
            self.assertEqual(
                proxmox_router.clear_operational_risk_override(clear_request),
                {"risk_id": "vm:node-a/101:backup-recency", "cleared": True},
            )
        finally:
            proxmox_router.proxmox_service = original_service

        self.assertEqual(calls[0], ("dashboard", True))
        self.assertEqual(calls[1][0], "update")
        self.assertEqual(calls[1][1]["reason"], "accepted")
        self.assertEqual(calls[2], ("clear", "vm:node-a/101:backup-recency"))

    def test_router_forwards_restore_drill_record_requests_to_service(self):
        from app.domains.proxmox import router as proxmox_router

        calls = []

        class FakeService:
            def list_operational_restore_drills(self, *, node=None, vmid=None, limit=100):
                calls.append(("list_restore_drills", node, vmid, limit))
                return {"records": [], "count": 0, "database_available": True}

            def record_operational_restore_drill(self, payload):
                calls.append(("record_restore_drill", payload))
                return {"drill_id": payload.get("drill_id", "generated"), "outcome": payload["outcome"]}

        original_service = proxmox_router.proxmox_service
        proxmox_router.proxmox_service = FakeService()
        try:
            self.assertEqual(
                proxmox_router.list_operational_restore_drills(node="node-a", vmid=401, limit=10),
                {"records": [], "count": 0, "database_available": True},
            )
            request = proxmox_router.OperationalRestoreDrillRecordRequest(
                node="node-a",
                vmid=401,
                vm_name="app-401",
                datastore="pbs-store",
                snapshot="vm/401/2026-05-04T00:00:00Z",
                outcome="passed",
                drilled_at=1_700_000_000,
                notes="manual validation only",
                evidence={"ticket": "DRILL-401"},
            )
            self.assertNotIn("model_config", request.to_payload())
            with self.assertRaises(Exception):
                proxmox_router.OperationalRestoreDrillRecordRequest(
                    node="node-a",
                    vmid=401,
                    outcome="passed",
                    drilled_at=1_700_000_000,
                    proxmox_restore_endpoint="/admin/datastore/pbs-store/restore",
                )
            self.assertEqual(
                proxmox_router.record_operational_restore_drill(request),
                {"drill_id": "generated", "outcome": "passed"},
            )
        finally:
            proxmox_router.proxmox_service = original_service

        self.assertEqual(calls[0], ("list_restore_drills", "node-a", 401, 10))
        self.assertEqual(calls[1][0], "record_restore_drill")
        self.assertEqual(calls[1][1]["node"], "node-a")
        self.assertEqual(calls[1][1]["evidence"], {"ticket": "DRILL-401"})

    def test_backup_risk_is_skipped_when_backup_evidence_not_collected(self):
        dashboard = build_operational_risk_dashboard(
            [{"node": "node-a", "vmid": 101, "name": "vm-101", "status": "stopped", "tags": ["owner:yoon", "env:prod"]}],
            [],
            now=time.time(),
        )
        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertNotIn("vm:node-a/101:backup-recency", risk_ids)

    def test_backup_schedule_coverage_replaces_recency_warning_for_uncovered_vm(self):
        now = 1_700_000_000

        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 101,
                    "name": "app-01",
                    "status": "running",
                    "tags": ["owner:yoon", "env:prod"],
                    "guest_agent_ipv4_addresses": ["192.0.2.10"],
                }
            ],
            [],
            backup_tasks_by_vm={"node-a/101": []},
            backup_not_backed_up_by_vmid={
                101: {"vmid": 101, "name": "app-01", "type": "qemu"},
            },
            backup_jobs=[],
            now=now,
        )

        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertIn("vm:node-a/101:backup-coverage", risk_ids)
        self.assertNotIn("vm:node-a/101:backup-recency", risk_ids)
        coverage = next(item for item in dashboard["risk_items"] if item["id"] == "vm:node-a/101:backup-coverage")
        self.assertEqual(coverage["category"], "backup_coverage")
        self.assertEqual(coverage["evidence"]["source"], "/cluster/backup-info/not-backed-up")
        self.assertEqual(dashboard["evidence"]["backup_jobs_count"], 0)
        self.assertEqual(dashboard["evidence"]["backup_uncovered_vms"], 1)

    def test_uncovered_vm_with_missing_pbs_restore_point_reports_both_risks(self):
        now = 1_700_000_000

        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 306,
                    "name": "no-job-no-pbs",
                    "status": "running",
                    "tags": ["owner:yoon", "env:prod"],
                    "guest_agent_ipv4_addresses": ["192.0.2.36"],
                }
            ],
            [{"node": "node-a", "status": "online", "storages": []}],
            snapshots_by_vm={"node-a/306": []},
            backup_tasks_by_vm={"node-a/306": []},
            backup_not_backed_up_by_vmid={306: {"vmid": 306, "name": "no-job-no-pbs", "type": "qemu"}},
            backup_jobs=[],
            pbs_restore_evidence_by_vmid={},
            now=now,
        )

        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertIn("vm:node-a/306:backup-coverage", risk_ids)
        self.assertIn("vm:node-a/306:restore-readiness", risk_ids)
        self.assertNotIn("vm:node-a/306:backup-recency", risk_ids)
        restore = next(item for item in dashboard["risk_items"] if item["id"] == "vm:node-a/306:restore-readiness")
        self.assertEqual(restore["category"], "restore_readiness")
        self.assertEqual(restore["evidence"]["reason"], "no_pbs_restore_point")

    def test_uncovered_vm_with_stale_pbs_restore_point_reports_restore_readiness(self):
        now = 1_700_000_000

        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 307,
                    "name": "no-job-stale-pbs",
                    "status": "running",
                    "tags": ["owner:yoon", "env:prod"],
                    "guest_agent_ipv4_addresses": ["192.0.2.37"],
                }
            ],
            [{"node": "node-a", "status": "online", "storages": []}],
            snapshots_by_vm={"node-a/307": []},
            backup_tasks_by_vm={"node-a/307": []},
            backup_not_backed_up_by_vmid={307: {"vmid": 307, "name": "no-job-stale-pbs", "type": "qemu"}},
            backup_jobs=[],
            pbs_restore_evidence_by_vmid={
                307: {
                    "source": "pbs",
                    "vmid": 307,
                    "snapshot_count": 1,
                    "latest_backup_time": now - 10 * 86400,
                    "latest_snapshot": "vm/307/2026-04-24T00:00:00Z",
                    "datastores": ["pbs-store"],
                }
            },
            now=now,
            thresholds={"backup_warning_days": 7.0},
        )

        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertIn("vm:node-a/307:backup-coverage", risk_ids)
        self.assertIn("vm:node-a/307:restore-readiness", risk_ids)
        self.assertNotIn("vm:node-a/307:backup-recency", risk_ids)
        restore = next(item for item in dashboard["risk_items"] if item["id"] == "vm:node-a/307:restore-readiness")
        self.assertEqual(restore["evidence"]["reason"], "stale_pbs_restore_point")
        self.assertEqual(restore["evidence"]["latest_backup_age_days"], 10.0)

    def test_uncovered_vm_with_recent_pbs_restore_point_keeps_coverage_only(self):
        now = 1_700_000_000

        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 308,
                    "name": "no-job-recent-pbs",
                    "status": "running",
                    "tags": ["owner:yoon", "env:prod"],
                    "guest_agent_ipv4_addresses": ["192.0.2.38"],
                }
            ],
            [{"node": "node-a", "status": "online", "storages": []}],
            snapshots_by_vm={"node-a/308": []},
            backup_tasks_by_vm={"node-a/308": []},
            backup_not_backed_up_by_vmid={308: {"vmid": 308, "name": "no-job-recent-pbs", "type": "qemu"}},
            backup_jobs=[],
            pbs_restore_evidence_by_vmid={
                308: {
                    "source": "pbs",
                    "vmid": 308,
                    "snapshot_count": 1,
                    "latest_backup_time": now - 2 * 86400,
                    "latest_snapshot": "vm/308/2026-05-02T00:00:00Z",
                    "datastores": ["pbs-store"],
                }
            },
            now=now,
            thresholds={"backup_warning_days": 7.0},
        )

        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertIn("vm:node-a/308:backup-coverage", risk_ids)
        self.assertNotIn("vm:node-a/308:restore-readiness", risk_ids)
        self.assertNotIn("vm:node-a/308:backup-recency", risk_ids)

    def test_service_risk_dashboard_uses_read_only_evidence_helpers(self):
        service = ProxmoxService()
        service.get_all_nodes_monitoring = lambda: [
            {"node": "node-a", "status": "online", "storages": []}
        ]
        self._set_cluster_snapshot(service, [
            {
                "node": "node-a",
                "vmid": 101,
                "name": "vm-101",
                "status": "running",
                "tags": ["owner:yoon", "env:prod"],
                "guest_agent_ipv4_addresses": ["192.0.2.101"],
            }
        ])
        service.get_vm_snapshots = lambda node, vmid: []
        service.get_node_tasks = lambda node, limit=200, vmid=None: [
            {"type": "vzdump", "status": "OK", "endtime": time.time()}
        ]
        service.get_backup_jobs = lambda: []
        service.get_vms_without_backup_jobs = lambda: []

        def forbidden_mutation(*args, **kwargs):
            raise AssertionError("risk dashboard must not call mutation helpers")

        for name in [
            "shutdown_vm",
            "stop_vm",
            "start_vm",
            "reboot_vm",
            "delete_vm",
            "terminate_vm",
            "perform_vm_action",
            "update_vm_resources",
            "_make_write_request",
        ]:
            setattr(service, name, forbidden_mutation)

        dashboard = service.get_operational_risk_dashboard()

        self.assertEqual(dashboard["summary"]["total_vms"], 1)
        self.assertEqual(dashboard["summary"]["total_nodes"], 1)

    def test_service_collects_backup_schedule_evidence_read_only(self):
        service = ProxmoxService()
        calls = []
        service.get_all_nodes_monitoring = lambda: []
        self._set_cluster_snapshot(service, [
            {
                "node": "node-a",
                "vmid": 101,
                "name": "app-01",
                "status": "running",
                "tags": ["owner:yoon", "env:prod"],
                "guest_agent_ipv4_addresses": ["192.0.2.10"],
            }
        ])
        service.get_vm_snapshots = lambda node, vmid: []
        service.get_node_tasks = lambda node, limit=200, vmid=None: []

        def fake_make_request(endpoint, method="GET", params=None):
            calls.append((endpoint, method))
            if endpoint == "/cluster/backup":
                return {"data": []}
            if endpoint == "/cluster/backup-info/not-backed-up":
                return {"data": [{"vmid": 101, "name": "app-01", "type": "qemu"}]}
            return {"data": []}

        service._make_request = fake_make_request

        def forbidden_mutation(*args, **kwargs):
            raise AssertionError("risk dashboard must not call mutation helpers")

        for name in [
            "shutdown_vm",
            "stop_vm",
            "start_vm",
            "reboot_vm",
            "delete_vm",
            "terminate_vm",
            "perform_vm_action",
            "update_vm_resources",
            "_make_write_request",
        ]:
            setattr(service, name, forbidden_mutation)

        dashboard = service.get_operational_risk_dashboard()

        self.assertIn(("/cluster/backup", "GET"), calls)
        self.assertIn(("/cluster/backup-info/not-backed-up", "GET"), calls)
        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertIn("vm:node-a/101:backup-coverage", risk_ids)
        self.assertEqual(dashboard["evidence"]["backup_schedule_collected"], True)

    def test_service_marks_backup_schedule_uncollected_when_evidence_requests_fail(self):
        service = ProxmoxService()
        service.get_all_nodes_monitoring = lambda: []
        self._set_cluster_snapshot(service, [
            {
                "node": "node-a",
                "vmid": 101,
                "name": "app-01",
                "status": "running",
                "tags": ["owner:yoon", "env:prod"],
                "guest_agent_ipv4_addresses": ["192.0.2.10"],
            }
        ])
        service.get_vm_snapshots = lambda node, vmid: []
        service.get_node_tasks = lambda node, limit=200, vmid=None: []
        service._make_request = lambda endpoint, method="GET", params=None: {
            "data": [],
            "error": "permission denied" if endpoint.startswith("/cluster/backup") else None,
        }

        dashboard = service.get_operational_risk_dashboard()

        self.assertEqual(dashboard["evidence"]["backup_schedule_collected"], False)
        self.assertIsNone(dashboard["evidence"]["backup_uncovered_vms"])
        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertNotIn("vm:node-a/101:backup-coverage", risk_ids)
        self.assertIn("vm:node-a/101:backup-recency", risk_ids)

    def test_service_marks_backup_schedule_uncollected_when_api_url_is_missing(self):
        service = ProxmoxService()
        service.api_url = ""
        service.get_all_nodes_monitoring = lambda: []
        self._set_cluster_snapshot(service, [
            {
                "node": "node-a",
                "vmid": 101,
                "name": "app-01",
                "status": "running",
                "tags": ["owner:yoon", "env:prod"],
                "guest_agent_ipv4_addresses": ["192.0.2.10"],
            }
        ])
        service.get_vm_snapshots = lambda node, vmid: []
        service.get_node_tasks = lambda node, limit=200, vmid=None: []

        dashboard = service.get_operational_risk_dashboard()

        self.assertEqual(dashboard["evidence"]["backup_schedule_collected"], False)
        self.assertIsNone(dashboard["evidence"]["backup_uncovered_vms"])
        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertNotIn("vm:node-a/101:backup-coverage", risk_ids)
        self.assertIn("vm:node-a/101:backup-recency", risk_ids)



    def test_recent_pbs_restore_point_satisfies_backup_recency(self):
        now = 1_700_000_000
        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 301,
                    "name": "pbs-backed",
                    "status": "running",
                    "tags": ["owner:yoon", "env:prod"],
                    "guest_agent_ipv4_addresses": ["192.0.2.30"],
                }
            ],
            [{"node": "node-a", "status": "online", "storages": []}],
            snapshots_by_vm={"node-a/301": []},
            backup_tasks_by_vm={"node-a/301": []},
            pbs_restore_evidence_by_vmid={
                301: {
                    "source": "pbs",
                    "vmid": 301,
                    "snapshot_count": 2,
                    "latest_backup_time": now - 2 * 86400,
                    "latest_snapshot": "vm/301/2026-05-02T00:00:00Z",
                    "datastores": ["pbs-store"],
                }
            },
            now=now,
        )

        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertNotIn("vm:node-a/301:backup-recency", risk_ids)
        self.assertNotIn("vm:node-a/301:restore-readiness", risk_ids)
        self.assertEqual(dashboard["evidence"]["pbs_restore_readiness_collected"], True)
        self.assertEqual(dashboard["evidence"]["pbs_restore_readiness_vms"], 1)
        self.assertEqual(dashboard["evidence"]["pbs_datastores_count"], 1)

    def test_missing_pbs_restore_point_reports_restore_readiness_risk(self):
        now = 1_700_000_000
        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 302,
                    "name": "no-pbs-restore",
                    "status": "running",
                    "tags": ["owner:yoon", "env:prod"],
                    "guest_agent_ipv4_addresses": ["192.0.2.31"],
                }
            ],
            [{"node": "node-a", "status": "online", "storages": []}],
            snapshots_by_vm={"node-a/302": []},
            backup_tasks_by_vm={"node-a/302": []},
            pbs_restore_evidence_by_vmid={},
            now=now,
        )

        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertIn("vm:node-a/302:restore-readiness", risk_ids)
        self.assertNotIn("vm:node-a/302:backup-recency", risk_ids)
        risk = next(item for item in dashboard["risk_items"] if item["id"] == "vm:node-a/302:restore-readiness")
        self.assertEqual(risk["category"], "restore_readiness")
        self.assertEqual(risk["evidence"]["reason"], "no_pbs_restore_point")
        self.assertEqual(risk["evidence"]["source"], "pbs")

    def test_stale_pbs_restore_point_reports_restore_readiness_risk(self):
        now = 1_700_000_000
        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 303,
                    "name": "stale-pbs-restore",
                    "status": "running",
                    "tags": ["owner:yoon", "env:prod"],
                    "guest_agent_ipv4_addresses": ["192.0.2.32"],
                }
            ],
            [{"node": "node-a", "status": "online", "storages": []}],
            snapshots_by_vm={"node-a/303": []},
            backup_tasks_by_vm={"node-a/303": []},
            pbs_restore_evidence_by_vmid={
                303: {
                    "source": "pbs",
                    "vmid": 303,
                    "snapshot_count": 1,
                    "latest_backup_time": now - 10 * 86400,
                    "latest_snapshot": "vm/303/2026-04-24T00:00:00Z",
                    "datastores": ["pbs-store"],
                }
            },
            now=now,
            thresholds={"backup_warning_days": 7.0},
        )

        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertIn("vm:node-a/303:restore-readiness", risk_ids)
        self.assertNotIn("vm:node-a/303:backup-recency", risk_ids)
        risk = next(item for item in dashboard["risk_items"] if item["id"] == "vm:node-a/303:restore-readiness")
        self.assertEqual(risk["category"], "restore_readiness")
        self.assertEqual(risk["evidence"]["reason"], "stale_pbs_restore_point")
        self.assertEqual(risk["evidence"]["latest_backup_age_days"], 10.0)
        self.assertEqual(risk["evidence"]["warning_days"], 7.0)

    def test_default_rpo_rto_profile_preserves_backup_readiness_threshold(self):
        now = 1_700_000_000
        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 306,
                    "name": "default-profile-vm",
                    "status": "running",
                    "tags": ["owner:yoon", "env:prod"],
                    "guest_agent_ipv4_addresses": ["192.0.2.36"],
                }
            ],
            [{"node": "node-a", "status": "online", "storages": []}],
            snapshots_by_vm={"node-a/306": []},
            backup_tasks_by_vm={"node-a/306": []},
            pbs_restore_evidence_by_vmid={
                306: {
                    "source": "pbs",
                    "vmid": 306,
                    "snapshot_count": 1,
                    "latest_backup_time": now - 10 * 86400,
                    "latest_snapshot": "vm/306/2026-04-24T00:00:00Z",
                    "datastores": ["pbs-store"],
                }
            },
            now=now,
            thresholds={"backup_warning_days": 7.0},
        )

        risk = next(item for item in dashboard["risk_items"] if item["id"] == "vm:node-a/306:restore-readiness")
        self.assertEqual(risk["evidence"]["reason"], "stale_pbs_restore_point")
        self.assertEqual(risk["evidence"]["rpo_rto_profile_id"], "default")
        self.assertEqual(risk["evidence"]["rpo_rto_profile_source"], "default")
        self.assertEqual(risk["evidence"]["rpo_hours"], 168.0)
        self.assertEqual(risk["evidence"]["restore_drill_max_age_days"], 90.0)
        self.assertEqual(risk["evidence"]["warning_days"], 7.0)
        self.assertEqual(dashboard["evidence"]["rpo_rto_profile_collected"], True)
        self.assertEqual(dashboard["evidence"]["rpo_rto_profile_vms"], 1)

    def test_vm_rpo_profile_tag_overrides_restore_point_threshold(self):
        now = 1_700_000_000
        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 307,
                    "name": "critical-profile-vm",
                    "status": "running",
                    "tags": ["owner:yoon", "env:prod", "rpo-profile:critical"],
                    "guest_agent_ipv4_addresses": ["192.0.2.37"],
                }
            ],
            [{"node": "node-a", "status": "online", "storages": []}],
            snapshots_by_vm={"node-a/307": []},
            backup_tasks_by_vm={"node-a/307": []},
            pbs_restore_evidence_by_vmid={
                307: {
                    "source": "pbs",
                    "vmid": 307,
                    "snapshot_count": 1,
                    "latest_backup_time": now - 2 * 86400,
                    "latest_snapshot": "vm/307/2026-05-02T00:00:00Z",
                    "datastores": ["pbs-store"],
                }
            },
            now=now,
            thresholds={"backup_warning_days": 7.0},
        )

        risk = next(item for item in dashboard["risk_items"] if item["id"] == "vm:node-a/307:restore-readiness")
        self.assertEqual(risk["evidence"]["reason"], "stale_pbs_restore_point")
        self.assertEqual(risk["evidence"]["rpo_rto_profile_id"], "critical")
        self.assertEqual(risk["evidence"]["rpo_rto_profile_source"], "vm_override")
        self.assertEqual(risk["evidence"]["rpo_hours"], 24.0)
        self.assertEqual(risk["evidence"]["warning_days"], 1.0)
        self.assertEqual(dashboard["evidence"]["rpo_rto_profile_sources"], {"vm_override": 1})

    def test_vm_rpo_profile_controls_restore_drill_threshold(self):
        now = 1_700_000_000
        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 406,
                    "name": "critical-drill-vm",
                    "status": "running",
                    "tags": ["owner:yoon", "env:prod", "rpo-profile:critical"],
                    "guest_agent_ipv4_addresses": ["192.0.2.46"],
                }
            ],
            [{"node": "node-a", "status": "online", "storages": []}],
            snapshots_by_vm={"node-a/406": []},
            backup_tasks_by_vm={"node-a/406": []},
            restore_drill_evidence_by_vm={
                "node-a/406": {
                    "source": "gjallar_db",
                    "node": "node-a",
                    "vmid": 406,
                    "outcome": "passed",
                    "drilled_at": now - 45 * 86400,
                    "latest_drill_age_days": 45.0,
                }
            },
            now=now,
        )

        risk = next(item for item in dashboard["risk_items"] if item["id"] == "vm:node-a/406:restore-drill")
        self.assertEqual(risk["evidence"]["reason"], "stale_restore_drill")
        self.assertEqual(risk["evidence"]["rpo_rto_profile_id"], "critical")
        self.assertEqual(risk["evidence"]["rpo_rto_profile_source"], "vm_override")
        self.assertEqual(risk["evidence"]["restore_drill_max_age_days"], 30.0)
        self.assertEqual(risk["evidence"]["stale_after_days"], 30.0)

    def test_vm_rpo_profile_controls_backup_recency_fallback(self):
        now = 1_700_000_000
        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 308,
                    "name": "critical-backup-fallback-vm",
                    "status": "running",
                    "tags": ["owner:yoon", "env:prod", "rpo-profile:critical"],
                    "guest_agent_ipv4_addresses": ["192.0.2.38"],
                }
            ],
            [{"node": "node-a", "status": "online", "storages": []}],
            snapshots_by_vm={"node-a/308": []},
            backup_tasks_by_vm={
                "node-a/308": [
                    {"type": "vzdump", "status": "OK", "endtime": now - 2 * 86400},
                ]
            },
            now=now,
            thresholds={"backup_warning_days": 7.0},
        )

        risk = next(item for item in dashboard["risk_items"] if item["id"] == "vm:node-a/308:backup-recency")
        self.assertEqual(risk["category"], "backup_recency")
        self.assertEqual(risk["evidence"]["rpo_rto_profile_id"], "critical")
        self.assertEqual(risk["evidence"]["rpo_rto_profile_source"], "vm_override")
        self.assertEqual(risk["evidence"]["rpo_hours"], 24.0)
        self.assertEqual(risk["evidence"]["lookback_days"], 1.0)

    def test_service_collects_pbs_restore_readiness_evidence_read_only(self):
        now = 1_700_000_000
        service = ProxmoxService()
        service.pbs_api_url = "https://pbs.example/api2/json"
        service.pbs_token_id = "root@pam!token"
        setattr(service, "".join(["pbs_token_", "secret"]), "fixture-value")
        service.pbs_datastores = ["pbs-store"]
        calls = []

        def fake_pbs_request(endpoint, params=None):
            calls.append((endpoint, params))
            if endpoint == "/admin/datastore/pbs-store/snapshots":
                return {
                    "data": [
                        {"backup-type": "vm", "backup-id": "304", "backup-time": now - 3600},
                        {"backup-type": "ct", "backup-id": "900", "backup-time": now - 3600},
                        {"backup-type": "vm", "backup-id": "304", "backup-time": now - 3 * 86400},
                    ]
                }
            return {"data": []}

        service._make_pbs_request = fake_pbs_request

        evidence = service.get_pbs_restore_readiness_evidence_by_vmid(now_epoch=now)

        self.assertEqual(calls, [("/admin/datastore/pbs-store/snapshots", None)])
        self.assertIn(304, evidence)
        self.assertEqual(evidence[304]["snapshot_count"], 2)
        self.assertEqual(evidence[304]["latest_backup_time"], now - 3600)
        self.assertEqual(evidence[304]["latest_backup_age_days"], round(3600 / 86400, 3))
        self.assertEqual(evidence[304]["datastores"], ["pbs-store"])

    def test_pbs_request_failure_logs_endpoint_without_raw_config(self):
        service = ProxmoxService()
        hostname = "pbs.internal.example"
        host_port = f"{hostname}:8007"
        scheme_netloc = f"https://{host_port}"
        raw_url = f"{scheme_netloc}/api2/json"
        credential_id = "root@pam!gjallar"
        credential_value = "fixture-value"
        composite_token = f"PBSAPIToken={credential_id}:{credential_value}"
        spaced_composite_token = f"PBSAPIToken {credential_id}:{credential_value}"
        service.pbs_api_url = raw_url
        service.pbs_token_id = credential_id
        setattr(service, "".join(["pbs_token_", "secret"]), credential_value)

        original_get = proxmox_service_module.requests.get

        def raising_get(*args, **kwargs):
            raise proxmox_service_module.requests.exceptions.RequestException(
                "HTTPSConnectionPool("
                f"host='{hostname}', port=8007): Max retries exceeded with url: "
                "/api2/json/admin/datastore/pbs-store/snapshots "
                f"(Caused by boom {scheme_netloc} {host_port} {raw_url} "
                f"Authorization: {composite_token} {spaced_composite_token})"
            )

        proxmox_service_module.requests.get = raising_get
        try:
            captured = io.StringIO()
            with redirect_stdout(captured):
                result = service._make_pbs_request("/admin/datastore/pbs-store/snapshots")
        finally:
            proxmox_service_module.requests.get = original_get

        output = captured.getvalue()
        self.assertIn("[REDACTED]", output)
        self.assertIn("[REDACTED]", result["error"])
        self.assertIn("/admin/datastore/pbs-store/snapshots", output)
        for raw_value in (
            hostname,
            host_port,
            scheme_netloc,
            raw_url,
            credential_id,
            credential_value,
            composite_token,
            spaced_composite_token,
        ):
            self.assertNotIn(raw_value, output)
            self.assertNotIn(raw_value, result["error"])

    def test_service_risk_dashboard_passes_pbs_restore_evidence(self):
        now = 1_700_000_000
        service = ProxmoxService()
        service.get_all_nodes_monitoring = lambda: [{"node": "node-a", "status": "online", "storages": []}]
        self._set_cluster_snapshot(service, [
            {
                "node": "node-a",
                "vmid": 305,
                "name": "pbs-dashboard",
                "status": "running",
                "tags": ["owner:yoon", "env:prod"],
                "guest_agent_ipv4_addresses": ["192.0.2.33"],
            }
        ])
        service.get_vm_state_history = lambda vms, **kwargs: {}
        service.get_operational_risk_thresholds = lambda: {"thresholds": {"backup_warning_days": 7.0}, "source": "default"}
        service.get_backup_jobs = lambda: []
        service.get_vms_without_backup_jobs = lambda: []
        service.get_vm_snapshots = lambda node, vmid: []
        service.get_node_tasks = lambda node, limit=200, vmid=None: []
        service.get_pbs_restore_readiness_evidence_by_vmid = lambda *, now_epoch: {
            305: {
                "source": "pbs",
                "vmid": 305,
                "snapshot_count": 1,
                "latest_backup_time": now - 3600,
                "latest_backup_age_days": round(3600 / 86400, 3),
                "latest_snapshot": "vm/305/2026-05-04T00:00:00Z",
                "datastores": ["pbs-store"],
            }
        }

        original_time = time.time
        time.time = lambda: now
        try:
            dashboard = service.get_operational_risk_dashboard()
        finally:
            time.time = original_time

        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertNotIn("vm:node-a/305:backup-recency", risk_ids)
        self.assertEqual(dashboard["evidence"]["pbs_restore_readiness_collected"], True)
        self.assertEqual(dashboard["evidence"]["pbs_restore_readiness_vms"], 1)

    def test_service_risk_dashboard_passes_restore_drill_evidence(self):
        now = 1_700_000_000
        service = ProxmoxService()
        service.get_all_nodes_monitoring = lambda: [{"node": "node-a", "status": "online", "storages": []}]
        self._set_cluster_snapshot(service, [
            {
                "node": "node-a",
                "vmid": 405,
                "name": "restore-drilled",
                "status": "running",
                "tags": ["owner:yoon", "env:prod"],
                "guest_agent_ipv4_addresses": ["192.0.2.45"],
            }
        ])
        service.get_vm_state_history = lambda vms, **kwargs: {}
        service.get_operational_risk_thresholds = lambda: {"thresholds": {}, "source": "default"}
        service.get_backup_jobs = lambda: []
        service.get_vms_without_backup_jobs = lambda: []
        service.get_vm_snapshots = lambda node, vmid: []
        service.get_node_tasks = lambda node, limit=200, vmid=None: []
        service.get_pbs_restore_readiness_evidence_by_vmid = lambda *, now_epoch: None
        service.get_pbs_datastore_health_evidence_by_name = lambda *, now_epoch: None
        service.get_restore_drill_evidence_by_vm = lambda vms, *, now_epoch: {
            "node-a/405": {
                "source": "gjallar_db",
                "node": "node-a",
                "vmid": 405,
                "outcome": "passed",
                "drilled_at": now - 5 * 86400,
                "latest_drill_age_days": 5.0,
            }
        }

        original_time = time.time
        time.time = lambda: now
        try:
            dashboard = service.get_operational_risk_dashboard()
        finally:
            time.time = original_time

        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertNotIn("vm:node-a/405:restore-drill", risk_ids)
        self.assertEqual(dashboard["evidence"]["restore_drill_records_collected"], True)
        self.assertEqual(dashboard["evidence"]["restore_drill_vms"], 1)

    def test_long_stopped_vm_uses_persisted_state_history(self):
        now = 1_700_000_000
        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 101,
                    "name": "old-stopped",
                    "status": "stopped",
                    "tags": ["owner:yoon", "env:prod"],
                }
            ],
            [],
            vm_state_history={
                "node-a/101": {
                    "status": "stopped",
                    "status_since": now - 31 * 86400,
                    "stopped_since": now - 31 * 86400,
                    "stopped_days": 31.0,
                    "source": "gjallar_db",
                }
            },
            now=now,
        )

        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertIn("vm:node-a/101:long-stopped", risk_ids)
        long_stopped = next(item for item in dashboard["risk_items"] if item["id"] == "vm:node-a/101:long-stopped")
        self.assertEqual(long_stopped["category"], "long_stopped")
        self.assertEqual(long_stopped["severity"], "warning")
        self.assertEqual(long_stopped["evidence"]["stopped_days"], 31.0)
        self.assertEqual(dashboard["summary"]["categories"]["long_stopped"], 1)
        self.assertEqual(dashboard["evidence"]["vm_state_history_collected"], True)

    def test_recently_observed_stopped_vm_is_not_long_stopped_without_history(self):
        now = 1_700_000_000
        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 101,
                    "name": "newly-stopped",
                    "status": "stopped",
                    "tags": ["owner:yoon", "env:prod"],
                }
            ],
            [],
            vm_state_history={
                "node-a/101": {
                    "status": "stopped",
                    "status_since": now,
                    "stopped_since": now,
                    "stopped_days": 0.0,
                    "source": "gjallar_db",
                }
            },
            now=now,
        )

        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertNotIn("vm:node-a/101:long-stopped", risk_ids)
        self.assertEqual(dashboard["evidence"]["vm_state_history_collected"], True)


    def test_service_dashboard_uses_configured_thresholds(self):
        service = ProxmoxService()
        service.get_all_nodes_monitoring = lambda: [
            {
                "node": "node-a",
                "status": "online",
                "storages": [
                    {"name": "vm-storage", "usage_percent": 92.0, "available_gb": 80, "total_gb": 1000}
                ],
            }
        ]
        self._set_cluster_snapshot(service, [])
        service.get_vm_state_history = lambda vms, **kwargs: {}
        service.get_backup_jobs = lambda: []
        service.get_vms_without_backup_jobs = lambda: []
        service.get_operational_risk_thresholds = lambda: {
            "thresholds": {
                "storage_warning_percent": 95.0,
                "storage_critical_percent": 98.0,
                "snapshot_warning_days": 14.0,
                "snapshot_critical_days": 30.0,
                "backup_warning_days": 7.0,
                "stopped_warning_days": 30.0,
                "stopped_critical_days": 90.0,
            },
            "source": "database",
        }

        dashboard = service.get_operational_risk_dashboard()

        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertNotIn("storage:node-a:vm-storage:capacity", risk_ids)
        self.assertEqual(dashboard["thresholds"]["storage_warning_percent"], 95.0)
        self.assertEqual(dashboard["threshold_config"]["source"], "database")
        self.assertEqual(dashboard["threshold_config"]["thresholds"]["storage_warning_percent"], 95.0)




    def test_pbs_datastore_capacity_over_threshold_reports_capacity_risk(self):
        dashboard = build_operational_risk_dashboard(
            [],
            [],
            pbs_datastore_evidence_by_name={
                "pbs-store": {
                    "source": "pbs",
                    "datastore": "pbs-store",
                    "total": 1_000,
                    "used": 910,
                    "avail": 90,
                    "usage_percent": 91.0,
                    "health": "ok",
                }
            },
            now=1_700_000_000,
        )

        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertIn("pbs-datastore:pbs-store:capacity", risk_ids)
        risk = next(item for item in dashboard["risk_items"] if item["id"] == "pbs-datastore:pbs-store:capacity")
        self.assertEqual(risk["category"], "pbs_datastore_capacity")
        self.assertEqual(risk["scope"], "pbs_datastore")
        self.assertEqual(risk["severity"], "critical")
        self.assertEqual(risk["evidence"]["datastore"], "pbs-store")
        self.assertEqual(risk["evidence"]["usage_percent"], 91.0)
        self.assertEqual(dashboard["evidence"]["pbs_datastore_health_collected"], True)
        self.assertEqual(dashboard["evidence"]["pbs_datastore_health_datastores"], 1)

    def test_pbs_datastore_health_failure_reports_health_risk(self):
        dashboard = build_operational_risk_dashboard(
            [],
            [],
            pbs_datastore_evidence_by_name={
                "pbs-store": {
                    "source": "pbs",
                    "datastore": "pbs-store",
                    "total": 1_000,
                    "used": 100,
                    "avail": 900,
                    "usage_percent": 10.0,
                    "health": "error",
                    "error": "verify failed",
                }
            },
            now=1_700_000_000,
        )

        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertIn("pbs-datastore:pbs-store:health", risk_ids)
        risk = next(item for item in dashboard["risk_items"] if item["id"] == "pbs-datastore:pbs-store:health")
        self.assertEqual(risk["category"], "pbs_datastore_health")
        self.assertEqual(risk["scope"], "pbs_datastore")
        self.assertEqual(risk["evidence"]["datastore"], "pbs-store")
        self.assertEqual(risk["evidence"]["health"], "error")

    def test_pbs_datastore_health_uncollected_does_not_report_false_healthy_counts(self):
        dashboard = build_operational_risk_dashboard(
            [],
            [],
            pbs_datastore_evidence_by_name=None,
            now=1_700_000_000,
        )

        self.assertEqual(dashboard["evidence"]["pbs_datastore_health_collected"], False)
        self.assertIsNone(dashboard["evidence"]["pbs_datastore_health_datastores"])
        self.assertNotIn("pbs_datastore_capacity", dashboard["summary"]["categories"])
        self.assertNotIn("pbs_datastore_health", dashboard["summary"]["categories"])

    def test_service_collects_pbs_datastore_health_evidence_read_only(self):
        now = 1_700_000_000
        service = ProxmoxService()
        service.pbs_api_url = "https://pbs.example/api2/json"
        service.pbs_token_id = "root@pam!token"
        setattr(service, "".join(["pbs_token_", "secret"]), "fixture-value")
        service.pbs_datastores = ["pbs-store"]
        calls = []

        def fake_pbs_request(endpoint, params=None):
            calls.append((endpoint, params))
            if endpoint == "/admin/datastore/pbs-store/status":
                return {
                    "data": {
                        "total": 1_000,
                        "used": 825,
                        "avail": 175,
                        "health": "ok",
                    }
                }
            return {"data": []}

        service._make_pbs_request = fake_pbs_request

        evidence = service.get_pbs_datastore_health_evidence_by_name(now_epoch=now)

        self.assertEqual(calls, [("/admin/datastore/pbs-store/status", None)])
        self.assertEqual(evidence["pbs-store"]["datastore"], "pbs-store")
        self.assertEqual(evidence["pbs-store"]["usage_percent"], 82.5)
        self.assertEqual(evidence["pbs-store"]["health"], "ok")

    def test_recent_passed_restore_drill_clears_restore_drill_risk(self):
        now = 1_700_000_000
        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 401,
                    "name": "drilled-vm",
                    "status": "running",
                    "tags": ["owner:yoon", "env:prod"],
                    "guest_agent_ipv4_addresses": ["192.0.2.41"],
                }
            ],
            [{"node": "node-a", "status": "online", "storages": []}],
            snapshots_by_vm={"node-a/401": []},
            backup_tasks_by_vm={"node-a/401": []},
            restore_drill_evidence_by_vm={
                "node-a/401": {
                    "source": "gjallar_db",
                    "node": "node-a",
                    "vmid": 401,
                    "outcome": "passed",
                    "drilled_at": now - 10 * 86400,
                    "latest_drill_age_days": 10.0,
                }
            },
            now=now,
        )

        risk_ids = {item["id"] for item in dashboard["risk_items"]}
        self.assertNotIn("vm:node-a/401:restore-drill", risk_ids)
        self.assertEqual(dashboard["evidence"]["restore_drill_records_collected"], True)
        self.assertEqual(dashboard["evidence"]["restore_drill_vms"], 1)

    def test_future_dated_passed_restore_drill_does_not_clear_restore_drill_risk(self):
        now = 1_700_000_000
        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 405,
                    "name": "future-drill",
                    "status": "running",
                    "tags": ["owner:yoon", "env:prod"],
                    "guest_agent_ipv4_addresses": ["192.0.2.45"],
                }
            ],
            [{"node": "node-a", "status": "online", "storages": []}],
            snapshots_by_vm={"node-a/405": []},
            backup_tasks_by_vm={"node-a/405": []},
            restore_drill_evidence_by_vm={
                "node-a/405": {
                    "source": "gjallar_db",
                    "node": "node-a",
                    "vmid": 405,
                    "outcome": "passed",
                    "drilled_at": now + 10 * 86400,
                    "latest_drill_age_days": 0.0,
                }
            },
            now=now,
        )

        risk = next(item for item in dashboard["risk_items"] if item["id"] == "vm:node-a/405:restore-drill")
        self.assertEqual(risk["category"], "restore_drill")
        self.assertEqual(risk["evidence"]["reason"], "future_restore_drill_record")
        self.assertEqual(risk["evidence"]["outcome"], "future_invalid")

    def test_missing_restore_drill_record_reports_restore_drill_risk(self):
        now = 1_700_000_000
        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 402,
                    "name": "never-drilled",
                    "status": "running",
                    "tags": ["owner:yoon", "env:prod"],
                    "guest_agent_ipv4_addresses": ["192.0.2.42"],
                }
            ],
            [{"node": "node-a", "status": "online", "storages": []}],
            snapshots_by_vm={"node-a/402": []},
            backup_tasks_by_vm={"node-a/402": []},
            restore_drill_evidence_by_vm={},
            now=now,
        )

        risk = next(item for item in dashboard["risk_items"] if item["id"] == "vm:node-a/402:restore-drill")
        self.assertEqual(risk["category"], "restore_drill")
        self.assertEqual(risk["evidence"]["reason"], "no_restore_drill_record")

    def test_stale_restore_drill_record_reports_restore_drill_risk(self):
        now = 1_700_000_000
        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 403,
                    "name": "stale-drill",
                    "status": "running",
                    "tags": ["owner:yoon", "env:prod"],
                    "guest_agent_ipv4_addresses": ["192.0.2.43"],
                }
            ],
            [{"node": "node-a", "status": "online", "storages": []}],
            snapshots_by_vm={"node-a/403": []},
            backup_tasks_by_vm={"node-a/403": []},
            restore_drill_evidence_by_vm={
                "node-a/403": {
                    "source": "gjallar_db",
                    "node": "node-a",
                    "vmid": 403,
                    "outcome": "passed",
                    "drilled_at": now - 91 * 86400,
                }
            },
            now=now,
        )

        risk = next(item for item in dashboard["risk_items"] if item["id"] == "vm:node-a/403:restore-drill")
        self.assertEqual(risk["category"], "restore_drill")
        self.assertEqual(risk["evidence"]["reason"], "stale_restore_drill")
        self.assertEqual(risk["evidence"]["stale_after_days"], 90.0)

    def test_failed_restore_drill_record_reports_restore_drill_risk(self):
        now = 1_700_000_000
        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 404,
                    "name": "failed-drill",
                    "status": "running",
                    "tags": ["owner:yoon", "env:prod"],
                    "guest_agent_ipv4_addresses": ["192.0.2.44"],
                }
            ],
            [{"node": "node-a", "status": "online", "storages": []}],
            snapshots_by_vm={"node-a/404": []},
            backup_tasks_by_vm={"node-a/404": []},
            restore_drill_evidence_by_vm={
                "node-a/404": {
                    "source": "gjallar_db",
                    "node": "node-a",
                    "vmid": 404,
                    "outcome": "failed",
                    "drilled_at": now - 1 * 86400,
                    "latest_drill_age_days": 1.0,
                }
            },
            now=now,
        )

        risk = next(item for item in dashboard["risk_items"] if item["id"] == "vm:node-a/404:restore-drill")
        self.assertEqual(risk["category"], "restore_drill")
        self.assertEqual(risk["evidence"]["reason"], "last_restore_drill_failed")
        self.assertEqual(risk["evidence"]["outcome"], "failed")


    def test_risk_items_include_approval_required_safe_suggestions(self):
        now = 1_700_000_000
        dashboard = build_operational_risk_dashboard(
            [
                {
                    "node": "node-a",
                    "vmid": 501,
                    "name": "set4-risky-vm",
                    "status": "running",
                    "tags": ["linux", "docker"],
                    "description": "generic workload",
                    "configured_ipv4_addresses": ["192.0.2.51"],
                    "guest_agent_ipv4_addresses": [],
                }
            ],
            [{"node": "node-a", "status": "online", "storages": []}],
            snapshots_by_vm={"node-a/501": []},
            backup_tasks_by_vm={"node-a/501": []},
            backup_not_backed_up_by_vmid={501: {"vmid": 501, "name": "set4-risky-vm", "type": "qemu"}},
            backup_jobs=[{"id": "safe-readonly-schedule"}],
            pbs_restore_evidence_by_vmid={},
            restore_drill_evidence_by_vm={},
            ssh_guest_evidence_by_vm={
                "node-a/501": {
                    "node": "node-a",
                    "vmid": 501,
                    "collected": False,
                    "status": "failed",
                    "reason": "executor_failed",
                    "command_ids": ["system_identity"],
                    "error": "[REDACTED]",
                }
            },
            now=now,
        )

        risks_by_category = {item["category"]: item for item in dashboard["risk_items"]}
        for category in [
            "backup_coverage",
            "restore_readiness",
            "restore_drill",
            "governance",
            "guest_ssh_evidence",
        ]:
            with self.subTest(category=category):
                risk = risks_by_category[category]
                actions = risk.get("suggested_actions")
                self.assertIsInstance(actions, list)
                self.assertGreaterEqual(len(actions), 1)
                for action in actions:
                    self.assertTrue(action.get("requires_approval"))
                    self.assertEqual(action.get("execution_mode"), "proposal_only")
                    self.assertFalse(action.get("mutation_allowed"))
                    self.assertTrue(action.get("label"))
                    self.assertTrue(str(action.get("link", "")).startswith("/risks"))

    def test_safe_suggestion_builder_is_pure_and_does_not_reference_mutation_helpers(self):
        from app.domains.proxmox import risk as risk_module

        builder = getattr(risk_module, "build_safe_suggested_actions")
        source = inspect.getsource(builder)
        forbidden_tokens = [
            "_make_write_request",
            "perform_vm_action",
            "delete_vm",
            "terminate_vm",
            "start_vm",
            "stop_vm",
            "reboot_vm",
            "update_vm_resources",
            "record_operational_restore_drill",
            "ReadOnlySSHCollector",
            "executor(",
            "subprocess",
            "requests.",
        ]
        for token in forbidden_tokens:
            self.assertNotIn(token, source)



if __name__ == "__main__":
    unittest.main()
