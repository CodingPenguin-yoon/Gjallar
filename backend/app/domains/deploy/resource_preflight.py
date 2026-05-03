"""Proxmox resource preflight checks for selected VM provisioning inputs."""

from __future__ import annotations

from dataclasses import dataclass
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


class ProvisioningResourcePreflightService:
    """Validates user-selected Proxmox resources before Terraform apply."""

    def __init__(self, proxmox_service: ProxmoxResourceReader | None = None):
        self.proxmox_service = proxmox_service or ProxmoxService()

    def check(self, request: dict[str, Any]) -> dict[str, Any]:
        target_node = str(request.get("server_id") or request.get("target_node") or "").strip()
        template_id = str(request.get("template_id") or "").strip()
        storage_id = str(request.get("storage_id") or "").strip()
        network_ids = self._normalize_string_list(request.get("network_ids"))

        nodes = self.proxmox_service.get_nodes()
        node_check = self._check_node(target_node, nodes)
        node_is_valid = node_check.status != "error"

        templates = self.proxmox_service.get_templates()
        storages = self.proxmox_service.get_storages(target_node) if target_node and node_is_valid else []
        networks = self.proxmox_service.get_networks(target_node) if target_node and node_is_valid else []

        template_match = self._find_template(template_id, templates)
        checks = [
            node_check,
            self._check_template(template_id, template_match),
            self._check_template_readiness(template_id, template_match),
            self._check_storage(storage_id, storages, target_node),
            self._check_networks(network_ids, networks, target_node),
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
            },
        }

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

    def _check_storage(self, storage_id: str, storages: list[dict[str, Any]], target_node: str) -> ResourceCheck:
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

        match = next((storage for storage in storages if self._resource_id(storage, "id", "storage_id", "name") == storage_id), None)
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
