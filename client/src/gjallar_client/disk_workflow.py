"""Review and execute an absolute disk expansion through the server API."""
import re

from . import resource_review
from .errors import ClientError
from .workflows import identifier, request_identity, segment


def show(app, vmid, node):
    return app.request(f"nodes/{segment(node)}/vms/{vmid}/disks/scsi0", operator=True)


def validate(payload):
    fields = {"idempotency_key", "expected_digest", "expected_name", "expected_volume", "expected_size_bytes", "size_gib"}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ClientError("INVALID_REVIEW", "디스크 검토 입력 필드를 확인하세요.", 2)
    request_identity(payload["idempotency_key"])
    if not isinstance(payload["expected_digest"], str) or not re.fullmatch(r"[a-fA-F0-9]{40}", payload["expected_digest"]):
        raise ClientError("INVALID_REVIEW", "설정 변경 감지값이 올바르지 않습니다.", 2)
    for key in ("expected_name", "expected_volume"):
        if not isinstance(payload[key], str) or len(payload[key]) > 255:
            raise ClientError("INVALID_REVIEW", "VM 이름·volume을 확인하세요.", 2)
    if (not payload["expected_volume"] or type(payload["expected_size_bytes"]) is not int or payload["expected_size_bytes"] <= 0
            or type(payload["size_gib"]) is not int or not 1 <= payload["size_gib"] <= 65536
            or payload["size_gib"] * 1024 ** 3 <= payload["expected_size_bytes"]):
        raise ClientError("INVALID_DISK_SIZE", "현재보다 큰 전체 용량을 1~65536 GiB 정수로 입력하세요. 축소는 지원하지 않습니다.", 2)


def plan(app, *, vmid, node, size_gib, request_id, review_file):
    node = identifier(node)
    result = show(app, vmid, node)
    review = result["data"]
    if not isinstance(review, dict) or review.get("target") != {"node_id": node, "vmid": vmid}:
        raise ClientError("TARGET_CHANGED", "조회한 대상이 선택한 VM과 다릅니다.", 8)
    before = review.get("observed_before", {})
    payload = {"idempotency_key": request_id, "expected_digest": before.get("digest"), "expected_name": before.get("name"),
               "expected_volume": before.get("volume_id"), "expected_size_bytes": before.get("size_bytes"), "size_gib": size_gib}
    validate(payload)
    resource_review.save(app, schema="gjallar.cli.disk.v1", review=review, payload=payload, path=review_file)
    return {**result, "data": {"target": review["target"], "before": before, "after": {"size_gib": size_gib},
                              "warnings": review.get("warnings", [])}, "review_file": str(review_file),
            "message": "확장 검토를 저장했습니다. 아직 디스크는 변경하지 않았습니다. 게스트 filesystem 확장은 별도입니다.",
            "exit_code": 0, "next": "gjallar vm disk execute --review-file <파일>로 검토한 확장을 실행하세요."}


def execute(app, review_file, confirm):
    return resource_review.execute(app, review_file, confirm, schema="gjallar.cli.disk.v1",
                                   validate=validate, action="disk-resize", label="디스크 확장 (축소 불가·게스트 filesystem 별도)")
