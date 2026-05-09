"""
인프라 액션 실행 서비스 모듈 (LLM 도메인 commands 버전)

배경/의도/목적:
- LLM 도메인에서 사용하는 인프라 액션 어댑터를 한 곳에 모은다.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks
from pydantic import BaseModel, Field

from app.domains.deploy.service import DeploymentService
from app.domains.proxmox.service import ProxmoxService


class InfraActionType(str, Enum):
    """지원하는 인프라 액션 타입 정의"""

    LIST_VMS = "list_vms"
    LIST_NODES = "list_nodes"
    GET_VM_DETAIL = "get_vm_detail"
    CREATE_VM = "create_vm"
    # VM 생성 전 질의응답(슬롯 채우기)을 위한 보조 조회 액션들
    LIST_TEMPLATES = "list_templates"
    LIST_STORAGES = "list_storages"
    LIST_NETWORKS = "list_networks"


class InfraAction(BaseModel):
    """LLM이 제안한 액션을 백엔드에서 사용하는 표준 형태로 표현"""

    type: InfraActionType = Field(description="액션 타입")
    description: Optional[str] = Field(
        default=None,
        description="이 액션이 수행하는 작업에 대한 자연어 설명 (선택)",
    )
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="액션 실행에 필요한 파라미터 딕셔너리",
    )


class InfraActionResult(BaseModel):
    """액션 실행 결과를 프론트엔드/LLM에게 전달하기 위한 표준 응답 모델"""

    result_message: str = Field(description="사용자에게 보여줄 결과 메시지")
    raw_result: Any = Field(
        default=None,
        description="원본 결과 데이터 (리스트/딕셔너리 등, 필요 시 프론트에서 추가 처리)",
    )


class InfraActionService:
    """
    인프라 액션 실행 서비스

    - 액션 타입별로 올바른 서비스(ProxmoxService, DeploymentService 등)를 호출
    - LLM이 제안한 params 를 내부 서비스 입력 형식으로 변환
    - 사용자에게 의미 있는 result_message 를 생성
    """

    def __init__(self) -> None:
        self.proxmox_service = ProxmoxService()
        self.deployment_service = DeploymentService()

    def execute_action(
        self,
        action: InfraAction,
        background_tasks: Optional[BackgroundTasks] = None,
    ) -> InfraActionResult:
        if action.type == InfraActionType.LIST_VMS:
            return self._execute_list_vms(action)
        if action.type == InfraActionType.LIST_NODES:
            return self._execute_list_nodes(action)
        if action.type == InfraActionType.GET_VM_DETAIL:
            return self._execute_get_vm_detail(action)
        if action.type == InfraActionType.CREATE_VM:
            return self._execute_create_vm(action, background_tasks=background_tasks)
        if action.type == InfraActionType.LIST_TEMPLATES:
            return self._execute_list_templates(action)
        if action.type == InfraActionType.LIST_STORAGES:
            return self._execute_list_storages(action)
        if action.type == InfraActionType.LIST_NETWORKS:
            return self._execute_list_networks(action)

        return InfraActionResult(
            result_message=f"지원되지 않는 액션 타입입니다: {action.type}",
            raw_result={"supported_types": [t.value for t in InfraActionType]},
        )

    def _execute_list_vms(self, action: InfraAction) -> InfraActionResult:
        # NOTE:
        # - LLM 프롬프트에서는 Proxmox 노드를 가리키는 필드로
        #   "server_id" 또는 "server_name" 을 예시로 들고 있다.
        # - 반면 내부 ProxmoxService.get_vms() 는 "node" 파라미터만을 사용한다.
        # - 이 불일치 때문에 LLM이 node 대신 server_id/server_name 으로만 채워 보내면
        #   실제로는 모든 노드의 VM 이 조회되는 문제가 발생한다.
        # - 이를 방지하기 위해 여기서 세 필드를 모두 허용하고 우선순위를 두어
        #   canonical 한 node 값으로 정규화한 뒤 ProxmoxService 로 넘긴다.
        node = (
            action.params.get("node")
            or action.params.get("server_id")
            or action.params.get("server_name")
        )
        if isinstance(node, str):
            node = node.strip() or None

        vms = self.proxmox_service.get_vms(node=node)

        count = len(vms)
        if node:
            header = f"노드 '{node}'에서 {count}개의 VM을 조회했습니다."
        else:
            header = f"모든 노드에서 {count}개의 VM을 조회했습니다."

        if count == 0:
            msg = header + "\n(표시할 VM이 없습니다.)"
        else:
            preview_lines = []
            for vm in vms[:5]:
                name = vm.get("name") or vm.get("vm_id") or vm.get("id") or "이름 없음"
                status = vm.get("status", "unknown")
                node_name = vm.get("node", "-")
                cpu = vm.get("cpu_cores", 0)
                mem = vm.get("memory_gb", 0)
                preview_lines.append(
                    f"- {name} (노드: {node_name}, 상태: {status}, CPU: {cpu}, 메모리: {mem}GB)"
                )

            if count > 5:
                preview_lines.append(f"... 그 외 {count - 5}개 VM 더 있음")

            msg = header + "\n\n" + "\n".join(preview_lines)

        return InfraActionResult(result_message=msg, raw_result={"vms": vms})

    def _execute_list_nodes(self, action: InfraAction) -> InfraActionResult:
        nodes = self.proxmox_service.get_nodes()
        count = len(nodes)
        if count == 0:
            msg = "조회할 수 있는 Proxmox 노드가 없습니다."
        else:
            lines = [
                f"- {n.get('name') or n.get('server_name') or n.get('id') or '이름 없음'} "
                f"(상태: {n.get('status', 'unknown')}, CPU: {n.get('cpu', 0)}, 메모리: {n.get('memory', 0)})"
                for n in nodes
            ]
            msg = f"{count}개의 Proxmox 노드를 조회했습니다.\n\n" + "\n".join(lines)

        return InfraActionResult(
            result_message=msg,
            raw_result={"nodes": nodes},
        )

    def _execute_get_vm_detail(self, action: InfraAction) -> InfraActionResult:
        vm_id = action.params.get("vm_id") or action.params.get("id")
        if not isinstance(vm_id, str) or "/" not in vm_id:
            return InfraActionResult(
                result_message="vm_id 파라미터가 올바른 형식이 아닙니다. 예: 'pve-node/100'.",
                raw_result={"vm_id": vm_id},
            )

        node, vmid_str = vm_id.split("/", 1)
        try:
            vmid = int(vmid_str)
        except ValueError:
            return InfraActionResult(
                result_message="vm_id의 VM ID 부분이 숫자가 아닙니다.",
                raw_result={"vm_id": vm_id},
            )

        status = self.proxmox_service.get_vm_status(node=node, vmid=vmid)
        if status is None:
            msg = f"VM 상태를 조회하지 못했습니다: {vm_id}"
        else:
            msg = f"VM '{vm_id}'의 현재 상태를 조회했습니다."

        return InfraActionResult(
            result_message=msg,
            raw_result={"vm_id": vm_id, "status": status},
        )

    # ------------------------------------------------------------------
    # VM 생성 전 질의응답(슬롯 채우기)을 위한 Proxmox 리소스 조회 액션들
    # ------------------------------------------------------------------

    def _execute_list_templates(self, action: InfraAction) -> InfraActionResult:
        """
        Proxmox VM 템플릿 목록 조회 액션.

        - LLM이 VM 생성 옵션 안내를 위해 사용할 수 있도록
          사람이 읽기 좋은 요약 메시지와 함께 원본 리스트를 반환한다.
        """
        node = action.params.get("node") or action.params.get("server_id") or None
        if isinstance(node, str):
            node = node.strip() or None

        templates = self.proxmox_service.get_templates(node=node)
        count = len(templates)

        if count == 0:
            header = "사용 가능한 VM 템플릿을 찾지 못했습니다."
            msg = header + "\n(템플릿이 있는지 Proxmox를 확인해 보세요.)"
        else:
            header = f"사용 가능한 VM 템플릿 {count}개를 조회했습니다."
            preview_lines = []
            for t in templates[:10]:
                name = t.get("template_name") or t.get("name") or "이름 없음"
                template_id = t.get("template_id") or t.get("id") or "-"
                node_name = t.get("node", "-")
                cpu = t.get("cpu_cores", 0)
                mem = t.get("memory_gb", 0)
                preview_lines.append(
                    f"- {name} (ID: {template_id}, 노드: {node_name}, CPU: {cpu}, 메모리: {mem}GB)"
                )
            if count > 10:
                preview_lines.append(f"... 그 외 {count - 10}개 템플릿 더 있음")
            msg = header + "\n\n" + "\n".join(preview_lines)

        return InfraActionResult(
            result_message=msg,
            raw_result={"templates": templates},
        )

    def _execute_list_storages(self, action: InfraAction) -> InfraActionResult:
        """
        Proxmox 스토리지 목록 조회 액션.

        - VM 디스크를 어느 스토리지에 배치할지 선택하기 위해 사용된다.
        """
        node = action.params.get("node") or action.params.get("server_id") or None
        if isinstance(node, str):
            node = node.strip() or None

        storages = self.proxmox_service.get_storages(node=node)
        count = len(storages)

        if count == 0:
            header = "사용 가능한 스토리지를 찾지 못했습니다."
            msg = header + "\n(Proxmox 스토리지 구성을 확인해 보세요.)"
        else:
            header = f"사용 가능한 스토리지 {count}개를 조회했습니다."
            preview_lines = []
            for s in storages[:10]:
                name = s.get("storage_name") or s.get("name") or s.get("storage_id") or "이름 없음"
                storage_id = s.get("storage_id") or s.get("id") or "-"
                stype = s.get("type", "unknown")
                size_gb = s.get("size_gb")
                avail_gb = s.get("available_gb")
                capacity_text = ""
                if size_gb is not None:
                    capacity_text = f", 용량: {size_gb}GB"
                    if avail_gb is not None:
                        capacity_text += f" (가용: {avail_gb}GB)"
                preview_lines.append(
                    f"- {name} (ID: {storage_id}, 타입: {stype}{capacity_text})"
                )
            if count > 10:
                preview_lines.append(f"... 그 외 {count - 10}개 스토리지 더 있음")
            msg = header + "\n\n" + "\n".join(preview_lines)

        return InfraActionResult(
            result_message=msg,
            raw_result={"storages": storages},
        )

    def _execute_list_networks(self, action: InfraAction) -> InfraActionResult:
        """
        Proxmox 네트워크(브리지) 목록 조회 액션.

        - VM NIC 를 어느 브리지/네트워크에 연결할지 선택하기 위해 사용된다.
        """
        node = action.params.get("node") or action.params.get("server_id") or None
        if isinstance(node, str):
            node = node.strip() or None

        networks = self.proxmox_service.get_networks(node=node)
        count = len(networks)

        if count == 0:
            header = "사용 가능한 네트워크(브리지)를 찾지 못했습니다."
            msg = header + "\n(Proxmox 네트워크 설정을 확인해 보세요.)"
        else:
            header = f"사용 가능한 네트워크 {count}개를 조회했습니다."
            preview_lines = []
            for n in networks[:15]:
                name = n.get("network_name") or n.get("name") or n.get("network_id") or "이름 없음"
                network_id = n.get("network_id") or n.get("id") or "-"
                ntype = n.get("type", "bridge")
                cidr = n.get("cidr") or ""
                desc = n.get("description") or ""
                extra = []
                if cidr:
                    extra.append(cidr)
                if desc:
                    extra.append(desc)
                extra_text = f" ({', '.join(extra)})" if extra else ""
                preview_lines.append(
                    f"- {name} (ID: {network_id}, 타입: {ntype}{extra_text})"
                )
            if count > 15:
                preview_lines.append(f"... 그 외 {count - 15}개 네트워크 더 있음")
            msg = header + "\n\n" + "\n".join(preview_lines)

        return InfraActionResult(
            result_message=msg,
            raw_result={"networks": networks},
        )

    def _execute_create_vm(
        self,
        action: InfraAction,
        background_tasks: Optional[BackgroundTasks],
    ) -> InfraActionResult:
        params = action.params or {}

        if not params.get("template_id"):
            return InfraActionResult(
                result_message=(
                    "VM 생성에는 template_id 가 필요합니다. "
                    "먼저 템플릿 목록을 조회하고 하나를 선택해 주세요."
                ),
                raw_result={"missing": "template_id"},
            )

        if background_tasks is None:
            return InfraActionResult(
                result_message="VM 생성 액션에는 BackgroundTasks 인스턴스가 필요합니다.",
                raw_result=None,
            )

        deploy_request: Dict[str, Any] = {}

        if "server_name" in params:
            deploy_request["server_name"] = params["server_name"]
        if "server_id" in params:
            deploy_request["server_id"] = params["server_id"]
        if "template_id" in params:
            deploy_request["template_id"] = params["template_id"]
        if "cpu_cores" in params:
            deploy_request["cpu_cores"] = params["cpu_cores"]
        if "memory_gb" in params:
            deploy_request["memory_gb"] = params["memory_gb"]
        if "disk_size_gb" in params:
            deploy_request["disk_size_gb"] = params["disk_size_gb"]
        if "storage_id" in params:
            deploy_request["storage_id"] = params["storage_id"]
        if "network_ids" in params:
            deploy_request["network_ids"] = params["network_ids"]

        if "ansible_packages" in params:
            deploy_request["ansible_packages"] = params["ansible_packages"]
        if "ansible_roles" in params:
            deploy_request["ansible_roles"] = params["ansible_roles"]

        task_id = self.deployment_service.start_deployment_with_request(
            background_tasks=background_tasks,
            deploy_request=deploy_request,
            skip_terraform=False,
            skip_ansible=False,
        )

        server_name = deploy_request.get("server_name") or "(이름 미지정)"
        msg = f"VM 생성 배포 작업을 시작했습니다. 이름: {server_name}, task_id: {task_id}"

        return InfraActionResult(
            result_message=msg,
            raw_result={
                "task_id": task_id,
                "deploy_request": deploy_request,
            },
        )


__all__ = [
    "InfraActionService",
    "InfraAction",
    "InfraActionResult",
    "InfraActionType",
]
