"""Pure constraints for the first NFS/scsi0 expansion path."""
from decimal import Decimal
import re

from pydantic import BaseModel, ConfigDict, Field

GIB = 1024 ** 3


class DiskError(RuntimeError):
    def __init__(self, code, message, status_code=409, details=None):
        super().__init__(message)
        self.code, self.status_code, self.details = code, status_code, details or {}

    def to_detail(self):
        return {"code": self.code, "message": str(self), "details": self.details}


class DiskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    idempotency_key: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    expected_digest: str = Field(pattern=r"^[a-fA-F0-9]{40}$")
    expected_name: str = Field(max_length=255)
    expected_volume: str = Field(min_length=1, max_length=255)
    expected_size_bytes: int = Field(gt=0)
    size_gib: int = Field(ge=1, le=65536)


def disk_identity(config, status, pending, *, vmid):
    if status.get("status") != "stopped":
        raise DiskError("VM_DISK_NOT_STOPPED", "정지된 VM만 디스크를 확장할 수 있습니다.")
    if str(config.get("template", 0)) != "0" or config.get("lock"):
        raise DiskError("VM_DISK_LOCKED_OR_TEMPLATE", "템플릿 또는 잠긴 VM은 확장할 수 없습니다.")
    if any("pending" in row or row.get("delete") for row in pending):
        raise DiskError("VM_DISK_PENDING_CONFIG", "대기 중인 VM 설정 변경을 먼저 확인하세요.")
    raw = config.get("scsi0")
    if not isinstance(raw, str):
        raise DiskError("VM_DISK_UNSUPPORTED", "첫 지원 범위는 scsi0 디스크입니다.")
    parts = raw.split(",")
    volume = parts[0]
    match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9_.-]{0,63}):([0-9]+)/vm-([0-9]+)-disk-([0-9]+)\.(raw|qcow2)", volume)
    if not match or int(match[2]) != vmid or int(match[3]) != vmid:
        raise DiskError("VM_DISK_OWNERSHIP_UNCONFIRMED", "이 VM 소유의 raw/qcow2 volume만 확장할 수 있습니다.")
    options = {}
    for part in parts[1:]:
        key, separator, value = part.partition("=")
        if not separator or key in options:
            raise DiskError("VM_DISK_UNSUPPORTED", "디스크 설정 형식을 확인할 수 없습니다.")
        options[key] = value
    if options.get("media") == "cdrom" or options.get("shared", "0") != "0" or options.get("ro", "0") != "0":
        raise DiskError("VM_DISK_UNSUPPORTED", "공유·읽기 전용·CDROM 디스크는 지원하지 않습니다.")
    size_match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([KMGT]?)", options.get("size", ""))
    if not size_match:
        raise DiskError("VM_DISK_SIZE_UNKNOWN", "현재 디스크 설정의 크기를 확인할 수 없습니다.", 503)
    size = Decimal(size_match[1]) * (1024 ** {"": 0, "K": 1, "M": 2, "G": 3, "T": 4}[size_match[2]])
    if size <= 0 or size != int(size):
        raise DiskError("VM_DISK_SIZE_UNKNOWN", "정확한 디스크 bytes를 확인할 수 없습니다.", 503)
    digest = config.get("digest")
    if not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{40}", digest):
        raise DiskError("VM_DISK_DIGEST_UNAVAILABLE", "설정 변경 감지값을 확인할 수 없습니다.", 503)
    return {"name": str(config.get("name", "")), "status": "stopped", "digest": digest, "disk": "scsi0",
            "volume_id": volume, "storage_id": match[1], "format": match[5], "config_size_bytes": int(size)}


def observed_disk(identity, storages, volume):
    storage = next((row for row in storages if row.get("storage") == identity["storage_id"]), None)
    if not storage or storage.get("type") != "nfs" or not storage.get("active") or not storage.get("enabled"):
        raise DiskError("VM_DISK_STORAGE_UNSUPPORTED", "활성 NFS storage만 지원합니다.")
    size = volume.get("size")
    if type(size) is not int or size <= 0 or size != identity["config_size_bytes"] or volume.get("format") != identity["format"]:
        raise DiskError("VM_DISK_SIZE_UNCONFIRMED", "설정과 실제 volume 용량·형식이 일치하지 않습니다.", 503)
    return {**identity, "size_bytes": size, "storage_type": "nfs"}


def check_expected(before, request):
    if (before["digest"], before["name"], before["volume_id"], before["size_bytes"]) != (
            request.expected_digest, request.expected_name, request.expected_volume, request.expected_size_bytes):
        raise DiskError("VM_DISK_STATE_CHANGED", "검토 후 설정·디스크가 변경됐습니다. 다시 조회·검토하세요.")
    if request.size_gib * GIB <= before["size_bytes"]:
        raise DiskError("VM_DISK_NOT_EXPANSION", "현재 실제 용량보다 큰 절대 GiB 값을 입력하세요. 축소는 지원하지 않습니다.", 422)


def verified_task_reference(value, *, node_id, vmid):
    pattern = rf"UPID:{re.escape(node_id)}:[0-9A-Fa-f]+:[0-9A-Fa-f]+:[0-9A-Fa-f]+:resize:{vmid}:[A-Za-z0-9_.@!+-]+:"
    if not isinstance(value, str) or len(value) > 512 or not re.fullmatch(pattern, value):
        raise DiskError("VM_DISK_DISPATCH_UNKNOWN", "확장 작업 식별자를 확인하지 못했습니다. 자동 재실행하지 마세요.", 503)
    return value
