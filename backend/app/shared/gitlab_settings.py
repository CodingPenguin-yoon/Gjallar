"""GitLab and staging-target environment settings helpers."""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address
import os
from urllib.parse import urlparse

STAGING_ENV_SHARED_HOST = "shared_host"
STAGING_ENV_DEDICATED_VM = "dedicated_vm"
DEPLOYMENT_ENV_STAGING = "staging"
DEPLOYMENT_ENV_PRODUCTION = "production"
ALLOWED_DEPLOYMENT_ENVIRONMENTS = {
    DEPLOYMENT_ENV_STAGING,
    DEPLOYMENT_ENV_PRODUCTION,
}


def _read_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = str(raw).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _read_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = int(str(raw).strip())
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _read_list_env(name: str) -> list[str]:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _read_port_range_env(name: str, default: tuple[int, int]) -> tuple[int, int]:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return default

    bounds = raw.split("-", 1)
    if len(bounds) != 2:
        return default

    try:
        start = int(bounds[0].strip())
        end = int(bounds[1].strip())
    except ValueError:
        return default

    if start <= 0 or end <= 0 or end < start:
        return default
    return start, end


@dataclass(frozen=True)
class GitLabSettings:
    """Prepared-only GitLab connection settings loaded from environment."""

    base_url: str
    api_token: str
    verify_ssl: bool
    default_namespace_path: str
    system_hook_secret: str
    public_base_url: str

    @property
    def is_configured(self) -> bool:
        """Return whether the GitLab base URL is valid enough for runtime use."""
        return self.validation_error is None

    @property
    def validation_error(self) -> str | None:
        """Validate GitLab base URL shape without exposing sensitive values."""
        if not self.base_url:
            return "GITLAB_BASE_URL is not configured."

        parsed = urlparse(self.base_url)
        if not parsed.scheme or not parsed.netloc:
            return "GITLAB_BASE_URL must include scheme and host."

        if parsed.scheme not in {"http", "https"}:
            return "GITLAB_BASE_URL must use http or https."

        return None

    @property
    def can_sync(self) -> bool:
        """Return whether manual sync has enough configuration to run."""
        return self.is_configured and bool(self.api_token)


@dataclass(frozen=True)
class StagingSharedHostSettings:
    """Existing shared staging host configuration for shared-host deploy mode."""

    host_ip: str
    host_name: str
    host_user: str

    @property
    def is_configured(self) -> bool:
        return self.validation_error is None

    @property
    def validation_error(self) -> str | None:
        if not self.host_ip:
            return "STAGING_SHARED_HOST_IP is not configured."

        try:
            ip_address(self.host_ip)
        except ValueError:
            return "STAGING_SHARED_HOST_IP must be a valid IP address."

        return None

    @property
    def summary(self) -> dict[str, object]:
        configured = self.is_configured
        label = (
            f"{self.host_name or 'shared-staging-host'} · {self.host_ip}"
            if configured
            else "Shared staging host is not configured."
        )
        return {
            "configured": configured,
            "host_name": self.host_name,
            "host_ip": self.host_ip,
            "host_user": self.host_user,
            "label": label,
            "validation_error": self.validation_error,
        }


@dataclass(frozen=True)
class StagingDedicatedVmSettings:
    """System-managed dedicated staging VM defaults."""

    server_id: str
    template_id: str
    storage_id: str
    network_ids: list[str]
    cpu_cores: int
    memory_gb: int
    disk_size_gb: int
    name_suffix: str

    @property
    def is_configured(self) -> bool:
        return self.validation_error is None

    @property
    def validation_error(self) -> str | None:
        missing_fields = [
            name
            for name, value in (
                ("STAGING_DEDICATED_VM_SERVER_ID", self.server_id),
                ("STAGING_DEDICATED_VM_TEMPLATE_ID", self.template_id),
                ("STAGING_DEDICATED_VM_STORAGE_ID", self.storage_id),
            )
            if not str(value or "").strip()
        ]
        if not self.network_ids:
            missing_fields.append("STAGING_DEDICATED_VM_NETWORK_IDS")
        if missing_fields:
            return "Missing dedicated VM defaults: " + ", ".join(missing_fields)
        return None

    @property
    def summary(self) -> dict[str, object]:
        configured = self.is_configured
        label = (
            f"System-managed dedicated VM · {self.server_id or 'node 미지정'} · {self.template_id or 'template 미지정'}"
            if configured
            else "System-managed dedicated VM defaults are not configured."
        )
        return {
            "configured": configured,
            "server_id": self.server_id,
            "template_id": self.template_id,
            "storage_id": self.storage_id,
            "network_ids": list(self.network_ids),
            "cpu_cores": self.cpu_cores,
            "memory_gb": self.memory_gb,
            "disk_size_gb": self.disk_size_gb,
            "name_suffix": self.name_suffix,
            "label": label,
            "validation_error": self.validation_error,
        }


