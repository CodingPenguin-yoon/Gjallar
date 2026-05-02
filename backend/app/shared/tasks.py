"""공용 작업 상태 관리 모듈."""

import logging
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, timedelta
import os
import threading
import time
from pathlib import Path
from copy import deepcopy

from app.shared.platform_db import resolve_platform_state_database_url
from app.shared.task_store import SQLAlchemyTaskStore


logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """작업 상태 열거형"""

    PENDING = "Pending"
    RUNNING = "Running"
    SUCCESS = "Success"
    FAILED = "Failed"


class TaskManager:
    """
    작업 상태 및 로그 관리 싱글톤 클래스

    배포 작업의 상태와 로그를 메모리에 저장하여 API를 통해 조회할 수 있도록 합니다.
    Thread-safe한 구조로 설계되어 동시 요청을 안전하게 처리합니다.
    """

    _instance = None
    _lock = threading.Lock()
    _DONE_STATUSES = {"success", "completed", "failed", "error"}
    _DETAILED_PROGRESS_SOURCES = {"terraform_log", "proxmox_task_log"}

    def __new__(cls):
        """싱글톤 패턴 구현"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(TaskManager, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """초기화: 작업 상태 및 로그 저장소 생성"""
        if getattr(self, "_initialized", False):
            return

        self._tasks: Dict[str, Dict] = {}
        self._logs: Dict[str, List[str]] = {}
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        project_root = Path(__file__).resolve().parents[3]
        self._legacy_storage_path = project_root / "data" / "task_history.json"
        self._database_url = resolve_platform_state_database_url(project_root)
        self._task_store: Optional[SQLAlchemyTaskStore] = SQLAlchemyTaskStore(
            database_url=self._database_url,
            legacy_json_path=self._legacy_storage_path,
        )
        self._event_version = 0
        self._events: List[Dict[str, Any]] = []
        self._max_events = self._read_int_env("TASK_EVENT_BUFFER_SIZE", 5000)
        self._auto_archive_days = self._read_int_env("TASK_AUTO_ARCHIVE_DAYS", 14)
        self._auto_archive_check_interval_seconds = self._read_int_env(
            "TASK_AUTO_ARCHIVE_CHECK_INTERVAL_SECONDS",
            300,
        )
        self._last_auto_archive_check_at = 0.0
        self._load_state()
        self._initialized = True

    def _read_int_env(self, name: str, default: int) -> int:
        raw = os.getenv(name)
        if raw is None:
            return default
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return default

    def _persist_task_safely(self, task_id: str) -> None:
        if self._task_store is None:
            return
        task = self._tasks.get(task_id)
        if task is None:
            return
        try:
            self._task_store.save_task(task_id, task)
        except Exception:
            logger.exception("Failed to persist task state", extra={"task_id": task_id})

    def _persist_task_with_log_safely(self, task_id: str, log_line: str) -> None:
        if self._task_store is None:
            return
        task = self._tasks.get(task_id)
        if task is None:
            return
        try:
            self._task_store.save_task_and_append_log(task_id, task, log_line)
        except Exception:
            logger.exception("Failed to persist task log", extra={"task_id": task_id})

    def _delete_task_safely(self, task_id: str) -> None:
        if self._task_store is None:
            return
        try:
            self._task_store.delete_task(task_id)
        except Exception:
            logger.exception("Failed to delete persisted task state", extra={"task_id": task_id})

    def _normalize_datetime(self, value: Optional[str], *, end_of_day: bool = False) -> Optional[datetime]:
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None

        try:
            if len(text) == 10 and text[4] == "-" and text[7] == "-":
                dt = datetime.fromisoformat(text)
                if end_of_day:
                    dt = dt + timedelta(days=1) - timedelta(microseconds=1)
                return dt

            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                dt = dt.astimezone().replace(tzinfo=None)
            return dt
        except Exception:
            return None

    def _ensure_task_shape_unlocked(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return

        now_iso = datetime.now().isoformat()
        task.setdefault("status", TaskStatus.PENDING.value)
        task.setdefault("created_at", now_iso)
        task.setdefault("updated_at", now_iso)
        task.setdefault("metadata", {})
        task.setdefault("progress", 0.0)
        task.setdefault("progress_text", "")
        task.setdefault("progress_source", "")
        task.setdefault("archived", False)
        task.setdefault("archived_at", None)

        if not isinstance(task.get("metadata"), dict):
            task["metadata"] = {}
        if task_id not in self._logs:
            self._logs[task_id] = []

    def _is_done_status(self, status: Optional[Union[str, TaskStatus]]) -> bool:
        return self._normalize_status(status or "").lower() in self._DONE_STATUSES

    def _build_task_summary_unlocked(self, task_id: str) -> Optional[Dict[str, Any]]:
        task_info = self._tasks.get(task_id)
        if task_info is None:
            return None
        self._ensure_task_shape_unlocked(task_id)
        task_info = self._tasks.get(task_id) or {}
        logs = self._logs.get(task_id, [])

        return {
            "task_id": task_id,
            "status": task_info.get("status"),
            "created_at": task_info.get("created_at"),
            "updated_at": task_info.get("updated_at"),
            "metadata": deepcopy(task_info.get("metadata", {})),
            "progress": float(task_info.get("progress", 0.0)),
            "progress_text": task_info.get("progress_text", ""),
            "progress_source": task_info.get("progress_source", ""),
            "archived": bool(task_info.get("archived", False)),
            "archived_at": task_info.get("archived_at"),
            "total_logs": len(logs),
            "last_log": logs[-1] if logs else None,
        }

    def _build_task_detail_unlocked(self, task_id: str) -> Optional[Dict[str, Any]]:
        summary = self._build_task_summary_unlocked(task_id)
        if summary is None:
            return None

        logs = self._logs.get(task_id, [])
        summary["logs"] = list(logs)
        summary["total_logs"] = len(logs)
        return summary

    def _record_event_unlocked(
        self,
        event_type: str,
        task_id: str,
        *,
        include_summary: bool = True,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._event_version += 1
        event: Dict[str, Any] = {
            "seq": self._event_version,
            "type": str(event_type),
            "task_id": task_id,
            "ts": datetime.now().isoformat(),
        }
        if include_summary:
            event["task"] = self._build_task_summary_unlocked(task_id)
        if extra:
            event.update(extra)

        self._events.append(event)
        overflow = len(self._events) - self._max_events
        if overflow > 0:
            del self._events[:overflow]
        self._condition.notify_all()

    def _run_auto_archive_unlocked(self, *, force: bool = False) -> None:
        if self._auto_archive_days <= 0:
            return

        now_mono = time.monotonic()
        if (
            not force
            and (now_mono - self._last_auto_archive_check_at)
            < self._auto_archive_check_interval_seconds
        ):
            return
        self._last_auto_archive_check_at = now_mono

        cutoff = datetime.now() - timedelta(days=self._auto_archive_days)
        archived_any = False

        for task_id, task in self._tasks.items():
            self._ensure_task_shape_unlocked(task_id)
            if task.get("archived"):
                continue
            if not self._is_done_status(task.get("status")):
                continue

            updated_at = self._normalize_datetime(task.get("updated_at"))
            if updated_at is None:
                updated_at = self._normalize_datetime(task.get("created_at"))
            if updated_at is None:
                continue

            if updated_at <= cutoff:
                task["archived"] = True
                task["archived_at"] = datetime.now().isoformat()
                task["updated_at"] = datetime.now().isoformat()
                archived_any = True
                self._record_event_unlocked("task_auto_archived", task_id)

        if archived_any:
            for task_id, task in self._tasks.items():
                if bool(task.get("archived", False)):
                    self._persist_task_safely(task_id)

    def _load_state(self) -> None:
        """SQLite에 저장된 작업 상태/로그를 로드"""
        try:
            if self._task_store is not None:
                self._tasks, self._logs = self._task_store.load_all()

            for task_id in self._tasks.keys():
                self._logs.setdefault(task_id, [])
                self._ensure_task_shape_unlocked(task_id)
        except Exception:
            logger.exception("Failed to load platform task state from database")
            raise RuntimeError(
                "Failed to load platform task state from database. "
                "Run `cd backend && alembic upgrade head` and retry."
            )

    def _normalize_status(self, status: Union[TaskStatus, str]) -> str:
        """
        상태 값을 문자열로 정규화

        Args:
            status: TaskStatus enum 또는 문자열

        Returns:
            문자열 상태값
        """
        if isinstance(status, TaskStatus):
            return status.value
        return str(status)

    def create_task(self, task_id: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        새로운 작업 생성

        Args:
            task_id: 고유 작업 식별자
            metadata: 작업 메타데이터
        """
        with self._lock:
            now = datetime.now().isoformat()
            self._tasks[task_id] = {
                "status": TaskStatus.PENDING.value,
                "created_at": now,
                "updated_at": now,
                "metadata": metadata or {},
                "progress": 0.0,
                "progress_text": "",
                "progress_source": "",
                "archived": False,
                "archived_at": None,
            }
            self._logs[task_id] = []
            self._record_event_unlocked("task_created", task_id)
            self._persist_task_safely(task_id)

    def update_status(self, task_id: str, status: Union[TaskStatus, str]) -> None:
        """
        작업 상태 업데이트

        Args:
            task_id: 작업 식별자
            status: 새로운 상태
        """
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["status"] = self._normalize_status(status)
                normalized_status = self._normalize_status(status).lower()
                if normalized_status in {"success", "completed"}:
                    self._tasks[task_id]["progress"] = 100.0
                    self._tasks[task_id]["progress_text"] = "Completed"
                self._tasks[task_id]["updated_at"] = datetime.now().isoformat()
                self._record_event_unlocked("task_status_changed", task_id)
                self._run_auto_archive_unlocked()
                self._persist_task_safely(task_id)

    def update_progress(
        self,
        task_id: str,
        progress: float,
        text: Optional[str] = None,
        source: Optional[str] = None,
    ) -> None:
        """
        작업 진행률 업데이트

        Args:
            task_id: 작업 식별자
            progress: 진행률(0~100)
            text: 진행률 보조 텍스트
            source: 진행률 소스(terraform_log / proxmox_task_log 등)
        """
        with self._lock:
            if task_id not in self._tasks:
                return

            clamped = max(0.0, min(100.0, float(progress)))
            current = float(self._tasks[task_id].get("progress", 0.0))
            current_source = str(self._tasks[task_id].get("progress_source", "") or "").strip()
            incoming_source = str(source or "").strip()
            normalized_status = self._normalize_status(
                self._tasks[task_id].get("status", "")
            ).lower()

            if normalized_status not in self._DONE_STATUSES and clamped >= 100.0:
                clamped = 99.0

            # proxmox/terraform 로그 기반 퍼센트는 실제 진행률로 간주하여 그대로 반영한다.
            # 다만 완료 상태(success/failed 등) 이후에는 진행률 역행을 막는다.
            if incoming_source in self._DETAILED_PROGRESS_SOURCES:
                if normalized_status in self._DONE_STATUSES and clamped < current:
                    next_progress = current
                else:
                    next_progress = clamped
            # 상세 소스(terraform/proxmox)가 100%를 찍은 뒤 다음 상위 phase로 넘어갈 때는
            # 이후 단계(예: Ansible) 진행률이 다시 보일 수 있게 phase 값을 허용한다.
            elif (
                incoming_source == "phase"
                and current_source in self._DETAILED_PROGRESS_SOURCES
                and clamped < current
            ):
                if normalized_status not in self._DONE_STATUSES:
                    next_progress = clamped
                else:
                    next_progress = current
            else:
                next_progress = max(current, clamped)

            self._tasks[task_id]["progress"] = round(next_progress, 2)
            if text is not None:
                self._tasks[task_id]["progress_text"] = text
            if source is not None:
                self._tasks[task_id]["progress_source"] = source
            self._tasks[task_id]["updated_at"] = datetime.now().isoformat()
            self._record_event_unlocked("task_progress_changed", task_id)
            self._persist_task_safely(task_id)

    def update_metadata(self, task_id: str, metadata: Dict[str, Any]) -> None:
        """
        작업 메타데이터 업데이트

        Args:
            task_id: 작업 식별자
            metadata: 병합할 메타데이터
        """
        with self._lock:
            if task_id not in self._tasks:
                return
            current_metadata = self._tasks[task_id].get("metadata", {})
            if not isinstance(current_metadata, dict):
                current_metadata = {}
            current_metadata.update(metadata)
            self._tasks[task_id]["metadata"] = current_metadata
            self._tasks[task_id]["updated_at"] = datetime.now().isoformat()
            self._record_event_unlocked("task_metadata_changed", task_id)
            self._persist_task_safely(task_id)

    def get_status(self, task_id: str) -> Optional[Dict]:
        """
        작업 상태 조회

        Args:
            task_id: 작업 식별자

        Returns:
            작업 상태 정보 딕셔너리 또는 None
        """
        with self._lock:
            self._run_auto_archive_unlocked()
            task = self._tasks.get(task_id)
            return deepcopy(task) if task else None

    def _matches_filters_unlocked(
        self,
        summary: Dict[str, Any],
        *,
        status: Optional[str] = None,
        q: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        include_archived: bool = False,
    ) -> bool:
        if not include_archived and bool(summary.get("archived", False)):
            return False

        if status:
            allowed = {
                self._normalize_status(item).lower()
                for item in str(status).split(",")
                if str(item).strip()
            }
            normalized = self._normalize_status(summary.get("status", "")).lower()
            if allowed and normalized not in allowed:
                return False

        if q:
            q_text = str(q).strip().lower()
            metadata = summary.get("metadata") or {}
            server_name = str(metadata.get("server_name", ""))
            task_id = str(summary.get("task_id", ""))
            last_log = str(summary.get("last_log", ""))
            if q_text and q_text not in server_name.lower() and q_text not in task_id.lower() and q_text not in last_log.lower():
                return False

        created_at = self._normalize_datetime(summary.get("created_at"))
        if date_from:
            date_from_dt = self._normalize_datetime(date_from, end_of_day=False)
            if date_from_dt and created_at and created_at < date_from_dt:
                return False
        if date_to:
            date_to_dt = self._normalize_datetime(date_to, end_of_day=True)
            if date_to_dt and created_at and created_at > date_to_dt:
                return False

        return True

    def list_tasks(
        self,
        limit: int = 100,
        status: Optional[str] = None,
        q: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        include_archived: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        작업 목록 조회 (최신순)

        Args:
            limit: 최대 반환 개수

        Returns:
            작업 요약 리스트
        """
        with self._lock:
            self._run_auto_archive_unlocked()
            task_items = sorted(
                self._tasks.items(),
                key=lambda item: item[1].get("created_at", ""),
                reverse=True,
            )
            results: List[Dict[str, Any]] = []
            for task_id, _task_info in task_items:
                summary = self._build_task_summary_unlocked(task_id)
                if summary is None:
                    continue
                if not self._matches_filters_unlocked(
                    summary,
                    status=status,
                    q=q,
                    date_from=date_from,
                    date_to=date_to,
                    include_archived=include_archived,
                ):
                    continue
                results.append(summary)
                if len(results) >= max(limit, 0):
                    break
            return results

    def get_task_detail(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        작업 상세 조회

        Args:
            task_id: 작업 식별자

        Returns:
            작업 상세 정보 또는 None
        """
        with self._lock:
            self._run_auto_archive_unlocked()
            return self._build_task_detail_unlocked(task_id)

    def append_log(self, task_id: str, log_line: str) -> None:
        """
        작업 로그 추가

        Args:
            task_id: 작업 식별자
            log_line: 추가할 로그 라인
        """
        with self._lock:
            if task_id in self._logs:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                formatted_line = f"[{timestamp}] {log_line}"
                self._logs[task_id].append(formatted_line)
                self._tasks[task_id]["updated_at"] = datetime.now().isoformat()
                self._record_event_unlocked(
                    "task_log_appended",
                    task_id,
                    extra={
                        "log_line": formatted_line,
                        "total_logs": len(self._logs[task_id]),
                    },
                )
                self._persist_task_with_log_safely(task_id, formatted_line)

    def get_logs(self, task_id: str) -> List[str]:
        """
        작업 로그 조회

        Args:
            task_id: 작업 식별자

        Returns:
            로그 라인 리스트
        """
        with self._lock:
            return list(self._logs.get(task_id, []))

    def clear_task(self, task_id: str) -> None:
        """
        작업 데이터 삭제 (메모리 정리용)

        Args:
            task_id: 작업 식별자
        """
        with self._lock:
            self._tasks.pop(task_id, None)
            self._logs.pop(task_id, None)
            self._record_event_unlocked(
                "task_removed",
                task_id,
                include_summary=False,
                extra={"task": None},
            )
            self._delete_task_safely(task_id)

    def archive_task(self, task_id: str, archived: bool = True) -> Optional[Dict[str, Any]]:
        """
        작업 아카이브 상태 변경

        Args:
            task_id: 작업 식별자
            archived: 아카이브 여부

        Returns:
            갱신된 작업 상세 정보 또는 None
        """
        with self._lock:
            if task_id not in self._tasks:
                return None

            self._ensure_task_shape_unlocked(task_id)
            self._tasks[task_id]["archived"] = bool(archived)
            self._tasks[task_id]["archived_at"] = (
                datetime.now().isoformat() if archived else None
            )
            self._tasks[task_id]["updated_at"] = datetime.now().isoformat()
            self._record_event_unlocked(
                "task_archived" if archived else "task_unarchived",
                task_id,
            )
            self._persist_task_safely(task_id)
            return self._build_task_detail_unlocked(task_id)

    def wait_for_updates(self, last_seq: int, timeout: float = 10.0) -> int:
        """
        지정한 시퀀스 이후의 변경이 생길 때까지 대기
        """
        with self._condition:
            if self._event_version > max(0, int(last_seq)):
                return self._event_version
            self._condition.wait(timeout=max(0.0, float(timeout)))
            return self._event_version

    def get_events_since(
        self,
        last_seq: int = 0,
        *,
        include_archived: bool = True,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """
        시퀀스 이후 이벤트 조회
        """
        with self._lock:
            self._run_auto_archive_unlocked()
            sequence = max(0, int(last_seq))
            results: List[Dict[str, Any]] = []
            for event in self._events:
                if int(event.get("seq", 0)) <= sequence:
                    continue
                task_summary = event.get("task")
                if (
                    not include_archived
                    and isinstance(task_summary, dict)
                    and bool(task_summary.get("archived", False))
                ):
                    continue
                results.append(deepcopy(event))
                if len(results) >= max(1, int(limit)):
                    break
            return results


# 전역 TaskManager 인스턴스
task_manager = TaskManager()

__all__ = ["TaskManager", "TaskStatus", "task_manager"]
