"""Tests for native Proxmox Create VM runner behavior."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
    ):
        self.calls = []
        self.task_exitstatus = task_exitstatus
        self.observed_status = observed_status
        self.missing = missing
        self.cloned_disk_gb = cloned_disk_gb
        self.resize_error = resize_error

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
            "polls": [{"status": "running"}, {"status": "stopped", "exitstatus": self.task_exitstatus}],
        }

    def set_vm_config(self, **kwargs):
        self.calls.append(("set_vm_config", kwargs))
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
        return {"vmid": kwargs["vmid"], "name": "gjallar-vm-job-proxmox-runner", "status": self.observed_status}

    def get_vm_config(self, **kwargs):
        self.calls.append(("get_vm_config", kwargs))
        return {
            "smbios1": "uuid=11111111-2222-3333-4444-555555555555",
            "vmgenid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "net0": "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0",
            "scsi0": f"local-lvm:vm-306-disk-0,size={self.cloned_disk_gb}G",
        }


class ProxmoxRunnerTests(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self._temp_dir.name)
        self.shared_root = self.root / "nfs"
        (self.shared_root / "IaC" / ".git").mkdir(parents=True)
        (self.shared_root / "IaC" / "manifests" / "vms").mkdir(parents=True)
        (self.shared_root / "IaC" / "manifests" / "networks").mkdir(parents=True)
        (self.shared_root / "IaC" / "generated").mkdir(parents=True)
        (self.shared_root / "IaC" / "manifests" / "networks" / "network-profiles.yaml").write_text(
            """apiVersion: gjallar/v1
kind: NetworkPolicySet
networks:
  - network_id: server-net
    display_name: Server network
    nodes:
      - node_id: yoonmanserver2
        bridge_id: vmbr0
        subnet: 192.168.2.0/24
        gateway: 192.168.2.1
        dns: [192.168.2.1]
        static_ip_ranges:
          - start: 192.168.2.142
            end: 192.168.2.150
""",
            encoding="utf-8",
        )
        self._env = patch.dict(
            "os.environ",
            {
                "GJALLAR_SHARED_ROOT": str(self.shared_root),
                "GJALLAR_DEFAULT_SSH_PUBLIC_KEY": TEST_SSH_PUBLIC_KEY,
            },
            clear=False,
        )
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._temp_dir.cleanup()

    def _plan(self, *, job_id="job-proxmox-runner", hardware_overrides=None):
        from app.proxmox.inventory import FakeProxmoxInventoryAdapter
        from app.vm_create.drafts import build_default_vm_draft
        from app.vm_create.planner import build_vm_create_plan
        from app.vm_create.preflight import run_preflight

        draft = build_default_vm_draft(
            operator_id="proxmox-test",
            job_id=job_id,
            target_node_id="yoonmanserver2",
            bridge_id="vmbr0",
            static_ip="192.168.2.142",
            prefix=25,
            gateway="192.168.2.254",
            proposed_vmid=306,
            hardware_overrides=hardware_overrides,
        )
        preflight = run_preflight(draft, inventory_adapter=FakeProxmoxInventoryAdapter())
        self.assertEqual("green", preflight.risk_level)
        return build_vm_create_plan(draft, preflight, run_dir=self.root / job_id / "plan")

    def test_preview_is_non_mutating_and_contains_native_payload(self):
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
        self.assertEqual(TEST_SSH_PUBLIC_KEY.split(" gjallar@test", 1)[0], raw_config["sshkeys"])
        self.assertEqual("[REDACTED]", preview["config"]["sshkeys"])
        self.assertEqual("ip=192.168.2.142/25,gw=192.168.2.254", preview["config"]["ipconfig0"])
        self.assertTrue(Path(preview["artifacts"][0]["path"]).is_file())
        self.assertNotIn(TEST_SSH_PUBLIC_KEY.split()[1], Path(preview["artifacts"][0]["path"]).read_text(encoding="utf-8"))

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
        self.assertEqual(TEST_SSH_PUBLIC_KEY.split(" gjallar@test", 1)[0], set_config_call["config"]["sshkeys"])
        self.assertEqual("UPID:yoonmanserver2:0001:test", result["task"]["upid"])
        self.assertEqual("stopped", result["observed_after"]["status"])
        self.assertEqual("sha256:", result["observed_after"]["fingerprint"]["hash"][:7])
        self.assertEqual(["aa:bb:cc:dd:ee:ff"], result["observed_after"]["fingerprint"]["mac_addresses"])
        self.assertEqual(["local-lvm:vm-306-disk-0"], result["observed_after"]["fingerprint"]["disk_volume_ids"])
        self.assertTrue(Path(result["observed_after_artifact"]["path"]).is_file())
        self.assertNotIn(TEST_SSH_PUBLIC_KEY.split()[1], repr(result))
        self.assertIn("proxmox_post_check_observed", result["side_effects"])

    def test_observed_after_sanitizes_public_key_material_from_proxmox_config(self):
        from app.vm_create.proxmox_runner import run_proxmox_create

        class SshkeysObservingClient(RecordingProxmoxClient):
            def get_vm_config(self, **kwargs):
                config = super().get_vm_config(**kwargs)
                return {**config, "sshkeys": TEST_SSH_PUBLIC_KEY}

        result = run_proxmox_create(self._plan(job_id="job-proxmox-sshkeys-observed"), run_dir=self.root / "observed", client=SshkeysObservingClient())

        self.assertTrue(result["success"])
        self.assertEqual("[REDACTED]", result["observed_after"]["config"]["sshkeys"])
        artifact_text = Path(result["observed_after_artifact"]["path"]).read_text(encoding="utf-8")
        self.assertNotIn(TEST_SSH_PUBLIC_KEY.split()[1], artifact_text)

    def test_requested_disk_larger_than_cloned_scsi0_invokes_resize_before_config(self):
        from app.vm_create.proxmox_runner import run_proxmox_create

        client = RecordingProxmoxClient(cloned_disk_gb=50)
        result = run_proxmox_create(
            self._plan(job_id="job-proxmox-resize", hardware_overrides={"disk_gb": 80}),
            run_dir=self.root / "resize",
            client=client,
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

    def test_task_failure_does_not_configure_or_mark_success(self):
        from app.vm_create.proxmox_runner import run_proxmox_create

        client = RecordingProxmoxClient(task_exitstatus="ERROR")
        result = run_proxmox_create(self._plan(job_id="job-proxmox-task-failure"), run_dir=self.root / "task-fail", client=client)

        self.assertFalse(result["success"])
        self.assertEqual("failed", result["status"])
        self.assertEqual(["clone_vm", "wait_for_task"], [call[0] for call in client.calls])
        self.assertEqual([], result["artifacts"])

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
        self.assertTrue(Path(running["observed_after_artifact"]["path"]).is_file())

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
