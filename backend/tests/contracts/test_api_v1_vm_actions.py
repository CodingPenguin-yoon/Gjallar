"""Contract tests for explicit /api/v1 VM action routes."""

import asyncio
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.proxmox.client import ProxmoxMutationError
from app.proxmox.models import VmInventory


class StubInventoryAdapter:
    source = "test_read_only"

    def __init__(self, *, vms=None, templates=None):
        self._vms = list(vms or [])
        self._templates = list(templates or [])

    def list_vms(self):
        return list(self._vms)

    def list_templates(self):
        return list(self._templates)


class RecordingStartClient:
    def __init__(
        self,
        *,
        task_exitstatus="OK",
        post_status="running",
        start_upid=None,
        start_error=None,
        wait_error=None,
        post_error=None,
    ):
        self.task_exitstatus = task_exitstatus
        self.post_status = post_status
        self.start_upid = start_upid
        self.start_error = start_error
        self.wait_error = wait_error
        self.post_error = post_error
        self.calls = []

    def redacted_connection_context(self):
        return {
            "mode": "native_mutation",
            "api_url": "https://pve.example.test/api2/json",
            "token_id": "root@pam!gjallar",
            "token_secret": "secret",
        }

    def start_vm(self, *, node, vmid):
        self.calls.append(("start_vm", {"node": node, "vmid": vmid}))
        if self.start_error is not None:
            raise self.start_error
        if self.start_upid is not None:
            return self.start_upid
        return f"UPID:{node}:0001:start"

    def wait_for_task(self, *, node, upid, heartbeat=None):
        self.calls.append(("wait_for_task", {"node": node, "upid": upid}))
        if heartbeat is not None:
            heartbeat()
        if self.wait_error is not None:
            raise self.wait_error
        return {
            "node": node,
            "upid": upid,
            "status": "stopped",
            "exitstatus": self.task_exitstatus,
            "polls": [{"status": "running"}, {"status": "stopped", "exitstatus": self.task_exitstatus}],
        }

    def get_vm_status(self, *, node, vmid):
        self.calls.append(("get_vm_status", {"node": node, "vmid": vmid}))
        if self.post_error is not None:
            raise self.post_error
        return {"vmid": vmid, "name": "stopped-app", "status": self.post_status}


def stopped_vm(*, vmid=306, node_id="node-a", name="stopped-app", status="stopped", template=False):
    return VmInventory(
        vmid=vmid,
        name=name,
        node_id=node_id,
        status=status,
        template=template,
        cpu=2,
        memory_mb=4096,
        disk_gb=40,
    )


