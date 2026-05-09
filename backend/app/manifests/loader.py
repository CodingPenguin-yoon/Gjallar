"""Builtin manifest loaders for the first Gjallar MVP slice."""

from __future__ import annotations

from app.manifests.models import (
    AccessDefaults,
    HardwareDefaults,
    NetworkProfile,
    ProfileNetworkDefaults,
    TemplateProfile,
    VmProfile,
)

_MVP_TARGET_NODES = ("yoonmanserver2", "yoonmanserver3")


def load_builtin_profiles() -> list[VmProfile]:
    """Load VM profile defaults locked by the PRD decision documents."""
    return [
        VmProfile(
            profile_id="general-vm",
            display_name="General VM",
            create_enabled=True,
            hardware=HardwareDefaults(cpu=2, memory_mb=4096, disk_gb=40),
            access=AccessDefaults(cloud_init_user="yoon", password_login=False),
            network=ProfileNetworkDefaults(network_profile="server-net", default_ip_mode="static"),
            target_node_candidates=_MVP_TARGET_NODES,
            template_family="ubuntu",
        ),
        VmProfile(
            profile_id="runtime-server",
            display_name="Runtime server candidate",
            create_enabled=False,
            hardware=HardwareDefaults(cpu=2, memory_mb=4096, disk_gb=40),
            access=AccessDefaults(cloud_init_user="yoon", password_login=False),
            network=ProfileNetworkDefaults(network_profile="server-net", default_ip_mode="static"),
            target_node_candidates=_MVP_TARGET_NODES,
            template_family="ubuntu",
        ),
        VmProfile(
            profile_id="dev-server",
            display_name="Development server candidate",
            create_enabled=False,
            hardware=HardwareDefaults(cpu=2, memory_mb=4096, disk_gb=40),
            access=AccessDefaults(cloud_init_user="yoon", password_login=False),
            network=ProfileNetworkDefaults(network_profile="server-net", default_ip_mode="static"),
            target_node_candidates=_MVP_TARGET_NODES,
            template_family="ubuntu",
        ),
        VmProfile(
            profile_id="db-server",
            display_name="Database server candidate",
            create_enabled=False,
            hardware=HardwareDefaults(cpu=2, memory_mb=4096, disk_gb=40),
            access=AccessDefaults(cloud_init_user="yoon", password_login=False),
            network=ProfileNetworkDefaults(network_profile="server-net", default_ip_mode="static"),
            target_node_candidates=_MVP_TARGET_NODES,
            template_family="ubuntu",
        ),
    ]


def load_builtin_network_profiles() -> list[NetworkProfile]:
    """Load NetworkProfile defaults for the MVP target nodes."""
    return [
        NetworkProfile(
            network_id="server-net",
            display_name="Server network",
            node_bridges={"yoonmanserver2": "vmbr0", "yoonmanserver3": "vmbr0"},
            allowed_ip_modes=("dhcp", "static"),
            default_ip_mode="static",
            create_ip_range="192.168.2.140-150",
        )
    ]


def load_builtin_templates() -> list[TemplateProfile]:
    """Load template defaults for the MVP skeleton.

    Live VMID/name/storage validation is intentionally deferred to the later
    read-only inventory and preflight Sets.
    """
    return [
        TemplateProfile(
            template_id="ubuntu-template",
            family="ubuntu",
            display_name="Ubuntu cloud-init template",
            metadata={"source": "prd-default"},
        )
    ]
