from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """프론트엔드에서 전달하는 단일 채팅 메시지 모델"""

    role: str = Field(description="메시지 역할 (user | assistant)")
    content: str = Field(description="메시지 내용")


class ChatRequest(BaseModel):
    """
    LLM 채팅 요청 모델

    - session_id: 채팅 세션 ID (선택적, 없으면 새로 생성)
    - messages: 기존 대화 이력 (system 제외, session_id가 있으면 무시됨)
    - latest_message: 이번에 새로 보낸 사용자 메시지(선택)
    - context: 선택적 인프라 컨텍스트 (예: 현재 선택된 클러스터/프로젝트 정보)
    """

    session_id: Optional[str] = Field(
        default=None,
        description="채팅 세션 ID (Redis에 저장된 대화 이력을 조회하기 위해 사용)",
    )
    messages: List[ChatMessage] = Field(
        default_factory=list,
        description="기존 대화 이력 (session_id가 없을 때만 사용, session_id가 있으면 Redis에서 조회)",
    )
    latest_message: Optional[ChatMessage] = Field(
        default=None,
        description="이번 요청에서 새로 보낸 메시지 (일반적으로 role=user)",
    )
    context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="선택적 인프라 컨텍스트 정보 (노드/VM 요약 등)",
    )


class ChatResponse(BaseModel):
    """LLM 채팅 응답 모델

    - session_id: 채팅 세션 ID (Redis에 대화 이력이 저장됨)
    - assistant_message: 자연어 응답
    - actions: 제안된 액션 목록
    - data: 일부 조회 액션(list_vms, list_nodes 등)을 자동 실행한 결과 JSON
    """

    session_id: str = Field(description="채팅 세션 ID (다음 요청 시 이 ID를 사용하여 대화 이력 유지)")
    assistant_message: str = Field(description="어시스턴트 자연어 응답")
    actions: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="LLM이 제안한 인프라 액션 목록 (type/description/params 포함)",
    )
    data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="자동 실행된 조회 액션 결과 (예: {'vms': [...], 'nodes': [...]})",
    )


class ExecuteActionRequest(BaseModel):
    """
    인프라 액션 실행 요청 모델

    프론트엔드는 /api/llm/chat 응답의 actions 중 하나를 그대로 넘겨주면 됩니다.
    """

    action: Dict[str, Any] = Field(
        description="실행할 액션 객체 (type, description, params 포함)",
    )


class ExecuteActionResponse(BaseModel):
    """인프라 액션 실행 응답 모델"""

    result_message: str = Field(description="사용자에게 보여줄 결과 메시지")
    raw_result: Any = Field(
        default=None,
        description="원본 결과 데이터 (디버깅/추가 표시용)",
    )


__all__ = [
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "ExecuteActionRequest",
    "ExecuteActionResponse",
]