class ApiV1VmActionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            from app.main import app
            from app.api.v1 import vm_actions as api_v1_router
        cls.paths = {getattr(route, "path", "") for route in app.routes}
        cls.api_v1_router = api_v1_router

    def _run_start(self, *, adapter=None, client=None, payload=None, node_id="node-a", vmid=306):
        adapter = adapter or StubInventoryAdapter(vms=[stopped_vm(vmid=vmid, node_id=node_id)])
        client = client or RecordingStartClient()
        with patch.object(self.api_v1_router.inventory_context, "mutation_inventory_adapter", return_value=adapter):
            with patch.object(self.api_v1_router, "get_default_proxmox_mutation_client", return_value=client):
                return asyncio.run(
                    self.api_v1_router.start_vm_action(
                        node_id,
                        vmid,
                        payload
                        or {
                            "vm_start_acknowledged": True,
                            "idempotency_key": "idem-start-1",
                            "expected_name": "stopped-app",
                            "expected_status": "stopped",
                        },
                    )
                )



    def test_start_route_exists_without_legacy_instance_action_routes(self):
        self.assertIn("/api/v1/nodes/{node_id}/vms/{vmid}/actions/start", self.paths)
        self.assertNotIn("/api/instances/action", self.paths)
        self.assertNotIn("/api/v1/instances/action", self.paths)

    def test_post_create_readiness_evidence_route_exists_without_bootstrap_aliases(self):
        self.assertIn("/api/v1/nodes/{node_id}/vms/{vmid}/post-create-readiness-evidence", self.paths)
        self.assertNotIn("/api/v1/nodes/{node_id}/vms/{vmid}/actions/bootstrap", self.paths)
        self.assertNotIn("/api/v1/nodes/{node_id}/vms/{vmid}/actions/ssh", self.paths)
        self.assertNotIn("/api/v1/nodes/{node_id}/vms/{vmid}/actions/ansible", self.paths)
        self.assertNotIn("/api/v1/nodes/{node_id}/vms/{vmid}/post-create-bootstrap", self.paths)

    def test_start_blocks_without_acknowledgement(self):
        with self.assertRaises(HTTPException) as raised:
            self._run_start(payload={"idempotency_key": "idem-no-ack"})

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("VM_START_ACK_REQUIRED", raised.exception.detail["code"])
        self.assertFalse(raised.exception.detail["proxmox_mutation_enabled"])

    def test_start_blocks_without_idempotency_key(self):
        with self.assertRaises(HTTPException) as raised:
            self._run_start(payload={"vm_start_acknowledged": True})

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("VM_START_IDEMPOTENCY_KEY_REQUIRED", raised.exception.detail["code"])
        self.assertFalse(raised.exception.detail["proxmox_mutation_enabled"])

    def test_start_precheck_blocks_missing_moved_template_and_non_stopped_vms(self):
        from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore

        cases = [
            (
                StubInventoryAdapter(vms=[]),
                "VM_START_MISSING_BLOCKED",
                "node-a",
                306,
                "stopped",
            ),
            (
                StubInventoryAdapter(vms=[stopped_vm(node_id="node-b")]),
                "VM_START_MOVED_BLOCKED",
                "node-a",
                306,
                "stopped",
            ),
            (
                StubInventoryAdapter(vms=[stopped_vm(template=True)]),
                "VM_START_TEMPLATE_BLOCKED",
                "node-a",
                306,
                "stopped",
            ),
            (
                StubInventoryAdapter(vms=[stopped_vm(status="running")]),
                "VM_START_NON_STOPPED_BLOCKED",
                "node-a",
                306,
                "running",
            ),
        ]

        for index, (adapter, code, node_id, vmid, expected_status) in enumerate(cases):
            client = RecordingStartClient()
            with self.subTest(code=code):
                with self.assertRaises(HTTPException) as raised:
                    self._run_start(
                        adapter=adapter,
                        client=client,
                        node_id=node_id,
                        vmid=vmid,
                        payload={
                            "vm_start_acknowledged": True,
                            "idempotency_key": f"idem-block-{index}",
                            "expected_name": "stopped-app",
                            "expected_status": expected_status,
                        },
                    )
                self.assertEqual(409, raised.exception.status_code)
                self.assertEqual(code, raised.exception.detail["code"])
                self.assertFalse(raised.exception.detail["proxmox_mutation_enabled"])
                self.assertEqual([], [call for call in client.calls if call[0] == "start_vm"])
                operation_store = SqlAlchemyOperationStore()
                operation = operation_store.get(raised.exception.detail["job_id"])
                latest_event = operation_store.list_events(operation.operation_id)[-1]
                self.assertEqual("blocked", operation.status)
                self.assertTrue(operation.details["pre_dispatch_terminal_no_effect"])
                self.assertFalse(operation.details["mutation_dispatched"])
                self.assertEqual("precheck_blocked", operation.details["pre_dispatch_terminal_reason"])
                self.assertTrue(operation.details["target_lock_id"].startswith("operation-lock-"))
                self.assertEqual("gjallar-mvp", operation.details["cluster_id"])
                self.assertTrue(latest_event.payload["pre_dispatch_terminal_no_effect"])
                self.assertFalse(latest_event.payload["mutation_dispatched"])

    def test_start_precheck_blocks_expected_name_context_mismatch(self):
        client = RecordingStartClient()

        with self.assertRaises(HTTPException) as raised:
            self._run_start(
                client=client,
                payload={
                    "vm_start_acknowledged": True,
                    "idempotency_key": "idem-name-mismatch",
                    "expected_name": "old-name",
                    "expected_status": "stopped",
                },
            )

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("VM_START_CONTEXT_MISMATCH", raised.exception.detail["code"])
        self.assertFalse(raised.exception.detail["proxmox_mutation_enabled"])
        self.assertEqual("stopped-app", raised.exception.detail["observed_before"]["name"])
        self.assertEqual([], [call for call in client.calls if call[0] == "start_vm"])

    def test_start_precheck_blocks_expected_status_context_mismatch(self):
        client = RecordingStartClient()

        with self.assertRaises(HTTPException) as raised:
            self._run_start(
                client=client,
                payload={
                    "vm_start_acknowledged": True,
                    "idempotency_key": "idem-status-mismatch",
                    "expected_name": "stopped-app",
                    "expected_status": "running",
                },
            )

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("VM_START_CONTEXT_MISMATCH", raised.exception.detail["code"])
        self.assertFalse(raised.exception.detail["proxmox_mutation_enabled"])
        self.assertEqual("stopped", raised.exception.detail["observed_before"]["status"])
        self.assertEqual([], [call for call in client.calls if call[0] == "start_vm"])

    def test_start_precheck_terminal_job_write_failure_retains_lock_for_common_recovery(self):
        from app.jobs.runs import get_job_run
        from app.operations.core.domain import OperationActor
        from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
        from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
        from app.operations.recovery.runtime import RecoveryRuntimeConfig, build_recovery_coordinator
        from app.operations.target_lock import get_target_operation_lock
        from app.operations.vm_start.domain import build_vm_start_job_id
        from app.vm_actions import start as start_module

        idempotency_key = "idem-precheck-terminal-job-write-failure"
        job_id = build_vm_start_job_id(node_id="node-a", vmid=306, idempotency_key=idempotency_key)
        original_record_job_run = start_module.record_job_run

        def fail_blocked_projection(**kwargs):
            if kwargs.get("status") == "blocked":
                raise RuntimeError("blocked start job projection unavailable")
            return original_record_job_run(**kwargs)

        client = RecordingStartClient()
        with patch("app.vm_actions.start.record_job_run", side_effect=fail_blocked_projection):
            with self.assertRaisesRegex(RuntimeError, "blocked start job projection unavailable"):
                self._run_start(
                    adapter=StubInventoryAdapter(vms=[stopped_vm(status="running")]),
                    client=client,
                    payload={
                        "vm_start_acknowledged": True,
                        "idempotency_key": idempotency_key,
                        "expected_name": "stopped-app",
                        "expected_status": "running",
                    },
                )

        operation_store = SqlAlchemyOperationStore()
        operation = operation_store.get(job_id)
        assert operation is not None
        self.assertEqual("blocked", operation.status)
        self.assertTrue(operation.details["pre_dispatch_terminal_no_effect"])
        self.assertEqual("running", get_job_run(job_id)["status"])
        self.assertIsNone(SqlAlchemyRecoveryStore().get(job_id))
        self.assertEqual(job_id, get_target_operation_lock("proxmox_vm", "vmid:306")["owner_id"])
        self.assertEqual([], client.calls)

        recovered = build_recovery_coordinator(
            config=RecoveryRuntimeConfig(enabled=True, poll_seconds=5, lease_seconds=60)
        ).observe(
            job_id,
            actor=OperationActor(user_id="operator-1", username="operator", role="operator"),
            expected_version=operation.version,
            expected_checksum=operation.last_event_checksum,
            idempotency_key="observe-start-precheck-job-write-failure",
        )

        self.assertEqual("blocked", recovered["outcome"])
        self.assertEqual("blocked", get_job_run(job_id)["status"])
        self.assertEqual("completed", SqlAlchemyRecoveryStore().get(job_id).status)
        self.assertIsNone(get_target_operation_lock("proxmox_vm", "vmid:306"))
        self.assertEqual([], client.calls)

    def test_start_success_writes_job_artifact_and_calls_proxmox_once(self):
        from app.jobs.artifacts import read_artifact_text
        from app.jobs.runs import get_job_run
        from app.operations.core.domain import verify_event_chain
        from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
        from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
        from app.operations.target_lock import get_target_operation_lock

        client = RecordingStartClient()
        response = self._run_start(client=client)

        self.assertTrue(response["ok"])
        self.assertEqual("proxmox_native_vm_start", response["meta"]["mode"])
        result = response["data"]
        self.assertTrue(result["proxmox_mutation_enabled"])
        self.assertFalse(result["idempotent_replay"])
        self.assertEqual("completed", result["status"])
        self.assertNotIn("path", result["target_operation_lock"])
        self.assertEqual("running", result["observed_after"]["status"])
        self.assertEqual(["start_vm", "wait_for_task", "get_vm_status"], [call[0] for call in client.calls])
        self.assertTrue(result["observed_after_artifact"]["path"].startswith("db://job-artifacts/"))
        artifact_payload = json.loads(read_artifact_text(result["observed_after_artifact"]))
        self.assertEqual("vm_start", artifact_payload["operation"])
        self.assertEqual("stopped", artifact_payload["observed_before"]["status"])
        self.assertEqual("running", artifact_payload["observed_after"]["status"])
        self.assertNotIn("api_url", artifact_payload["evidence"]["connection"])
        self.assertNotIn("token_id", artifact_payload["evidence"]["connection"])
        self.assertNotIn("token_secret", artifact_payload["evidence"]["connection"])
        self.assertEqual(
            ["vm_start", "task_status", "vm_status"],
            artifact_payload["evidence"]["observation_kinds"],
        )
        self.assertNotIn("start_endpoint", artifact_payload["evidence"])
        self.assertNotIn("task_status_endpoint", artifact_payload["evidence"])
        self.assertNotIn("post_check_endpoint", artifact_payload["evidence"])
        job = get_job_run(result["job_id"])
        self.assertEqual("vm_start", job["job_type"])
        self.assertEqual("completed", job["status"])
        self.assertNotIn("path", job["details"]["target_operation_lock"])
        self.assertEqual(
            {
                "schema": "vm_start_intent.v1",
                "operation": "vm_start",
                "target": {"node_id": "node-a", "vmid": 306},
                "expected": {"expected_name": "stopped-app", "expected_status": "stopped"},
            },
            job["details"]["vm_start_intent"],
        )
        self.assertTrue(any(artifact["type"] == "vm_start_observed_after" for artifact in job["artifacts"]))
        operation_store = SqlAlchemyOperationStore()
        operation = operation_store.get(result["job_id"])
        operation_events = operation_store.list_events(result["job_id"])
        self.assertEqual("succeeded", operation.status)
        self.assertEqual("managed_api", operation.execution_mode)
        self.assertEqual(
            [
                "operation_created",
                "dispatch_prepared",
                "dispatch_accepted",
                "task_and_state_observed",
                "verification_succeeded",
                "recovery_compatibility_projection_recorded",
            ],
            [event.event_type for event in operation_events],
        )
        self.assertTrue(verify_event_chain(operation_events))
        recovery = SqlAlchemyRecoveryStore().get(result["job_id"])
        self.assertIsNotNone(recovery)
        self.assertEqual("completed", recovery.status)
        self.assertIsNone(recovery.lease_owner)
        self.assertEqual(
            {
                "node": "node-a",
                "upid": "UPID:node-a:0001:start",
                "status": "stopped",
                "exitstatus": "OK",
            },
            recovery.details["task"],
        )
        self.assertNotIn("polls", recovery.details["task"])
        self.assertEqual(
            {
                "node_id": "node-a",
                "vmid": 306,
                "name": "stopped-app",
                "status": "running",
                "error": "",
            },
            recovery.details["observed_after"],
        )
        self.assertIsNone(get_target_operation_lock("proxmox_vm", "vmid:306"))

    def test_recovery_registration_failure_blocks_before_proxmox_dispatch(self):
        from app.jobs.runs import get_job_run
        from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
        from app.operations.target_lock import get_target_operation_lock

        client = RecordingStartClient()

        with patch(
            "app.vm_actions.start.SqlAlchemyRecoveryStore.prepare_and_claim",
            side_effect=RuntimeError("database unavailable"),
        ):
            with self.assertRaises(HTTPException) as raised:
                self._run_start(
                    client=client,
                    payload={
                        "vm_start_acknowledged": True,
                        "idempotency_key": "idem-recovery-registration-failure",
                        "expected_name": "stopped-app",
                        "expected_status": "stopped",
                    },
                )

        self.assertEqual(503, raised.exception.status_code)
        self.assertEqual("VM_START_RECOVERY_UNAVAILABLE", raised.exception.detail["code"])
        self.assertFalse(raised.exception.detail["proxmox_mutation_enabled"])
        self.assertEqual([], [call for call in client.calls if call[0] == "start_vm"])
        job_id = raised.exception.detail["job_id"]
        self.assertEqual("failed", get_job_run(job_id)["status"])
        operation_store = SqlAlchemyOperationStore()
        operation = operation_store.get(job_id)
        self.assertEqual("failed", operation.status)
        self.assertTrue(operation.details["pre_dispatch_terminal_no_effect"])
        self.assertFalse(operation.details["mutation_dispatched"])
        self.assertEqual("recovery_registration_failed", operation.details["pre_dispatch_terminal_reason"])
        self.assertTrue(operation.details["target_lock_id"].startswith("operation-lock-"))
        self.assertEqual("gjallar-mvp", operation.details["cluster_id"])
        self.assertEqual(
            operation.details["target_lock_id"],
            operation_store.list_events(job_id)[-1].payload["target_lock_id"],
        )
        self.assertIsNone(get_target_operation_lock("proxmox_vm", "vmid:306"))

    def test_missing_start_client_records_no_effect_marker_and_replay_does_not_acquire_new_lock(self):
        from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
        from app.operations.target_lock import get_target_operation_lock

        payload = {
            "vm_start_acknowledged": True,
            "idempotency_key": "idem-start-client-unavailable-marker",
            "expected_name": "stopped-app",
            "expected_status": "stopped",
        }
        inventory = StubInventoryAdapter(vms=[stopped_vm()])
        with patch.object(
            self.api_v1_router.inventory_context,
            "mutation_inventory_adapter",
            return_value=inventory,
        ), patch.object(
            self.api_v1_router,
            "get_default_proxmox_mutation_client",
            return_value=None,
        ):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(self.api_v1_router.start_vm_action("node-a", 306, payload))

        job_id = raised.exception.detail["job_id"]
        operation_store = SqlAlchemyOperationStore()
        operation = operation_store.get(job_id)
        latest_event = operation_store.list_events(job_id)[-1]
        self.assertEqual("failed", operation.status)
        self.assertTrue(operation.details["pre_dispatch_terminal_no_effect"])
        self.assertFalse(operation.details["mutation_dispatched"])
        self.assertEqual("mutation_client_unavailable", operation.details["pre_dispatch_terminal_reason"])
        self.assertEqual(operation.details["target_lock_id"], latest_event.payload["target_lock_id"])
        self.assertIsNone(get_target_operation_lock("proxmox_vm", "vmid:306"))

        replay_client = RecordingStartClient()
        replay = self._run_start(client=replay_client, payload=payload)

        self.assertTrue(replay["data"]["idempotent_replay"])
        self.assertEqual("failed", replay["data"]["status"])
        self.assertIsNone(get_target_operation_lock("proxmox_vm", "vmid:306"))
        self.assertEqual([], replay_client.calls)

    def _assert_start_no_effect_foreground_preserves_replay_completion(self, failure_mode):
        from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
        from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
        from app.operations.target_lock import get_target_operation_lock
        from app.vm_actions import start

        payload = {
            "vm_start_acknowledged": True,
            "idempotency_key": f"start-no-effect-replay-before-foreground-close-{failure_mode}",
            "expected_name": "stopped-app",
            "expected_status": "stopped",
        }
        original_record = start._CurrentVmStartJobAdapter.record
        original_prepare = SqlAlchemyRecoveryStore.prepare_and_claim
        client = RecordingStartClient()
        replay = None

        def create_client():
            if failure_mode == "factory_error":
                raise ProxmoxMutationError("client unavailable", details={})
            return client if failure_mode == "recovery_error" else None

        def prepare_recovery(store, *args, **kwargs):
            if failure_mode == "recovery_error" and kwargs["lease_owner"].startswith("foreground:"):
                raise RuntimeError("recovery unavailable")
            return original_prepare(store, *args, **kwargs)

        def record_then_replay(adapter, **kwargs):
            nonlocal replay
            job = original_record(adapter, **kwargs)
            if kwargs["status"] == "failed":
                replay = start.run_vm_start(
                    node_id="node-a", vmid=306, payload=payload,
                    inventory_adapter=StubInventoryAdapter(vms=[stopped_vm()]),
                )
            return job

        with patch.object(start._CurrentVmStartJobAdapter, "record", record_then_replay), patch.object(
            SqlAlchemyRecoveryStore, "prepare_and_claim", prepare_recovery,
        ), patch.object(start._CurrentVmStartLockAdapter, "release_target", autospec=True) as release:
            with self.assertRaises(start.VmStartError) as raised:
                start.run_vm_start(
                    node_id="node-a", vmid=306, payload=payload,
                    inventory_adapter=StubInventoryAdapter(vms=[stopped_vm()]),
                    client_factory=create_client,
                )

        expected_code = "VM_START_RECOVERY_UNAVAILABLE" if failure_mode == "recovery_error" else "VM_START_CLIENT_UNAVAILABLE"
        self.assertEqual(expected_code, raised.exception.code)
        self.assertTrue(replay["idempotent_replay"])
        job_id = replay["job_id"]
        store = SqlAlchemyOperationStore()
        self.assertEqual("failed", store.get(job_id).status)
        self.assertEqual("replayed_pre_dispatch_failure_closed", store.list_events(job_id)[-1].event_type)
        self.assertEqual("completed", SqlAlchemyRecoveryStore().get(job_id).status)
        self.assertIsNone(get_target_operation_lock("proxmox_vm", "vmid:306"))
        self.assertEqual([], client.calls)
        release.assert_not_called()

    def test_start_no_effect_foreground_preserves_replay_completion(self):
        self._assert_start_no_effect_foreground_preserves_replay_completion("missing_client")

    def test_start_failed_client_factory_preserves_replay_completion(self):
        self._assert_start_no_effect_foreground_preserves_replay_completion("factory_error")

    def test_start_recovery_registration_failure_preserves_replay_completion(self):
        self._assert_start_no_effect_foreground_preserves_replay_completion("recovery_error")

    def _assert_start_no_effect_foreground_replay_lease_race(self, *, claim_before_foreground):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event, local
        from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
        from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
        from app.operations.target_lock import get_target_operation_lock
        from app.vm_actions import start

        payload = {
            "vm_start_acknowledged": True,
            "idempotency_key": f"start-no-effect-replay-lease-{claim_before_foreground}",
            "expected_name": "stopped-app",
            "expected_status": "stopped",
        }
        job_ready = Event()
        replay_ready = Event()
        foreground_done = Event()
        worker = local()
        original_record = start._CurrentVmStartJobAdapter.record
        original_prepare = SqlAlchemyRecoveryStore.prepare_and_claim
        original_release = start._CurrentVmStartLockAdapter.release_target

        def record_then_wait(adapter, **kwargs):
            job = original_record(adapter, **kwargs)
            if kwargs["status"] == "failed" and not worker.is_replay:
                job_ready.set()
                self.assertTrue(replay_ready.wait(5))
            return job

        def prepare_around_foreground(store, *args, **kwargs):
            if not worker.is_replay:
                return original_prepare(store, *args, **kwargs)
            if claim_before_foreground:
                lease = original_prepare(store, *args, **kwargs)
            replay_ready.set()
            self.assertTrue(foreground_done.wait(5))
            return lease if claim_before_foreground else original_prepare(store, *args, **kwargs)

        def invoke(is_replay):
            worker.is_replay = is_replay
            try:
                return start.run_vm_start(
                    node_id="node-a", vmid=306, payload=payload,
                    inventory_adapter=StubInventoryAdapter(vms=[stopped_vm()]),
                )
            except start.VmStartError as exc:
                return exc
            finally:
                if not is_replay:
                    foreground_done.set()

        with patch.object(start._CurrentVmStartJobAdapter, "record", record_then_wait), patch.object(
            SqlAlchemyRecoveryStore, "prepare_and_claim", prepare_around_foreground,
        ), patch.object(
            start._CurrentVmStartLockAdapter, "release_target", autospec=True, side_effect=original_release,
        ) as release, ThreadPoolExecutor(max_workers=2) as executor:
            foreground_future = executor.submit(invoke, False)
            self.assertTrue(job_ready.wait(5))
            replay_future = executor.submit(invoke, True)
            foreground = foreground_future.result(timeout=10)
            replay = replay_future.result(timeout=10)

        self.assertIsInstance(foreground, start.VmStartError)
        self.assertEqual("VM_START_CLIENT_UNAVAILABLE", foreground.code)
        self.assertIsInstance(replay, dict)
        self.assertTrue(replay["idempotent_replay"])
        job_id = replay["job_id"]
        self.assertEqual("failed", SqlAlchemyOperationStore().get(job_id).status)
        recovery = SqlAlchemyRecoveryStore().get(job_id)
        if claim_before_foreground:
            self.assertEqual("completed", recovery.status)
            release.assert_not_called()
        else:
            self.assertIsNone(recovery)
            self.assertEqual(1, release.call_count)
        self.assertIsNone(get_target_operation_lock("proxmox_vm", "vmid:306"))

    def test_start_no_effect_foreground_does_not_invalidate_claimed_replay_lease(self):
        self._assert_start_no_effect_foreground_replay_lease_race(claim_before_foreground=True)

    def test_start_no_effect_replay_accepts_foreground_completion_before_claim(self):
        self._assert_start_no_effect_foreground_replay_lease_race(claim_before_foreground=False)

    def test_terminal_no_effect_crash_after_start_commit_is_operator_recoverable_without_proxmox(self):
        from app.operations.core.domain import OperationActor
        from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
        from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
        from app.operations.recovery.runtime import RecoveryRuntimeConfig, build_recovery_coordinator
        from app.operations.target_lock import get_target_operation_lock

        client = RecordingStartClient()
        with patch(
            "app.vm_actions.start.SqlAlchemyRecoveryStore.prepare_and_claim",
            side_effect=RuntimeError("database unavailable"),
        ), patch(
            "app.vm_actions.start._CurrentVmStartLockAdapter.release_target",
            return_value=None,
        ):
            with self.assertRaises(HTTPException) as raised:
                self._run_start(
                    client=client,
                    payload={
                        "vm_start_acknowledged": True,
                        "idempotency_key": "idem-start-terminal-release-crash",
                        "expected_name": "stopped-app",
                        "expected_status": "stopped",
                    },
                )

        job_id = raised.exception.detail["job_id"]
        operation_store = SqlAlchemyOperationStore()
        operation = operation_store.get(job_id)
        self.assertEqual("failed", operation.status)
        self.assertEqual("recovery_registration_failed", operation.details["pre_dispatch_terminal_reason"])
        self.assertEqual(job_id, get_target_operation_lock("proxmox_vm", "vmid:306")["owner_id"])
        self.assertIsNone(SqlAlchemyRecoveryStore().get(job_id))

        recovered = build_recovery_coordinator(
            config=RecoveryRuntimeConfig(enabled=True, poll_seconds=5, lease_seconds=60)
        ).observe(
            job_id,
            actor=OperationActor(user_id="operator-1", username="operator", role="operator"),
            expected_version=operation.version,
            expected_checksum=operation.last_event_checksum,
            idempotency_key="observe-start-terminal-release-crash",
        )

        self.assertEqual("failed", recovered["outcome"])
        self.assertEqual("failed", operation_store.get(job_id).status)
        self.assertEqual("completed", SqlAlchemyRecoveryStore().get(job_id).status)
        self.assertIsNone(get_target_operation_lock("proxmox_vm", "vmid:306"))
        self.assertEqual([], client.calls)



    def test_recovery_registration_operation_write_failure_retains_lock_until_same_key_closes_canonical(self):
        from app.jobs.runs import get_job_run
        from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
        from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
        from app.operations.target_lock import get_target_operation_lock

        client = RecordingStartClient()
        payload = {
            "vm_start_acknowledged": True,
            "idempotency_key": "idem-recovery-operation-write-failure",
            "expected_name": "stopped-app",
            "expected_status": "stopped",
        }
        with patch(
            "app.vm_actions.start.SqlAlchemyRecoveryStore.prepare_and_claim",
            side_effect=RuntimeError("recovery database unavailable"),
        ), patch(
            "app.vm_actions.start.SqlAlchemyOperationStore.transition_pre_dispatch_failure",
            side_effect=RuntimeError("operation transition unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "operation transition unavailable"):
                self._run_start(client=client, payload=payload)

        from app.vm_actions.start import build_vm_start_job_id

        job_id = build_vm_start_job_id(node_id="node-a", vmid=306, idempotency_key=payload["idempotency_key"])
        operation_store = SqlAlchemyOperationStore()
        job = get_job_run(job_id)
        self.assertEqual("failed", job["status"])
        self.assertTrue(job["details"]["vm_start_result"]["pre_dispatch_no_effect_verified"])
        self.assertEqual("planned", operation_store.get(job_id).status)
        self.assertEqual(job_id, get_target_operation_lock("proxmox_vm", "vmid:306")["owner_id"])
        self.assertEqual([], client.calls)

        replay = self._run_start(client=client, payload=payload)

        self.assertTrue(replay["data"]["idempotent_replay"])
        self.assertEqual("failed", replay["data"]["status"])
        operation = operation_store.get(job_id)
        self.assertEqual("failed", operation.status)
        self.assertTrue(operation.details["recovered_pre_dispatch"])
        self.assertEqual("replayed_pre_dispatch_failure_closed", operation_store.list_events(job_id)[-1].event_type)
        self.assertEqual("completed", SqlAlchemyRecoveryStore().get(job_id).status)
        self.assertIsNone(get_target_operation_lock("proxmox_vm", "vmid:306"))
        self.assertEqual([], client.calls)



    def test_duplicate_idempotency_key_returns_existing_job_without_second_start(self):
        client = RecordingStartClient()
        payload = {
            "vm_start_acknowledged": True,
            "idempotency_key": "same-idem-key",
            "expected_name": "stopped-app",
            "expected_status": "stopped",
        }

        first = self._run_start(client=client, payload=payload)
        second = self._run_start(client=client, payload=payload)

        self.assertEqual(first["data"]["job_id"], second["data"]["job_id"])
        self.assertTrue(first["data"]["proxmox_mutation_enabled"])
        self.assertFalse(second["data"]["proxmox_mutation_enabled"])
        self.assertTrue(second["data"]["idempotent_replay"])
        self.assertEqual(1, len([call for call in client.calls if call[0] == "start_vm"]))

    def test_start_rechecks_job_when_owner_completes_after_initial_job_lookup(self):
        from app.vm_actions import start

        payload = {
            "vm_start_acknowledged": True,
            "idempotency_key": "start-owner-finishes-before-prepare",
            "expected_name": "stopped-app",
            "expected_status": "stopped",
        }
        owner_client = RecordingStartClient()
        replay_client = RecordingStartClient()
        original_get = start._CurrentVmStartJobAdapter.get
        first_lookup = True

        def get_after_owner_finishes(adapter, job_id):
            nonlocal first_lookup
            if first_lookup:
                first_lookup = False
                start.run_vm_start(
                    node_id="node-a", vmid=306, payload=payload,
                    inventory_adapter=StubInventoryAdapter(vms=[stopped_vm()]),
                    client=owner_client,
                )
                return None
            return original_get(adapter, job_id)

        with patch.object(start._CurrentVmStartJobAdapter, "get", get_after_owner_finishes):
            response = self._run_start(client=replay_client, payload=payload)

        self.assertEqual("completed", response["data"]["status"])
        self.assertTrue(response["data"]["idempotent_replay"])
        self.assertEqual([], replay_client.calls)
        self.assertEqual(1, sum(call[0] == "start_vm" for call in owner_client.calls))

    def test_start_rechecks_terminal_projection_after_acquiring_target_lock(self):
        from app.jobs.runs import get_job_run, record_job_run
        from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
        from app.vm_actions import start

        original_acquire = start._CurrentVmStartLockAdapter.acquire_target
        completed_job = None

        def acquire_after_owner_finishes(adapter, target_type, target_id, operation_id):
            nonlocal completed_job
            store = SqlAlchemyOperationStore()
            for status in ("dispatching", "running", "verifying", "succeeded"):
                store.transition(operation_id, next_status=status, event_type=status, stage="post_check")
            completed_job = record_job_run(
                job_id=operation_id, job_type="vm_start", status="completed",
                target_id="node-a:306:stopped-app", risk_level="unknown",
                stage="post_check", step_status="completed", message="Owner completed VM start",
                details={"vm_start_result": {"proxmox_mutation_enabled": True}},
            )
            return original_acquire(adapter, target_type, target_id, operation_id)

        client = RecordingStartClient()
        with patch.object(start._CurrentVmStartLockAdapter, "acquire_target", acquire_after_owner_finishes):
            response = self._run_start(client=client)

        self.assertEqual("completed", response["data"]["status"])
        self.assertTrue(response["data"]["idempotent_replay"])
        self.assertEqual(completed_job, get_job_run(response["data"]["job_id"]))
        self.assertEqual("succeeded", SqlAlchemyOperationStore().get(response["data"]["job_id"]).status)
        self.assertEqual([], client.calls)

    def test_start_same_owner_busy_rechecks_new_job_without_changing_operation(self):
        from app.jobs.runs import record_job_run
        from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
        from app.operations.target_lock import acquire_target_operation_lock, release_target_operation_lock
        from app.vm_actions import start

        original_acquire = start._CurrentVmStartLockAdapter.acquire_target
        owner_handle = None

        def acquire_after_owner_records_job(adapter, target_type, target_id, operation_id):
            nonlocal owner_handle
            owner_handle = acquire_target_operation_lock(
                target_type, target_id, operation_id, operation_type="vm_start",
            )
            record_job_run(
                job_id=operation_id, job_type="vm_start", status="running",
                target_id="node-a:306:stopped-app", risk_level="unknown",
                stage="precheck", step_status="running", message="Owner precheck",
            )
            return original_acquire(adapter, target_type, target_id, operation_id)

        client = RecordingStartClient()
        try:
            with patch.object(start._CurrentVmStartLockAdapter, "acquire_target", acquire_after_owner_records_job):
                response = self._run_start(client=client)
            self.assertEqual("running", response["data"]["status"])
            self.assertTrue(response["data"]["idempotent_replay"])
            store = SqlAlchemyOperationStore()
            self.assertEqual("planned", store.get(response["data"]["job_id"]).status)
            self.assertEqual(1, len(store.list_events(response["data"]["job_id"])))
            self.assertEqual([], client.calls)
        finally:
            if owner_handle is not None:
                release_target_operation_lock(owner_handle)

    def test_start_concurrent_foreign_busy_projection_returns_stable_conflict(self):
        from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
        from app.operations.target_lock import acquire_target_operation_lock, release_target_operation_lock

        original_transition = SqlAlchemyOperationStore.transition_for_target_lock_conflict
        competing_transition = True

        def transition_after_competing_request(store, operation_id, **kwargs):
            nonlocal competing_transition
            if competing_transition and kwargs["event_type"] == "target_lock_blocked":
                competing_transition = False
                original_transition(store, operation_id, **kwargs)
            return original_transition(store, operation_id, **kwargs)

        owner_lock = acquire_target_operation_lock("proxmox_vm", "vmid:306", "foreign-owner", operation_type="vm_start")
        client = RecordingStartClient()
        try:
            with patch.object(SqlAlchemyOperationStore, "transition_for_target_lock_conflict", transition_after_competing_request):
                with self.assertRaises(HTTPException) as raised:
                    self._run_start(client=client)
            self.assertEqual(409, raised.exception.status_code)
            self.assertEqual("VM_START_TARGET_LOCK_BUSY", raised.exception.detail["code"])
            self.assertEqual("foreign-owner", raised.exception.detail["conflicting_operation_id"])
            store = SqlAlchemyOperationStore()
            operation_id = raised.exception.detail["operation_id"]
            self.assertEqual("blocked", store.get(operation_id).status)
            self.assertEqual(2, len(store.list_events(operation_id)))
            self.assertEqual([], client.calls)
        finally:
            release_target_operation_lock(owner_lock)

    def test_start_stale_foreign_busy_does_not_block_new_same_key_lock_owner(self):
        from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
        from app.operations.target_lock import (
            acquire_target_operation_lock, get_target_operation_lock, release_target_operation_lock,
        )

        foreign_lock = acquire_target_operation_lock(
            "proxmox_vm", "vmid:306", "foreign-owner", operation_type="vm_start",
        )
        original_transition = SqlAlchemyOperationStore.transition_for_target_lock_conflict
        new_owner_lock = None

        def transition_after_lock_changes_owner(store, operation_id, **kwargs):
            nonlocal new_owner_lock
            release_target_operation_lock(foreign_lock)
            new_owner_lock = acquire_target_operation_lock(
                "proxmox_vm", "vmid:306", operation_id, operation_type="vm_start",
            )
            return original_transition(store, operation_id, **kwargs)

        client = RecordingStartClient()
        try:
            with patch.object(SqlAlchemyOperationStore, "transition_for_target_lock_conflict", transition_after_lock_changes_owner):
                with self.assertRaises(HTTPException) as raised:
                    self._run_start(client=client)
            self.assertEqual("VM_START_TARGET_LOCK_BUSY", raised.exception.detail["code"])
            operation_id = raised.exception.detail["operation_id"]
            store = SqlAlchemyOperationStore()
            self.assertEqual("planned", store.get(operation_id).status)
            self.assertEqual(1, len(store.list_events(operation_id)))
            self.assertEqual(operation_id, get_target_operation_lock("proxmox_vm", "vmid:306")["owner_id"])
            self.assertEqual([], client.calls)
        finally:
            if new_owner_lock is not None:
                release_target_operation_lock(new_owner_lock)
            release_target_operation_lock(foreign_lock)

    def test_start_ignores_and_preserves_historical_request_lock_file(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from app.vm_actions import start

        with TemporaryDirectory() as temporary_directory:
            lock_path = Path(temporary_directory) / "vm_start.lock"
            lock_path.write_text("historical-owner", encoding="utf-8")
            client = RecordingStartClient()
            with patch.object(start, "run_dir", return_value=lock_path.parent):
                response = self._run_start(client=client)
                replay = self._run_start(client=client)

            self.assertEqual("completed", response["data"]["status"])
            self.assertTrue(replay["data"]["idempotent_replay"])
            self.assertEqual("historical-owner", lock_path.read_text(encoding="utf-8"))
            self.assertEqual(1, sum(call[0] == "start_vm" for call in client.calls))

    def test_duplicate_idempotency_key_with_different_intent_is_conflict(self):
        client = RecordingStartClient()
        payload = {
            "vm_start_acknowledged": True,
            "idempotency_key": "same-key-different-intent",
            "expected_name": "stopped-app",
            "expected_status": "stopped",
        }

        first = self._run_start(client=client, payload=payload)
        with self.assertRaises(HTTPException) as raised:
            self._run_start(
                client=client,
                payload={**payload, "expected_status": "running"},
            )

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("VM_START_IDEMPOTENCY_CONFLICT", raised.exception.detail["code"])
        self.assertEqual(first["data"]["job_id"], raised.exception.detail["job_id"])
        self.assertEqual(1, len([call for call in client.calls if call[0] == "start_vm"]))

    def test_legacy_duplicate_without_stored_intent_keeps_replay_compatibility(self):
        from app.jobs.runs import record_job_run
        from app.vm_actions.start import build_vm_start_job_id

        job_id = build_vm_start_job_id(node_id="node-a", vmid=306, idempotency_key="legacy-idem")
        record_job_run(
            job_id=job_id,
            job_type="vm_start",
            status="completed",
            target_id="node-a:306:stopped-app",
            risk_level="unknown",
            stage="post_check",
            step_status="completed",
            message="Legacy VM start job",
            details={
                "target": {"node_id": "node-a", "vmid": 306, "name": "stopped-app"},
                "vm_start_result": {
                    "job_id": job_id,
                    "status": "completed",
                    "target": {"node_id": "node-a", "vmid": 306, "name": "stopped-app"},
                    "proxmox_mutation_enabled": True,
                },
            },
        )
        client = RecordingStartClient()

        response = self._run_start(
            client=client,
            payload={
                "vm_start_acknowledged": True,
                "idempotency_key": "legacy-idem",
                "expected_name": "stopped-app",
                "expected_status": "running",
            },
        )

        self.assertTrue(response["data"]["idempotent_replay"])
        self.assertEqual([], [call for call in client.calls if call[0] == "start_vm"])

    def test_target_lock_blocks_different_idempotency_key_for_same_vm(self):
        from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
        from app.operations.target_lock import acquire_target_operation_lock, release_target_operation_lock
        from app.vm_actions.start import build_vm_start_job_id

        handle = acquire_target_operation_lock("proxmox_vm", "vmid:306", "other-job", operation_type="vm_start")
        client = RecordingStartClient()
        idempotency_key = "different-idem-while-target-busy"
        operation_id = build_vm_start_job_id(node_id="node-a", vmid=306, idempotency_key=idempotency_key)
        try:
            with self.assertRaises(HTTPException) as raised:
                self._run_start(
                    client=client,
                    payload={
                        "vm_start_acknowledged": True,
                        "idempotency_key": idempotency_key,
                        "expected_name": "stopped-app",
                        "expected_status": "stopped",
                    },
                )
        finally:
            release_target_operation_lock(handle)

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("VM_START_TARGET_LOCK_BUSY", raised.exception.detail["code"])
        self.assertEqual(operation_id, raised.exception.detail["operation_id"])
        self.assertEqual("other-job", raised.exception.detail["conflicting_operation_id"])
        operation_store = SqlAlchemyOperationStore()
        operation = operation_store.get(operation_id)
        events = operation_store.list_events(operation_id)
        self.assertEqual("blocked", operation.status)
        self.assertEqual("precheck", operation.current_stage)
        self.assertEqual("other-job", operation.details["conflicting_operation_id"])
        self.assertEqual(
            "other-job",
            operation.details["target_operation_lock"]["existing"]["owner_id"],
        )
        self.assertEqual("target_lock_blocked", events[-1].event_type)
        self.assertEqual("planned", events[-1].from_status)
        self.assertEqual("blocked", events[-1].to_status)
        self.assertEqual("other-job", events[-1].payload["conflicting_operation_id"])
        self.assertFalse(raised.exception.detail["proxmox_mutation_enabled"])
        self.assertNotIn("path", raised.exception.detail["target_operation_lock"])
        self.assertEqual([], [call for call in client.calls if call[0] == "start_vm"])

    def test_same_operation_target_lock_collision_is_in_progress_without_blocking_owner(self):
        from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
        from app.operations.target_lock import (
            acquire_target_operation_lock,
            get_target_operation_lock,
            release_target_operation_lock,
        )
        from app.vm_actions.start import build_vm_start_job_id

        idempotency_key = "same-owner-target-lock"
        operation_id = build_vm_start_job_id(
            node_id="node-a",
            vmid=306,
            idempotency_key=idempotency_key,
        )
        owner_lock = acquire_target_operation_lock(
            "proxmox_vm",
            "vmid:306",
            operation_id,
            operation_type="vm_start",
        )
        client = RecordingStartClient()
        try:
            with self.assertRaises(HTTPException) as raised:
                self._run_start(
                    client=client,
                    payload={
                        "vm_start_acknowledged": True,
                        "idempotency_key": idempotency_key,
                        "expected_name": "stopped-app",
                        "expected_status": "stopped",
                    },
                )

            self.assertEqual(409, raised.exception.status_code)
            self.assertEqual("VM_START_IN_PROGRESS", raised.exception.detail["code"])
            operation_store = SqlAlchemyOperationStore()
            operation = operation_store.get(operation_id)
            self.assertEqual("planned", operation.status)
            self.assertEqual(
                ["operation_created"],
                [event.event_type for event in operation_store.list_events(operation_id)],
            )
            active_lock = get_target_operation_lock("proxmox_vm", "vmid:306")
            self.assertEqual(operation_id, active_lock["owner_id"])
            self.assertEqual([], client.calls)
        finally:
            release_target_operation_lock(owner_lock)

    def test_task_failure_returns_409_with_artifact_and_failed_job(self):
        from app.jobs.runs import get_job_run

        client = RecordingStartClient(task_exitstatus="ERROR", post_status="stopped")
        with self.assertRaises(HTTPException) as raised:
            self._run_start(client=client, payload={
                "vm_start_acknowledged": True,
                "idempotency_key": "idem-task-failed",
                "expected_name": "stopped-app",
                "expected_status": "stopped",
            })

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("VM_START_TASK_FAILED", raised.exception.detail["code"])
        self.assertTrue(raised.exception.detail["proxmox_mutation_enabled"])
        self.assertTrue(raised.exception.detail["observed_after_artifact"]["path"].startswith("db://job-artifacts/"))
        job = get_job_run(raised.exception.detail["job_id"])
        self.assertEqual("failed", job["status"])
        self.assertEqual("task_poll", job["current_stage"])

    def test_definitive_4xx_start_rejection_releases_target_lock(self):
        from app.jobs.runs import get_job_run
        from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore

        rejecting_client = RecordingStartClient(
            start_error=ProxmoxMutationError(
                "bad request",
                details={
                    "method": "POST",
                    "path": "/nodes/node-a/qemu/306/status/start",
                    "status_code": 400,
                    "response_text": "opaque-start-customer-value",
                    "response_json": {
                        "errors": {"vmid": "opaque-start-customer-description"}
                    },
                },
            )
        )
        with self.assertRaises(HTTPException) as raised:
            self._run_start(client=rejecting_client, payload={
                "vm_start_acknowledged": True,
                "idempotency_key": "idem-definitive-4xx",
                "expected_name": "stopped-app",
                "expected_status": "stopped",
            })

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("VM_START_REQUEST_FAILED", raised.exception.detail["code"])
        self.assertFalse(raised.exception.detail["proxmox_mutation_enabled"])
        self.assertNotIn("path", raised.exception.detail["target_operation_lock"])
        job = get_job_run(raised.exception.detail["job_id"])
        self.assertEqual("failed", job["status"])
        self.assertNotIn("path", job["details"]["target_operation_lock"])
        operation_events = SqlAlchemyOperationStore().list_events(
            raised.exception.detail["job_id"]
        )
        serialized = json.dumps(
            {
                "error": raised.exception.detail,
                "job": job,
                "events": [event.payload for event in operation_events],
            },
            sort_keys=True,
        )
        self.assertNotIn("opaque-start-customer-value", serialized)
        self.assertNotIn("opaque-start-customer-description", serialized)
        self.assertNotIn("response_text", serialized)
        self.assertNotIn("response_json", serialized)
        self.assertNotIn("/nodes/node-a/qemu/306/status/start", serialized)

        allowed_client = RecordingStartClient()
        response = self._run_start(client=allowed_client, payload={
            "vm_start_acknowledged": True,
            "idempotency_key": "idem-after-definitive-4xx",
            "expected_name": "stopped-app",
            "expected_status": "stopped",
        })
        self.assertEqual("completed", response["data"]["status"])
        self.assertEqual(1, len([call for call in allowed_client.calls if call[0] == "start_vm"]))

    def test_definitive_4xx_projection_failure_keeps_recovery_retryable_until_handler_finishes(self):
        from app.jobs.runs import get_job_run
        from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
        from app.operations.recovery.application import VmStartRecoveryHandler
        from app.operations.recovery.infrastructure.job_projection import SqlAlchemyVmStartRecoveryJobProjection
        from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
        from app.operations.target_lock import get_target_operation_lock
        from app.vm_actions import start as start_module
        from app.vm_actions.start import build_vm_start_job_id

        idempotency_key = "idem-definitive-4xx-projection-failed"
        operation_id = build_vm_start_job_id(
            node_id="node-a",
            vmid=306,
            idempotency_key=idempotency_key,
        )
        original_record_job_run = start_module.record_job_run

        def fail_failed_projection(**kwargs):
            if kwargs.get("status") == "failed":
                raise RuntimeError("failed job projection unavailable")
            return original_record_job_run(**kwargs)

        rejecting_client = RecordingStartClient(
            start_error=ProxmoxMutationError("bad request", details={"status_code": 400})
        )
        with patch("app.vm_actions.start.record_job_run", side_effect=fail_failed_projection):
            with self.assertRaises(HTTPException) as raised:
                self._run_start(
                    client=rejecting_client,
                    payload={
                        "vm_start_acknowledged": True,
                        "idempotency_key": idempotency_key,
                        "expected_name": "stopped-app",
                        "expected_status": "stopped",
                    },
                )

        self.assertEqual(503, raised.exception.status_code)
        self.assertEqual(
            "VM_START_COMPATIBILITY_PROJECTION_PERSISTENCE_UNAVAILABLE",
            raised.exception.detail["code"],
        )
        self.assertEqual(operation_id, raised.exception.detail["operation_id"])
        self.assertEqual(operation_id, raised.exception.detail["job_id"])
        self.assertEqual("failed", raised.exception.detail["operation_status"])
        self.assertEqual("retry_wait", raised.exception.detail["recovery_status"])
        self.assertEqual("not_required", raised.exception.detail["evidence_status"])
        self.assertFalse(raised.exception.detail["evidence_recorded"])
        self.assertEqual(
            ["proxmox_start_request_rejected"],
            raised.exception.detail["side_effects"],
        )

        operation_store = SqlAlchemyOperationStore()
        recovery_store = SqlAlchemyRecoveryStore()
        self.assertEqual("failed", operation_store.get(operation_id).status)
        self.assertEqual("retry_wait", recovery_store.get(operation_id).status)
        self.assertEqual("running", get_job_run(operation_id)["status"])
        self.assertEqual(
            "compatibility_projection_persistence_failed",
            operation_store.list_events(operation_id)[-1].event_type,
        )
        self.assertEqual(operation_id, get_target_operation_lock("proxmox_vm", "vmid:306")["owner_id"])
        self.assertEqual(["start_vm"], [call[0] for call in rejecting_client.calls])

        lease = recovery_store.claim_due(lease_owner="start-recovery-test", lease_seconds=60)[0]
        handler = VmStartRecoveryHandler(
            recovery=recovery_store,
            operations=operation_store,
            observation_factory=lambda: self.fail("terminal rejection recovery must not observe Proxmox"),
            compatibility_projection=SqlAlchemyVmStartRecoveryJobProjection(),

            target_lock_reader=get_target_operation_lock,
        )

        recovered = handler.handle(lease)

        self.assertEqual("failed", recovered.outcome)
        self.assertEqual("failed", get_job_run(operation_id)["status"])
        self.assertEqual("completed", recovery_store.get(operation_id).status)
        self.assertIsNone(get_target_operation_lock("proxmox_vm", "vmid:306"))

    def test_ambiguous_408_start_error_preserves_needs_reconciliation_and_lock(self):
        from app.jobs.runs import get_job_run
        from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore

        client = RecordingStartClient(
            start_error=ProxmoxMutationError("request timeout", details={"status_code": 408}),
            post_status="stopped",
        )
        with self.assertRaises(HTTPException) as raised:
            self._run_start(client=client, payload={
                "vm_start_acknowledged": True,
                "idempotency_key": "idem-ambiguous-408",
                "expected_name": "stopped-app",
                "expected_status": "stopped",
            })

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("VM_START_REQUEST_RECONCILIATION_REQUIRED", raised.exception.detail["code"])
        self.assertTrue(raised.exception.detail["proxmox_mutation_enabled"])
        self.assertNotIn("path", raised.exception.detail["target_operation_lock"])
        job = get_job_run(raised.exception.detail["job_id"])
        self.assertEqual("needs_reconciliation", job["status"])
        self.assertNotIn("path", job["details"]["target_operation_lock"])
        operation = SqlAlchemyOperationStore().get(raised.exception.detail["job_id"])
        self.assertEqual("needs_reconciliation", operation.status)

        with self.assertRaises(HTTPException) as blocked:
            self._run_start(client=client, payload={
                "vm_start_acknowledged": True,
                "idempotency_key": "idem-after-ambiguous-408",
                "expected_name": "stopped-app",
                "expected_status": "stopped",
            })
        self.assertEqual("VM_START_TARGET_LOCK_BUSY", blocked.exception.detail["code"])

    def test_post_check_non_running_returns_409_with_artifact_and_needs_reconciliation_job(self):
        from app.jobs.runs import get_job_run

        client = RecordingStartClient(post_status="stopped")
        with self.assertRaises(HTTPException) as raised:
            self._run_start(client=client, payload={
                "vm_start_acknowledged": True,
                "idempotency_key": "idem-post-check-needs-reconciliation",
                "expected_name": "stopped-app",
                "expected_status": "stopped",
            })

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("VM_START_POST_CHECK_RECONCILIATION_REQUIRED", raised.exception.detail["code"])
        self.assertTrue(raised.exception.detail["proxmox_mutation_enabled"])
        self.assertEqual("stopped", raised.exception.detail["observed_after"]["status"])
        self.assertTrue(raised.exception.detail["observed_after_artifact"]["path"].startswith("db://job-artifacts/"))
        self.assertNotIn("path", raised.exception.detail["target_operation_lock"])
        job = get_job_run(raised.exception.detail["job_id"])
        self.assertEqual("needs_reconciliation", job["status"])
        self.assertEqual("post_check", job["current_stage"])
        self.assertTrue(job["details"]["vm_start_result"]["reconciliation_required"])
        self.assertNotIn("path", job["details"]["target_operation_lock"])

    def test_missing_upid_preserves_needs_reconciliation_and_blocks_second_mutation(self):
        from app.jobs.runs import get_job_run

        client = RecordingStartClient(start_upid="", post_status="stopped")
        with self.assertRaises(HTTPException) as raised:
            self._run_start(client=client, payload={
                "vm_start_acknowledged": True,
                "idempotency_key": "idem-missing-upid",
                "expected_name": "stopped-app",
                "expected_status": "stopped",
            })

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("VM_START_REQUEST_RECONCILIATION_REQUIRED", raised.exception.detail["code"])
        job_id = raised.exception.detail["job_id"]
        job = get_job_run(job_id)
        self.assertEqual("needs_reconciliation", job["status"])
        self.assertNotIn("path", raised.exception.detail["target_operation_lock"])
        self.assertNotIn("path", job["details"]["target_operation_lock"])

        replay = self._run_start(client=client, payload={
            "vm_start_acknowledged": True,
            "idempotency_key": "idem-missing-upid",
            "expected_name": "stopped-app",
            "expected_status": "stopped",
        })
        self.assertTrue(replay["data"]["idempotent_replay"])
        self.assertFalse(replay["data"]["proxmox_mutation_enabled"])

        with self.assertRaises(HTTPException) as blocked:
            self._run_start(client=client, payload={
                "vm_start_acknowledged": True,
                "idempotency_key": "idem-after-retained-lock",
                "expected_name": "stopped-app",
                "expected_status": "stopped",
            })
        self.assertEqual("VM_START_TARGET_LOCK_BUSY", blocked.exception.detail["code"])
        self.assertEqual(1, len([call for call in client.calls if call[0] == "start_vm"]))

    def test_invalid_upid_is_not_persisted_or_used_for_task_observation(self):
        from app.jobs.runs import get_job_run
        from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore

        opaque_locator = "opaque-secret?token=do-not-store"
        client = RecordingStartClient(start_upid=opaque_locator, post_status="stopped")
        with self.assertRaises(HTTPException) as raised:
            self._run_start(
                client=client,
                payload={
                    "vm_start_acknowledged": True,
                    "idempotency_key": "idem-invalid-upid",
                    "expected_name": "stopped-app",
                    "expected_status": "stopped",
                },
            )

        self.assertEqual("VM_START_REQUEST_RECONCILIATION_REQUIRED", raised.exception.detail["code"])
        operation_id = raised.exception.detail["job_id"]
        operation_store = SqlAlchemyOperationStore()
        serialized = json.dumps(
            {
                "detail": raised.exception.detail,
                "job": get_job_run(operation_id),
                "operation": operation_store.get(operation_id).details,
                "events": [event.payload for event in operation_store.list_events(operation_id)],
            },
            sort_keys=True,
        )
        self.assertNotIn(opaque_locator, serialized)
        self.assertNotIn("wait_for_task", [call[0] for call in client.calls])

    def test_task_poll_timeout_preserves_needs_reconciliation(self):
        from app.jobs.runs import get_job_run

        client = RecordingStartClient(
            wait_error=ProxmoxMutationError(
                "Timed out waiting for Proxmox task",
                details={"node": "node-a", "upid": "UPID:node-a:0001:start"},
            ),
            post_status="stopped",
        )
        with self.assertRaises(HTTPException) as raised:
            self._run_start(client=client, payload={
                "vm_start_acknowledged": True,
                "idempotency_key": "idem-task-timeout",
                "expected_name": "stopped-app",
                "expected_status": "stopped",
            })

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("VM_START_TASK_RECONCILIATION_REQUIRED", raised.exception.detail["code"])
        job = get_job_run(raised.exception.detail["job_id"])
        self.assertEqual("needs_reconciliation", job["status"])
        self.assertEqual("task_poll", job["current_stage"])

    def test_artifact_write_failure_after_start_retains_target_lock(self):
        from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
        from app.operations.facade import get_operation
        from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore

        client = RecordingStartClient()
        with patch("app.vm_actions.start.write_json_artifact", side_effect=RuntimeError("artifact write failed")):
            with self.assertRaises(HTTPException) as raised:
                self._run_start(client=client, payload={
                    "vm_start_acknowledged": True,
                    "idempotency_key": "idem-artifact-write-failed",
                    "expected_name": "stopped-app",
                    "expected_status": "stopped",
                })

        detail = raised.exception.detail
        operation_id = detail["operation_id"]
        self.assertEqual(503, raised.exception.status_code)
        self.assertEqual("VM_START_OBSERVED_EVIDENCE_PERSISTENCE_UNAVAILABLE", detail["code"])
        self.assertEqual(operation_id, detail["job_id"])
        self.assertEqual("needs_reconciliation", detail["operation_status"])
        self.assertEqual("retry_wait", detail["recovery_status"])
        self.assertEqual("persistence_failed", detail["evidence_status"])
        self.assertFalse(detail["evidence_recorded"])
        self.assertEqual({}, detail["observed_after_artifact"])
        self.assertEqual(
            ["proxmox_start_invoked", "proxmox_task_polled", "proxmox_post_check_observed"],
            detail["side_effects"],
        )
        self.assertEqual("needs_reconciliation", SqlAlchemyOperationStore().get(operation_id).status)
        self.assertEqual("retry_wait", SqlAlchemyRecoveryStore().get(operation_id).status)
        self.assertEqual("observe", get_operation(operation_id)["recovery_available_actions"][0]["action"])

        with self.assertRaises(HTTPException) as blocked:
            self._run_start(client=client, payload={
                "vm_start_acknowledged": True,
                "idempotency_key": "idem-after-artifact-write-failed",
                "expected_name": "stopped-app",
                "expected_status": "stopped",
            })
        self.assertEqual("VM_START_TARGET_LOCK_BUSY", blocked.exception.detail["code"])
        self.assertEqual(1, len([call for call in client.calls if call[0] == "start_vm"]))

    def test_artifact_failure_secondary_recovery_write_still_returns_exact_stable_503(self):
        from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
        from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
        from app.operations.target_lock import get_target_operation_lock

        original_commit = SqlAlchemyRecoveryStore.commit_observation

        def fail_handoff_commit(store, lease, **kwargs):
            if kwargs.get("event_type") == "observed_evidence_persistence_failed":
                raise RuntimeError("secondary recovery handoff unavailable")
            return original_commit(store, lease, **kwargs)

        client = RecordingStartClient()
        with patch.object(SqlAlchemyRecoveryStore, "commit_observation", new=fail_handoff_commit), patch(
            "app.vm_actions.start.write_json_artifact",
            side_effect=RuntimeError("artifact write failed"),
        ):
            with self.assertRaises(HTTPException) as raised:
                self._run_start(
                    client=client,
                    payload={
                        "vm_start_acknowledged": True,
                        "idempotency_key": "idem-artifact-secondary-recovery-failed",
                        "expected_name": "stopped-app",
                        "expected_status": "stopped",
                    },
                )

        detail = raised.exception.detail
        operation_id = detail["operation_id"]
        self.assertEqual(503, raised.exception.status_code)
        self.assertEqual("VM_START_OBSERVED_EVIDENCE_PERSISTENCE_UNAVAILABLE", detail["code"])
        self.assertEqual(operation_id, detail["job_id"])
        self.assertEqual("verifying", detail["operation_status"])
        self.assertEqual("leased", detail["recovery_status"])
        self.assertEqual("persistence_failed", detail["evidence_status"])
        self.assertEqual("verifying", SqlAlchemyOperationStore().get(operation_id).status)
        self.assertEqual("leased", SqlAlchemyRecoveryStore().get(operation_id).status)
        self.assertEqual(
            operation_id,
            get_target_operation_lock("proxmox_vm", "vmid:306")["owner_id"],
        )
        self.assertEqual(1, len([call for call in client.calls if call[0] == "start_vm"]))

    def test_completed_job_projection_failure_retains_durable_lock(self):
        from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
        from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
        from app.vm_actions import start as start_module
        from app.vm_actions.start import build_vm_start_job_id

        client = RecordingStartClient()
        original_record_job_run = start_module.record_job_run

        def fail_completed_projection(**kwargs):
            if kwargs.get("status") == "completed":
                raise RuntimeError("completed job projection failed")
            return original_record_job_run(**kwargs)

        payload = {
            "vm_start_acknowledged": True,
            "idempotency_key": "idem-completed-job-projection-failed",
            "expected_name": "stopped-app",
            "expected_status": "stopped",
        }
        operation_id = build_vm_start_job_id(
            node_id="node-a",
            vmid=306,
            idempotency_key=payload["idempotency_key"],
        )
        with patch("app.vm_actions.start.record_job_run", side_effect=fail_completed_projection):
            with self.assertRaises(HTTPException) as raised:
                self._run_start(client=client, payload=payload)

        detail = raised.exception.detail
        self.assertEqual(503, raised.exception.status_code)
        self.assertEqual(
            "VM_START_COMPATIBILITY_PROJECTION_PERSISTENCE_UNAVAILABLE",
            detail["code"],
        )
        self.assertEqual(operation_id, detail["operation_id"])
        self.assertEqual(operation_id, detail["job_id"])
        self.assertEqual("succeeded", detail["operation_status"])
        self.assertEqual("retry_wait", detail["recovery_status"])
        self.assertEqual("recorded", detail["evidence_status"])
        self.assertTrue(detail["evidence_recorded"])
        self.assertTrue(detail["observed_after_artifact"]["artifact_id"])
        self.assertEqual(
            ["proxmox_start_invoked", "proxmox_task_polled", "proxmox_post_check_observed"],
            detail["side_effects"],
        )

        operation = SqlAlchemyOperationStore().get(operation_id)
        recovery = SqlAlchemyRecoveryStore().get(operation_id)
        self.assertEqual("succeeded", operation.status)
        self.assertEqual("retry_wait", recovery.status)

        # Simulate container-local compatibility file loss. PostgreSQL must
        # still reject a second mutation for the same cluster/VMID.
        with self.assertRaises(HTTPException) as blocked:
            self._run_start(
                client=RecordingStartClient(),
                payload={
                    "vm_start_acknowledged": True,
                    "idempotency_key": "idem-after-completed-job-projection-failed",
                    "expected_name": "stopped-app",
                    "expected_status": "stopped",
                },
            )
        self.assertEqual("VM_START_TARGET_LOCK_BUSY", blocked.exception.detail["code"])
        self.assertEqual(operation_id, blocked.exception.detail["target_operation_lock"]["existing"]["owner_id"])

    def test_operation_persistence_failure_blocks_before_proxmox_dispatch(self):
        client = RecordingStartClient()

        with patch(
            "app.vm_actions.start.SqlAlchemyOperationStore.create",
            side_effect=RuntimeError("operation persistence failed"),
        ):
            with self.assertRaises(RuntimeError):
                self._run_start(
                    client=client,
                    payload={
                        "vm_start_acknowledged": True,
                        "idempotency_key": "idem-operation-persistence-failed",
                        "expected_name": "stopped-app",
                        "expected_status": "stopped",
                    },
                )

        self.assertEqual([], client.calls)


if __name__ == "__main__":
    unittest.main()
