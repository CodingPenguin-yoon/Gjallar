"""
Terraform 실행 서비스 패키지

이 패키지는 Terraform 명령어를 OS 레벨에서 실행하고 결과를 관리합니다.
기존 단일 모듈이었던 `terraform_service.py`의 구현을 패키지 구조로 옮겼습니다.
"""

import subprocess
import os
import re
import threading
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from dotenv import load_dotenv
from app.shared.tasks import task_manager
from app.domains.proxmox.service import ProxmoxService

# .env 파일 로드
# 패키지로 이동하면서 경로 깊이가 1단계 늘어났기 때문에
# 항상 프로젝트 루트(backend 기준 한 단계 위)의 .env 를 바라보도록 조정한다.
project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)
    print(f"[TerraformService] .env 파일 로드됨: {env_path}")


class TerraformService:
    """
    Terraform 명령어 실행을 담당하는 서비스 클래스
    
    /infra/terraform 디렉토리 내의 Terraform 파일들을 대상으로
    terraform init, plan, apply 등의 명령어를 실행합니다.
    """
    
    def __init__(self, terraform_dir: Optional[str] = None):
        """
        초기화
        
        Args:
            terraform_dir: Terraform 작업 디렉토리 경로 (기본값: 프로젝트 루트/infra/terraform)
        """
        if terraform_dir:
            self.terraform_dir = Path(terraform_dir)
        else:
            # 프로젝트 루트 기준 infra/terraform 경로 설정
            # __file__ = backend/app/integrations/terraform/__init__.py
            # parents[4] = repo root
            repo_root = Path(__file__).resolve().parents[4]
            self.terraform_dir = repo_root / "infra" / "terraform"
        
        # 디렉토리 존재 여부 확인
        if not self.terraform_dir.exists():
            self.terraform_dir.mkdir(parents=True, exist_ok=True)

        # ------------------------------------------------------------------
        # Proxmox 관련 환경변수를 Terraform 변수(TF_VAR_*)로 연결
        # .env 에서는 PROXMOX_* 이름을 쓰고, Terraform은 TF_VAR_proxmox_* 를 기대하므로
        # 여기서 한 번만 매핑해 두면 이후 subprocess 에서 그대로 사용 가능하다.
        # ------------------------------------------------------------------
        proxmox_api_url = os.getenv("PROXMOX_API_URL")
        if proxmox_api_url and not os.getenv("TF_VAR_proxmox_api_url"):
            os.environ["TF_VAR_proxmox_api_url"] = proxmox_api_url

        proxmox_token_id = os.getenv("PROXMOX_API_TOKEN_ID")
        if proxmox_token_id and not os.getenv("TF_VAR_proxmox_api_token_id"):
            os.environ["TF_VAR_proxmox_api_token_id"] = proxmox_token_id

        proxmox_token_secret = os.getenv("PROXMOX_API_TOKEN_SECRET")
        if proxmox_token_secret and not os.getenv("TF_VAR_proxmox_api_token_secret"):
            os.environ["TF_VAR_proxmox_api_token_secret"] = proxmox_token_secret

        proxmox_tls_insecure = os.getenv("PROXMOX_TLS_INSECURE")
        if proxmox_tls_insecure is not None and not os.getenv("TF_VAR_proxmox_tls_insecure"):
            # 문자열(true/false)를 Terraform 이 이해할 수 있는 bool 값으로 넘긴다.
            value = str(proxmox_tls_insecure).strip().lower() in ["1", "true", "yes", "on"]
            os.environ["TF_VAR_proxmox_tls_insecure"] = "true" if value else "false"

        # 디버깅: 환경변수 확인
        print(f"[TerraformService] TF_VAR_proxmox_api_url: {os.getenv('TF_VAR_proxmox_api_url', 'NOT SET')}")
        print(f"[TerraformService] TF_VAR_proxmox_api_token_id: {os.getenv('TF_VAR_proxmox_api_token_id', 'NOT SET')}")
        print(f"[TerraformService] TF_VAR_proxmox_api_token_secret: {'SET' if os.getenv('TF_VAR_proxmox_api_token_secret') else 'NOT SET'}")

        self.proxmox_service = ProxmoxService()
        self._percent_pattern = re.compile(r"\((\d+(?:[.,]\d+)?)%\)")
        self._upid_pattern = re.compile(r"(UPID:[^\s'\",]+)")

    def _append_task_log(self, task_id: Optional[str], message: str) -> None:
        if task_id:
            task_manager.append_log(task_id, message)

    def _sanitize_workspace_name(self, value: str) -> str:
        """
        Terraform workspace 이름을 안전한 문자로 정규화
        """
        sanitized = re.sub(r"[^0-9A-Za-z_-]+", "-", str(value).strip())
        sanitized = re.sub(r"-{2,}", "-", sanitized).strip("-")
        if not sanitized:
            return "default"
        return sanitized[:90]

    def select_or_create_workspace(self, task_id: str, workspace: str) -> tuple[bool, str]:
        """
        Terraform workspace 선택(없으면 생성)
        """
        workspace_name = self._sanitize_workspace_name(workspace)
        env = os.environ.copy()

        try:
            task_manager.append_log(task_id, f"Terraform workspace 선택: {workspace_name}")

            select_result = subprocess.run(
                ["terraform", "workspace", "select", workspace_name],
                cwd=str(self.terraform_dir),
                capture_output=True,
                text=True,
                env=env,
            )

            if select_result.returncode == 0:
                task_manager.append_log(task_id, f"Workspace 활성화됨: {workspace_name}")
                task_manager.update_metadata(task_id, {"terraform_workspace": workspace_name})
                return True, workspace_name

            task_manager.append_log(
                task_id,
                f"Workspace 미존재, 생성 시도: {workspace_name}",
            )
            new_result = subprocess.run(
                ["terraform", "workspace", "new", workspace_name],
                cwd=str(self.terraform_dir),
                capture_output=True,
                text=True,
                env=env,
            )
            if new_result.returncode != 0:
                error_msg = new_result.stderr.strip() or "workspace 생성 실패"
                task_manager.append_log(task_id, f"ERROR: {error_msg}")
                return False, error_msg

            task_manager.append_log(task_id, f"Workspace 생성 및 활성화 완료: {workspace_name}")
            task_manager.update_metadata(task_id, {"terraform_workspace": workspace_name})
            return True, workspace_name
        except Exception as e:
            error_msg = f"workspace 설정 중 예외: {str(e)}"
            task_manager.append_log(task_id, f"EXCEPTION: {error_msg}")
            return False, error_msg

    def migrate_legacy_local_state(
        self,
        workspace: str,
        task_id: Optional[str] = None,
        legacy_terraform_dir: Optional[str] = None,
        force: bool = False,
    ) -> tuple[bool, str]:
        """
        구 경로(backend/iac/terraform)의 local state를 현재 workspace로 이관

        Args:
            workspace: 대상 Terraform workspace
            task_id: task 로그 연동용 식별자(선택)
            legacy_terraform_dir: legacy terraform 디렉토리(선택)
            force: 대상 workspace에 state가 있어도 강제 push 허용
        """
        workspace_name = self._sanitize_workspace_name(workspace)
        repo_root = Path(__file__).resolve().parents[4]
        legacy_dir = (
            Path(legacy_terraform_dir)
            if legacy_terraform_dir
            else repo_root / "backend" / "iac" / "terraform"
        )
        legacy_state_file = legacy_dir / "terraform.tfstate"
        env = os.environ.copy()

        if not legacy_state_file.exists():
            return True, f"legacy state 없음: {legacy_state_file}"

        try:
            with legacy_state_file.open("r", encoding="utf-8") as file:
                legacy_payload = json.load(file)
        except Exception as e:
            return False, f"legacy state 파싱 실패: {str(e)}"

        legacy_resources = []
        if isinstance(legacy_payload, dict):
            resources = legacy_payload.get("resources", [])
            if isinstance(resources, list):
                legacy_resources = resources

        if not legacy_resources:
            return True, "legacy state가 비어 있어 이관할 리소스가 없습니다."

        self._append_task_log(task_id, f"Legacy state 이관 시작: {legacy_state_file} -> workspace={workspace_name}")

        try:
            init_result = subprocess.run(
                ["terraform", "init", "-input=false"],
                cwd=str(self.terraform_dir),
                capture_output=True,
                text=True,
                env=env,
            )
            if init_result.returncode != 0:
                return False, init_result.stderr.strip() or "terraform init 실패"

            select_result = subprocess.run(
                ["terraform", "workspace", "select", workspace_name],
                cwd=str(self.terraform_dir),
                capture_output=True,
                text=True,
                env=env,
            )
            if select_result.returncode != 0:
                new_result = subprocess.run(
                    ["terraform", "workspace", "new", workspace_name],
                    cwd=str(self.terraform_dir),
                    capture_output=True,
                    text=True,
                    env=env,
                )
                if new_result.returncode != 0:
                    return False, new_result.stderr.strip() or "workspace 생성 실패"

            current_pull = subprocess.run(
                ["terraform", "state", "pull"],
                cwd=str(self.terraform_dir),
                capture_output=True,
                text=True,
                env=env,
            )

            current_resources = []
            current_state_raw = current_pull.stdout.strip() if current_pull.returncode == 0 else ""
            if current_state_raw:
                try:
                    current_payload = json.loads(current_state_raw)
                    resources = current_payload.get("resources", []) if isinstance(current_payload, dict) else []
                    if isinstance(resources, list):
                        current_resources = resources
                except Exception:
                    current_resources = []

            if current_resources and not force:
                return True, (
                    f"workspace '{workspace_name}'에 기존 state가 있어 자동 이관을 건너뜁니다. "
                    "force=true로 재시도할 수 있습니다."
                )

            if current_state_raw:
                backup_dir = self.terraform_dir / ".state-migration-backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                backup_file = backup_dir / f"{workspace_name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.tfstate.json"
                backup_file.write_text(current_state_raw, encoding="utf-8")
                self._append_task_log(task_id, f"현재 workspace state 백업 완료: {backup_file}")

            push_command = ["terraform", "state", "push"]
            if force:
                push_command.append("-force")
            push_command.append(str(legacy_state_file))
            push_result = subprocess.run(
                push_command,
                cwd=str(self.terraform_dir),
                capture_output=True,
                text=True,
                env=env,
            )
            if push_result.returncode != 0:
                return False, push_result.stderr.strip() or "terraform state push 실패"

            verify_pull = subprocess.run(
                ["terraform", "state", "pull"],
                cwd=str(self.terraform_dir),
                capture_output=True,
                text=True,
                env=env,
            )
            if verify_pull.returncode != 0:
                return False, "이관 후 state 검증 실패(state pull 오류)"

            migrated_count = len(legacy_resources)
            self._append_task_log(task_id, f"Legacy state 이관 완료: resource {migrated_count}개")
            if task_id:
                task_manager.update_metadata(
                    task_id,
                    {
                        "legacy_state_migrated": True,
                        "legacy_state_source": str(legacy_state_file),
                        "legacy_state_workspace": workspace_name,
                        "legacy_state_resource_count": migrated_count,
                    },
                )
            return True, f"legacy state 이관 완료 (resource {migrated_count}개)"
        except Exception as e:
            return False, f"legacy state 이관 예외: {str(e)}"

    def _extract_progress_from_line(self, line: str) -> Optional[float]:
        """
        로그 라인에서 퍼센트 진행률 추출

        Args:
            line: 로그 라인

        Returns:
            진행률(0~100) 또는 None
        """
        match = self._percent_pattern.search(line)
        if not match:
            return None
        try:
            progress = float(str(match.group(1)).replace(",", "."))
            if 0 <= progress <= 100:
                return progress
        except (TypeError, ValueError):
            return None
        return None

    def _extract_upid_from_line(self, line: str) -> Optional[str]:
        """
        로그 라인에서 Proxmox UPID 추출
        """
        match = self._upid_pattern.search(line)
        if not match:
            return None
        return match.group(1)

    def _extract_node_from_upid(self, upid: str) -> Optional[str]:
        """
        UPID에서 노드명 추출 (UPID:node:...)
        """
        parts = upid.split(":")
        if len(parts) >= 2 and parts[0] == "UPID":
            return parts[1]
        return None

    def _parse_template_hint(self, template_id: object) -> tuple[Optional[str], Optional[int]]:
        """
        template_id에서 clone source node / template VMID 추출

        지원 형식:
        - "node/vmid"
        - "vmid"
        """
        raw = str(template_id or "").strip()
        if not raw:
            return None, None

        parts = [part.strip() for part in raw.split("/", 1)]
        source_node: Optional[str] = None
        raw_vmid = parts[0]
        if len(parts) == 2:
            source_node = parts[0] or None
            raw_vmid = parts[1]

        try:
            template_vmid = int(raw_vmid)
        except (TypeError, ValueError):
            template_vmid = None

        return source_node, template_vmid

    def _extract_task_log_line(self, entry: Any) -> str:
        """
        Proxmox task log entry에서 실제 메시지 텍스트 추출
        """
        if isinstance(entry, dict):
            for key in ("t", "msg", "message"):
                if key in entry and entry.get(key) is not None:
                    return str(entry.get(key))
            return ""
        return str(entry or "")

    def _is_candidate_proxmox_task(
        self,
        task: dict,
        min_start_time: int,
        *,
        expected_task_id: Optional[int] = None,
    ) -> bool:
        if not isinstance(task, dict):
            return False

        upid = str(task.get("upid", "")).strip()
        if not upid.startswith("UPID:"):
            return False

        task_type = str(task.get("type", "")).lower()
        # clone/move/create 류 작업만 진행률 연동 대상으로 사용
        if not any(token in task_type for token in ("clone", "move", "create")):
            return False

        try:
            start_time = int(task.get("starttime", 0) or 0)
        except (TypeError, ValueError):
            start_time = 0
        if start_time > 0 and min_start_time > 0 and start_time < min_start_time:
            return False

        if expected_task_id is not None:
            raw_task_id = str(task.get("id", "")).strip()
            if raw_task_id.startswith("qemu/"):
                raw_task_id = raw_task_id.split("/", 1)[1]
            try:
                task_id_value = int(raw_task_id)
            except (TypeError, ValueError):
                return False
            if task_id_value != expected_task_id:
                return False

        return True

    def _pick_recent_proxmox_task(
        self,
        tasks: list[dict],
        min_start_time: int,
        *,
        expected_task_id: Optional[int] = None,
    ) -> Optional[dict]:
        candidates: list[dict] = []
        for task in tasks:
            if not self._is_candidate_proxmox_task(
                task,
                min_start_time,
                expected_task_id=expected_task_id,
            ):
                continue
            candidates.append(task)

        if not candidates:
            return None

        # running 상태를 우선, 그 다음 최신 starttime 우선
        def sort_key(item: dict) -> tuple[int, int]:
            status = str(item.get("status", "")).lower()
            running_score = 1 if status == "running" else 0
            try:
                start_time = int(item.get("starttime", 0) or 0)
            except (TypeError, ValueError):
                start_time = 0
            return running_score, start_time

        candidates.sort(key=sort_key, reverse=True)
        return candidates[0]

    def _discover_proxmox_task(
        self,
        *,
        node_hints: list[str],
        vm_name_hint: str,
        started_at_epoch: float,
        template_source_node: Optional[str] = None,
        template_vmid_hint: Optional[int] = None,
    ) -> Optional[dict]:
        candidate_nodes: list[str] = []
        for node_hint in node_hints:
            node_name = str(node_hint or "").strip()
            if node_name and node_name not in candidate_nodes:
                candidate_nodes.append(node_name)

        if not candidate_nodes:
            return None

        vm_name = str(vm_name_hint or "").strip()
        min_start_time = max(int(started_at_epoch) - 180, 0)
        template_source_node = str(template_source_node or "").strip() or None

        for node_name in candidate_nodes:
            vmid = self.proxmox_service.find_vm_id_by_name(node_name, vm_name) if vm_name else None
            if vmid is not None:
                vm_tasks = self.proxmox_service.get_node_tasks(
                    node=node_name,
                    vmid=vmid,
                    limit=80,
                    source="all",
                )
                picked = self._pick_recent_proxmox_task(vm_tasks, min_start_time)
                if picked:
                    return {
                        "node": node_name,
                        "upid": str(picked.get("upid", "")),
                        "vmid": vmid,
                    }

            expected_task_id = (
                template_vmid_hint
                if template_vmid_hint is not None and node_name == template_source_node
                else None
            )
            node_tasks = self.proxmox_service.get_node_tasks(
                node=node_name,
                limit=120,
                source="all",
            )
            picked = self._pick_recent_proxmox_task(
                node_tasks,
                min_start_time,
                expected_task_id=expected_task_id,
            )
            if picked:
                picked_upid = str(picked.get("upid", "")).strip()
                if not picked_upid.startswith("UPID:"):
                    continue

                picked_vmid = vmid
                task_id = str(picked.get("id", "")).strip()
                if picked_vmid is None and task_id.startswith("qemu/"):
                    raw_vmid = task_id.split("/", 1)[1]
                    try:
                        picked_vmid = int(raw_vmid)
                    except (TypeError, ValueError):
                        picked_vmid = None

                return {
                    "node": node_name,
                    "upid": str(picked.get("upid", "")),
                    "vmid": picked_vmid,
                }

        return None

    def _start_proxmox_task_polling(
        self,
        *,
        task_id: str,
        node: str,
        upid: str,
        vmid: Optional[int],
        stop_event: threading.Event,
    ) -> threading.Thread:
        metadata: dict[str, Any] = {
            "proxmox_node": node,
            "proxmox_upid": upid,
        }
        if vmid is not None:
            metadata["proxmox_vmid"] = vmid

        task_manager.update_metadata(task_id, metadata)
        task_manager.append_log(
            task_id,
            f"Proxmox task 연동 시작: node={node}, upid={upid}" + (f", vmid={vmid}" if vmid is not None else ""),
        )

        poll_thread = threading.Thread(
            target=self._poll_proxmox_task_progress,
            args=(task_id, node, upid, stop_event),
            daemon=True,
        )
        poll_thread.start()
        return poll_thread

    def _poll_proxmox_task_progress(
        self,
        task_id: str,
        node: str,
        upid: str,
        stop_event: threading.Event,
    ) -> None:
        """
        Proxmox task 로그를 폴링해서 진행률 갱신
        """
        last_line_number = -1

        while not stop_event.is_set():
            try:
                log_start = max(last_line_number + 1, 0)
                entries = self.proxmox_service.get_task_log(node=node, upid=upid, start=log_start)

                for entry in entries:
                    line_number = None
                    if isinstance(entry, dict) and entry.get("n") is not None:
                        try:
                            line_number = int(entry.get("n"))
                        except (TypeError, ValueError):
                            line_number = None

                    if line_number is not None and line_number <= last_line_number:
                        continue

                    log_line = self._extract_task_log_line(entry).strip()
                    if not log_line:
                        if line_number is not None:
                            last_line_number = max(last_line_number, line_number)
                        continue

                    task_manager.append_log(task_id, f"[Proxmox Task] {log_line}")

                    progress = self._extract_progress_from_line(log_line)
                    if progress is not None:
                        task_manager.update_progress(
                            task_id,
                            progress,
                            text=log_line,
                            source="proxmox_task_log",
                        )

                    if line_number is not None:
                        last_line_number = max(last_line_number, line_number)
                    else:
                        last_line_number += 1

                task_status = self.proxmox_service.get_task_status(node=node, upid=upid) or {}
                status_text = str(task_status.get("status", "")).lower()
                exit_status = str(task_status.get("exitstatus", ""))
                if status_text == "stopped":
                    if exit_status.upper() == "OK":
                        task_manager.update_progress(
                            task_id,
                            100.0,
                            text="Proxmox task completed",
                            source="proxmox_task_log",
                        )
                    elif exit_status:
                        task_manager.append_log(
                            task_id,
                            f"[Proxmox Task] 종료 상태: {exit_status}",
                        )
                    return
            except Exception:
                # 진행률 보조 스레드는 실패해도 메인 Terraform 실행에 영향 주지 않음
                pass

            stop_event.wait(1.0)
    
    def _run_command(
        self,
        command: list,
        task_id: str,
        cwd: Optional[Path] = None,
        proxmox_hint: Optional[dict] = None,
    ) -> tuple[bool, str]:
        """
        Terraform 명령어 실행 (내부 메서드)
        
        Args:
            command: 실행할 명령어 리스트 (예: ['terraform', 'init'])
            task_id: 작업 식별자 (로그 및 상태 추적용)
            cwd: 작업 디렉토리 (기본값: self.terraform_dir)
            
        Returns:
            (성공 여부, 에러 메시지) 튜플
        """
        if cwd is None:
            cwd = self.terraform_dir

        proxmox_stop_event = threading.Event()
        proxmox_poll_thread: Optional[threading.Thread] = None
        discovered_upid: Optional[str] = None
        discovered_node: Optional[str] = None
        discovered_vmid: Optional[int] = None
        command_started_at = time.time()
        hint_node = str((proxmox_hint or {}).get("target_node", "")).strip()
        hint_vm_name = str((proxmox_hint or {}).get("vm_name", "")).strip()
        hint_template_source_node = str((proxmox_hint or {}).get("template_source_node", "")).strip()
        raw_template_vmid = (proxmox_hint or {}).get("template_vmid")
        try:
            hint_template_vmid = int(raw_template_vmid) if raw_template_vmid is not None else None
        except (TypeError, ValueError):
            hint_template_vmid = None
        discovery_nodes: list[str] = []
        for node_name in (hint_node, hint_template_source_node):
            if node_name and node_name not in discovery_nodes:
                discovery_nodes.append(node_name)
        last_discovery_attempt = 0.0
        
        try:
            task_manager.append_log(task_id, f"실행 명령어: {' '.join(command)}")
            task_manager.append_log(task_id, f"작업 디렉토리: {cwd}")
            
            # 현재 환경변수를 상속받아 subprocess 실행
            # Terraform은 TF_VAR_ 접두사를 가진 환경변수를 자동으로 읽습니다
            env = os.environ.copy()
            
            # subprocess로 명령어 실행 (실시간 로그 스트리밍)
            process = subprocess.Popen(
                command,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                env=env
            )
            
            # 실시간 로그 수집
            for line in iter(process.stdout.readline, ''):
                if line:
                    stripped_line = line.strip()
                    task_manager.append_log(task_id, stripped_line)

                    # 1안: Terraform 실시간 로그에 포함된 % 파싱
                    progress_from_tf = self._extract_progress_from_line(stripped_line)
                    if progress_from_tf is not None:
                        task_manager.update_progress(
                            task_id,
                            progress_from_tf,
                            text=stripped_line,
                            source="terraform_log",
                        )

                    # 2안 보강: UPID를 찾으면 Proxmox task log/status 폴링 시작
                    if proxmox_poll_thread is None:
                        upid = self._extract_upid_from_line(stripped_line)
                        if upid:
                            node = self._extract_node_from_upid(upid)
                            if not node and discovery_nodes:
                                node = discovery_nodes[0]
                            if node:
                                discovered_upid = upid
                                discovered_node = node
                                proxmox_poll_thread = self._start_proxmox_task_polling(
                                    task_id=task_id,
                                    node=node,
                                    upid=upid,
                                    vmid=discovered_vmid,
                                    stop_event=proxmox_stop_event,
                                )
                                continue

                        lowered = stripped_line.lower()
                        can_try_discovery = (
                            discovery_nodes
                            and (
                                "still creating" in lowered
                                or "proxmox_virtual_environment_vm.instance" in lowered
                            )
                        )
                        if can_try_discovery:
                            now_mono = time.monotonic()
                            if now_mono - last_discovery_attempt >= 3.0:
                                last_discovery_attempt = now_mono
                                discovered = self._discover_proxmox_task(
                                    node_hints=discovery_nodes,
                                    vm_name_hint=hint_vm_name,
                                    started_at_epoch=command_started_at,
                                    template_source_node=hint_template_source_node or None,
                                    template_vmid_hint=hint_template_vmid,
                                )
                                if discovered:
                                    discovered_node = str(discovered.get("node", "")).strip() or (
                                        discovery_nodes[0] if discovery_nodes else ""
                                    )
                                    discovered_upid = str(discovered.get("upid", "")).strip()
                                    raw_vmid = discovered.get("vmid")
                                    try:
                                        discovered_vmid = int(raw_vmid) if raw_vmid is not None else None
                                    except (TypeError, ValueError):
                                        discovered_vmid = None

                                    if discovered_node and discovered_upid.startswith("UPID:"):
                                        proxmox_poll_thread = self._start_proxmox_task_polling(
                                            task_id=task_id,
                                            node=discovered_node,
                                            upid=discovered_upid,
                                            vmid=discovered_vmid,
                                            stop_event=proxmox_stop_event,
                                        )
            
            process.wait()
            
            if process.returncode == 0:
                return True, ""
            else:
                error_msg = f"명령어 실행 실패 (종료 코드: {process.returncode})"
                task_manager.append_log(task_id, f"ERROR: {error_msg}")
                return False, error_msg
                
        except Exception as e:
            error_msg = f"명령어 실행 중 예외 발생: {str(e)}"
            task_manager.append_log(task_id, f"EXCEPTION: {error_msg}")
            return False, error_msg
        finally:
            proxmox_stop_event.set()
            if proxmox_poll_thread is not None:
                proxmox_poll_thread.join(timeout=1.5)

            final_metadata: dict[str, Any] = {}
            if discovered_node:
                final_metadata["proxmox_node"] = discovered_node
            if discovered_upid:
                final_metadata["proxmox_upid_final"] = discovered_upid
            if discovered_vmid is not None:
                final_metadata["proxmox_vmid"] = discovered_vmid
            if final_metadata:
                task_manager.update_metadata(task_id, final_metadata)
    
    def init(self, task_id: str) -> tuple[bool, str]:
        """
        terraform init 실행

        Args:
            task_id: 작업 식별자

        Returns:
            (성공 여부, 에러 메시지) 튜플
        """
        task_manager.append_log(task_id, "=== Terraform Init 시작 ===")
        return self._run_command(["terraform", "init"], task_id)
    
    def plan(self, task_id: str, workspace: Optional[str] = None) -> tuple[bool, str]:
        """
        terraform plan 실행
        
        Args:
            task_id: 작업 식별자
            
        Returns:
            (성공 여부, 에러 메시지) 튜플
        """
        if workspace:
            ok, message = self.select_or_create_workspace(task_id, workspace)
            if not ok:
                return False, message

        task_manager.append_log(task_id, "=== Terraform Plan 시작 ===")
        return self._run_command(["terraform", "plan", "-input=false"], task_id)
    
    def apply(
        self, 
        task_id: str, 
        auto_approve: bool = True,
        variables: Optional[dict] = None,
        workspace: Optional[str] = None
    ) -> tuple[bool, str]:
        """
        terraform apply 실행
        
        Args:
            task_id: 작업 식별자
            auto_approve: 자동 승인 여부 (기본값: True)
            variables: Terraform 변수 딕셔너리 (예: {"vm_name": "test-vm", "cpu_cores": 2})
            
        Returns:
            (성공 여부, 에러 메시지) 튜플
        """
        if workspace:
            ok, message = self.select_or_create_workspace(task_id, workspace)
            if not ok:
                return False, message

        task_manager.append_log(task_id, "=== Terraform Apply 시작 ===")
        command = ["terraform", "apply", "-input=false"]
        if auto_approve:
            command.append("-auto-approve")
        
        # 변수 추가 (-var 옵션)
        if variables:
            for key, value in variables.items():
                if value is not None:
                    # 리스트는 JSON 문자열로 변환
                    if isinstance(value, list):
                        import json
                        command.extend(["-var", f"{key}={json.dumps(value)}"])
                    else:
                        command.extend(["-var", f"{key}={value}"])

        template_source_node, template_vmid = self._parse_template_hint(
            (variables or {}).get("template_id"),
        )
        proxmox_hint = {
            "target_node": (variables or {}).get("target_node"),
            "template_source_node": template_source_node,
            "template_vmid": template_vmid,
            "vm_name": (variables or {}).get("vm_name"),
        }

        return self._run_command(
            command,
            task_id,
            proxmox_hint=proxmox_hint,
        )
    
    def get_output(self, output_name: str = None, workspace: Optional[str] = None) -> dict:
        """
        Terraform output 값 조회
        
        Args:
            output_name: 조회할 output 이름 (None이면 모든 output 반환)
            
        Returns:
            output 값 딕셔너리
        """
        try:
            import json
            if workspace:
                # output 조회 전 워크스페이스 고정
                workspace_name = self._sanitize_workspace_name(workspace)
                subprocess.run(
                    ["terraform", "workspace", "select", workspace_name],
                    cwd=str(self.terraform_dir),
                    capture_output=True,
                    text=True,
                    env=os.environ.copy(),
                )
            command = ["terraform", "output", "-json"]
            if output_name:
                command.append(output_name)
            
            result = subprocess.run(
                command,
                cwd=str(self.terraform_dir),
                capture_output=True,
                text=True,
                env=os.environ.copy()
            )
            
            if result.returncode == 0:
                outputs = json.loads(result.stdout)
                # Terraform output -json 형식 변환
                if output_name:
                    # 단일 output인 경우
                    if isinstance(outputs, dict) and "value" in outputs:
                        return {output_name: outputs["value"]}
                    return {output_name: outputs}
                else:
                    # 모든 output인 경우
                    parsed = {}
                    for key, value in outputs.items():
                        if isinstance(value, dict) and "value" in value:
                            parsed[key] = value["value"]
                        else:
                            parsed[key] = value
                    return parsed
            else:
                return {}
        except Exception as e:
            return {}
