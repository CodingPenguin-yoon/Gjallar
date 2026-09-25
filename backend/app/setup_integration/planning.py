"""Exact role/ACL planning for opt-in PVE 9 capabilities."""
from app.cloud_images.contracts import VM_PRIVILEGES
from app.setup_integration.contracts import FEATURES, SetupError, digest


ROLE_PRIVILEGES = {
    "GjallarHostNetworkV1": ["Sys.Modify"],
    "GjallarHostStorageV1": ["Datastore.Allocate"],
    "GjallarVmMigrateV1": ["VM.Migrate", "VM.Config.Disk"],
    "GjallarVmRestoreV1": ["VM.Allocate", "VM.Audit", "VM.Config.Disk", "VM.PowerMgmt", "VM.GuestAgent.Audit"],
    "GjallarVmBackupV1": ["VM.Backup"],
    "GjallarImageCleanupV1": ["VM.Allocate", "VM.Audit"],
    "GjallarImageCleanupStorageV1": ["Datastore.Allocate"],
    "GjallarImageBuildV1": VM_PRIVILEGES,
    "GjallarImageUploadV1": ["Datastore.AllocateTemplate"],
    "GjallarNodeReadV1": ["Sys.Audit"],
    "GjallarVmReadV1": ["VM.Audit", "VM.GuestAgent.Audit"],
    "GjallarVmPowerV1": ["VM.Audit", "VM.GuestAgent.Audit", "VM.PowerMgmt"],
    "GjallarVmComputeV1": ["VM.Config.CPU", "VM.Config.Memory"],
    "GjallarVmConsoleV1": ["VM.Console"],
    "GjallarVmTemplateV2": ["VM.Allocate", "VM.Config.Disk"],
    "GjallarVmDeleteV1": ["VM.Allocate"],
    "GjallarVmDeleteStorageV1": ["Datastore.Allocate"],
    "GjallarVmCloneV2": ["VM.Audit", "VM.Clone", "VM.Config.Disk"],
    "GjallarVmCloneTargetV2": ["VM.Allocate", "VM.Audit", "VM.Config.Disk"],
    "GjallarVmNetworkV1": ["VM.Config.Network"],
    "GjallarVmDiskV1": ["VM.Config.Disk"],
    "GjallarStorageReadV1": ["Datastore.Audit"],
    "GjallarBridgeReadV1": ["SDN.Audit"],
    "GjallarTemplateCloneV1": ["VM.Audit", "VM.Clone"],
    "GjallarVmCreateV1": ["VM.Allocate", "VM.Audit", "VM.Config.CPU", "VM.Config.Memory",
                          "VM.Config.Disk", "VM.Config.Network", "VM.Config.Options", "VM.Config.Cloudinit",
                          "VM.GuestAgent.Audit", "VM.GuestAgent.Unrestricted", "VM.PowerMgmt"],
    "GjallarStorageAllocateV1": ["Datastore.AllocateSpace"],
    "GjallarBridgeUseV1": ["SDN.Use"],
}


ROLE_PRIVILEGES["GjallarClusterV1"] = sorted({privilege for values in ROLE_PRIVILEGES.values() for privilege in values})

CLUSTER_FEATURE_ROLES = {
    "read": ["GjallarNodeReadV1", "GjallarVmReadV1", "GjallarStorageReadV1", "GjallarBridgeReadV1"],
    "power": ["GjallarVmPowerV1"],
    "compute": ["GjallarVmComputeV1"],
    "console": ["GjallarVmConsoleV1"],
    "template": ["GjallarVmTemplateV2"],
    "delete": ["GjallarVmDeleteV1", "GjallarVmDeleteStorageV1"],
    "disk": ["GjallarVmDiskV1", "GjallarStorageAllocateV1"],
    "network": ["GjallarVmNetworkV1", "GjallarBridgeUseV1"],
    "clone": ["GjallarVmCloneV2", "GjallarVmCloneTargetV2", "GjallarStorageAllocateV1", "GjallarBridgeUseV1"],
    "create": ["GjallarTemplateCloneV1", "GjallarVmCreateV1", "GjallarStorageAllocateV1", "GjallarBridgeUseV1"],
    "backup": ["GjallarVmBackupV1", "GjallarStorageAllocateV1"],
    "restore": ["GjallarVmBackupV1", "GjallarVmRestoreV1", "GjallarStorageAllocateV1", "GjallarBridgeUseV1"],
    "migrate": ["GjallarVmMigrateV1", "GjallarBridgeUseV1"],
    "image_build": ["GjallarImageBuildV1", "GjallarImageUploadV1", "GjallarStorageAllocateV1", "GjallarBridgeUseV1"],
    "image_cleanup": ["GjallarImageCleanupV1", "GjallarImageCleanupStorageV1"],
    "host_storage": ["GjallarHostStorageV1"],
    "host_network": ["GjallarHostNetworkV1"],
}


