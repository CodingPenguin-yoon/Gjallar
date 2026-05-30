"""Manual DRS VM migration policy management.

This module manages Gjallar-local policy rows only. It never writes Proxmox
state, tags, or migration jobs.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.auth.roles import AuthenticatedUser, actor_evidence
from app.db.models import (
    VmIdentityObservationRecord,
    VmIdentityRecord,
    VmMigrationPolicyEventRecord,
    VmMigrationPolicyRecord,
)
from app.db.session import session_scope
from app.drs.advisor import (
    _blocker_detail,
    _calculate_drs_model,
    _identity_policy_blockers,
    build_drs_check_result,
)
from app.drs.identity import policy_evidence_for_identity

POLICY_VALUES = {"unknown", "allowed", "restricted", "blocked"}
GUARD_FIELDS = ("cluster_id", "node_id", "vmid", "fingerprint_hash", "observed_at")


class DrsPolicyServiceError(Exception):
    """HTTP-mappable policy service error."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = {"code": code, "message": message, **(details or {})}

    def to_detail(self) -> dict[str, Any]:
        return dict(self.detail)


def _event_id() -> str:
    return f"vmpolevt-{uuid.uuid4().hex}"


def _policy_id() -> str:
    return f"vmpol-{uuid.uuid4().hex}"


def _request_id() -> str:
    return f"drs-policy-{uuid.uuid4().hex}"


def _as_text(value: Any, fallback: str = "") -> str:
    text = str(value if value is not None else "").strip()
    return text or fallback


def _as_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    aware = _aware(value)
    return aware.isoformat() if aware is not None else None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _aware(value)
    text = _as_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _aware(parsed)


def _same_observed_at(left: Any, right: Any) -> bool:
    left_dt = _parse_datetime(left)
    right_dt = _parse_datetime(right)
    if left_dt is None or right_dt is None:
        return _as_text(left) == _as_text(right)
    return left_dt == right_dt


def _latest_observation(
    session: Session,
    vm_identity_id: str,
    *,
    high_only: bool = False,
) -> VmIdentityObservationRecord | None:
    statement = select(VmIdentityObservationRecord).where(
        VmIdentityObservationRecord.vm_identity_id == vm_identity_id,
    )
    if high_only:
        statement = statement.where(VmIdentityObservationRecord.match_confidence == "high")
    return session.execute(statement.order_by(desc(VmIdentityObservationRecord.observed_at)).limit(1)).scalar_one_or_none()


def _observation_guard(observation: VmIdentityObservationRecord | None) -> dict[str, Any]:
    if observation is None:
        return {}
    return {
        "observation_id": observation.observation_id,
        "cluster_id": observation.cluster_id,
        "node_id": observation.node_id,
        "vmid": observation.vmid,
        "fingerprint_hash": observation.fingerprint_hash,
        "observed_at": _iso(observation.observed_at),
        "match_confidence": observation.match_confidence,
    }


def _fingerprint_summary(identity_evidence: dict[str, Any], observation: VmIdentityObservationRecord | None) -> dict[str, Any]:
    components = _as_mapping(identity_evidence.get("fingerprint_components"))
    return {
        "fingerprint_hash": observation.fingerprint_hash if observation is not None else identity_evidence.get("stable_fingerprint"),
        "stable_fingerprint": identity_evidence.get("stable_fingerprint"),
        "smbios1_uuid_present": bool(_as_text(components.get("smbios1_uuid"))),
        "vmgenid_present": bool(_as_text(components.get("vmgenid"))),
        "mac_address_count": len(_as_list(components.get("mac_addresses"))),
        "disk_volume_id_count": len(_as_list(components.get("disk_volume_ids"))),
        "source": identity_evidence.get("source"),
    }


def _observation_age_seconds(observation: VmIdentityObservationRecord | None) -> int | None:
    observed_at = _aware(observation.observed_at if observation is not None else None)
    if observed_at is None:
        return None
    return max(0, int((datetime.now(timezone.utc) - observed_at).total_seconds()))


def _recommendation_for_vm(vm: dict[str, Any], identity_evidence: dict[str, Any], recommendations: list[dict[str, Any]]) -> dict[str, Any] | None:
    vm_identity_id = _as_text(identity_evidence.get("vm_identity_id"))
    for recommendation in recommendations:
        recommendation_identity = _as_mapping(recommendation.get("identity_evidence"))
        if vm_identity_id and recommendation_identity.get("vm_identity_id") == vm_identity_id:
            return recommendation
        if recommendation.get("vmid") == vm.get("vmid") and recommendation.get("source_node_id") == vm.get("node_id"):
            return recommendation
    return None


