"""Tests for native Proxmox Create VM runner behavior."""

from app.db import create_vm_profiles as profile_repository

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

TEST_SSH_PUBLIC_KEY = (
    "ssh-ed25519 "
    "AAAAC3NzaC1lZDI1NTE5AAAAIAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8g "
    "gjallar@test"
)


class RecordingProxmoxClient:
    def __init__(
        self,
        *,
        task_exitstatus="OK",
        observed_status="stopped",
        missing=False,
        cloned_disk_gb=50,
        resize_error=False,
        config_error=False,
    ):
        self.calls = []
        self.task_exitstatus = task_exitstatus
        self.observed_status = observed_status
        self.missing = missing
        self.cloned_disk_gb = cloned_disk_gb
        self.resize_error = resize_error
        self.config_error = config_error

    def clone_vm(self, **kwargs):
        self.calls.append(("clone_vm", kwargs))
        return "UPID:yoonmanserver2:0001:test"

    def wait_for_task(self, **kwargs):
        self.calls.append(("wait_for_task", kwargs))
        return {
            "node": kwargs["node"],
            "upid": kwargs["upid"],
            "status": "stopped",
            "exitstatus": self.task_exitstatus,
            "polls": [
                {"status": "running", "opaque": "opaque-task-poll-value"},
                {"status": "stopped", "exitstatus": self.task_exitstatus},
            ],
        }

    def set_vm_config(self, **kwargs):
        self.calls.append(("set_vm_config", kwargs))
        if self.config_error:
            from app.proxmox.client import ProxmoxMutationError

            raise ProxmoxMutationError(
                "config rejected",
                details={
                    "method": "PUT",
                    "path": "/nodes/yoonmanserver2/qemu/306/config",
                    "status_code": 500,
                    "response_text": "opaque-customer-value",
                    "response_json": {
                        "errors": {
                            "sshkeys": "invalid urlencoded string ssh-ed25519 AAAA",
                            "description": "opaque-customer-description",
                        }
                    },
                },
            )
        return None

    def resize_vm_disk(self, **kwargs):
        self.calls.append(("resize_vm_disk", kwargs))
        if self.resize_error:
            from app.proxmox.client import ProxmoxMutationError

            raise ProxmoxMutationError("resize rejected", details={"disk": kwargs.get("disk")})
        self.cloned_disk_gb = int(kwargs["size"])
        return None

    def get_vm_status(self, **kwargs):
        self.calls.append(("get_vm_status", kwargs))
        if self.missing:
            from app.proxmox.client import ProxmoxMutationError

            raise ProxmoxMutationError("VM not found")
        return {
            "vmid": kwargs["vmid"],
            "name": "gjallar-vm-job-proxmox-runner",
            "status": self.observed_status,
            "opaque_status_extension": "opaque-status-value",
        }

    def get_vm_config(self, **kwargs):
        self.calls.append(("get_vm_config", kwargs))
        return {
            "smbios1": "uuid=11111111-2222-3333-4444-555555555555",
            "vmgenid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "net0": "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0",
            "scsi0": f"local-lvm:vm-306-disk-0,size={self.cloned_disk_gb}G",
            "opaque_config_extension": "opaque-config-value",
        }

    def start_vm(self, **kwargs):
        self.calls.append(("start_vm", kwargs))
        self.observed_status = "running"
        return "UPID:yoonmanserver2:0002:start"

    def get_guest_network_interfaces(self, **kwargs):
        self.calls.append(("get_guest_network_interfaces", kwargs))
        return {
            "opaque_guest_extension": "opaque-guest-value",
            "result": [
                {
                    "name": "ens18",
                    "ip-addresses": [
                        {"ip-address": "127.0.0.1", "ip-address-type": "ipv4"},
                        {"ip-address": "192.168.2.142", "ip-address-type": "ipv4"},
                    ],
                }
            ]
        }

    def exec_guest_command(self, **kwargs):
        self.calls.append(("exec_guest_command", kwargs))
        return 77

    def wait_guest_exec(self, **kwargs):
        self.calls.append(("wait_guest_exec", kwargs))
        return {
            "exited": True,
            "exitcode": 0,
            "out-data": "opaque-cloud-init-output",
            "err-data": "opaque-cloud-init-error-output",
        }


