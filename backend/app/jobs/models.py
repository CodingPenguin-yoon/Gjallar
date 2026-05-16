"""Dataclass records for the minimum Gjallar job/artifact substrate."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class JobRecord:
    """Minimum persisted job fields required before preflight/plan work."""

    job_id: str
    job_type: str
    status: str
    target_id: str
    risk_level: str
    started_at: str
    finished_at: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ArtifactRecord:
    """Metadata for a Gjallar job artifact."""

    artifact_id: str
    job_id: str
    type: str
    path: str
    checksum: str
    created_at: str
    content_type: str = "application/octet-stream"
    size_bytes: int = 0
    storage_backend: str = "db"

    def __post_init__(self) -> None:
        if not self.checksum.startswith("sha256:"):
            raise ValueError("artifact checksum must use the sha256:<hex> format")
        digest = self.checksum.removeprefix("sha256:")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest.lower()):
            raise ValueError("artifact checksum must contain a 64-character SHA-256 hex digest")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ApprovalRecord:
    """Minimum approval metadata tied to real plan/review artifacts."""

    job_id: str
    plan_artifact_id: str
    review_summary_checksum: str
    yellow_risk_acknowledged: bool
    decision: str

    def __post_init__(self) -> None:
        if not self.review_summary_checksum.startswith("sha256:"):
            raise ValueError("review summary checksum must use the sha256:<hex> format")

    def to_dict(self) -> dict:
        return asdict(self)
