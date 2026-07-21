"""Infrastructure-free graceful VM Shutdown command and stable intent."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Mapping


def _safe_segment(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value)).strip("-")
    return safe[:80] or "vm"


def build_vm_shutdown_job_id(*, node_id: str, vmid: int, idempotency_key: str) -> str:
    digest = hashlib.sha256(f"{node_id}:{int(vmid)}:{idempotency_key}".encode("utf-8")).hexdigest()[:16]
    return f"vm-shutdown-{_safe_segment(node_id)}-{int(vmid)}-{digest}"


def vm_shutdown_target(*, node_id: str, vmid: int, name: str = "") -> dict[str, Any]:
    return {"node_id": str(node_id), "vmid": int(vmid), "name": str(name)}


def vm_shutdown_target_lock_id(vmid: int) -> str:
    return f"vmid:{int(vmid)}"


def vm_shutdown_expected_context(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "expected_name": str(payload.get("expected_name") or "").strip(),
        "expected_status": str(payload.get("expected_status") or "").strip(),
    }


def stable_vm_shutdown_intent(*, node_id: str, vmid: int, payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": "vm_shutdown_intent.v1",
        "operation": "vm_shutdown",
        "target": {"node_id": str(node_id), "vmid": int(vmid)},
        "expected": vm_shutdown_expected_context(payload),
    }


@dataclass(frozen=True)
class VmShutdownCommand:
    node_id: str
    vmid: int
    payload: dict[str, Any]
    actor: dict[str, Any]

    @classmethod
    def from_request(
        cls,
        *,
        node_id: str,
        vmid: int,
        payload: Mapping[str, Any] | None,
        actor: Mapping[str, Any] | None,
    ) -> "VmShutdownCommand":
        return cls(
            node_id=str(node_id),
            vmid=int(vmid),
            payload=dict(payload or {}),
            actor=dict(actor or {}),
        )

    @property
    def expected(self) -> dict[str, Any]:
        return vm_shutdown_expected_context(self.payload)

    @property
    def stable_intent(self) -> dict[str, Any]:
        return stable_vm_shutdown_intent(node_id=self.node_id, vmid=self.vmid, payload=self.payload)
