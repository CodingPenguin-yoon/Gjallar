"""Server-bound review files shared by explicit VM resource changes."""
import json
import os

from .errors import ClientError
from .workflows import mutation, read_json, segment


def save(app, *, schema, review, payload, path):
    _, profile = app.connections.get(app.connection_name)
    record = {"schema": schema, "origin": profile["origin"], "connection_id": profile["id"],
              "target": review["target"], "payload": payload, "review": review}
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError:
        raise ClientError("REVIEW_FILE_EXISTS", "새 검토 파일을 만들 수 없습니다. 기존 파일은 덮어쓰지 않습니다.", 7) from None
    with os.fdopen(fd, "w") as stream:
        json.dump(record, stream, ensure_ascii=True, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def execute(app, path, confirm, *, schema, validate, action, label, operation_vmid_from_payload=None, operation_type=None):
    record = read_json(path)
    _, profile = app.connections.get(app.connection_name)
    if (record.get("schema") != schema or record.get("origin") != profile["origin"]
            or record.get("connection_id") != profile["id"]):
        raise ClientError("REVIEW_CONNECTION_MISMATCH", "검토 파일을 만든 서버 연결을 선택하세요.", 2)
    payload = record.get("payload")
    validate(payload)
    target = record.get("target")
    if not isinstance(target, dict) or set(target) != {"node_id", "vmid"} or type(target["vmid"]) is not int or not 100 <= target["vmid"] <= 999999999:
        raise ClientError("INVALID_REVIEW", "검토 대상 VMID를 확인하세요.", 2)
    node = segment(target.get("node_id"))
    confirm({"server": profile["origin"], "action": label, "target": target,
             "review": record.get("review"), "requested": payload})
    operation_vmid = operation_vmid_from_payload(payload) if operation_vmid_from_payload else target["vmid"]
    return mutation(app, f"nodes/{node}/vms/{target['vmid']}/actions/{action}", payload,
                    f"gjallar operations list --vmid {operation_vmid}",
                    expected_operation={"type": operation_type, "node": target["node_id"], "vmid": operation_vmid} if operation_type else None)
