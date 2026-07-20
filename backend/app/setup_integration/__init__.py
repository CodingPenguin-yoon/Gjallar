"""Setup and external integration application contracts."""

from app.setup_integration.proxmox_connection import ProxmoxConnectionStatus, observe_proxmox_connection

__all__ = ["ProxmoxConnectionStatus", "observe_proxmox_connection"]
