"""VM provisioning API routes. The deploy domain/route is kept for compatibility."""

from __future__ import annotations

from ipaddress import IPv4Address, IPv4Interface, ip_address, ip_interface
from typing import Optional, List

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from app.domains.deploy.service import DeploymentService
from app.domains.deploy.readiness import ProvisioningReadinessService
from app.domains.deploy.resource_preflight import ProvisioningResourcePreflightService


router = APIRouter()
deployment_service = DeploymentService()
readiness_service = ProvisioningReadinessService()
resource_preflight_service = ProvisioningResourcePreflightService()


class DeployRequest(BaseModel):
    """배포 요청 모델 (Proxmox/VM/Ansible 설정 포함)"""

    # Proxmox 리소스 선택 (마법사 스타일)
    server_id: Optional[str] = None
    template_id: Optional[str] = None
    storage_id: Optional[str] = None
    storage_type: Optional[str] = None
    network_ids: Optional[List[str]] = None

    # VM 설정 (템플릿 미사용 시)
    cpu_cores: Optional[int] = Field(default=None, ge=1)
    memory_gb: Optional[int] = Field(default=None, ge=1)
    disk_size_gb: Optional[int] = Field(default=None, ge=1)

    # 인스턴스 이름
    server_name: Optional[str] = None
    vmid: Optional[int] = Field(default=None, ge=1)
    vm_ip: Optional[str] = None
    vm_gateway: Optional[str] = None

    # Ansible 설정
    ansible_packages: List[str] = Field(default_factory=list)
    ansible_roles: List[str] = Field(default_factory=list)

    # 옵션 플래그
    skip_terraform: Optional[bool] = False
    skip_ansible: Optional[bool] = False


class DeployResponse(BaseModel):
    """배포 응답 모델"""

    task_id: str
    message: str
    status: str


def _validate_static_network(request: DeployRequest) -> None:
    vm_ip = request.vm_ip
    vm_gateway = request.vm_gateway

    if not vm_ip and not vm_gateway:
        return

    if not vm_ip or not vm_gateway:
        raise HTTPException(
            status_code=400,
            detail="Static IP provisioning requires both vm_ip (CIDR) and vm_gateway.",
        )

    if "/" not in vm_ip:
        raise HTTPException(
            status_code=400,
            detail="vm_ip must be an IPv4 host CIDR like 192.168.2.100/24.",
        )

    try:
        parsed_ip = ip_interface(vm_ip)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="vm_ip must be an IPv4 host CIDR like 192.168.2.100/24.",
        ) from exc

    if not isinstance(parsed_ip, IPv4Interface):
        raise HTTPException(
            status_code=400,
            detail="vm_ip must be an IPv4 host CIDR like 192.168.2.100/24.",
        )

    try:
        parsed_gateway = ip_address(vm_gateway)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="vm_gateway must be a valid IPv4 address like 192.168.2.1.",
        ) from exc

    if not isinstance(parsed_gateway, IPv4Address):
        raise HTTPException(
            status_code=400,
            detail="vm_gateway must be a valid IPv4 address like 192.168.2.1.",
        )

    if parsed_ip.network.prefixlen < 31 and parsed_ip.ip in {parsed_ip.network.network_address, parsed_ip.network.broadcast_address}:
        raise HTTPException(
            status_code=400,
            detail="vm_ip host address must not be the subnet network or broadcast address.",
        )

    if parsed_gateway not in parsed_ip.network:
        raise HTTPException(
            status_code=400,
            detail="vm_gateway must be in the same subnet as vm_ip.",
        )

    if parsed_ip.ip == parsed_gateway:
        raise HTTPException(
            status_code=400,
            detail="vm_ip host address must not equal vm_gateway.",
        )


@router.get("/provision/readiness")
def provision_readiness():
    """Return non-secret provisioning runtime readiness checks."""
    return readiness_service.check()


@router.post("/provision/preflight")
def provision_resource_preflight(request: DeployRequest):
    """Validate selected Proxmox node/template/storage/network before provisioning."""
    return resource_preflight_service.check(request.model_dump(exclude_none=True))


@router.post("/deploy", response_model=DeployResponse)
async def deploy(
    request: DeployRequest,
    background_tasks: BackgroundTasks,
):
    """
    인프라 배포 시작

    Terraform apply와 Ansible playbook을 순차적으로 실행합니다.
    BackgroundTasks를 사용하여 비동기적으로 처리됩니다.
    """
    try:
        _validate_static_network(request)

        if not (request.skip_terraform or False) and not request.template_id:
            raise HTTPException(
                status_code=400,
                detail="현재 VM 생성은 template_id 기반 배포만 지원합니다.",
            )

        deploy_request_dict = request.model_dump(exclude_none=True)

        task_id = deployment_service.start_deployment_with_request(
            background_tasks=background_tasks,
            deploy_request=deploy_request_dict,
            skip_terraform=request.skip_terraform or False,
            skip_ansible=request.skip_ansible or False,
        )

        return DeployResponse(
            task_id=task_id,
            message="VM provisioning 작업이 시작되었습니다.",
            status="pending",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"배포 시작 실패: {str(e)}",
        )


@router.post("/provision", response_model=DeployResponse)
async def provision(
    request: DeployRequest,
    background_tasks: BackgroundTasks,
):
    """
    VM provisioning 시작

    `/deploy`는 과거 호환용으로 유지하고, 신규 프론트엔드/문서는
    Gjallar 제품 방향에 맞는 `/provision` 엔드포인트를 사용합니다.
    """
    return await deploy(request=request, background_tasks=background_tasks)


__all__ = ["router"]