def _policy_write_blockers(
    *,
    identity_evidence: dict[str, Any],
    identity: VmIdentityRecord | None,
    latest_observation: VmIdentityObservationRecord | None,
) -> list[str]:
    blockers: list[str] = []
    vm_identity_id = _as_text(identity_evidence.get("vm_identity_id"))
    confidence = _as_text(identity_evidence.get("match_confidence"), "unknown")
    if not vm_identity_id:
        blockers.append("policy_write_identity_unknown")
    if confidence != "high":
        blockers.append("policy_write_identity_uncertain" if confidence != "unknown" else "policy_write_identity_unknown")
    if identity_evidence.get("conflict_signal") is True:
        blockers.append("policy_write_identity_conflict")
    if identity is not None and identity.identity_status != "active":
        blockers.append("policy_write_identity_retired")
    if latest_observation is None:
        blockers.append("policy_write_current_observation_missing")
    elif latest_observation.match_confidence != "high":
        blockers.append("policy_write_latest_observation_not_high")
    return sorted(set(blockers))


def _policy_item_from_current(
    *,
    session: Session,
    vm: dict[str, Any],
    identity_evidence: dict[str, Any],
    recommendation: dict[str, Any] | None,
) -> dict[str, Any]:
    vm_identity_id = _as_text(identity_evidence.get("vm_identity_id"))
    identity = session.get(VmIdentityRecord, vm_identity_id) if vm_identity_id else None
    latest = _latest_observation(session, vm_identity_id) if vm_identity_id else None
    policy_evidence = policy_evidence_for_identity(session, vm_identity_id)
    policy_blockers = _identity_policy_blockers(identity_evidence, policy_evidence)
    write_blockers = _policy_write_blockers(
        identity_evidence=identity_evidence,
        identity=identity,
        latest_observation=latest,
    )
    recommendation_blockers = _as_list((recommendation or {}).get("blockers"))
    locator = {
        "cluster_id": (latest.cluster_id if latest is not None else identity_evidence.get("fingerprint_components", {}).get("locator", {}).get("cluster_id")),
        "node_id": vm.get("node_id"),
        "vmid": vm.get("vmid"),
        "name": vm.get("name"),
        "power_state": vm.get("status"),
    }
    return {
        "vm_identity_id": vm_identity_id or None,
        "identity_confidence": _as_text(identity_evidence.get("match_confidence"), "unknown"),
        "identity_status": _as_text(identity_evidence.get("identity_status"), "unknown"),
        "identity_evidence": identity_evidence,
        "current_locator": locator,
        "latest_observation": {
            "observation_id": latest.observation_id if latest is not None else None,
            "observed_at": _iso(latest.observed_at if latest is not None else None),
            "age_seconds": _observation_age_seconds(latest),
            "match_confidence": latest.match_confidence if latest is not None else None,
            "source": latest.source if latest is not None else None,
        },
        "expected_observation": _observation_guard(latest),
        "fingerprint": _fingerprint_summary(identity_evidence, latest),
        "policy": {
            "policy_id": policy_evidence.get("policy_id"),
            "value": policy_evidence.get("policy", "unknown"),
            "policy": policy_evidence.get("policy", "unknown"),
            "reason": policy_evidence.get("reason", ""),
            "source": policy_evidence.get("source", "default"),
            "updated_by": policy_evidence.get("updated_by"),
            "updated_at": policy_evidence.get("updated_at"),
        },
        "policy_evidence": policy_evidence,
        "current_drs_candidate": recommendation is not None,
        "recommendation_id": (recommendation or {}).get("id"),
        "drs_blocker_impact": {
            "policy_blockers": policy_blockers,
            "recommendation_blockers": recommendation_blockers,
            "blocks_recommendation": bool(policy_blockers),
            "blocks_final_check": policy_evidence.get("policy") != "allowed" or bool(
                set(policy_blockers)
                & {
                    "vm_identity_unknown",
                    "vm_identity_uncertain",
                    "identity_unknown",
                    "metadata_missing",
                    "identity_conflict",
                    "migration_policy_unknown",
                    "migration_policy_restricted",
                    "migration_policy_blocked",
                }
            ),
            "allowed_is_prerequisite_only": True,
            "blocker_details": [_blocker_detail(code) for code in policy_blockers],
        },
        "policy_write_allowed": not write_blockers,
        "policy_write_blockers": write_blockers,
    }


