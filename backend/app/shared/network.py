"""
네트워크/IP 관리 서비스 패키지

IP 풀에서 사용 가능한 IP를 찾고 할당하는 기능을 제공합니다.
"""

import os
import subprocess
import ipaddress
from typing import Optional, List, Dict
from dataclasses import dataclass


@dataclass
class IPPoolConfig:
    """IP 풀 설정"""
    start: str
    end: str
    gateway: str
    subnet: int = 24


class NetworkService:
    """
    네트워크/IP 관리 서비스

    IP 풀에서 사용 가능한 IP를 찾고, ping으로 사용 여부를 확인합니다.
    """

    def __init__(self):
        """환경변수에서 IP 풀 설정 로드"""
        self.pool_config = self._load_pool_config()

    def _load_pool_config(self) -> Optional[IPPoolConfig]:
        """환경변수에서 IP 풀 설정 로드"""
        start = os.getenv("IP_POOL_START")
        end = os.getenv("IP_POOL_END")
        gateway = os.getenv("IP_GATEWAY")
        subnet = int(os.getenv("IP_SUBNET", "24"))

        if start and end and gateway:
            return IPPoolConfig(
                start=start,
                end=end,
                gateway=gateway,
                subnet=subnet
            )
        return None

    def get_pool_config(self) -> Optional[Dict]:
        """IP 풀 설정 반환"""
        if not self.pool_config:
            return None
        return {
            "start": self.pool_config.start,
            "end": self.pool_config.end,
            "gateway": self.pool_config.gateway,
            "subnet": self.pool_config.subnet,
        }

    def is_ip_in_use(self, ip: str, timeout: float = 1.0) -> bool:
        """
        IP가 사용 중인지 ping으로 확인

        Args:
            ip: 확인할 IP 주소
            timeout: ping 타임아웃 (초)

        Returns:
            사용 중이면 True, 아니면 False
        """
        try:
            # macOS와 Linux에서 다른 옵션 사용
            import platform
            if platform.system() == "Darwin":  # macOS
                cmd = ["ping", "-c", "1", "-W", str(int(timeout * 1000)), ip]
            else:  # Linux
                cmd = ["ping", "-c", "1", "-W", str(int(timeout)), ip]

            result = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout + 1
            )
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            return False
        except Exception:
            return False

    def get_available_ips(self, limit: int = 10) -> List[Dict]:
        """
        사용 가능한 IP 목록 반환

        Args:
            limit: 반환할 최대 IP 개수

        Returns:
            사용 가능한 IP 목록 [{"ip": "192.168.1.100", "status": "available"}, ...]
        """
        if not self.pool_config:
            return []

        available_ips = []
        start_ip = ipaddress.IPv4Address(self.pool_config.start)
        end_ip = ipaddress.IPv4Address(self.pool_config.end)

        current_ip = start_ip
        while current_ip <= end_ip and len(available_ips) < limit:
            ip_str = str(current_ip)

            # Gateway IP는 건너뛰기
            if ip_str == self.pool_config.gateway:
                current_ip += 1
                continue

            # ping으로 사용 여부 확인
            in_use = self.is_ip_in_use(ip_str, timeout=0.5)

            if not in_use:
                available_ips.append({
                    "ip": ip_str,
                    "cidr": f"{ip_str}/{self.pool_config.subnet}",
                    "status": "available"
                })

            current_ip += 1

        return available_ips

    def get_next_available_ip(self) -> Optional[Dict]:
        """
        다음 사용 가능한 IP 반환

        Returns:
            사용 가능한 IP 정보 또는 None
        """
        available = self.get_available_ips(limit=1)
        if available:
            return {
                **available[0],
                "gateway": self.pool_config.gateway,
                "subnet": self.pool_config.subnet
            }
        return None

    def scan_ip_range(self) -> List[Dict]:
        """
        IP 풀 전체 스캔하여 사용 현황 반환

        Returns:
            IP 목록 [{"ip": "192.168.1.100", "status": "in_use" | "available"}, ...]
        """
        if not self.pool_config:
            return []

        result = []
        start_ip = ipaddress.IPv4Address(self.pool_config.start)
        end_ip = ipaddress.IPv4Address(self.pool_config.end)

        current_ip = start_ip
        while current_ip <= end_ip:
            ip_str = str(current_ip)
            in_use = self.is_ip_in_use(ip_str, timeout=0.5)

            result.append({
                "ip": ip_str,
                "cidr": f"{ip_str}/{self.pool_config.subnet}",
                "status": "in_use" if in_use else "available",
                "is_gateway": ip_str == self.pool_config.gateway
            })

            current_ip += 1

        return result


# 전역 인스턴스
network_service = NetworkService()

__all__ = ["NetworkService", "network_service", "IPPoolConfig"]
