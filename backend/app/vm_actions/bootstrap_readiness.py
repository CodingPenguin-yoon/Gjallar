"""No-live SSH/Ansible bootstrap readiness intent evidence."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.auth.roles import actor_detail_fields, actor_evidence
from app.core.redaction import redact_secrets
from app.jobs.artifacts import write_json_artifact
from app.jobs.runs import get_job_run, record_job_run, run_dir


READINESS_FLAGS = {
    "proxmox_mutation_enabled": False,
    "ssh_login_ran": False,
    "ansible_ran": False,
    "app_bootstrap_ran": False,
    "side_effects": [],
}

_FORBIDDEN_EXACT_KEYS = {
    "ansibleinventory": "ansible_inventory",
    "ansibleplaybook": "playbook",
    "ansibleuser": "ansible_user",
    "ansiblesshprivatekeyfile": "ssh_private_key",
    "command": "command",
    "commands": "command",
    "env": "env",
    "environment": "env",
    "environmentvariables": "env",
    "keypath": "key_path",
    "password": "password",
    "passwd": "password",
    "playbook": "playbook",
    "playbookpath": "playbook",
    "privatekey": "private_key",
    "privatekeypath": "key_path",
    "publickey": "public_key",
    "script": "command",
    "shell": "shell",
    "sshkeypath": "key_path",
    "sshprivatekey": "ssh_private_key",
    "sshprivatekeyfile": "ssh_private_key",
    "sshpublickey": "ssh_public_key",
    "sshuser": "ssh_user",
    "sshusername": "ssh_username",
    "token": "token",
}
_FORBIDDEN_MARKER_KEYS = (
    ("privatekey", "private_key"),
    ("publickey", "public_key"),
    ("password", "password"),
    ("passwd", "password"),
    ("token", "token"),
    ("secret", "secret"),
)


class BootstrapReadinessError(RuntimeError):
    """Raised when a bootstrap readiness intent request is blocked."""

    def __init__(self, code: str, message: str, *, status_code: int = 409, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = dict(details or {})

    def to_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            **self.details,
        }


@dataclass(frozen=True)
class BootstrapReadinessPrecheck:
    target: dict[str, Any]
    observed_inventory: dict[str, Any]
    expected: dict[str, str]
    guest_agent_ip_addresses: list[str]


def _safe_segment(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value)).strip("-")
    return safe[:80] or "vm"


def build_bootstrap_readiness_job_id(*, node_id: str, vmid: int, idempotency_key: str) -> str:
    digest = hashlib.sha256(f"{node_id}:{int(vmid)}:{idempotency_key}".encode("utf-8")).hexdigest()[:16]
    return f"bootstrap-readiness-{_safe_segment(node_id)}-{int(vmid)}-{digest}"


def _target_id(node_id: str, vmid: int, name: str = "") -> str:
    suffix = f":{name}" if name else ""
    return f"{node_id}:{int(vmid)}{suffix}"


def _target_payload(node_id: str, vmid: int, name: str = "") -> dict[str, Any]:
    return {
        "node_id": node_id,
        "vmid": int(vmid),
        "name": name,
    }


def _normalize_status(value: object) -> str:
    return str(value or "").strip().lower()


def _to_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return dict(value)
    return {}


def _vm_node_id(value: Any) -> str:
    data = _to_dict(value)
    return str(data.get("node_id") or data.get("node") or "").strip()


def _vm_vmid(value: Any) -> int | None:
    data = _to_dict(value)
    try:
        return int(data.get("vmid") if data.get("vmid") is not None else data.get("id"))
    except (TypeError, ValueError):
        return None


def _find_exact_vm(adapter: Any, *, node_id: str, vmid: int) -> tuple[Any | None, Any | None]:
    vms = list(adapter.list_vms()) if hasattr(adapter, "list_vms") else []
    exact = next((vm for vm in vms if _vm_vmid(vm) == int(vmid) and _vm_node_id(vm) == node_id), None)
    moved = next((vm for vm in vms if _vm_vmid(vm) == int(vmid) and _vm_node_id(vm) != node_id), None)
    return exact, moved


def _find_template(adapter: Any, *, node_id: str, vmid: int) -> Any | None:
    templates = list(adapter.list_templates()) if hasattr(adapter, "list_templates") else []
    return next(
        (
            template
            for template in templates
            if _vm_vmid(template) == int(vmid)
            and (not _vm_node_id(template) or _vm_node_id(template) == node_id)
        ),
        None,
    )


def _payload_value(payload: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return str(value).strip()
    return ""


def _expected_context(payload: Mapping[str, Any]) -> dict[str, str]:
    return {
        "expected_name": _payload_value(payload, "expected_name", "expectedName"),
        "expected_status": _payload_value(payload, "expected_status", "expectedStatus"),
        "expected_ip": _payload_value(payload, "expected_ip", "expectedIp", "expected_ip_address", "expectedIpAddress"),
    }


def _normalize_key(key: Any) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "", str(key)).lower()


def _forbidden_key_category(key: Any) -> str:
    normalized = _normalize_key(key)
    if normalized in _FORBIDDEN_EXACT_KEYS:
        return _FORBIDDEN_EXACT_KEYS[normalized]
    for marker, category in _FORBIDDEN_MARKER_KEYS:
        if marker in normalized:
            return category
    return ""


def _forbidden_payload_keys(value: Any) -> list[str]:
    categories: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                category = _forbidden_key_category(key)
                if category:
                    categories.add(category)
                    continue
                visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)

    visit(value)
    return sorted(categories)


def _safe_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = []
    return [str(item).strip() for item in values if str(item or "").strip()]


def _safe_ip_evidence(value: Any) -> list[dict[str, Any]]:
    result = []
    items = value if isinstance(value, (list, tuple)) else []
    for item in items:
        data = _to_dict(item)
        ip_address = str(data.get("ip_address") or data.get("ip") or "").strip()
        if not ip_address:
            continue
        result.append(
            {
                "ip_address": ip_address,
                "source": str(data.get("source") or "").strip(),
                "interface_name": str(data.get("interface_name") or "").strip(),
                "scope": str(data.get("scope") or "").strip(),
                "primary_candidate": bool(data.get("primary_candidate")),
            }
        )
    return result


def _safe_vm_evidence(value: Any) -> dict[str, Any]:
    data = _to_dict(value)
    guest_agent = data.get("guest_agent") if isinstance(data.get("guest_agent"), dict) else {}
    guest_agent_ips = _safe_string_list(guest_agent.get("ip_addresses"))
    ip_evidence = _safe_ip_evidence(data.get("ip_evidence"))
    return {
        "node_id": str(data.get("node_id") or data.get("node") or "").strip(),
        "vmid": int(data.get("vmid") or data.get("id") or 0),
        "name": str(data.get("name") or "").strip(),
        "status": _normalize_status(data.get("status")),
        "template": bool(data.get("template")),
        "guest_agent": {
            "available": bool(guest_agent.get("available")),
            "ip_addresses": guest_agent_ips,
        },
        "ip_addresses": _safe_string_list(data.get("ip_addresses")),
        "ip_evidence": ip_evidence,
    }


def _all_observed_ips(evidence: Mapping[str, Any]) -> set[str]:
    guest_agent = evidence.get("guest_agent") if isinstance(evidence.get("guest_agent"), Mapping) else {}
    ips = set(_safe_string_list(guest_agent.get("ip_addresses")))
    ips.update(_safe_string_list(evidence.get("ip_addresses")))
    ip_evidence = evidence.get("ip_evidence") if isinstance(evidence.get("ip_evidence"), list) else []
    for item in ip_evidence:
        if isinstance(item, Mapping):
            ip_address = str(item.get("ip_address") or "").strip()
            if ip_address:
                ips.add(ip_address)
    return ips


def _guest_agent_ips(evidence: Mapping[str, Any]) -> list[str]:
    guest_agent = evidence.get("guest_agent") if isinstance(evidence.get("guest_agent"), Mapping) else {}
    ips = _safe_string_list(guest_agent.get("ip_addresses"))
    ip_evidence = evidence.get("ip_evidence") if isinstance(evidence.get("ip_evidence"), list) else []
    for item in ip_evidence:
        if not isinstance(item, Mapping):
            continue
        source = str(item.get("source") or "").lower()
        ip_address = str(item.get("ip_address") or "").strip()
        if ip_address and "guest" in source and ip_address not in ips:
            ips.append(ip_address)
    return ips


def _record_bootstrap_job(
    *,
    job_id: str,
    status: str,
    stage: str,
    step_status: str,
    message: str,
    target: dict[str, Any],
    artifacts: list[Any] | None = None,
    details: dict[str, Any] | None = None,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    details_payload = {"target": target, **(details or {})}
    details_payload.update(actor_detail_fields(actor))
    return record_job_run(
        job_id=job_id,
        job_type="bootstrap_readiness",
        status=status,
        target_id=_target_id(str(target.get("node_id") or ""), int(target.get("vmid") or 0)),
        risk_level="unknown",
        stage=stage,
        step_status=step_status,
        message=message,
        artifacts=artifacts,
        risks=[],
        details=redact_secrets(details_payload),
    )


def _write_intent_artifact(
    *,
    job_id: str,
    status: str,
    message: str,
    target: dict[str, Any],
    idempotency_key: str,
    expected: dict[str, str],
    inventory_source: str,
    observed_inventory: dict[str, Any] | None = None,
    blockers: list[str] | None = None,
    forbidden_payload_keys: list[str] | None = None,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "job_id": job_id,
        "operation": "bootstrap_readiness_intent",
        "mode": "no_live_ssh_no_ansible",
        "status": status,
        "message": message,
        "target": target,
        "idempotency_key": idempotency_key,
        "expected": expected,
        "inventory_source": inventory_source,
        "observed_inventory": observed_inventory or {},
        "readiness": {
            "ready": status == "completed",
            "blockers": list(blockers or []),
            "forbidden_payload_keys": list(forbidden_payload_keys or []),
        },
        **READINESS_FLAGS,
    }
    payload.update(actor_detail_fields(actor))
    return write_json_artifact(
        run_dir=run_dir(job_id),
        job_id=job_id,
        artifact_type="bootstrap_readiness_intent",
        filename="bootstrap_readiness_intent.json",
        payload=payload,
    ).to_dict()


def _blocked(
    *,
    job_id: str,
    code: str,
    message: str,
    target: dict[str, Any],
    idempotency_key: str,
    expected: dict[str, str],
    inventory_source: str,
    observed_inventory: dict[str, Any] | None = None,
    stage: str = "target_precheck",
    forbidden_payload_keys: list[str] | None = None,
    actor: dict[str, Any] | None = None,
) -> None:
    artifact = _write_intent_artifact(
        job_id=job_id,
        status="blocked",
        message=message,
        target=target,
        idempotency_key=idempotency_key,
        expected=expected,
        inventory_source=inventory_source,
        observed_inventory=observed_inventory or {},
        blockers=[code],
        forbidden_payload_keys=forbidden_payload_keys,
        actor=actor,
    )
    result = {
        "job_id": job_id,
        "status": "blocked",
        "message": message,
        "target": target,
        "expected": expected,
        "observed_inventory": observed_inventory or {},
        "bootstrap_readiness_intent_artifact": artifact,
        "artifacts": [artifact],
        "idempotent_replay": False,
        "forbidden_payload_keys": list(forbidden_payload_keys or []),
        **READINESS_FLAGS,
    }
    safe_result = redact_secrets(result)
    if forbidden_payload_keys:
        safe_result["forbidden_payload_keys"] = list(forbidden_payload_keys)
    _record_bootstrap_job(
        job_id=job_id,
        status="blocked",
        stage=stage,
        step_status="blocked",
        message=message,
        target=target,
        artifacts=[artifact],
        actor=actor,
        details={"bootstrap_readiness_result": safe_result},
    )
    raise BootstrapReadinessError(code, message, details=safe_result)


def _precheck_bootstrap_readiness(
    *,
    adapter: Any,
    node_id: str,
    vmid: int,
    payload: Mapping[str, Any],
    job_id: str,
    idempotency_key: str,
    inventory_source: str,
    actor: dict[str, Any] | None = None,
) -> BootstrapReadinessPrecheck:
    expected = _expected_context(payload)
    target = _target_payload(node_id, vmid, expected.get("expected_name", ""))
    exact_vm, moved_vm = _find_exact_vm(adapter, node_id=node_id, vmid=vmid)
    template = _find_template(adapter, node_id=node_id, vmid=vmid)

    if template is not None:
        observed = _safe_vm_evidence(template)
        _blocked(
            job_id=job_id,
            code="BOOTSTRAP_READINESS_TEMPLATE_BLOCKED",
            message="Bootstrap readiness intent is blocked for templates",
            target={**target, "name": str(observed.get("name") or target.get("name") or "")},
            idempotency_key=idempotency_key,
            expected=expected,
            inventory_source=inventory_source,
            observed_inventory={**observed, "template": True},
            actor=actor,
        )

    if exact_vm is None:
        if moved_vm is not None:
            observed = _safe_vm_evidence(moved_vm)
            _blocked(
                job_id=job_id,
                code="BOOTSTRAP_READINESS_MOVED_BLOCKED",
                message="Bootstrap readiness target moved from the requested node",
                target={**target, "name": str(observed.get("name") or target.get("name") or "")},
                idempotency_key=idempotency_key,
                expected=expected,
                inventory_source=inventory_source,
                observed_inventory=observed,
                actor=actor,
            )
        _blocked(
            job_id=job_id,
            code="BOOTSTRAP_READINESS_MISSING_BLOCKED",
            message="Bootstrap readiness target was not found in fresh inventory",
            target=target,
            idempotency_key=idempotency_key,
            expected=expected,
            inventory_source=inventory_source,
            observed_inventory={},
            actor=actor,
        )

    observed = _safe_vm_evidence(exact_vm)
    target = _target_payload(node_id, vmid, str(observed.get("name") or target.get("name") or ""))
    if bool(observed.get("template")):
        _blocked(
            job_id=job_id,
            code="BOOTSTRAP_READINESS_TEMPLATE_BLOCKED",
            message="Bootstrap readiness intent is blocked for templates",
            target=target,
            idempotency_key=idempotency_key,
            expected=expected,
            inventory_source=inventory_source,
            observed_inventory=observed,
            actor=actor,
        )

    status = _normalize_status(observed.get("status"))
    expected_name = str(expected.get("expected_name") or "").strip()
    observed_name = str(observed.get("name") or "").strip()
    if expected_name and observed_name != expected_name:
        _blocked(
            job_id=job_id,
            code="BOOTSTRAP_READINESS_CONTEXT_MISMATCH",
            message="Bootstrap readiness context mismatch: expected name did not match fresh inventory",
            target=target,
            idempotency_key=idempotency_key,
            expected=expected,
            inventory_source=inventory_source,
            observed_inventory=observed,
            actor=actor,
        )

    expected_status = _normalize_status(expected.get("expected_status"))
    if expected_status and status != expected_status:
        _blocked(
            job_id=job_id,
            code="BOOTSTRAP_READINESS_CONTEXT_MISMATCH",
            message="Bootstrap readiness context mismatch: expected status did not match fresh inventory",
            target=target,
            idempotency_key=idempotency_key,
            expected=expected,
            inventory_source=inventory_source,
            observed_inventory=observed,
            actor=actor,
        )

    expected_ip = str(expected.get("expected_ip") or "").strip()
    if expected_ip and expected_ip not in _all_observed_ips(observed):
        _blocked(
            job_id=job_id,
            code="BOOTSTRAP_READINESS_CONTEXT_MISMATCH",
            message="Bootstrap readiness context mismatch: expected IP was not observed in fresh inventory",
            target=target,
            idempotency_key=idempotency_key,
            expected=expected,
            inventory_source=inventory_source,
            observed_inventory=observed,
            actor=actor,
        )

    if status != "running":
        _blocked(
            job_id=job_id,
            code="BOOTSTRAP_READINESS_NON_RUNNING_BLOCKED",
            message=f"Bootstrap readiness requires a running VM; observed {status or 'unknown'}",
            target=target,
            idempotency_key=idempotency_key,
            expected=expected,
            inventory_source=inventory_source,
            observed_inventory=observed,
            actor=actor,
        )

    guest_agent = observed.get("guest_agent") if isinstance(observed.get("guest_agent"), Mapping) else {}
    guest_ips = _guest_agent_ips(observed)
    if guest_agent.get("available") is not True or not guest_ips:
        _blocked(
            job_id=job_id,
            code="BOOTSTRAP_READINESS_GUEST_AGENT_IP_REQUIRED",
            message="Bootstrap readiness requires guest-agent IP evidence before any SSH or Ansible possibility",
            target=target,
            idempotency_key=idempotency_key,
            expected=expected,
            inventory_source=inventory_source,
            observed_inventory=observed,
            stage="inventory_evidence",
            actor=actor,
        )

    return BootstrapReadinessPrecheck(
        target=target,
        observed_inventory=observed,
        expected=expected,
        guest_agent_ip_addresses=guest_ips,
    )


def _validated_request(node_id: str, vmid: int, payload: Mapping[str, Any]) -> tuple[str, str]:
    idempotency_key = str(payload.get("idempotency_key") or "").strip()
    if payload.get("bootstrap_readiness_acknowledged") is not True:
        raise BootstrapReadinessError(
            "BOOTSTRAP_READINESS_ACK_REQUIRED",
            "bootstrap_readiness_acknowledged=true is required before recording bootstrap readiness intent",
            details={"target": _target_payload(node_id, vmid), **READINESS_FLAGS},
        )
    if not idempotency_key:
        raise BootstrapReadinessError(
            "BOOTSTRAP_READINESS_IDEMPOTENCY_KEY_REQUIRED",
            "A non-empty idempotency_key is required before recording bootstrap readiness intent",
            details={"target": _target_payload(node_id, vmid), **READINESS_FLAGS},
        )
    return idempotency_key, build_bootstrap_readiness_job_id(
        node_id=node_id,
        vmid=vmid,
        idempotency_key=idempotency_key,
    )


def _result_from_existing(job: dict[str, Any]) -> dict[str, Any]:
    details = job.get("details") if isinstance(job.get("details"), dict) else {}
    stored = details.get("bootstrap_readiness_result") if isinstance(details.get("bootstrap_readiness_result"), dict) else {}
    target = details.get("target") if isinstance(details.get("target"), dict) else stored.get("target", {})
    return {
        **stored,
        "job_id": job.get("job_id"),
        "status": job.get("status"),
        "target": target,
        "idempotent_replay": True,
        **READINESS_FLAGS,
        "message": job.get("message") or stored.get("message") or "Existing bootstrap readiness job returned for idempotency key",
    }


def run_bootstrap_readiness_intent(
    *,
    node_id: str,
    vmid: int,
    payload: dict[str, Any] | None,
    inventory_adapter: Any,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record a no-live-SSH/Ansible bootstrap readiness intent from read-only inventory."""
    request_payload = dict(payload or {})
    actor_payload = actor_evidence(actor) if actor is not None else {}
    inventory_source = str(getattr(inventory_adapter, "source", "") or "read_only")
    idempotency_key, job_id = _validated_request(node_id, vmid, request_payload)
    existing = get_job_run(job_id)
    if existing:
        return _result_from_existing(existing)

    expected = _expected_context(request_payload)
    target = _target_payload(node_id, vmid, expected.get("expected_name", ""))
    forbidden_keys = _forbidden_payload_keys(request_payload)
    if forbidden_keys:
        _blocked(
            job_id=job_id,
            code="BOOTSTRAP_READINESS_FORBIDDEN_PAYLOAD",
            message="Bootstrap readiness intent rejects credential and execution payload keys",
            target=target,
            idempotency_key=idempotency_key,
            expected=expected,
            inventory_source=inventory_source,
            observed_inventory={},
            forbidden_payload_keys=forbidden_keys,
            actor=actor_payload,
        )

    _record_bootstrap_job(
        job_id=job_id,
        status="running",
        stage="target_precheck",
        step_status="running",
        message="Bootstrap readiness target precheck is running.",
        target=target,
        actor=actor_payload,
        details={
            "bootstrap_readiness": {
                "idempotency_key": idempotency_key,
                "expected": expected,
                "inventory_source": inventory_source,
                **READINESS_FLAGS,
            }
        },
    )

    precheck = _precheck_bootstrap_readiness(
        adapter=inventory_adapter,
        node_id=node_id,
        vmid=vmid,
        payload=request_payload,
        job_id=job_id,
        idempotency_key=idempotency_key,
        inventory_source=inventory_source,
        actor=actor_payload,
    )
    artifact = _write_intent_artifact(
        job_id=job_id,
        status="completed",
        message="Bootstrap readiness intent recorded without live SSH, Ansible, app bootstrap, or Proxmox mutation.",
        target=precheck.target,
        idempotency_key=idempotency_key,
        expected=precheck.expected,
        inventory_source=inventory_source,
        observed_inventory=precheck.observed_inventory,
        actor=actor_payload,
    )
    result = {
        "job_id": job_id,
        "status": "completed",
        "message": "Bootstrap readiness intent recorded without live SSH, Ansible, app bootstrap, or Proxmox mutation.",
        "target": precheck.target,
        "expected": precheck.expected,
        "observed_inventory": precheck.observed_inventory,
        "guest_agent_ip_addresses": precheck.guest_agent_ip_addresses,
        "bootstrap_readiness_intent_artifact": artifact,
        "artifacts": [artifact],
        "idempotent_replay": False,
        **READINESS_FLAGS,
    }
    safe_result = redact_secrets(result)
    _record_bootstrap_job(
        job_id=job_id,
        status="completed",
        stage="intent_recorded",
        step_status="completed",
        message=result["message"],
        target=precheck.target,
        artifacts=[artifact],
        actor=actor_payload,
        details={"bootstrap_readiness_result": safe_result},
    )
    return safe_result
