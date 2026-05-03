"""Proxmox resource preflight checks for selected VM provisioning inputs."""

from __future__ import annotations

from dataclasses import dataclass
import re
from ipaddress import IPv4Address, IPv4Interface, ip_address, ip_interface
from typing import Any, Iterable, Protocol

from app.domains.proxmox.service import ProxmoxService


@dataclass(frozen=True)
class ResourceCheck:
    id: str
    label: str
    status: str
    message: str
    detail: str | None = None
    next_action: str | None = None


class ProxmoxResourceReader(Protocol):
    def get_nodes(self) -> list[dict[str, Any]]: ...
    def get_templates(self, node: str | None = None) -> list[dict[str, Any]]: ...
    def get_storages(self, node: str | None = None) -> list[dict[str, Any]]: ...
    def get_networks(self, node: str | None = None) -> list[dict[str, Any]]: ...
    def get_vm_config(self, node: str, vmid: int) -> dict[str, Any]: ...
    def get_vms(self, node: str | None = None) -> list[dict[str, Any]]: ...


class ProvisioningResourcePreflightService:
    """Validates user-selected Proxmox resources before Terraform apply."""

    DEFAULT_DISK_SIZE_GB = 50

    def __init__(self, proxmox_service: ProxmoxResourceReader | None = None):
        self.proxmox_service = proxmox_service or ProxmoxService()

    def check(self, request: dict[str, Any]) -> dict[str, Any]:
        target_node = str(request.get("server_id") or request.get("target_node") or "").strip()
        template_id = str(request.get("template_id") or "").strip()
        storage_id = str(request.get("storage_id") or "").strip()
        network_ids = self._normalize_string_list(request.get("network_ids"))
        server_name = str(request.get("server_name") or request.get("vm_name") or "").strip()
        requested_vmid = request.get("vmid") or request.get("vm_id")
        disk_size_gb = self._requested_disk_size_gb(
            request.get("disk_size_gb"),
            request.get("disk_size"),
        )
        vm_ip = str(request.get("vm_ip") or "").strip()
        vm_gateway = str(request.get("vm_gateway") or "").strip()

        nodes = self.proxmox_service.get_nodes()
        node_check = self._check_node(target_node, nodes)
        node_is_valid = node_check.status != "error"

        templates = self.proxmox_service.get_templates()
        storages = self.proxmox_service.get_storages(target_node) if target_node and node_is_valid else []
        networks = self.proxmox_service.get_networks(target_node) if target_node and node_is_valid else []
        vms = self.proxmox_service.get_vms() if target_node and node_is_valid else []

        template_match = self._find_template(template_id, templates)
        storage_match = self._find_storage(storage_id, storages)
        checks = [
            node_check,
            self._check_template(template_id, template_match),
            self._check_template_readiness(template_id, template_match),
            self._check_template_disk_size(template_id, template_match, disk_size_gb),
            self._check_storage(storage_id, storage_match, target_node),
            self._check_storage_capacity(storage_id, storage_match, disk_size_gb),
            self._check_networks(network_ids, networks, target_node),
            self._check_vm_identity(server_name, requested_vmid, vms, target_node),
            self._check_static_network(vm_ip, vm_gateway),
        ]
        status = self._overall_status(checks)

        return {
            "status": status,
            "summary": self._summary_for_status(status),
            "checks": [self._public_check(check) for check in checks],
            "next_actions": [check.next_action for check in checks if check.next_action],
            "target": {
                "node": target_node or None,
                "template_id": template_id or None,
                "storage_id": storage_id or None,
                "network_ids": network_ids,
                "server_name": server_name or None,
                "vmid": requested_vmid,
                "disk_size_gb": disk_size_gb,
                "vm_ip": vm_ip or None,
                "vm_gateway": vm_gateway or None,
            },
        }

    @classmethod
    def _requested_disk_size_gb(cls, disk_size_gb: Any, disk_size: Any) -> Any:
        for value in (disk_size_gb, disk_size):
            if value is not None and value != "":
                return value
        return cls.DEFAULT_DISK_SIZE_GB

    @staticmethod
    def _normalize_string_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, Iterable):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    @staticmethod
    def _resource_id(resource: dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = resource.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    def _check_node(self, target_node: str, nodes: list[dict[str, Any]]) -> ResourceCheck:
        if not target_node:
            return ResourceCheck(
                id="target_node",
                label="Target node",
                status="error",
                message="No target node selected.",
                next_action="Select a Proxmox node before provisioning.",
            )

        match = next((node for node in nodes if self._resource_id(node, "id", "server_id", "name") == target_node), None)
        if not match:
            return ResourceCheck(
                id="target_node",
                label="Target node",
                status="error",
                message=f"Target node '{target_node}' was not found in Proxmox inventory.",
                next_action="Refresh nodes and select an existing Proxmox node.",
            )

        node_status = str(match.get("status") or "unknown").strip().lower()
        if node_status and node_status not in {"online", "unknown"}:
            return ResourceCheck(
                id="target_node",
                label="Target node",
                status="error",
                message=f"Target node '{target_node}' is {node_status}.",
                detail=f"status={node_status}",
                next_action="Select an online node or restore the node before provisioning.",
            )

        return ResourceCheck(
            id="target_node",
            label="Target node",
            status="ok",
            message=f"Target node '{target_node}' exists.",
            detail=f"status={node_status or 'unknown'}",
        )

    def _find_template(self, template_id: str, templates: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not template_id:
            return None
        return next(
            (
                template for template in templates
                if template_id in {
                    self._resource_id(template, "id"),
                    self._resource_id(template, "template_id"),
                    str(template.get("vmid") or "").strip(),
                }
            ),
            None,
        )

    def _check_template(self, template_id: str, match: dict[str, Any] | None) -> ResourceCheck:
        if not template_id:
            return ResourceCheck(
                id="template",
                label="Template",
                status="error",
                message="No template selected.",
                next_action="Select a VM template before provisioning.",
            )

        if not match:
            return ResourceCheck(
                id="template",
                label="Template",
                status="error",
                message=f"Template '{template_id}' was not found.",
                next_action="Refresh templates and select an existing template.",
            )

        template_node = self._resource_id(match, "node")
        return ResourceCheck(
            id="template",
            label="Template",
            status="ok",
            message=f"Template '{template_id}' exists.",
            detail=f"source_node={template_node or 'unknown'}",
        )

    def _check_template_readiness(self, template_id: str, match: dict[str, Any] | None) -> ResourceCheck:
        if not template_id or not match:
            return ResourceCheck(
                id="template_readiness",
                label="Template readiness",
                status="error",
                message="Template readiness cannot be checked without a valid template.",
                next_action="Select an existing VM template before provisioning.",
            )

        node = self._resource_id(match, "node")
        raw_vmid = match.get("vmid")
        try:
            vmid = int(raw_vmid)
        except (TypeError, ValueError):
            return ResourceCheck(
                id="template_readiness",
                label="Template readiness",
                status="warning",
                message="Template VMID could not be parsed for config readiness checks.",
                detail=f"template_id={template_id}",
                next_action="Confirm the selected template has cloud-init and qemu guest agent enabled.",
            )

        config = self.proxmox_service.get_vm_config(node, vmid) if node else {}
        if not config:
            return ResourceCheck(
                id="template_readiness",
                label="Template readiness",
                status="warning",
                message="Template config could not be loaded for cloud-init/guest agent checks.",
                detail=f"template={node or 'unknown'}/{vmid}",
                next_action="Confirm the template config is readable and prepared for cloud-init provisioning.",
            )

        agent_ready = self._guest_agent_enabled(config.get("agent"))
        cloud_init_ready = self._has_cloud_init_config(config)
        missing = []
        if not agent_ready:
            missing.append("qemu guest agent")
        if not cloud_init_ready:
            missing.append("cloud-init")

        detail = f"agent={config.get('agent', '-')}; cloud_init={cloud_init_ready}"
        if missing:
            return ResourceCheck(
                id="template_readiness",
                label="Template readiness",
                status="warning",
                message=f"Template exists but {' and '.join(missing)} readiness was not detected.",
                detail=detail,
                next_action="Prepare the template with cloud-init and qemu guest agent before relying on automatic IP/Ansible handoff.",
            )

        return ResourceCheck(
            id="template_readiness",
            label="Template readiness",
            status="ok",
            message="Template has cloud-init and qemu guest agent readiness signals.",
            detail=detail,
        )

    def _check_template_disk_size(self, template_id: str, match: dict[str, Any] | None, disk_size_gb: Any) -> ResourceCheck:
        requested_gb = self._to_float(disk_size_gb)
        if requested_gb is None or requested_gb <= 0:
            return ResourceCheck(
                id="template_disk_size",
                label="Template disk size",
                status="ok",
                message="No explicit disk size requested for template disk-size preflight.",
            )
        if not template_id or not match:
            return ResourceCheck(
                id="template_disk_size",
                label="Template disk size",
                status="ok",
                message="Template disk-size check skipped until a valid template is selected.",
            )

        config = self._load_template_config(match)
        if not config:
            return ResourceCheck(
                id="template_disk_size",
                label="Template disk size",
                status="warning",
                message="Template disk size could not be checked because template config was not available.",
                next_action="Confirm the requested disk size is not smaller than the template disk before provisioning.",
            )

        template_disk_gb = self._max_template_disk_size_gb(config)
        if template_disk_gb is None:
            return ResourceCheck(
                id="template_disk_size",
                label="Template disk size",
                status="warning",
                message="Template disk size could not be detected from template config.",
                next_action="Confirm the requested disk size is not smaller than the template disk before provisioning.",
            )

        if requested_gb < template_disk_gb:
            return ResourceCheck(
                id="template_disk_size",
                label="Template disk size",
                status="error",
                message=(
                    f"Requested disk size {requested_gb:g}GB is lower than template disk size "
                    f"{template_disk_gb:g}GB. Proxmox/Terraform cannot shrink cloned disks."
                ),
                detail=f"requested_gb={requested_gb:g}; template_disk_gb={template_disk_gb:g}",
                next_action=f"Set disk_size_gb to at least {template_disk_gb:g}GB or choose a smaller template.",
            )

        return ResourceCheck(
            id="template_disk_size",
            label="Template disk size",
            status="ok",
            message="Requested disk size is not smaller than the template disk.",
            detail=f"requested_gb={requested_gb:g}; template_disk_gb={template_disk_gb:g}",
        )

    def _load_template_config(self, match: dict[str, Any]) -> dict[str, Any]:
        node = self._resource_id(match, "node")
        raw_vmid = match.get("vmid")
        try:
            vmid = int(raw_vmid)
        except (TypeError, ValueError):
            return {}
        return self.proxmox_service.get_vm_config(node, vmid) if node else {}

    @staticmethod
    def _max_template_disk_size_gb(config: dict[str, Any]) -> float | None:
        sizes: list[float] = []
        for key, value in config.items():
            key_text = str(key).lower()
            value_text = str(value).lower()
            if not key_text.startswith(("scsi", "sata", "virtio", "ide")):
                continue
            if "cloudinit" in value_text or "cloud-init" in value_text or "media=cdrom" in value_text:
                continue
            size_gb = ProvisioningResourcePreflightService._parse_proxmox_disk_size_gb(value_text)
            if size_gb is not None:
                sizes.append(size_gb)
        return max(sizes) if sizes else None

    @staticmethod
    def _parse_proxmox_disk_size_gb(value: str) -> float | None:
        match = re.search(r"(?:^|,)size=(\d+(?:\.\d+)?)([kmgt]?)i?b?", str(value).lower())
        if not match:
            return None
        number = float(match.group(1))
        unit = match.group(2) or "g"
        if unit == "t":
            return number * 1024
        if unit == "g":
            return number
        if unit == "m":
            return number / 1024
        if unit == "k":
            return number / (1024 * 1024)
        return number

    @staticmethod
    def _guest_agent_enabled(value: Any) -> bool:
        if value is None:
            return False
        normalized = str(value).strip().lower()
        return normalized in {"1", "true", "yes", "enabled=1"} or "enabled=1" in normalized

    @staticmethod
    def _has_cloud_init_config(config: dict[str, Any]) -> bool:
        for key, value in config.items():
            key_text = str(key).lower()
            value_text = str(value).lower()
            if key_text.startswith("ipconfig"):
                return True
            if "cloudinit" in value_text or "cloud-init" in value_text:
                return True
        return False

    def _find_storage(self, storage_id: str, storages: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not storage_id:
            return None
        return next((storage for storage in storages if self._resource_id(storage, "id", "storage_id", "name") == storage_id), None)

    def _check_storage(self, storage_id: str, match: dict[str, Any] | None, target_node: str) -> ResourceCheck:
        if not storage_id:
            return ResourceCheck(
                id="storage",
                label="Storage",
                status="error",
                message="No storage selected.",
                next_action="Select a storage target before provisioning.",
            )
        if not target_node:
            return ResourceCheck(
                id="storage",
                label="Storage",
                status="error",
                message="Storage cannot be validated without a target node.",
                next_action="Select a target node before choosing storage.",
            )

        if not match:
            return ResourceCheck(
                id="storage",
                label="Storage",
                status="error",
                message=f"Storage '{storage_id}' is not available on node '{target_node}'.",
                next_action="Select storage available on the target node.",
            )

        content = match.get("content")
        content_items = self._normalize_content(content)
        if content_items and "images" not in content_items:
            return ResourceCheck(
                id="storage",
                label="Storage",
                status="warning",
                message=f"Storage '{storage_id}' exists but does not explicitly advertise VM image content.",
                detail=f"content={','.join(content_items)}",
                next_action="Confirm this storage can hold VM disks before provisioning.",
            )

        available_gb = match.get("available_gb")
        detail = f"available_gb={available_gb}" if available_gb is not None else None
        return ResourceCheck(
            id="storage",
            label="Storage",
            status="ok",
            message=f"Storage '{storage_id}' is available on node '{target_node}'.",
            detail=detail,
        )


    def _check_storage_capacity(self, storage_id: str, match: dict[str, Any] | None, disk_size_gb: Any) -> ResourceCheck:
        requested_gb = self._to_float(disk_size_gb)
        if requested_gb is None or requested_gb <= 0:
            return ResourceCheck(
                id="storage_capacity",
                label="Storage capacity",
                status="ok",
                message="No explicit disk size requested for capacity preflight.",
            )
        if not storage_id or not match:
            return ResourceCheck(
                id="storage_capacity",
                label="Storage capacity",
                status="error",
                message="Storage capacity cannot be checked without a valid storage target.",
                next_action="Select a valid storage target before provisioning.",
            )

        available_gb = self._to_float(match.get("available_gb"))
        if available_gb is None:
            return ResourceCheck(
                id="storage_capacity",
                label="Storage capacity",
                status="warning",
                message=f"Storage '{storage_id}' free space is unknown; requested disk is {requested_gb:g}GB.",
                next_action="Confirm storage free space in Proxmox before provisioning.",
            )
        if requested_gb > available_gb:
            return ResourceCheck(
                id="storage_capacity",
                label="Storage capacity",
                status="error",
                message=f"Requested disk size {requested_gb:g}GB exceeds storage '{storage_id}' free space {available_gb:g}GB.",
                detail=f"requested_gb={requested_gb:g}; available_gb={available_gb:g}",
                next_action="Choose a storage with enough free space or reduce disk_size_gb.",
            )
        return ResourceCheck(
            id="storage_capacity",
            label="Storage capacity",
            status="ok",
            message=f"Storage '{storage_id}' has enough free space for the requested disk.",
            detail=f"requested_gb={requested_gb:g}; available_gb={available_gb:g}",
        )

    def _check_vm_identity(self, server_name: str, requested_vmid: Any, vms: list[dict[str, Any]], target_node: str) -> ResourceCheck:
        normalized_name = server_name.strip().lower()
        normalized_vmid = self._to_int(requested_vmid)
        if not normalized_name and normalized_vmid is None:
            return ResourceCheck(
                id="vm_identity",
                label="VM identity",
                status="warning",
                message="No VM name or VMID provided for duplicate preflight.",
                next_action="Set a VM name before provisioning so duplicates can be detected.",
            )

        for vm in vms:
            vm_name = str(vm.get("name") or vm.get("server_name") or "").strip()
            vmid = self._to_int(vm.get("vmid") or vm.get("vm_id"))
            vm_node = str(vm.get("node") or vm.get("node_name") or vm.get("server_id") or "").strip()
            same_target_node = vm_node == target_node if vm_node else True

            if normalized_name and same_target_node and vm_name.lower() == normalized_name:
                return ResourceCheck(
                    id="vm_identity",
                    label="VM identity",
                    status="error",
                    message=f"VM name '{server_name}' already exists on node '{target_node}'.",
                    detail=f"existing_vmid={vmid if vmid is not None else '-'}",
                    next_action="Choose a unique VM name before provisioning.",
                )
            if normalized_vmid is not None and vmid == normalized_vmid:
                return ResourceCheck(
                    id="vm_identity",
                    label="VM identity",
                    status="error",
                    message=f"VMID {normalized_vmid} already exists in the Proxmox cluster.",
                    detail=f"existing_node={vm_node or '-'}; existing_name={vm_name or '-'}",
                    next_action="Choose an unused VMID cluster-wide or let Proxmox allocate one.",
                )

        detail_parts = []
        if server_name:
            detail_parts.append(f"name={server_name}")
        if normalized_vmid is not None:
            detail_parts.append(f"vmid={normalized_vmid}")
        return ResourceCheck(
            id="vm_identity",
            label="VM identity",
            status="ok",
            message="Requested VM identity is not already present on the target node/cluster.",
            detail="; ".join(detail_parts) if detail_parts else None,
        )

    def _check_static_network(self, vm_ip: str, vm_gateway: str) -> ResourceCheck:
        if not vm_ip and not vm_gateway:
            return ResourceCheck(
                id="static_network",
                label="Static network",
                status="ok",
                message="No static IP requested; VM will use DHCP/default provisioning policy.",
            )
        if not vm_ip or not vm_gateway:
            return ResourceCheck(
                id="static_network",
                label="Static network",
                status="error",
                message="Static IP provisioning requires both vm_ip CIDR and vm_gateway.",
                next_action="Provide both vm_ip, for example 192.168.2.50/24, and vm_gateway.",
            )
        if "/" not in vm_ip:
            return ResourceCheck(
                id="static_network",
                label="Static network",
                status="error",
                message="vm_ip must include CIDR prefix, for example 192.168.2.50/24.",
                next_action="Add a CIDR prefix to vm_ip before provisioning.",
            )
        try:
            parsed_ip = ip_interface(vm_ip)
        except ValueError:
            return ResourceCheck(
                id="static_network",
                label="Static network",
                status="error",
                message="vm_ip must be a valid IPv4 host CIDR, for example 192.168.2.50/24.",
                next_action="Fix the static VM IP address format.",
            )
        if not isinstance(parsed_ip, IPv4Interface):
            return ResourceCheck(
                id="static_network",
                label="Static network",
                status="error",
                message="vm_ip must be an IPv4 host CIDR.",
                next_action="Use an IPv4 CIDR such as 192.168.2.50/24.",
            )
        try:
            parsed_gateway = ip_address(vm_gateway)
        except ValueError:
            return ResourceCheck(
                id="static_network",
                label="Static network",
                status="error",
                message="vm_gateway must be a valid IPv4 address, for example 192.168.2.1.",
                next_action="Fix the static gateway address format.",
            )
        if not isinstance(parsed_gateway, IPv4Address):
            return ResourceCheck(
                id="static_network",
                label="Static network",
                status="error",
                message="vm_gateway must be an IPv4 address.",
                next_action="Use an IPv4 gateway such as 192.168.2.1.",
            )
        if parsed_ip.network.prefixlen < 31 and parsed_ip.ip in {parsed_ip.network.network_address, parsed_ip.network.broadcast_address}:
            return ResourceCheck(
                id="static_network",
                label="Static network",
                status="error",
                message="vm_ip host address must not be the subnet network or broadcast address.",
                detail=f"vm_network={parsed_ip.network}; vm_ip={parsed_ip.ip}",
                next_action="Choose a usable host IP inside the subnet.",
            )

        if parsed_gateway not in parsed_ip.network:
            return ResourceCheck(
                id="static_network",
                label="Static network",
                status="error",
                message="vm_gateway must be in the same subnet as vm_ip.",
                detail=f"vm_network={parsed_ip.network}; gateway={parsed_gateway}",
                next_action="Choose a gateway address inside the vm_ip subnet.",
            )
        if parsed_ip.ip == parsed_gateway:
            return ResourceCheck(
                id="static_network",
                label="Static network",
                status="error",
                message="vm_ip host address must not equal vm_gateway.",
                next_action="Choose a unique host IP that differs from the gateway.",
            )
        return ResourceCheck(
            id="static_network",
            label="Static network",
            status="ok",
            message="Static IP and gateway are valid and in the same subnet.",
            detail=f"vm_ip={parsed_ip}; gateway={parsed_gateway}",
        )

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_content(content: Any) -> list[str]:
        if content is None:
            return []
        if isinstance(content, str):
            return [item.strip() for item in content.split(",") if item.strip()]
        if isinstance(content, Iterable):
            return [str(item).strip() for item in content if str(item).strip()]
        return []

    def _check_networks(self, network_ids: list[str], networks: list[dict[str, Any]], target_node: str) -> ResourceCheck:
        if not network_ids:
            return ResourceCheck(
                id="networks",
                label="Networks",
                status="error",
                message="No network bridge selected.",
                next_action="Select at least one VM bridge before provisioning.",
            )
        if not target_node:
            return ResourceCheck(
                id="networks",
                label="Networks",
                status="error",
                message="Networks cannot be validated without a target node.",
                next_action="Select a target node before choosing networks.",
            )

        available = {
            self._resource_id(network, "id", "network_id", "name", "network_name")
            for network in networks
        }
        missing = [network_id for network_id in network_ids if network_id not in available]
        if missing:
            return ResourceCheck(
                id="networks",
                label="Networks",
                status="error",
                message=f"Network bridge(s) not available on node '{target_node}': {', '.join(missing)}.",
                detail=f"available={', '.join(sorted(available)) or '-'}",
                next_action="Select network bridges that exist on the target node.",
            )

        return ResourceCheck(
            id="networks",
            label="Networks",
            status="ok",
            message=f"Selected network bridge(s) exist on node '{target_node}'.",
            detail=", ".join(network_ids),
        )

    @staticmethod
    def _overall_status(checks: list[ResourceCheck]) -> str:
        if any(check.status == "error" for check in checks):
            return "error"
        if any(check.status == "warning" for check in checks):
            return "warning"
        return "ready"

    @staticmethod
    def _summary_for_status(status: str) -> str:
        if status == "ready":
            return "Selected Proxmox resources are ready for provisioning."
        if status == "warning":
            return "Selected Proxmox resources need review before provisioning."
        return "Selected Proxmox resources have blocking issues."

    @staticmethod
    def _public_check(check: ResourceCheck) -> dict[str, object]:
        payload: dict[str, object] = {
            "id": check.id,
            "label": check.label,
            "status": check.status,
            "message": check.message,
        }
        if check.detail:
            payload["detail"] = check.detail
        if check.next_action:
            payload["next_action"] = check.next_action
        return payload
