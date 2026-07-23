"""Contract tests for DRS read/check routes and narrow DRS execution routes."""

import contextlib
import io
import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from app.drs import application as drs_application


class ApiV1DrsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            from app.main import app
        cls.paths = {getattr(route, "path", "") for route in app.routes}

    def test_drs_routes_exist_under_api_v1_without_unsafe_recommendation_aliases(self):
        expected = {
            "/api/v1/drs/summary",
            "/api/v1/drs/recommendations",
            "/api/v1/drs/recommendations/{recommendation_id}",
            "/api/v1/drs/recommendations/{recommendation_id}/check",
            "/api/v1/drs/explicit-test-candidates/check",
            "/api/v1/drs/explicit-test-candidates/approval-packets",
            "/api/v1/drs/policies",
            "/api/v1/drs/policies/{vm_identity_id}",
            "/api/v1/drs/recommendations/{recommendation_id}/approval-packets",
            "/api/v1/drs/migration-jobs/{job_id}/execute",
            "/api/v1/drs/migration-jobs/{job_id}/reconcile",
            "/api/v1/drs/migration-jobs/{job_id}/reconcile-preview",
        }
        self.assertEqual([], sorted(expected - self.paths))
        self.assertNotIn("/api/v1/drs/recommendations/{recommendation_id}/check-now", self.paths)
        self.assertNotIn("/api/v1/drs/recommendations/{recommendation_id}/approve", self.paths)
        self.assertNotIn("/api/v1/drs/recommendations/{recommendation_id}/execute", self.paths)
        self.assertNotIn("/api/v1/drs/recommendations/{recommendation_id}/migrate", self.paths)
        self.assertNotIn("/api/v1/drs/recommendations/{recommendation_id}/migration", self.paths)
        self.assertNotIn("/api/v1/drs/recommendations/{recommendation_id}/live-migrate", self.paths)

    def test_policy_routes_read_and_update_by_vm_identity_id_with_session_actor(self):
        from app.api.v1 import drs_compat as v1_router
        from app.auth.roles import AuthenticatedUser

        actor = AuthenticatedUser(user_id="operator-1", username="operator", role="operator")
        adapter = _adapter()
        with patch.object(v1_router, "_inventory_adapter", return_value=adapter), patch.object(
            v1_router,
            "_drs_risks",
            return_value=[],
        ):
            policies = v1_router.list_drs_policies()
            item = policies["data"]["items"][0]
            response = v1_router.put_drs_policy(
                item["vm_identity_id"],
                {
                    "policy": "allowed",
                    "reason": "classified in API contract",
                    "policy_change_acknowledged": True,
                    "expected_observation": item["expected_observation"],
                    "actor": {"user_id": "payload-user", "username": "payload", "role": "admin"},
                    "updated_by": "payload",
                    "source": "tag",
                },
                actor=actor,
            )
            updated = v1_router.get_drs_policy(item["vm_identity_id"])

        self.assertTrue(policies["ok"])
        self.assertEqual("drs_policy_management_read_only", policies["meta"]["mode"])
        self.assertEqual("drs_policy_manual_update", response["meta"]["mode"])
        self.assertEqual("allowed", response["data"]["new_policy"]["policy"])
        self.assertEqual("operator", response["data"]["actor"]["username"])
        self.assertEqual("operator", response["data"]["policy_item"]["policy"]["updated_by"])
        self.assertEqual("manual", response["data"]["policy_item"]["policy"]["source"])
        self.assertEqual("allowed", updated["data"]["policy"]["value"])
        self.assertEqual(item["vm_identity_id"], updated["data"]["vm_identity_id"])

    def test_recommendations_are_read_only_and_filter_candidates(self):
        from app.api.v1 import drs_compat as v1_router

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
        self.assertEqual("not_collected", recommendation["technical_gate_status"]["status"])
        self.assertIn("proxmox_final_technical_gate", recommendation["criteria"]["authorities"])
        self.assertEqual("proxmox_final_technical_gate", recommendation["technical_gate_status"]["authority"])
        self.assertEqual("high", recommendation["identity_evidence"]["match_confidence"])
        self.assertEqual("unknown", recommendation["policy_evidence"]["policy"])
        self.assertEqual(2, data["summary"]["running_candidate_vms"])
        self.assertEqual(1, data["summary"]["excluded_red_risk_vms"])

    def test_advisory_prefilter_signals_are_not_hard_blockers(self):
        from app.api.v1 import drs_compat as v1_router

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
        self.assertNotIn("route_unknown", recommendation["blockers"])
        self.assertNotIn("local_storage_dependency", recommendation["blockers"])
        self.assertNotIn("passthrough_device_dependency", recommendation["blockers"])
        advisory = {item["code"]: item for item in recommendation["advisory_signals"]}
        self.assertEqual("advisor_prefilter_signal", advisory["route_unknown"]["authority"])
        self.assertEqual("advisory", advisory["local_storage_dependency"]["category"])
        self.assertEqual("warning", advisory["passthrough_device_dependency"]["severity"])
        self.assertEqual("none", advisory["route_unknown"]["action_blocked"])
        self.assertEqual(["gpu"], recommendation["evidence"]["passthrough"]["matched_tags"])
        self.assertFalse(recommendation["evidence"]["route"]["network_evidence_sufficient"])

    def test_target_over_threshold_blocks_projected_critical_target_pressure(self):
        from app.api.v1 import drs_compat as v1_router

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
        from app.api.v1 import drs_compat as v1_router

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

        self.assertNotIn("route_unknown", recommendation["blockers"])
        advisory = {item["code"]: item for item in recommendation["advisory_signals"]}
        self.assertEqual("warning", advisory["route_unknown"]["status"])
        self.assertEqual("advisor_prefilter_signal", advisory["route_unknown"]["authority"])
        self.assertFalse(recommendation["evidence"]["route"]["storage_evidence_sufficient"])
        self.assertIn("shared-nfs", recommendation["evidence"]["route"]["target_storage_ids"])
        self.assertIn("spacious-nfs", recommendation["evidence"]["route"]["target_storage_ids"])
        self.assertFalse(recommendation["executable"])

    def test_detail_404s_unknown_recommendation_id(self):
        from app.api.v1 import drs_compat as v1_router

        with patch.object(v1_router, "_inventory_adapter", return_value=_adapter()), patch.object(
            v1_router,
            "_drs_risks",
            return_value=[],
        ):
            with self.assertRaises(HTTPException) as context:
                v1_router.get_drs_recommendation("missing")

        self.assertEqual(404, context.exception.status_code)

    def test_check_recalculates_reference_only_without_job_writes(self):
        from app.api.v1 import drs_compat as v1_router

        adapter = _adapter()
        with patch.object(v1_router, "_inventory_adapter", return_value=adapter), patch.object(
            v1_router,
            "_drs_risks",
            return_value=[],
        ), patch("app.drs.approval.record_job_run") as record_job_run:
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

    def test_explicit_test_candidate_routes_require_exact_ack_before_drs_work(self):
        from app.api.v1 import drs_compat as v1_router
        from app.auth.roles import AuthenticatedUser

        actor = AuthenticatedUser(user_id="operator-1", username="operator", role="operator")
        invalid_payloads = [
            ("missing_payload", None),
            ("missing_field", {}),
            ("false", {"explicit_test_vm_acknowledged": False}),
            ("null", {"explicit_test_vm_acknowledged": None}),
            ("string_true", {"explicit_test_vm_acknowledged": "true"}),
            ("number_one", {"explicit_test_vm_acknowledged": 1}),
            ("camel_case_only", {"explicitTestVmAcknowledged": True}),
            ("create_vm_ack_only", {"proxmox_mutation_acknowledged": True}),
        ]

        for label, payload in invalid_payloads:
            for route in (
                v1_router.check_drs_explicit_test_candidate,
                v1_router.create_drs_explicit_test_approval_packet,
            ):
                with (
                    self.subTest(label=label, route=route.__name__),
                    patch.object(v1_router, "_inventory_adapter") as inventory,
                    patch.object(v1_router, "_drs_risks") as risks,
                    patch.object(
                        drs_application,
                        "build_drs_check_result",
                    ) as build_check,
                    patch.object(
                        drs_application,
                        "create_approval_packet_and_job_intent",
                    ) as create_packet,
                ):
                    with self.assertRaises(HTTPException) as raised:
                        route(payload, actor=actor)

                    detail = raised.exception.detail
                    self.assertEqual(409, raised.exception.status_code)
                    self.assertEqual("DRS_EXPLICIT_TEST_CANDIDATE_ACK_REQUIRED", detail["code"])
                    self.assertEqual("explicit_test_vm_acknowledged", detail["required_acknowledgement"])
                    self.assertFalse(detail["proxmox_mutation_enabled"])
                    self.assertEqual([], detail["side_effects"])
                    inventory.assert_not_called()
                    risks.assert_not_called()
                    build_check.assert_not_called()
                    create_packet.assert_not_called()

    def test_explicit_test_candidate_check_and_approval_packet_use_local_drs_gates(self):
        from app.api.v1 import drs_compat as v1_router
        from app.auth.roles import AuthenticatedUser

        adapter = _adapter(include_explicit_smoke=True)
        actor = AuthenticatedUser(user_id="operator-1", username="operator", role="operator")
        with patch.object(v1_router, "_inventory_adapter", return_value=adapter), patch.object(
            v1_router,
            "_drs_risks",
            return_value=[],
        ):
            recommendations = v1_router.list_drs_recommendations()["data"]["recommendations"]
            policy_items = v1_router.list_drs_policies()["data"]["items"]
            smoke_policy = next(item for item in policy_items if item["current_locator"]["vmid"] == 140)
            payload = {
                "explicit_test_vm_acknowledged": True,
                "vm_identity_id": smoke_policy["vm_identity_id"],
                "vmid": 140,
                "source_node_id": "node-a",
                "target_node_id": "node-b",
            }
            blocked_check = v1_router.check_drs_explicit_test_candidate(payload, actor=actor)
            with patch.object(drs_application, "create_approval_packet_and_job_intent") as create_packet:
                with self.assertRaises(HTTPException) as blocked_approval:
                    v1_router.create_drs_explicit_test_approval_packet(payload, actor=actor)
            _set_policy(smoke_policy["vm_identity_id"], "allowed")
            allowed_check = v1_router.check_drs_explicit_test_candidate(payload, actor=actor)
            approval = v1_router.create_drs_explicit_test_approval_packet(payload, actor=actor)

        self.assertNotIn(140, [item["vmid"] for item in recommendations])
        self.assertTrue(blocked_check["ok"])
        self.assertFalse(blocked_check["data"]["would_be_executable"])
        self.assertIn("migration_policy_unknown", blocked_check["data"]["blockers"])
        self.assertEqual(409, blocked_approval.exception.status_code)
        self.assertEqual("DRS_APPROVAL_GATE_BLOCKED", blocked_approval.exception.detail["code"])
        create_packet.assert_not_called()
        self.assertTrue(allowed_check["data"]["would_be_executable"])
        self.assertTrue(allowed_check["data"]["recommendation"]["explicit_test_candidate"])
        self.assertTrue(approval["ok"])
        self.assertEqual("drs_explicit_test_local_approval_packet_no_mutation", approval["meta"]["mode"])
        self.assertEqual(allowed_check["data"]["recommendation_id"], approval["data"]["approval_packet"]["recommendation_id"])
        self.assertEqual(smoke_policy["vm_identity_id"], approval["data"]["approval_packet"]["vm_identity_id"])
        self.assertEqual("pending", approval["data"]["job_intent"]["status"])
        self.assertFalse(approval["data"]["job_intent"]["proxmox_mutation_enabled"])
        self.assertEqual([], approval["data"]["job_intent"]["side_effects"])

    def test_explicit_test_candidate_selection_mismatch_rejects_before_approval_creation(self):
        from app.api.v1 import drs_compat as v1_router
        from app.auth.roles import AuthenticatedUser

        adapter = _adapter(include_explicit_smoke=True)
        actor = AuthenticatedUser(user_id="operator-1", username="operator", role="operator")
        with patch.object(v1_router, "_inventory_adapter", return_value=adapter), patch.object(
            v1_router,
            "_drs_risks",
            return_value=[],
        ):
            smoke_policy = next(
                item for item in v1_router.list_drs_policies()["data"]["items"] if item["current_locator"]["vmid"] == 140
            )
            payload = {
                "explicit_test_vm_acknowledged": True,
                "vm_identity_id": smoke_policy["vm_identity_id"],
                "vmid": 140,
                "source_node_id": "node-x",
                "target_node_id": "node-b",
            }
            with patch.object(drs_application, "create_approval_packet_and_job_intent") as create_packet:
                with self.assertRaises(HTTPException) as raised:
                    v1_router.create_drs_explicit_test_approval_packet(payload, actor=actor)

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("DRS_EXPLICIT_TEST_CANDIDATE_SELECTION_MISMATCH", raised.exception.detail["code"])
        self.assertIn("source_node_id", raised.exception.detail["mismatches"])
        self.assertFalse(raised.exception.detail["proxmox_mutation_enabled"])
        self.assertEqual([], raised.exception.detail["side_effects"])
        create_packet.assert_not_called()

    def test_approval_packet_route_creates_local_non_runnable_job_without_proxmox_mutation(self):
        from app.api.v1 import drs_compat as v1_router
        from app.auth.roles import AuthenticatedUser

        adapter = _adapter()
        actor = AuthenticatedUser(user_id="operator-1", username="operator", role="operator")
        with patch.object(v1_router, "_inventory_adapter", return_value=adapter), patch.object(
            v1_router,
            "_drs_risks",
            return_value=[{"level": "red", "vmid": 104, "code": "vm_blocked"}],
        ), patch("app.api.v1.vm_create_compat._mutation_client_factory") as mutation_client, patch(
            "app.vm_create.application.run_proxmox_create"
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
        self.assertNotIn("live_migration_execution_not_implemented", data["job_intent"]["runnable_blockers"])
        self.assertIn("proxmox_active_task_not_collected", data["job_intent"]["runnable_blockers"])
        self.assertIn("proxmox_ha_state_not_collected", data["job_intent"]["runnable_blockers"])
        self.assertIn("proxmox_cluster_quorum_not_collected", data["job_intent"]["runnable_blockers"])
        self.assertEqual("would_pass", data["job_intent"]["final_precheck_summary"]["status"])
        mutation_client.assert_not_called()
        create_mutation.assert_not_called()

    def test_migration_job_execute_route_delegates_to_drs_execution_only(self):
        from app.api.v1 import drs_compat as v1_router
        from app.auth.roles import AuthenticatedUser

        actor = AuthenticatedUser(user_id="operator-1", username="operator", role="operator")
        expected = {
            "status": "running",
            "proxmox_upid": "UPID:node-a:0001:migrate",
            "side_effects": ["drs_operation_locks_acquired", "proxmox_migrate_invoked"],
        }
        with (
            patch.object(v1_router, "_inventory_adapter", return_value=_adapter()),
            patch.object(v1_router, "_drs_risks", return_value=[]),
            patch.object(
                drs_application,
                "execute_drs_migration_job",
                return_value=expected,
            ) as execute,
            patch(
                "app.api.v1.vm_create_compat._mutation_client_factory",
            ) as create_vm_client,
        ):
            response = asyncio.run(
                v1_router.execute_drs_migration_job_action(
                    "job-drs-1",
                    {"drs_live_migration_acknowledged": True},
                    actor=actor,
                )
            )

        self.assertTrue(response["ok"])
        self.assertEqual("drs_live_migration_execution", response["meta"]["mode"])
        self.assertEqual(expected, response["data"])
        execute.assert_called_once()
        self.assertEqual({"drs_live_migration_acknowledged": True}, execute.call_args.kwargs["payload"])
        create_vm_client.assert_not_called()

    def test_migration_job_execute_route_requires_exact_live_ack_before_drs_work(self):
        from app.api.v1 import drs_compat as v1_router
        from app.auth.roles import AuthenticatedUser

        actor = AuthenticatedUser(user_id="operator-1", username="operator", role="operator")
        invalid_payloads = [
            ("missing_payload", None),
            ("missing_field", {}),
            ("false", {"drs_live_migration_acknowledged": False}),
            ("null", {"drs_live_migration_acknowledged": None}),
            ("string_true", {"drs_live_migration_acknowledged": "true"}),
            ("number_one", {"drs_live_migration_acknowledged": 1}),
            ("camel_case_only", {"drsLiveMigrationAcknowledged": True}),
            ("create_vm_ack_only", {"proxmox_mutation_acknowledged": True}),
        ]

        for label, payload in invalid_payloads:
            with (
                self.subTest(label=label),
                patch.object(v1_router, "_inventory_adapter") as inventory,
                patch.object(v1_router, "_drs_risks") as risks,
                patch.object(
                    drs_application,
                    "execute_drs_migration_job",
                ) as execute,
                patch.object(
                    v1_router,
                    "_drs_migration_client_factory",
                ) as drs_client_factory,
                patch.object(drs_application.asyncio, "to_thread") as threadpool,
                patch(
                    "app.api.v1.vm_create_compat._mutation_client_factory",
                ) as create_vm_client,
            ):
                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(v1_router.execute_drs_migration_job_action("job-drs-ack", payload, actor=actor))

                detail = raised.exception.detail
                self.assertEqual(409, raised.exception.status_code)
                self.assertEqual("DRS_EXECUTION_ACK_REQUIRED", detail["code"])
                self.assertEqual("job-drs-ack", detail["job_id"])
                self.assertEqual("drs_live_migration_acknowledged", detail["required_acknowledgement"])
                self.assertFalse(detail["proxmox_mutation_enabled"])
                self.assertEqual([], detail["side_effects"])
                self.assertNotIn("payload", detail)
                inventory.assert_not_called()
                risks.assert_not_called()
                execute.assert_not_called()
                drs_client_factory.assert_not_called()
                threadpool.assert_not_called()
                create_vm_client.assert_not_called()

    def test_migration_job_reconcile_route_delegates_to_local_reconciliation_only(self):
        from app.api.v1 import drs_compat as v1_router
        from app.auth.roles import AuthenticatedUser

        actor = AuthenticatedUser(user_id="operator-1", username="operator", role="operator")
        expected = {
            "status": "completed",
            "proxmox_upid": "UPID:node-a:0001:migrate",
            "proxmox_mutation_enabled": False,
            "corrective_mutation_enabled": False,
            "side_effects": ["proxmox_task_polled", "proxmox_drs_post_check_observed"],
        }
        payload = {"drs_reconciliation_acknowledged": True}
        with (
            patch.object(
                drs_application,
                "reconcile_drs_migration_job",
                return_value=expected,
            ) as reconcile,
            patch.object(
                drs_application,
                "execute_drs_migration_job",
            ) as execute,
            patch(
                "app.api.v1.vm_create_compat._mutation_client_factory",
            ) as create_vm_client,
        ):
            response = asyncio.run(v1_router.reconcile_drs_migration_job_action("job-drs-1", payload, actor=actor))

        self.assertTrue(response["ok"])
        self.assertEqual("drs_local_reconciliation_follow_up", response["meta"]["mode"])
        self.assertEqual(expected, response["data"])
        reconcile.assert_called_once()
        self.assertEqual(payload, reconcile.call_args.kwargs["payload"])
        execute.assert_not_called()
        create_vm_client.assert_not_called()

    def test_migration_job_reconcile_route_requires_exact_ack_before_drs_work(self):
        from app.api.v1 import drs_compat as v1_router
        from app.auth.roles import AuthenticatedUser

        actor = AuthenticatedUser(user_id="operator-1", username="operator", role="operator")
        invalid_payloads = [
            ("missing_payload", None),
            ("missing_field", {}),
            ("false", {"drs_reconciliation_acknowledged": False}),
            ("null", {"drs_reconciliation_acknowledged": None}),
            ("string_true", {"drs_reconciliation_acknowledged": "true"}),
            ("number_one", {"drs_reconciliation_acknowledged": 1}),
            ("camel_case_only", {"drsReconciliationAcknowledged": True}),
            ("create_vm_ack_only", {"proxmox_mutation_acknowledged": True}),
            ("live_ack_only", {"drs_live_migration_acknowledged": True}),
        ]

        for label, payload in invalid_payloads:
            with (
                self.subTest(label=label),
                patch.object(
                    drs_application,
                    "reconcile_drs_migration_job",
                ) as reconcile,
                patch.object(
                    v1_router,
                    "_drs_migration_client_factory",
                ) as drs_client_factory,
                patch.object(drs_application.asyncio, "to_thread") as threadpool,
                patch.object(
                    drs_application,
                    "execute_drs_migration_job",
                ) as execute,
            ):
                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(v1_router.reconcile_drs_migration_job_action("job-drs-reconcile", payload, actor=actor))

                detail = raised.exception.detail
                self.assertEqual(409, raised.exception.status_code)
                self.assertEqual("DRS_RECONCILIATION_ACK_REQUIRED", detail["code"])
                self.assertEqual("job-drs-reconcile", detail["job_id"])
                self.assertEqual("drs_reconciliation_acknowledged", detail["required_acknowledgement"])
                self.assertFalse(detail["proxmox_mutation_enabled"])
                self.assertEqual([], detail["side_effects"])
                reconcile.assert_not_called()
                drs_client_factory.assert_not_called()
                threadpool.assert_not_called()
                execute.assert_not_called()

    def test_migration_job_execute_ack_failure_preserves_pending_job_without_locks(self):
        from app.api.v1 import drs_compat as v1_router
        from app.auth.roles import AuthenticatedUser
        from app.db.models import DrsMigrationJobRecord, OperationLockRecord
        from app.db.session import session_scope

        adapter = _adapter()
        actor = AuthenticatedUser(user_id="operator-1", username="operator", role="operator")
        with patch.object(v1_router, "_inventory_adapter", return_value=adapter), patch.object(
            v1_router,
            "_drs_risks",
            return_value=[],
        ):
            recommendation = v1_router.list_drs_recommendations()["data"]["recommendations"][0]
            _set_policy(recommendation["identity_evidence"]["vm_identity_id"], "allowed")
            recommendation = v1_router.list_drs_recommendations()["data"]["recommendations"][0]
            packet = v1_router.create_drs_approval_packet(
                recommendation["id"],
                {"recommendation": recommendation},
                actor=actor,
            )
        job_id = packet["data"]["job_intent"]["job_id"]

        with (
            patch.object(v1_router, "_inventory_adapter") as inventory,
            patch.object(v1_router, "_drs_risks") as risks,
            patch.object(
                drs_application,
                "execute_drs_migration_job",
            ) as execute,
            patch.object(
                v1_router,
                "_drs_migration_client_factory",
            ) as drs_client_factory,
            patch.object(drs_application.asyncio, "to_thread") as threadpool,
        ):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(
                    v1_router.execute_drs_migration_job_action(
                        job_id,
                        {"proxmox_mutation_acknowledged": True},
                        actor=actor,
                    )
                )

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("DRS_EXECUTION_ACK_REQUIRED", raised.exception.detail["code"])
        inventory.assert_not_called()
        risks.assert_not_called()
        execute.assert_not_called()
        drs_client_factory.assert_not_called()
        threadpool.assert_not_called()
        with session_scope() as session:
            job = session.get(DrsMigrationJobRecord, job_id)
            self.assertEqual("pending", job.status)
            self.assertEqual([], job.side_effects)
            self.assertIsNone(job.proxmox_upid)
            self.assertIsNone(job.proxmox_task_node)
            self.assertEqual([], job.operation_lock_ids)
            self.assertEqual([], session.query(OperationLockRecord).all())

    def test_reconcile_preview_route_is_read_only_and_not_create_vm_coupled(self):
        from app.api.v1 import drs_compat as v1_router
        from app.auth.roles import AuthenticatedUser

        actor = AuthenticatedUser(user_id="operator-1", username="operator", role="operator")
        expected = {
            "job_id": "job-drs-1",
            "read_only": True,
            "proxmox_mutation_enabled": False,
            "side_effects": [],
            "corrective_mutation_enabled": False,
            "post_check": {"status": "pass"},
        }
        with (
            patch.object(
                drs_application,
                "build_drs_migration_reconciliation_preview",
                return_value=expected,
            ) as preview,
            patch.object(
                drs_application,
                "execute_drs_migration_job",
            ) as execute,
            patch(
                "app.api.v1.vm_create_compat._mutation_client_factory",
            ) as create_vm_client,
        ):
            response = asyncio.run(v1_router.preview_drs_migration_reconciliation_action("job-drs-1", {}, actor=actor))

        self.assertTrue(response["ok"])
        self.assertEqual("drs_reconciliation_preview_read_only", response["meta"]["mode"])
        self.assertTrue(response["data"]["read_only"])
        self.assertFalse(response["data"]["proxmox_mutation_enabled"])
        self.assertEqual([], response["data"]["side_effects"])
        preview.assert_called_once()
        execute.assert_not_called()
        create_vm_client.assert_not_called()


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
    include_explicit_smoke=False,
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
            vms = [
                _vm(101, "app-01", "running", False, storage_id, vm_tags),
                _vm(102, "stopped-01", "stopped", False, storage_id, ()),
                _vm(103, "template-01", "running", True, storage_id, ()),
                _vm(104, "red-risk-01", "running", False, storage_id, ()),
            ]
            if include_explicit_smoke:
                vms.extend(
                    [
                        _vm(105, "app-02", "running", False, storage_id, ()),
                        _vm(106, "app-03", "running", False, storage_id, ()),
                        _vm(140, "drs-smoke-140", "running", False, storage_id, ()),
                    ]
                )
            self._vms = tuple(vms)

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
