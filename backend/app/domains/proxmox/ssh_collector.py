"""Optional read-only SSH guest evidence collector for operational risks.

The collector is disabled by default and intentionally small. It only executes
predefined read-only command identifiers, never accepts arbitrary command text,
and returns ``None`` when disabled/unconfigured so dashboard evidence remains
explicitly uncollected instead of falsely healthy.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

READ_ONLY_SSH_COMMANDS: Dict[str, tuple[str, ...]] = {
    "os_release": ("cat", "/etc/os-release"),
    "disk_usage": ("df", "-P", "-T"),
    "qemu_guest_agent_status": ("systemctl", "is-active", "qemu-guest-agent"),
}

_DEFAULT_COMMAND_IDS = ("os_release",)
SENSITIVE_SSH_TARGET_FIELDS = {
    "password",
    "passphrase",
    "private_key",
    "private_key_data",
    "ssh_key",
    "ssh_private_key",
    "key_data",
}
SENSITIVE_TARGET_KEY_MARKERS = ("password", "passphrase", "secret", "token", "private", "credential")


@dataclass(frozen=True)
class SSHCollectorConfig:
    """Configuration for the optional SSH collector.

    ``targets`` is keyed by the Gjallar VM resource key (``node/vmid``). Target
    dictionaries may contain ``host``, ``user``, ``port``, and ``key_path``.
    Private key material and passwords are not accepted by this contract.
    """

    enabled: bool = False
    targets: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    command_ids: Sequence[str] = field(default_factory=lambda: _DEFAULT_COMMAND_IDS)
    timeout_seconds: float = 5.0
    connect_timeout_seconds: float = 3.0
    extra_redactions: Sequence[str] = field(default_factory=tuple)

    @classmethod
    def from_env(cls) -> "SSHCollectorConfig":
        """Build config from environment without requiring real credentials."""

        enabled = _env_bool("GJALLAR_SSH_COLLECTOR_ENABLED", default=False)
        targets = _read_targets_json(os.getenv("GJALLAR_SSH_COLLECTOR_TARGETS_JSON", ""))
        command_ids = _read_csv_env("GJALLAR_SSH_COLLECTOR_COMMANDS", default=_DEFAULT_COMMAND_IDS)
        return cls(
            enabled=enabled,
            targets=targets,
            command_ids=command_ids,
            timeout_seconds=_read_float_env("GJALLAR_SSH_COLLECTOR_TIMEOUT_SECONDS", 5.0, minimum=0.5),
            connect_timeout_seconds=_read_float_env("GJALLAR_SSH_COLLECTOR_CONNECT_TIMEOUT_SECONDS", 3.0, minimum=0.5),
            extra_redactions=_read_csv_env("GJALLAR_SSH_COLLECTOR_REDACT_VALUES", default=()),
        )


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _read_float_env(name: str, default: float, *, minimum: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(float(raw), minimum)
    except (TypeError, ValueError):
        return default


def _read_csv_env(name: str, *, default: Sequence[str]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return tuple(default)
    values = tuple(part.strip() for part in raw.split(",") if part.strip())
    return values or tuple(default)


def _read_targets_json(raw: str) -> Dict[str, Dict[str, Any]]:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, Mapping):
        return {}
    targets: Dict[str, Dict[str, Any]] = {}
    for key, value in parsed.items():
        if not isinstance(value, Mapping):
            continue
        resource_key = str(key or "").strip()
        if not resource_key:
            continue
        target = {str(target_key): target_value for target_key, target_value in value.items()}
        targets[resource_key] = target
    return targets


def redact_ssh_message(message: object, redactions: Sequence[object] = ()) -> str:
    """Redact configured endpoint/key/secret fragments from SSH errors."""

    text = str(message)
    sensitive_values = {str(value) for value in redactions if str(value or "").strip()}
    for value in sorted(sensitive_values, key=len, reverse=True):
        text = text.replace(value, "[REDACTED]")
    return text


class ReadOnlySSHCollector:
    """Collect optional guest evidence with a fail-closed SSH allowlist."""

    def __init__(
        self,
        config: Optional[SSHCollectorConfig] = None,
        *,
        executor: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.config = config or SSHCollectorConfig.from_env()
        self.executor = executor or self._default_executor

    def collect_for_vms(
        self,
        vms: Sequence[Mapping[str, Any]],
        *,
        now_epoch: Optional[float] = None,
    ) -> Optional[Dict[str, Dict[str, Any]]]:
        """Return SSH evidence by ``node/vmid`` or ``None`` when uncollected."""

        if not self.config.enabled:
            return None
        if not self.config.targets:
            return None

        target_vms = [vm for vm in (vms or []) if self._target_for_vm(vm) is not None]
        if not target_vms:
            return {}

        blocked_commands = [
            command_id for command_id in self.config.command_ids if command_id not in READ_ONLY_SSH_COMMANDS
        ]
        if blocked_commands:
            return {
                self._resource_key(vm): self._blocked_record(vm, blocked_commands, now_epoch=now_epoch)
                for vm in target_vms
            }

        evidence: Dict[str, Dict[str, Any]] = {}
        for vm in target_vms:
            key = self._resource_key(vm)
            target = self._target_for_vm(vm) or {}
            evidence[key] = self._collect_one_vm(key, vm, target, now_epoch=now_epoch)
        return evidence

    def _collect_one_vm(
        self,
        key: str,
        vm: Mapping[str, Any],
        target: Mapping[str, Any],
        *,
        now_epoch: Optional[float],
    ) -> Dict[str, Any]:
        target_error = self._validate_target(target)
        if target_error:
            return self._blocked_record(
                vm,
                list(self.config.command_ids),
                now_epoch=now_epoch,
                reason="invalid_target",
                error=self._redact_for_target(f"{target_error}: [REDACTED]", target),
            )

        command_results: Dict[str, Dict[str, Any]] = {}
        for command_id in self.config.command_ids:
            argv = self._build_ssh_argv(target, READ_ONLY_SSH_COMMANDS[command_id])
            try:
                result = self.executor(argv, timeout_seconds=self.config.timeout_seconds)
            except Exception as exc:  # noqa: BLE001 - evidence collection must fail closed
                return self._failed_record(
                    vm,
                    status="failed",
                    reason="ssh_execution_failed",
                    error=self._redact_for_target(exc, target),
                    now_epoch=now_epoch,
                )

            returncode = int(_result_field(result, "returncode", _result_field(result, "exit_code", 0)) or 0)
            stdout = str(_result_field(result, "stdout", "") or "")
            stderr = str(_result_field(result, "stderr", "") or "")
            if returncode != 0:
                return self._failed_record(
                    vm,
                    status="failed",
                    reason="ssh_command_failed",
                    error=self._redact_for_target(stderr or stdout or f"ssh command exited {returncode}", target),
                    now_epoch=now_epoch,
                )
            command_results[command_id] = self._summarize_command_output(command_id, stdout)

        return {
            "source": "optional_readonly_ssh",
            "node": str(vm.get("node") or ""),
            "vmid": _safe_int(vm.get("vmid"), 0),
            "collected": True,
            "status": "collected",
            "reason": "ok",
            "command_ids": list(self.config.command_ids),
            "command_results": command_results,
            "collected_at": _now(now_epoch),
        }

    def _blocked_record(
        self,
        vm: Mapping[str, Any],
        blocked_commands: Sequence[str],
        *,
        now_epoch: Optional[float],
        reason: str = "command_not_allowlisted",
        error: str = "SSH command id is not in the read-only allowlist.",
    ) -> Dict[str, Any]:
        return {
            "source": "optional_readonly_ssh",
            "node": str(vm.get("node") or ""),
            "vmid": _safe_int(vm.get("vmid"), 0),
            "collected": False,
            "status": "blocked",
            "reason": reason,
            "blocked_commands": list(blocked_commands),
            "command_ids": list(self.config.command_ids),
            "error": error,
            "collected_at": _now(now_epoch),
        }

    def _failed_record(
        self,
        vm: Mapping[str, Any],
        *,
        status: str,
        reason: str,
        error: str,
        now_epoch: Optional[float],
    ) -> Dict[str, Any]:
        return {
            "source": "optional_readonly_ssh",
            "node": str(vm.get("node") or ""),
            "vmid": _safe_int(vm.get("vmid"), 0),
            "collected": False,
            "status": status,
            "reason": reason,
            "command_ids": list(self.config.command_ids),
            "error": error,
            "collected_at": _now(now_epoch),
        }

    def _validate_target(self, target: Mapping[str, Any]) -> str | None:
        sensitive_fields = {str(field_name or "").strip().lower() for field_name in target}
        if sensitive_fields & SENSITIVE_SSH_TARGET_FIELDS:
            return "unsupported sensitive SSH target fields"

        host = str(target.get("host") or "").strip()
        if not host:
            return "missing SSH host"
        if host.startswith("-") or any(ch.isspace() for ch in host):
            return "invalid SSH host"

        user = str(target.get("user") or "").strip()
        if user and (user.startswith("-") or any(ch.isspace() for ch in user) or "@" in user):
            return "invalid SSH user"

        port = str(target.get("port") or "").strip()
        if port:
            try:
                port_value = int(port)
            except ValueError:
                return "invalid SSH port"
            if not 1 <= port_value <= 65535:
                return "invalid SSH port"

        key_path = str(target.get("key_path") or "").strip()
        if key_path.startswith("-"):
            return "invalid SSH key path"

        return None

    def _build_ssh_argv(self, target: Mapping[str, Any], command_args: Sequence[str]) -> list[str]:
        host = str(target.get("host") or "").strip()
        user = str(target.get("user") or "").strip()
        destination = f"{user}@{host}" if user else host
        argv = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"ConnectTimeout={int(max(1.0, self.config.connect_timeout_seconds))}",
        ]
        key_path = str(target.get("key_path") or "").strip()
        if key_path:
            argv.extend(["-o", "IdentitiesOnly=yes", "-i", key_path])
        port = str(target.get("port") or "").strip()
        if port:
            argv.extend(["-p", str(int(port))])
        argv.append(destination)
        argv.extend(command_args)
        return argv

    def _target_for_vm(self, vm: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
        key = self._resource_key(vm)
        target = self.config.targets.get(key)
        return target if isinstance(target, Mapping) else None

    def _resource_key(self, vm: Mapping[str, Any]) -> str:
        return f"{vm.get('node')}/{vm.get('vmid')}"

    def _redact_for_target(self, message: object, target: Mapping[str, Any]) -> str:
        redactions = list(self.config.extra_redactions)
        for field_name, raw_value in target.items():
            value = str(raw_value or "").strip()
            normalized_field = str(field_name or "").strip().lower()
            if value and (
                normalized_field in {"host", "key_path"}
                or normalized_field in SENSITIVE_SSH_TARGET_FIELDS
                or any(marker in normalized_field for marker in SENSITIVE_TARGET_KEY_MARKERS)
            ):
                redactions.append(value)
        host = str(target.get("host") or "").strip()
        user = str(target.get("user") or "").strip()
        if host and user:
            redactions.append(f"{user}@{host}")
        return redact_ssh_message(message, redactions)

    def _summarize_command_output(self, command_id: str, stdout: str) -> Dict[str, Any]:
        lines = [line.strip() for line in stdout.splitlines() if line.strip()]
        summary: Dict[str, Any] = {"stdout_lines": len(lines)}
        if command_id == "os_release":
            pretty_name = _parse_os_release_pretty_name(lines)
            if pretty_name:
                summary["pretty_name"] = pretty_name
        elif command_id == "qemu_guest_agent_status" and lines:
            summary["service_state"] = lines[0][:64]
        elif command_id == "disk_usage":
            summary["filesystems_reported"] = max(0, len(lines) - 1)
        return summary

    def _default_executor(self, argv: Sequence[str], *, timeout_seconds: float) -> Dict[str, Any]:
        completed = subprocess.run(  # noqa: S603 - argv is built from a fixed allowlist, no shell.
            list(argv),
            check=False,
            capture_output=True,
            text=True,
            timeout=max(0.5, float(timeout_seconds)),
        )
        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }


def _parse_os_release_pretty_name(lines: Sequence[str]) -> str:
    for line in lines:
        key, separator, value = line.partition("=")
        if separator and key == "PRETTY_NAME":
            return value.strip().strip('"')[:128]
    return ""


def _result_field(result: Any, field_name: str, default: Any) -> Any:
    if isinstance(result, Mapping):
        return result.get(field_name, default)
    return getattr(result, field_name, default)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _now(now_epoch: Optional[float]) -> float:
    return float(now_epoch if now_epoch is not None else time.time())