def get_gitlab_settings() -> GitLabSettings:
    """Load GitLab settings from environment without forcing runtime use yet."""
    return GitLabSettings(
        base_url=os.getenv("GITLAB_BASE_URL", "").strip().rstrip("/"),
        api_token=os.getenv("GITLAB_API_TOKEN", "").strip(),
        verify_ssl=_read_bool_env("GITLAB_VERIFY_SSL", True),
        default_namespace_path=os.getenv("GITLAB_DEFAULT_NAMESPACE_PATH", "heimdall").strip() or "heimdall",
        system_hook_secret=os.getenv("GITLAB_SYSTEM_HOOK_SECRET", "").strip(),
        public_base_url=os.getenv("PLATFORM_PUBLIC_BASE_URL", "").strip().rstrip("/"),
    )


def get_staging_shared_host_settings() -> StagingSharedHostSettings:
    """Load shared staging host settings for shared-host deploy mode."""
    default_user = os.getenv("ANSIBLE_SSH_USER", "root").strip() or "root"
    host_ip = os.getenv("STAGING_SHARED_HOST_IP", "").strip()
    host_name = os.getenv("STAGING_SHARED_HOST_NAME", "").strip() or "shared-staging-host"
    host_user = os.getenv("STAGING_SHARED_HOST_USER", "").strip() or default_user

    return StagingSharedHostSettings(
        host_ip=host_ip,
        host_name=host_name,
        host_user=host_user,
    )


def get_staging_dedicated_vm_settings() -> StagingDedicatedVmSettings:
    """Load system-managed dedicated VM defaults."""
    return StagingDedicatedVmSettings(
        server_id=os.getenv("STAGING_DEDICATED_VM_SERVER_ID", "").strip(),
        template_id=os.getenv("STAGING_DEDICATED_VM_TEMPLATE_ID", "").strip(),
        storage_id=os.getenv("STAGING_DEDICATED_VM_STORAGE_ID", "").strip(),
        network_ids=_read_list_env("STAGING_DEDICATED_VM_NETWORK_IDS"),
        cpu_cores=_read_int_env("STAGING_DEDICATED_VM_CPU_CORES", 2),
        memory_gb=_read_int_env("STAGING_DEDICATED_VM_MEMORY_GB", 4),
        disk_size_gb=_read_int_env("STAGING_DEDICATED_VM_DISK_SIZE_GB", 50),
        name_suffix=os.getenv("STAGING_DEDICATED_VM_NAME_SUFFIX", "").strip() or "staging",
    )


def get_staging_environment_catalog() -> list[dict[str, object]]:
    """Build the currently available staging environment options."""
    shared_host = get_staging_shared_host_settings()
    dedicated_vm = get_staging_dedicated_vm_settings()
    options: list[dict[str, object]] = []

    if shared_host.host_ip:
        options.append(
            {
                "key": STAGING_ENV_SHARED_HOST,
                "label": "Shared staging host",
                "mode": STAGING_ENV_SHARED_HOST,
                "configured": shared_host.is_configured,
                "description": "Reuse the existing staging host and deploy only the app bundle.",
            }
        )

    options.append(
        {
            "key": STAGING_ENV_DEDICATED_VM,
            "label": "Dedicated staging VM",
            "mode": STAGING_ENV_DEDICATED_VM,
            "configured": dedicated_vm.is_configured,
            "description": "Provision a system-managed dedicated VM through Terraform, then deploy the app.",
        }
    )

    return options


def normalize_deployment_environment(value: str | None) -> str:
    normalized = str(value or "").strip().lower() or DEPLOYMENT_ENV_STAGING
    if normalized not in ALLOWED_DEPLOYMENT_ENVIRONMENTS:
        return DEPLOYMENT_ENV_STAGING
    return normalized


def get_deployment_environment_catalog() -> list[dict[str, str]]:
    return [
        {
            "key": DEPLOYMENT_ENV_STAGING,
            "label": "Staging",
            "description": "Shared pre-production host pools used for validation and QA.",
        },
        {
            "key": DEPLOYMENT_ENV_PRODUCTION,
            "label": "Production",
            "description": "Production host pools. UI setup is ready, deploy execution is still staging-only.",
        },
    ]


def get_environment_port_range(environment: str) -> dict[str, object]:
    normalized_environment = normalize_deployment_environment(environment)
    if normalized_environment == DEPLOYMENT_ENV_PRODUCTION:
        start, end = _read_port_range_env("DEPLOYMENT_PORT_RANGE_PRODUCTION", (4000, 4499))
    else:
        start, end = _read_port_range_env("DEPLOYMENT_PORT_RANGE_STAGING", (3000, 3499))

    return {
        "environment": normalized_environment,
        "start": start,
        "end": end,
        "label": f"{start}-{end}",
    }


__all__ = [
    "ALLOWED_DEPLOYMENT_ENVIRONMENTS",
    "DEPLOYMENT_ENV_PRODUCTION",
    "DEPLOYMENT_ENV_STAGING",
    "GitLabSettings",
    "StagingDedicatedVmSettings",
    "StagingSharedHostSettings",
    "STAGING_ENV_DEDICATED_VM",
    "STAGING_ENV_SHARED_HOST",
    "get_deployment_environment_catalog",
    "get_environment_port_range",
    "get_gitlab_settings",
    "get_staging_dedicated_vm_settings",
    "get_staging_environment_catalog",
    "get_staging_shared_host_settings",
    "normalize_deployment_environment",
]
