"""Stopped-VM net0 bridge/tag rules; preserve all other existing NIC options."""
import re

from pydantic import BaseModel, ConfigDict, Field


class NetworkError(RuntimeError):
    def __init__(self, code, message, status_code=409, details=None):
        super().__init__(message)
        self.code, self.status_code, self.details = code, status_code, details or {}

    def to_detail(self):
        return {"code": self.code, "message": str(self), "details": self.details}


class NetworkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    idempotency_key: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    expected_digest: str = Field(pattern=r"^[a-fA-F0-9]{40}$")
    expected_name: str = Field(max_length=255)
    expected_net0: str = Field(min_length=1, max_length=2048)
    bridge_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    vlan_tag: int | None = Field(default=None, ge=1, le=4094)


def validate_target(node_id, vmid):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", node_id) or not 100 <= vmid <= 999999999:
        raise NetworkError("VM_NETWORK_INVALID_TARGET", "노드·VMID 형식을 확인하세요.", 422)


def parse_net0(value):
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise NetworkError("VM_NETWORK_CONFIG_UNSUPPORTED", "기존 net0 설정을 확인할 수 없습니다.")
    pairs = [part.split("=", 1) for part in value.split(",")]
    if any(len(pair) != 2 or not re.fullmatch(r"[A-Za-z0-9_-]+", pair[0]) or not pair[1] for pair in pairs):
        raise NetworkError("VM_NETWORK_CONFIG_UNSUPPORTED", "net0 설정 형식을 확인하세요.")
    options = dict(pairs)
    if len(options) != len(pairs) or not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", pairs[0][1]):
        raise NetworkError("VM_NETWORK_CONFIG_UNSUPPORTED", "net0 MAC 또는 중복 옵션을 확인하세요.")
    if pairs[0][0] not in {"virtio", "e1000", "e1000-82540em", "e1000-82544gc", "e1000-82545em", "i82551", "i82557b", "i82559er", "ne2k_pci", "pcnet", "rtl8139", "vmxnet3"}:
        raise NetworkError("VM_NETWORK_CONFIG_UNSUPPORTED", "첫 지원 범위의 NIC 모델이 아닙니다.")
    if "trunks" in options or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", options.get("bridge", "")):
        raise NetworkError("VM_NETWORK_CONFIG_UNSUPPORTED", "bridge 없는 NIC 또는 VLAN trunk는 지원하지 않습니다.")
    tag = options.get("tag")
    if tag is not None and (not tag.isdigit() or not 1 <= int(tag) <= 4094):
        raise NetworkError("VM_NETWORK_CONFIG_UNSUPPORTED", "현재 VLAN tag 형식을 확인하세요.")
    return options


def replace_network(net0, bridge, tag):
    options = parse_net0(net0)
    options["bridge"] = bridge
    if tag is None:
        options.pop("tag", None)
    else:
        options["tag"] = str(tag)
    return ",".join(f"{key}={value}" for key, value in options.items())


def observed_network(config, status, pending, snapshot):
    if status.get("status") != "stopped":
        raise NetworkError("VM_NETWORK_NOT_STOPPED", "정지된 VM만 변경할 수 있습니다.")
    if str(config.get("template", 0)) != "0" or config.get("lock"):
        raise NetworkError("VM_NETWORK_LOCKED_OR_TEMPLATE", "템플릿 또는 잠긴 VM은 변경할 수 없습니다.")
    if any("pending" in row or row.get("delete") for row in pending):
        raise NetworkError("VM_NETWORK_PENDING_CONFIG", "먼저 Proxmox의 대기 중 VM 설정을 확인하세요.")
    if snapshot["pending_changes"]:
        raise NetworkError("VM_NETWORK_HOST_PENDING", "호스트에 미적용 네트워크 설정이 있습니다. 적용 상태를 먼저 확인하세요.")
    digest = config.get("digest", "")
    if not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{40}", digest):
        raise NetworkError("VM_NETWORK_DIGEST_UNAVAILABLE", "설정 변경 감지값을 확인할 수 없습니다.", 503)
    net0 = config.get("net0")
    options = parse_net0(net0)
    bridges = [{"bridge_id": row["iface"], "vlan_aware": row.get("bridge_vlan_aware", 0) in (1, "1")}
               for row in snapshot["interfaces"]
               if row.get("type") == "bridge" and row.get("active") in (1, "1")
               and isinstance(row.get("iface"), str)
               and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", row["iface"])]
    if options["bridge"] not in {row["bridge_id"] for row in bridges}:
        raise NetworkError("VM_NETWORK_BRIDGE_UNAVAILABLE", "현재 bridge의 실제 상태·선택 범위·사용 권한을 확인하세요.")
    model, mac = next(iter(options.items()))
    return {"name": str(config.get("name", "")), "status": "stopped", "digest": digest, "net0": net0,
            "model": model, "mac": mac, "bridge_id": options["bridge"],
            "vlan_tag": int(options["tag"]) if "tag" in options else None, "bridges": bridges}


def check_expected(before, request):
    if (before["digest"], before["name"], before["net0"]) != (request.expected_digest, request.expected_name, request.expected_net0):
        raise NetworkError("VM_NETWORK_STATE_CHANGED", "검토 후 설정이 변경됐습니다. 다시 조회·검토하세요.")
    selected = next((row for row in before["bridges"] if row["bridge_id"] == request.bridge_id), None)
    if selected is None:
        raise NetworkError("VM_NETWORK_BRIDGE_UNAVAILABLE", "선택 bridge의 실제 상태·사용 권한을 확인하세요.")
    if request.vlan_tag is not None and not selected["vlan_aware"]:
        raise NetworkError("VM_NETWORK_VLAN_UNSUPPORTED", "VLAN tag는 VLAN-aware Linux bridge에서만 지원합니다.", 422)
    if (before["bridge_id"], before["vlan_tag"]) == (request.bridge_id, request.vlan_tag):
        raise NetworkError("VM_NETWORK_NO_CHANGE", "현재 설정과 같습니다. 변경할 값이 없습니다.", 422)
