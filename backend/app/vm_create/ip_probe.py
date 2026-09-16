"""Single-address ICMP evidence from the Gjallar backend network."""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import AddressValueError, IPv4Address
import platform
import shutil
import subprocess


@dataclass(frozen=True)
class IpProbeResult:
    status: str
    reason: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "status": self.status,
            "reason": self.reason,
            "source": "icmp",
            "execution_location": "gjallar_backend",
        }


def probe_ipv4(address: str) -> IpProbeResult:
    """Observe a reply; no reply or an execution failure never proves an IP free."""
    if not isinstance(address, str):
        return IpProbeResult("unavailable", "invalid_ipv4")
    try:
        target = IPv4Address(address)
    except AddressValueError:
        return IpProbeResult("unavailable", "invalid_ipv4")
    if target.is_unspecified or target.is_multicast or target == IPv4Address("255.255.255.255"):
        return IpProbeResult("unavailable", "invalid_target")

    system = platform.system()
    # iputils uses seconds for -W and exit 1 for no reply; macOS uses
    # milliseconds for -W and exit 2 for a sent probe without a reply.
    if system == "Linux":
        options = ["-n", "-c", "1", "-W", "1", "-w", "2"]
        no_reply_code = 1
    elif system == "Darwin":
        options = ["-n", "-c", "1", "-W", "1000", "-t", "2"]
        no_reply_code = 2
    else:
        return IpProbeResult("unavailable", "unsupported_platform")

    executable = shutil.which("ping")
    if not executable:
        return IpProbeResult("unavailable", "ping_not_found")
    try:
        completed = subprocess.run(
            [executable, *options, str(target)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            check=False,
            timeout=3,
        )
    except subprocess.TimeoutExpired:
        return IpProbeResult("unavailable", "process_timeout")
    except FileNotFoundError:
        return IpProbeResult("unavailable", "ping_not_found")
    except PermissionError:
        return IpProbeResult("unavailable", "permission_denied")
    except OSError:
        return IpProbeResult("unavailable", "execution_error")

    if completed.returncode == 0:
        return IpProbeResult("reply", "echo_reply")
    if completed.returncode == no_reply_code:
        return IpProbeResult("no_reply", "no_echo_reply")
    return IpProbeResult("unavailable", "execution_error")