def _policy_model(adapter: Any, *, risks: list[Any] | None = None) -> dict[str, Any]:
    calculated = _calculate_drs_model(adapter, risks=risks)
    vms = [vm for vm in calculated["vms"] if vm.get("template") is not True]
    recommendations = calculated["model"]["recommendations"]
    items: list[dict[str, Any]] = []
    with session_scope() as session:
        for vm in vms:
            identity_resolution = calculated["identity_map"].get((vm["node_id"], vm["vmid"]))
            identity_evidence = identity_resolution.to_evidence() if identity_resolution is not None else {}
            recommendation = _recommendation_for_vm(vm, identity_evidence, recommendations)
            items.append(
                _policy_item_from_current(
                    session=session,
                    vm=vm,
                    identity_evidence=identity_evidence,
                    recommendation=recommendation,
                )
            )
    coverage = {
        "total_non_template_vms": len(items),
        "write_allowed_count": len([item for item in items if item["policy_write_allowed"]]),
        "unknown_count": len([item for item in items if item["policy"]["value"] == "unknown"]),
        "allowed_count": len([item for item in items if item["policy"]["value"] == "allowed"]),
        "restricted_count": len([item for item in items if item["policy"]["value"] == "restricted"]),
        "blocked_count": len([item for item in items if item["policy"]["value"] == "blocked"]),
        "identity_uncertain_count": len([item for item in items if item["identity_confidence"] != "high"]),
    }
    return {
        "items": sorted(items, key=lambda item: (_as_text(item["current_locator"].get("node_id")), _as_int(item["current_locator"].get("vmid")))),
        "coverage": coverage,
        "read_only": True,
        "executable": False,
        "allowed_actions": [],
        "evidence": {
            "source": calculated["source"],
            "cluster_id": calculated["cluster_id"],
            "observed_at": calculated["observed_at"],
            "policy_scope": "vm_identity_id",
        },
    }


def list_drs_policy_items(adapter: Any, *, risks: list[Any] | None = None) -> dict[str, Any]:
    """Return policy management state for current non-template VMs."""
    return _policy_model(adapter, risks=risks)


def get_drs_policy_item(adapter: Any, vm_identity_id: str, *, risks: list[Any] | None = None) -> dict[str, Any]:
    """Return one current policy management item by Gjallar VM identity ID."""
    normalized_id = _as_text(vm_identity_id)
    model = _policy_model(adapter, risks=risks)
    for item in model["items"]:
        if item.get("vm_identity_id") == normalized_id:
            return item
    raise DrsPolicyServiceError(
        404,
        "DRS_POLICY_IDENTITY_NOT_FOUND",
        "Current DRS policy item was not found for this VM identity",
        details={"vm_identity_id": normalized_id},
    )


def _payload_policy(payload: dict[str, Any]) -> str:
    policy = _as_text(payload.get("policy") or payload.get("value"))
    if policy not in POLICY_VALUES:
        raise DrsPolicyServiceError(
            422,
            "DRS_POLICY_INVALID_VALUE",
            "DRS VM policy must be one of unknown, allowed, restricted, or blocked",
            details={"allowed_values": sorted(POLICY_VALUES)},
        )
    return policy


def _payload_reason(payload: dict[str, Any], policy: str) -> str:
    reason = _as_text(payload.get("reason"))
    if policy in {"allowed", "restricted", "blocked"} and not reason:
        raise DrsPolicyServiceError(
            422,
            "DRS_POLICY_REASON_REQUIRED",
            "A non-empty reason is required when setting allowed, restricted, or blocked",
        )
    return reason


def _payload_ack(payload: dict[str, Any]) -> None:
    acknowledged = payload.get("policy_change_acknowledged")
    if acknowledged is None:
        acknowledged = payload.get("policyChangeAcknowledged")
    if acknowledged is not True:
        raise DrsPolicyServiceError(
            422,
            "DRS_POLICY_ACK_REQUIRED",
            "Manual DRS policy changes require policy_change_acknowledged=true",
        )


