"""Infrastructure-free contracts for derived operational Insights."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from app.core.redaction import redact_secrets


INSIGHT_CATEGORIES = ("risk", "readiness", "capacity", "placement")
INSIGHT_SEVERITIES = ("critical", "warning", "info", "unknown")
INSIGHT_FINDING_STATUSES = ("active", "clear", "unknown")
INSIGHT_SECTION_STATUSES = ("ready", "attention", "unknown", "unavailable")


def _safe_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    redacted = redact_secrets(dict(value or {}))
    return dict(redacted) if isinstance(redacted, dict) else {}


@dataclass(frozen=True)
class InsightFinding:
    finding_id: str
    category: str
    severity: str
    status: str
    code: str
    title: str
    message: str
    target_type: str
    target_id: str
    source: str
    observed_at: str | None
    freshness: str
    rule_version: str
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        required = {
            "finding_id": self.finding_id,
            "code": self.code,
            "title": self.title,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "source": self.source,
            "freshness": self.freshness,
            "rule_version": self.rule_version,
        }
        missing = [name for name, value in required.items() if not str(value).strip()]
        if missing:
            raise ValueError(f"Insight finding fields are required: {', '.join(missing)}")
        if self.category not in INSIGHT_CATEGORIES:
            raise ValueError(f"Unsupported Insight category: {self.category}")
        if self.severity not in INSIGHT_SEVERITIES:
            raise ValueError(f"Unsupported Insight severity: {self.severity}")
        if self.status not in INSIGHT_FINDING_STATUSES:
            raise ValueError(f"Unsupported Insight finding status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "category": self.category,
            "severity": self.severity,
            "status": self.status,
            "code": self.code,
            "title": self.title,
            "message": self.message,
            "target": {"type": self.target_type, "id": self.target_id},
            "source": self.source,
            "observed_at": self.observed_at,
            "freshness": self.freshness,
            "rule_version": self.rule_version,
            "evidence": _safe_mapping(self.evidence),
            "read_only": True,
            "allowed_actions": [],
        }


@dataclass(frozen=True)
class InsightSection:
    category: str
    status: str
    available: bool
    source: str
    observed_at: str | None
    freshness: str
    rule_version: str
    summary: Mapping[str, Any] = field(default_factory=dict)
    findings: Sequence[InsightFinding] = field(default_factory=tuple)
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        if self.category not in INSIGHT_CATEGORIES:
            raise ValueError(f"Unsupported Insight category: {self.category}")
        if self.status not in INSIGHT_SECTION_STATUSES:
            raise ValueError(f"Unsupported Insight section status: {self.status}")
        if self.available is False and self.status != "unavailable":
            raise ValueError("Unavailable Insight sections must use status=unavailable")
        if self.available is True and self.status == "unavailable":
            raise ValueError("Available Insight sections cannot use status=unavailable")
        if not str(self.source).strip() or not str(self.freshness).strip() or not str(self.rule_version).strip():
            raise ValueError("Insight section source, freshness, and rule_version are required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "status": self.status,
            "available": self.available,
            "source": self.source,
            "observed_at": self.observed_at,
            "freshness": self.freshness,
            "rule_version": self.rule_version,
            "summary": _safe_mapping(self.summary),
            "findings": [finding.to_dict() for finding in self.findings],
            "unavailable_reason": self.unavailable_reason,
            "read_only": True,
            "allowed_actions": [],
        }


@dataclass(frozen=True)
class InsightsSnapshot:
    generated_at: str
    status: str
    connection: Mapping[str, Any]
    sections: Mapping[str, InsightSection]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "status": self.status,
            "execution_mode": "observe_only",
            "read_only": True,
            "allowed_actions": [],
            "connection": _safe_mapping(self.connection),
            "sections": {
                category: self.sections[category].to_dict()
                for category in INSIGHT_CATEGORIES
            },
        }


def unavailable_section(
    category: str,
    *,
    source: str,
    rule_version: str,
    reason: str,
    observed_at: str | None = None,
) -> InsightSection:
    return InsightSection(
        category=category,
        status="unavailable",
        available=False,
        source=source or "unavailable",
        observed_at=observed_at,
        freshness="unavailable",
        rule_version=rule_version,
        summary={"finding_count": 0, "returned_finding_count": 0, "truncated": False},
        findings=(),
        unavailable_reason=reason,
    )