def acl_plan(intent):
    if intent.access_mode == "cluster":
        roles = (["GjallarClusterV1"] if set(intent.features) == FEATURES else
                 sorted({role for feature in intent.features for role in CLUSTER_FEATURE_ROLES[feature]}))
        return [{"path": "/", "role": role, "propagate": 1} for role in roles]
    scope = intent.scope
    rows = [{"path": f"/nodes/{value}", "role": "GjallarNodeReadV1", "propagate": 1} for value in scope.nodes]
    if 'host_network' in intent.features:
        rows += [{'path': f'/nodes/{value}', 'role': 'GjallarHostNetworkV1', 'propagate': 1} for value in scope.nodes]
        rows += [{'path': '/sdn/zones/localnetwork', 'role': 'GjallarBridgeReadV1', 'propagate': 1}]
    if 'host_storage' in intent.features:
        rows += [{'path':'/storage','role':'GjallarHostStorageV1','propagate':1}]
        rows += [{'path':f'/storage/{value}','role':'GjallarStorageReadV1','propagate':1} for value in scope.host_storages]
    vm_role = "GjallarVmPowerV1" if "power" in intent.features else "GjallarVmReadV1"
    rows += [{"path": f"/vms/{value}", "role": vm_role, "propagate": 1} for value in scope.vmids]
    if "migrate" in intent.features:
        rows += [{"path": f"/vms/{value}", "role": "GjallarVmMigrateV1", "propagate": 1} for value in scope.vmids]
        rows += [{"path": f"/sdn/zones/localnetwork/{value}", "role": "GjallarBridgeUseV1", "propagate": 1} for value in scope.bridges]
    if "compute" in intent.features:
        rows += [{"path": f"/vms/{value}", "role": "GjallarVmComputeV1", "propagate": 1} for value in scope.vmids]
    if "network" in intent.features:
        rows += [{"path": f"/vms/{value}", "role": "GjallarVmNetworkV1", "propagate": 1} for value in scope.vmids]
        rows += [{"path": f"/sdn/zones/localnetwork/{value}", "role": "GjallarBridgeUseV1", "propagate": 1} for value in scope.bridges]
    if "disk" in intent.features:
        rows += [{"path": f"/vms/{value}", "role": "GjallarVmDiskV1", "propagate": 1} for value in scope.vmids]
        rows += [{"path": f"/storage/{value}", "role": "GjallarStorageAllocateV1", "propagate": 1} for value in scope.storages]
    rows += [{"path": f"/storage/{value}", "role": "GjallarStorageReadV1", "propagate": 1} for value in scope.storages]
    rows += [{"path": f"/sdn/zones/localnetwork/{value}", "role": "GjallarBridgeReadV1", "propagate": 1} for value in scope.bridges]
    if {"backup", "restore"} & set(intent.features):
        rows += [{"path": f"/vms/{value}", "role": "GjallarVmBackupV1", "propagate": 1} for value in scope.vmids]
        rows += [{"path": f"/storage/{value}", "role": "GjallarStorageAllocateV1", "propagate": 1} for value in scope.backup_storages]
    if "restore" in intent.features:
        for values, prefix, role in (
            (scope.restore_vmids, "/vms", "GjallarVmRestoreV1"),
            (scope.restore_storages, "/storage", "GjallarStorageAllocateV1"),
            (scope.bridges, "/sdn/zones/localnetwork", "GjallarBridgeUseV1"),
        ):
            rows += [{"path": f"{prefix}/{value}", "role": role, "propagate": 1} for value in values]
    if "image_cleanup" in intent.features:
        rows += [{"path": f"/vms/{value}", "role": "GjallarImageCleanupV1", "propagate": 1} for value in scope.vmids]
        rows += [{"path": f"/storage/{value}", "role": "GjallarImageCleanupStorageV1", "propagate": 1} for value in scope.image_cleanup_storages]
    if "image_build" in intent.features:
        for values, prefix, role in (
            (scope.image_vmids, "/vms", "GjallarImageBuildV1"),
            (scope.storages, "/storage", "GjallarImageUploadV1"),
            (scope.storages, "/storage", "GjallarStorageAllocateV1"),
            (scope.bridges, "/sdn/zones/localnetwork", "GjallarBridgeUseV1"),
        ):
            rows += [{"path": f"{prefix}/{value}", "role": role, "propagate": 1} for value in values]
    if "template" in intent.features:
        rows += [{"path": f"/vms/{value}", "role": "GjallarVmTemplateV2", "propagate": 1} for value in scope.vmids]
    if "console" in intent.features:
        rows += [{"path": f"/vms/{value}", "role": "GjallarVmConsoleV1", "propagate": 1} for value in scope.vmids]
    if "delete" in intent.features:
        rows += [{"path": f"/vms/{value}", "role": "GjallarVmDeleteV1", "propagate": 1} for value in scope.vmids]
        rows += [{"path": f"/storage/{value}", "role": "GjallarVmDeleteStorageV1", "propagate": 1} for value in scope.storages]
    if "clone" in intent.features:
        for values, prefix, role in (
            (scope.vmids, "/vms", "GjallarVmCloneV2"),
            (scope.clone_vmids, "/vms", "GjallarVmCloneTargetV2"),
            (scope.storages, "/storage", "GjallarStorageAllocateV1"),
            (scope.bridges, "/sdn/zones/localnetwork", "GjallarBridgeUseV1"),
        ):
            rows += [{"path": f"{prefix}/{value}", "role": role, "propagate": 1} for value in values]
    if "create" in intent.features:
        for values, prefix, role in (
            (scope.template_vmids, "/vms", "GjallarTemplateCloneV1"),
            (scope.create_vmids, "/vms", "GjallarVmCreateV1"),
            (scope.storages, "/storage", "GjallarStorageAllocateV1"),
            (scope.bridges, "/sdn/zones/localnetwork", "GjallarBridgeUseV1"),
        ):
            rows += [{"path": f"{prefix}/{value}", "role": role, "propagate": 1} for value in values]
    return [dict(path=path, role=role, propagate=propagate)
            for path, role, propagate in dict.fromkeys((row["path"], row["role"], row["propagate"]) for row in rows)]