class ProxmoxRunnerTests(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self._temp_dir.name)

    def tearDown(self):
        self._temp_dir.cleanup()

    def _plan(self, *, job_id="job-proxmox-runner", hardware_overrides=None, power_policy=None, ip_mode="static"):
        from app.proxmox.inventory import FakeProxmoxInventoryAdapter
        from app.vm_create.drafts import build_default_vm_draft
        from app.vm_create.planner import calculate_vm_create_plan
        from app.vm_create.plan_persistence import persist_vm_create_plan
        from app.vm_create.preflight import run_preflight

        draft = build_default_vm_draft(
            profiles=profile_repository.get_active_create_vm_profiles_by_id(),
            operator_id="proxmox-test",
            job_id=job_id,
            target_node_id="yoonmanserver2",
            bridge_id="vmbr0",
            static_ip="192.168.2.142" if ip_mode == "static" else None,
            prefix=25 if ip_mode == "static" else None,
            gateway="192.168.2.254" if ip_mode == "static" else None,
            ip_mode=ip_mode,
            proposed_vmid=306,
            hardware_overrides=hardware_overrides,
            power_policy=power_policy,
        )
        preflight = run_preflight(draft, profiles=profile_repository.get_active_create_vm_profiles_by_id(), inventory_adapter=FakeProxmoxInventoryAdapter())
        self.assertEqual("yellow", preflight.risk_level)
        return persist_vm_create_plan(calculate_vm_create_plan(draft, preflight), run_dir=self.root / job_id / "plan")

    def test_preview_is_non_mutating_and_contains_native_payload(self):
        from app.jobs.artifacts import read_artifact_text
        from app.vm_create.proxmox_runner import build_proxmox_create_preview, config_payload_from_plan

        plan = self._plan()
        raw_config = config_payload_from_plan(plan)
        preview = build_proxmox_create_preview(plan, run_dir=self.root / "preview")

        self.assertFalse(preview["proxmox_mutation_enabled"])
        self.assertEqual("/nodes/yoonmanserver2/qemu/9000/clone", preview["clone"]["endpoint"])
        self.assertEqual(1, preview["clone"]["full"])
        self.assertEqual(306, preview["clone"]["newid"])
        self.assertEqual("yoonmanserver2", preview["clone"]["target"])
        self.assertEqual("local-lvm", preview["clone"]["storage"])
        self.assertEqual("enabled=1", preview["config"]["agent"])
        self.assertEqual(0, preview["config"]["onboot"])
        self.assertEqual("yoon", raw_config["ciuser"])
        expected_ssh_key = TEST_SSH_PUBLIC_KEY.split(" gjallar@test", 1)[0]
        self.assertEqual(quote(expected_ssh_key, safe=""), raw_config["sshkeys"])
        self.assertEqual("[REDACTED]", preview["config"]["sshkeys"])
        self.assertEqual("ip=192.168.2.142/25,gw=192.168.2.254", preview["config"]["ipconfig0"])
        self.assertTrue(preview["artifacts"][0]["path"].startswith("db://job-artifacts/"))
        self.assertNotIn(TEST_SSH_PUBLIC_KEY.split()[1], read_artifact_text(preview["artifacts"][0]))

    def test_create_success_requires_ok_task_stopped_post_check_and_observed_after(self):
        from app.vm_create.proxmox_runner import run_proxmox_create

        client = RecordingProxmoxClient()
        result = run_proxmox_create(self._plan(), run_dir=self.root / "run", client=client)

        self.assertTrue(result["success"])
        self.assertEqual("completed", result["status"])
        self.assertEqual(
            [
                "clone_vm",
                "wait_for_task",
                "get_vm_config",
                "set_vm_config",
                "get_vm_status",
                "get_vm_config",
            ],
            [call[0] for call in client.calls],
        )
        self.assertEqual("not_needed", result["resize"]["action"])
        self.assertEqual("[REDACTED]", result["config"]["sshkeys"])
        set_config_call = next(call for call in client.calls if call[0] == "set_vm_config")[1]
        expected_ssh_key = TEST_SSH_PUBLIC_KEY.split(" gjallar@test", 1)[0]
        self.assertEqual(quote(expected_ssh_key, safe=""), set_config_call["config"]["sshkeys"])
        self.assertEqual("UPID:yoonmanserver2:0001:test", result["task"]["upid"])
        self.assertEqual("stopped", result["observed_after"]["status"])
        self.assertEqual("sha256:", result["observed_after"]["fingerprint"]["hash"][:7])
        self.assertEqual(["aa:bb:cc:dd:ee:ff"], result["observed_after"]["fingerprint"]["mac_addresses"])
        self.assertEqual(["local-lvm:vm-306-disk-0"], result["observed_after"]["fingerprint"]["disk_volume_ids"])
        self.assertTrue(result["observed_after_artifact"]["path"].startswith("db://job-artifacts/"))
        self.assertNotIn(TEST_SSH_PUBLIC_KEY.split()[1], repr(result))
        serialized = json.dumps(result, sort_keys=True)
        self.assertNotIn("polls", serialized)
        self.assertNotIn("opaque-task-poll-value", serialized)
        self.assertNotIn("opaque-status-value", serialized)
        self.assertNotIn("opaque-config-value", serialized)
        self.assertNotIn("opaque_status_extension", serialized)
        self.assertNotIn("opaque_config_extension", serialized)
        self.assertNotIn("config", result["observed_after"])
        self.assertIn("proxmox_post_check_observed", result["side_effects"])

    def test_unknown_power_status_is_bounded_and_never_authorizes_create_start(self):
        from app.vm_create.proxmox_runner import run_proxmox_create

        status_marker = "opaque-create-power-token"
        name_marker = "opaque create vm name token"

        class OpaqueSemanticClient(RecordingProxmoxClient):
            def get_vm_status(self, **kwargs):
                self.calls.append(("get_vm_status", kwargs))
                return {
                    "vmid": kwargs["vmid"],
                    "name": name_marker,
                    "status": status_marker,
                }

        client = OpaqueSemanticClient()
        checkpoints = []
        result = run_proxmox_create(
            self._plan(
                job_id="job-proxmox-create-unknown-power",
                power_policy="boot_and_verify",
            ),
            run_dir=self.root / "unknown-power",
            client=client,
            checkpoint=lambda phase, evidence: checkpoints.append((phase, evidence)),
        )

        self.assertFalse(result["success"])
        self.assertEqual("needs_reconciliation", result["status"])
        self.assertEqual("unknown", result["observed_after"]["status"])
        self.assertEqual(
            "gjallar-vm-job-proxmox-create-unknown-power",
            result["observed_after"]["vm_name"],
        )
        self.assertNotIn("start_vm", [call[0] for call in client.calls])
        serialized = json.dumps({"result": result, "checkpoints": checkpoints}, sort_keys=True)
        self.assertNotIn(status_marker, serialized)
        self.assertNotIn(name_marker, serialized)

    def test_create_records_durable_mutation_boundaries_and_upid_before_poll(self):
        from app.vm_create.proxmox_runner import run_proxmox_create

        checkpoints = []
        result = run_proxmox_create(
            self._plan(job_id="job-proxmox-create-checkpoints"),
            run_dir=self.root / "checkpoints",
            client=RecordingProxmoxClient(),
            checkpoint=lambda phase, evidence: checkpoints.append((phase, evidence)),
        )

        self.assertTrue(result["success"])
        self.assertEqual(
            [
                "clone_pending",
                "clone_dispatched",
                "clone_task_observed",
                "config_pending",
                "config_completed",
                "post_check_observed",
                "readiness_observed",
                "observed_after_artifact_recorded",
            ],
            [phase for phase, _ in checkpoints],
        )
        self.assertEqual(
            "UPID:yoonmanserver2:0001:test",
            dict(checkpoints[1][1])["clone_upid"],
        )
        self.assertTrue(dict(checkpoints[-1][1])["observed_after_artifact"]["artifact_id"])

    def test_checkpoint_failure_before_clone_prevents_every_external_mutation(self):
        from app.vm_create.proxmox_runner import run_proxmox_create

        client = RecordingProxmoxClient()

        def fail_clone_pending(phase, evidence):
            if phase == "clone_pending":
                raise RuntimeError("recovery checkpoint unavailable")

        with self.assertRaisesRegex(RuntimeError, "recovery checkpoint unavailable"):
            run_proxmox_create(
                self._plan(job_id="job-proxmox-checkpoint-before-clone"),
                run_dir=self.root / "checkpoint-before-clone",
                client=client,
                checkpoint=fail_clone_pending,
            )

        self.assertEqual([], client.calls)

    def test_checkpoint_failure_after_clone_upid_blocks_poll_and_followup_mutations(self):
        from app.vm_create.proxmox_runner import run_proxmox_create

        client = RecordingProxmoxClient()
        checkpoints = []

        def fail_after_upid(phase, evidence):
            checkpoints.append((phase, evidence))
            if phase == "clone_dispatched":
                raise RuntimeError("UPID checkpoint unavailable")

        with self.assertRaisesRegex(RuntimeError, "UPID checkpoint unavailable"):
            run_proxmox_create(
                self._plan(job_id="job-proxmox-checkpoint-after-upid"),
                run_dir=self.root / "checkpoint-after-upid",
                client=client,
                checkpoint=fail_after_upid,
            )

        self.assertEqual(["clone_pending", "clone_dispatched"], [item[0] for item in checkpoints])
        self.assertEqual(["clone_vm"], [call[0] for call in client.calls])
        self.assertEqual(
            "UPID:yoonmanserver2:0001:test",
            dict(checkpoints[-1][1])["clone_upid"],
        )

    def test_current_observed_after_artifact_failure_surfaces_after_external_effects(self):
        from app.vm_create.proxmox_runner import run_proxmox_create

        plan = self._plan(job_id="job-proxmox-observed-after-artifact-failure")
        client = RecordingProxmoxClient()
        checkpoints = []
        with patch(
            "app.vm_create.proxmox_runner.write_json_artifact",
            side_effect=RuntimeError("observed-after artifact store unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "observed-after artifact store unavailable"):
                run_proxmox_create(
                    plan,
                    run_dir=self.root / "observed-after-artifact-failure",
                    client=client,
                    checkpoint=lambda phase, evidence: checkpoints.append((phase, evidence)),
                )

        self.assertEqual(
            [
                "clone_vm",
                "wait_for_task",
                "get_vm_config",
                "set_vm_config",
                "get_vm_status",
                "get_vm_config",
            ],
            [call[0] for call in client.calls],
        )
        self.assertEqual("readiness_observed", checkpoints[-1][0])
        self.assertTrue(checkpoints[-1][1]["result_success"])
        self.assertNotIn("observed_after_artifact_recorded", [item[0] for item in checkpoints])

    def test_boot_and_verify_policy_starts_vm_and_records_guest_ip_cloud_init(self):
        from app.vm_create.proxmox_runner import run_proxmox_create
        from app.vm_create.application import _record_create_progress, _record_plan_job
        from app.jobs.runs import get_job_run_strict

        client = RecordingProxmoxClient()
        checkpoints = []
        plan = self._plan(job_id="job-proxmox-boot-verify", power_policy="boot_and_verify")
        _record_plan_job(plan, status="running", stage="create", step_status="running",
                         message="생성 중", details={"approval": {"approved": True}})
        progress_calls = []

        def progress(message):
            _record_create_progress(plan, message)
            job = get_job_run_strict(plan.job_id)
            self.assertEqual("running", job["status"])
            self.assertEqual(message, job["message"])
            self.assertEqual({"approved": True}, job["details"]["approval"])
            self.assertLess(job["progress_percent"], 100)
            progress_calls.append((message, [call[0] for call in client.calls]))

        result = run_proxmox_create(
            plan,
            run_dir=self.root / "boot-verify",
            client=client,
            checkpoint=lambda phase, evidence: checkpoints.append((phase, evidence)),
            progress=progress,
        )

        self.assertEqual(3, len(progress_calls))
        self.assertNotIn("start_vm", progress_calls[0][1])
        self.assertNotIn("get_guest_network_interfaces", progress_calls[1][1])
        self.assertIn("cloud-init", progress_calls[2][0])
        self.assertNotIn("exec_guest_command", progress_calls[2][1])
        self.assertTrue(result["success"])
        self.assertEqual("completed", result["status"])
        self.assertEqual("running", result["observed_after"]["status"])
        self.assertEqual("boot_and_verify", result["observed_after"]["power_policy"])
        self.assertEqual(["192.168.2.142"], result["observed_after"]["ip_addresses"])
        self.assertEqual("192.168.2.142", result["observed_after"]["primary_ip"])
        self.assertTrue(result["observed_after"]["guest_agent"]["available"])
        self.assertTrue(result["observed_after"]["cloud_init"]["success"])
        self.assertTrue(result["observed_after"]["boot_verification"]["success"])
        self.assertEqual("UPID:yoonmanserver2:0002:start", result["start_task"]["upid"])
        self.assertEqual(
            [
                "clone_vm",
                "wait_for_task",
                "get_vm_config",
                "set_vm_config",
                "get_vm_status",
                "get_vm_config",
                "start_vm",
                "wait_for_task",
                "get_vm_status",
                "get_vm_config",
                "get_guest_network_interfaces",
                "exec_guest_command",
                "wait_guest_exec",
            ],
            [call[0] for call in client.calls],
        )
        self.assertIn("proxmox_start_invoked", result["side_effects"])
        self.assertIn("proxmox_guest_agent_observed", result["side_effects"])
        self.assertIn("proxmox_cloud_init_status_checked", result["side_effects"])
        serialized = json.dumps(result, sort_keys=True)
        self.assertNotIn("opaque-guest-value", serialized)
        self.assertNotIn("opaque-cloud-init-output", serialized)
        self.assertNotIn("opaque-cloud-init-error-output", serialized)
        phases = [item[0] for item in checkpoints]
        self.assertLess(phases.index("start_pending"), phases.index("start_dispatched"))
        self.assertLess(phases.index("start_dispatched"), phases.index("start_task_observed"))
        self.assertEqual("UPID:yoonmanserver2:0002:start", checkpoints[phases.index("start_dispatched")][1]["start_upid"])

    def test_cloud_init_status_retries_transient_guest_exec_pid_error(self):
        from app.proxmox.client import ProxmoxMutationError
        from app.vm_create.proxmox_runner import _check_cloud_init_status

        class FlakyCloudInitClient(RecordingProxmoxClient):
            def __init__(self):
                super().__init__()
                self.remaining_wait_errors = 1

            def wait_guest_exec(self, **kwargs):
                self.calls.append(("wait_guest_exec", kwargs))
                if self.remaining_wait_errors:
                    self.remaining_wait_errors -= 1
                    raise ProxmoxMutationError(
                        "Proxmox API HTTP 500: GET /nodes/yoonmanserver/qemu/135/agent/exec-status?pid=1406",
                        details={"response_json": {"message": "Agent error: Invalid parameter 'pid'"}},
                    )
                return {"exited": True, "exitcode": 0, "out-data": "status: done\n"}

        client = FlakyCloudInitClient()
        result = _check_cloud_init_status(
            client,
            plan=self._plan(job_id="job-proxmox-boot-verify", power_policy="boot_and_verify"),
            sleep=lambda _: None,
        )

        self.assertTrue(result["success"])
        self.assertEqual("done", result["status"])
        self.assertEqual(2, result["attempts"])
        self.assertEqual(1, len(result["previous_errors"]))
        self.assertEqual(
            [
                "exec_guest_command",
                "wait_guest_exec",
                "exec_guest_command",
                "wait_guest_exec",
            ],
            [call[0] for call in client.calls],
        )

    def test_observed_after_excludes_raw_proxmox_config(self):
        from app.jobs.artifacts import read_artifact_text
        from app.vm_create.proxmox_runner import run_proxmox_create

        class SshkeysObservingClient(RecordingProxmoxClient):
            def get_vm_config(self, **kwargs):
                config = super().get_vm_config(**kwargs)
                return {**config, "sshkeys": TEST_SSH_PUBLIC_KEY}

        result = run_proxmox_create(self._plan(job_id="job-proxmox-sshkeys-observed"), run_dir=self.root / "observed", client=SshkeysObservingClient())

        self.assertTrue(result["success"])
        self.assertNotIn("config", result["observed_after"])
        artifact_text = read_artifact_text(result["observed_after_artifact"])
        self.assertNotIn(TEST_SSH_PUBLIC_KEY.split()[1], artifact_text)
        artifact_payload = json.loads(artifact_text)
        self.assertNotIn("config", artifact_payload)
        self.assertNotIn("sshkeys", artifact_payload["status_current"])

    def test_requested_disk_larger_than_cloned_scsi0_invokes_resize_before_config(self):
        from app.vm_create.proxmox_runner import run_proxmox_create

        client = RecordingProxmoxClient(cloned_disk_gb=50)
        checkpoints = []
        result = run_proxmox_create(
            self._plan(job_id="job-proxmox-resize", hardware_overrides={"disk_gb": 80}),
            run_dir=self.root / "resize",
            client=client,
            checkpoint=lambda phase, evidence: checkpoints.append((phase, evidence)),
        )

        self.assertTrue(result["success"])
        self.assertEqual("resized", result["resize"]["action"])
        self.assertEqual(50, result["resize"]["current_disk_gb"])
        self.assertEqual("scsi0", result["resize"]["disk"])
        self.assertEqual("80G", result["resize"]["size"])
        self.assertEqual(
            [
                "clone_vm",
                "wait_for_task",
                "get_vm_config",
                "resize_vm_disk",
                "set_vm_config",
                "get_vm_status",
                "get_vm_config",
            ],
            [call[0] for call in client.calls],
        )
        resize_call = client.calls[3][1]
        self.assertEqual({"node": "yoonmanserver2", "vmid": 306, "disk": "scsi0", "size": 80}, resize_call)
        self.assertIn("proxmox_disk_resize_succeeded", result["side_effects"])
        phases = [item[0] for item in checkpoints]
        self.assertLess(phases.index("resize_pending"), phases.index("resize_completed"))
        self.assertLess(phases.index("resize_completed"), phases.index("config_pending"))

    def test_requested_disk_equal_to_cloned_scsi0_skips_resize(self):
        from app.vm_create.proxmox_runner import run_proxmox_create

        client = RecordingProxmoxClient(cloned_disk_gb=50)
        result = run_proxmox_create(
            self._plan(job_id="job-proxmox-no-resize", hardware_overrides={"disk_gb": 50}),
            run_dir=self.root / "no-resize",
            client=client,
        )

        self.assertTrue(result["success"])
        self.assertEqual("not_needed", result["resize"]["action"])
        self.assertEqual("requested_not_larger_than_current", result["resize"]["reason"])
        self.assertNotIn("resize_vm_disk", [call[0] for call in client.calls])

    def test_resize_failure_needs_reconciliation_before_config_or_observed_after(self):
        from app.vm_create.proxmox_runner import run_proxmox_create

        client = RecordingProxmoxClient(cloned_disk_gb=50, resize_error=True)
        result = run_proxmox_create(
            self._plan(job_id="job-proxmox-resize-failure", hardware_overrides={"disk_gb": 80}),
            run_dir=self.root / "resize-failure",
            client=client,
        )

        self.assertFalse(result["success"])
        self.assertEqual("needs_reconciliation", result["status"])
        self.assertEqual("failed", result["resize"]["action"])
        self.assertEqual(
            ["clone_vm", "wait_for_task", "get_vm_config", "resize_vm_disk"],
            [call[0] for call in client.calls],
        )
        self.assertEqual([], result["artifacts"])
        self.assertNotIn("observed_after", result)
        self.assertIn("proxmox_disk_resize_failed", result["side_effects"])

    def test_config_failure_keeps_only_allowlisted_proxmox_error_evidence(self):
        from app.vm_create.proxmox_runner import run_proxmox_create

        client = RecordingProxmoxClient(config_error=True)
        checkpoints = []
        result = run_proxmox_create(
            self._plan(job_id="job-proxmox-config-failure"),
            run_dir=self.root / "config-failure",
            client=client,
            checkpoint=lambda phase, evidence: checkpoints.append((phase, evidence)),
        )

        self.assertFalse(result["success"])
        self.assertEqual("needs_reconciliation", result["status"])
        self.assertEqual(
            {
                "status_code": 500,
                "method": "PUT",
                "invalid_fields": ["description", "sshkeys"],
            },
            result["details"],
        )
        serialized = json.dumps({"result": result, "checkpoints": checkpoints}, sort_keys=True)
        self.assertNotIn("opaque-customer-value", serialized)
        self.assertNotIn("opaque-customer-description", serialized)
        self.assertNotIn("response_text", serialized)
        self.assertNotIn("response_json", serialized)
        self.assertNotIn("/nodes/yoonmanserver2/qemu/306/config", serialized)
        self.assertNotIn("observed_after", result)
        self.assertIn("set_vm_config", [call[0] for call in client.calls])

    def test_task_failure_does_not_configure_or_mark_success(self):
        from app.vm_create.proxmox_runner import run_proxmox_create

        client = RecordingProxmoxClient(task_exitstatus="ERROR")
        result = run_proxmox_create(self._plan(job_id="job-proxmox-task-failure"), run_dir=self.root / "task-fail", client=client)

        self.assertFalse(result["success"])
        self.assertEqual("failed", result["status"])
        self.assertEqual(["clone_vm", "wait_for_task"], [call[0] for call in client.calls])
        self.assertEqual([], result["artifacts"])

    def test_clone_without_upid_requires_reconciliation_because_clone_may_have_started(self):
        from app.proxmox.client import ProxmoxMutationError
        from app.vm_create.proxmox_runner import run_proxmox_create

        class MissingUpidCloneClient(RecordingProxmoxClient):
            def clone_vm(self, **kwargs):
                self.calls.append(("clone_vm", kwargs))
                raise ProxmoxMutationError("Proxmox clone did not return a UPID", details={"payload": kwargs})

        client = MissingUpidCloneClient()
        result = run_proxmox_create(
            self._plan(job_id="job-proxmox-missing-upid"),
            run_dir=self.root / "missing-upid",
            client=client,
        )

        self.assertFalse(result["success"])
        self.assertEqual("needs_reconciliation", result["status"])
        self.assertEqual([], result["artifacts"])
        self.assertEqual(["clone_vm"], [call[0] for call in client.calls])
        self.assertIn("proxmox_clone_state_unknown", result["side_effects"])
        self.assertEqual({}, result["details"])
        self.assertEqual("unknown", result["task"]["status"])

    def test_invalid_clone_upid_is_not_persisted_or_used_for_task_observation(self):
        from app.vm_create.proxmox_runner import run_proxmox_create

        opaque_locator = "opaque-secret?token=do-not-store"

        class InvalidCloneUpidClient(RecordingProxmoxClient):
            def clone_vm(self, **kwargs):
                self.calls.append(("clone_vm", kwargs))
                return opaque_locator

        client = InvalidCloneUpidClient()
        checkpoints = []
        result = run_proxmox_create(
            self._plan(job_id="job-proxmox-invalid-clone-upid"),
            run_dir=self.root / "invalid-clone-upid",
            client=client,
            checkpoint=lambda phase, evidence: checkpoints.append((phase, evidence)),
        )

        self.assertFalse(result["success"])
        self.assertEqual("needs_reconciliation", result["status"])
        self.assertEqual(["clone_vm"], [call[0] for call in client.calls])
        self.assertEqual("", result["task"]["upid"])
        self.assertIn("clone_locator_invalid", [phase for phase, _ in checkpoints])
        self.assertNotIn(opaque_locator, json.dumps({"result": result, "checkpoints": checkpoints}, sort_keys=True))

    def test_invalid_start_upid_is_not_persisted_or_used_for_task_observation(self):
        from app.vm_create.proxmox_runner import run_proxmox_create

        opaque_locator = "opaque-secret?token=do-not-store"

        class InvalidStartUpidClient(RecordingProxmoxClient):
            def start_vm(self, **kwargs):
                self.calls.append(("start_vm", kwargs))
                self.observed_status = "running"
                return opaque_locator

        client = InvalidStartUpidClient()
        checkpoints = []
        result = run_proxmox_create(
            self._plan(
                job_id="job-proxmox-invalid-start-upid",
                power_policy="boot_and_verify",
            ),
            run_dir=self.root / "invalid-start-upid",
            client=client,
            checkpoint=lambda phase, evidence: checkpoints.append((phase, evidence)),
        )

        self.assertFalse(result["success"])
        self.assertEqual("needs_reconciliation", result["status"])
        self.assertEqual("", result["start_task"]["upid"])
        call_names = [call[0] for call in client.calls]
        self.assertEqual(1, call_names.count("wait_for_task"))
        self.assertEqual("start_vm", call_names[-1])
        self.assertIn("start_locator_invalid", [phase for phase, _ in checkpoints])
        self.assertNotIn(opaque_locator, json.dumps({"result": result, "checkpoints": checkpoints}, sort_keys=True))

    def test_clone_http_4xx_rejection_can_fail_without_reconciliation(self):
        from app.proxmox.client import ProxmoxMutationError
        from app.vm_create.proxmox_runner import run_proxmox_create

        class RejectedCloneClient(RecordingProxmoxClient):
            def clone_vm(self, **kwargs):
                self.calls.append(("clone_vm", kwargs))
                raise ProxmoxMutationError(
                    "Proxmox API HTTP 400: POST /nodes/yoonmanserver2/qemu/9000/clone",
                    details={"status_code": 400, "response_json": {"errors": {"newid": "already exists"}}},
                )

        result = run_proxmox_create(
            self._plan(job_id="job-proxmox-clone-4xx-rejected"),
            run_dir=self.root / "clone-4xx-rejected",
            client=RejectedCloneClient(),
        )

        self.assertFalse(result["success"])
        self.assertEqual("failed", result["status"])
        self.assertIn("proxmox_clone_rejected", result["side_effects"])
        self.assertEqual([], result["artifacts"])

    def test_clone_http_408_timeout_requires_reconciliation(self):
        from app.proxmox.client import ProxmoxMutationError
        from app.vm_create.proxmox_runner import run_proxmox_create

        class TimeoutCloneClient(RecordingProxmoxClient):
            def clone_vm(self, **kwargs):
                self.calls.append(("clone_vm", kwargs))
                raise ProxmoxMutationError(
                    "Proxmox API HTTP 408: POST /nodes/yoonmanserver2/qemu/9000/clone",
                    details={"status_code": 408, "reason": "Request Timeout"},
                )

        result = run_proxmox_create(
            self._plan(job_id="job-proxmox-clone-408-timeout"),
            run_dir=self.root / "clone-408-timeout",
            client=TimeoutCloneClient(),
        )

        self.assertFalse(result["success"])
        self.assertEqual("needs_reconciliation", result["status"])
        self.assertIn("proxmox_clone_state_unknown", result["side_effects"])
        self.assertNotIn("proxmox_clone_rejected", result["side_effects"])
        self.assertEqual(408, result["details"]["status_code"])

    def test_task_poll_exception_after_upid_requires_reconciliation_with_upid_evidence(self):
        from app.proxmox.client import ProxmoxMutationError
        from app.vm_create.proxmox_runner import run_proxmox_create

        class AmbiguousTaskPollClient(RecordingProxmoxClient):
            def wait_for_task(self, **kwargs):
                self.calls.append(("wait_for_task", kwargs))
                raise ProxmoxMutationError(
                    "Proxmox API request failed: GET /nodes/yoonmanserver2/tasks/UPID:yoonmanserver2:0001:test/status",
                    details={"node": kwargs["node"], "upid": kwargs["upid"], "error": "connection reset"},
                )

        client = AmbiguousTaskPollClient()
        result = run_proxmox_create(
            self._plan(job_id="job-proxmox-task-poll-unknown"),
            run_dir=self.root / "task-poll-unknown",
            client=client,
        )

        self.assertFalse(result["success"])
        self.assertEqual("needs_reconciliation", result["status"])
        self.assertEqual(["clone_vm", "wait_for_task"], [call[0] for call in client.calls])
        self.assertEqual("UPID:yoonmanserver2:0001:test", result["task"]["upid"])
        self.assertEqual("unknown", result["task"]["status"])
        self.assertEqual({}, result["details"])
        self.assertIn("proxmox_clone_invoked", result["side_effects"])
        self.assertIn("proxmox_task_poll_state_unknown", result["side_effects"])

    def test_powered_on_or_missing_post_check_needs_reconciliation(self):
        from app.vm_create.proxmox_runner import run_proxmox_create

        running_client = RecordingProxmoxClient(observed_status="running")
        running = run_proxmox_create(
            self._plan(job_id="job-proxmox-running"),
            run_dir=self.root / "running",
            client=running_client,
        )
        self.assertFalse(running["success"])
        self.assertEqual("needs_reconciliation", running["status"])
        self.assertEqual("running", running["observed_after"]["status"])
        self.assertTrue(running["observed_after_artifact"]["path"].startswith("db://job-artifacts/"))

        missing_client = RecordingProxmoxClient(missing=True)
        missing = run_proxmox_create(
            self._plan(job_id="job-proxmox-missing"),
            run_dir=self.root / "missing",
            client=missing_client,
        )
        self.assertFalse(missing["success"])
        self.assertEqual("needs_reconciliation", missing["status"])
        self.assertFalse(missing["observed_after"]["exists"])


if __name__ == "__main__":
    unittest.main()


def test_cloud_init_wait_passes_foreground_heartbeat():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from app.vm_create.proxmox_runner import _check_cloud_init_status
    client = Mock()
    client.exec_guest_command.return_value = 77
    client.wait_guest_exec.return_value = {'exitcode': 0}
    heartbeat = Mock()
    result = _check_cloud_init_status(client, plan=SimpleNamespace(target_node_id='node', vmid=10001), heartbeat=heartbeat)
    assert result['success'] is True
    client.wait_guest_exec.assert_called_once_with(node='node', vmid=10001, pid=77, heartbeat=heartbeat)
