"""Builtin manifest loaders for the first Gjallar MVP slice."""

from __future__ import annotations

from app.manifests.models import (
    AccessDefaults,
    HardwareLimit,
    NetworkProfile,
    ProfileHardware,
    TemplateProfile,
    VmProfile,
)

_MVP_TARGET_NODES = ("yoonmanserver2", "yoonmanserver3")


def load_builtin_profiles() -> list[VmProfile]:
    """Load initial Create VM profile definitions for the manual DB seed."""
    return [
        VmProfile(
            profile_id="general-vm",
            display_name="General VM",
            display_name_ko="범용 VM",
            enabled=True,
            hardware=ProfileHardware(
                cpu=HardwareLimit(default=2, min=1, max=8),
                memory_mb=HardwareLimit(default=4096, min=1024, max=32768),
                disk_gb=HardwareLimit(default=50, min=50, max=500),
            ),
            access=AccessDefaults(default_user="yoon"),
            target_node_candidates=_MVP_TARGET_NODES,
            template_family="ubuntu",
        ),
        VmProfile(
            profile_id="runtime-server",
            display_name="Runtime Server",
            display_name_ko="서비스 실행용 VM",
            enabled=True,
            hardware=ProfileHardware(
                cpu=HardwareLimit(default=4, min=2, max=16),
                memory_mb=HardwareLimit(default=8192, min=4096, max=65536),
                disk_gb=HardwareLimit(default=100, min=80, max=1000),
            ),
            access=AccessDefaults(default_user="yoon"),
            target_node_candidates=_MVP_TARGET_NODES,
            template_family="ubuntu",
        ),
        VmProfile(
            profile_id="development-vm",
            display_name="Development VM",
            display_name_ko="개발/테스트용 VM",
            enabled=True,
            hardware=ProfileHardware(
                cpu=HardwareLimit(default=2, min=1, max=12),
                memory_mb=HardwareLimit(default=4096, min=2048, max=32768),
                disk_gb=HardwareLimit(default=50, min=50, max=500),
            ),
            access=AccessDefaults(default_user="yoon"),
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