def permissions_at(request, path):
    response = request("GET", "/access/permissions", data={"path": path})
    if not isinstance(response, dict):
        raise SetupError("PROXMOX_PROTOCOL_ERROR", "권한 응답 형식이 올바르지 않습니다.", 502)
    permissions = response.get(path, {})
    if not isinstance(permissions, dict):
        raise SetupError("PROXMOX_PROTOCOL_ERROR", "권한 응답 형식이 올바르지 않습니다.", 502)
    # Values indicate propagation, not whether the privilege is present.
    return set(permissions)


def authority_warnings(intent):
    warnings = (["현재와 이후 추가되는 클러스터 전체 자원을 조회합니다. 선택한 작업 권한도 전체 자원에 적용됩니다."]
                if intent.access_mode == "cluster" else [])
    if "create" in intent.features or "image_build" in intent.features:
        warnings.append("생성 기능에는 전원·guest-agent 권한이 포함됩니다. Gjallar의 허용 작업보다 PVE 토큰 자체 권한은 넓을 수 있습니다.")
    if 'host_storage' in intent.features:
        warnings.append('PVE token은 /storage의 Datastore.Allocate로 클러스터 전체 storage 설정을 변경할 수 있습니다. Gjallar는 별도로 선택한 host storage ID와 directory 설정 필드만 허용합니다.')
    if 'host_network' in intent.features:
        warnings.append('PVE token의 Sys.Modify는 선택 node의 광범위한 설정 권한입니다. 전체 local bridge 읽기 권한도 필요합니다. Gjallar는 선택 host bridge의 허용 필드와 노드 전체 network reload만 사용합니다.')
    return warnings


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
            "trust_digest": digest(intent.certificate_sha256 or intent.ca_pem), "version": "pve9-managed-host-network.v17",
            "authority_warnings": authority_warnings(intent)}
    if intent.access_mode == "cluster":
        plan.update(access_mode="cluster", version="pve9-cluster.v1")
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
    if intent.access_mode == "cluster":
        if any(not isinstance(node, str) or not node for node in visible_nodes):
            raise SetupError("PROXMOX_PROTOCOL_ERROR", "노드 이름을 확인할 수 없습니다.", 502)
        for node in sorted(visible_nodes):
            for resource in ("qemu", "storage", "network"):
                values = request("GET", f"/nodes/{node}/{resource}")
                if not isinstance(values, list) or any(not isinstance(row, dict) for row in values):
                    raise SetupError("PROXMOX_PROTOCOL_ERROR", "클러스터 자원 목록을 확인할 수 없습니다.", 502)
        return {"nodes": sorted(visible_nodes), "access_mode": "cluster"}
    seen = set()
    existing_vmids = set(intent.scope.vmids) | set(intent.scope.template_vmids)
    seen_storage = set()
    seen_bridges = set()
    for node in intent.scope.nodes:
        vms = request("GET", f"/nodes/{node}/qemu")
        if not isinstance(vms, list) or any(not isinstance(row, dict) for row in vms):
            raise SetupError("PROXMOX_PROTOCOL_ERROR", "VM 목록 형식이 올바르지 않습니다.", 502)
        for vm in vms:
            if vm.get("vmid") in existing_vmids:
                config = request("GET", f'/nodes/{node}/qemu/{vm["vmid"]}/config')
                if not isinstance(config, dict):
                    raise SetupError("PROXMOX_PROTOCOL_ERROR", "VM 설정 형식이 올바르지 않습니다.", 502)
                if vm["vmid"] in intent.scope.template_vmids and str(config.get("template", 0)) != "1":
                    raise SetupError("PROXMOX_SCOPE_UNAVAILABLE", "선택한 복제 원본이 템플릿이 아닙니다.", 502)
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
    if seen != existing_vmids:
        raise SetupError("PROXMOX_SCOPE_UNAVAILABLE", "선택한 VM을 모두 확인할 수 없습니다.", 502)
    if seen_storage != set(intent.scope.storages) or seen_bridges != set(intent.scope.bridges):
        raise SetupError("PROXMOX_SCOPE_UNAVAILABLE", "선택한 스토리지·브리지를 모두 확인할 수 없습니다.", 502)
    return {"nodes": sorted(intent.scope.nodes), "vmids": sorted(seen)}
