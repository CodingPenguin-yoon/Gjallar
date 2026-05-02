"""LLM (Gemini) 연동 서비스 코어 모듈."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 환경 변수 로드
# ---------------------------------------------------------------------------
# __file__ = backend/app/domains/llm/llm_core.py
# parent x5 = terraform_ansible (프로젝트 루트)
project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)


class LLMMessage(BaseModel):
    """LLM 대화용 메시지 모델"""

    role: str = Field(description="메시지 역할 (user / assistant / system)")
    content: str = Field(description="메시지 텍스트 내용")


class LLMActionDict(BaseModel):
    """LLM이 제안하는 인프라 액션의 JSON 표현"""

    type: str = Field(description="액션 타입 (예: list_vms, create_vm 등)")
    description: Optional[str] = Field(
        default=None,
        description="사용자에게 보여줄 자연어 설명 (선택)",
    )
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="액션 실행에 필요한 파라미터 딕셔너리",
    )


class LLMChatResult(BaseModel):
    """Gemini 응답을 정규화한 결과 모델"""

    assistant_message: str = Field(description="어시스턴트 자연어 응답 메시지")
    actions: List[LLMActionDict] = Field(
        default_factory=list, description="제안된 인프라 액션 목록"
    )
    raw_text: str = Field(description="LLM 원본 텍스트 응답")


@dataclass
class LLMConfig:
    """LLM/Gemini 관련 설정 값"""

    api_key: str
    model_name: str = "gemini-2.0-flash"
    timeout_seconds: int = 30


class LLMService:
    """Gemini API 호출을 담당하는 서비스 클래스"""

    def __init__(self) -> None:
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        model_name = os.getenv("GEMINI_MODEL_NAME", "gemini-2.0-flash").strip()
        timeout_str = os.getenv("GEMINI_TIMEOUT_SECONDS", "30").strip()

        try:
            timeout_seconds = int(timeout_str)
        except ValueError:
            timeout_seconds = 30

        self.config = LLMConfig(
            api_key=api_key,
            model_name=model_name or "gemini-2.0-flash",
            timeout_seconds=timeout_seconds,
        )

        if not self.config.api_key:
            print("[LLMService] 경고: GEMINI_API_KEY가 설정되지 않았습니다.")

        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models"

    # ------------------------------------------------------------------
    # 내부 유틸리티
    # ------------------------------------------------------------------
    def _build_system_prompt(self, extra_context: Optional[Dict[str, Any]] = None) -> str:
        context_text = ""
        if extra_context:
            try:
                context_text = json.dumps(extra_context, ensure_ascii=False)
            except Exception:
                context_text = str(extra_context)

        base_prompt = """
당신은 Proxmox / Terraform / Ansible 기반으로 동작하는 인프라 ChatOps 도우미입니다.

- 사용자의 자연어 요청을 이해하여, 가상머신(VM) 조회/생성/상세 확인 등의 작업을 도와줍니다.
- 실제 인프라 변경(생성/삭제/수정)은 직접 수행하지 않고, 반드시 actions 배열에 "제안"만 합니다.
- 프론트엔드가 사용자의 확인을 받은 뒤 /api/llm/execute-action 으로 액션을 실행합니다.

[응답 형식]
반드시 아래 JSON 형식으로만 응답하세요:
{
  "assistant_message": "사용자에게 보여줄 자연어 설명",
  "actions": [
    {
      "type": "list_vms | list_nodes | get_vm_detail | create_vm | list_templates | list_storages | list_networks",
      "description": "이 액션이 수행하는 일을 자연어로 한 줄 요약",
      "params": {
        "server_name": "예시-이름",
        "server_id": "노드/호스트 ID 또는 Proxmox 노드 이름",
        "template_id": "node/vmid 형식 템플릿 ID (템플릿 기반 생성 시)",
        "cpu_cores": 4,
        "memory_gb": 8,
        "disk_size_gb": 50,
        "storage_id": "local-lvm",
        "network_ids": ["vmbr0"]
      }
    }
  ]
}

