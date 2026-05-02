"""
LLM 기반 인프라 어시스턴트 API 라우트 (llm 도메인)

이 모듈은 자연어 채팅을 처리하고, LLM이 제안한 인프라 액션을
실제 Proxmox / Terraform / Ansible 서비스로 연결하는 엔드포인트를 제공합니다.

엔드포인트:
- POST /api/llm/chat
    - 사용자 메시지 + 대화 이력을 받아 Gemini LLM을 호출
    - assistant_message + actions(JSON) 을 반환
- POST /api/llm/execute-action
    - 사용자가 선택/확인한 단일 액션을 실제 인프라 서비스에 매핑하여 실행
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.domains.llm.commands.chat_session import ChatSessionService
from app.domains.llm.commands.infra_action import (
    InfraAction,
    InfraActionResult,
    InfraActionService,
)
from app.domains.llm.service import LLMMessage, LLMService
from .schemas import (
    ChatRequest,
    ChatResponse,
    ExecuteActionRequest,
    ExecuteActionResponse,
)


router = APIRouter()

# 서비스 인스턴스는 모듈 레벨에서 생성하여 재사용
llm_service = LLMService()
infra_action_service = InfraActionService()
chat_session_service = ChatSessionService()


@router.post("/llm/chat", response_model=ChatResponse)
async def llm_chat(request: ChatRequest) -> ChatResponse:
    """
    LLM 채팅 엔드포인트

    - 자연어 질의와 기존 대화 이력을 전달하여 Gemini LLM 응답을 생성합니다.
    - session_id가 제공되면 Redis에서 대화 이력을 조회하고, 없으면 새 세션을 생성합니다.
    - 응답에는 assistant_message 와 함께 actions 리스트가 포함될 수 있습니다.
    - 대화 이력은 Redis에 자동 저장되어 페이지 새로고침 후에도 유지됩니다.
    """
    try:
        # 세션 ID 처리: 없으면 새로 생성, 있으면 Redis에서 이력 조회
        session_id = request.session_id
        if not session_id:
            session_id = chat_session_service.create_session()

        # 대화 이력 조회: session_id가 있으면 Redis에서, 없으면 request.messages 사용
        if chat_session_service.is_available() and session_id:
            # Redis에서 대화 이력 조회
            stored_messages = chat_session_service.get_messages(session_id)
            if stored_messages:
                # Redis에 저장된 메시지를 LLMMessage로 변환
                all_messages: List[LLMMessage] = [
                    LLMMessage(role=msg.get("role", "user"), content=msg.get("content", ""))
                    for msg in stored_messages
                ]
            else:
                # Redis에 이력이 없으면 request.messages 사용 (하위 호환성)
                all_messages = [
                    LLMMessage(role=m.role, content=m.content) for m in request.messages
                ]
        else:
            # Redis 사용 불가 시 request.messages 사용
            all_messages = [
                LLMMessage(role=m.role, content=m.content) for m in request.messages
            ]

        # latest_message 추가
        user_message_content = None
        if request.latest_message is not None:
            user_message_content = request.latest_message.content
            all_messages.append(
                LLMMessage(
                    role=request.latest_message.role,
                    content=request.latest_message.content,
                )
            )

        # Gemini LLM 호출
        result = llm_service.chat(
            messages=all_messages,
            extra_context=request.context,
        )

        # actions 는 그대로 dict 로 직렬화하여 프론트로 전달
        actions_as_dicts: List[Dict[str, Any]] = [
            {
                "type": a.type,
                "description": a.description,
                "params": a.params,
            }
            for a in result.actions
        ]

        assistant_message = result.assistant_message

        # ------------------------------------------------------------------
        # 조회(read-only) 액션은 서버에서 한 번 자동 실행하여
        # - assistant_message 뒤에 요약을 붙이고
        # - data 필드에 JSON(raw_result)로 포함시킨다.
        #
        # VM 생성 질의응답(슬롯 채우기)을 위해 추가된 보조 액션들도
        # 여기서 자동 실행하여 템플릿/스토리지/네트워크 옵션을
        # LLM 응답과 함께 프론트로 전달한다.
        # ------------------------------------------------------------------
        SAFE_AUTO_ACTION_TYPES = {
            "list_vms",
            "list_nodes",
            "get_vm_detail",
            "list_templates",
            "list_storages",
            "list_networks",
        }
        aggregated_data: Dict[str, Any] = {}
        vm_node_filter: Optional[str] = None

        for action_dict in actions_as_dicts:
            action_type = action_dict.get("type")
            if action_type not in SAFE_AUTO_ACTION_TYPES:
                continue

            try:
                action_model = InfraAction(
                    type=action_type,
                    description=action_dict.get("description"),
                    params=action_dict.get("params") or {},
                )

                # list_vms 액션에 특정 노드 파라미터가 지정된 경우(node/server_id/server_name),
                # 프론트엔드에서 해당 노드만 필터링해서 보여줄 수 있도록
                # 별도의 vm_node_filter 메타데이터로 저장한다.
                if action_type == "list_vms":
                    params = action_dict.get("params") or {}
                    # LLM 프롬프트에서는 Proxmox 노드를 server_id/server_name 으로
                    # 넘길 수 있으므로, 세 필드를 모두 확인하여 우선순위로 선택한다.
                    node_value = (
                        params.get("node")
                        or params.get("server_id")
                        or params.get("server_name")
                    )
                    if isinstance(node_value, str) and node_value.strip():
                        vm_node_filter = node_value.strip()

                exec_result: InfraActionResult = infra_action_service.execute_action(
                    action=action_model,
                    background_tasks=None,
                )
                # raw_result 를 data 필드에 병합 (vms, nodes, templates 등)
                if isinstance(exec_result.raw_result, dict):
                    for key, value in exec_result.raw_result.items():
                        aggregated_data[key] = value
            except Exception as e:
                # 조회 액션 자동 실행 실패는 치명적이지 않으므로, 로그만 남기고 계속 진행
                print(f"[LLM Chat] 조회 액션 자동 실행 실패: type={action_type}, error={e}")

        # 특정 노드에 대한 VM 조회(list_vms with node)가 있었다면,
        # data에 vm_node_filter 메타데이터를 추가하여 프론트엔드가 해당 노드만
        # 필터링해 표시할 수 있도록 한다.
        if vm_node_filter:
            aggregated_data["vm_node_filter"] = vm_node_filter

        # Redis에 대화 이력 저장
        if user_message_content:
            chat_session_service.save_message(
                session_id=session_id,
                role="user",
                content=user_message_content,
            )

        # 어시스턴트 응답 저장 (data 포함)
        chat_session_service.save_message(
            session_id=session_id,
            role="assistant",
            content=assistant_message,
            extras={"data": aggregated_data} if aggregated_data else None,
        )

        return ChatResponse(
            session_id=session_id,
            assistant_message=assistant_message,
            actions=actions_as_dicts,
            data=aggregated_data or None,
        )
    except RuntimeError as e:
        # LLM 호출 관련 예외는 500 에러로 전달
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"LLM 채팅 처리 중 예외 발생: {str(e)}",
        )


@router.get("/llm/session/{session_id}/messages")
@router.post("/llm/session/{session_id}/messages")
async def get_session_messages(session_id: str) -> Dict[str, Any]:
    """
    세션의 대화 이력 조회 엔드포인트

    - Redis에 저장된 대화 이력을 조회하여 반환합니다.
    - 프론트엔드에서 페이지 새로고침 후 대화 이력을 복원할 때 사용합니다.
    - 기존 POST 호출도 유지하지만, 프론트엔드 구현과 맞추기 위해 GET도 함께 지원합니다.
    """
    try:
        messages = chat_session_service.get_messages(session_id)
        return {
            "session_id": session_id,
            "messages": messages,
            "count": len(messages),
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"세션 이력 조회 중 예외 발생: {str(e)}",
        )


@router.delete("/llm/session/{session_id}")
async def clear_session(session_id: str) -> Dict[str, Any]:
    """
    세션의 대화 이력 삭제 엔드포인트

    - Redis에 저장된 대화 이력을 삭제합니다.
    """
    try:
        success = chat_session_service.clear_session(session_id)
        return {
            "session_id": session_id,
            "deleted": success,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"세션 삭제 중 예외 발생: {str(e)}",
        )


@router.post("/llm/execute-action", response_model=ExecuteActionResponse)
async def execute_llm_action(
    request: ExecuteActionRequest,
    background_tasks: BackgroundTasks,
) -> ExecuteActionResponse:
    """
    LLM이 제안한 인프라 액션 실행 엔드포인트

    - 프론트엔드는 /api/llm/chat 응답에서 받은 actions 중 하나를 선택하여 action 으로 전달합니다.
    - 이 엔드포인트는 액션 타입/파라미터를 검증한 뒤, 실제 인프라 서비스에 매핑하여 실행합니다.
    """
    try:
        action_dict = request.action or {}

        # 최소한의 유효성 검사 (type 필수)
        action_type_value = action_dict.get("type")
        if not action_type_value:
            raise HTTPException(status_code=400, detail="action.type 필드는 필수입니다.")

        # Pydantic 모델로 변환 (유효하지 않은 필드는 무시)
        action = InfraAction(
            type=action_type_value,  # Enum 타입이므로 여기서 검증
            description=action_dict.get("description"),
            params=action_dict.get("params") or {},
        )

        # 인프라 액션 실행
        result: InfraActionResult = infra_action_service.execute_action(
            action=action,
            background_tasks=background_tasks,
        )

        return ExecuteActionResponse(
            result_message=result.result_message,
            raw_result=result.raw_result,
        )
    except HTTPException:
        # 명시적으로 던진 HTTPException은 그대로 전달
        raise
    except ValueError as e:
        # Enum 변환 실패 등 유효하지 않은 타입
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"인프라 액션 실행 중 예외 발생: {str(e)}",
        )


__all__ = ["router"]
