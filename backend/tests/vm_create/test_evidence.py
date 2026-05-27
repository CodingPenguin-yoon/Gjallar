"""Tests for the read-only Create VM evidence helper."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

from app.db.models import JobArtifactRecord, JobRunRecord, VmCreateRequestRecord, VmInstanceRecord
from app.db.session import session_scope
from app.vm_create.evidence import build_create_vm_evidence_summary

NOW = "2026-05-27T00:00:00Z"
TEST_SSH_PUBLIC_KEY = (
    "ssh-ed25519 "
    "AAAAC3NzaC1lZDI1NTE5AAAAIAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8g "
    "gjallar@test"
)


def _checksum(seed: str) -> str:
    return "sha256:" + seed[:1].lower() * 64


def _observed_after(
    *,
    status: str = "stopped",
    power_policy: str = "stopped",
    primary_ip: str = "",
    start_task: dict[str, Any] | None = None,
    include_raw: bool = False,
) -> dict[str, Any]:
    ip_addresses = [primary_ip] if primary_ip else []
    payload: dict[str, Any] = {
        "observed_at": NOW,
        "job_id": "job-evidence",
        "manifest_id": "manifest-evidence",
        "vmid": 306,
        "vm_name": "gjallar-evidence-vm",
        "target_node_id": "node-a",
        "exists": True,
        "status": status,
        "post_check_status": "completed",
        "message": "VM evidence recorded",
        "power_policy": power_policy,
        "guest_agent": {
            "available": bool(primary_ip),
            "ip_addresses": ip_addresses,
            "primary_ip": primary_ip,
            "attempts": 2 if primary_ip else None,
        },
        "ip_addresses": ip_addresses,
        "primary_ip": primary_ip,
        "cloud_init": {
            "checked": power_policy == "boot_and_verify",
            "success": power_policy == "boot_and_verify",
            "status": "done" if power_policy == "boot_and_verify" else "not_requested",
            "exitcode": 0 if power_policy == "boot_and_verify" else None,
            "attempts": 1 if power_policy == "boot_and_verify" else None,
        },
        "boot_verification": {
            "success": power_policy == "boot_and_verify",
            "checks": {
                "running": status == "running",
                "guest_agent_available": bool(primary_ip),
                "ip_observed": bool(primary_ip),
                "cloud_init_completed": power_policy == "boot_and_verify",
            },
        },
        "start_task": start_task or {},
        "fingerprint": {
            "hash": _checksum("f"),
            "mac_addresses": ["aa:bb:cc:dd:ee:ff"],
            "disk_volume_ids": ["local-lvm:vm-306-disk-0"],
        },
    }
    if include_raw:
        payload.update(
            {
                "status_current": {"raw_status_current_marker": "RAW_STATUS_CURRENT_MARKER"},
                "config": {"raw_config_marker": "RAW_CONFIG_MARKER", "sshkeys": TEST_SSH_PUBLIC_KEY},
            }
        )
        payload["guest_agent"]["last_payload"] = {"raw_guest_agent_payload_marker": "RAW_GUEST_AGENT_PAYLOAD_MARKER"}
        payload["cloud_init"]["output"] = "RAW_CLOUD_INIT_STDOUT_MARKER"
        payload["cloud_init"]["error_output"] = "RAW_CLOUD_INIT_STDERR_MARKER"
    return payload


def _create_result(
    observed_after: dict[str, Any],
    *,
    start_task: dict[str, Any] | None = None,
    include_raw: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "success": True,
        "status": "completed",
        "message": "VM evidence recorded",
        "task": {"upid": "UPID:node-a:0001:clone", "exitstatus": "OK"},
        "resize": {"action": "not_needed", "success": True, "reason": "requested_not_larger_than_current"},
        "start_task": start_task or {},
        "observed_after": observed_after,
        "side_effects": ["proxmox_clone_invoked", "proxmox_post_check_observed"],
    }
    if include_raw:
        result.update(
            {
                "raw_result_marker": "RAW_RESULT_MARKER",
                "config": {"sshkeys": TEST_SSH_PUBLIC_KEY, "token": "RESULT_TOKEN_MARKER"},
                "status_current": {"raw_result_status_current_marker": "RAW_RESULT_STATUS_CURRENT_MARKER"},
                "endpoint": "/nodes/raw-node/qemu/306/config",
            }
        )
        result["resize"]["selected_disk"] = {"raw_config": "RAW_RESIZE_RAW_CONFIG_MARKER"}
        result["side_effects"].append("token=RESULT_TOKEN_MARKER")
    return result


def _insert_job(job_id: str, *, status: str = "completed", risk_level: str = "green") -> None:
    with session_scope() as session:
        session.add(
            JobRunRecord(
                job_id=job_id,
                job_type="vm_create",
                status=status,
                target_id="node-a:306",
                risk_level=risk_level,
                started_at=NOW,
                finished_at=NOW if status in {"completed", "failed", "blocked"} else None,
                current_stage="create" if status == "completed" else "preflight",
                message="Proxmox native VM 생성이 완료되었습니다." if status == "completed" else "Preflight blocked",
                progress_percent=100 if status == "completed" else 20,
                steps=[
                    {"id": "draft", "label": "요청 입력", "status": "completed", "message": "", "updated_at": NOW},
                    {
                        "id": "preflight",
                        "label": "사전 검토",
                        "status": "blocked" if status == "blocked" else "completed",
                        "message": "Preflight blocked" if status == "blocked" else "",
                        "updated_at": NOW,
                    },
                ],
                risks=[{"level": risk_level, "code": "create_vm_risk_code", "message": "risk"}],
                details={"raw_job_details_marker": "RAW_JOB_DETAILS_MARKER"},
                artifact_count=1,
                risk_count=1,
                updated_at=NOW,
            )
        )


def _insert_artifact(job_id: str, artifact_type: str, payload: dict[str, Any], *, suffix: str = "a") -> None:
    content = json.dumps(payload, sort_keys=True)
    with session_scope() as session:
        session.add(
            JobArtifactRecord(
                artifact_id=f"artifact_{artifact_type}_{job_id}_{suffix}",
                job_id=job_id,
                type=artifact_type,
                path=f"db://job-artifacts/artifact_{artifact_type}_{job_id}_{suffix}",
                checksum=_checksum(suffix),
                content_type="application/json",
                content_text=content,
                size_bytes=len(content.encode("utf-8")),
                storage_backend="db",
                created_at=NOW,
                updated_at=NOW,
            )
        )


def _insert_request_and_instance(
    job_id: str,
    observed_after: dict[str, Any],
    *,
    result: dict[str, Any] | None = None,
    include_raw: bool = False,
) -> None:
    with session_scope() as session:
        session.add(
            VmCreateRequestRecord(
                request_id=job_id,
                draft_id=f"draft-{job_id}",
                manifest_id=f"manifest-{job_id}",
                operator_id="payload-operator-id",
                status="completed",
                target_node_id="node-a",
                vmid=306,
                vm_name="gjallar-evidence-vm",
                profile_id="general-vm",
                template_id="template-9000",
                storage_id="local-lvm",
                actor_user_id="user-123",
                actor_username="operator-a",
                actor_role="operator",
                request_payload={
                    "operator_id": "payload-operator-id",
                    "raw_request_marker": "RAW_REQUEST_PAYLOAD_MARKER",
                    "access": {"ssh_public_key": TEST_SSH_PUBLIC_KEY},
                },
                approval={
                    "raw_approval_marker": "RAW_APPROVAL_MARKER",
                    "session_token": "APPROVAL_TOKEN_MARKER",
                },
                result=result or _create_result(observed_after, include_raw=include_raw),
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            VmInstanceRecord(
                vm_instance_id="node-a:306",
                node_id="node-a",
                vmid=306,
                name="gjallar-evidence-vm",
                status=str(observed_after.get("status") or "stopped"),
                profile_id="general-vm",
                template_id="template-9000",
                storage_id="local-lvm",
                cpu=2,
                memory_mb=4096,
                disk_gb=50,
                network={"raw_network_marker": "RAW_NETWORK_MARKER"},
                access={"ssh_public_key": TEST_SSH_PUBLIC_KEY},
                observed_after=observed_after,
                create_job_id=job_id,
                created_at=NOW,
                updated_at=NOW,
            )
        )


def _insert_completed_create(
    job_id: str,
    *,
    observed_after: dict[str, Any],
    result: dict[str, Any] | None = None,
    include_raw: bool = False,
) -> None:
    _insert_job(job_id)
    _insert_artifact(job_id, "observed_after", observed_after)
    _insert_artifact(
        job_id,
        "proxmox_create_result",
        {"raw_artifact_payload_marker": "RAW_ARTIFACT_PAYLOAD_MARKER", "ssh_public_key": TEST_SSH_PUBLIC_KEY},
        suffix="b",
    )
    _insert_request_and_instance(job_id, observed_after, result=result, include_raw=include_raw)


def _snapshot(job_id: str) -> dict[str, Any]:
    with session_scope() as session:
        job = session.get(JobRunRecord, job_id)
        request = session.get(VmCreateRequestRecord, job_id)
        instance = session.get(VmInstanceRecord, "node-a:306")
        artifact = session.get(JobArtifactRecord, f"artifact_observed_after_{job_id}_a")
        return {
            "counts": {
                "jobs": session.query(JobRunRecord).count(),
                "artifacts": session.query(JobArtifactRecord).count(),
                "requests": session.query(VmCreateRequestRecord).count(),
                "instances": session.query(VmInstanceRecord).count(),
            },
            "job_updated_at": job.updated_at if job is not None else None,
            "request_updated_at": request.updated_at if request is not None else None,
            "instance_updated_at": instance.updated_at if instance is not None else None,
            "artifact_updated_at": artifact.updated_at if artifact is not None else None,
        }


class CreateVmEvidenceTests(unittest.TestCase):
    def test_completed_stopped_job_summary_joins_safe_records(self):
        job_id = "job-evidence-stopped"
        observed_after = _observed_after()
        _insert_completed_create(job_id, observed_after=observed_after)

        summary = build_create_vm_evidence_summary(job_id)

        self.assertTrue(summary["job_found"])
        self.assertTrue(summary["request_found"])
        self.assertTrue(summary["vm_instance_found"])
        self.assertEqual(job_id, summary["job"]["job_id"])
        self.assertEqual(["create_vm_risk_code"], summary["job"]["risk_codes"])
        self.assertEqual(job_id, summary["request"]["request_id"])
        self.assertEqual("user-123", summary["request"]["actor_user_id"])
        self.assertEqual("operator-a", summary["request"]["actor_username"])
        self.assertEqual("operator", summary["request"]["actor_role"])
        self.assertEqual("node-a:306", summary["vm_instance"]["vm_instance_id"])
        self.assertEqual("UPID:node-a:0001:clone", summary["proxmox"]["clone_task"]["upid"])
        self.assertEqual("not_needed", summary["proxmox"]["resize"]["action"])
        self.assertEqual(_checksum("f"), summary["observed_after"]["fingerprint_hash"])
        self.assertEqual("stopped", summary["observed_after"]["status"])
        self.assertEqual(2, len(summary["artifacts"]))
        self.assertNotIn("content_text", summary["artifacts"][0])
        self.assertEqual("node-a", summary["runbook_fields"]["target_node"])

    def test_boot_and_verify_summary_includes_safe_runtime_evidence(self):
        job_id = "job-evidence-boot-verify"
        start_task = {"upid": "UPID:node-a:0002:start", "exitstatus": "OK", "raw": "RAW_START_TASK_MARKER"}
        observed_after = _observed_after(
            status="running",
            power_policy="boot_and_verify",
            primary_ip="192.168.2.142",
            start_task=start_task,
        )
        result = _create_result(observed_after, start_task=start_task)
        result["side_effects"].extend(["proxmox_start_invoked", "proxmox_guest_agent_observed"])
        _insert_completed_create(job_id, observed_after=observed_after, result=result)

        summary = build_create_vm_evidence_summary(job_id)

        self.assertEqual("boot_and_verify", summary["observed_after"]["power_policy"])
        self.assertEqual("192.168.2.142", summary["observed_after"]["primary_ip"])
        self.assertEqual(["192.168.2.142"], summary["observed_after"]["ip_addresses"])
        self.assertTrue(summary["observed_after"]["guest_agent"]["available"])
        self.assertEqual(2, summary["observed_after"]["guest_agent"]["attempts"])
        self.assertTrue(summary["observed_after"]["cloud_init"]["success"])
        self.assertEqual("done", summary["observed_after"]["cloud_init"]["status"])
        self.assertEqual(0, summary["observed_after"]["cloud_init"]["exitcode"])
        self.assertTrue(summary["observed_after"]["boot_verification"]["success"])
        self.assertTrue(summary["observed_after"]["boot_verification"]["checks"]["cloud_init_completed"])
        self.assertEqual("UPID:node-a:0002:start", summary["proxmox"]["start_task"]["upid"])
        self.assertIn("proxmox_start_invoked", summary["proxmox"]["side_effects"])

    def test_negative_preflight_job_without_request_or_instance_is_summarized(self):
        job_id = "job-evidence-negative-preflight"
        _insert_job(job_id, status="blocked", risk_level="red")
        _insert_artifact(
            job_id,
            "preflight",
            {"status": "blocked", "raw_preflight_marker": "RAW_PREFLIGHT_PAYLOAD_MARKER"},
        )

        summary = build_create_vm_evidence_summary(job_id)

        self.assertTrue(summary["job_found"])
        self.assertFalse(summary["request_found"])
        self.assertFalse(summary["vm_instance_found"])
        self.assertIsNone(summary["request"])
        self.assertIsNone(summary["vm_instance"])
        self.assertEqual("blocked", summary["job"]["status"])
        self.assertIsNone(summary["observed_after"]["status"])
        self.assertEqual("not_recorded", summary["observed_after"]["post_check_status"])
        self.assertEqual("not_recorded", summary["runbook_fields"]["db_vm_create_request_vm_instance_evidence"]["vm_instance"])

    def test_failed_request_does_not_attach_unrelated_same_vmid_instance(self):
        job_id = "job-evidence-failed-request-only"
        _insert_job(job_id, status="failed", risk_level="yellow")
        with session_scope() as session:
            session.add(
                VmCreateRequestRecord(
                    request_id=job_id,
                    draft_id=f"draft-{job_id}",
                    manifest_id=f"manifest-{job_id}",
                    operator_id="payload-operator-id",
                    status="needs_reconciliation",
                    target_node_id="node-a",
                    vmid=306,
                    vm_name="gjallar-evidence-vm",
                    profile_id="general-vm",
                    template_id="template-9000",
                    storage_id="local-lvm",
                    actor_user_id="user-123",
                    actor_username="operator-a",
                    actor_role="operator",
                    request_payload={},
                    approval={},
                    result={"success": False, "status": "failed", "message": "create failed"},
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            session.add(
                VmInstanceRecord(
                    vm_instance_id="node-a:306",
                    node_id="node-a",
                    vmid=306,
                    name="unrelated-existing-vm",
                    status="running",
                    profile_id="general-vm",
                    template_id="template-9000",
                    storage_id="local-lvm",
                    cpu=2,
                    memory_mb=4096,
                    disk_gb=50,
                    network={},
                    access={},
                    observed_after={"status": "running"},
                    create_job_id="job-unrelated-success",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )

        summary = build_create_vm_evidence_summary(job_id)

        self.assertTrue(summary["job_found"])
        self.assertTrue(summary["request_found"])
        self.assertFalse(summary["vm_instance_found"])
        self.assertIsNone(summary["vm_instance"])

    def test_secret_and_raw_payload_fields_are_excluded_from_json(self):
        job_id = "job-evidence-secrets"
        observed_after = _observed_after(include_raw=True)
        _insert_completed_create(job_id, observed_after=observed_after, include_raw=True)

        serialized = json.dumps(build_create_vm_evidence_summary(job_id), sort_keys=True)

        forbidden = [
            TEST_SSH_PUBLIC_KEY.split()[1],
            "operator_id",
            "payload-operator-id",
            "RAW_ARTIFACT_PAYLOAD_MARKER",
            "RAW_REQUEST_PAYLOAD_MARKER",
            "RAW_APPROVAL_MARKER",
            "RAW_RESULT_MARKER",
            "RAW_CONFIG_MARKER",
            "RAW_RESIZE_RAW_CONFIG_MARKER",
            "RAW_STATUS_CURRENT_MARKER",
            "RAW_RESULT_STATUS_CURRENT_MARKER",
            "RAW_GUEST_AGENT_PAYLOAD_MARKER",
            "RAW_CLOUD_INIT_STDOUT_MARKER",
            "RAW_CLOUD_INIT_STDERR_MARKER",
            "RESULT_TOKEN_MARKER",
            "APPROVAL_TOKEN_MARKER",
            "/nodes/raw-node/qemu/306/config",
        ]
        for value in forbidden:
            self.assertNotIn(value, serialized)
        self.assertIn("[REDACTED]", serialized)

    def test_build_summary_does_not_change_counts_or_timestamps(self):
        job_id = "job-evidence-read-only"
        observed_after = _observed_after()
        _insert_completed_create(job_id, observed_after=observed_after)
        before = _snapshot(job_id)

        summary = build_create_vm_evidence_summary(job_id)

        self.assertTrue(summary["job_found"])
        self.assertEqual(before, _snapshot(job_id))

    def test_cli_emits_json_and_missing_job_returns_nonzero(self):
        job_id = "job-evidence-cli"
        observed_after = _observed_after()
        _insert_completed_create(job_id, observed_after=observed_after)
        backend_root = Path(__file__).resolve().parents[2]
        repo_root = backend_root.parent
        env = {**os.environ, "PYTHONPATH": str(backend_root)}

        completed = subprocess.run(
            [sys.executable, "-m", "app.vm_create.evidence", "--job-id", job_id],
            check=False,
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=env,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["job_found"])
        self.assertEqual(job_id, payload["job"]["job_id"])

        missing = subprocess.run(
            [sys.executable, "-m", "app.vm_create.evidence", "--job-id", "job-does-not-exist"],
            check=False,
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=env,
        )
        self.assertNotEqual(0, missing.returncode)
        self.assertEqual("", missing.stdout)
        self.assertIn("job not found: job-does-not-exist", missing.stderr)


if __name__ == "__main__":
    unittest.main()
