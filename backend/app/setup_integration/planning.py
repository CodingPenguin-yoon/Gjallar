"""Exact role/ACL planning for the initial PVE 9 read and power profile."""
from app.setup_integration.contracts import SetupError, digest


ROLE_PRIVILEGES = {
    "GjallarNodeReadV1": ["Sys.Audit"],
    "GjallarVmReadV1": ["VM.Audit", "VM.GuestAgent.Audit"],
    "GjallarVmPowerV1": ["VM.Audit", "VM.GuestAgent.Audit", "VM.PowerMgmt"],
    "GjallarStorageReadV1": ["Datastore.Audit"],
    "GjallarBridgeReadV1": ["SDN.Audit"],
}


def acl_plan(intent):
    scope = intent.scope
    rows = [{"path": f"/nodes/{value}", "role": "GjallarNodeReadV1", "propagate": 1} for value in scope.nodes]
    vm_role = "GjallarVmPowerV1" if "power" in intent.features else "GjallarVmReadV1"
    rows += [{"path": f"/vms/{value}", "role": vm_role, "propagate": 1} for value in scope.vmids]
    rows += [{"path": f"/storage/{value}", "role": "GjallarStorageReadV1", "propagate": 1} for value in scope.storages]
    rows += [{"path": f"/sdn/zones/localnetwork/{value}", "role": "GjallarBridgeReadV1", "propagate": 1} for value in scope.bridges]
    return rows


def permissions_at(request, path):
    response = request("GET", "/access/permissions", data={"path": path})
    if not isinstance(response, dict):
        raise SetupError("PROXMOX_PROTOCOL_ERROR", "권한 응답 형식이 올바르지 않습니다.", 502)
    permissions = response.get(path, {})
    if not isinstance(permissions, dict):
        raise SetupError("PROXMOX_PROTOCOL_ERROR", "권한 응답 형식이 올바르지 않습니다.", 502)
    # Values indicate propagation, not whether the privilege is present.
    return set(permissions)


def build_plan(intent, request, *, attempt_id, connection_version):
    acls = acl_plan(intent)
    roles = {row["role"]: ROLE_PRIVILEGES[row["role"]] for row in acls}
    existing = request("GET", "/access/roles")
    if not isinstance(existing, list) or any(not isinstance(item, dict) for item in existing):
        raise SetupError("PROXMOX_PROTOCOL_ERROR", "role 목록 형식이 올바르지 않습니다.", 502)
    existing_names = {item.get("roleid") for item in existing}
    create_roles = []
    for name, privileges in sorted(roles.items()):
        if name in existing_names:
            value = request("GET", "/access/roles/" + name)
            if not isinstance(value, dict) or set(value) != set(privileges):
                raise SetupError("PROXMOX_ROLE_CONFLICT", "같은 이름의 role 권한이 다릅니다. 기존 role을 덮어쓰지 않습니다.")
        else:
            create_roles.append(name)
    missing = []
    if create_roles and "Sys.Modify" not in permissions_at(request, "/access"):
        missing.append({"path": "/access", "privileges": ["Sys.Modify"], "purpose": "role_creation"})
    for row in acls:
        granted = permissions_at(request, row["path"])
        required = set(roles[row["role"]]) | {"Permissions.Modify"}
        if absent := sorted(required - granted):
            missing.append({"path": row["path"], "privileges": absent, "purpose": "owner_and_acl"})
    plan = {"endpoint": intent.endpoint, "owner": intent.owner,
            "token_id": intent.owner + "!gjallar-" + attempt_id,
            "expires_at": intent.expires_at, "privsep": 1, "scope": intent.scope.model_dump(),
            "features": intent.features, "roles": roles, "create_roles": create_roles, "acls": acls,
            "missing_privileges": missing, "connection_version": connection_version,
            "trust_digest": digest(intent.ca_pem), "version": "pve9-read-power.v1"}
    return {**plan, "digest": digest(plan), "can_confirm": not missing}


def verify_token(intent, request):
    missing = []
    for row in acl_plan(intent):
        absent = sorted(set(ROLE_PRIVILEGES[row["role"]]) - permissions_at(request, row["path"]))
        if absent:
            missing.append({"path": row["path"], "privileges": absent})
    if missing:
        raise SetupError("PROXMOX_TOKEN_SCOPE_INCOMPLETE", "선택한 대상의 token 권한 검증에 실패했습니다.", 502)
    nodes = request("GET", "/nodes")
    if not isinstance(nodes, list) or any(not isinstance(row, dict) for row in nodes):
        raise SetupError("PROXMOX_PROTOCOL_ERROR", "노드 목록 형식이 올바르지 않습니다.", 502)
    visible_nodes = {row.get("node") for row in nodes}
    if not set(intent.scope.nodes) <= visible_nodes:
        raise SetupError("PROXMOX_SCOPE_UNAVAILABLE", "선택한 노드를 모두 확인할 수 없습니다.", 502)
    seen = set()
    seen_storage = set()
    seen_bridges = set()
    for node in intent.scope.nodes:
        vms = request("GET", f"/nodes/{node}/qemu")
        if not isinstance(vms, list) or any(not isinstance(row, dict) for row in vms):
            raise SetupError("PROXMOX_PROTOCOL_ERROR", "VM 목록 형식이 올바르지 않습니다.", 502)
        for vm in vms:
            if vm.get("vmid") in intent.scope.vmids:
                config = request("GET", f'/nodes/{node}/qemu/{vm["vmid"]}/config')
                if not isinstance(config, dict):
                    raise SetupError("PROXMOX_PROTOCOL_ERROR", "VM 설정 형식이 올바르지 않습니다.", 502)
                seen.add(vm["vmid"])
        for resource, requested, key, observed in (
            ("storage", intent.scope.storages, "storage", seen_storage),
            ("network", intent.scope.bridges, "iface", seen_bridges),
        ):
            if not requested:
                continue
            values = request("GET", f"/nodes/{node}/{resource}")
            if not isinstance(values, list) or any(not isinstance(value, dict) for value in values):
                raise SetupError("PROXMOX_PROTOCOL_ERROR", "선택 자원 목록 형식이 올바르지 않습니다.", 502)
            observed.update(value[key] for value in values if value.get(key) in requested)
    if seen != set(intent.scope.vmids):
        raise SetupError("PROXMOX_SCOPE_UNAVAILABLE", "선택한 VM을 모두 확인할 수 없습니다.", 502)
    if seen_storage != set(intent.scope.storages) or seen_bridges != set(intent.scope.bridges):
        raise SetupError("PROXMOX_SCOPE_UNAVAILABLE", "선택한 스토리지·브리지를 모두 확인할 수 없습니다.", 502)
    return {"nodes": sorted(intent.scope.nodes), "vmids": sorted(seen)}
