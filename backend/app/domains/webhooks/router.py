"""Webhook ingress routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.domains.gitlab.service import GitLabConfigurationError, GitLabSyncError
from app.domains.webhooks.service import (
    GitLabSystemHookService,
    GitLabWebhookAuthenticationError,
    GitLabWebhookConfigurationError,
    GitLabWebhookPayloadError,
)


router = APIRouter()
gitlab_system_hook_service = GitLabSystemHookService()


@router.post("/webhooks/gitlab/system", status_code=status.HTTP_202_ACCEPTED)
async def receive_gitlab_system_hook(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="GitLab system hook payload must be valid JSON.") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="GitLab system hook payload must be a JSON object.")

    headers = {key.lower(): value for key, value in request.headers.items()}

    try:
        return gitlab_system_hook_service.handle(headers=headers, payload=payload)
    except GitLabWebhookConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except GitLabWebhookAuthenticationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except GitLabWebhookPayloadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GitLabConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GitLabSyncError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


__all__ = ["router"]
