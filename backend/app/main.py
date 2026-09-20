"""
FastAPI 메인 애플리케이션 진입점

이 모듈은 Gjallar 백엔드 서버의 핵심 엔트리포인트입니다.
- CORS 설정을 통해 프론트엔드와 통신
- PRD v1 MVP `/api/v1` 라우트 등록
"""

import os
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

# 환경 변수 로드 (.env 파일에서)
# proxmox_service.py에서도 로드하지만, 다른 서비스들을 위해 여기서도 로드
project_root = Path(__file__).resolve().parent.parent.parent
env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path, override=False)

from app.api.v1.router import router as api_v1_router
from app.api.v1.vm_console import websocket_router as console_websocket_router
from app.auth.admin_api import router as admin_router
from app.auth.api import router as auth_router
from app.auth.config import allowed_origins
from app.auth.origin import reject_unexpected_unsafe_origin
from app.console.log_safety import install_console_log_filter
from app.operations.recovery.runtime import RecoveryRuntimeConfig, run_recovery_loop


@asynccontextmanager
async def _application_lifespan(_app: FastAPI):
    install_console_log_filter()
    config = RecoveryRuntimeConfig.from_env()
    stop_event = asyncio.Event()
    task = asyncio.create_task(run_recovery_loop(stop_event, config=config)) if config.enabled else None
    try:
        yield
    finally:
        if task is not None:
            stop_event.set()
            try:
                await asyncio.wait_for(task, timeout=min(config.poll_seconds + 5, 30))
            except TimeoutError:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

# FastAPI 애플리케이션 인스턴스 생성
app = FastAPI(
    title="Gjallar VM Operations API",
    description="Proxmox VM 운영, inventory, monitoring을 위한 Gjallar 백엔드",
    version="1.0.0",
    lifespan=_application_lifespan,
)

# CORS 설정: 프론트엔드로부터의 요청 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(allowed_origins()),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.middleware("http")(reject_unexpected_unsafe_origin)

# API 라우트 등록
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(api_v1_router)
app.include_router(console_websocket_router)
# PRD v1 MVP exposes only the explicit /api/v1 operator surface.

FRONTEND_DIST_ENV = "GJALLAR_FRONTEND_DIST"
RESERVED_FRONTEND_PREFIXES = {"api", "assets", "docs", "health", "openapi.json", "redoc"}


def _configured_frontend_dist() -> Path | None:
    raw_path = os.environ.get(FRONTEND_DIST_ENV)
    if not raw_path:
        return None
    dist = Path(raw_path).expanduser().resolve()
    if not (dist / "index.html").is_file():
        return None
    return dist


def _is_file_like_path(path: str) -> bool:
    return "." in PurePosixPath(path).name


def _is_reserved_frontend_path(path: str) -> bool:
    stripped = path.strip("/")
    if not stripped:
        return False
    first_segment = stripped.split("/", 1)[0]
    return first_segment in RESERVED_FRONTEND_PREFIXES


def _dist_file_response(dist: Path, relative_path: str) -> FileResponse | None:
    root = dist.resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return FileResponse(candidate)


def _frontend_index_response(dist: Path) -> FileResponse:
    return FileResponse(dist / "index.html")


@app.get("/")
async def root():
    """Return backend root JSON or the built frontend index."""
    frontend_dist = _configured_frontend_dist()
    if frontend_dist is not None:
        return _frontend_index_response(frontend_dist)
    return {"message": "Gjallar VM Operations API", "status": "running"}


@app.get("/health")
async def health():
    """상세 헬스체크 엔드포인트"""
    return {"status": "healthy", "service": "backend"}


@app.get("/assets/{asset_path:path}", include_in_schema=False)
async def frontend_asset(asset_path: str):
    frontend_dist = _configured_frontend_dist()
    if frontend_dist is None:
        raise HTTPException(status_code=404)
    response = _dist_file_response(frontend_dist / "assets", asset_path)
    if response is None:
        raise HTTPException(status_code=404)
    return response


@app.get("/{frontend_path:path}", include_in_schema=False)
async def frontend_route(frontend_path: str):
    frontend_dist = _configured_frontend_dist()
    if frontend_dist is None or _is_reserved_frontend_path(frontend_path):
        raise HTTPException(status_code=404)

    if _is_file_like_path(frontend_path):
        response = _dist_file_response(frontend_dist, frontend_path)
        if response is not None:
            return response
        raise HTTPException(status_code=404)

    return _frontend_index_response(frontend_dist)
