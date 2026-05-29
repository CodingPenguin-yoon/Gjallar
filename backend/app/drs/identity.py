"""DRS VM identity resolution from read-only inventory evidence."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import VmIdentityObservationRecord, VmIdentityRecord, VmMigrationPolicyRecord
from app.db.session import session_scope

DEFAULT_CLUSTER_ID = "gjallar-mvp"
UNKNOWN_POLICY_EVIDENCE = {
    "policy": "unknown",
    "source": "default",
    "reason": "No DRS migration policy has been recorded for this VM identity.",
    "updated_by": None,
    "policy_id": None,
}
_SMBIOS_UUID_PATTERN = re.compile(r"(?:^|[,;\s])uuid=([0-9a-fA-F-]{8,40})(?:$|[,;\s])")
_UUID_TEXT_PATTERN = re.compile(r"^[0-9a-fA-F-]{8,40}$")
_MAC_ADDRESS_PATTERN = re.compile(r"^[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}$")


@dataclass(frozen=True)
class IdentityResolution:
    vm_identity_id: str | None
    stable_fingerprint: str
    match_confidence: str
    match_reason: str
    identity_status: str
    fingerprint_components: dict[str, Any]
    source: str
    conflict_signal: bool = False

    def to_evidence(self) -> dict[str, Any]:
        return {
            "vm_identity_id": self.vm_identity_id,
            "stable_fingerprint": self.stable_fingerprint,
            "match_confidence": self.match_confidence,
            "match_reason": self.match_reason,
            "identity_status": self.identity_status,
            "fingerprint_components": self.fingerprint_components,
            "source": self.source,
            "conflict_signal": self.conflict_signal,
            "blocking": self.match_confidence != "high" or self.conflict_signal,
        }


def _field(source: Any, *names: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        for name in names:
            if name in source:
                return source[name]
        return default
    for name in names:
        if hasattr(source, name):
            return getattr(source, name)
    return default


def _as_text(value: Any, fallback: str = "") -> str:
    text = str(value if value is not None else "").strip()
    return text or fallback


def _as_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    text = _as_text(value)
    if text:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _normalize_smbios_uuid(value: Any) -> str:
    text = _as_text(value).lower()
    if not text:
        return ""
    match = _SMBIOS_UUID_PATTERN.search(text)
    if match is not None:
        return match.group(1).strip().lower()
    if _UUID_TEXT_PATTERN.fullmatch(text):
        return text
    return ""


def _normalize_uuidish(value: Any) -> str:
    text = _as_text(value).lower()
    return text if _UUID_TEXT_PATTERN.fullmatch(text) else ""


def _normalize_mac(value: Any) -> str:
    text = _as_text(value).lower()
    return text if _MAC_ADDRESS_PATTERN.fullmatch(text) else ""


def _unique_text(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _as_text(value)
        if not text or text.lower() == "unknown":
            continue
        normalized = text.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _mac_addresses(vm: Any) -> list[str]:
    direct = [_normalize_mac(value) for value in _as_list(_field(vm, "mac_addresses", "macAddresses", default=[]))]
    nic_values = [
        _normalize_mac(_field(item, "mac_address", "macAddress", "mac", default=""))
        for item in _as_list(_field(vm, "nic_bridge_evidence", "nicBridgeEvidence", default=[]))
    ]
    return _unique_text([*direct, *nic_values])


def _disk_volume_ids(vm: Any) -> list[str]:
    direct = _unique_text(_as_list(_field(vm, "disk_volume_ids", "diskVolumeIds", default=[])))
    if direct:
        return direct
    return _unique_text(
        [
            _field(disk, "volume_id", "volumeId", default="")
            for disk in _as_list(_field(vm, "disks", default=[]))
        ]
    )


def fingerprint_components_for_vm(
    vm: Any,
    *,
    cluster_id: str,
) -> dict[str, Any]:
    """Return compact fingerprint components without raw Proxmox config."""
    smbios1 = _as_text(_field(vm, "smbios1", default=""))
    vmgenid = _as_text(_field(vm, "vmgenid", default=""))
    vmid = _as_int(_field(vm, "vmid", "vm_id", "id", default=0))
    node_id = _as_text(_field(vm, "node_id", "nodeId", "node", default="unknown"), "unknown")
    name = _as_text(_field(vm, "name", "vm_name", default=f"vm-{vmid}"), f"vm-{vmid}")
    return {
        "smbios1_uuid": _normalize_smbios_uuid(smbios1),
        "vmgenid": _normalize_uuidish(vmgenid),
        "mac_addresses": _mac_addresses(vm),
        "disk_volume_ids": _disk_volume_ids(vm),
        "locator": {
            "cluster_id": _as_text(cluster_id, DEFAULT_CLUSTER_ID),
            "node_id": node_id,
            "vmid": vmid,
            "name": name,
        },
    }


def stable_fingerprint_for_components(components: dict[str, Any]) -> str:
    stable_payload = {
        "smbios1_uuid": _as_text(components.get("smbios1_uuid")),
        "vmgenid": _as_text(components.get("vmgenid")),
        "disk_volume_ids": _unique_text(_as_list(components.get("disk_volume_ids"))),
    }
    if not any([stable_payload["smbios1_uuid"], stable_payload["vmgenid"], stable_payload["disk_volume_ids"]]):
        return ""
    encoded = json.dumps(stable_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _identity_id() -> str:
    return f"vmid-{uuid.uuid4().hex}"


def _observation_id() -> str:
    return f"vmobs-{uuid.uuid4().hex}"


def _policy_id() -> str:
    return f"vmpol-{uuid.uuid4().hex}"


def _identity_by_fingerprint(
    session: Session,
    *,
    cluster_id: str,
    stable_fingerprint: str,
) -> VmIdentityRecord | None:
    return session.execute(
        select(VmIdentityRecord).where(
            VmIdentityRecord.cluster_id == cluster_id,
            VmIdentityRecord.stable_fingerprint == stable_fingerprint,
        )
    ).scalar_one_or_none()


def _latest_vmid_observation(
    session: Session,
    *,
    cluster_id: str,
    vmid: int,
) -> VmIdentityObservationRecord | None:
    return session.execute(
        select(VmIdentityObservationRecord)
        .where(
            VmIdentityObservationRecord.cluster_id == cluster_id,
            VmIdentityObservationRecord.vmid == vmid,
        )
        .order_by(desc(VmIdentityObservationRecord.observed_at))
        .limit(1)
    ).scalar_one_or_none()


def _weak_resolution(
    *,
    vm: Any,
    cluster_id: str,
    source: str,
    components: dict[str, Any],
    confidence: str,
    reason: str,
    conflict: bool = False,
) -> IdentityResolution:
    del vm, cluster_id
    return IdentityResolution(
        vm_identity_id=None,
        stable_fingerprint="",
        match_confidence=confidence,
        match_reason=reason,
        identity_status="unknown",
        fingerprint_components=components,
        source=source,
        conflict_signal=conflict,
    )


def _record_observation(
    session: Session,
    *,
    identity: VmIdentityRecord,
    vm: Any,
    cluster_id: str,
    observed_at: datetime,
    source: str,
    components: dict[str, Any],
    confidence: str,
    reason: str,
) -> None:
    session.add(
        VmIdentityObservationRecord(
            observation_id=_observation_id(),
            vm_identity_id=identity.vm_identity_id,
            observed_at=observed_at,
            cluster_id=cluster_id,
            node_id=_as_text(_field(vm, "node_id", "nodeId", "node", default="unknown"), "unknown"),
            vmid=_as_int(_field(vm, "vmid", "vm_id", "id", default=0)),
            name=_as_text(_field(vm, "name", "vm_name", default="unknown"), "unknown"),
            power_state=_as_text(_field(vm, "status", "power_state", "powerState", default="unknown"), "unknown"),
            template=_as_bool(_field(vm, "template", default=False)),
            fingerprint_hash=identity.stable_fingerprint,
            fingerprint_components=components,
            match_confidence=confidence,
            match_reason=reason,
            source=source,
        )
    )


def resolve_vm_identity(
    session: Session,
    vm: Any,
    *,
    cluster_id: str = DEFAULT_CLUSTER_ID,
    observed_at: datetime | str | None = None,
    source: str = "proxmox_inventory",
    duplicate_fingerprints: set[str] | None = None,
) -> IdentityResolution:
    """Resolve and record a VM identity only from curated inventory fields."""
    normalized_cluster_id = _as_text(cluster_id, DEFAULT_CLUSTER_ID)
    seen_at = _parse_datetime(observed_at)
    components = fingerprint_components_for_vm(vm, cluster_id=normalized_cluster_id)
    stable_fingerprint = stable_fingerprint_for_components(components)
    locator = components["locator"]
    vmid = _as_int(locator.get("vmid"), 0)
    duplicate_fingerprints = duplicate_fingerprints or set()

    if not stable_fingerprint:
        if components["mac_addresses"]:
            return _weak_resolution(
                vm=vm,
                cluster_id=normalized_cluster_id,
                source=source,
                components=components,
                confidence="medium",
                reason="supporting_only_no_stable_fingerprint",
            )
        return _weak_resolution(
            vm=vm,
            cluster_id=normalized_cluster_id,
            source=source,
            components=components,
            confidence="unknown",
            reason="no_usable_stable_fingerprint",
        )

    if stable_fingerprint in duplicate_fingerprints:
        return _weak_resolution(
            vm=vm,
            cluster_id=normalized_cluster_id,
            source=source,
            components=components,
            confidence="low",
            reason="duplicate_current_stable_fingerprint",
            conflict=True,
        )

    latest_locator = _latest_vmid_observation(
        session,
        cluster_id=normalized_cluster_id,
        vmid=vmid,
    )
    if latest_locator is not None and latest_locator.fingerprint_hash != stable_fingerprint:
        return _weak_resolution(
            vm=vm,
            cluster_id=normalized_cluster_id,
            source=source,
            components=components,
            confidence="low",
            reason="locator_conflicts_with_existing_identity",
            conflict=True,
        )

    identity = _identity_by_fingerprint(
        session,
        cluster_id=normalized_cluster_id,
        stable_fingerprint=stable_fingerprint,
    )
    reason = "stable_fingerprint_matched_existing_identity"
    if identity is None:
        reason = "first_high_confidence_stable_fingerprint"
        identity = VmIdentityRecord(
            vm_identity_id=_identity_id(),
            cluster_id=normalized_cluster_id,
            stable_fingerprint=stable_fingerprint,
            identity_status="active",
            first_seen_at=seen_at,
            last_seen_at=seen_at,
        )
        session.add(identity)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            identity = _identity_by_fingerprint(
                session,
                cluster_id=normalized_cluster_id,
                stable_fingerprint=stable_fingerprint,
            )
            if identity is None:
                raise
            reason = "stable_fingerprint_matched_existing_identity"
    else:
        identity.last_seen_at = seen_at

    if identity.identity_status != "active":
        _record_observation(
            session,
            identity=identity,
            vm=vm,
            cluster_id=normalized_cluster_id,
            observed_at=seen_at,
            source=source,
            components=components,
            confidence="low",
            reason=f"identity_status_{identity.identity_status}",
        )
        return IdentityResolution(
            vm_identity_id=identity.vm_identity_id,
            stable_fingerprint=stable_fingerprint,
            match_confidence="low",
            match_reason=f"identity_status_{identity.identity_status}",
            identity_status=identity.identity_status,
            fingerprint_components=components,
            source=source,
            conflict_signal=True,
        )

    _record_observation(
        session,
        identity=identity,
        vm=vm,
        cluster_id=normalized_cluster_id,
        observed_at=seen_at,
        source=source,
        components=components,
        confidence="high",
        reason=reason,
    )
    return IdentityResolution(
        vm_identity_id=identity.vm_identity_id,
        stable_fingerprint=stable_fingerprint,
        match_confidence="high",
        match_reason=reason,
        identity_status=identity.identity_status,
        fingerprint_components=components,
        source=source,
        conflict_signal=False,
    )


def resolve_inventory_identities(
    vms: list[Any],
    *,
    cluster_id: str = DEFAULT_CLUSTER_ID,
    observed_at: datetime | str | None = None,
    source: str = "proxmox_inventory",
) -> dict[tuple[str, int], IdentityResolution]:
    """Resolve current inventory VMs in one transaction."""
    normalized_cluster_id = _as_text(cluster_id, DEFAULT_CLUSTER_ID)
    fingerprint_counts: dict[str, int] = {}
    for vm in vms:
        components = fingerprint_components_for_vm(vm, cluster_id=normalized_cluster_id)
        stable_fingerprint = stable_fingerprint_for_components(components)
        if stable_fingerprint:
            fingerprint_counts[stable_fingerprint] = fingerprint_counts.get(stable_fingerprint, 0) + 1
    duplicates = {
        stable_fingerprint
        for stable_fingerprint, count in fingerprint_counts.items()
        if count > 1
    }
    result: dict[tuple[str, int], IdentityResolution] = {}
    with session_scope() as session:
        for vm in vms:
            key = (
                _as_text(_field(vm, "node_id", "nodeId", "node", default="unknown"), "unknown"),
                _as_int(_field(vm, "vmid", "vm_id", "id", default=0)),
            )
            result[key] = resolve_vm_identity(
                session,
                vm,
                cluster_id=normalized_cluster_id,
                observed_at=observed_at,
                source=source,
                duplicate_fingerprints=duplicates,
            )
    return result


def policy_evidence_for_identity(
    session: Session,
    vm_identity_id: str | None,
) -> dict[str, Any]:
    if not vm_identity_id:
        return dict(UNKNOWN_POLICY_EVIDENCE)
    policy = session.execute(
        select(VmMigrationPolicyRecord).where(VmMigrationPolicyRecord.vm_identity_id == vm_identity_id)
    ).scalar_one_or_none()
    if policy is None:
        return {**UNKNOWN_POLICY_EVIDENCE, "vm_identity_id": vm_identity_id}
    return {
        "policy_id": policy.policy_id,
        "vm_identity_id": policy.vm_identity_id,
        "policy": policy.policy,
        "reason": policy.reason,
        "source": policy.source,
        "updated_by": policy.updated_by,
        "updated_at": policy.updated_at.isoformat() if policy.updated_at else None,
    }


def migration_policy_evidence(
    identity_evidence: dict[str, Any],
) -> dict[str, Any]:
    """Return policy evidence with missing rows treated as default unknown."""
    with session_scope() as session:
        return policy_evidence_for_identity(session, identity_evidence.get("vm_identity_id"))


def create_migration_policy(
    session: Session,
    *,
    vm_identity_id: str,
    policy: str,
    reason: str = "",
    source: str = "manual",
    updated_by: str | None = None,
) -> VmMigrationPolicyRecord:
    """Small test/support helper for the one-policy-per-identity contract."""
    row = VmMigrationPolicyRecord(
        policy_id=_policy_id(),
        vm_identity_id=vm_identity_id,
        policy=policy,
        reason=reason,
        source=source,
        updated_by=updated_by,
    )
    session.add(row)
    return row
