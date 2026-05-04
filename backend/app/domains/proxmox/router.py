"""Proxmox 리소스 조회/모니터링 API 라우트 (proxmox 도메인)."""

from __future__ import annotations

from typing import Any, List, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

try:
    from pydantic import ConfigDict
except ImportError:  # pragma: no cover - compatibility for older local tooling
    ConfigDict = None

from app.domains.proxmox.service import ProxmoxService
from app.shared.network import network_service


router = APIRouter()
proxmox_service = ProxmoxService()


class ExtraForbidRequestModel(BaseModel):
    """Request model base that forbids extra fields on Pydantic v1 and v2."""

    if ConfigDict is not None:
        model_config = ConfigDict(extra="forbid")
    else:  # pragma: no cover - exercised only on Pydantic v1
        class Config:
            extra = "forbid"


class ServerResponse(BaseModel):
    """서버 응답 모델"""

    servers: List[dict]


class TemplateResponse(BaseModel):
    """템플릿 응답 모델"""

    templates: List[dict]


class StorageResponse(BaseModel):
    """스토리지 응답 모델"""

    storages: List[dict]


class NetworkResponse(BaseModel):
    """네트워크 응답 모델"""

    networks: List[dict]


class VMResponse(BaseModel):
    """VM 응답 모델"""

    vms: List[dict]


class TerminateInstanceRequest(BaseModel):
    """인스턴스 종료/삭제 요청 모델"""

    node: str
    vmid: int
    shutdown_timeout_seconds: int = Field(default=60, ge=5, le=600)
    force_stop_timeout_seconds: int = Field(default=30, ge=5, le=300)


class TerminateInstanceResponse(BaseModel):
    """인스턴스 종료/삭제 응답 모델"""

    success: bool
    node: str
    vmid: int
    message: str
    details: dict


class InstanceActionRequest(BaseModel):
    """인스턴스 라이프사이클 액션 요청 모델"""

    node: str
    vmid: int
    action: Literal["start", "shutdown", "stop", "reboot"]
    timeout_seconds: int = Field(default=60, ge=5, le=600)


class InstanceActionResponse(BaseModel):
    """인스턴스 라이프사이클 액션 응답 모델"""

    success: bool
    node: str
    vmid: int
    action: str
    message: str
    details: dict


class UpdateInstanceResourcesRequest(BaseModel):
    """인스턴스 CPU/메모리 수정 요청 모델"""

    node: str
    vmid: int
    cpu_cores: int = Field(ge=1)
    memory_gb: float = Field(gt=0)


class UpdateInstanceResourcesResponse(BaseModel):
    """인스턴스 CPU/메모리 수정 응답 모델"""

    success: bool
    node: str
    vmid: int
    message: str
    details: dict

class OperationalRiskThresholdUpdateRequest(ExtraForbidRequestModel):
    """Local Gjallar risk threshold update request."""

    storage_warning_percent: Optional[float] = Field(default=None, gt=0, le=100)
    storage_critical_percent: Optional[float] = Field(default=None, gt=0, le=100)
    snapshot_warning_days: Optional[float] = Field(default=None, ge=1, le=3650)
    snapshot_critical_days: Optional[float] = Field(default=None, ge=1, le=3650)
    backup_warning_days: Optional[float] = Field(default=None, ge=1, le=3650)
    stopped_warning_days: Optional[float] = Field(default=None, ge=1, le=3650)
    stopped_critical_days: Optional[float] = Field(default=None, ge=1, le=3650)

    def to_updates(self) -> dict[str, Any]:
        if hasattr(self, "model_dump"):
            return self.model_dump(exclude_none=True)
        return self.dict(exclude_none=True)


class OperationalRiskOverrideRequest(ExtraForbidRequestModel):
    """Local acknowledge/suppress request for a deterministic risk item."""

    risk_id: str = Field(min_length=1, max_length=512)
    status: Literal["acknowledged", "suppressed"]
    reason: Optional[str] = Field(default=None, max_length=2000)
    expires_at: Optional[float] = Field(default=None, gt=0)
    def to_updates(self) -> dict[str, Any]:
        if hasattr(self, "model_dump"):
            return self.model_dump(exclude_none=True)
        return self.dict(exclude_none=True)