def _payload_expected_observation(payload: dict[str, Any]) -> dict[str, Any]:
    expected = _as_mapping(payload.get("expected_observation") or payload.get("expectedObservation"))
    missing = [field for field in GUARD_FIELDS if _as_text(expected.get(field)) == ""]
    if missing:
        raise DrsPolicyServiceError(
            422,
            "DRS_POLICY_EXPECTED_OBSERVATION_REQUIRED",
            "Expected observation guard is required for manual DRS policy changes",
            details={"missing_fields": missing},
        )
    return expected


def _validate_expected_observation(
    session: Session,
    *,
    vm_identity_id: str,
    expected: dict[str, Any],
    item: dict[str, Any],
) -> tuple[VmIdentityRecord, VmIdentityObservationRecord, dict[str, Any]]:
    identity = session.get(VmIdentityRecord, vm_identity_id)
    latest = _latest_observation(session, vm_identity_id)
    latest_high = _latest_observation(session, vm_identity_id, high_only=True)
    current = _observation_guard(latest_high)
    validation_result = {
        "status": "pass",
        "guard": "latest_high_confidence_observation",
        "expected_observation": {field: expected.get(field) for field in GUARD_FIELDS},
        "current_observation": current,
        "policy_write_allowed": item.get("policy_write_allowed") is True,
        "policy_write_blockers": item.get("policy_write_blockers") or [],
        "mismatches": [],
    }
    if identity is None:
        validation_result["status"] = "failed"
        validation_result["reason"] = "identity_missing"
        raise DrsPolicyServiceError(409, "DRS_POLICY_IDENTITY_MISSING", "VM identity is not available", details=validation_result)
    if identity.identity_status != "active":
        validation_result["status"] = "failed"
        validation_result["reason"] = "identity_not_active"
        raise DrsPolicyServiceError(409, "DRS_POLICY_IDENTITY_NOT_ACTIVE", "VM identity is not active", details=validation_result)
    if item.get("policy_write_allowed") is not True:
        validation_result["status"] = "failed"
        validation_result["reason"] = "policy_write_blocked"
        raise DrsPolicyServiceError(409, "DRS_POLICY_WRITE_BLOCKED", "Current identity evidence blocks policy writes", details=validation_result)
    if latest is None or latest_high is None or latest.observation_id != latest_high.observation_id:
        validation_result["status"] = "failed"
        validation_result["reason"] = "latest_observation_not_high_confidence"
        raise DrsPolicyServiceError(
            409,
            "DRS_POLICY_OBSERVATION_NOT_HIGH_CONFIDENCE",
            "Latest VM identity observation is not high confidence",
            details=validation_result,
        )
    mismatches = []
    for field in ("cluster_id", "node_id", "fingerprint_hash"):
        if _as_text(expected.get(field)) != _as_text(current.get(field)):
            mismatches.append(field)
    if _as_int(expected.get("vmid"), -1) != _as_int(current.get("vmid"), -2):
        mismatches.append("vmid")
    if not _same_observed_at(expected.get("observed_at"), current.get("observed_at")):
        mismatches.append("observed_at")
    if mismatches:
        validation_result["status"] = "failed"
        validation_result["reason"] = "stale_or_mismatched_expected_observation"
        validation_result["mismatches"] = mismatches
        raise DrsPolicyServiceError(
            409,
            "DRS_POLICY_EXPECTED_OBSERVATION_MISMATCH",
            "Expected observation guard does not match the latest high-confidence observation",
            details=validation_result,
        )
    return identity, latest_high, validation_result


def _policy_dict(row: VmMigrationPolicyRecord | None, *, vm_identity_id: str) -> dict[str, Any]:
    if row is None:
        return {
            "policy_id": None,
            "vm_identity_id": vm_identity_id,
            "policy": "unknown",
            "reason": "",
            "source": "default",
            "updated_by": None,
            "updated_at": None,
        }
    return {
        "policy_id": row.policy_id,
        "vm_identity_id": row.vm_identity_id,
        "policy": row.policy,
        "reason": row.reason,
        "source": row.source,
        "updated_by": row.updated_by,
        "updated_at": _iso(row.updated_at),
    }


def _find_policy(session: Session, vm_identity_id: str) -> VmMigrationPolicyRecord | None:
    return session.execute(
        select(VmMigrationPolicyRecord).where(VmMigrationPolicyRecord.vm_identity_id == vm_identity_id)
    ).scalar_one_or_none()


