"""Durable single-dispatch flow for synchronous stopped-VM config changes.

Feature services own target rules, review, comparison and errors. This flow owns
idempotency, lock admission, dispatch evidence and GET-only verification.
"""
from abc import ABC, abstractmethod

from app.operations.core.domain import OperationActor, OperationSpec, operation_digest
from app.operations.recovery.domain import RecoveryLease


class ConfigChangeService(ABC):
    def __init__(self, *, client, admission, operations, recovery, cluster_id):
        self.client, self.admission = client, admission
        self.operations, self.recovery, self.cluster_id = operations, recovery, cluster_id

    @abstractmethod
    def review(self, *, node_id, vmid): ...

    @abstractmethod
    def observe(self, *, node_id, vmid): ...

    @abstractmethod
    def matches(self, observed, requested, before): ...

    def execute(self, *, node_id, vmid, request, actor):
        self.validate_target(node_id, vmid)
        target = {"node_id": node_id, "vmid": vmid, "name": request.expected_name}
        identity = operation_digest({"cluster_id": self.cluster_id, "node_id": node_id, "vmid": vmid,
                                     "idempotency_key": request.idempotency_key})
        operation_id = self.operation_prefix + identity.split(":", 1)[1]
        intent = {"target": target, **request.model_dump()}
        intent_digest = operation_digest(intent)
        existing = self.operations.get(operation_id)
        if existing is not None:
            if existing.intent_digest != intent_digest:
                raise self.error_type(self.error_prefix + "IDEMPOTENCY_CONFLICT", "같은 요청 ID에 다른 변경을 사용할 수 없습니다.")
            return self.result(existing, replay=True)
        # No DB mutation or external write until the reviewed target is valid.
        before = self.review(node_id=node_id, vmid=vmid)["observed_before"]
        self.check_expected(before, request)
        spec = OperationSpec(
            operation_id=operation_id, operation_type=self.operation_type, execution_mode="managed_api",
            target_type="proxmox_vm", target_id=f"vmid:{vmid}", idempotency_key=identity,
            intent_digest=intent_digest, plan_digest=intent_digest, actor=OperationActor.from_mapping(actor),
            details={"target": target, "observed_before": before, "requested": request.model_dump(),
                     "mutation_dispatched": False, "dispatch_acknowledged": False},
        )
        operation, lease = self.admission.prepare(spec, cluster_id=self.cluster_id, vmid=vmid)
        if lease is None:
            return self.result(operation, replay=True)
        try:
            # Repeat the direct reads after the shared target lock is acquired.
            latest = self.review(node_id=node_id, vmid=vmid)["observed_before"]
            self.check_expected(latest, request)
        except self.error_type as exc:
            operation, _ = self.recovery.commit_observation(
                lease, next_status="blocked", event_type=self.event_prefix + "precheck_blocked", stage="precheck",
                details_patch={"failure_code": exc.code}, expected_statuses=["planned"],
                recovery_status="completed", release_target_lock=True,
            )
            raise self.error_type(exc.code, str(exc), exc.status_code, {**exc.details, "operation_id": operation_id}) from None
        operation, item = self.recovery.commit_observation(
            lease, next_status="dispatching", event_type=self.event_prefix + "dispatching", stage="dispatch",
            details_patch={"mutation_dispatched": True}, expected_statuses=["planned"], recovery_status="leased",
        )
        lease = RecoveryLease(item=item, token=lease.token)
        try:
            self.client.apply(node_id=node_id, vmid=vmid, request=request)
        except self.error_type as exc:
            operation, _ = self.recovery.commit_observation(
                lease, next_status="needs_reconciliation", event_type=self.event_prefix + "dispatch_unknown", stage="reconciliation",
                details_patch={"failure_code": exc.code}, expected_statuses=["dispatching"],
                recovery_status="paused", error_code=self.error_prefix + "DISPATCH_UNKNOWN",
            )
            return self.result(operation)
        operation, item = self.recovery.commit_observation(
            lease, next_status="running", event_type=self.event_prefix + "dispatch_acknowledged", stage="post_check",
            details_patch={"dispatch_acknowledged": True}, expected_statuses=["dispatching"], recovery_status="leased",
        )
        self.verify(RecoveryLease(item=item, token=lease.token), operation)
        return self.result(self.operations.get(operation_id))

    def verify(self, lease, operation):
        target = operation.details["target"]
        requested = operation.details["requested"]
        observed = None
        error_code = None
        try:
            observed = self.observe(node_id=target["node_id"], vmid=target["vmid"])
        except self.error_type as exc:
            error_code = exc.code
        matches = observed is not None and self.matches(observed, requested, operation.details["observed_before"])
        if operation.details.get("dispatch_acknowledged") is not True or not matches:
            self.recovery.commit_observation(
                lease, next_status=None if operation.status == "needs_reconciliation" else "needs_reconciliation",
                event_type=self.event_prefix + "result_unconfirmed", stage="reconciliation",
                details_patch={"observed_after": observed, "failure_code": error_code or self.error_prefix + "RESULT_UNCONFIRMED"},
                expected_statuses=[operation.status], expected_operation_version=operation.version,
                expected_operation_checksum=operation.last_event_checksum,
                recovery_status="paused", error_code=error_code or self.error_prefix + "RESULT_UNCONFIRMED",
            )
            return "paused"
        if operation.status != "verifying":
            operation, item = self.recovery.commit_observation(
                lease, next_status="verifying", event_type=self.event_prefix + "state_observed", stage="post_check",
                details_patch={"observed_after": observed}, expected_statuses=[operation.status],
                expected_operation_version=operation.version, expected_operation_checksum=operation.last_event_checksum,
                recovery_status="leased",
            )
            lease = RecoveryLease(item=item, token=lease.token)
        self.recovery.commit_observation(
            lease, next_status="succeeded", event_type=self.event_prefix + "verified", stage="completed",
            details_patch={"observed_after": observed, "failure_code": None}, expected_statuses=["verifying"],
            expected_operation_version=operation.version, expected_operation_checksum=operation.last_event_checksum,
            recovery_status="completed", release_target_lock=True,
        )
        return "succeeded"

    @staticmethod
    def result(operation, replay=False):
        return {"operation_id": operation.operation_id, "status": operation.status,
                "operation": {"operation_id": operation.operation_id, "status": operation.status},
                "target": operation.details["target"], "observed_before": operation.details.get("observed_before"),
                "observed_after": operation.details.get("observed_after"), "requested": operation.details["requested"],
                "failure_code": operation.details.get("failure_code"), "idempotent_replay": replay,
                "automatic_retry_allowed": False}
