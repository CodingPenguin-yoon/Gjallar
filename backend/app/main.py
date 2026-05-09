"""
FastAPI 메인 애플리케이션 진입점

이 모듈은 Gjallar 백엔드 서버의 핵심 엔트리포인트입니다.
- CORS 설정을 통해 프론트엔드와 통신
- PRD v1 MVP `/api/v1` 라우트 등록
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.router import router as api_v1_router

# 환경 변수 로드 (.env 파일에서)
# proxmox_service.py에서도 로드하지만, 다른 서비스들을 위해 여기서도 로드
project_root = Path(__file__).resolve().parent.parent.parent
env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)

# FastAPI 애플리케이션 인스턴스 생성
app = FastAPI(
    title="Gjallar VM Operations API",
    description="Proxmox VM 운영, inventory, monitoring을 위한 Gjallar 백엔드",
    version="1.0.0"
)

# CORS 설정: 프론트엔드로부터의 요청 허용
frontend_port = os.getenv("FRONTEND_PORT", "5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://localhost:{frontend_port}",
        f"http://127.0.0.1:{frontend_port}",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 라우트 등록
app.include_router(api_v1_router)
# PRD v1 MVP에서는 legacy deploy/provision/proxmox mutation/LLM 라우터를 노출하지 않는다.


@app.get("/")
async def root():
    """헬스체크 엔드포인트"""
    return {"message": "Gjallar VM Operations API", "status": "running"}


@app.get("/health")
async def health():
    """상세 헬스체크 엔드포인트"""
    return {"status": "healthy", "service": "backend"}
