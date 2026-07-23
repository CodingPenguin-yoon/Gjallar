"""Application facade for the legacy-compatible DRS maintenance workflow."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.drs.advisor import (
    build_drs_advisor_model,
    build_drs_check_result,
    explicit_test_recommendation_id,
    find_drs_recommendation,
)
from app.drs.approval import (
    DrsApprovalBlockedError,
    create_approval_packet_and_job_intent,
)
from app.drs.execution import (
    DrsMigrationExecutionError,
    build_drs_migration_reconciliation_preview,
    execute_drs_migration_job,
    reconcile_drs_migration_job,
    require_drs_live_migration_ack,
    require_drs_reconciliation_ack,
)
from app.drs.policies import (
    DrsPolicyServiceError,
    get_drs_policy_item,
    list_drs_policy_items,
    update_drs_policy,
)

EXPLICIT_TEST_VM_ACK_FIELD = "explicit_test_vm_acknowledged"


@dataclass(frozen=True)
class DrsApplicationProviders:
    """Composition-provided dependencies used by the DRS compatibility facade."""

    inventory_adapter: Callable[[], Any]
    risks: Callable[[], list[dict[str, Any]]]
    migration_client_factory: Callable[[], Any]


@dataclass(frozen=True)
class DrsApplicationResult:
    """Transport-neutral DRS result and response metadata."""

    data: dict[str, Any]
    meta: dict[str, Any]


class DrsApplicationError(RuntimeError):
    """Transport-neutral error mapped by the DRS HTTP compatibility layer."""

    def __init__(self, status_code: int, detail: Any):
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


def _application_error(exc: Any) -> DrsApplicationError:
    return DrsApplicationError(exc.status_code, exc.to_detail())


def _explicit_test_error(code: str, message: str, **detail: Any) -> DrsApplicationError:
    return DrsApplicationError(
        409,
        {
            "code": code,
            "message": message,
            "proxmox_mutation_enabled": False,
            "side_effects": [],
            **detail,
        },
    )


def require_explicit_test_vm_ack(payload: dict[str, Any] | None) -> None:
    request_payload = payload if isinstance(payload, dict) else {}
    if request_payload.get(EXPLICIT_TEST_VM_ACK_FIELD) is not True:
        raise _explicit_test_error(
            "DRS_EXPLICIT_TEST_CANDIDATE_ACK_REQUIRED",
            f"{EXPLICIT_TEST_VM_ACK_FIELD}=true is required before DRS explicit test candidate work",
            required_acknowledgement=EXPLICIT_TEST_VM_ACK_FIELD,
        )


def _explicit_test_selection(payload: dict[str, Any] | None) -> dict[str, Any]:
    request_payload = payload if isinstance(payload, dict) else {}
    vmid = request_payload.get("vmid")
    vm_identity_id = request_payload.get("vm_identity_id")
    source_node_id = request_payload.get("source_node_id")
    target_node_id = request_payload.get("target_node_id")
    if (
        not isinstance(vmid, int)
        or isinstance(vmid, bool)
        or not isinstance(vm_identity_id, str)
        or not vm_identity_id.strip()
        or not isinstance(source_node_id, str)
        or not source_node_id.strip()
        or not isinstance(target_node_id, str)
        or not target_node_id.strip()
    ):
        raise _explicit_test_error(
            "DRS_EXPLICIT_TEST_CANDIDATE_SELECTION_REQUIRED",
            "vm_identity_id, integer vmid, source_node_id, and target_node_id are required for explicit DRS test candidate selection",
            required_fields=[
                "vm_identity_id",
                "vmid",
                "source_node_id",
                "target_node_id",
            ],
        )
    return {
        "vm_identity_id": vm_identity_id.strip(),
        "vmid": vmid,
        "source_node_id": source_node_id.strip(),
        "target_node_id": target_node_id.strip(),
    }


def _assert_explicit_test_selection_current(
    result: dict[str, Any],
    selection: dict[str, Any],
) -> None:
    recommendation = (
        result.get("recommendation")
        if isinstance(result.get("recommendation"), dict)
        else {}
    )
    identity = (
        result.get("identity_evidence")
        if isinstance(result.get("identity_evidence"), dict)
        else {}
    )
    mismatches: list[str] = []
    if recommendation.get("explicit_test_candidate") is not True:
        mismatches.append("explicit_candidate_not_current")
    if recommendation.get("vmid") != selection["vmid"]:
        mismatches.append("vmid")
    if recommendation.get("source_node_id") != selection["source_node_id"]:
        mismatches.append("source_node_id")
    if recommendation.get("target_node_id") != selection["target_node_id"]:
        mismatches.append("target_node_id")
    if identity.get("vm_identity_id") != selection["vm_identity_id"]:
        mismatches.append("vm_identity_id")
    if mismatches:
        raise _explicit_test_error(
            "DRS_EXPLICIT_TEST_CANDIDATE_SELECTION_MISMATCH",
            "current inventory no longer matches the requested explicit DRS test candidate selection",
            mismatches=mismatches,
            blockers=list(result.get("blockers") or []),
            selection=selection,
        )


def _explicit_test_check_result(
    payload: dict[str, Any] | None,
    providers: DrsApplicationProviders,
) -> tuple[dict[str, Any], dict[str, Any], str, Any]:
    require_explicit_test_vm_ack(payload)
    selection = _explicit_test_selection(payload)
    adapter = providers.inventory_adapter()
    recommendation_id = explicit_test_recommendation_id(
        vmid=selection["vmid"],
        source_node_id=selection["source_node_id"],
        target_node_id=selection["target_node_id"],
    )
    result = build_drs_check_result(
        adapter,
        recommendation_id,
        risks=providers.risks(),
        payload={"recommendation": selection},
    )
    if result is None:
        raise DrsApplicationError(404, "DRS explicit test candidate not found")
    _assert_explicit_test_selection_current(result, selection)
    return result, selection, recommendation_id, adapter


def get_summary(providers: DrsApplicationProviders) -> DrsApplicationResult:
    adapter = providers.inventory_adapter()
    return DrsApplicationResult(
        build_drs_advisor_model(adapter, risks=providers.risks()),
        {"source": adapter.source, "mode": "drs_advisor_read_only"},
    )


def list_recommendations(
    providers: DrsApplicationProviders,
) -> DrsApplicationResult:
    adapter = providers.inventory_adapter()
    return DrsApplicationResult(
        build_drs_advisor_model(adapter, risks=providers.risks()),
        {"source": adapter.source, "mode": "drs_advisor_read_only"},
    )


def get_recommendation(
    recommendation_id: str,
    providers: DrsApplicationProviders,
) -> DrsApplicationResult:
    adapter = providers.inventory_adapter()
    recommendation = find_drs_recommendation(
        adapter,
        recommendation_id,
        risks=providers.risks(),
    )
    if recommendation is None:
        raise DrsApplicationError(404, "DRS recommendation not found")
    return DrsApplicationResult(
        recommendation,
        {"source": adapter.source, "mode": "drs_advisor_read_only"},
    )


def check_recommendation(
    recommendation_id: str,
    payload: dict[str, Any] | None,
    providers: DrsApplicationProviders,
) -> DrsApplicationResult:
    adapter = providers.inventory_adapter()
    result = build_drs_check_result(
        adapter,
        recommendation_id,
        risks=providers.risks(),
        payload=payload,
    )
    if result is None:
        raise DrsApplicationError(404, "DRS recommendation not found")
    return DrsApplicationResult(
        result,
        {"source": adapter.source, "mode": "drs_advisor_read_only"},
    )


def check_explicit_test_candidate(
    payload: dict[str, Any] | None,
    providers: DrsApplicationProviders,
) -> DrsApplicationResult:
    result, selection, recommendation_id, adapter = _explicit_test_check_result(
        payload,
        providers,
    )
    return DrsApplicationResult(
        {**result, "explicit_test_selection": selection},
        {
            "source": adapter.source,
            "mode": "drs_explicit_test_candidate_read_only",
            "recommendation_id": recommendation_id,
        },
    )


def list_policies(providers: DrsApplicationProviders) -> DrsApplicationResult:
    adapter = providers.inventory_adapter()
    return DrsApplicationResult(
        list_drs_policy_items(adapter, risks=providers.risks()),
        {"source": adapter.source, "mode": "drs_policy_management_read_only"},
    )


def get_policy(
    vm_identity_id: str,
    providers: DrsApplicationProviders,
) -> DrsApplicationResult:
    adapter = providers.inventory_adapter()
    try:
        item = get_drs_policy_item(
            adapter,
            vm_identity_id,
            risks=providers.risks(),
        )
    except DrsPolicyServiceError as exc:
        raise _application_error(exc) from exc
    return DrsApplicationResult(
        item,
        {"source": adapter.source, "mode": "drs_policy_management_read_only"},
    )


def put_policy(
    vm_identity_id: str,
    payload: dict[str, Any] | None,
    *,
    actor: dict[str, Any],
    providers: DrsApplicationProviders,
) -> DrsApplicationResult:
    adapter = providers.inventory_adapter()
    try:
        result = update_drs_policy(
            adapter,
            vm_identity_id,
            payload or {},
            actor=actor,
            risks=providers.risks(),
        )
    except DrsPolicyServiceError as exc:
        raise _application_error(exc) from exc
    return DrsApplicationResult(
        result,
        {"source": adapter.source, "mode": "drs_policy_manual_update"},
    )


def create_approval_packet(
    recommendation_id: str,
    payload: dict[str, Any] | None,
    *,
    actor: dict[str, Any],
    providers: DrsApplicationProviders,
) -> DrsApplicationResult:
    adapter = providers.inventory_adapter()
    result = build_drs_check_result(
        adapter,
        recommendation_id,
        risks=providers.risks(),
        payload=payload,
    )
    if result is None:
        raise DrsApplicationError(404, "DRS recommendation not found")
    try:
        packet = create_approval_packet_and_job_intent(
            result,
            payload=payload or {},
            actor=actor,
        )
    except DrsApprovalBlockedError as exc:
        raise DrsApplicationError(409, exc.to_detail()) from exc
    return DrsApplicationResult(
        packet,
        {
            "source": adapter.source,
            "mode": "drs_local_approval_packet_no_mutation",
        },
    )


def create_explicit_test_approval_packet(
    payload: dict[str, Any] | None,
    *,
    actor: dict[str, Any],
    providers: DrsApplicationProviders,
) -> DrsApplicationResult:
    result, selection, recommendation_id, adapter = _explicit_test_check_result(
        payload,
        providers,
    )
    if result.get("would_be_executable") is not True:
        raise DrsApplicationError(
            409,
            {
                "code": "DRS_APPROVAL_GATE_BLOCKED",
                "message": "DRS explicit test candidate approval packet cannot be created because final pre-check gates are blocked",
                "approval_readiness": result.get("approval_readiness"),
                "proxmox_mutation_enabled": False,
                "side_effects": [],
            },
        )
    try:
        packet = create_approval_packet_and_job_intent(
            result,
            payload=payload or {},
            actor=actor,
        )
    except DrsApprovalBlockedError as exc:
        raise DrsApplicationError(409, exc.to_detail()) from exc
    return DrsApplicationResult(
        {**packet, "explicit_test_selection": selection},
        {
            "source": adapter.source,
            "mode": "drs_explicit_test_local_approval_packet_no_mutation",
            "recommendation_id": recommendation_id,
        },
    )


async def execute_migration_job(
    job_id: str,
    payload: dict[str, Any] | None,
    *,
    actor: dict[str, Any] | None,
    providers: DrsApplicationProviders,
) -> DrsApplicationResult:
    try:
        require_drs_live_migration_ack(job_id, payload)
        result = await asyncio.to_thread(
            execute_drs_migration_job,
            job_id,
            actor=actor,
            inventory_adapter=providers.inventory_adapter(),
            payload=payload,
            risks=providers.risks(),
            client_factory=providers.migration_client_factory,
        )
    except DrsMigrationExecutionError as exc:
        raise _application_error(exc) from exc
    return DrsApplicationResult(
        result,
        {"mode": "drs_live_migration_execution"},
    )


async def reconcile_migration_job(
    job_id: str,
    payload: dict[str, Any] | None,
    *,
    actor: dict[str, Any] | None,
    providers: DrsApplicationProviders,
) -> DrsApplicationResult:
    try:
        require_drs_reconciliation_ack(job_id, payload)
        result = await asyncio.to_thread(
            reconcile_drs_migration_job,
            job_id,
            actor=actor,
            payload=payload,
            client_factory=providers.migration_client_factory,
        )
    except DrsMigrationExecutionError as exc:
        raise _application_error(exc) from exc
    return DrsApplicationResult(
        result,
        {"mode": "drs_local_reconciliation_follow_up"},
    )


async def preview_migration_reconciliation(
    job_id: str,
    payload: dict[str, Any] | None,
    *,
    actor: dict[str, Any] | None,
    providers: DrsApplicationProviders,
) -> DrsApplicationResult:
    _ = payload
    try:
        result = await asyncio.to_thread(
            build_drs_migration_reconciliation_preview,
            job_id,
            actor=actor,
            client_factory=providers.migration_client_factory,
        )
    except DrsMigrationExecutionError as exc:
        raise _application_error(exc) from exc
    return DrsApplicationResult(
        result,
        {"mode": "drs_reconciliation_preview_read_only"},
    )