class OperationalRiskOverrideClearRequest(ExtraForbidRequestModel):
    """Clear local acknowledge/suppress state for one risk item."""

    risk_id: str = Field(min_length=1, max_length=512)


@router.get("/servers", response_model=ServerResponse)
def get_servers():
    """
    Proxmox 노드(서버) 목록 조회
    """
    try:
        servers = proxmox_service.get_nodes()
        if not servers:
            print("경고: 서버 목록이 비어있습니다. Proxmox 연결을 확인하세요.")
        return ServerResponse(servers=servers)
    except Exception as e:
        print(f"서버 목록 조회 중 예외 발생: {str(e)}")
        import traceback

        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"서버 목록 조회 실패: {str(e)}",
        )


@router.get("/templates", response_model=TemplateResponse)
def get_templates():
    """
    Proxmox 템플릿 목록 조회
    """
    try:
        templates = proxmox_service.get_templates()
        return TemplateResponse(templates=templates)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"템플릿 목록 조회 실패: {str(e)}",
        )


@router.get("/vms", response_model=VMResponse)
def get_vms():
    """
    Proxmox VM 목록 조회 (템플릿 제외)
    """
    try:
        vms = proxmox_service.get_vms()
        return VMResponse(vms=vms)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"VM 목록 조회 실패: {str(e)}",
        )


@router.get("/instances")
def get_instances():
    """
    인스턴스 목록 조회 (VM 목록과 동일, 프론트 호환용)
    """
    try:
        vms = proxmox_service.get_vms()

        instances = []
        for vm in vms:
            instances.append(
                {
                    "id": vm.get("id") or vm.get("vm_id"),
                    "server_name": vm.get("name"),
                    "name": vm.get("name"),
                    "status": vm.get("status", "unknown"),
                    "cpu_cores": vm.get("cpu_cores", 0),
                    "memory_gb": vm.get("memory_gb", 0),
                    "memory": vm.get("memory_gb", 0),
                    "cpu": vm.get("cpu_cores", 0),
                    "region": vm.get("node", ""),
                    "vmid": vm.get("vmid"),
                    "node": vm.get("node"),
                    "disk_gb": vm.get("disk_gb", 0),
                    "disks": vm.get("disks", []),
                    "primary_ip": vm.get("primary_ip"),
                    "ip_addresses": vm.get("ip_addresses", []),
                }
            )

        return {"instances": instances}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"인스턴스 목록 조회 실패: {str(e)}",
        )


@router.post("/instances/terminate", response_model=TerminateInstanceResponse)
def terminate_instance(request: TerminateInstanceRequest):
    """
    인스턴스 종료 후 삭제
    순서: graceful shutdown -> (타임아웃 시 force stop) -> delete
    """
    try:
        result = proxmox_service.terminate_vm(
            node=request.node,
            vmid=request.vmid,
            shutdown_timeout_seconds=request.shutdown_timeout_seconds,
            force_stop_timeout_seconds=request.force_stop_timeout_seconds,
        )

        if not result.get("success"):
            if result.get("not_found"):
                raise HTTPException(status_code=404, detail=result.get("error") or "VM을 찾을 수 없습니다.")
            raise HTTPException(status_code=409, detail=result.get("error") or "VM 종료/삭제에 실패했습니다.")

        return TerminateInstanceResponse(
            success=True,
            node=request.node,
            vmid=request.vmid,
            message="VM이 종료 후 삭제되었습니다.",
            details=result,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"인스턴스 종료/삭제 실패: {str(e)}",
        )


@router.post("/instances/action", response_model=InstanceActionResponse)
async def instance_action(request: InstanceActionRequest):
    """
    인스턴스 라이프사이클 액션 수행
    """
    try:
        result = proxmox_service.perform_vm_action(
            node=request.node,
            vmid=request.vmid,
            action=request.action,
            timeout_seconds=request.timeout_seconds,
        )

        if not result.get("success"):
            if result.get("not_found"):
                raise HTTPException(status_code=404, detail=result.get("error") or "VM을 찾을 수 없습니다.")
            if result.get("invalid_state"):
                raise HTTPException(status_code=409, detail=result.get("error") or "현재 VM 상태에서는 해당 액션을 수행할 수 없습니다.")
            raise HTTPException(status_code=409, detail=result.get("error") or "VM 액션 수행에 실패했습니다.")

        return InstanceActionResponse(
            success=True,
            node=request.node,
            vmid=request.vmid,
            action=request.action,
            message=result.get("message") or "VM action completed successfully.",
            details=result,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"인스턴스 액션 실패: {str(e)}",
        )


