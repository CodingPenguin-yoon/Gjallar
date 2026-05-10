"""IaC-backed network policy helpers for Gjallar network profiles."""

from __future__ import annotations

import os
import subprocess
from ipaddress import ip_address
from pathlib import Path
from typing import Any

import yaml

from app.proxmox.models import NetworkInventory
from app.vm_create.paths import iac_root

POLICY_RELATIVE_PATH = Path("manifests") / "networks" / "network-profiles.yaml"


class NetworkPolicyError(RuntimeError):
    """Raised when a network policy cannot be read or written safely."""


def _policy_path(root: Path | None = None) -> Path:
    base = (root or iac_root()).expanduser().resolve()
    target = (base / POLICY_RELATIVE_PATH).resolve()
    if not target.is_relative_to(base):
        raise NetworkPolicyError("network policy path escaped IaC root")
    return target


def _empty_policy() -> dict[str, Any]:
    return {
        "apiVersion": "gjallar/v1",
        "kind": "NetworkPolicySet",
        "networks": [],
    }


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _normalize_dns(value: Any) -> list[str]:
    if isinstance(value, str):
        candidates = [item.strip() for item in value.replace("\n", ",").split(",")]
    elif isinstance(value, list):
        candidates = [str(item).strip() for item in value]
    else:
        candidates = []
    return [item for item in candidates if item]


def _normalize_static_ip_ranges(value: Any, legacy_ip_range: Any = None) -> list[dict[str, str]]:
    raw_ranges = value if isinstance(value, list) else []
    ranges: list[dict[str, str]] = []
    for raw_range in raw_ranges:
        if not isinstance(raw_range, dict):
            continue
        start = str(raw_range.get("start") or "").strip()
        end = str(raw_range.get("end") or "").strip()
        if start or end:
            ranges.append({"start": start, "end": end})

    if ranges:
        return ranges

    legacy_text = str(legacy_ip_range or "").strip()
    if not legacy_text:
        return []
    for part in [item.strip() for item in legacy_text.replace("\n", ",").split(",") if item.strip()]:
        start, separator, end = part.partition("-")
        ranges.append({"start": start.strip(), "end": (end if separator else start).strip()})
    return ranges


