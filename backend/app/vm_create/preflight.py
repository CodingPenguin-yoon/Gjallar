"""Non-destructive preflight checks for Set 6 Create VM planning."""

from __future__ import annotations

from ipaddress import ip_address

from app.manifests.loader import load_builtin_profiles
from app.proxmox.inventory import FakeProxmoxInventoryAdapter, get_default_inventory_adapter
from app.proxmox.models import TemplateInventory
from app.vm_create.iac_readiness import run_iac_readiness
from app.vm_create.models import PreflightCheck, PreflightResult, RiskItem, VmCreateDraft


def _risk_level(risks: list[RiskItem]) -> str:
    levels = {risk.level for risk in risks}
    if "red" in levels:
        return "red"
    if "yellow" in levels:
        return "yellow"
    return "green"


def _check(
    checks: list[PreflightCheck],
    risks: list[RiskItem],
    *,
    code: str,
    ok: bool,
    message: str,
    fail_code: str | None = None,
    fail_level: str = "red",
    detail: dict | None = None,
) -> None:
    level = "green" if ok else fail_level
    status = "pass" if ok else "fail"
    detail = dict(detail or {})
    checks.append(PreflightCheck(code=code, status=status, level=level, message=message, detail=detail))
    if not ok:
        risks.append(RiskItem(level=fail_level, code=fail_code or code, message=message, detail=detail))


def _valid_static_ipv4(value: str) -> bool:
    try:
        ip = ip_address(value)
    except ValueError:
        return False
    return ip.version == 4


def _present(value: object) -> bool:
    return value is not None and str(value).strip() != ""


def _valid_static_prefix(value: object) -> bool:
    if not _present(value):
        return False
    try:
        prefix = int(str(value).strip())
    except (TypeError, ValueError):
        return False
    return 1 <= prefix <= 32


def _select_template(templates: list[TemplateInventory], draft: VmCreateDraft) -> TemplateInventory | None:
    if draft.template_vmid is not None:
        return next(
            (
                item
                for item in templates
                if item.vmid == draft.template_vmid
                and (draft.template_node_id is None or item.node_id == draft.template_node_id)
            ),
            None,
        )

    if draft.template_id:
        requested = str(draft.template_id)
        return next(
            (
                item
                for item in templates
                if requested
                in {
                    item.template_id,
                    item.name,
                    str(item.vmid),
                    f"{item.node_id}/{item.vmid}",
                    f"{item.node_id}:{item.vmid}",
                }
            ),
            None,
        )

    return next((item for item in templates if item.family == draft.template_family), None)


def _profile_limits_dict(profile) -> dict:
    if profile is None:
        return {}
    return profile.hardware.to_dict()


def _template_requirement_level(profile, requirement_name: str) -> str:
    if profile is None:
        return "yellow"
    requirements = getattr(profile, "template_requirements", None)
    if requirements is None:
        return "yellow"
    return "red" if getattr(requirements, requirement_name, False) else "yellow"


def _profile_requires_ssh_key(profile) -> bool:
    if profile is None:
        return True
    access = getattr(profile, "access", None)
    return bool(getattr(access, "require_ssh_key", True))


def _profile_allows_password_login(profile) -> bool:
    if profile is None:
        return False
    access = getattr(profile, "access", None)
    return bool(getattr(access, "allow_password_login", False))


def _template_evidence(template: TemplateInventory | None, draft: VmCreateDraft) -> dict:
    if template is None:
        return {
            "requested_template_id": draft.template_id,
            "requested_template_vmid": draft.template_vmid,
            "requested_template_node_id": draft.template_node_id,
            "source": "live_inventory_missing",
        }
    return {**template.to_dict(), "source": "live_inventory"}


def _bridge_evidence(live_bridge, *, selected_bridge: str | None, node_id: str) -> dict:
    if live_bridge is None:
        return {
            "bridge_id": selected_bridge,
            "node_id": node_id,
            "active": False,
            "source": "live_inventory_missing",
        }
    return {**live_bridge.to_dict(), "source": "live_inventory"}


def _check_hardware_range(
    checks: list[PreflightCheck],
    risks: list[RiskItem],
    *,
    profile,
    profile_id: str,
    field_name: str,
    requested: int,
) -> None:
    limits = getattr(profile.hardware, field_name)
    _check(
        checks,
        risks,
        code=f"profile_{field_name}_range",
        ok=limits.min <= requested <= limits.max,
        message=f"requested {field_name} is inside the selected profile limits",
        fail_code=f"profile_{field_name}_out_of_range",
        detail={
            "profile_id": profile_id,
            "requested": requested,
            "default": limits.default,
            "min": limits.min,
            "max": limits.max,
        },
    )