@router.patch("/instances/resources", response_model=UpdateInstanceResourcesResponse)
def update_instance_resources(request: UpdateInstanceResourcesRequest):
    """
    정지된 인스턴스의 CPU/메모리 설정 수정
    """
    try:
        result = proxmox_service.update_vm_resources(
            node=request.node,
            vmid=request.vmid,
            cpu_cores=request.cpu_cores,
            memory_gb=request.memory_gb,
        )

        if not result.get("success"):
            if result.get("not_found"):
                raise HTTPException(status_code=404, detail=result.get("error") or "VM을 찾을 수 없습니다.")
            if result.get("invalid_state"):
                raise HTTPException(status_code=409, detail=result.get("error") or "CPU/메모리 수정은 정지된 VM에서만 가능합니다.")
            raise HTTPException(status_code=409, detail=result.get("error") or "VM 리소스 수정에 실패했습니다.")

        return UpdateInstanceResourcesResponse(
            success=True,
            node=request.node,
            vmid=request.vmid,
            message=result.get("message") or "VM CPU/memory updated successfully.",
            details=result,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"인스턴스 리소스 수정 실패: {str(e)}",
        )


@router.get("/servers/{server_id}/storage", response_model=StorageResponse)
def get_server_storage(server_id: str):
    """
    특정 서버의 스토리지 목록 조회
    """
    try:
        storages = proxmox_service.get_storages(node=server_id)
        return StorageResponse(storages=storages)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"스토리지 목록 조회 실패: {str(e)}",
        )


@router.get("/servers/{server_id}/networks", response_model=NetworkResponse)
def get_server_networks(server_id: str):
    """
    특정 서버의 네트워크 목록 조회
    """
    try:
        networks = proxmox_service.get_networks(node=server_id)
        return NetworkResponse(networks=networks)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"네트워크 목록 조회 실패: {str(e)}",
        )


@router.get("/servers/{server_id}/vms", response_model=VMResponse)
def get_server_vms(server_id: str):
    """
    특정 서버의 VM 목록 조회 (템플릿 제외)
    """
    try:
        vms = proxmox_service.get_vms(node=server_id)
        return VMResponse(vms=vms)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"VM 목록 조회 실패: {str(e)}",
        )


@router.get("/operations/risks")
def get_operational_risks(include_suppressed: bool = False):
    """
    운영 리스크 대시보드 조회 (read-only)
    """
    try:
        return proxmox_service.get_operational_risk_dashboard(include_suppressed=include_suppressed)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"운영 리스크 조회 실패: {str(e)}",
        )


@router.get("/operations/risks/overrides")
def list_operational_risk_overrides():
    """운영 리스크 acknowledge/suppress 상태 조회 (Gjallar DB only)."""
    try:
        return proxmox_service.list_operational_risk_overrides()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"운영 리스크 override 조회 실패: {str(e)}",
        )


@router.put("/operations/risks/overrides")
def update_operational_risk_override(request: OperationalRiskOverrideRequest):
    """운영 리스크 acknowledge/suppress 상태 저장 (Gjallar DB only)."""
    try:
        return proxmox_service.update_operational_risk_override(request.to_updates())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"운영 리스크 override 저장 실패: {str(e)}",
        )


@router.post("/operations/risks/overrides/clear")
def clear_operational_risk_override(request: OperationalRiskOverrideClearRequest):
    """운영 리스크 acknowledge/suppress 상태 제거 (Gjallar DB only)."""
    try:
        return proxmox_service.clear_operational_risk_override(request.risk_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"운영 리스크 override 삭제 실패: {str(e)}",
        )


