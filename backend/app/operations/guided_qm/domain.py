"""Infrastructure-free rules for the allowlisted `qm unlock` instruction."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from app.operations.core.domain import operation_digest
from app.operations.guided_qm.errors import GuidedQmError


GUIDED_QM_UNLOCK_TEMPLATE_ID = "qm.vm.unlock.v1"
GUIDED_QM_UNLOCK_OPERATION_TYPE = "guided_qm_vm_unlock"
GUIDED_QM_UNLOCK_TTL_SECONDS = 300
GUIDED_QM_UNLOCK_ACK_FIELD = "qm_unlock_risk_acknowledged"
GUIDED_QM_EXECUTION_ACK_FIELD = "command_executed"
GUIDED_QM_UNLOCK_SUPPORTED_LOCKS = frozenset(
    {"backup", "clone", "create", "migrate", "rollback", "snapshot", "snapshot-delete", "suspending"}
)
_NODE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PLAN_FIELDS = frozenset({"node_id", "vmid", "idempotency_key", GUIDED_QM_UNLOCK_ACK_FIELD})
_ATTEST_FIELDS = frozenset({"plan_digest", GUIDED_QM_EXECUTION_ACK_FIELD})
_VERIFY_FIELDS = frozenset({"plan_digest"})


def _mapping(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(payload or {})


def _reject_unknown_fields(payload: Mapping[str, Any], allowed: frozenset[str]) -> None:
    unsupported = sorted(str(key) for key in payload if key not in allowed)
    if unsupported:
        raise GuidedQmError(
            "GUIDED_QM_UNSUPPORTED_FIELD",
            "Guided qm requests accept only the fixed typed fields for the selected template",
            status_code=422,
            details={"unsupported_fields": unsupported, "allowed_fields": sorted(allowed)},
        )


def _validated_node_id(value: Any) -> str:
    if not isinstance(value, str):
        raise GuidedQmError("GUIDED_QM_NODE_ID_INVALID", "node_id must be a string", status_code=422)
    node_id = str(value or "").strip()
    if not _NODE_ID_PATTERN.fullmatch(node_id):
        raise GuidedQmError(
            "GUIDED_QM_NODE_ID_INVALID",
            "node_id must be a Proxmox node identifier containing only letters, numbers, dot, underscore, or hyphen",
            status_code=422,
        )
    return node_id


def _validated_vmid(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise GuidedQmError("GUIDED_QM_VMID_INVALID", "vmid must be an integer", status_code=422)
    vmid = value
    if vmid < 100 or vmid > 999_999_999:
        raise GuidedQmError(
            "GUIDED_QM_VMID_INVALID",
            "vmid must be between 100 and 999999999",
            status_code=422,
        )
    return vmid


def _validated_idempotency_key(value: Any) -> str:
    if not isinstance(value, str):
        raise GuidedQmError(
            "GUIDED_QM_IDEMPOTENCY_KEY_INVALID",
            "idempotency_key must be a string",
            status_code=422,
        )
    key = str(value or "").strip()
    if not _IDEMPOTENCY_KEY_PATTERN.fullmatch(key):
        raise GuidedQmError(
            "GUIDED_QM_IDEMPOTENCY_KEY_INVALID",
            "idempotency_key must be 1-128 safe identifier characters",
            status_code=422,
        )
    return key


def _validated_plan_digest(value: Any) -> str:
    if not isinstance(value, str):
        raise GuidedQmError(
            "GUIDED_QM_PLAN_DIGEST_INVALID",
            "A valid plan_digest is required",
            status_code=422,
        )
    digest = str(value or "").strip()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise GuidedQmError(
            "GUIDED_QM_PLAN_DIGEST_INVALID",
            "A valid plan_digest is required",
            status_code=422,
        )
    return digest


def build_guided_qm_unlock_operation_id(*, node_id: str, vmid: int, idempotency_key: str) -> str:
    digest = hashlib.sha256(f"{node_id}:{int(vmid)}:{idempotency_key}".encode("utf-8")).hexdigest()[:20]
    return f"guided-qm-unlock-{node_id}-{int(vmid)}-{digest}"


def guided_qm_vm_target_id(vmid: int) -> str:
    return f"vmid:{int(vmid)}"


def guided_qm_unlock_intent(*, node_id: str, vmid: int) -> dict[str, Any]:
    return {
        "schema": "guided_qm_intent.v1",
        "operation": "vm_unlock",
        "template_id": GUIDED_QM_UNLOCK_TEMPLATE_ID,
        "target": {"type": "proxmox_vm", "node_id": node_id, "vmid": int(vmid)},
    }


def build_guided_qm_unlock_bundle(
    *,
    operation_id: str,
    node_id: str,
    vmid: int,
    expires_at: datetime,
    observed_lock: str,
) -> dict[str, Any]:
    if expires_at.tzinfo is None:
        raise ValueError("Guided qm bundle expiry must include a timezone")
    plan = {
        "schema": "guided_qm_instruction.v1",
        "template_id": GUIDED_QM_UNLOCK_TEMPLATE_ID,
        "operation_id": operation_id,
        "execution_mode": "guided_manual",
        "target": {"type": "proxmox_vm", "node_id": node_id, "vmid": int(vmid)},
        "command": {
            "program": "qm",
            "arguments": ["unlock", str(int(vmid))],
            "display": f"qm unlock {int(vmid)}",
            "run_on": "target_proxmox_node_shell",
        },
        "expires_at": expires_at.isoformat(),
        "observed_before": {"config_lock": observed_lock, "active_tasks": []},
        "expected_result": {"config_lock_absent": True, "active_tasks": []},
        "verification": {
            "authority": "proxmox_api",
            "config_endpoint": f"/nodes/{node_id}/qemu/{int(vmid)}/config",
            "tasks_endpoint": f"/nodes/{node_id}/tasks?source=active&vmid={int(vmid)}",
        },
        "warnings": [
            "Run only after confirming the task that created the lock is no longer running.",
            f"The observed Proxmox configuration lock is {observed_lock}.",
            "Do not edit the command or add options.",
        ],
    }
    return {**plan, "plan_digest": operation_digest(plan)}


@dataclass(frozen=True)
class PlanGuidedQmUnlockCommand:
    node_id: str
    vmid: int
    idempotency_key: str
    actor: dict[str, Any]

    @classmethod
    def from_request(
        cls,
        payload: Mapping[str, Any] | None,
        *,
        actor: Mapping[str, Any] | None,
    ) -> "PlanGuidedQmUnlockCommand":
        request = _mapping(payload)
        _reject_unknown_fields(request, _PLAN_FIELDS)
        if request.get(GUIDED_QM_UNLOCK_ACK_FIELD) is not True:
            raise GuidedQmError(
                "GUIDED_QM_UNLOCK_RISK_ACK_REQUIRED",
                f"{GUIDED_QM_UNLOCK_ACK_FIELD}=true is required before issuing an unlock instruction",
                details={"required_acknowledgement": GUIDED_QM_UNLOCK_ACK_FIELD},
            )
        return cls(
            node_id=_validated_node_id(request.get("node_id")),
            vmid=_validated_vmid(request.get("vmid")),
            idempotency_key=_validated_idempotency_key(request.get("idempotency_key")),
            actor=dict(actor or {}),
        )

    @property
    def operation_id(self) -> str:
        return build_guided_qm_unlock_operation_id(
            node_id=self.node_id,
            vmid=self.vmid,
            idempotency_key=self.idempotency_key,
        )

    @property
    def target_id(self) -> str:
        return guided_qm_vm_target_id(self.vmid)

    @property
    def intent(self) -> dict[str, Any]:
        return guided_qm_unlock_intent(node_id=self.node_id, vmid=self.vmid)


@dataclass(frozen=True)
class AttestGuidedQmCommand:
    operation_id: str
    plan_digest: str
    actor: dict[str, Any]

    @classmethod
    def from_request(
        cls,
        operation_id: str,
        payload: Mapping[str, Any] | None,
        *,
        actor: Mapping[str, Any] | None,
    ) -> "AttestGuidedQmCommand":
        request = _mapping(payload)
        _reject_unknown_fields(request, _ATTEST_FIELDS)
        if request.get(GUIDED_QM_EXECUTION_ACK_FIELD) is not True:
            raise GuidedQmError(
                "GUIDED_QM_EXECUTION_ACK_REQUIRED",
                f"{GUIDED_QM_EXECUTION_ACK_FIELD}=true is required after external command execution",
                details={"required_acknowledgement": GUIDED_QM_EXECUTION_ACK_FIELD},
            )
        return cls(
            operation_id=str(operation_id or "").strip(),
            plan_digest=_validated_plan_digest(request.get("plan_digest")),
            actor=dict(actor or {}),
        )


@dataclass(frozen=True)
class VerifyGuidedQmCommand:
    operation_id: str
    plan_digest: str
    actor: dict[str, Any]

    @classmethod
    def from_request(
        cls,
        operation_id: str,
        payload: Mapping[str, Any] | None,
        *,
        actor: Mapping[str, Any] | None,
    ) -> "VerifyGuidedQmCommand":
        request = _mapping(payload)
        _reject_unknown_fields(request, _VERIFY_FIELDS)
        return cls(
            operation_id=str(operation_id or "").strip(),
            plan_digest=_validated_plan_digest(request.get("plan_digest")),
            actor=dict(actor or {}),
        )