def run_preflight(
    draft: VmCreateDraft,
    *,
    inventory_adapter: FakeProxmoxInventoryAdapter | None = None,
) -> PreflightResult:
    """Evaluate a Create VM draft without live Proxmox/IaC mutation."""
    adapter = inventory_adapter or get_default_inventory_adapter()
    checks: list[PreflightCheck] = []
    risks: list[RiskItem] = []

    profiles = {profile.profile_id: profile for profile in load_builtin_profiles()}
    profile = profiles.get(draft.profile_id)
    _check(
        checks,
        risks,
        code="profile_schema",
        ok=profile is not None,
        message="selected profile exists in static seed data",
        fail_code="unknown_profile",
        detail={"profile_id": draft.profile_id},
    )
    _check(
        checks,
        risks,
        code="profile_enabled",
        ok=profile is not None and profile.create_enabled,
        message="selected profile is enabled for Create VM",
        fail_code="disabled_profile",
        detail={"profile_id": draft.profile_id},
    )
    if profile is not None:
        _check_hardware_range(
            checks,
            risks,
            profile=profile,
            profile_id=draft.profile_id,
            field_name="cpu",
            requested=draft.hardware.cpu,
        )
        _check_hardware_range(
            checks,
            risks,
            profile=profile,
            profile_id=draft.profile_id,
            field_name="memory_mb",
            requested=draft.hardware.memory_mb,
        )
        _check_hardware_range(
            checks,
            risks,
            profile=profile,
            profile_id=draft.profile_id,
            field_name="disk_gb",
            requested=draft.hardware.disk_gb,
        )

    access_evidence = draft.access.to_dict()
    _check(
        checks,
        risks,
        code="access_cloud_init_user_present",
        ok=_present(draft.access.cloud_init_user),
        message="cloud-init username is present",
        fail_code="cloud_init_user_missing",
        detail={
            "username": draft.access.cloud_init_user or None,
            "cloud_init_user": draft.access.cloud_init_user or None,
        },
    )
    _check(
        checks,
        risks,
        code="access_password_login_disabled",
        ok=draft.access.password_login is False,
        message="password login is disabled for the selected profile",
        fail_code="password_login_enabled",
        detail={
            "password_login": bool(draft.access.password_login),
            "profile_allows_password_login": _profile_allows_password_login(profile),
        },
    )
    _check(
        checks,
        risks,
        code="access_ssh_key_present",
        ok=not _profile_requires_ssh_key(profile) or draft.access.ssh_key_present,
        message="required SSH public key is available from the request or backend default",
        fail_code="ssh_public_key_missing",
        detail={
            **access_evidence,
            "profile_requires_ssh_key": _profile_requires_ssh_key(profile),
        },
    )
    _check(
        checks,
        risks,
        code="access_ssh_key_valid",
        ok=not draft.access.ssh_key_present or draft.access.ssh_key_valid,
        message="SSH public key is a valid OpenSSH public key",
        fail_code=draft.access.ssh_key_validation_error or "ssh_public_key_malformed",
        detail=access_evidence,
    )

    templates = list(adapter.list_templates())
    template = _select_template(templates, draft)
    _check(
        checks,
        risks,
        code="template_available",
        ok=template is not None,
        message="selected template is available in read-only inventory",
        fail_code="template_unavailable",
        detail={
            "template_family": draft.template_family,
            "requested_template_id": draft.template_id,
            "requested_template_vmid": draft.template_vmid,
            "requested_template_node_id": draft.template_node_id,
        },
    )
    if template is not None:
        _check(
            checks,
            risks,
            code="template_matches_profile",
            ok=template.family == draft.template_family,
            message="selected template matches the profile family",
            fail_code="template_family_mismatch",
            detail={
                "template_id": template.template_id,
                "template_family": template.family,
                "profile_template_family": draft.template_family,
            },
        )
        _check(
            checks,
            risks,
            code="template_cloud_init_ready",
            ok=template.cloud_init_ready,
            message="template cloud-init readiness is verified",
            fail_code="template_cloud_init_unverified",
            fail_level=_template_requirement_level(profile, "require_cloud_init"),
            detail={"template_id": template.template_id, "template_vmid": template.vmid},
        )
        _check(
            checks,
            risks,
            code="template_guest_agent_ready",
            ok=template.guest_agent_ready,
            message="template guest-agent readiness is verified",
            fail_code="template_guest_agent_unverified",
            fail_level=_template_requirement_level(profile, "require_qemu_guest_agent"),
            detail={"template_id": template.template_id, "template_vmid": template.vmid},
        )
        template_disk_gb = int(template.disk_gb or 0)
        _check(
            checks,
            risks,
            code="template_disk_floor",
            ok=template_disk_gb <= 0 or draft.hardware.disk_gb >= template_disk_gb,
            message="requested disk is at least as large as the selected template disk",
            fail_code="template_disk_larger_than_requested",
            detail={
                "template_id": template.template_id,
                "template_vmid": template.vmid,
                "template_disk_gb": template_disk_gb,
                "requested_disk_gb": draft.hardware.disk_gb,
            },
        )
        if profile is not None:
            _check(
                checks,
                risks,
                code="profile_template_disk_limit",
                ok=template_disk_gb <= 0 or template_disk_gb <= profile.hardware.disk_gb.max,
                message="selected template disk fits inside the selected profile disk limit",
                fail_code="template_disk_exceeds_profile_max",
                detail={
                    "profile_id": draft.profile_id,
                    "template_id": template.template_id,
                    "template_vmid": template.vmid,
                    "template_disk_gb": template_disk_gb,
                    "profile_disk_max_gb": profile.hardware.disk_gb.max,
                },
            )

    vms = list(adapter.list_vms())
    nodes = {node.node_id: node for node in adapter.list_nodes()}
    node = nodes.get(draft.target_node_id)
    _check(
        checks,
        risks,
        code="target_node_online",
        ok=node is not None and node.status == "online",
        message="target node is present and online in read-only inventory",
        fail_code="target_node_unavailable",
        detail={"target_node_id": draft.target_node_id},
    )

    storages = list(adapter.list_storage(draft.target_node_id))
    selected_storage_id = str(draft.storage_id or "").strip()
    if selected_storage_id:
        storage = next((item for item in storages if item.storage_id == selected_storage_id), None)
        storage_ok = storage is not None and storage.free_gb >= draft.hardware.disk_gb and "images" in storage.content
    else:
        storage = next((item for item in storages if item.free_gb >= draft.hardware.disk_gb and "images" in item.content), None)
        storage_ok = storage is not None
    _check(
        checks,
        risks,
        code="storage_available",
        ok=storage_ok,
        message="selected storage has images content and enough free space for the requested disk",
        fail_code="storage_unavailable",
        detail={
            "target_node_id": draft.target_node_id,
            "selected_storage_id": selected_storage_id or None,
            "resolved_storage_id": storage.storage_id if storage is not None else None,
            "disk_gb": draft.hardware.disk_gb,
        },
    )

    selected_bridge = str(draft.network.bridge_id or "").strip() or None
    _check(
        checks,
        risks,
        code="bridge_selection",
        ok=selected_bridge is not None,
        message="operator selected an explicit bridge for the target node",
        fail_code="bridge_id_missing",
        detail={
            "node_id": draft.target_node_id,
            "bridge_id": selected_bridge,
            "source": "explicit",
        },
    )

    live_bridge = None
    if selected_bridge is not None:
        live_bridge = next(
            (item for item in adapter.list_networks(draft.target_node_id) if item.bridge_id == selected_bridge and item.active),
            None,
        )
    _check(
        checks,
        risks,
        code="bridge_exists",
        ok=live_bridge is not None,
        message="selected bridge is active on the target node in read-only inventory",
        fail_code="bridge_missing_or_inactive",
        detail={"bridge_id": selected_bridge, "node_id": draft.target_node_id},
    )

    existing_vmids = {vm.vmid for vm in vms} | {item.vmid for item in templates}
    _check(
        checks,
        risks,
        code="vmid_available",
        ok=draft.proposed_vmid not in existing_vmids,
        message="proposed VMID does not collide with observed VMs/templates",
        fail_code="vmid_collision",
        detail={"proposed_vmid": draft.proposed_vmid},
    )

    existing_names = {vm.name for vm in vms} | {item.name for item in templates}
    _check(
        checks,
        risks,
        code="name_available",
        ok=draft.vm_name not in existing_names,
        message="VM name does not collide with observed inventory",
        fail_code="name_collision",
        detail={"vm_name": draft.vm_name},
    )

    observed_ips = {addr for vm in vms for addr in vm.ip_addresses}
    if draft.network.ip_mode == "static":
        static_ip = str(draft.network.static_ip or "").strip()
        gateway = str(draft.network.gateway or "").strip()
        prefix = draft.network.prefix
        _check(
            checks,
            risks,
            code="static_ip_present",
            ok=_present(static_ip),
            message="static mode includes operator-supplied static_ip",
            fail_code="static_ip_missing",
            detail={"static_ip": static_ip or None},
        )
        _check(
            checks,
            risks,
            code="static_prefix_present",
            ok=_present(prefix),
            message="static mode includes operator-supplied prefix",
            fail_code="static_prefix_missing",
            detail={"prefix": prefix},
        )
        _check(
            checks,
            risks,
            code="static_gateway_present",
            ok=_present(gateway),
            message="static mode includes operator-supplied gateway",
            fail_code="static_gateway_missing",
            detail={"gateway": gateway or None},
        )
        _check(
            checks,
            risks,
            code="static_ip_valid",
            ok=_valid_static_ipv4(static_ip),
            message="static IP is a valid IPv4 address",
            fail_code="static_ip_invalid",
            detail={"static_ip": static_ip or None},
        )
        _check(
            checks,
            risks,
            code="static_prefix_valid",
            ok=_valid_static_prefix(prefix),
            message="static prefix is a valid IPv4 CIDR prefix length",
            fail_code="static_prefix_invalid",
            detail={"prefix": prefix},
        )
        _check(
            checks,
            risks,
            code="static_gateway_valid",
            ok=_valid_static_ipv4(gateway),
            message="static gateway is a valid IPv4 address",
            fail_code="static_gateway_invalid",
            detail={"gateway": gateway or None},
        )
        conflicts = [
            {"vmid": vm.vmid, "name": vm.name, "node_id": vm.node_id}
            for vm in vms
            if static_ip in vm.ip_addresses
        ]
        _check(
            checks,
            risks,
            code="static_ip_available",
            ok=not conflicts,
            message="static IP is not observed in current VM inventory",
            fail_code="static_ip_unavailable",
            detail={"static_ip": static_ip, "conflicts": conflicts},
        )
    else:
        checks.append(
            PreflightCheck(
                code="static_ip_available",
                status="pass",
                level="yellow",
                message="DHCP mode is allowed but requires guest-agent/IP discovery evidence after first boot",
                detail={"ip_mode": draft.network.ip_mode},
            )
        )
        risks.append(
            RiskItem(
                level="yellow",
                code="dhcp_requires_discovery",
                message="DHCP mode requires later discovery evidence",
                detail={"ip_mode": draft.network.ip_mode},
            )
        )

    iac_readiness = run_iac_readiness()
    checks.extend(iac_readiness.checks)
    risks.extend(iac_readiness.risks)

    _check(
        checks,
        risks,
        code="destroy_delete_plan_absent",
        ok=True,
        message="Set 6 planner does not produce destroy/delete actions",
    )
    mutating_methods = {"apply", "clone_vm", "create_vm", "delete_vm", "power_on", "perform_vm_action"}
    offenders = sorted(name for name in mutating_methods if hasattr(adapter, name))
    adapter_source = getattr(adapter, "source", "")
    _check(
        checks,
        risks,
        code="credential_scope_read_only",
        ok=not offenders and adapter_source in {"fake_read_only", "live_read_only"},
        message="Create VM preflight uses read-only inventory only",
        fail_code="inventory_adapter_not_read_only",
        detail={"offenders": offenders, "source": adapter_source or None},
    )

    return PreflightResult(
        draft_id=draft.draft_id,
        inventory_source=getattr(adapter, "source", "unknown"),
        risk_level=_risk_level(risks),
        checks=checks,
        risks=risks,
        selected_storage_id=storage.storage_id if storage is not None else None,
        selected_template_id=template.template_id if template is not None else None,
        selected_template_vmid=template.vmid if template is not None else None,
        selected_template_node_id=template.node_id if template is not None else None,
        selected_bridge_id=selected_bridge,
        profile_id=draft.profile_id,
        profile_hardware_limits=_profile_limits_dict(profile),
        iac_root=iac_readiness.iac_root,
        iac_ready_for_plan=iac_readiness.ready_for_plan,
        iac_ready_for_execute=iac_readiness.ready_for_execute,
        side_effects=[],
        access=access_evidence,
        selected_template=_template_evidence(template, draft),
        selected_bridge=_bridge_evidence(live_bridge, selected_bridge=selected_bridge, node_id=draft.target_node_id),
    )