@router.get("/operations/risks/thresholds")
def get_operational_risk_thresholds():
    """운영 리스크 threshold 설정 조회 (Gjallar local policy)."""
    try:
        return proxmox_service.get_operational_risk_thresholds()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"운영 리스크 threshold 조회 실패: {str(e)}",
        )


@router.put("/operations/risks/thresholds")
def update_operational_risk_thresholds(request: OperationalRiskThresholdUpdateRequest):
    """운영 리스크 threshold 설정 저장 (Gjallar DB only)."""
    try:
        return proxmox_service.update_operational_risk_thresholds(request.to_updates())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"운영 리스크 threshold 저장 실패: {str(e)}",
        )


@router.delete("/operations/risks/thresholds")
def reset_operational_risk_thresholds():
    """운영 리스크 threshold 설정을 기본값으로 초기화."""
    try:
        return proxmox_service.reset_operational_risk_thresholds()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"운영 리스크 threshold 초기화 실패: {str(e)}",
        )


@router.get("/monitoring/nodes")
def get_nodes_monitoring():
    """
    모든 노드의 모니터링 정보 조회
    """
    try:
        monitoring_data = proxmox_service.get_all_nodes_monitoring()
        return {"nodes": monitoring_data}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"노드 모니터링 정보 조회 실패: {str(e)}",
        )


@router.get("/monitoring/nodes/{node_id}")
def get_node_monitoring(node_id: str):
    """
    특정 노드의 상세 모니터링 정보 조회
    """
    try:
        status = proxmox_service.get_node_status(node_id)
        rrd_data = proxmox_service.get_node_rrddata(node_id, timeframe="hour")

        return {
            "node": node_id,
            "status": status,
            "rrd_data": rrd_data,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"노드 모니터링 정보 조회 실패: {str(e)}",
        )


@router.get("/monitoring/vms/{node_id}/{vmid}")
def get_vm_monitoring(node_id: str, vmid: int):
    """
    특정 VM의 모니터링 정보 조회
    """
    try:
        status = proxmox_service.get_vm_status(node_id, vmid)
        rrd_data = proxmox_service.get_vm_rrddata(node_id, vmid, timeframe="hour")

        return {
            "node": node_id,
            "vmid": vmid,
            "status": status,
            "rrd_data": rrd_data,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"VM 모니터링 정보 조회 실패: {str(e)}",
        )


# ============ IP Pool 관련 엔드포인트 ============

@router.get("/network/ip-pool/config")
def get_ip_pool_config():
    """
    IP 풀 설정 조회
    """
    config = network_service.get_pool_config()
    if not config:
        raise HTTPException(
            status_code=404,
            detail="IP 풀이 설정되지 않았습니다. .env 파일에 IP_POOL_START, IP_POOL_END, IP_GATEWAY를 설정하세요.",
        )
    return config


@router.get("/network/ip-pool/available")
def get_available_ips(limit: int = 10):
    """
    사용 가능한 IP 목록 조회 (ping으로 확인)
    """
    try:
        available_ips = network_service.get_available_ips(limit=limit)
        pool_config = network_service.get_pool_config()
        return {
            "available_ips": available_ips,
            "pool_config": pool_config,
            "count": len(available_ips),
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"사용 가능한 IP 조회 실패: {str(e)}",
        )


@router.get("/network/ip-pool/next")
def get_next_available_ip():
    """
    다음 사용 가능한 IP 반환
    """
    try:
        next_ip = network_service.get_next_available_ip()
        if not next_ip:
            raise HTTPException(
                status_code=404,
                detail="사용 가능한 IP가 없습니다.",
            )
        return next_ip
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"IP 조회 실패: {str(e)}",
        )


@router.get("/network/ip-pool/check/{ip}")
def check_ip_availability(ip: str):
    """
    특정 IP의 사용 가능 여부 확인
    """
    try:
        in_use = network_service.is_ip_in_use(ip)
        pool_config = network_service.get_pool_config()
        return {
            "ip": ip,
            "in_use": in_use,
            "available": not in_use,
            "gateway": pool_config["gateway"] if pool_config else None,
            "subnet": pool_config["subnet"] if pool_config else 24,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"IP 확인 실패: {str(e)}",
        )


__all__ = ["router"]
