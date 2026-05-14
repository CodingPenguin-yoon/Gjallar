"""VMInstance manifest rendering for Create VM review plans."""

from __future__ import annotations

from typing import Any

import yaml

from app.vm_create.models import PreflightResult, VmCreateDraft


def vm_instance_manifest_path(manifest_id: str) -> str:
    return f"manifests/vms/{manifest_id}.yaml"


def build_vm_instance_manifest(draft: VmCreateDraft, preflight: PreflightResult) -> dict[str, Any]:
    """Build the desired-state manifest that a later approved GitOps step writes."""
    return {
        "apiVersion": "gjallar/v1",
        "kind": "VMInstance",
        "metadata": {
            "id": draft.manifest_id,
            "name": draft.vm_name,
            "owner": draft.operator_id,
            "request_id": draft.job_id,
        },
        "spec": {
            "proxmox_vmid": draft.proposed_vmid,
            "proxmox_vmid_allocation": {
                "mode": "proxmox_nextid",
                "resolved_at_plan": True,
            },
            "state_backend": {
                "type": "local",
                "path": draft.terraform_state_path,
            },
            "node": draft.target_node_id,
            "profile_id": draft.profile_id,
            "template_id": preflight.selected_template_id,
            "template_source": {
                "node": preflight.selected_template_node_id,
                "vmid": preflight.selected_template_vmid,
            },
            "hardware": draft.hardware.to_dict(),
            "storage": preflight.selected_storage_id,
            "access": {
                "cloud_init_user": draft.access.cloud_init_user,
                "ssh_key_source": draft.access.ssh_key_source,
                "password_login": "enabled" if draft.access.password_login else "disabled",
            },
            "network": {
                "profile_id": draft.network.network_id,
                "bridge_id": preflight.selected_bridge_id,
                "ip_mode": draft.network.ip_mode,
                "static_ip": draft.network.static_ip,
                "prefix": draft.network.prefix,
                "gateway": draft.network.gateway,
                "ip": draft.network.static_ip,
            },
            "lifecycle": {
                "desired_power_state": "running" if draft.first_power_on_included else "stopped",
            },
            "safety": {
                "require_approval_for_apply": True,
            },
        },
        "status": {
            "phase": "pending",
            "last_error": "",
            "updated_at": "",
        },
    }


def render_vm_instance_manifest_yaml(manifest: dict[str, Any]) -> str:
    return yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True)