def update_drs_policy(
    adapter: Any,
    vm_identity_id: str,
    payload: dict[str, Any] | None,
    *,
    actor: AuthenticatedUser | dict | None,
    risks: list[Any] | None = None,
) -> dict[str, Any]:
    """Manually set one Gjallar-local DRS policy after a fresh observation guard."""
    trusted_actor = actor_evidence(actor)
    if not trusted_actor:
        raise DrsPolicyServiceError(401, "AUTH_REQUIRED", "A trusted authenticated actor is required")
    normalized_id = _as_text(vm_identity_id)
    request = _as_mapping(payload)
    _payload_ack(request)
    new_policy_value = _payload_policy(request)
    reason = _payload_reason(request, new_policy_value)
    expected = _payload_expected_observation(request)
    item = get_drs_policy_item(adapter, normalized_id, risks=risks)

    event_id: str | None = None
    audit_event_created = False
    idempotent = False
    validation_result: dict[str, Any]
    previous_policy: dict[str, Any]
    new_policy: dict[str, Any]

    with session_scope() as session:
        _, current_observation, validation_result = _validate_expected_observation(
            session,
            vm_identity_id=normalized_id,
            expected=expected,
            item=item,
        )
        row = _find_policy(session, normalized_id)
        previous_policy = _policy_dict(row, vm_identity_id=normalized_id)
        if row is None and new_policy_value == "unknown" and not reason:
            idempotent = True
            new_policy = previous_policy
        elif row is not None and row.policy == new_policy_value and row.reason == reason and row.source == "manual":
            idempotent = True
            new_policy = _policy_dict(row, vm_identity_id=normalized_id)
        else:
            if row is None:
                row = VmMigrationPolicyRecord(
                    policy_id=_policy_id(),
                    vm_identity_id=normalized_id,
                    policy=new_policy_value,
                    reason=reason,
                    source="manual",
                    updated_by=trusted_actor.get("username"),
                )
                session.add(row)
                session.flush()
            else:
                row.policy = new_policy_value
                row.reason = reason
                row.source = "manual"
                row.updated_by = trusted_actor.get("username")
                session.flush()
            event_id = _event_id()
            event = VmMigrationPolicyEventRecord(
                event_id=event_id,
                vm_identity_id=normalized_id,
                policy_id=row.policy_id,
                old_policy=previous_policy["policy"],
                new_policy=new_policy_value,
                reason=reason,
                source="manual",
                actor_user_id=trusted_actor.get("user_id"),
                actor_username=trusted_actor.get("username"),
                actor_role=trusted_actor.get("role"),
                request_id=_as_text(request.get("request_id") or request.get("requestId"), _request_id()),
                cluster_id=current_observation.cluster_id,
                node_id=current_observation.node_id,
                vmid=current_observation.vmid,
                fingerprint_hash=current_observation.fingerprint_hash,
                observed_at=current_observation.observed_at,
                expected_observation={field: expected.get(field) for field in GUARD_FIELDS},
                current_observation=_observation_guard(current_observation),
                validation_result=validation_result,
            )
            session.add(event)
            session.flush()
            audit_event_created = True
            new_policy = _policy_dict(row, vm_identity_id=normalized_id)

    updated_model = _policy_model(adapter, risks=risks)
    updated_item = next((candidate for candidate in updated_model["items"] if candidate.get("vm_identity_id") == normalized_id), None)
    recommendation_impact = None
    check_impact = None
    if updated_item is not None and updated_item.get("recommendation_id"):
        recommendation_impact = next(
            (
                recommendation
                for recommendation in _calculate_drs_model(adapter, risks=risks)["model"]["recommendations"]
                if recommendation.get("id") == updated_item.get("recommendation_id")
            ),
            None,
        )
        if recommendation_impact is not None:
            check_impact = build_drs_check_result(
                adapter,
                recommendation_impact["id"],
                risks=risks,
                payload={"recommendation": recommendation_impact},
            )
    return {
        "vm_identity_id": normalized_id,
        "previous_policy": previous_policy,
        "new_policy": new_policy,
        "actor": trusted_actor,
        "audit_event_id": event_id,
        "audit_event_created": audit_event_created,
        "idempotent": idempotent,
        "validation_result": validation_result,
        "policy_item": updated_item,
        "recommendation_impact": recommendation_impact,
        "check_impact": check_impact,
        "read_only": False,
        "executable": False,
        "allowed_actions": [],
        "proxmox_mutation_enabled": False,
        "side_effects": ["gjallar_local_policy_update"] if audit_event_created else [],
    }