- JSON 이외의 텍스트(설명 문장 등)는 assistant_message 안에만 넣어야 합니다.
- JSON 전체는 하나의 유효한 객체여야 하며, 주석이나 추가 문자열을 포함하면 안 됩니다.

[VM 생성(create_vm) 시 동작 규칙]
1) 사용자가 "VM 만들어줘", "Ubuntu 하나 대충" 같이 모호하게 요청하면,
   곧바로 create_vm 액션을 생성하지 말고 다음 정보를 차례대로 물어보세요.
   - 어느 Proxmox 노드(서버)에 만들지 (필요 시 list_nodes 액션으로 후보를 보여줍니다)
   - 어떤 템플릿(template_id)으로 클론할지
     (필요 시 list_templates 액션으로 후보를 보여줍니다)
   - CPU 코어 수(cpu_cores), 메모리 용량(memory_gb), 디스크 용량(disk_size_gb)
   - 어느 스토리지(storage_id)에 둘지 (필요 시 list_storages 액션으로 후보를 보여줍니다)
   - 어느 네트워크 브리지들(network_ids)에 연결할지 (필요 시 list_networks 액션으로 후보를 보여줍니다)

2) 위 필수 파라미터들이 모두 명확해지기 전까지는
   - actions 배열에는 create_vm 대신 list_* 형태의 보조 조회 액션들만 넣어
     사용자가 선택할 수 있는 옵션을 보여주도록 합니다.

   특히 아래 규칙을 지킵니다.
   - "어느 노드에 만들까요?" 라고 물을 때에는,
     actions 배열에 반드시 하나의 list_nodes 액션을 포함합니다.
       예: { "type": "list_nodes", "description": "선택 가능한 Proxmox 노드 목록 조회", "params": {} }
   - "어떤 템플릿을 사용할까요?" 라고 물을 때에는,
     actions 배열에 반드시 하나의 list_templates 액션을 포함합니다.
   - "어느 스토리지에 둘까요?" 라고 물을 때에는,
     actions 배열에 반드시 하나의 list_storages 액션을 포함합니다.
   - "어느 네트워크(브리지)에 연결할까요?" 라고 물을 때에는,
     actions 배열에 반드시 하나의 list_networks 액션을 포함합니다.

3) 필수 파라미터가 모두 결정된 뒤에만
   - actions 배열에 단일 create_vm 액션을 넣고,
   - assistant_message 에서는 "이 설정으로 VM을 생성해도 될지"를 한국어로 요약해 다시 확인합니다.
   (예: "노드 pve1, 템플릿 ubuntu-22.04, CPU 4, 메모리 8GB, 디스크 50GB, 스토리지 local-lvm, 네트워크 vmbr0 로 VM을 만들까요?")

4) create_vm 액션의 params 에는 백엔드에서 사용하는 키 이름을 그대로 사용합니다:
   - server_name (선택)
   - server_id (또는 node 이름)
   - template_id
   - cpu_cores, memory_gb, disk_size_gb, storage_id, network_ids

