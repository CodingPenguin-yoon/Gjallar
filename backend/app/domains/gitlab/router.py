"""GitLab inventory API router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from app.domains.gitlab.service import (
    GitLabConfigurationError,
    GitLabInventoryService,
    GitLabProjectCreateError,
    GitLabProjectNotFoundError,
    GitLabProjectSettingsError,
    GitLabSyncError,
)


router = APIRouter()
gitlab_inventory_service = GitLabInventoryService()


class GitLabStagingEnvironmentOptionResponse(BaseModel):
    key: str
    label: str
    mode: str
    configured: bool
    description: str


class GitLabDeploymentEnvironmentOptionResponse(BaseModel):
    key: str
    label: str
    description: str


class GitLabProjectResponse(BaseModel):
    gitlab_project_id: int
    name: str
    path_with_namespace: str
    web_url: str
    http_url_to_repo: str
    ssh_url_to_repo: str | None = None
    default_branch: str | None = None
    visibility: str
    archived: bool
    last_activity_at: str | None = None
    synced_at: str
    configuration_status: str
    manifest_status: str
    manifest_summary: str
    deployment_environment: str
    deployment_environment_options: list[GitLabDeploymentEnvironmentOptionResponse] = Field(default_factory=list)
    deployment_pool_key: str | None = None
    deployment_pool_summary: dict[str, Any] | None = None
    requested_app_port: int | None = None
    effective_app_port: int | None = None
    app_port_source: str | None = None
    readiness_summary: dict[str, Any] | None = None
    staging_environment_key: str
    staging_environment_options: list[GitLabStagingEnvironmentOptionResponse] = Field(default_factory=list)
    staging_target_mode: str
    staging_target_summary: dict[str, Any] | None = None
    manifest_deploy_summary: dict[str, Any] | None = None
    settings_summary: dict[str, Any] | None = None


class GitLabProjectsListResponse(BaseModel):
    configured: bool
    can_sync: bool
    default_namespace_path: str
    configuration_error: str | None = None
    projects: list[GitLabProjectResponse] = Field(default_factory=list)
    last_sync: dict[str, Any] | None = None


class GitLabProjectsSyncResponse(BaseModel):
    status: str
    project_count: int
    updated_at: str


class GitLabNamespaceResponse(BaseModel):
    id: int
    name: str
    path: str
    full_path: str
    kind: str
    web_url: str


class GitLabNamespacesListResponse(BaseModel):
    namespaces: list[GitLabNamespaceResponse] = Field(default_factory=list)


class GitLabProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    path: str | None = None
    description: str | None = None
    visibility: str = "private"
    initialize_with_readme: bool = False
    default_branch: str | None = None


class GitLabProjectCreateResponse(BaseModel):
    project: GitLabProjectResponse
    manifest_seeded: bool = False
    manifest_seed_message: str | None = None


class GitLabProjectSettingsResponse(BaseModel):
    gitlab_project_id: int
    configuration_status: str
    manifest_status: str
    manifest_summary: str
    deployment_environment: str
    deployment_environment_options: list[GitLabDeploymentEnvironmentOptionResponse] = Field(default_factory=list)
    deployment_pool_key: str | None = None
    deployment_pool_options: list[dict[str, Any]] = Field(default_factory=list)
    deployment_pool_summary: dict[str, Any] | None = None
    port_range_summary: dict[str, Any] | None = None
    available_port_options: list[dict[str, Any]] = Field(default_factory=list)
    requested_app_port: int | None = None
    effective_app_port: int | None = None
    app_port_source: str | None = None
    readiness_summary: dict[str, Any] | None = None
    staging_environment_key: str
    staging_environment_options: list[GitLabStagingEnvironmentOptionResponse] = Field(default_factory=list)
    staging_target_mode: str
    staging_target_summary: dict[str, Any] | None = None
    manifest_deploy_summary: dict[str, Any] | None = None
    staging_enabled: bool
    ready_for_bootstrap: bool
    database_required: bool
    database_engine: str | None = None
    database_mode: str | None = None
    migration_command: str | None = None
    deploy_branch: str
    bootstrap_strategy: str
    staging_server_name: str | None = None
    staging_server_id: str | None = None
    staging_template_id: str | None = None
    staging_storage_id: str | None = None
    staging_network_ids: list[str] = Field(default_factory=list)
    staging_cpu_cores: int | None = None
    staging_memory_gb: int | None = None
    staging_disk_size_gb: int | None = None
    staging_vm_ip: str | None = None
    staging_vm_gateway: str | None = None
    staging_ansible_packages: list[str] = Field(default_factory=list)
    staging_ansible_roles: list[str] = Field(default_factory=list)
    notes: str | None = None
    updated_at: str | None = None
    settings_summary: dict[str, Any] | None = None


class GitLabProjectSettingsUpdateRequest(BaseModel):
    deployment_environment: str = "staging"
    deployment_pool_key: str | None = None
    requested_app_port: int | None = Field(default=None, ge=1)
    staging_environment_key: str = "dedicated_vm"
    staging_enabled: bool = False
    ready_for_bootstrap: bool = False
    database_required: bool = False
    database_engine: str | None = None
    database_mode: str | None = None
    migration_command: str | None = None
    deploy_branch: str = "main"
    bootstrap_strategy: str = "merge_request"
    staging_server_name: str | None = None
    staging_server_id: str | None = None
    staging_template_id: str | None = None
    staging_storage_id: str | None = None
    staging_network_ids: list[str] | None = None
    staging_cpu_cores: int | None = Field(default=None, ge=1)
    staging_memory_gb: int | None = Field(default=None, ge=1)
    staging_disk_size_gb: int | None = Field(default=None, ge=1)
    staging_vm_ip: str | None = None
    staging_vm_gateway: str | None = None
    staging_ansible_packages: list[str] | None = None
    staging_ansible_roles: list[str] | None = None
    notes: str | None = None


class GitLabProjectSettingsPreviewRequest(BaseModel):
    deployment_environment: str = "staging"
    deployment_pool_key: str | None = None
    requested_app_port: int | None = Field(default=None, ge=1)


class GitLabProjectSettingsPreviewResponse(BaseModel):
    deployment_environment: str
    deployment_environment_options: list[GitLabDeploymentEnvironmentOptionResponse] = Field(default_factory=list)
    deployment_pool_key: str | None = None
    deployment_pool_options: list[dict[str, Any]] = Field(default_factory=list)
    deployment_pool_summary: dict[str, Any] | None = None
    port_range_summary: dict[str, Any] | None = None
    available_port_options: list[dict[str, Any]] = Field(default_factory=list)
    requested_app_port: int | None = None
    suggested_app_port: int | None = None
    requested_port_available: bool = False
    readiness_summary: dict[str, Any] | None = None


class GitLabProjectManifestResponse(BaseModel):
    gitlab_project_id: int
    path_with_namespace: str
    default_branch: str | None = None
    deploy_branch: str | None = None
    manifest_ref: str
    manifest_exists: bool
    manifest_status: str
    manifest_summary: str
    raw_content: str | None = None
    draft_content: str
    manifest_deploy_summary: dict[str, Any] | None = None
    requested_app_port: int | None = None
    effective_app_port: int | None = None
    app_port_source: str | None = None
    database_required: bool = False
    write_mode: str | None = None
    message: str | None = None


class GitLabProjectManifestUpdateRequest(BaseModel):
    branch: str = Field(min_length=1)
    content: str = Field(min_length=1)
    commit_message: str | None = None


class GitLabProjectManifestPreviewRequest(BaseModel):
    content: str = Field(min_length=1)


class GitLabProjectManifestPreviewResponse(BaseModel):
    manifest_status: str
    manifest_summary: str
    manifest_deploy_summary: dict[str, Any] | None = None
    requested_app_port: int | None = None
    effective_app_port: int | None = None
    app_port_source: str | None = None


class GitLabDeployRequestResponse(BaseModel):
    task_id: str
    message: str
    status: str
    already_exists: bool


@router.get("/gitlab/projects", response_model=GitLabProjectsListResponse)
async def get_gitlab_projects() -> GitLabProjectsListResponse:
    return GitLabProjectsListResponse(**gitlab_inventory_service.list_projects())


@router.get("/gitlab/namespaces", response_model=GitLabNamespacesListResponse)
async def get_gitlab_namespaces() -> GitLabNamespacesListResponse:
    try:
        return GitLabNamespacesListResponse(namespaces=gitlab_inventory_service.list_namespaces())
    except GitLabConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GitLabSyncError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/gitlab/projects", response_model=GitLabProjectCreateResponse, status_code=201)
async def create_gitlab_project(payload: GitLabProjectCreateRequest) -> GitLabProjectCreateResponse:
    try:
        return GitLabProjectCreateResponse(**gitlab_inventory_service.create_project(payload.model_dump()))
    except GitLabConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GitLabProjectCreateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/gitlab/projects/{project_id}/settings", response_model=GitLabProjectSettingsResponse)
async def get_gitlab_project_settings(project_id: int) -> GitLabProjectSettingsResponse:
    try:
        return GitLabProjectSettingsResponse(
            **gitlab_inventory_service.get_project_settings(project_id)
        )
    except GitLabProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GitLabProjectSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/gitlab/projects/{project_id}/settings", response_model=GitLabProjectSettingsResponse)
async def update_gitlab_project_settings(
    project_id: int,
    payload: GitLabProjectSettingsUpdateRequest,
) -> GitLabProjectSettingsResponse:
    try:
        return GitLabProjectSettingsResponse(
            **gitlab_inventory_service.upsert_project_settings(project_id, payload.model_dump())
        )
    except GitLabProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GitLabProjectSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/gitlab/projects/{project_id}/settings/preview",
    response_model=GitLabProjectSettingsPreviewResponse,
)
async def preview_gitlab_project_settings(
    project_id: int,
    payload: GitLabProjectSettingsPreviewRequest,
) -> GitLabProjectSettingsPreviewResponse:
    try:
        return GitLabProjectSettingsPreviewResponse(
            **gitlab_inventory_service.preview_project_settings_contract(
                project_id,
                payload.model_dump(),
            )
        )
    except GitLabProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GitLabProjectSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/gitlab/projects/{project_id}/manifest", response_model=GitLabProjectManifestResponse)
async def get_gitlab_project_manifest(
    project_id: int,
    ref: str | None = None,
) -> GitLabProjectManifestResponse:
    try:
        return GitLabProjectManifestResponse(
            **gitlab_inventory_service.get_project_manifest_document(project_id, ref=ref)
        )
    except GitLabProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GitLabProjectSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/gitlab/projects/{project_id}/manifest", response_model=GitLabProjectManifestResponse)
async def update_gitlab_project_manifest(
    project_id: int,
    payload: GitLabProjectManifestUpdateRequest,
) -> GitLabProjectManifestResponse:
    try:
        return GitLabProjectManifestResponse(
            **gitlab_inventory_service.upsert_project_manifest(
                project_id,
                payload.model_dump(),
            )
        )
    except GitLabProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GitLabProjectSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/gitlab/projects/{project_id}/manifest/preview",
    response_model=GitLabProjectManifestPreviewResponse,
)
async def preview_gitlab_project_manifest(
    project_id: int,
    payload: GitLabProjectManifestPreviewRequest,
) -> GitLabProjectManifestPreviewResponse:
    try:
        return GitLabProjectManifestPreviewResponse(
            **gitlab_inventory_service.preview_project_manifest_document(
                project_id,
                payload.model_dump(),
            )
        )
    except GitLabProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GitLabProjectSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/gitlab/projects/{project_id}/deploy/staging",
    response_model=GitLabDeployRequestResponse,
    status_code=202,
)
async def request_gitlab_project_staging_deploy(
    project_id: int,
    background_tasks: BackgroundTasks,
) -> GitLabDeployRequestResponse:
    try:
        return GitLabDeployRequestResponse(
            **gitlab_inventory_service.request_staging_deploy(project_id, background_tasks)
        )
    except GitLabProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GitLabProjectSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/gitlab/projects/sync", response_model=GitLabProjectsSyncResponse)
async def sync_gitlab_projects() -> GitLabProjectsSyncResponse:
    try:
        return GitLabProjectsSyncResponse(**gitlab_inventory_service.sync_projects())
    except GitLabConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GitLabSyncError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


__all__ = ["router"]
