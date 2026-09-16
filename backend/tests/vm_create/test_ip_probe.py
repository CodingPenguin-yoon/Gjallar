"""Bounded ICMP evidence never treats an unanswered probe as an unused IP."""

from dataclasses import FrozenInstanceError
import subprocess
from unittest.mock import Mock

import pytest

from app.vm_create import ip_probe


@pytest.fixture(autouse=True)
def ping_runtime(monkeypatch):
    monkeypatch.setattr(ip_probe.platform, "system", lambda: "Linux")
    monkeypatch.setattr(ip_probe.shutil, "which", lambda executable: "/usr/bin/ping")
    run = Mock(return_value=subprocess.CompletedProcess(args=[], returncode=0))
    monkeypatch.setattr(ip_probe.subprocess, "run", run)
    return run


@pytest.mark.parametrize("system,options,no_reply_code", [
    ("Linux", ["-n", "-c", "1", "-W", "1", "-w", "2"], 1),
    ("Darwin", ["-n", "-c", "1", "-W", "1000", "-t", "2"], 2),
])
def test_probe_uses_platform_timeout_and_single_numeric_target(
    monkeypatch, ping_runtime, system, options, no_reply_code,
):
    monkeypatch.setattr(ip_probe.platform, "system", lambda: system)

    result = ip_probe.probe_ipv4("192.0.2.50")

    assert result.status == "reply"
    ping_runtime.assert_called_once_with(
        ["/usr/bin/ping", *options, "192.0.2.50"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
        check=False,
        timeout=3,
    )
    ping_runtime.return_value = subprocess.CompletedProcess(args=[], returncode=no_reply_code)
    result = ip_probe.probe_ipv4("192.0.2.50")
    assert result.status == "no_reply"
    assert result.reason == "no_echo_reply"


@pytest.mark.parametrize("address", [
    "example.com", "192.0.2.50/24", "::1", "192.0.2.50;echo secret",
    "-f", "192.0.2.50 192.0.2.51", "$(hostname)", "192.000.2.50",
    "192.0.2.256", " 192.0.2.50", "192.0.2.50\n", "", None, 1234,
])
def test_non_numeric_or_malformed_ipv4_never_starts_process(address, ping_runtime):
    assert ip_probe.probe_ipv4(address) == ip_probe.IpProbeResult("unavailable", "invalid_ipv4")
    ping_runtime.assert_not_called()


@pytest.mark.parametrize("address", ["0.0.0.0", "224.0.0.1", "255.255.255.255"])
def test_non_unicast_target_never_starts_process(address, ping_runtime):
    result = ip_probe.probe_ipv4(address)
    assert result == ip_probe.IpProbeResult("unavailable", "invalid_target")
    ping_runtime.assert_not_called()


def test_unsupported_platform_is_unavailable(monkeypatch, ping_runtime):
    monkeypatch.setattr(ip_probe.platform, "system", lambda: "Windows")
    result = ip_probe.probe_ipv4("192.0.2.50")
    assert result == ip_probe.IpProbeResult("unavailable", "unsupported_platform")
    ping_runtime.assert_not_called()


def test_missing_ping_is_unavailable(monkeypatch, ping_runtime):
    monkeypatch.setattr(ip_probe.shutil, "which", lambda executable: None)
    assert ip_probe.probe_ipv4("192.0.2.50") == ip_probe.IpProbeResult("unavailable", "ping_not_found")
    ping_runtime.assert_not_called()


@pytest.mark.parametrize("error,reason", [
    (subprocess.TimeoutExpired(cmd="ping", timeout=3), "process_timeout"),
    (FileNotFoundError("sensitive path"), "ping_not_found"),
    (PermissionError("sensitive path"), "permission_denied"),
    (OSError("sensitive host details"), "execution_error"),
])
def test_process_failures_return_explicit_unavailability_without_raw_error(ping_runtime, error, reason):
    ping_runtime.side_effect = error
    result = ip_probe.probe_ipv4("192.0.2.50")
    assert result == ip_probe.IpProbeResult("unavailable", reason)
    assert "sensitive" not in str(result.to_dict())


@pytest.mark.parametrize("system,returncode", [("Linux", 2), ("Darwin", 1), ("Linux", -9), ("Darwin", 77)])
def test_non_response_exit_errors_are_unavailable(monkeypatch, ping_runtime, system, returncode):
    monkeypatch.setattr(ip_probe.platform, "system", lambda: system)
    ping_runtime.return_value = subprocess.CompletedProcess(args=[], returncode=returncode)
    assert ip_probe.probe_ipv4("192.0.2.50") == ip_probe.IpProbeResult("unavailable", "execution_error")


def test_result_has_safe_provenance_and_is_immutable():
    result = ip_probe.IpProbeResult("reply")
    assert result.to_dict() == {
        "status": "reply", "reason": "", "source": "icmp", "execution_location": "gjallar_backend",
    }
    with pytest.raises(FrozenInstanceError):
        result.status = "unused"
