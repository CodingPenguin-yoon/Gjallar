"""
Ansible 실행 서비스 패키지

이 패키지는 Ansible Playbook을 OS 레벨에서 실행하고 결과를 관리합니다.
기존 단일 모듈이었던 `ansible_service.py`의 구현을 패키지 구조로 옮겼습니다.
"""

import subprocess
import os
import uuid
import yaml
from pathlib import Path
from typing import Optional, Dict, List
from app.shared.tasks import task_manager


class AnsibleService:
    """
    Ansible Playbook 실행을 담당하는 서비스 클래스
    
    /infra/ansible 디렉토리 내의 playbook.yml 파일을 대상으로
    ansible-playbook 명령어를 실행합니다.
    """
    
    def __init__(self, ansible_dir: Optional[str] = None):
        """
        초기화
        
        Args:
            ansible_dir: Ansible 작업 디렉토리 경로 (기본값: 프로젝트 루트/infra/ansible)
        """
        if ansible_dir:
            self.ansible_dir = Path(ansible_dir)
        else:
            # 프로젝트 루트 기준 infra/ansible 경로 설정
            # __file__ = backend/app/integrations/ansible/__init__.py
            # parents[4] = repo root
            repo_root = Path(__file__).resolve().parents[4]
            self.ansible_dir = repo_root / "infra" / "ansible"
        
        # 디렉토리 존재 여부 확인
        if not self.ansible_dir.exists():
            self.ansible_dir.mkdir(parents=True, exist_ok=True)
        
        # Inventory 파일 경로
        self.inventory_file = self.ansible_dir / "inventory.yml"
    
    def create_inventory(self, hosts: List[Dict[str, str]], task_id: str = None) -> Optional[Path]:
        """
        Ansible inventory 파일 동적 생성
        
        Args:
            hosts: 호스트 정보 리스트 [{"name": "vm1", "ip": "192.168.1.100", "user": "root"}]
            task_id: 작업 식별자 (로그용)
            
        Returns:
            생성 성공 여부
        """
        try:
            inventory_data = {
                "all": {
                    "children": {
                        "proxmox_vms": {
                            "hosts": {}
                        }
                    },
                    "vars": {
                        "ansible_ssh_common_args": "-o StrictHostKeyChecking=no"
                    }
                }
            }
            
            # 호스트 정보 추가
            for host in hosts:
                host_name = host.get("name", f"vm{len(inventory_data['all']['children']['proxmox_vms']['hosts'])}")
                host_config = {
                    "ansible_host": host.get("ip", ""),
                    "ansible_user": host.get("user", os.getenv("ANSIBLE_SSH_USER", "root")),
                }
                
                # SSH 키 파일이 설정되어 있으면 추가
                ssh_key = os.getenv("ANSIBLE_SSH_PRIVATE_KEY_FILE")
                if ssh_key:
                    host_config["ansible_ssh_private_key_file"] = ssh_key
                
                inventory_data["all"]["children"]["proxmox_vms"]["hosts"][host_name] = host_config
            
            inventory_path = self.inventory_file
            if task_id:
                safe_task_id = "".join(ch for ch in str(task_id) if ch.isalnum() or ch in {"-", "_"})
                suffix = safe_task_id or uuid.uuid4().hex[:8]
                inventory_path = self.ansible_dir / f"inventory.{suffix}.yml"

            # YAML 파일로 저장
            with open(inventory_path, "w") as f:
                yaml.dump(inventory_data, f, default_flow_style=False, allow_unicode=True)

            if task_id:
                task_manager.append_log(task_id, f"Inventory 파일 생성 완료: {inventory_path}")
                task_manager.append_log(task_id, f"호스트 수: {len(hosts)}")

            return inventory_path
        except Exception as e:
            if task_id:
                task_manager.append_log(task_id, f"Inventory 파일 생성 실패: {str(e)}")
            return None
    
    def run_playbook(
        self,
        playbook_file: str = "playbook.yml",
        task_id: str = None,
        extra_vars: Optional[dict] = None,
        inventory_hosts: Optional[List[Dict[str, str]]] = None
    ) -> tuple[bool, str]:
        """
        Ansible Playbook 실행
        
        Args:
            playbook_file: 실행할 playbook 파일명 (기본값: playbook.yml)
            task_id: 작업 식별자 (로그 및 상태 추적용)
            extra_vars: 추가 변수 딕셔너리 (ansible-playbook -e 옵션)
            
        Returns:
            (성공 여부, 에러 메시지) 튜플
        """
        playbook_path = self.ansible_dir / playbook_file
        
        # Playbook 파일 존재 여부 확인
        if not playbook_path.exists():
            error_msg = f"Playbook 파일을 찾을 수 없습니다: {playbook_path}"
            if task_id:
                task_manager.append_log(task_id, f"ERROR: {error_msg}")
            return False, error_msg
        
        # Inventory 파일 생성 (호스트 정보가 제공된 경우)
        created_inventory_path: Optional[Path] = None
        if inventory_hosts:
            created_inventory_path = self.create_inventory(inventory_hosts, task_id)
            if created_inventory_path is None:
                return False, "Inventory 파일 생성 실패"

        # Inventory 파일이 없으면 기본 inventory.yml 사용
        inventory_path = created_inventory_path
        if inventory_path is None and self.inventory_file.exists():
            inventory_path = self.inventory_file
        
        try:
            # ansible-playbook 명령어 구성
            command = ["ansible-playbook", str(playbook_path)]
            
            # Inventory 파일 지정
            if inventory_path:
                command.extend(["-i", str(inventory_path)])
            
            # 추가 변수 처리 (-e 옵션)
            if extra_vars:
                import json
                # 전체 extra_vars를 JSON 문자열로 전달
                # Ansible은 -e '{"key": ["val1", "val2"]}' 형식을 인식함
                vars_json = json.dumps(extra_vars)
                command.extend(["-e", vars_json])
            
            if task_id:
                display_command = command[:]
                if extra_vars:
                    display_command = command[:-2] + ["-e", "<redacted-extra-vars>"]
                    task_manager.append_log(
                        task_id,
                        f"Ansible extra_vars keys: {', '.join(sorted(str(key) for key in extra_vars.keys()))}",
                    )
                task_manager.append_log(task_id, f"실행 명령어: {' '.join(display_command)}")
                task_manager.append_log(task_id, f"작업 디렉토리: {self.ansible_dir}")
                task_manager.append_log(task_id, "=== Ansible Playbook 실행 시작 ===")
            
            # 현재 환경변수를 상속받아 subprocess 실행
            env = os.environ.copy()
            
            # subprocess로 명령어 실행 (실시간 로그 스트리밍)
            process = subprocess.Popen(
                command,
                cwd=str(self.ansible_dir),
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
                    if task_id:
                        task_manager.append_log(task_id, line.strip())
            
            process.wait()
            
            if process.returncode == 0:
                if task_id:
                    task_manager.append_log(task_id, "=== Ansible Playbook 실행 완료 ===")
                return True, ""
            else:
                error_msg = f"Playbook 실행 실패 (종료 코드: {process.returncode})"
                if task_id:
                    task_manager.append_log(task_id, f"ERROR: {error_msg}")
                return False, error_msg
                
        except Exception as e:
            error_msg = f"Playbook 실행 중 예외 발생: {str(e)}"
            if task_id:
                task_manager.append_log(task_id, f"EXCEPTION: {error_msg}")
            return False, error_msg
        finally:
            if created_inventory_path is not None and created_inventory_path.exists():
                try:
                    created_inventory_path.unlink()
                except OSError:
                    pass
