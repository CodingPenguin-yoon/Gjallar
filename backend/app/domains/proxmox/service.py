"""
Proxmox API 연동 서비스 패키지

이 패키지는 Proxmox API와 통신하여 리소스 정보를 조회하는 기능을 제공합니다.
기존 단일 모듈이었던 `proxmox_service.py`의 구현을 패키지 구조로 옮겼습니다.
"""

import os
import re
import time
import ipaddress
import copy
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional
from pathlib import Path
from dotenv import load_dotenv
import urllib3

# SSL 경고 비활성화 (자체 서명 인증서 사용 시)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 환경 변수 로드 (ProxmoxService가 import될 때 실행)
# 패키지로 이동하면서 경로 깊이가 1단계 늘어났기 때문에
# 항상 프로젝트 루트(backend 기준 한 단계 위)의 .env 를 바라보도록 조정한다.
project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)


class ProxmoxService:
    """
    Proxmox API와 통신하는 서비스 클래스
    
    환경 변수에서 Proxmox API 인증 정보를 읽어서
    Proxmox API를 호출하고 결과를 반환합니다.
    """
    
    def __init__(self):
        """
        초기화: 환경 변수에서 Proxmox API 설정 읽기
        """
        self.api_url = os.getenv("PROXMOX_API_URL", "").rstrip('/')
        self.token_id = os.getenv("PROXMOX_API_TOKEN_ID", "")
        self.token_secret = os.getenv("PROXMOX_API_TOKEN_SECRET", "")
        self.tls_insecure = os.getenv("PROXMOX_TLS_INSECURE", "false").lower() == "true"
        self.api_connect_timeout_seconds = self._read_float_env(
            "PROXMOX_API_CONNECT_TIMEOUT_SECONDS",
            5.0,
            minimum=0.1,
        )
        self.api_read_timeout_seconds = self._read_float_env(
            "PROXMOX_API_READ_TIMEOUT_SECONDS",
            self._read_float_env("PROXMOX_API_TIMEOUT_SECONDS", 60.0, minimum=1.0),
            minimum=1.0,
        )
        self._request_timeout = (
            self.api_connect_timeout_seconds,
            self.api_read_timeout_seconds,
        )
        self.vm_inventory_cache_ttl_seconds = self._read_float_env(
            "PROXMOX_VM_INVENTORY_CACHE_TTL_SECONDS",
            10.0,
            minimum=0.0,
        )
        self._vm_inventory_cache: Dict[str, Dict[str, Any]] = {}
        self._vm_inventory_cache_lock = threading.Lock()
        
        # 디버깅: 설정 확인
        if not self.api_url:
            print("경고: PROXMOX_API_URL이 설정되지 않았습니다.")
            self.api_url = None
        if not self.token_id:
            print("경고: PROXMOX_API_TOKEN_ID가 설정되지 않았습니다.")
        if not self.token_secret:
            print("경고: PROXMOX_API_TOKEN_SECRET이 설정되지 않았습니다.")
        
        # API URL이 없으면 빈 리스트 반환
        if not self.api_url:
            self.api_url = None

    def _read_float_env(self, name: str, default: float, *, minimum: float = 0.0) -> float:
        raw = os.getenv(name)
        if raw is None:
            return default
        try:
            return max(float(raw), minimum)
        except (TypeError, ValueError):
            return default

    def _natural_sort_key(self, value: object) -> List[object]:
        text = str(value or "").lower()
        return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", text)]

    def _safe_int(self, value: object, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    def _normalize_ipv4_address(self, value: object) -> Optional[str]:
        text = str(value or "").strip()
        if not text:
            return None
        if "/" in text:
            text = text.split("/", 1)[0].strip()
        if not text or text.lower() in {"dhcp", "auto"}:
            return None
        try:
            parsed = ipaddress.ip_address(text)
        except ValueError:
            return None
        if parsed.version != 4 or parsed.is_loopback or parsed.is_link_local:
            return None
        return str(parsed)

    def _merge_ip_addresses(self, *groups: List[str]) -> List[str]:
        merged: List[str] = []
        seen = set()
        for group in groups:
            for candidate in group or []:
                ip = self._normalize_ipv4_address(candidate)
                if not ip or ip in seen:
                    continue
                seen.add(ip)
                merged.append(ip)
        return merged

    def _extract_configured_ipv4_addresses(self, config_data: Dict[str, Any]) -> List[str]:
        candidates: List[str] = []
        if not isinstance(config_data, dict):
            return candidates

        for key, value in config_data.items():
            if not str(key).startswith("ipconfig"):
                continue
            raw = str(value or "").strip()
            if not raw:
                continue
            for part in raw.split(","):
                name, _, part_value = part.partition("=")
                if name.strip() != "ip":
                    continue
                normalized = self._normalize_ipv4_address(part_value)
                if normalized:
                    candidates.append(normalized)

        return self._merge_ip_addresses(candidates)

    def _extract_guest_agent_ipv4_addresses(self, payload: Any) -> List[str]:
        interfaces: List[Dict[str, Any]] = []
        if isinstance(payload, list):
            interfaces = [item for item in payload if isinstance(item, dict)]
        elif isinstance(payload, dict):
            result = payload.get("result")
            if isinstance(result, list):
                interfaces = [item for item in result if isinstance(item, dict)]
            elif isinstance(payload.get("interfaces"), list):
                interfaces = [item for item in payload.get("interfaces", []) if isinstance(item, dict)]

        addresses: List[str] = []
        for interface in interfaces:
            ip_list = interface.get("ip-addresses") or interface.get("ip_addresses") or []
            if not isinstance(ip_list, list):
                continue
            for ip_info in ip_list:
                if not isinstance(ip_info, dict):
                    continue
                ip_type = str(
                    ip_info.get("ip-address-type") or ip_info.get("ip_address_type") or ""
                ).strip().lower()
                if ip_type and ip_type not in {"ipv4", "inet"}:
                    continue
                normalized = self._normalize_ipv4_address(
                    ip_info.get("ip-address") or ip_info.get("ip_address")
                )
                if normalized:
                    addresses.append(normalized)

        return self._merge_ip_addresses(addresses)

    def get_vm_ip_addresses(self, node: str, vmid: int) -> List[str]:
        if not self.api_url:
            return []

        url = f"{self.api_url}/nodes/{node}/qemu/{vmid}/agent/network-get-interfaces"
        timeout = (
            self.api_connect_timeout_seconds,
            min(self.api_read_timeout_seconds, 5.0),
        )
        try:
            response = requests.get(
                url,
                headers=self._auth_headers(),
                verify=not self.tls_insecure,
                timeout=timeout,
            )
            if response.status_code >= 400:
                return []
            payload = response.json()
            return self._extract_guest_agent_ipv4_addresses(payload.get("data"))
        except (requests.RequestException, ValueError):
            return []

    def _auth_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"PVEAPIToken={self.token_id}={self.token_secret}",
        }

    def _make_write_request(
        self,
        endpoint: str,
        *,
        method: str = "POST",
        data: Optional[Dict[str, Any]] = None,
        query: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Proxmox 제어성(POST/DELETE 등) 요청 실행.

        참고:
        - Proxmox는 대부분 form-data 기반 파라미터를 기대하므로 `data`로 전달합니다.
        - DELETE는 query string 파라미터를 받을 수 있어 `query`를 별도로 제공합니다.
        """
        if not self.api_url:
            return {"data": None, "error": "PROXMOX_API_URL이 설정되지 않았습니다."}

        url = f"{self.api_url}{endpoint}"
        try:
            response = requests.request(
                method.upper(),
                url,
                headers=self._auth_headers(),
                data=data,
                params=query,
                verify=not self.tls_insecure,
                timeout=self._request_timeout,
            )
            response.raise_for_status()

            if not response.text:
                return {"data": None}

            try:
                return response.json()
            except ValueError:
                return {"data": response.text}
        except requests.exceptions.RequestException as e:
            error_message = str(e)
            if hasattr(e, "response") and e.response is not None:
                error_message = (
                    f"{e.response.status_code}: {e.response.text[:500]}"
                )
            print(f"Proxmox 제어 API 요청 실패: {url}")
            print(f"에러: {error_message}")
            return {"data": None, "error": error_message}
    
    def _make_request(self, endpoint: str, method: str = "GET", params: Optional[Dict] = None) -> Dict:
        """
        Proxmox API 요청 실행 (내부 메서드)
        
        Args:
            endpoint: API 엔드포인트 (예: "/nodes")
            method: HTTP 메서드 (GET, POST 등)
            params: 쿼리 파라미터
            
        Returns:
            API 응답 데이터 딕셔너리
            
        Raises:
            Exception: API 요청 실패 시
        """
        if not self.api_url:
            return {"data": []}
        
        url = f"{self.api_url}{endpoint}"
        headers = self._auth_headers()
        
        try:
            if method == "GET":
                response = requests.get(
                    url,
                    headers=headers,
                    params=params,
                    verify=not self.tls_insecure,
                    timeout=self._request_timeout
                )
            else:
                response = requests.request(
                    method,
                    url,
                    headers=headers,
                    json=params,
                    verify=not self.tls_insecure,
                    timeout=self._request_timeout
                )
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            # API 연결 실패 시 에러 정보 포함하여 반환 (디버깅용)
            print(f"Proxmox API 요청 실패: {url}")
            print(f"에러: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"응답 상태 코드: {e.response.status_code}")
                print(f"응답 내용: {e.response.text[:200]}")
            return {"data": [], "error": str(e)}
        except Exception as e:
            print(f"Proxmox API 예외 발생: {url}")
            print(f"에러: {str(e)}")
            return {"data": [], "error": str(e)}
    
    def get_nodes(self) -> List[Dict]:
        """
        Proxmox 노드(서버) 목록 조회
        
        Returns:
            노드 정보 리스트
        """
        try:
            result = self._make_request("/nodes")
            nodes = result.get("data", [])
            
            # 노드 정보를 프론트엔드 형식으로 변환
            formatted_nodes = []
            for node in nodes:
                formatted_nodes.append({
                    "id": node.get("node"),
                    "server_id": node.get("node"),
                    "name": node.get("node"),
                    "server_name": node.get("node"),
                    "status": node.get("status", "unknown"),
                    "cpu": node.get("maxcpu", 0),
                    "memory": node.get("maxmem", 0),
                    "uptime": node.get("uptime", 0),
                })

            return sorted(
                formatted_nodes,
                key=lambda item: self._natural_sort_key(
                    item.get("id") or item.get("server_id") or item.get("name") or ""
                ),
            )
        except Exception:
            return []
    
    def get_templates(self, node: Optional[str] = None) -> List[Dict]:
        """
        Proxmox 템플릿 목록 조회
        
        Args:
            node: 특정 노드에서만 조회 (None이면 모든 노드)
            
        Returns:
            템플릿 정보 리스트
        """
        try:
            templates = []
            
            # 노드 목록 가져오기
            if node:
                nodes = [{"node": node}]
            else:
                nodes_result = self._make_request("/nodes")
                nodes = nodes_result.get("data", [])
            
            # 각 노드에서 템플릿 조회
            for node_info in nodes:
                node_name = node_info.get("node")
                if not node_name:
                    continue
                
                # VM 목록 조회 (템플릿 포함)
                vms_result = self._make_request(f"/nodes/{node_name}/qemu")
                vms = vms_result.get("data", [])
                
                # 템플릿만 필터링 (template 속성이 1인 것)
                for vm in vms:
                    if vm.get("template") == 1:
                        templates.append({
                            "id": f"{node_name}/{vm.get('vmid')}",
                            "template_id": f"{node_name}/{vm.get('vmid')}",
                            "name": vm.get("name", f"template-{vm.get('vmid')}"),
                            "template_name": vm.get("name", f"template-{vm.get('vmid')}"),
                            "vmid": vm.get("vmid"),
                            "node": node_name,
                            "cpu_cores": vm.get("cpus", 0),
                            "memory_gb": round(vm.get("maxmem", 0) / 1024 / 1024 / 1024, 2) if vm.get("maxmem") else 0,
                        })

            return sorted(
                templates,
                key=lambda item: (
                    self._natural_sort_key(item.get("node") or ""),
                    self._safe_int(item.get("vmid"), 10**9),
                    self._natural_sort_key(item.get("name") or item.get("template_name") or ""),
                ),
            )
        except Exception:
            return []
    
    def get_storages(self, node: Optional[str] = None) -> List[Dict]:
        """
        Proxmox 스토리지 목록 조회

        선택한 노드의 로컬 스토리지와 공유 스토리지(NFS 등)만 반환합니다.
        다른 노드의 로컬 스토리지는 필터링됩니다.

        Args:
            node: 특정 노드에서만 조회 (None이면 첫 번째 노드)

        Returns:
            스토리지 정보 리스트
        """
        try:
            storages = []

            # 노드 선택
            if not node:
                nodes_result = self._make_request("/nodes")
                nodes = nodes_result.get("data", [])
                if nodes:
                    node = nodes[0].get("node")

            if not node:
                return []

            # 스토리지 목록 조회
            storages_result = self._make_request(f"/nodes/{node}/storage")
            storage_list = storages_result.get("data", [])

            # 스토리지 정보 변환
            for storage in storage_list:
                storage_info = storage.get("storage", "")
                if not storage_info:
                    continue

                # 스토리지 상세 정보 조회
                try:
                    detail_result = self._make_request(f"/storage/{storage_info}")
                    detail = detail_result.get("data", {})

                    # 스토리지 필터링:
                    # 1. shared=1 이면 공유 스토리지 (NFS, Ceph 등) -> 모든 노드에서 표시
                    # 2. nodes 필드가 없거나 비어있으면 모든 노드에서 접근 가능
                    # 3. nodes 필드에 현재 노드가 포함되어 있으면 표시
                    is_shared = detail.get("shared", 0) == 1
                    storage_nodes = detail.get("nodes", "")

                    # nodes 필드가 있으면 해당 노드만 접근 가능
                    if storage_nodes and not is_shared:
                        # 쉼표로 구분된 노드 목록 파싱
                        allowed_nodes = [n.strip() for n in storage_nodes.split(",")]
                        if node not in allowed_nodes:
                            # 현재 노드가 허용된 노드 목록에 없으면 스킵
                            continue

                    storages.append({
                        "id": storage_info,
                        "storage_id": storage_info,
                        "name": storage_info,
                        "storage_name": storage_info,
                        "type": detail.get("type", storage.get("type", "unknown")),
                        "content": detail.get("content", []),
                        "shared": is_shared,
                        "size_gb": round(detail.get("total", 0) / 1024 / 1024 / 1024, 2) if detail.get("total") else None,
                        "available_gb": round((detail.get("total", 0) - detail.get("used", 0)) / 1024 / 1024 / 1024, 2) if detail.get("total") else None,
                    })
                except Exception:
                    # 상세 정보 조회 실패 시 기본 정보만 (필터링 불가하므로 포함)
                    storages.append({
                        "id": storage_info,
                        "storage_id": storage_info,
                        "name": storage_info,
                        "storage_name": storage_info,
                        "type": storage.get("type", "unknown"),
                        "shared": False,
                    })

            return sorted(
                storages,
                key=lambda item: self._natural_sort_key(
                    item.get("id") or item.get("storage_id") or item.get("name") or ""
                ),
            )
        except Exception:
            return []
    
    def _get_vm_inventory_workers(self) -> int:
        raw_value = os.getenv("PROXMOX_VM_INVENTORY_WORKERS", "8")
        try:
            return max(1, int(raw_value))
        except (TypeError, ValueError):
            return 8

    def _build_vm_inventory_item(self, node_name: str, vm: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if vm.get("template") == 1:
            return None

        vmid = vm.get("vmid")
        config_data: Dict[str, Any] = {}
        disks = []
        total_disk_gb = 0

        try:
            config_result = self._make_request(f"/nodes/{node_name}/qemu/{vmid}/config")
            config_payload = config_result.get("data", {})
            if isinstance(config_payload, dict):
                config_data = config_payload

            for key, value in config_data.items():
                if any(key.startswith(prefix) for prefix in ["scsi", "virtio", "ide", "sata"]):
                    if isinstance(value, str) and "media=cdrom" not in value:
                        size_str = None
                        for param in value.split(","):
                            if param.startswith("size="):
                                size_str = param.split("=")[1]
                                break

                        if size_str:
                            size_gb = 0
                            if size_str.endswith("G"):
                                size_gb = float(size_str[:-1])
                            elif size_str.endswith("M"):
                                size_gb = float(size_str[:-1]) / 1024
                            elif size_str.endswith("K"):
                                size_gb = float(size_str[:-1]) / 1024 / 1024
                            else:
                                try:
                                    size_gb = float(size_str) / 1024 / 1024 / 1024
                                except Exception:
                                    pass

                            if size_gb > 0:
                                disks.append({
                                    "device": key,
                                    "size_gb": round(size_gb, 2),
                                    "storage": value.split(":")[0] if ":" in value else "unknown"
                                })
                                total_disk_gb += size_gb
        except Exception:
            pass

        if not disks:
            maxdisk_gb = round(vm.get("maxdisk", 0) / 1024 / 1024 / 1024, 2) if vm.get("maxdisk") else 0
            if maxdisk_gb > 0:
                disks.append({
                    "device": "unknown",
                    "size_gb": maxdisk_gb,
                    "storage": "unknown"
                })
                total_disk_gb = maxdisk_gb

        configured_ip_addresses = self._extract_configured_ipv4_addresses(config_data)
        guest_ip_addresses = (
            self.get_vm_ip_addresses(node_name, vmid)
            if str(vm.get("status", "")).strip().lower() == "running"
            else []
        )
        ip_addresses = self._merge_ip_addresses(configured_ip_addresses, guest_ip_addresses)

        return {
            "id": f"{node_name}/{vmid}",
            "vm_id": f"{node_name}/{vmid}",
            "vmid": vmid,
            "name": vm.get("name", f"vm-{vmid}"),
            "node": node_name,
            "status": vm.get("status", "unknown"),
            "cpu_cores": vm.get("cpus", 0),
            "memory_gb": round(vm.get("maxmem", 0) / 1024 / 1024 / 1024, 2) if vm.get("maxmem") else 0,
            "disk_gb": round(total_disk_gb, 2),
            "disks": disks,
            "uptime": vm.get("uptime", 0),
            "primary_ip": ip_addresses[0] if ip_addresses else None,
            "ip_addresses": ip_addresses,
        }

    def _get_cached_vm_inventory(self, cache_key: str) -> Optional[List[Dict[str, Any]]]:
        if self.vm_inventory_cache_ttl_seconds <= 0:
            return None
        now = time.monotonic()
        with self._vm_inventory_cache_lock:
            cached = self._vm_inventory_cache.get(cache_key)
            if not cached:
                return None
            age = now - float(cached.get("cached_at", 0.0))
            if age > self.vm_inventory_cache_ttl_seconds:
                return None
            return copy.deepcopy(cached.get("items", []))

    def _set_cached_vm_inventory(self, cache_key: str, items: List[Dict[str, Any]]) -> None:
        if self.vm_inventory_cache_ttl_seconds <= 0:
            return
        with self._vm_inventory_cache_lock:
            self._vm_inventory_cache[cache_key] = {
                "cached_at": time.monotonic(),
                "items": copy.deepcopy(items),
            }

    def get_vms(self, node: Optional[str] = None) -> List[Dict]:
        try:
            cache_key = node or "__all__"
            cached_vms = self._get_cached_vm_inventory(cache_key)
            if cached_vms is not None:
                return cached_vms

            if node:
                nodes = [{"node": node}]
            else:
                nodes_result = self._make_request("/nodes")
                nodes = nodes_result.get("data", [])

            vm_jobs = []
            for node_info in nodes:
                node_name = node_info.get("node")
                if not node_name:
                    continue

                vms_result = self._make_request(f"/nodes/{node_name}/qemu")
                vm_list = vms_result.get("data", [])
                for vm in vm_list:
                    if vm.get("template") != 1:
                        vm_jobs.append((node_name, vm))

            if not vm_jobs:
                return []

            vms = []
            workers = min(self._get_vm_inventory_workers(), len(vm_jobs))
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [
                    executor.submit(self._build_vm_inventory_item, node_name, vm)
                    for node_name, vm in vm_jobs
                ]
                for future in as_completed(futures):
                    item = future.result()
                    if item:
                        vms.append(item)

            sorted_vms = sorted(
                vms,
                key=lambda item: (
                    self._natural_sort_key(item.get("node") or ""),
                    self._safe_int(item.get("vmid"), 10**9),
                    self._natural_sort_key(item.get("name") or item.get("server_name") or ""),
                ),
            )
            self._set_cached_vm_inventory(cache_key, sorted_vms)
            return sorted_vms
        except Exception:
            return []

    def get_networks(self, node: Optional[str] = None) -> List[Dict]:
        """
        Proxmox 네트워크 목록 조회

        VM에 할당 가능한 bridge 타입 인터페이스(vmbr*)만 반환합니다.
        물리 인터페이스(eth, enp 등)는 VM에 직접 할당할 수 없으므로 필터링됩니다.

        Args:
            node: 특정 노드에서만 조회 (None이면 첫 번째 노드)

        Returns:
            네트워크 정보 리스트
        """
        try:
            networks = []

            # 노드 선택
            if not node:
                nodes_result = self._make_request("/nodes")
                nodes = nodes_result.get("data", [])
                if nodes:
                    node = nodes[0].get("node")

            if not node:
                return []

            # 네트워크 목록 조회
            networks_result = self._make_request(f"/nodes/{node}/network")
            network_list = networks_result.get("data", [])

            # 네트워크 정보 변환 (bridge 타입만 필터링)
            for network in network_list:
                iface = network.get("iface", "")
                iface_type = network.get("type", "")

                # VM에 할당 가능한 bridge 타입만 포함
                # - vmbr* 형식의 Linux bridge만 VM에 할당 가능
                # - eth, enp, enx 등 물리 인터페이스는 제외
                # - lo (loopback), bond, vlan 등도 제외
                if not iface or not iface.startswith("vmbr"):
                    continue

                # bridge 타입인지 추가 확인
                if iface_type != "bridge":
                    continue

                networks.append({
                    "id": iface,
                    "network_id": iface,
                    "name": iface,
                    "network_name": iface,
                    "type": iface_type,
                    "cidr": network.get("cidr", ""),
                    "gateway": network.get("gateway", ""),
                    "description": "bridge interface",
                })

            return sorted(
                networks,
                key=lambda item: self._natural_sort_key(
                    item.get("id") or item.get("network_id") or item.get("name") or ""
                ),
            )
        except Exception:
            return []
    
    def get_node_status(self, node: str) -> Optional[Dict]:
        """
        노드 상태 정보 조회
        
        Args:
            node: 노드 이름
            
        Returns:
            노드 상태 정보
        """
        try:
            result = self._make_request(f"/nodes/{node}/status")
            return result.get("data", {})
        except Exception:
            return None
    
    def get_node_rrddata(self, node: str, timeframe: str = "hour", cf: str = "AVERAGE") -> List[Dict]:
        """
        노드 RRD 데이터 조회 (CPU, 메모리, 네트워크 등)
        
        Args:
            node: 노드 이름
            timeframe: 시간 범위 (hour, day, week, month, year)
            cf: 통계 함수 (AVERAGE, MAX)
            
        Returns:
            RRD 데이터 리스트
        """
        try:
            result = self._make_request(f"/nodes/{node}/rrddata", params={"timeframe": timeframe, "cf": cf})
            return result.get("data", [])
        except Exception:
            return []
    
    def get_vm_status(self, node: str, vmid: int) -> Optional[Dict]:
        """
        VM 현재 상태 조회
        
        Args:
            node: 노드 이름
            vmid: VM ID
            
        Returns:
            VM 상태 정보
        """
        try:
            result = self._make_request(f"/nodes/{node}/qemu/{vmid}/status/current")
            data = result.get("data")
            return data if isinstance(data, dict) and data else None
        except Exception:
            return None
    
    def get_vm_rrddata(self, node: str, vmid: int, timeframe: str = "hour", cf: str = "AVERAGE") -> List[Dict]:
        """
        VM RRD 데이터 조회 (CPU, 메모리, 네트워크 등)
        
        Args:
            node: 노드 이름
            vmid: VM ID
            timeframe: 시간 범위 (hour, day, week, month, year)
            cf: 통계 함수 (AVERAGE, MAX)
            
        Returns:
            RRD 데이터 리스트
        """
        try:
            result = self._make_request(f"/nodes/{node}/qemu/{vmid}/rrddata", params={"timeframe": timeframe, "cf": cf})
            return result.get("data", [])
        except Exception:
            return []

    def get_task_status(self, node: str, upid: str) -> Optional[Dict]:
        """
        Proxmox task 상태 조회

        Args:
            node: 노드 이름
            upid: Proxmox 작업 ID (UPID:...)

        Returns:
            task 상태 딕셔너리 또는 None
        """
        try:
            result = self._make_request(f"/nodes/{node}/tasks/{upid}/status")
            return result.get("data", {})
        except Exception:
            return None

    def wait_for_task_completion(
        self,
        node: str,
        upid: str,
        *,
        timeout_seconds: int = 60,
        poll_interval_seconds: float = 1.0,
    ) -> Dict[str, Any]:
        """
        Proxmox task 가 종료될 때까지 폴링
        """
        timeout = max(1, int(timeout_seconds))
        poll_interval = max(0.5, float(poll_interval_seconds))
        deadline = time.monotonic() + timeout

        while time.monotonic() <= deadline:
            status = self.get_task_status(node, upid) or {}
            status_text = str(status.get("status", "")).strip().lower()
            exit_status = str(status.get("exitstatus", "")).strip()

            if status_text == "stopped":
                if not exit_status or exit_status.upper() == "OK":
                    return {
                        "success": True,
                        "status": status_text,
                        "exitstatus": exit_status or "OK",
                    }
                return {
                    "success": False,
                    "status": status_text,
                    "exitstatus": exit_status,
                    "error": f"Proxmox task failed with exit status: {exit_status}",
                }

            time.sleep(poll_interval)

        return {
            "success": False,
            "status": "timeout",
            "error": "Timed out while waiting for Proxmox task completion.",
        }

    def get_task_log(self, node: str, upid: str, start: int = 0) -> List[Dict]:
        """
        Proxmox task 로그 조회

        Args:
            node: 노드 이름
            upid: Proxmox 작업 ID (UPID:...)
            start: 시작 라인 인덱스

        Returns:
            로그 엔트리 리스트
        """
        try:
            result = self._make_request(
                f"/nodes/{node}/tasks/{upid}/log",
                params={"start": max(0, int(start))},
            )
            return result.get("data", [])
        except Exception:
            return []

    def get_node_tasks(
        self,
        node: str,
        limit: int = 100,
        source: str = "all",
        vmid: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        특정 노드의 최근 task 목록 조회

        Args:
            node: 노드 이름
            limit: 최대 조회 개수
            source: Proxmox task source 옵션 (all/active/...)
            vmid: VM ID 필터 (선택)

        Returns:
            task 리스트
        """
        try:
            params: Dict[str, Any] = {
                "limit": max(1, min(int(limit), 500)),
                "source": source or "all",
            }
            if vmid is not None:
                params["vmid"] = int(vmid)
            result = self._make_request(
                f"/nodes/{node}/tasks",
                params=params,
            )
            data = result.get("data", [])
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def find_vm_id_by_name(self, node: str, vm_name: str) -> Optional[int]:
        """
        노드에서 VM 이름으로 VMID 조회 (경량 조회)
        """
        name = str(vm_name or "").strip().lower()
        if not node or not name:
            return None

        try:
            result = self._make_request(f"/nodes/{node}/qemu")
            vm_list = result.get("data", [])
            if not isinstance(vm_list, list):
                return None
            for vm in vm_list:
                current_name = str(vm.get("name", "")).strip().lower()
                if current_name != name:
                    continue
                if vm.get("template") == 1:
                    continue
                vmid = vm.get("vmid")
                if vmid is None:
                    continue
                try:
                    return int(vmid)
                except (TypeError, ValueError):
                    continue
            return None
        except Exception:
            return None

    def shutdown_vm(self, node: str, vmid: int) -> Dict[str, Any]:
        """
        VM 정상 종료 요청 (graceful shutdown)
        """
        result = self._make_write_request(
            f"/nodes/{node}/qemu/{vmid}/status/shutdown",
            method="POST",
        )
        if result.get("error"):
            return {"success": False, "error": result["error"]}
        return {"success": True, "upid": result.get("data")}

    def stop_vm(self, node: str, vmid: int) -> Dict[str, Any]:
        """
        VM 강제 종료 요청 (power off)
        """
        result = self._make_write_request(
            f"/nodes/{node}/qemu/{vmid}/status/stop",
            method="POST",
        )
        if result.get("error"):
            return {"success": False, "error": result["error"]}
        return {"success": True, "upid": result.get("data")}

    def start_vm(self, node: str, vmid: int) -> Dict[str, Any]:
        """
        VM 시작 요청
        """
        result = self._make_write_request(
            f"/nodes/{node}/qemu/{vmid}/status/start",
            method="POST",
        )
        if result.get("error"):
            return {"success": False, "error": result["error"]}
        return {"success": True, "upid": result.get("data")}

    def reboot_vm(self, node: str, vmid: int) -> Dict[str, Any]:
        """
        VM 재부팅 요청
        """
        result = self._make_write_request(
            f"/nodes/{node}/qemu/{vmid}/status/reboot",
            method="POST",
        )
        if result.get("error"):
            return {"success": False, "error": result["error"]}
        return {"success": True, "upid": result.get("data")}

    def perform_vm_action(
        self,
        node: str,
        vmid: int,
        *,
        action: str,
        timeout_seconds: int = 60,
    ) -> Dict[str, Any]:
        """
        VM 라이프사이클 액션 수행
        """
        status = self.get_vm_status(node, vmid)
        if not status:
            return {
                "success": False,
                "not_found": True,
                "error": f"VM not found: {node}/{vmid}",
            }

        normalized_action = str(action or "").strip().lower()
        current_status = str(status.get("status", "unknown")).strip().lower()
        result: Dict[str, Any] = {
            "success": False,
            "node": node,
            "vmid": int(vmid),
            "action": normalized_action,
            "initial_status": current_status,
            "warnings": [],
        }

        if normalized_action == "start":
            if current_status == "running":
                result["success"] = True
                result["message"] = "VM is already running."
                result["no_op"] = True
                return result

            start_result = self.start_vm(node, vmid)
            if not start_result.get("success"):
                result["error"] = f"VM start 실패: {start_result.get('error')}"
                return result

            result["upid"] = start_result.get("upid")
            if not self.wait_for_vm_status(
                node,
                vmid,
                "running",
                timeout_seconds=timeout_seconds,
            ):
                result["error"] = "VM running 상태 확인 타임아웃"
                return result

            result["success"] = True
            result["message"] = "VM started successfully."
            return result

        if normalized_action == "shutdown":
            if current_status == "stopped":
                result["success"] = True
                result["message"] = "VM is already stopped."
                result["no_op"] = True
                return result

            shutdown_result = self.shutdown_vm(node, vmid)
            if not shutdown_result.get("success"):
                result["error"] = f"VM shutdown 실패: {shutdown_result.get('error')}"
                return result

            result["upid"] = shutdown_result.get("upid")
            if not self.wait_for_vm_status(
                node,
                vmid,
                "stopped",
                timeout_seconds=timeout_seconds,
            ):
                result["error"] = "VM stopped 상태 확인 타임아웃"
                return result

            result["success"] = True
            result["message"] = "VM shut down successfully."
            return result

        if normalized_action == "stop":
            if current_status == "stopped":
                result["success"] = True
                result["message"] = "VM is already stopped."
                result["no_op"] = True
                return result

            stop_result = self.stop_vm(node, vmid)
            if not stop_result.get("success"):
                result["error"] = f"VM stop 실패: {stop_result.get('error')}"
                return result

            result["upid"] = stop_result.get("upid")
            if not self.wait_for_vm_status(
                node,
                vmid,
                "stopped",
                timeout_seconds=timeout_seconds,
            ):
                result["error"] = "VM stopped 상태 확인 타임아웃"
                return result

            result["success"] = True
            result["message"] = "VM stopped successfully."
            return result

        if normalized_action == "reboot":
            if current_status != "running":
                result["invalid_state"] = True
                result["error"] = "VM must be running before reboot."
                return result

            reboot_result = self.reboot_vm(node, vmid)
            if not reboot_result.get("success"):
                result["error"] = f"VM reboot 실패: {reboot_result.get('error')}"
                return result

            result["upid"] = reboot_result.get("upid")
            result["success"] = True
            result["accepted"] = True
            result["message"] = "VM reboot request accepted. Verify the VM status after refresh."
            return result

        result["error"] = f"Unsupported action: {normalized_action}"
        return result

    def update_vm_resources(
        self,
        node: str,
        vmid: int,
        *,
        cpu_cores: int,
        memory_gb: float,
    ) -> Dict[str, Any]:
        """
        VM CPU/메모리 설정 변경

        현재 프로젝트에서는 정지된 VM에 대해서만 허용한다.
        """
        status = self.get_vm_status(node, vmid)
        if not status:
            return {
                "success": False,
                "not_found": True,
                "error": f"VM not found: {node}/{vmid}",
            }

        current_status = str(status.get("status", "unknown")).strip().lower()
        result: Dict[str, Any] = {
            "success": False,
            "node": node,
            "vmid": int(vmid),
            "initial_status": current_status,
            "cpu_cores": int(cpu_cores),
            "memory_gb": float(memory_gb),
        }

        if current_status != "stopped":
            result["invalid_state"] = True
            result["error"] = "VM must be stopped before updating CPU or memory."
            return result

        memory_mib = max(1, int(round(float(memory_gb) * 1024)))
        result["memory_mib"] = memory_mib

        update_result = self._make_write_request(
            f"/nodes/{node}/qemu/{vmid}/config",
            method="PUT",
            data={
                "cores": int(cpu_cores),
                "memory": memory_mib,
            },
        )
        if update_result.get("error"):
            result["error"] = f"VM 리소스 업데이트 실패: {update_result.get('error')}"
            return result

        result["success"] = True
        result["upid"] = update_result.get("data")
        result["message"] = "VM CPU and memory updated successfully."
        return result

    def delete_vm(
        self,
        node: str,
        vmid: int,
        *,
        purge: bool = True,
        destroy_unreferenced_disks: bool = True,
    ) -> Dict[str, Any]:
        """
        VM 삭제 요청
        """
        query: Dict[str, Any] = {}
        if purge:
            query["purge"] = 1
        if destroy_unreferenced_disks:
            query["destroy-unreferenced-disks"] = 1

        result = self._make_write_request(
            f"/nodes/{node}/qemu/{vmid}",
            method="DELETE",
            query=query,
        )
        if result.get("error"):
            return {"success": False, "error": result["error"]}
        return {"success": True, "upid": result.get("data")}

    def wait_for_vm_status(
        self,
        node: str,
        vmid: int,
        target_status: str,
        *,
        timeout_seconds: int = 60,
        poll_interval_seconds: float = 2.0,
    ) -> bool:
        """
        VM 상태가 target_status가 될 때까지 폴링
        """
        target = str(target_status or "").strip().lower()
        timeout = max(1, int(timeout_seconds))
        poll_interval = max(0.5, float(poll_interval_seconds))
        deadline = time.monotonic() + timeout

        while time.monotonic() <= deadline:
            status = self.get_vm_status(node, vmid)
            if isinstance(status, dict):
                current = str(status.get("status", "")).strip().lower()
                if current == target:
                    return True
            time.sleep(poll_interval)
        return False

    def wait_for_vm_deleted(
        self,
        node: str,
        vmid: int,
        *,
        timeout_seconds: int = 60,
        poll_interval_seconds: float = 2.0,
    ) -> bool:
        """
        VM 삭제 완료(조회 불가) 상태가 될 때까지 폴링
        """
        timeout = max(1, int(timeout_seconds))
        poll_interval = max(0.5, float(poll_interval_seconds))
        deadline = time.monotonic() + timeout

        while time.monotonic() <= deadline:
            status = self.get_vm_status(node, vmid)
            if status is None:
                return True
            time.sleep(poll_interval)
        return False

    def terminate_vm(
        self,
        node: str,
        vmid: int,
        *,
        shutdown_timeout_seconds: int = 60,
        force_stop_timeout_seconds: int = 30,
    ) -> Dict[str, Any]:
        """
        VM 종료 후 삭제(terminate) 처리
        순서: 상태조회 -> (running이면 shutdown) -> (timeout 시 stop) -> delete
        """
        status = self.get_vm_status(node, vmid)
        if not status:
            return {
                "success": False,
                "not_found": True,
                "error": f"VM not found: {node}/{vmid}",
            }

        initial_status = str(status.get("status", "unknown")).strip().lower()
        result: Dict[str, Any] = {
            "success": False,
            "node": node,
            "vmid": int(vmid),
            "initial_status": initial_status,
            "shutdown_requested": False,
            "forced_stop_requested": False,
            "delete_requested": False,
            "warnings": [],
        }

        if initial_status == "running":
            shutdown_result = self.shutdown_vm(node, vmid)
            if not shutdown_result.get("success"):
                result["error"] = f"VM shutdown 실패: {shutdown_result.get('error')}"
                return result

            result["shutdown_requested"] = True
            result["shutdown_upid"] = shutdown_result.get("upid")

            stopped = self.wait_for_vm_status(
                node,
                vmid,
                "stopped",
                timeout_seconds=shutdown_timeout_seconds,
            )
            if not stopped:
                result["warnings"].append(
                    "Graceful shutdown 타임아웃으로 force stop을 시도합니다."
                )
                stop_result = self.stop_vm(node, vmid)
                if not stop_result.get("success"):
                    result["error"] = f"VM force stop 실패: {stop_result.get('error')}"
                    return result

                result["forced_stop_requested"] = True
                result["force_stop_upid"] = stop_result.get("upid")

                forced_stopped = self.wait_for_vm_status(
                    node,
                    vmid,
                    "stopped",
                    timeout_seconds=force_stop_timeout_seconds,
                )
                if not forced_stopped:
                    result["error"] = "VM stopped 상태 확인 타임아웃"
                    return result

        delete_result = self.delete_vm(node, vmid)
        if not delete_result.get("success"):
            result["error"] = f"VM 삭제 실패: {delete_result.get('error')}"
            return result

        result["delete_requested"] = True
        result["delete_upid"] = delete_result.get("upid")

        deleted = self.wait_for_vm_deleted(node, vmid, timeout_seconds=60)
        if not deleted:
            result["warnings"].append("삭제 요청은 성공했지만 삭제 완료 확인이 지연되고 있습니다.")

        result["success"] = True
        return result
    
    def get_all_nodes_monitoring(self) -> List[Dict]:
        """
        모든 노드의 모니터링 정보 조회
        
        Returns:
            노드 모니터링 정보 리스트
        """
        try:
            nodes = self.get_nodes()
            monitoring_data = []
            
            for node_info in nodes:
                node_name = node_info.get("id") or node_info.get("server_id")
                if not node_name:
                    continue
                
                # 노드 상태
                status = self.get_node_status(node_name)
                # 최근 RRD 데이터 (1시간)
                rrd_data = self.get_node_rrddata(node_name, timeframe="hour")
                
                # RRD 데이터에서 최신 값 추출
                latest_rrd = rrd_data[-1] if rrd_data else {}
                
                # CPU 필드가 있는 최신 데이터 포인트 찾기 (일부 포인트에는 cpu 필드가 없을 수 있음)
                cpu_usage_raw = None
                if rrd_data:
                    # 역순으로 검색하여 cpu 필드가 있는 최신 데이터 찾기
                    for rrd_point in reversed(rrd_data):
                        if "cpu" in rrd_point and rrd_point.get("cpu") is not None:
                            cpu_usage_raw = rrd_point.get("cpu")
                            break
                
                # 노드 상태 판단 (uptime이 있으면 online)
                node_status = "online" if status and status.get("uptime", 0) > 0 else "unknown"
                
                # CPU 사용률 (RRD의 cpu는 0-1 범위이므로 100을 곱함)
                # cpu_usage_raw가 None이면 0으로 처리
                cpu_usage_percent = float(cpu_usage_raw) * 100 if cpu_usage_raw is not None else 0
                
                # 메모리 정보 (RRD 데이터에서 가져오거나 status에서 가져오기)
                memory_total = latest_rrd.get("memtotal") if latest_rrd and latest_rrd.get("memtotal") else (status.get("memory", {}).get("total", 0) if status else 0)
                memory_used = latest_rrd.get("memused") if latest_rrd and latest_rrd.get("memused") else (status.get("memory", {}).get("used", 0) if status else 0)
                memory_usage_percent = (memory_used / memory_total * 100) if memory_total > 0 else 0
                
                # Load average (RRD 데이터에서 가져오거나 status에서 가져오기)
                load_avg_raw = latest_rrd.get("loadavg") if latest_rrd and latest_rrd.get("loadavg") else None
                if load_avg_raw is None:
                    load_avg_raw = status.get("loadavg", [0, 0, 0]) if status else [0, 0, 0]
                
                # Load average를 숫자 배열로 변환
                load_avg = []
                if isinstance(load_avg_raw, (list, tuple)):
                    for load in load_avg_raw:
                        try:
                            load_avg.append(float(load) if isinstance(load, str) else load)
                        except (ValueError, TypeError):
                            load_avg.append(0.0)
                elif isinstance(load_avg_raw, (int, float)):
                    # 단일 값인 경우 (RRD 데이터)
                    load_avg = [float(load_avg_raw), float(load_avg_raw), float(load_avg_raw)]
                else:
                    load_avg = [0.0, 0.0, 0.0]
                
                # 디스크 정보 조회 (각 노드의 모든 스토리지 개별 정보)
                # /nodes/{node}/storage 엔드포인트는 이미 total, used, avail 정보를 포함함
                storages = []
                disk_total = 0
                disk_used = 0
                try:
                    storages_result = self._make_request(f"/nodes/{node_name}/storage")
                    storage_list = storages_result.get("data", [])
                    
                    for storage in storage_list:
                        storage_name = storage.get("storage", "")
                        if not storage_name:
                            continue
                        
                        # /nodes/{node}/storage 응답에 이미 total, used, avail 정보가 포함되어 있음
                        storage_total = storage.get("total", 0)
                        storage_used = storage.get("used", 0)
                        storage_avail = storage.get("avail", 0)
                        storage_type = storage.get("type", "unknown")
                        storage_enabled = storage.get("enabled", 0)
                        storage_active = storage.get("active", 0)
                        
                        # 용량 정보가 있고 활성화된 스토리지만 추가
                        if storage_total and storage_total > 0 and storage_enabled:
                            storage_total_gb = round(storage_total / 1024 / 1024 / 1024, 2)
                            storage_used_gb = round(storage_used / 1024 / 1024 / 1024, 2)
                            
                            # avail이 있으면 사용, 없으면 계산
                            if storage_avail and storage_avail > 0:
                                storage_available_gb = round(storage_avail / 1024 / 1024 / 1024, 2)
                            else:
                                storage_available_gb = round((storage_total - storage_used) / 1024 / 1024 / 1024, 2)
                            
                            storage_usage_percent = (storage_used / storage_total * 100) if storage_total > 0 else 0
                            
                            storages.append({
                                "name": storage_name,
                                "type": storage_type,
                                "total_gb": storage_total_gb,
                                "used_gb": storage_used_gb,
                                "available_gb": storage_available_gb,
                                "usage_percent": round(storage_usage_percent, 2),
                                "active": bool(storage_active),
                            })
                            
                            disk_total += storage_total
                            disk_used += storage_used
                    
                    # 스토리지 목록은 이름 기준 자연 오름차순으로 고정
                    storages.sort(key=lambda x: self._natural_sort_key(x.get("name", "")))
                except Exception as e:
                    # 스토리지 목록 조회 실패 시 기본값 유지 (에러 로깅)
                    print(f"스토리지 목록 조회 실패 ({node_name}): {str(e)}")
                    pass
                
                disk_total_gb = round(disk_total / 1024 / 1024 / 1024, 2) if disk_total else 0
                disk_used_gb = round(disk_used / 1024 / 1024 / 1024, 2) if disk_used else 0
                disk_usage_percent = (disk_used / disk_total * 100) if disk_total > 0 else 0
                
                monitoring_data.append({
                    "node": node_name,
                    "name": node_info.get("name", node_name),
                    "status": node_status,
                    "cpu_total": status.get("cpuinfo", {}).get("cpus", 0) if status else 0,
                    "cpu_usage_percent": round(cpu_usage_percent, 2),
                    "memory_total_gb": round(memory_total / 1024 / 1024 / 1024, 2) if memory_total else 0,
                    "memory_used_gb": round(memory_used / 1024 / 1024 / 1024, 2) if memory_used else 0,
                    "memory_usage_percent": round(memory_usage_percent, 2),
                    "disk_total_gb": disk_total_gb,
                    "disk_used_gb": disk_used_gb,
                    "disk_usage_percent": round(disk_usage_percent, 2),
                    "storages": storages,  # 개별 스토리지 목록
                    "uptime": status.get("uptime", 0) if status else 0,
                    "load_avg": load_avg,
                })
            
            return sorted(
                monitoring_data,
                key=lambda item: self._natural_sort_key(
                    item.get("node") or item.get("name") or ""
                ),
            )
        except Exception:
            return []
