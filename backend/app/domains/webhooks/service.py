"""Inbound webhook handlers for external control-plane integrations."""

from __future__ import annotations

import secrets
from typing import Any

from app.domains.gitlab.service import (
    GitLabConfigurationError,
    GitLabInventoryService,
    GitLabSyncError,
)
from app.shared.gitlab_settings import get_gitlab_settings


SUPPORTED_GITLAB_SYSTEM_HOOK_EVENTS = {
    "project_create",
    "project_destroy",
    "project_rename",
    "project_transfer",
    "project_update",
    "project_archive",
    "project_unarchive",
}

IGNORED_GITLAB_SYSTEM_HOOK_EVENTS = {
    "repository_update",
    "push",
    "tag_push",
    "merge_request",
    "pipeline",
    "job",
    "deployment",
    "group_create",
    "group_destroy",
    "group_rename",
    "key_create",
    "key_destroy",
    "user_create",
    "user_destroy",
}


class GitLabWebhookConfigurationError(RuntimeError):
    """Raised when the webhook secret is not configured safely."""


class GitLabWebhookAuthenticationError(RuntimeError):
    """Raised when a webhook request cannot be trusted."""


class GitLabWebhookPayloadError(RuntimeError):
    """Raised when a webhook payload is malformed."""


class GitLabSystemHookService:
    """Validate GitLab system hooks and trigger inventory refresh when needed."""

    def __init__(self) -> None:
        self._inventory_service = GitLabInventoryService()

    def handle(self, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        settings = get_gitlab_settings()
        self._validate_secret(settings.system_hook_secret, headers)

        event_name = self._extract_event_name(payload)
        if not event_name:
            raise GitLabWebhookPayloadError("GitLab system hook payload is missing event_name.")

        if event_name in SUPPORTED_GITLAB_SYSTEM_HOOK_EVENTS:
            sync_result = self._inventory_service.sync_projects()
            return {
                "status": "accepted",
                "event_name": event_name,
                "sync": sync_result,
            }

        if event_name in IGNORED_GITLAB_SYSTEM_HOOK_EVENTS:
            return {
                "status": "ignored",
                "event_name": event_name,
                "reason": "unsupported system hook event for this slice",
            }

        return {
            "status": "ignored",
            "event_name": event_name,
            "reason": "unrecognized system hook event",
        }

    def _validate_secret(self, configured_secret: str, headers: dict[str, str]) -> None:
        if not configured_secret:
            raise GitLabWebhookConfigurationError("GITLAB_SYSTEM_HOOK_SECRET is not configured.")

        provided_secret = headers.get("x-gitlab-token", "").strip()
        if not provided_secret:
            raise GitLabWebhookAuthenticationError("GitLab system hook token is missing.")

        if not secrets.compare_digest(provided_secret, configured_secret):
            raise GitLabWebhookAuthenticationError("GitLab system hook token is invalid.")

    def _extract_event_name(self, payload: dict[str, Any]) -> str:
        event_name = payload.get("event_name")
        if isinstance(event_name, str):
            return event_name.strip().lower()
        return ""


__all__ = [
    "GitLabSystemHookService",
    "GitLabWebhookAuthenticationError",
    "GitLabWebhookConfigurationError",
    "GitLabWebhookPayloadError",
]
