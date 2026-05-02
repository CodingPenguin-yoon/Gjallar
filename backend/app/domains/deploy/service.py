"""배포 작업 통합 서비스 모듈 (deploy 도메인)."""

from __future__ import annotations

import os
import socket
import tempfile
import time
import uuid
from urllib.parse import urljoin

from fastapi import BackgroundTasks
from typing import Any, Dict, Optional
import requests

from app.shared.tasks import task_manager, TaskStatus
from app.shared.gitlab_settings import get_gitlab_settings
from app.domains.staging.service import StagingHostRegistryError, StagingHostRegistryService
from app.integrations.terraform import TerraformService
from app.integrations.ansible import AnsibleService
from app.domains.proxmox.service import ProxmoxService


class DeploymentService:
    """
    배포 작업을 통합 관리하는 서비스 클래스

    Terraform과 Ansible을 순차적으로 실행하여 인프라 배포를 수행합니다.
    BackgroundTasks를 활용하여 비동기적으로 작업을 처리합니다.
    """

    def __init__(self):
        """초기화: Terraform 및 Ansible 서비스 인스턴스 생성"""
        self.terraform_service = TerraformService()
        self.ansible_service = AnsibleService()
        self.proxmox_service = ProxmoxService()
        self.staging_host_registry_service = StagingHostRegistryService()

    def start_deployment(
        self,
        background_tasks: BackgroundTasks,
        skip_terraform: bool = False,
        skip_ansible: bool = False,
    ) -> str:
        """
        배포 작업 시작

        Args:
            background_tasks: FastAPI BackgroundTasks 인스턴스
            skip_terraform: Terraform 단계 건너뛰기 여부
            skip_ansible: Ansible 단계 건너뛰기 여부

        Returns:
            생성된 task_id
        """
        # 고유 작업 ID 생성
        task_id = str(uuid.uuid4())

        # 작업 초기화
        task_manager.create_task(
            task_id,
            metadata={
                "action": "deploy",
                "skip_terraform": skip_terraform,
                "skip_ansible": skip_ansible,
            },
        )
        task_manager.update_status(task_id, TaskStatus.PENDING)

        # 백그라운드 작업 등록
        background_tasks.add_task(
            self._execute_deployment,
            task_id,
            skip_terraform,
            skip_ansible,
            None,  # deploy_request는 나중에 추가 가능
        )

        return task_id

    def start_deployment_with_request(
        self,
        background_tasks: BackgroundTasks,
        deploy_request: dict,
        skip_terraform: bool = False,
        skip_ansible: bool = False,
    ) -> str:
        """
        배포 요청 정보와 함께 배포 작업 시작

        Args:
            background_tasks: FastAPI BackgroundTasks 인스턴스
            deploy_request: 배포 요청 정보 딕셔너리
            skip_terraform: Terraform 단계 건너뛰기 여부
            skip_ansible: Ansible 단계 건너뛰기 여부

        Returns:
            생성된 task_id
        """
        # 고유 작업 ID 생성
        task_id = str(uuid.uuid4())

        task_metadata = {
            "action": "deploy",
            "server_name": deploy_request.get("server_name"),
            "server_id": deploy_request.get("server_id"),
            "template_id": deploy_request.get("template_id"),
            "storage_id": deploy_request.get("storage_id"),
            "network_ids": deploy_request.get("network_ids") or [],
            "cpu_cores": deploy_request.get("cpu_cores"),
            "memory_gb": deploy_request.get("memory_gb"),
            "requested_vm_ip": deploy_request.get("vm_ip"),
            "requested_vm_gateway": deploy_request.get("vm_gateway"),
            "ansible_packages": deploy_request.get("ansible_packages") or [],
            "ansible_roles": deploy_request.get("ansible_roles") or [],
            "gitlab_project_id": deploy_request.get("gitlab_project_id"),
            "deploy_branch": deploy_request.get("deploy_branch"),
            "path_with_namespace": deploy_request.get("path_with_namespace"),
            "staging_target_mode": deploy_request.get("staging_target_mode"),
            "target_host_ip": deploy_request.get("target_host_ip"),
            "target_host_name": deploy_request.get("target_host_name"),
            "app_deploy_enabled": bool(deploy_request.get("app_deploy_enabled")),
            "compose_file": deploy_request.get("compose_file"),
            "app_port": deploy_request.get("app_port"),
            "healthcheck_type": deploy_request.get("healthcheck_type"),
            "healthcheck_path": deploy_request.get("healthcheck_path"),
            "healthcheck_port": deploy_request.get("healthcheck_port"),
            "healthcheck_command": deploy_request.get("healthcheck_command"),
            "create_as_staging_host": bool(deploy_request.get("create_as_staging_host")),
            "skip_terraform": skip_terraform,
            "skip_ansible": skip_ansible,
        }
        extra_metadata = deploy_request.get("metadata")
        if isinstance(extra_metadata, dict):
            task_metadata.update(extra_metadata)

        # 작업 초기화
        task_manager.create_task(task_id, metadata=task_metadata)
        task_manager.update_status(task_id, TaskStatus.PENDING)

        # 백그라운드 작업 등록
        background_tasks.add_task(
            self._execute_deployment,
            task_id,
            skip_terraform,
            skip_ansible,
            deploy_request,
        )

        return task_id

    def _execute_deployment(
        self,
        task_id: str,
        skip_terraform: bool = False,
        skip_ansible: bool = False,
        deploy_request: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        실제 배포 작업 실행 (내부 메서드)

        Terraform apply -> post-clone VM 조정 -> Ansible playbook 순차 실행

        Args:
            task_id: 작업 식별자
            skip_terraform: Terraform 단계 건너뛰기 여부
            skip_ansible: Ansible 단계 건너뛰기 여부
            deploy_request: 배포 요청 정보 (선택적)
        """
        vm_ip = None  # Terraform에서 추출한 IP 주소
        app_source_archive_path: Optional[str] = None
        ansible_executed = False
        ansible_skipped_due_to_missing_ip = False
        target_host_ip = str((deploy_request or {}).get("target_host_ip") or "").strip()
        target_host_name = str((deploy_request or {}).get("target_host_name") or "shared-staging-host").strip()
        target_host_user = str(
            (deploy_request or {}).get("target_host_user") or os.getenv("ANSIBLE_SSH_USER", "root")
        ).strip() or "root"
        workspace_key = (
            (deploy_request or {}).get("server_name")
            or f"task-{task_id[:8]}"
        )
        task_manager.update_metadata(task_id, {"terraform_workspace_key": workspace_key})

        try:
            task_manager.update_status(task_id, TaskStatus.RUNNING)
            task_manager.update_progress(
                task_id,
                1.0,
                text="배포 시작",
                source="phase",
            )
            task_manager.append_log(task_id, "=== 배포 작업 시작 ===")

            # 배포 요청 정보 로깅
            if deploy_request:
                task_manager.append_log(
                    task_id,
                    f"배포 설정: {self._summarize_deploy_request(deploy_request)}",
                )

            # 1단계: Terraform Init
            if not skip_terraform:
                task_manager.append_log(task_id, "\n[1/5] Terraform Init 실행 중...")
                task_manager.update_progress(
                    task_id,
                    5.0,
                    text="Terraform Init",
                    source="phase",
                )
                success, error = self.terraform_service.init(task_id)
                if not success:
                    task_manager.update_status(task_id, TaskStatus.FAILED)
                    task_manager.append_log(task_id, f"Terraform Init 실패: {error}")
                    return

                # 멱등성 보장을 위해 인스턴스별 workspace 사용
                ws_ok, ws_result = self.terraform_service.select_or_create_workspace(
                    task_id=task_id,
                    workspace=workspace_key,
                )
                if not ws_ok:
                    task_manager.update_status(task_id, TaskStatus.FAILED)
                    task_manager.append_log(task_id, f"Terraform workspace 설정 실패: {ws_result}")
                    return
                workspace_name = ws_result
                task_manager.update_metadata(task_id, {"terraform_workspace": workspace_name})

                # 선택적: legacy local state 자동 이관(기본 비활성화)
                auto_migrate_legacy_state = os.getenv(
                    "TF_AUTO_MIGRATE_LEGACY_STATE",
                    "false",
                ).strip().lower() in {"1", "true", "yes", "on"}
                if auto_migrate_legacy_state:
                    migrate_force = os.getenv(
                        "TF_AUTO_MIGRATE_LEGACY_STATE_FORCE",
                        "false",
                    ).strip().lower() in {"1", "true", "yes", "on"}
                    migrate_strict = os.getenv(
                        "TF_AUTO_MIGRATE_LEGACY_STATE_STRICT",
                        "false",
                    ).strip().lower() in {"1", "true", "yes", "on"}

                    mig_ok, mig_msg = self.terraform_service.migrate_legacy_local_state(
                        workspace=workspace_name,
                        task_id=task_id,
                        force=migrate_force,
                    )
                    if mig_ok:
                        task_manager.append_log(task_id, f"Legacy state migration: {mig_msg}")
                    else:
                        task_manager.append_log(task_id, f"경고: Legacy state migration 실패: {mig_msg}")
                        if migrate_strict:
                            task_manager.update_status(task_id, TaskStatus.FAILED)
                            task_manager.append_log(task_id, "엄격 모드로 인해 배포를 중단합니다.")
                            return

                # 2단계: Terraform Plan (선택적)
                task_manager.append_log(task_id, "\n[2/5] Terraform Plan 실행 중...")
                task_manager.update_progress(
                    task_id,
                    12.0,
                    text="Terraform Plan",
                    source="phase",
                )
                success, error = self.terraform_service.plan(
                    task_id=task_id,
                    workspace=workspace_name,
                )
                if not success:
                    task_manager.append_log(task_id, f"Terraform Plan 경고: {error}")
                    # Plan 실패는 치명적이지 않을 수 있으므로 계속 진행

                # 3단계: Terraform Apply (프론트엔드 입력값을 변수로 전달)
                task_manager.append_log(task_id, "\n[3/5] Terraform Apply 실행 중...")
                task_manager.update_progress(
                    task_id,
                    20.0,
                    text="Terraform Apply 시작",
                    source="phase",
                )

                # 프론트엔드 입력값을 Terraform 변수로 변환
                terraform_vars: Dict[str, Any] = {}
                if deploy_request:
                    # VM 이름
                    if deploy_request.get("server_name"):
                        terraform_vars["vm_name"] = deploy_request["server_name"]

                    # 타겟 노드 (서버)
                    if deploy_request.get("server_id"):
                        terraform_vars["target_node"] = deploy_request["server_id"]

                    # 템플릿 ID (형식: node/template-vmid)
                    if deploy_request.get("template_id"):
                        # template_id가 이미 "node/vmid" 형식인지 확인
                        if "/" in str(deploy_request["template_id"]):
                            terraform_vars["template_id"] = deploy_request["template_id"]
                        else:
                            # template_id만 있으면 노드와 조합 필요 (나중에 개선 가능)
                            terraform_vars["template_id"] = deploy_request["template_id"]

                    if (
                        deploy_request.get("cpu_cores") is not None
                        or deploy_request.get("memory_gb") is not None
                    ):
                        task_manager.append_log(
                            task_id,
                            "요청된 CPU/메모리는 Terraform 생성 단계가 아니라 clone 후 VM 조정 단계에서 적용합니다.",
                        )

                    # 디스크 크기 (기본값 50GB)
                    terraform_vars["disk_size_gb"] = deploy_request.get("disk_size_gb", 50)

                    # 스토리지
                    if deploy_request.get("storage_id"):
                        terraform_vars["storage_id"] = deploy_request["storage_id"]

                    # 네트워크 (리스트)
                    if deploy_request.get("network_ids"):
                        terraform_vars["network_ids"] = deploy_request["network_ids"]

                    # VM IP 주소 (고정 IP 설정)
                    if deploy_request.get("vm_ip"):
                        terraform_vars["vm_ip"] = deploy_request["vm_ip"]
                        task_manager.append_log(
                            task_id, f"고정 IP 설정: {deploy_request['vm_ip']}"
                        )

                    # Gateway 주소
                    if deploy_request.get("vm_gateway"):
                        terraform_vars["vm_gateway"] = deploy_request["vm_gateway"]

                    # SSH 공개키 주입 (Ansible 연결을 위해 필수)
                    ssh_public_key = self._read_ssh_public_key()
                    if ssh_public_key:
                        terraform_vars["ssh_public_key"] = ssh_public_key
                        terraform_vars["ssh_user"] = os.getenv("ANSIBLE_SSH_USER", "root")
                        task_manager.append_log(
                            task_id, "SSH 공개키 설정 완료 (cloud-init으로 VM에 주입)"
                        )
                    else:
                        task_manager.append_log(
                            task_id,
                            "경고: SSH 공개키를 찾을 수 없습니다. Ansible 연결이 실패할 수 있습니다.",
                        )

                    task_manager.append_log(
                        task_id,
                        f"Terraform 변수 요약: {self._summarize_terraform_vars(terraform_vars)}",
                    )

                success, error = self.terraform_service.apply(
                    task_id,
                    auto_approve=True,
                    variables=terraform_vars if terraform_vars else None,
                    workspace=workspace_name,
                )
                if not success:
                    task_manager.update_status(task_id, TaskStatus.FAILED)
                    task_manager.append_log(task_id, f"Terraform Apply 실패: {error}")
                    return

                task_manager.append_log(task_id, "Terraform Apply 완료")
                task_manager.update_progress(
                    task_id,
                    85.0,
                    text="Terraform Apply 완료",
                    source="phase",
                )

                # Terraform Output에서 IP 주소 추출
                task_manager.append_log(task_id, "Terraform Output에서 IP 주소 추출 중...")
                terraform_outputs = self.terraform_service.get_output(
                    workspace=workspace_name,
                )
                task_manager.append_log(
                    task_id,
                    f"Terraform Outputs 요약: {self._summarize_terraform_outputs(terraform_outputs)}",
                )
                self._record_vm_identity_metadata(task_id, deploy_request, terraform_outputs)

                # IP 주소 추출 (vm_ip, instance_ip, ip_address 등 다양한 키 이름 지원)
                vm_ip = None
                for key in [
                    "vm_ip",
                    "instance_ip",
                    "ip_address",
                    "ip",
                    "default_ipv4_address",
                ]:
                    if key in terraform_outputs:
                        vm_ip = terraform_outputs[key]
                        break

                # Output이 딕셔너리인 경우 value 추출
                if vm_ip and isinstance(vm_ip, dict):
                    vm_ip = vm_ip.get("value", vm_ip)

                if vm_ip:
                    task_manager.append_log(task_id, f"추출된 IP 주소: {vm_ip}")
                    task_manager.update_metadata(task_id, {"vm_ip": str(vm_ip)})
                else:
                    task_manager.append_log(
                        task_id, "경고: Terraform Output에서 IP 주소를 찾을 수 없습니다."
                    )

                self._maybe_adjust_cloned_vm_resources(
                    task_id=task_id,
                    deploy_request=deploy_request,
                    terraform_outputs=terraform_outputs,
                )
            else:
                task_manager.append_log(task_id, "Terraform 단계 건너뛰기")
                if target_host_ip:
                    vm_ip = target_host_ip
                    task_manager.append_log(
                        task_id,
                        f"Shared staging host 사용: {target_host_name} ({target_host_ip})",
                    )
                    task_manager.update_metadata(
                        task_id,
                        {
                            "vm_ip": target_host_ip,
                            "target_host_ip": target_host_ip,
                            "target_host_name": target_host_name,
                        },
                    )

            # 5단계: Ansible Playbook 실행
            # IP가 없으면 Ansible 건너뛰기
            if not skip_ansible and not vm_ip:
                task_manager.append_log(
                    task_id,
                    "\n[5/5] Ansible 건너뛰기: VM IP 주소를 가져올 수 없습니다. "
                    "(VM에 qemu-guest-agent가 설치되어 있는지 확인하세요)"
                )
                skip_ansible = True
                ansible_skipped_due_to_missing_ip = True

            if not skip_ansible:
                task_manager.append_log(task_id, "\n[5/5] Ansible Playbook 실행 중...")
                task_manager.update_progress(
                    task_id,
                    92.0,
                    text="Ansible Playbook 실행",
                    source="phase",
                )

                # Inventory 호스트 정보 준비 (Terraform에서 추출한 IP 사용)
                inventory_hosts = None
                if vm_ip:
                    self._wait_for_ansible_ssh_readiness(task_id, str(vm_ip))
                    inventory_hosts = [
                        {
                            "name": target_host_name if skip_terraform and target_host_ip else "proxmox_vm",
                            "ip": str(vm_ip),
                            "user": target_host_user if skip_terraform and target_host_ip else os.getenv("ANSIBLE_SSH_USER", "root"),
                        }
                    ]
                    task_manager.append_log(task_id, f"Ansible Inventory에 IP {vm_ip} 추가")

                # Ansible extra_vars 준비 (선택한 패키지 및 역할)
                extra_vars: dict[str, object] = {}
                if deploy_request:
                    packages = deploy_request.get("ansible_packages", [])
                    roles = deploy_request.get("ansible_roles", [])

                    if packages:
                        extra_vars["packages_to_install"] = packages
                        task_manager.append_log(
                            task_id, f"설치할 패키지: {', '.join(packages)}"
                        )

                    if roles:
                        extra_vars["roles_to_apply"] = roles
                        task_manager.append_log(
                            task_id, f"적용할 역할: {', '.join(roles)}"
                        )

                    app_extra_vars, app_source_archive_path = self._prepare_app_deploy_extra_vars(
                        task_id=task_id,
                        deploy_request=deploy_request,
                    )
                    if app_extra_vars:
                        extra_vars.update(app_extra_vars)
                        task_manager.update_metadata(
                            task_id,
                            {
                                "app_deploy_status": "prepared",
                                "app_project_slug": app_extra_vars.get("deploy_project_slug"),
                                "app_source_ref": app_extra_vars.get("deploy_source_ref"),
                            },
                        )

                success, error = self.ansible_service.run_playbook(
                    playbook_file="playbook.yml",
                    task_id=task_id,
                    inventory_hosts=inventory_hosts,
                    extra_vars=extra_vars if extra_vars else None,
                )
                if not success:
                    task_manager.update_status(task_id, TaskStatus.FAILED)
                    task_manager.append_log(task_id, f"Ansible Playbook 실행 실패: {error}")
                    return

                task_manager.append_log(task_id, "Ansible Playbook 실행 완료")
                ansible_executed = True
                if deploy_request and deploy_request.get("app_deploy_enabled"):
                    task_manager.update_metadata(
                        task_id,
                        {
                            "app_deploy_status": "success",
                        },
                    )
                task_manager.update_progress(
                    task_id,
                    98.0,
                    text="Ansible Playbook 완료",
                    source="phase",
                )
            else:
                task_manager.append_log(task_id, "Ansible 단계 건너뛰기")
                task_manager.update_progress(
                    task_id,
                    98.0,
                    text="Ansible 건너뛰기",
                    source="phase",
                )

            if deploy_request and deploy_request.get("create_as_staging_host"):
                self._finalize_staging_host_registration(
                    task_id=task_id,
                    deploy_request=deploy_request,
                    vm_ip=str(vm_ip or "").strip(),
                    ansible_executed=ansible_executed,
                    ansible_skipped_due_to_missing_ip=ansible_skipped_due_to_missing_ip,
                )

            # 배포 성공
            task_manager.update_status(task_id, TaskStatus.SUCCESS)
            task_manager.append_log(task_id, "\n=== 배포 작업 완료 ===")

        except Exception as e:
            # 예외 발생 시 실패 처리
            error_msg = f"배포 작업 중 예외 발생: {str(e)}"
            task_manager.update_status(task_id, TaskStatus.FAILED)
            task_manager.append_log(task_id, f"EXCEPTION: {error_msg}")
            if deploy_request and deploy_request.get("app_deploy_enabled"):
                task_manager.update_metadata(
                    task_id,
                    {
                        "app_deploy_status": "failed",
                    },
                )
        finally:
            self._cleanup_local_app_bundle(task_id, app_source_archive_path)

    def _finalize_staging_host_registration(
        self,
        *,
        task_id: str,
        deploy_request: Dict[str, Any],
        vm_ip: str,
        ansible_executed: bool,
        ansible_skipped_due_to_missing_ip: bool,
    ) -> None:
        if ansible_skipped_due_to_missing_ip or not vm_ip:
            raise RuntimeError(
                "Staging host preset requires a reachable VM IP and completed Ansible bootstrap."
            )
        if not ansible_executed:
            raise RuntimeError(
                "Staging host preset requires the Ansible bootstrap step to complete successfully."
            )

        node_name, vmid = self._resolve_vm_identity(
            task_id=task_id,
            deploy_request=deploy_request,
            terraform_outputs={},
        )
        if not node_name or vmid is None:
            raise RuntimeError("Staging host registration requires resolved node/vmid metadata.")

        host_name = str(
            deploy_request.get("server_name")
            or (task_manager.get_status(task_id) or {}).get("metadata", {}).get("vm_name")
            or ""
        ).strip() or None

        try:
            registered = self.staging_host_registry_service.register_host(
                {
                    "environment": "staging",
                    "node": node_name,
                    "vmid": vmid,
                    "name": host_name,
                    "host_ip": vm_ip,
                    "host_user": os.getenv("ANSIBLE_SSH_USER", "root"),
                    "pool_key": "default",
                    "role": "shared",
                    "bootstrap_status": "ready",
                    "enabled": True,
                    "drain_mode": False,
                    "source_task_id": task_id,
                }
            )
        except StagingHostRegistryError as exc:
            raise RuntimeError(f"Staging host registry update failed: {exc}") from exc

        task_manager.update_metadata(
            task_id,
            {
                "staging_host_registered": True,
                "staging_host_registry_id": registered.get("id"),
                "staging_host_pool_key": registered.get("pool_key"),
            },
        )
        task_manager.append_log(
            task_id,
            f"Staging host registry 등록 완료: {registered.get('node')}/{registered.get('vmid')} -> {registered.get('host_ip')}",
        )

    def _record_vm_identity_metadata(
        self,
        task_id: str,
        deploy_request: Optional[Dict[str, Any]],
        terraform_outputs: Dict[str, Any],
    ) -> None:
        metadata: Dict[str, Any] = {}

        node_name = str((deploy_request or {}).get("server_id") or "").strip()
        if node_name:
            metadata["vm_node"] = node_name

        raw_vm_id = terraform_outputs.get("vm_id")
        if isinstance(raw_vm_id, dict):
            raw_vm_id = raw_vm_id.get("value", raw_vm_id)
        try:
            if raw_vm_id is not None and str(raw_vm_id).strip():
                metadata["vm_id"] = int(raw_vm_id)
        except (TypeError, ValueError):
            pass

        raw_vm_name = terraform_outputs.get("vm_name")
        if isinstance(raw_vm_name, dict):
            raw_vm_name = raw_vm_name.get("value", raw_vm_name)
        if raw_vm_name is not None and str(raw_vm_name).strip():
            metadata["vm_name"] = str(raw_vm_name).strip()

        if metadata:
            task_manager.update_metadata(task_id, metadata)

    def _maybe_adjust_cloned_vm_resources(
        self,
        *,
        task_id: str,
        deploy_request: Optional[Dict[str, Any]],
        terraform_outputs: Dict[str, Any],
    ) -> None:
        if not deploy_request or not deploy_request.get("template_id"):
            return

        requested_cpu = deploy_request.get("cpu_cores")
        requested_memory = deploy_request.get("memory_gb")
        if requested_cpu is None and requested_memory is None:
            task_manager.append_log(
                task_id,
                "[4/5] VM 하드웨어 조정 건너뛰기: CPU/메모리 요청값이 없습니다.",
            )
            task_manager.update_metadata(
                task_id,
                {
                    "post_clone_resize_status": "skipped",
                    "post_clone_resize_reason": "no_requested_resources",
                },
            )
            return

        node_name, vmid = self._resolve_vm_identity(
            task_id=task_id,
            deploy_request=deploy_request,
            terraform_outputs=terraform_outputs,
        )
        if not node_name or vmid is None:
            raise RuntimeError("clone된 VM 식별 정보(node/vmid)를 확인할 수 없습니다.")

        current_status = self._wait_for_vm_status_snapshot(node_name, vmid)
        if current_status is None:
            raise RuntimeError(f"VM 상태 조회에 실패했습니다: {node_name}/{vmid}")

        current_cpu = self._extract_vm_cpu_cores(current_status)
        current_memory_gb = self._extract_vm_memory_gb(current_status)
        target_cpu = int(requested_cpu) if requested_cpu is not None else current_cpu
        target_memory_gb = (
            float(requested_memory)
            if requested_memory is not None
            else current_memory_gb
        )

        if target_cpu is None or target_memory_gb is None:
            raise RuntimeError("VM 현재 CPU/메모리 값을 확인할 수 없어 post-clone 조정을 진행할 수 없습니다.")

        task_manager.append_log(
            task_id,
            f"[4/5] VM 하드웨어 조정 확인: {node_name}/{vmid} "
            f"(current: {current_cpu} cores, {current_memory_gb}GB -> "
            f"target: {target_cpu} cores, {target_memory_gb}GB)",
        )

        if (
            current_cpu is not None
            and current_memory_gb is not None
            and current_cpu == target_cpu
            and abs(current_memory_gb - target_memory_gb) < 0.01
        ):
            task_manager.append_log(
                task_id,
                "[4/5] VM 하드웨어 조정 건너뛰기: 현재 스펙이 이미 요청값과 일치합니다.",
            )
            task_manager.update_metadata(
                task_id,
                {
                    "post_clone_resize_status": "already_aligned",
                    "post_clone_resize_node": node_name,
                    "post_clone_resize_vmid": vmid,
                    "post_clone_resize_cpu_cores": target_cpu,
                    "post_clone_resize_memory_gb": target_memory_gb,
                },
            )
            return

        task_manager.update_progress(
            task_id,
            88.0,
            text="Post-clone VM 조정",
            source="phase",
        )

        self._ensure_vm_stopped_for_resize(task_id, node_name, vmid)

        update_result = self.proxmox_service.update_vm_resources(
            node_name,
            vmid,
            cpu_cores=target_cpu,
            memory_gb=target_memory_gb,
        )
        if not update_result.get("success"):
            raise RuntimeError(update_result.get("error") or "VM 하드웨어 조정에 실패했습니다.")

        resize_upid = str(update_result.get("upid") or "").strip()
        if resize_upid:
            wait_result = self.proxmox_service.wait_for_task_completion(
                node_name,
                resize_upid,
                timeout_seconds=120,
            )
            if not wait_result.get("success"):
                raise RuntimeError(
                    wait_result.get("error")
                    or "VM 하드웨어 조정 task 완료를 확인하지 못했습니다."
                )

        task_manager.append_log(
            task_id,
            f"VM CPU/메모리 조정 완료: {target_cpu} cores, {target_memory_gb}GB",
        )

        start_result = self.proxmox_service.perform_vm_action(
            node_name,
            vmid,
            action="start",
            timeout_seconds=120,
        )
        if not start_result.get("success"):
            raise RuntimeError(start_result.get("error") or "VM 재시작에 실패했습니다.")

        task_manager.append_log(task_id, "VM 재시작 완료")
        task_manager.update_metadata(
            task_id,
            {
                "post_clone_resize_status": "applied",
                "post_clone_resize_node": node_name,
                "post_clone_resize_vmid": vmid,
                "post_clone_resize_cpu_cores": target_cpu,
                "post_clone_resize_memory_gb": target_memory_gb,
            },
        )

    def _resolve_vm_identity(
        self,
        *,
        task_id: str,
        deploy_request: Optional[Dict[str, Any]],
        terraform_outputs: Dict[str, Any],
    ) -> tuple[str, Optional[int]]:
        task_status = task_manager.get_status(task_id) or {}
        metadata = task_status.get("metadata") or {}

        node_name = str(
            (deploy_request or {}).get("server_id")
            or metadata.get("vm_node")
            or metadata.get("proxmox_node")
            or ""
        ).strip()

        raw_vmid = terraform_outputs.get("vm_id")
        if isinstance(raw_vmid, dict):
            raw_vmid = raw_vmid.get("value", raw_vmid)
        if raw_vmid is None:
            raw_vmid = metadata.get("vm_id")
        if raw_vmid is None:
            raw_vmid = metadata.get("proxmox_vmid")

        try:
            vmid = int(raw_vmid) if raw_vmid is not None and str(raw_vmid).strip() else None
        except (TypeError, ValueError):
            vmid = None

        if vmid is None:
            vm_name = str(
                metadata.get("vm_name")
                or (deploy_request or {}).get("server_name")
                or ""
            ).strip()
            if node_name and vm_name:
                vmid = self.proxmox_service.find_vm_id_by_name(node_name, vm_name)

        return node_name, vmid

    def _wait_for_vm_status_snapshot(
        self,
        node_name: str,
        vmid: int,
        *,
        timeout_seconds: int = 60,
        poll_interval_seconds: float = 2.0,
    ) -> Optional[Dict[str, Any]]:
        deadline = time.monotonic() + max(1, int(timeout_seconds))
        poll_interval = max(0.5, float(poll_interval_seconds))

        while time.monotonic() <= deadline:
            status = self.proxmox_service.get_vm_status(node_name, vmid)
            if isinstance(status, dict) and status:
                return status
            time.sleep(poll_interval)
        return None

    def _ensure_vm_stopped_for_resize(
        self,
        task_id: str,
        node_name: str,
        vmid: int,
    ) -> None:
        status = self._wait_for_vm_status_snapshot(node_name, vmid)
        if status is None:
            raise RuntimeError(f"VM 상태 조회에 실패했습니다: {node_name}/{vmid}")

        current_state = str(status.get("status", "unknown")).strip().lower()
        if current_state == "stopped":
            task_manager.append_log(task_id, "VM이 이미 stopped 상태입니다.")
            return

        task_manager.append_log(task_id, "VM graceful shutdown 시도")
        shutdown_result = self.proxmox_service.perform_vm_action(
            node_name,
            vmid,
            action="shutdown",
            timeout_seconds=120,
        )
        if shutdown_result.get("success"):
            task_manager.append_log(task_id, "VM graceful shutdown 완료")
            return

        task_manager.append_log(
            task_id,
            "경고: graceful shutdown 실패 또는 타임아웃, force stop을 시도합니다.",
        )
        stop_result = self.proxmox_service.perform_vm_action(
            node_name,
            vmid,
            action="stop",
            timeout_seconds=60,
        )
        if not stop_result.get("success"):
            raise RuntimeError(stop_result.get("error") or "VM force stop에 실패했습니다.")

        task_manager.append_log(task_id, "VM force stop 완료")

    def _extract_vm_cpu_cores(self, status: Dict[str, Any]) -> Optional[int]:
        for key in ("cpus", "cores"):
            raw_value = status.get(key)
            try:
                if raw_value is not None:
                    return int(raw_value)
            except (TypeError, ValueError):
                continue
        return None

    def _extract_vm_memory_gb(self, status: Dict[str, Any]) -> Optional[float]:
        raw_bytes = status.get("maxmem")
        if raw_bytes is None:
            raw_bytes = status.get("memory")

        try:
            if raw_bytes is None:
                return None
            return round(float(raw_bytes) / 1024 / 1024 / 1024, 2)
        except (TypeError, ValueError):
            return None

    def _wait_for_ansible_ssh_readiness(
        self,
        task_id: str,
        vm_ip: str,
        *,
        timeout_seconds: int = 180,
        poll_interval_seconds: float = 5.0,
    ) -> None:
        host = str(vm_ip or "").strip()
        if not host:
            return

        timeout = max(5, int(timeout_seconds))
        poll_interval = max(1.0, float(poll_interval_seconds))
        deadline = time.monotonic() + timeout

        task_manager.append_log(
            task_id,
            f"Ansible 실행 전 SSH readiness 확인 중: {host}:22 (timeout={timeout}s)",
        )
        task_manager.update_metadata(
            task_id,
            {
                "ansible_readiness_host": host,
                "ansible_readiness_status": "waiting",
            },
        )

        while time.monotonic() <= deadline:
            try:
                with socket.create_connection((host, 22), timeout=min(5.0, poll_interval)):
                    task_manager.append_log(task_id, f"SSH readiness 확인 완료: {host}:22 연결 가능")
                    task_manager.update_metadata(
                        task_id,
                        {
                            "ansible_readiness_status": "ready",
                        },
                    )
                    return
            except OSError:
                time.sleep(poll_interval)

        task_manager.append_log(
            task_id,
            "경고: SSH readiness timeout이 발생했습니다. playbook의 cloud-init/재접속 로직에 맡기고 계속 진행합니다.",
        )
        task_manager.update_metadata(
            task_id,
            {
                "ansible_readiness_status": "timeout",
            },
        )

    def _read_ssh_public_key(self) -> Optional[str]:
        """
        SSH 공개키 파일 읽기

        환경변수 ANSIBLE_SSH_PUBLIC_KEY_FILE 또는 기본 경로에서 SSH 공개키를 읽습니다.
        """
        # 환경변수에서 경로 가져오기 (기본값: ~/.ssh/id_rsa.pub)
        ssh_public_key_path = os.getenv(
            "ANSIBLE_SSH_PUBLIC_KEY_FILE",
            os.path.expanduser("~/.ssh/id_rsa.pub")
        )
        ssh_public_key_path = os.path.expanduser(ssh_public_key_path)

        if not os.path.exists(ssh_public_key_path):
            # id_ed25519.pub도 시도
            alt_path = os.path.expanduser("~/.ssh/id_ed25519.pub")
            if os.path.exists(alt_path):
                ssh_public_key_path = alt_path
            else:
                return None

        try:
            with open(ssh_public_key_path, "r") as f:
                public_key = f.read().strip()
            return public_key
        except Exception:
            return None

    def _summarize_deploy_request(self, deploy_request: Dict[str, Any]) -> Dict[str, Any]:
        summary = {
            "server_name": deploy_request.get("server_name"),
            "server_id": deploy_request.get("server_id"),
            "template_id": deploy_request.get("template_id"),
            "storage_id": deploy_request.get("storage_id"),
            "network_ids": deploy_request.get("network_ids") or [],
            "cpu_cores": deploy_request.get("cpu_cores"),
            "memory_gb": deploy_request.get("memory_gb"),
            "vm_ip": deploy_request.get("vm_ip"),
            "vm_gateway": deploy_request.get("vm_gateway"),
            "ansible_packages": deploy_request.get("ansible_packages") or [],
            "ansible_roles": deploy_request.get("ansible_roles") or [],
            "gitlab_project_id": deploy_request.get("gitlab_project_id"),
            "path_with_namespace": deploy_request.get("path_with_namespace"),
            "deploy_branch": deploy_request.get("deploy_branch"),
            "staging_target_mode": deploy_request.get("staging_target_mode"),
            "target_host_ip": deploy_request.get("target_host_ip"),
            "target_host_name": deploy_request.get("target_host_name"),
            "app_deploy_enabled": bool(deploy_request.get("app_deploy_enabled")),
            "compose_file": deploy_request.get("compose_file"),
            "app_port": deploy_request.get("app_port"),
            "healthcheck_type": deploy_request.get("healthcheck_type"),
            "healthcheck_path": deploy_request.get("healthcheck_path"),
            "healthcheck_port": deploy_request.get("healthcheck_port"),
            "healthcheck_command": deploy_request.get("healthcheck_command"),
        }
        return {key: value for key, value in summary.items() if value not in (None, "", [])}

    def _prepare_app_deploy_extra_vars(
        self,
        *,
        task_id: str,
        deploy_request: Dict[str, Any],
    ) -> tuple[dict[str, object], Optional[str]]:
        if not deploy_request.get("app_deploy_enabled"):
            return {}, None

        compose_file = str(deploy_request.get("compose_file") or "").strip()
        project_slug = str(deploy_request.get("app_project_slug") or "").strip()
        source_ref = str(deploy_request.get("deploy_branch") or "").strip()
        project_id = deploy_request.get("gitlab_project_id")
        healthcheck_type = str(deploy_request.get("healthcheck_type") or "").strip().lower()
        healthcheck_path = str(deploy_request.get("healthcheck_path") or "").strip()
        healthcheck_command = str(deploy_request.get("healthcheck_command") or "").strip()
        healthcheck_port = deploy_request.get("healthcheck_port")
        app_port = deploy_request.get("app_port")

        if not compose_file or not project_slug or not source_ref or project_id is None:
            raise RuntimeError("앱 배포에 필요한 GitLab source metadata가 부족합니다.")
        if isinstance(app_port, bool) or not isinstance(app_port, int) or app_port <= 0:
            raise RuntimeError("앱 배포에 필요한 app_port가 올바르지 않습니다.")
        if healthcheck_type not in {"http", "tcp", "command", "none"}:
            raise RuntimeError("앱 배포에 필요한 healthcheck_type이 올바르지 않습니다.")
        if healthcheck_type == "http" and not healthcheck_path.startswith("/"):
            raise RuntimeError("앱 배포에 필요한 healthcheck_path가 올바르지 않습니다.")
        if healthcheck_type in {"http", "tcp"}:
            if isinstance(healthcheck_port, bool) or not isinstance(healthcheck_port, int) or healthcheck_port <= 0:
                raise RuntimeError("앱 배포에 필요한 healthcheck_port가 올바르지 않습니다.")
        if healthcheck_type == "command" and not healthcheck_command:
            raise RuntimeError("앱 배포에 필요한 healthcheck_command가 올바르지 않습니다.")

        task_manager.append_log(task_id, "GitLab source archive 다운로드 준비 중...")
        task_manager.update_progress(
            task_id,
            90.0,
            text="GitLab source archive download",
            source="phase",
        )
        archive_path = self._download_gitlab_source_archive(
            task_id=task_id,
            gitlab_project_id=project_id,
            source_ref=source_ref,
        )

        extra_vars: dict[str, object] = {
            "deploy_app_enabled": True,
            "deploy_bundle_local_path": archive_path,
            "deploy_project_slug": project_slug,
            "deploy_release_id": task_id[:12],
            "deploy_source_ref": source_ref,
            "deploy_compose_file": compose_file,
            "deploy_app_port": app_port,
            "deploy_healthcheck_type": healthcheck_type,
            "deploy_healthcheck_path": healthcheck_path,
            "deploy_healthcheck_port": healthcheck_port,
            "deploy_healthcheck_command": healthcheck_command,
        }
        task_manager.append_log(
            task_id,
            f"앱 배포 소스 준비 완료: {project_slug} @ {source_ref}",
        )
        return extra_vars, archive_path

    def _download_gitlab_source_archive(
        self,
        *,
        task_id: str,
        gitlab_project_id: Any,
        source_ref: str,
    ) -> str:
        settings = get_gitlab_settings()
        if not settings.can_sync:
            raise RuntimeError("GitLab source archive download requires configured GitLab settings.")

        try:
            normalized_project_id = int(gitlab_project_id)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("gitlab_project_id must be an integer for app deploy.") from exc

        session = requests.Session()
        session.headers.update({"PRIVATE-TOKEN": settings.api_token})
        url = urljoin(
            f"{settings.base_url}/",
            f"api/v4/projects/{normalized_project_id}/repository/archive.tar.gz",
        )
        max_archive_bytes = self._read_int_env(
            "GITLAB_APP_ARCHIVE_MAX_BYTES",
            default=200 * 1024 * 1024,
        )
        fd, archive_path = tempfile.mkstemp(
            prefix=f"heimdall-app-{normalized_project_id}-",
            suffix=".tar.gz",
        )
        os.close(fd)

        try:
            with session.get(
                url,
                params={"sha": source_ref},
                stream=True,
                timeout=(5, 120),
                verify=settings.verify_ssl,
            ) as response:
                response.raise_for_status()
                written_bytes = 0
                with open(archive_path, "wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            written_bytes += len(chunk)
                            if max_archive_bytes > 0 and written_bytes > max_archive_bytes:
                                raise RuntimeError(
                                    "GitLab source archive exceeded the configured size limit "
                                    f"({max_archive_bytes} bytes)."
                                )
                            handle.write(chunk)
        except requests.RequestException as exc:
            self._cleanup_local_app_bundle(task_id, archive_path)
            raise RuntimeError(
                f"GitLab source archive download failed for ref {source_ref}: {exc}"
            ) from exc
        except RuntimeError:
            self._cleanup_local_app_bundle(task_id, archive_path)
            raise
        finally:
            session.close()

        task_manager.update_metadata(
            task_id,
            {
                "app_source_archive_status": "downloaded",
                "app_source_ref": source_ref,
            },
        )
        return archive_path

    def _cleanup_local_app_bundle(self, task_id: str, archive_path: Optional[str]) -> None:
        if not archive_path:
            return
        try:
            if os.path.exists(archive_path):
                os.remove(archive_path)
                task_manager.append_log(task_id, "임시 GitLab source archive 정리 완료")
        except OSError as exc:
            task_manager.append_log(task_id, f"경고: 임시 source archive 정리 실패: {exc}")

    def _summarize_terraform_vars(self, terraform_vars: Dict[str, Any]) -> Dict[str, Any]:
        summary = {
            "vm_name": terraform_vars.get("vm_name"),
            "target_node": terraform_vars.get("target_node"),
            "template_id": terraform_vars.get("template_id"),
            "disk_size_gb": terraform_vars.get("disk_size_gb"),
            "storage_id": terraform_vars.get("storage_id"),
            "network_ids": terraform_vars.get("network_ids") or [],
            "vm_ip": terraform_vars.get("vm_ip"),
            "vm_gateway": terraform_vars.get("vm_gateway"),
            "ssh_public_key_present": bool(terraform_vars.get("ssh_public_key")),
            "ssh_user": terraform_vars.get("ssh_user"),
        }
        return {key: value for key, value in summary.items() if value not in (None, "", [])}

    def _summarize_terraform_outputs(self, terraform_outputs: Dict[str, Any]) -> Dict[str, Any]:
        summary: Dict[str, Any] = {
            "keys": sorted(str(key) for key in terraform_outputs.keys()),
        }
        for key in ("vm_id", "vm_name", "vm_ip", "instance_ip", "ip_address"):
            value = terraform_outputs.get(key)
            if isinstance(value, dict):
                value = value.get("value", value)
            if value not in (None, ""):
                summary[key] = value
        return summary

    def _read_int_env(self, name: str, default: int) -> int:
        raw_value = str(os.getenv(name, default)).strip()
        try:
            return int(raw_value)
        except (TypeError, ValueError):
            return int(default)


__all__ = ["DeploymentService"]
