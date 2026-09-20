"""One asynchronous PVE task with durable task binding and observation-only recovery."""
from abc import ABC, abstractmethod

from app.operations.core.domain import OperationActor, OperationSpec, operation_digest
from app.operations.recovery.domain import RecoveryLease


class TaskChangeService(ABC):
    def __init__(self, *, client, admission, operations, recovery, cluster_id):
        self.client, self.admission = client, admission
        self.operations, self.recovery, self.cluster_id = operations, recovery, cluster_id

    @abstractmethod
    def review(self, **kwargs): ...

    @abstractmethod
    def matches(self, after, requested, before): ...

    def target(self, *, node_id, vmid, request):
        return {"node_id": node_id, "vmid": vmid, "name": request.expected_name}

    def extra_details(self, *, node_id, vmid, request):
        return {}

    def review_request(self, *, node_id, vmid, request):
        return self.review(node_id=node_id, vmid=vmid)

    def admit(self, spec, *, node_id, vmid, request):
        return self.admission.prepare(spec, cluster_id=self.cluster_id, vmid=vmid)

    def observe_result(self, operation):
        target = operation.details["target"]
        return self.client.read(node_id=target["node_id"], vmid=target["vmid"])

    def dispatch(self, *, node_id, vmid, request, operation):
        return self.client.apply(node_id=node_id, vmid=vmid, request=request)

    def execute(self, *, node_id, vmid, request, actor):
        target = self.target(node_id=node_id, vmid=vmid, request=request)
        identity = operation_digest({"cluster_id": self.cluster_id, "node_id": node_id, "vmid": vmid,
                                     "idempotency_key": request.idempotency_key})
        operation_id = self.operation_prefix + identity.split(":", 1)[1]
        intent_digest = operation_digest({"target": target, **request.model_dump()})
        existing = self.operations.get(operation_id)
        if existing:
            if existing.intent_digest != intent_digest:
                raise self.error_type(self.error_prefix + "IDEMPOTENCY_CONFLICT", "같은 요청 ID에 다른 변경을 사용할 수 없습니다.")
            return self.result(existing, replay=True)
        before = self.review_request(node_id=node_id, vmid=vmid, request=request)["observed_before"]
        self.check_expected(before, request)
        spec = OperationSpec(operation_id=operation_id, operation_type=self.operation_type, execution_mode="managed_api",
            target_type="proxmox_vm", target_id=f"vmid:{target['vmid']}", idempotency_key=identity,
            intent_digest=intent_digest, plan_digest=intent_digest, actor=OperationActor.from_mapping(actor),
            details={"target": target, "observed_before": before, "requested": request.model_dump(), "mutation_dispatched": False, **self.extra_details(node_id=node_id, vmid=vmid, request=request)})
        operation, lease = self.admit(spec, node_id=node_id, vmid=vmid, request=request)
        if lease is None:
            return self.result(operation, replay=True)
        try:
            self.check_expected(self.review_request(node_id=node_id, vmid=vmid, request=request)["observed_before"], request)
        except self.error_type as exc:
            self.recovery.commit_observation(lease, next_status="blocked", event_type=self.event_prefix + "precheck_blocked", stage="precheck",
                details_patch={"failure_code": exc.code}, expected_statuses=["planned"],
                recovery_status="completed", release_target_lock=True)
            raise self.error_type(exc.code, str(exc), exc.status_code, {"operation_id": operation_id}) from None
        operation, item = self.recovery.commit_observation(lease, next_status="dispatching", event_type=self.event_prefix + "dispatching",
            stage="dispatch", details_patch={"mutation_dispatched": True}, expected_statuses=["planned"], recovery_status="leased")
        lease = RecoveryLease(item=item, token=lease.token)
        try:
            upid = self.dispatch(node_id=node_id, vmid=vmid, request=request, operation=operation)
        except self.error_type as exc:
            self.pause(lease, operation, exc.code)
            return self.result(self.operations.get(operation_id))
        operation, item = self.recovery.commit_observation(lease, next_status="running", event_type=self.event_prefix + "task_bound",
            stage="task", details_patch={"proxmox_upid": upid}, recovery_details_patch={"upid": upid},
            expected_statuses=["dispatching"], recovery_status="leased")
        lease = RecoveryLease(item=item, token=lease.token)

        def heartbeat():
            nonlocal lease
            lease = self.recovery.heartbeat(lease, lease_seconds=60)

        try:
            task = self.client.task(node_id=node_id, upid=upid, heartbeat=heartbeat)
        except self.error_type as exc:
            self.pause(lease, operation, exc.code)
        else:
            self.verify(lease, operation, task=task)
        return self.result(self.operations.get(operation_id))

    def pause(self, lease, operation, code, **evidence):
        self.recovery.commit_observation(lease,
            next_status=None if operation.status == "needs_reconciliation" else "needs_reconciliation",
            event_type=self.event_prefix + "result_unconfirmed", stage="reconciliation",
            details_patch={"failure_code": code, **evidence}, expected_statuses=[operation.status],
            expected_operation_version=operation.version, expected_operation_checksum=operation.last_event_checksum,
            recovery_status="paused", error_code=code)
        return "paused"

    def verify(self, lease, operation, task=None):
        target = operation.details["target"]
        upid = operation.details.get("proxmox_upid")
        if not upid:
            return self.pause(lease, operation, self.error_prefix + "TASK_REFERENCE_MISSING")
        try:
            task = task or self.client.task(node_id=target["node_id"], upid=upid)
            if task["status"] in {"running", "queued"}:
                self.recovery.commit_observation(lease, event_type=self.event_prefix + "task_running", stage="task",
                    details_patch={"task": task}, expected_statuses=[operation.status],
                    recovery_status="retry_wait", retry_delay_seconds=5)
                return "retry_wait"
            if task["status"] != "stopped" or task["exitstatus"] != "OK":
                return self.pause(lease, operation, self.error_prefix + "TASK_UNCONFIRMED", task=task)
            after = self.observe_result(operation)
        except self.error_type as exc:
            return self.pause(lease, operation, exc.code)
        requested = operation.details["requested"]
        if not self.matches(after, requested, operation.details["observed_before"]):
            return self.pause(lease, operation, self.error_prefix + "RESULT_UNCONFIRMED", observed_after=after, task=task)
        if operation.status != "verifying":
            operation, item = self.recovery.commit_observation(lease, next_status="verifying", event_type=self.event_prefix + "size_observed",
                stage="post_check", details_patch={"observed_after": after, "task": task}, expected_statuses=[operation.status],
                expected_operation_version=operation.version, expected_operation_checksum=operation.last_event_checksum,
                recovery_status="leased")
            lease = RecoveryLease(item=item, token=lease.token)
        self.recovery.commit_observation(lease, next_status="succeeded", event_type=self.event_prefix + "verified", stage="completed",
            details_patch={"observed_after": after, "task": task, "failure_code": None}, expected_statuses=["verifying"],
            expected_operation_version=operation.version, expected_operation_checksum=operation.last_event_checksum,
            recovery_status="completed", release_target_lock=True)
        return "succeeded"

    @staticmethod
    def result(operation, replay=False):
        return {"operation_id": operation.operation_id, "status": operation.status,
                "operation": {"operation_id": operation.operation_id, "status": operation.status},
                "target": operation.details["target"], "observed_before": operation.details.get("observed_before"),
                "observed_after": operation.details.get("observed_after"), "requested": operation.details["requested"],
                "task": operation.details.get("task"), "failure_code": operation.details.get("failure_code"),
                "idempotent_replay": replay, "automatic_retry_allowed": False}
