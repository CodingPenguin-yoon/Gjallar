"""Staging host registry API router."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.domains.staging.service import StagingHostRegistryError, StagingHostRegistryService


router = APIRouter()
staging_host_registry_service = StagingHostRegistryService()


class StagingHostResponse(BaseModel):
    id: int
    environment: str
    node: str
    vmid: int
    name: str | None = None
    host_ip: str
    host_user: str | None = None
    pool_key: str
    role: str
    bootstrap_status: str
    enabled: bool
    drain_mode: bool
    source_task_id: str | None = None
    created_at: str
    updated_at: str


class StagingHostsListResponse(BaseModel):
    hosts: list[StagingHostResponse] = Field(default_factory=list)


class StagingHostPoolSummaryResponse(BaseModel):
    environment: str
    pool_key: str
    label: str
    state: str
    total_hosts: int
    ready_hosts: int
    blocked_hosts: int
    sample_hosts: list[dict] = Field(default_factory=list)


class StagingHostPoolsListResponse(BaseModel):
    pools: list[StagingHostPoolSummaryResponse] = Field(default_factory=list)


class StagingHostPoolPreviewResponse(BaseModel):
    environment: str
    pool_key: str | None = None
    label: str
    state: str
    summary: str
    total_hosts: int
    ready_hosts: int
    blocked_hosts: int
    sample_hosts: list[dict] = Field(default_factory=list)
    blocked_host_summaries: list[dict] = Field(default_factory=list)
    port_range: dict
    requested_port: int | None = None
    requested_port_available: bool
    suggested_app_port: int | None = None
    available_port_count: int
    available_port_options: list[dict] = Field(default_factory=list)
    selected_host: dict | None = None
    inspection_errors: list[str] = Field(default_factory=list)


class StagingHostRegisterRequest(BaseModel):
    environment: str = "staging"
    node: str
    vmid: int
    host_ip: str
    host_user: str | None = None
    name: str | None = None
    pool_key: str = "default"
    role: str = "shared"
    bootstrap_status: str = "ready"
    enabled: bool = True
    drain_mode: bool = False
    source_task_id: str | None = None


@router.get("/staging-hosts", response_model=StagingHostsListResponse)
async def get_staging_hosts() -> StagingHostsListResponse:
    return StagingHostsListResponse(hosts=staging_host_registry_service.list_hosts())


@router.get("/staging-hosts/pools", response_model=StagingHostPoolsListResponse)
async def get_staging_host_pools(environment: str | None = None) -> StagingHostPoolsListResponse:
    return StagingHostPoolsListResponse(
        pools=staging_host_registry_service.list_pools(environment=environment)
    )


@router.get("/staging-hosts/pools/preview", response_model=StagingHostPoolPreviewResponse)
async def preview_staging_host_pool(
    environment: str,
    pool_key: str,
    requested_port: int | None = None,
) -> StagingHostPoolPreviewResponse:
    try:
        return StagingHostPoolPreviewResponse(
            **staging_host_registry_service.preview_pool(
                environment=environment,
                pool_key=pool_key,
                requested_port=requested_port,
            )
        )
    except StagingHostRegistryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/staging-hosts/register", response_model=StagingHostResponse, status_code=201)
async def register_staging_host(payload: StagingHostRegisterRequest) -> StagingHostResponse:
    try:
        return StagingHostResponse(
            **staging_host_registry_service.register_host(payload.model_dump())
        )
    except StagingHostRegistryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