def normalize_network_policy(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Return a stable NetworkPolicySet document shape."""
    payload = payload or {}
    normalized_networks: list[dict[str, Any]] = []
    for raw_network in _as_list(payload.get("networks")):
        if not isinstance(raw_network, dict):
            continue
        network_id = str(raw_network.get("network_id") or raw_network.get("id") or "").strip()
        if not network_id:
            continue
        nodes: list[dict[str, Any]] = []
        for raw_node in _as_list(raw_network.get("nodes")):
            if not isinstance(raw_node, dict):
                continue
            node_id = str(raw_node.get("node_id") or "").strip()
            bridge_id = str(raw_node.get("bridge_id") or "").strip()
            if not node_id or not bridge_id:
                continue
            nodes.append(
                {
                    "node_id": node_id,
                    "bridge_id": bridge_id,
                    "subnet": str(raw_node.get("subnet") or "").strip(),
                    "gateway": str(raw_node.get("gateway") or "").strip(),
                    "dns": _normalize_dns(raw_node.get("dns")),
                    "static_ip_ranges": _normalize_static_ip_ranges(
                        raw_node.get("static_ip_ranges"),
                        raw_node.get("ip_range"),
                    ),
                }
            )
        normalized_networks.append(
            {
                "network_id": network_id,
                "display_name": str(raw_network.get("display_name") or network_id).strip(),
                "description": str(raw_network.get("description") or "").strip(),
                "nodes": nodes,
            }
        )
    return {
        "apiVersion": str(payload.get("apiVersion") or "gjallar/v1"),
        "kind": str(payload.get("kind") or "NetworkPolicySet"),
        "networks": normalized_networks,
    }


def load_network_policy() -> dict[str, Any]:
    """Load the IaC network policy file, returning an empty policy if absent."""
    path = _policy_path()
    if not path.is_file():
        return _empty_policy()
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise NetworkPolicyError("network policy YAML must be a mapping")
    return normalize_network_policy(loaded)


def _policy_bindings(policy: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    bindings: dict[tuple[str, str], dict[str, Any]] = {}
    for network in _as_list(policy.get("networks")):
        if not isinstance(network, dict):
            continue
        network_id = str(network.get("network_id") or "")
        display_name = str(network.get("display_name") or network_id)
        for node in _as_list(network.get("nodes")):
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("node_id") or "")
            bridge_id = str(node.get("bridge_id") or "")
            if node_id and bridge_id:
                bindings[(node_id, bridge_id)] = {
                    **node,
                    "network_id": network_id,
                    "display_name": display_name,
                }
    return bindings


def find_network_policy_binding(
    policy: dict[str, Any],
    *,
    node_id: str,
    bridge_id: str | None,
    network_id: str | None = None,
) -> dict[str, Any] | None:
    """Return the IaC policy binding for one node/bridge pair."""
    if not bridge_id:
        return None
    normalized = normalize_network_policy(policy)
    for network in _as_list(normalized.get("networks")):
        if not isinstance(network, dict):
            continue
        current_network_id = str(network.get("network_id") or "")
        if network_id and current_network_id != network_id:
            continue
        for node in _as_list(network.get("nodes")):
            if not isinstance(node, dict):
                continue
            if str(node.get("node_id") or "") != node_id:
                continue
            if str(node.get("bridge_id") or "") != bridge_id:
                continue
            return {
                **node,
                "network_id": current_network_id,
                "display_name": str(network.get("display_name") or current_network_id),
            }
    return None


def ip_in_static_ranges(value: str, ranges: list[dict[str, str]]) -> bool:
    """Return whether an IPv4 address is included in the configured static ranges."""
    try:
        candidate = ip_address(str(value or "").strip())
    except ValueError:
        return False
    if candidate.version != 4:
        return False

    for static_range in _as_list(ranges):
        if not isinstance(static_range, dict):
            continue
        start_text = str(static_range.get("start") or "").strip()
        end_text = str(static_range.get("end") or start_text).strip()
        if not start_text or not end_text:
            continue
        try:
            start = ip_address(start_text)
            end = ip_address(end_text)
        except ValueError:
            continue
        if start.version != candidate.version or end.version != candidate.version:
            continue
        if start <= candidate <= end:
            return True
    return False


def build_network_policy_view(discovered_networks: list[NetworkInventory]) -> dict[str, Any]:
    """Combine live vmbr inventory with IaC policy registration state."""
    root = iac_root().expanduser().resolve()
    path = _policy_path(root)
    policy = load_network_policy()
    bindings = _policy_bindings(policy)
    rows: list[dict[str, Any]] = []
    discovered_keys: set[tuple[str, str]] = set()
    for network in sorted(discovered_networks, key=lambda item: (item.node_id, item.bridge_id)):
        key = (network.node_id, network.bridge_id)
        discovered_keys.add(key)
        binding = bindings.get(key)
        rows.append(
            {
                **network.to_dict(),
                "registered": binding is not None,
                "policy": binding,
            }
        )

    missing = [
        {
            "node_id": node_id,
            "bridge_id": bridge_id,
            "policy": binding,
        }
        for (node_id, bridge_id), binding in sorted(bindings.items())
        if (node_id, bridge_id) not in discovered_keys
    ]
    return {
        "iac_root": str(root),
        "policy_path": str(path),
        "policy_relative_path": str(POLICY_RELATIVE_PATH),
        "policy_exists": path.is_file(),
        "policy": policy,
        "discovered": [network.to_dict() for network in discovered_networks],
        "bridges": rows,
        "missing_policy_bridges": missing,
        "side_effects": [],
    }


def _run_git(root: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": os.getenv("GJALLAR_GIT_AUTHOR_NAME", "Gjallar"),
        "GIT_AUTHOR_EMAIL": os.getenv("GJALLAR_GIT_AUTHOR_EMAIL", "gjallar@localhost"),
        "GIT_COMMITTER_NAME": os.getenv("GJALLAR_GIT_COMMITTER_NAME", "Gjallar"),
        "GIT_COMMITTER_EMAIL": os.getenv("GJALLAR_GIT_COMMITTER_EMAIL", "gjallar@localhost"),
    }
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "git command failed").strip()
        raise NetworkPolicyError(message)
    return completed.stdout.strip()


def save_network_policy(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Write the network policy to the shared IaC repo and commit if changed."""
    root = iac_root().expanduser().resolve()
    target = _policy_path(root)
    policy = normalize_network_policy(payload)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(policy, sort_keys=False, allow_unicode=True)
    target.write_text(text, encoding="utf-8")

    side_effects = ["network_policy_written"]
    commit_sha = ""
    if (root / ".git").exists():
        relative_path = str(POLICY_RELATIVE_PATH)
        _run_git(root, "add", "--", relative_path)
        status = _run_git(root, "status", "--porcelain", "--", relative_path)
        if status.strip():
            _run_git(root, "commit", "-m", "feat: update network policy")
            commit_sha = _run_git(root, "rev-parse", "HEAD")
            side_effects.append("iac_git_commit_created")
        else:
            commit_sha = _run_git(root, "rev-parse", "HEAD")
            side_effects.append("network_policy_unchanged")

    return {
        "iac_root": str(root),
        "policy_path": str(target),
        "policy_relative_path": str(POLICY_RELATIVE_PATH),
        "policy": policy,
        "commit_sha": commit_sha,
        "side_effects": side_effects,
    }
