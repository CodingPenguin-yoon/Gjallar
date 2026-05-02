"""
간단한 Gemini LLM 호출 테스트 스크립트

배경/의도/목적:
- 현재 백엔드 LLMService 경로에서 429(쿼터 초과) 에러가 발생하고 있음
- 최상위 Test 폴더에서 독립된 최소 호출을 수행해:
  - 환경변수(GEMINI_API_KEY, GEMINI_MODEL_NAME)가 제대로 읽히는지
  - 실제 응답/에러 메시지를 간단히 확인할 수 있게 함

사용 방법:
1) 프로젝트 루트에서 venv 생성 및 활성화 (사용자 규칙 반영)
   python -m venv venv
   source venv/bin/activate  # macOS/Linux

2) 필요한 패키지 설치 (requests, python-dotenv)
   pip install requests python-dotenv

3) .env 파일에 다음 값이 설정되어 있어야 함
   GEMINI_API_KEY=your_key
   GEMINI_MODEL_NAME=gemini-2.0-flash  # 또는 사용 중인 모델명

4) 테스트 실행
   python Test/llm_test.py "현재 VM들 상태를 요약해줘"
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv


def load_env() -> None:
  """
  프로젝트 루트의 .env 파일을 로드.
  - 비즈니스 로직이 아니라 테스트용이지만, 운영 코드와 동일한 방식으로 env를 읽도록 맞춘다.
  """
  project_root = Path(__file__).resolve().parent.parent
  env_path = project_root / ".env"
  if env_path.exists():
    load_dotenv(env_path, override=True)
  else:
    print(f"[WARN] .env 파일을 찾지 못했습니다: {env_path}")


def build_payload(user_content: str, model_name: str) -> dict:
  """
  Gemini generateContent 호출용 최소 payload 생성.
  - 시스템 메시지를 따로 두지 않고, 단일 user 메시지만 사용 (쿼터 최소화 목적).
  - 실제 백엔드 LLMService는 더 풍부한 컨텍스트를 사용.
  """
  system_prompt = (
    "당신은 Proxmox / Terraform / Ansible 기반 인프라를 도와주는 어시스턴트입니다. "
    "자연어 요청에 대해 짧고 간단하게 한국어로 응답하세요."
  )

  # Gemini v1beta는 role로 user / model 만 허용하므로
  # 시스템 지침 + 유저 메시지를 하나의 user 메시지로 합친다.
  combined = f"{system_prompt}\n\n[사용자 요청]\n{user_content}"

  return {
    "contents": [
      {
        "role": "user",
        "parts": [{"text": combined}],
      }
    ]
  }


def call_gemini(message: str) -> None:
  """
  Gemini generateContent API를 한 번 호출하고, 응답/에러를 그대로 출력.

  - 429(쿼터 초과) 등 에러 코드를 명확히 보여주는 것이 목적.
  """
  load_env()

  api_key = os.getenv("GEMINI_API_KEY", "").strip()
  model_name = os.getenv("GEMINI_MODEL_NAME", "gemini-2.0-flash").strip()

  if not api_key:
    print("[ERROR] GEMINI_API_KEY가 설정되어 있지 않습니다. .env 파일을 확인하세요.")
    return

  base_url = "https://generativelanguage.googleapis.com/v1beta/models"
  url = f"{base_url}/{model_name}:generateContent"

  payload = build_payload(message, model_name=model_name)

  print("=== Gemini LLM 호출 테스트 ===")
  print(f"- Model    : {model_name}")
  print(f"- Endpoint: {url}")

  try:
    response = requests.post(
      url,
      params={"key": api_key},
      headers={"Content-Type": "application/json; charset=utf-8"},
      data=json.dumps(payload, ensure_ascii=False),
      timeout=20,
    )
  except requests.RequestException as e:
    print(f"[ERROR] 네트워크/요청 예외 발생: {e}")
    return

  print(f"- HTTP Status: {response.status_code}")

  # 본문 그대로 찍어서 쿼터/인증 문제 등을 바로 확인
  try:
    body = response.json()
    print("=== Response JSON ===")
    print(json.dumps(body, ensure_ascii=False, indent=2))
  except ValueError:
    print("=== Raw Response Text ===")
    print(response.text)


if __name__ == "__main__":
  # CLI 인자로 메시지를 받지 않으면 기본 프롬프트 사용
  if len(sys.argv) > 1:
    user_msg = " ".join(sys.argv[1:])
  else:
    user_msg = "현재 VM 상태를 한 문장으로 요약해줘."

  call_gemini(user_msg)

