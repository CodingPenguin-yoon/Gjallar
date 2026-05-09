"""배포 작업 상태/로그 조회 API 라우트 (task 도메인)."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.shared.tasks import task_manager


router = APIRouter()


class StatusResponse(BaseModel):
    """상태 응답 모델"""

    task_id: str
    status: str
    progress: float = 0
    progress_text: str = ""
    progress_source: str = ""
    archived: bool = False
    archived_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class LogsResponse(BaseModel):
    """로그 응답 모델"""

    task_id: str
    logs: List[str]
    total_lines: int


class TaskSummaryResponse(BaseModel):
    """작업 요약 응답 모델"""

    task_id: str
    status: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    progress: float = 0
    progress_text: str = ""
    progress_source: str = ""
    archived: bool = False
    archived_at: Optional[str] = None
    total_logs: int = 0
    last_log: Optional[str] = None


class TaskListResponse(BaseModel):
    """작업 목록 응답 모델"""

    tasks: List[TaskSummaryResponse]
    total: int


class TaskDetailResponse(BaseModel):
    """작업 상세 응답 모델"""

    task_id: str
    status: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    progress: float = 0
    progress_text: str = ""
    progress_source: str = ""
    archived: bool = False
    archived_at: Optional[str] = None
    logs: List[str] = Field(default_factory=list)
    total_logs: int = 0
    last_log: Optional[str] = None


class ArchiveTaskRequest(BaseModel):
    """작업 아카이브 토글 요청 모델"""

    archived: bool = True


@router.get("/status/{task_id}", response_model=StatusResponse)
async def get_status(task_id: str):
    """
    배포 작업 상태 조회
    """
    task_info = task_manager.get_status(task_id)

    if task_info is None:
        raise HTTPException(
            status_code=404,
            detail=f"작업을 찾을 수 없습니다: {task_id}",
        )

    return StatusResponse(
        task_id=task_id,
        status=task_info["status"],
        progress=float(task_info.get("progress", 0)),
        progress_text=task_info.get("progress_text", ""),
        progress_source=task_info.get("progress_source", ""),
        archived=bool(task_info.get("archived", False)),
        archived_at=task_info.get("archived_at"),
        created_at=task_info.get("created_at"),
        updated_at=task_info.get("updated_at"),
    )


@router.get("/logs/{task_id}", response_model=LogsResponse)
async def get_logs(task_id: str):
    """
    배포 작업 로그 조회
    """
    task_info = task_manager.get_status(task_id)
    if task_info is None:
        raise HTTPException(
            status_code=404,
            detail=f"작업을 찾을 수 없습니다: {task_id}",
        )

    logs = task_manager.get_logs(task_id)

    return LogsResponse(
        task_id=task_id,
        logs=logs,
        total_lines=len(logs),
    )


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(
    limit: int = Query(default=100, ge=1, le=1000),
    status: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    include_archived: bool = Query(default=False),
):
    """
    작업 목록 조회 (최신순)
    """
    tasks = task_manager.list_tasks(
        limit=limit,
        status=status,
        q=q,
        date_from=date_from,
        date_to=date_to,
        include_archived=include_archived,
    )
    return TaskListResponse(tasks=tasks, total=len(tasks))


@router.get("/tasks/stream")
async def stream_tasks(
    request: Request,
    include_archived: bool = Query(default=False),
    last_event_id: Optional[int] = Query(default=None),
):
    """
    작업 이벤트 스트림 (SSE)
    """
    start_seq = 0
    if last_event_id is not None:
        start_seq = max(0, int(last_event_id))
    else:
        header_seq = request.headers.get("last-event-id", "")
        if header_seq:
            try:
                start_seq = max(0, int(header_seq))
            except ValueError:
                start_seq = 0

    async def event_generator():
        current_seq = start_seq
        keepalive_seconds = 15.0

        while True:
            if await request.is_disconnected():
                break

            await asyncio.to_thread(task_manager.wait_for_updates, current_seq, keepalive_seconds)
            events = task_manager.get_events_since(
                current_seq,
                include_archived=include_archived,
                limit=500,
            )

            if not events:
                yield ": keepalive\n\n"
                continue

            for event in events:
                seq = int(event.get("seq", current_seq))
                current_seq = max(current_seq, seq)
                payload = json.dumps(event, ensure_ascii=False)
                yield f"id: {current_seq}\nevent: task\ndata: {payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/tasks/{task_id}/archive", response_model=TaskDetailResponse)
async def archive_task(task_id: str, request: ArchiveTaskRequest):
    """
    작업 아카이브 상태 변경
    """
    task_detail = task_manager.archive_task(task_id, archived=request.archived)
    if task_detail is None:
        raise HTTPException(
            status_code=404,
            detail=f"작업을 찾을 수 없습니다: {task_id}",
        )
    return TaskDetailResponse(**task_detail)


@router.get("/tasks/{task_id}", response_model=TaskDetailResponse)
async def get_task_detail(task_id: str):
    """
    작업 상세 조회 (메타데이터 + 전체 로그 포함)
    """
    task_detail = task_manager.get_task_detail(task_id)
    if task_detail is None:
        raise HTTPException(
            status_code=404,
            detail=f"작업을 찾을 수 없습니다: {task_id}",
        )
    return TaskDetailResponse(**task_detail)


__all__ = ["router"]
