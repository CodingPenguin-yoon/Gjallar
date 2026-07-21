"""Single-container target operation locks.

The lock is intentionally file-backed and target-keyed. It prevents a second
mutation for the same target while the first operation is running or retained
for manual reconciliation. Stale lock cleanup is deliberately not automatic.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.operations.locks.domain import DurableTargetLock, DurableTargetLockBusy
from app.operations.locks.infrastructure.repository import SqlAlchemyDurableTargetLockRepository


class TargetOperationLockBusy(RuntimeError):
    """Raised when another operation already holds the target lock."""

    def __init__(
        self,
        *,
        target_type: str,
        target_id: str,
        owner_id: str,
        path: Path,
        existing: dict[str, Any] | None = None,
    ) -> None:
        self.target_type = target_type
        self.target_id = target_id
        self.owner_id = owner_id
        self.path = path
        self.existing = dict(existing or {})
        super().__init__(f"Target operation lock is busy: {target_type}:{target_id}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_type": self.target_type,
            "target_id": self.target_id,
            "requested_owner_id": self.owner_id,
            "existing": self.existing,
        }


@dataclass(frozen=True)
class TargetOperationLockHandle:
    target_type: str
    target_id: str
    owner_id: str
    lock_id: str
    path: Path
    acquired_at: str
    durable: DurableTargetLock | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "target_type": self.target_type,
            "target_id": self.target_id,
            "owner_id": self.owner_id,
            "lock_id": self.lock_id,
            "acquired_at": self.acquired_at,
        }
        if self.durable is not None:
            result["durable"] = self.durable.to_dict()
        return result


def _safe_segment(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value)).strip("-")
    return safe[:80] or "target"


def _normalized(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _target_operation_lock_path(*, target_type: str, target_id: str) -> Path:
    normalized_type = _normalized(target_type) or "target"
    normalized_id = _normalized(target_id) or "unknown"
    digest = hashlib.sha256(f"{normalized_type}:{normalized_id}".encode("utf-8")).hexdigest()
    return (
        Path(tempfile.gettempdir())
        / "gjallar-runtime"
        / "target-operation-locks"
        / f"{_safe_segment(normalized_type)}-{digest}.lock"
    )


def _read_lock_metadata(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    return dict(payload) if isinstance(payload, dict) else {"raw": payload}


def acquire_target_operation_lock(
    target_type: str,
    target_id: str,
    owner_id: str,
    *,
    operation_type: str | None = None,
    cluster_id: str | None = None,
) -> TargetOperationLockHandle:
    """Acquire an exclusive lock for one mutation target.

    The lock path is derived only from ``target_type`` and ``target_id``. If the
    file already exists, acquisition fails; callers must not auto-remove it as a
    stale lock because it may represent a reconciliation-required mutation.
    """

    normalized_type = _normalized(target_type) or "target"
    normalized_id = _normalized(target_id) or "unknown"
    normalized_owner = _normalized(owner_id) or "unknown"
    path = _target_operation_lock_path(target_type=normalized_type, target_id=normalized_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    durable: DurableTargetLock | None = None
    vmid_match = re.fullmatch(r"vmid:(\d+)", normalized_id)
    if operation_type and normalized_type == "proxmox_vm" and vmid_match:
        durable_repository = SqlAlchemyDurableTargetLockRepository()
        normalized_cluster = _normalized(cluster_id) or _normalized(os.getenv("GJALLAR_CLUSTER_ID")) or "gjallar-mvp"
        try:
            durable = durable_repository.acquire(
                operation_type=operation_type,
                cluster_id=normalized_cluster,
                vmid=int(vmid_match.group(1)),
                owner_id=normalized_owner,
                reason=f"{operation_type}_dispatch",
            )
        except DurableTargetLockBusy as exc:
            raise TargetOperationLockBusy(
                target_type=normalized_type,
                target_id=normalized_id,
                owner_id=normalized_owner,
                path=path,
                existing=exc.existing,
            ) from exc

    acquired_at = datetime.now(timezone.utc).isoformat()
    lock_id = f"targetlock-{uuid.uuid4().hex}"
    payload = {
        "target_type": normalized_type,
        "target_id": normalized_id,
        "owner_id": normalized_owner,
        "lock_id": lock_id,
        "acquired_at": acquired_at,
    }
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError as exc:
        if durable is not None:
            SqlAlchemyDurableTargetLockRepository().release(durable, reason="compatibility_file_lock_busy")
        if isinstance(exc, FileExistsError):
            raise TargetOperationLockBusy(
                target_type=normalized_type,
                target_id=normalized_id,
                owner_id=normalized_owner,
                path=path,
                existing=_read_lock_metadata(path),
            ) from exc
        raise

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as lock_file:
            json.dump(payload, lock_file, ensure_ascii=False, sort_keys=True)
    except Exception:
        path.unlink(missing_ok=True)
        if durable is not None:
            SqlAlchemyDurableTargetLockRepository().release(durable, reason="compatibility_file_lock_write_failed")
        raise

    return TargetOperationLockHandle(
        target_type=normalized_type,
        target_id=normalized_id,
        owner_id=normalized_owner,
        lock_id=lock_id,
        path=path,
        acquired_at=acquired_at,
        durable=durable,
    )


def release_target_operation_lock(handle: TargetOperationLockHandle) -> None:
    """Release a target lock only if it still belongs to this handle."""

    metadata = _read_lock_metadata(handle.path)
    if metadata and (
        metadata.get("lock_id") != handle.lock_id
        or metadata.get("owner_id") != handle.owner_id
        or metadata.get("target_type") != handle.target_type
        or metadata.get("target_id") != handle.target_id
    ):
        return
    try:
        handle.path.unlink()
    except FileNotFoundError:
        pass
    if handle.durable is not None:
        SqlAlchemyDurableTargetLockRepository().release(handle.durable, reason="verified_operation_completed")


def get_target_operation_lock(target_type: str, target_id: str) -> dict[str, Any] | None:
    """Return public lock evidence without exposing the local filesystem path."""

    normalized_type = _normalized(target_type) or "target"
    normalized_id = _normalized(target_id) or "unknown"
    vmid_match = re.fullmatch(r"vmid:(\d+)", normalized_id)
    if normalized_type == "proxmox_vm" and vmid_match:
        cluster_id = _normalized(os.getenv("GJALLAR_CLUSTER_ID")) or "gjallar-mvp"
        durable = SqlAlchemyDurableTargetLockRepository().current(
            cluster_id=cluster_id,
            vmid=int(vmid_match.group(1)),
        )
        if durable is not None:
            return {
                "target_type": normalized_type,
                "target_id": normalized_id,
                "owner_id": durable.owner_id,
                "lock_id": durable.lock_id,
                "acquired_at": durable.created_at.isoformat(),
                "durable": durable.to_dict(),
            }
    path = _target_operation_lock_path(target_type=normalized_type, target_id=normalized_id)
    if not path.exists():
        return None
    metadata = _read_lock_metadata(path)
    return {
        key: metadata.get(key)
        for key in ("target_type", "target_id", "owner_id", "lock_id", "acquired_at")
        if metadata.get(key) is not None
    }


def release_target_operation_lock_for_owner(target_type: str, target_id: str, owner_id: str) -> bool:
    """Release a retained lock only when its persisted owner still matches."""

    normalized_type = _normalized(target_type) or "target"
    normalized_id = _normalized(target_id) or "unknown"
    normalized_owner = _normalized(owner_id) or "unknown"
    path = _target_operation_lock_path(target_type=normalized_type, target_id=normalized_id)
    metadata = _read_lock_metadata(path)
    file_matches = bool(metadata) and not (
        metadata.get("target_type") != normalized_type
        or metadata.get("target_id") != normalized_id
        or metadata.get("owner_id") != normalized_owner
    )
    file_released = False
    if file_matches:
        try:
            path.unlink()
            file_released = True
        except FileNotFoundError:
            pass
    durable_released = False
    vmid_match = re.fullmatch(r"vmid:(\d+)", normalized_id)
    if normalized_type == "proxmox_vm" and vmid_match:
        cluster_id = _normalized(os.getenv("GJALLAR_CLUSTER_ID")) or "gjallar-mvp"
        durable_released = SqlAlchemyDurableTargetLockRepository().release_owned(
            cluster_id=cluster_id,
            vmid=int(vmid_match.group(1)),
            owner_id=normalized_owner,
            reason="verified_operation_completed",
        )
    return file_released or durable_released