""".strip()

        if context_text:
            base_prompt += "\n\n[현재 인프라 컨텍스트]\n" + context_text

        return base_prompt

    def _build_gemini_payload(
        self,
        messages: List[LLMMessage],
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        system_prompt = self._build_system_prompt(extra_context=extra_context)

        contents: List[Dict[str, Any]] = []

        contents.append(
            {
                "role": "user",
                "parts": [{"text": system_prompt}],
            }
        )

        for msg in messages:
            if msg.role == "user":
                gemini_role = "user"
            else:
                gemini_role = "model"

            contents.append(
                {
                    "role": gemini_role,
                    "parts": [{"text": msg.content}],
                }
            )

        return {"contents": contents}

    def _parse_llm_text(self, text: str) -> LLMChatResult:
        original_text = text
        text = text.strip()
        if not text:
            return LLMChatResult(
                assistant_message="LLM 응답이 비어 있습니다. 나중에 다시 시도해 주세요.",
                actions=[],
                raw_text=original_text,
            )

        # 1차: 응답 전체가 코드블록(```json ... ```)인 경우 코드블록 안만 추출
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        # 2차: 본문 어딘가에 ```json ... ``` 코드블록이 섞여 있는 경우,
        #      코드블록 안의 JSON 부분만 떼어내서 파싱을 시도한다.
        if "```" in text:
            parts = text.split("```")
            # 짝수 인덱스: 코드블록 밖 텍스트, 홀수 인덱스: 코드블록 안
            # 일반적으로 첫 번째 코드블록(인덱스 1)을 우선 사용
            for idx, block in enumerate(parts):
                if idx % 2 == 1:  # 코드블록 내용
                    # "json\n{ ... }" 형태일 수 있으므로, 첫 줄이 언어 태그면 제거
                    block_lines = block.splitlines()
                    if block_lines and block_lines[0].strip().lower().startswith("json"):
                        block_lines = block_lines[1:]
                    candidate = "\n".join(block_lines).strip()
                    if candidate:
                        text = candidate
                        break

        # 3차: JSON 파싱 시도
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # 4차: 텍스트 안에서 첫 { 와 마지막 } 사이를 잘라 JSON 파싱 재시도
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                inner = text[start : end + 1]
                try:
                    data = json.loads(inner)
                    text = inner
                except json.JSONDecodeError:
                    return LLMChatResult(
                        assistant_message=original_text.strip(),
                        actions=[],
                        raw_text=original_text,
                    )
            else:
                return LLMChatResult(
                    assistant_message=original_text.strip(),
                    actions=[],
                    raw_text=original_text,
                )

        assistant_message = str(data.get("assistant_message", "")).strip() or text
        raw_actions = data.get("actions", []) or []

        actions: List[LLMActionDict] = []
        if isinstance(raw_actions, list):
            for item in raw_actions:
                if not isinstance(item, dict):
                    continue
                try:
                    actions.append(LLMActionDict(**item))
                except Exception:
                    continue

        return LLMChatResult(
            assistant_message=assistant_message,
            actions=actions,
            raw_text=text,
        )

    # ------------------------------------------------------------------
    # 공개 메서드
    # ------------------------------------------------------------------
    def chat(
        self,
        messages: List[LLMMessage],
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> LLMChatResult:
        if not self.config.api_key:
            raise RuntimeError("GEMINI_API_KEY가 설정되지 않아 LLM 호출을 수행할 수 없습니다.")

        url = f"{self.base_url}/{self.config.model_name}:generateContent"
        payload = self._build_gemini_payload(messages=messages, extra_context=extra_context)

        params = {
            "key": self.config.api_key,
        }

        try:
            # json 파라미터를 사용하여 자동으로 JSON 직렬화 및 Content-Type 헤더 설정
            # ensure_ascii=False는 json.dumps()에서만 사용 가능하므로, 
            # requests의 json 파라미터는 기본적으로 UTF-8을 지원합니다.
            response = requests.post(
                url,
                params=params,
                json=payload,
                timeout=self.config.timeout_seconds,
            )
        except requests.RequestException as e:
            raise RuntimeError(f"Gemini API 호출 중 네트워크 예외 발생: {str(e)}") from e

        if not response.ok:
            raise RuntimeError(
                f"Gemini API 응답 오류: status={response.status_code}, body={response.text[:500]}"
            )

        try:
            data = response.json()
        except ValueError as e:
            raise RuntimeError(f"Gemini API 응답 JSON 파싱 실패: {str(e)}") from e

        try:
            candidates = data.get("candidates", [])
            if not candidates:
                raise KeyError("candidates 가 비어 있습니다.")

            content = candidates[0].get("content") or {}
            parts = content.get("parts") or []
            if not parts or "text" not in parts[0]:
                raise KeyError("content.parts[0].text 를 찾을 수 없습니다.")

            text = str(parts[0]["text"])
        except Exception as e:
            raise RuntimeError(f"Gemini API 응답에서 텍스트를 추출하지 못했습니다: {str(e)}") from e

        return self._parse_llm_text(text)


__all__ = [
    "LLMService",
    "LLMMessage",
    "LLMActionDict",
    "LLMChatResult",
    "LLMConfig",
]
