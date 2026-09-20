"""Narrow compute input and observed-state rules; no infrastructure imports."""
import re

from pydantic import BaseModel, ConfigDict, Field


class ComputeError(RuntimeError):
    def __init__(self, code, message, status_code=409, details=None):
        super().__init__(message)
        self.code, self.status_code, self.details = code, status_code, details or {}

    def to_detail(self):
        return {"code": self.code, "message": str(self), "details": self.details}


class ComputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    idempotency_key: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    expected_digest: str = Field(pattern=r"^[a-fA-F0-9]{40}$")
    expected_name: str = Field(max_length=255)
    cores: int = Field(ge=1, le=128)
    memory_mib: int = Field(ge=128, le=1048576)


def validate_target(node_id, vmid):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", node_id) or not 100 <= vmid <= 999999999:
        raise ComputeError("VM_COMPUTE_INVALID_TARGET", "노드·VMID 형식을 확인하세요.", 422)


def observed_compute(config, status, pending):
    if status.get("status") != "stopped":
        raise ComputeError("VM_COMPUTE_NOT_STOPPED", "정지된 VM만 변경할 수 있습니다.")
    if str(config.get("template", 0)) != "0" or config.get("lock"):
        raise ComputeError("VM_COMPUTE_LOCKED_OR_TEMPLATE", "템플릿 또는 잠긴 VM은 변경할 수 없습니다.")
    if any("pending" in row or row.get("delete") for row in pending):
        raise ComputeError("VM_COMPUTE_PENDING_CONFIG", "먼저 Proxmox의 대기 중 설정 변경을 확인하세요.")
    try:
        cores = int(config["cores"])
        memory = int(config["memory"])
        sockets = int(config.get("sockets", 1))
        balloon = int(config.get("balloon", 0))
    except (KeyError, ValueError, TypeError):
        raise ComputeError("VM_COMPUTE_CONFIG_UNSUPPORTED", "숫자형 CPU·메모리 설정을 확인할 수 없습니다.") from None
    if sockets != 1 or "vcpus" in config or any(re.fullmatch(r"numa\d+", key) for key in config):
        raise ComputeError("VM_COMPUTE_TOPOLOGY_UNSUPPORTED", "첫 지원 범위는 단일 socket·고정 vCPU이며 NUMA 세부 설정 변경은 지원하지 않습니다.")
    digest = config.get("digest", "")
    if not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{40}", digest):
        raise ComputeError("VM_COMPUTE_DIGEST_UNAVAILABLE", "설정 변경 감지값을 확인할 수 없습니다.", 503)
    return {"name": str(config.get("name", "")), "status": "stopped", "cores": cores,
            "memory_mib": memory, "sockets": sockets, "balloon_mib": balloon, "digest": digest}


def check_expected(before, request):
    if before["digest"] != request.expected_digest or before["name"] != request.expected_name:
        raise ComputeError("VM_COMPUTE_STATE_CHANGED", "검토 후 설정이 변경됐습니다. 다시 조회·검토하세요.")
    if request.memory_mib < before["balloon_mib"]:
        raise ComputeError("VM_COMPUTE_BALLOON_LIMIT", "메모리는 기존 balloon 최소 메모리보다 작을 수 없습니다.", 422)
    if (request.cores, request.memory_mib) == (before["cores"], before["memory_mib"]):
        raise ComputeError("VM_COMPUTE_NO_CHANGE", "현재 설정과 같습니다. 변경할 값이 없습니다.", 422)
