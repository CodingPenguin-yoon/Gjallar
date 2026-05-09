"""
LLM 채팅 세션 관리 서비스 모듈 (도메인/commands 버전)

배경/의도/목적:
- Redis 기반으로 세션별 대화 이력을 저장/조회/삭제하는 비즈니스 로직을 담당한다.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional
from uuid import uuid4

import redis
from dotenv import load_dotenv
from pathlib import Path

# 환경 변수 로드
project_root = Path(__file__).resolve().parent.parent.parent.parent
env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)


class ChatSessionService:
    """
    Redis 기반 채팅 세션 관리 서비스
    
    - 대화 이력을 Redis에 저장하여 페이지 새로고침/서버 재시작 후에도 유지
    - 세션 ID 기반으로 대화 이력 조회/갱신
    - 대화 이력 크기 제한 (최근 100개 메시지만 유지)
    """

    def __init__(self) -> None:
        """Redis 클라이언트 초기화"""
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))
        redis_db = int(os.getenv("REDIS_DB", "0"))
        redis_password = os.getenv("REDIS_PASSWORD", None)

        try:
            self.redis_client = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                password=redis_password,
                decode_responses=True,  # 문자열로 자동 디코딩
                socket_connect_timeout=5,
            )
            # 연결 테스트
            self.redis_client.ping()
        except Exception as e:
            print(f"[ChatSessionService] 경고: Redis 연결 실패: {e}")
            print("[ChatSessionService] Redis 없이도 동작하지만 대화 이력이 저장되지 않습니다.")
            self.redis_client = None

        # 대화 이력 키 접두사
        self.session_key_prefix = "llm:chat:session:"
        # 세션 만료 시간 (초) - 7일
        self.session_ttl = int(os.getenv("CHAT_SESSION_TTL_SECONDS", "604800"))
        # 최대 메시지 수 (최근 N개만 유지)
        self.max_messages = int(os.getenv("CHAT_MAX_MESSAGES", "100"))

    def create_session(self) -> str:
        """
        새 채팅 세션 ID 생성
        
        Returns:
            str: 세션 ID (UUID)
        """
        return str(uuid4())

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        extras: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        대화 메시지를 세션에 추가 저장
        
        Args:
            session_id: 세션 ID
            role: 메시지 역할 (user/assistant)
            content: 메시지 내용
            extras: 추가 데이터 (예: data 필드)
            
        Returns:
            bool: 저장 성공 여부
        """
        if not self.redis_client:
            return False

        try:
            key = f"{self.session_key_prefix}{session_id}"
            
            # 메시지 객체 생성
            message = {
                "role": role,
                "content": content,
            }
            if extras:
                message.update(extras)

            # Redis List에 메시지 추가 (JSON 문자열로 저장)
            self.redis_client.rpush(key, json.dumps(message, ensure_ascii=False))

            # 최대 메시지 수 제한 (오래된 메시지 제거)
            current_length = self.redis_client.llen(key)
            if current_length > self.max_messages:
                # 오래된 메시지 제거 (앞에서부터)
                remove_count = current_length - self.max_messages
                for _ in range(remove_count):
                    self.redis_client.lpop(key)

            # 세션 TTL 갱신
            self.redis_client.expire(key, self.session_ttl)

            return True
        except Exception as e:
            print(f"[ChatSessionService] 메시지 저장 실패: session_id={session_id}, error={e}")
            return False

    def get_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """
        세션의 전체 대화 이력 조회
        
        Args:
            session_id: 세션 ID
            
        Returns:
            List[Dict]: 대화 메시지 목록 (역순이 아님, 시간순)
        """
        if not self.redis_client:
            return []

        try:
            key = f"{self.session_key_prefix}{session_id}"
            messages_json = self.redis_client.lrange(key, 0, -1)  # 전체 리스트 조회

            messages: List[Dict[str, Any]] = []
            for msg_json in messages_json:
                try:
                    msg = json.loads(msg_json)
                    messages.append(msg)
                except json.JSONDecodeError:
                    continue

            return messages
        except Exception as e:
            print(f"[ChatSessionService] 메시지 조회 실패: session_id={session_id}, error={e}")
            return []

    def clear_session(self, session_id: str) -> bool:
        """
        세션의 대화 이력 삭제
        
        Args:
            session_id: 세션 ID
            
        Returns:
            bool: 삭제 성공 여부
        """
        if not self.redis_client:
            return False

        try:
            key = f"{self.session_key_prefix}{session_id}"
            self.redis_client.delete(key)
            return True
        except Exception as e:
            print(f"[ChatSessionService] 세션 삭제 실패: session_id={session_id}, error={e}")
            return False

    def is_available(self) -> bool:
        """
        Redis 연결 가능 여부 확인
        
        Returns:
            bool: Redis 사용 가능 여부
        """
        if not self.redis_client:
            return False

        try:
            self.redis_client.ping()
            return True
        except Exception:
            return False


__all__ = ["ChatSessionService"]
