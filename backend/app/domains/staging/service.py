"""Staging host registry and pool preview service."""

from __future__ import annotations

from collections import defaultdict
import os
import re
import subprocess
from typing import Any

from sqlalchemy import or_, select

from app.shared.gitlab_settings import get_environment_port_range, normalize_deployment_environment
from app.shared.platform_db import create_platform_engine, create_session_factory
from app.shared.platform_models import StagingHost


READY_BOOTSTRAP_STATUS = "ready"


class StagingHostRegistryError(RuntimeError):
    """Raised when staging host registry operations fail validation."""


class StagingHostRegistryService:
    """Persist and expose environment-tagged host registry entries."""

    def __init__(self) -> None:
        self._engine = create_platform_engine()
        self._session_factory = create_session_factory(self._engine)

    def list_hosts(self, environment: str | None = None) -> list[dict[str, Any]]:
        normalized_environment = (
            normalize_deployment_environment(environment) if environment is not None else None
        )
        with self._session_factory() as session:
            statement = select(StagingHost).order_by(
                StagingHost.environment.asc(),
                StagingHost.pool_key.asc(),
                StagingHost.node.asc(),
                StagingHost.vmid.asc(),
            )
            if normalized_environment is not None:
                statement = statement.where(StagingHost.environment == normalized_environment)
            hosts = list(session.execute(statement).scalars())
            return [self._serialize_host(host) for host in hosts]

    def list_pools(self, environment: str | None = None) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for host in self.list_hosts(environment):
            grouped[(host["environment"], host["pool_key"])].append(host)

        pools: list[dict[str, Any]] = []
        for (pool_environment, pool_key), hosts in sorted(grouped.items(), key=lambda item: item[0]):
            ready_hosts = [host for host in hosts if self._is_ready_host(host)]
            blocked_hosts = [host for host in hosts if not self._is_ready_host(host)]
            state = "available" if ready_hosts else "full"
            pools.append(
                {
                    "environment": pool_environment,
                    "pool_key": pool_key,
                    "label": f"{pool_environment}:{pool_key}",
                    "state": state,
                    "total_hosts": len(hosts),
                    "ready_hosts": len(ready_hosts),
                    "blocked_hosts": len(blocked_hosts),
                    "sample_hosts": [self._serialize_pool_host_summary(host) for host in ready_hosts[:3]],
                }
            )
        return pools

    def preview_pool(
        self,
        *,
        environment: str,
        pool_key: str,
        requested_port: int | None = None,
    ) -> dict[str, Any]:
        normalized_environment = normalize_deployment_environment(environment)
        normalized_pool_key = str(pool_key or "").strip()
        if not normalized_pool_key:
            return self._empty_pool_preview(normalized_environment, None, requested_port)

        hosts = [
            host
            for host in self.list_hosts(normalized_environment)
            if str(host.get("pool_key") or "").strip() == normalized_pool_key
        ]
        if not hosts:
            return self._empty_pool_preview(normalized_environment, normalized_pool_key, requested_port)

        ready_hosts = [host for host in hosts if self._is_ready_host(host)]
        blocked_hosts = [host for host in hosts if not self._is_ready_host(host)]
        port_range = get_environment_port_range(normalized_environment)
        start = int(port_range["start"])
        end = int(port_range["end"])

        inspection_rows: list[dict[str, Any]] = []
        available_port_counts: dict[int, int] = defaultdict(int)
        inspection_errors: list[str] = []

        for host in ready_hosts:
            inspection = self._inspect_host_ports(host, start=start, end=end)
            inspection_rows.append(inspection)
            if inspection["inspect_ok"]:
                for port in inspection["available_ports"]:
                    available_port_counts[int(port)] += 1
            elif inspection.get("error"):
                inspection_errors.append(str(inspection["error"]))

        available_ports = sorted(available_port_counts.keys())
        requested_port_available = (
            requested_port in available_port_counts if requested_port is not None else False
        )
        suggested_port = (
            requested_port
            if requested_port_available
            else (available_ports[0] if available_ports else None)
        )
        selected_host = self._select_host_candidate(
            inspection_rows=inspection_rows,
            requested_port=requested_port,
        )

        if not ready_hosts:
            state = "full"
            summary = "등록된 host는 있지만 현재 ready 상태인 host가 없습니다."
        elif not available_ports:
            state = "full"
            summary = "ready host는 있지만 현재 허용 포트 범위에서 사용 가능한 포트가 없습니다."
        else:
            state = "available"
            summary = (
                f"ready host {len(ready_hosts)}대에서 {len(available_ports)}개의 사용 가능한 포트를 찾았습니다."
            )

        port_options = [
            {
                "port": port,
                "available_host_count": int(available_port_counts[port]),
                "selected": requested_port is not None and port == requested_port,
            }
            for port in available_ports[:24]
        ]
        if (
            requested_port is not None
            and requested_port in available_port_counts
            and requested_port not in {option["port"] for option in port_options}
        ):
            port_options.append(
                {
                    "port": requested_port,
                    "available_host_count": int(available_port_counts[requested_port]),
                    "selected": True,
                }
            )
            port_options.sort(key=lambda item: int(item["port"]))

        return {
            "environment": normalized_environment,
            "pool_key": normalized_pool_key,
            "label": f"{normalized_environment}:{normalized_pool_key}",
            "state": state,
            "summary": summary,
            "total_hosts": len(hosts),
            "ready_hosts": len(ready_hosts),
            "blocked_hosts": len(blocked_hosts),
            "sample_hosts": [self._serialize_pool_host_summary(host) for host in ready_hosts[:4]],
            "blocked_host_summaries": [self._serialize_pool_host_summary(host) for host in blocked_hosts[:4]],
            "port_range": port_range,
            "requested_port": requested_port,
            "requested_port_available": requested_port_available,
            "suggested_app_port": suggested_port,
            "available_port_count": len(available_ports),
            "available_port_options": port_options,
            "selected_host": selected_host,
            "inspection_errors": inspection_errors,
        }

    def register_host(self, payload: dict[str, Any]) -> dict[str, Any]:
        environment = normalize_deployment_environment(payload.get("environment"))
        node = str(payload.get("node") or "").strip()
        host_ip = str(payload.get("host_ip") or "").strip()
        host_user = str(payload.get("host_user") or "").strip() or None
        name = str(payload.get("name") or "").strip() or None
        pool_key = str(payload.get("pool_key") or "default").strip() or "default"
        role = str(payload.get("role") or "shared").strip() or "shared"
        bootstrap_status = str(payload.get("bootstrap_status") or READY_BOOTSTRAP_STATUS).strip() or READY_BOOTSTRAP_STATUS
        source_task_id = str(payload.get("source_task_id") or "").strip() or None

        try:
            vmid = int(payload.get("vmid"))
        except (TypeError, ValueError) as exc:
            raise StagingHostRegistryError("vmid must be an integer.") from exc

        if not node:
            raise StagingHostRegistryError("node is required.")
        if not host_ip:
            raise StagingHostRegistryError("host_ip is required.")

        now = self._now_iso()

        with self._session_factory.begin() as session:
            conflict = session.execute(
                select(StagingHost).where(
                    or_(
                        (StagingHost.node == node) & (StagingHost.vmid == vmid),
                        StagingHost.host_ip == host_ip,
                    )
                )
            ).scalars().all()

            existing = None
            for candidate in conflict:
                same_identity = candidate.node == node and candidate.vmid == vmid
                same_ip = candidate.host_ip == host_ip
                if same_identity:
                    existing = candidate
                    continue
                if same_ip:
                    raise StagingHostRegistryError(
                        f"host_ip {host_ip} is already registered to {candidate.node}/{candidate.vmid}."
                    )

            if existing is None:
                existing = StagingHost(
                    node=node,
                    vmid=vmid,
                    created_at=now,
                )
                session.add(existing)

            existing.environment = environment
            existing.name = name
            existing.host_ip = host_ip
            existing.host_user = host_user
            existing.pool_key = pool_key
            existing.role = role
            existing.bootstrap_status = bootstrap_status
            existing.enabled = bool(payload.get("enabled", True))
            existing.drain_mode = bool(payload.get("drain_mode", False))
            existing.source_task_id = source_task_id
            existing.updated_at = now

        with self._session_factory() as session:
            host = session.execute(
                select(StagingHost).where(StagingHost.node == node, StagingHost.vmid == vmid)
            ).scalar_one()
            return self._serialize_host(host)

    def _serialize_host(self, host: StagingHost) -> dict[str, Any]:
        return {
            "id": host.id,
            "environment": host.environment,
            "node": host.node,
            "vmid": host.vmid,
            "name": host.name,
            "host_ip": host.host_ip,
            "host_user": host.host_user,
            "pool_key": host.pool_key,
            "role": host.role,
            "bootstrap_status": host.bootstrap_status,
            "enabled": host.enabled,
            "drain_mode": host.drain_mode,
            "source_task_id": host.source_task_id,
            "created_at": host.created_at,
            "updated_at": host.updated_at,
        }

    def _serialize_pool_host_summary(self, host: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": host.get("id"),
            "name": host.get("name"),
            "node": host.get("node"),
            "vmid": host.get("vmid"),
            "host_ip": host.get("host_ip"),
            "host_user": host.get("host_user"),
            "bootstrap_status": host.get("bootstrap_status"),
            "enabled": host.get("enabled"),
            "drain_mode": host.get("drain_mode"),
        }

    def _empty_pool_preview(
        self,
        environment: str,
        pool_key: str | None,
        requested_port: int | None,
    ) -> dict[str, Any]:
        return {
            "environment": environment,
            "pool_key": pool_key,
            "label": f"{environment}:{pool_key}" if pool_key else environment,
            "state": "empty",
            "summary": "선택된 환경에 등록된 host pool이 없습니다.",
            "total_hosts": 0,
            "ready_hosts": 0,
            "blocked_hosts": 0,
            "sample_hosts": [],
            "blocked_host_summaries": [],
            "port_range": get_environment_port_range(environment),
            "requested_port": requested_port,
            "requested_port_available": False,
            "suggested_app_port": None,
            "available_port_count": 0,
            "available_port_options": [],
            "selected_host": None,
            "inspection_errors": [],
        }

    def _is_ready_host(self, host: dict[str, Any]) -> bool:
        bootstrap_status = str(host.get("bootstrap_status") or "").strip().lower()
        return (
            host.get("enabled") is not False
            and host.get("drain_mode") is not True
            and bootstrap_status == READY_BOOTSTRAP_STATUS
        )

    def _inspect_host_ports(self, host: dict[str, Any], *, start: int, end: int) -> dict[str, Any]:
        user = str(host.get("host_user") or os.getenv("ANSIBLE_SSH_USER", "root")).strip() or "root"
        host_ip = str(host.get("host_ip") or "").strip()
        target = f"{user}@{host_ip}" if user else host_ip
        command = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "ConnectTimeout=4",
        ]
        ssh_key = str(os.getenv("ANSIBLE_SSH_PRIVATE_KEY_FILE", "") or "").strip()
        if ssh_key:
            command.extend(["-i", ssh_key])
        command.extend([target, "ss -H -ltn || netstat -ltn"])

        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception as exc:
            return {
                **self._serialize_pool_host_summary(host),
                "inspect_ok": False,
                "error": f"{host_ip} port inspection failed: {exc}",
                "used_ports": [],
                "available_ports": [],
            }

        if completed.returncode != 0:
            stderr = str(completed.stderr or completed.stdout or "").strip() or "ssh command failed"
            return {
                **self._serialize_pool_host_summary(host),
                "inspect_ok": False,
                "error": f"{host_ip} port inspection failed: {stderr}",
                "used_ports": [],
                "available_ports": [],
            }

        used_ports = sorted(
            {
                port
                for port in self._parse_listening_ports(completed.stdout)
                if start <= port <= end
            }
        )
        used_port_set = set(used_ports)
        available_ports = [port for port in range(start, end + 1) if port not in used_port_set]
        return {
            **self._serialize_pool_host_summary(host),
            "inspect_ok": True,
            "error": None,
            "used_ports": used_ports,
            "available_ports": available_ports,
            "available_port_count": len(available_ports),
        }

    def _parse_listening_ports(self, output: str) -> set[int]:
        ports: set[int] = set()
        for raw_line in str(output or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            local_address = parts[3]
            match = re.search(r":(\d+)$", local_address)
            if not match:
                continue
            try:
                ports.add(int(match.group(1)))
            except ValueError:
                continue
        return ports

    def _select_host_candidate(
        self,
        *,
        inspection_rows: list[dict[str, Any]],
        requested_port: int | None,
    ) -> dict[str, Any] | None:
        candidates = [row for row in inspection_rows if row.get("inspect_ok")]
        if requested_port is not None:
            candidates = [
                row for row in candidates if int(requested_port) in set(row.get("available_ports") or [])
            ]
        if not candidates:
            return None

        selected = max(
            candidates,
            key=lambda row: (
                int(row.get("available_port_count") or len(row.get("available_ports") or [])),
                -int(row.get("vmid") or 0),
            ),
        )
        return {
            "id": selected.get("id"),
            "name": selected.get("name"),
            "node": selected.get("node"),
            "vmid": selected.get("vmid"),
            "host_ip": selected.get("host_ip"),
            "host_user": selected.get("host_user"),
            "available_port_count": int(
                selected.get("available_port_count") or len(selected.get("available_ports") or [])
            ),
            "used_port_count": len(selected.get("used_ports") or []),
        }

    def _now_iso(self) -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
