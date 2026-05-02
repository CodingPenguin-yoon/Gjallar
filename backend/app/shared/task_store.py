"""SQLAlchemy-backed task persistence for platform state."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.shared.platform_db import create_platform_engine, create_session_factory
from app.shared.platform_models import PlatformMetadata, PlatformTask, PlatformTaskLog


LEGACY_IMPORT_MARKER_KEY = "legacy_task_history_import"


class SQLAlchemyTaskStore:
    """Persist task summaries and logs in the platform state database."""

    def __init__(self, database_url: str, legacy_json_path: Path):
        self._database_url = database_url
        self._legacy_json_path = legacy_json_path
        self._engine = create_platform_engine(database_url)
        self._session_factory = create_session_factory(self._engine)
        self._initialize()

    def _initialize(self) -> None:
        self._ensure_required_schema()
        self._ensure_legacy_import_marker()

    def _ensure_required_schema(self) -> None:
        inspector = inspect(self._engine)
        existing_tables = set(inspector.get_table_names())
        required_tables = {"tasks", "task_logs", "platform_metadata"}
        missing_tables = sorted(required_tables - existing_tables)
        if not missing_tables:
            return

        missing = ", ".join(missing_tables)
        raise RuntimeError(
            "Platform state DB schema is missing required tables "
            f"({missing}). Run `cd backend && alembic upgrade head`."
        )

    def _ensure_legacy_import_marker(self) -> None:
        with self._session_factory.begin() as session:
            marker = session.get(PlatformMetadata, LEGACY_IMPORT_MARKER_KEY)
            if marker is not None:
                return

            existing_task_count = session.execute(
                select(func.count()).select_from(PlatformTask)
            ).scalar_one()
            if existing_task_count:
                session.add(
                    PlatformMetadata(
                        key=LEGACY_IMPORT_MARKER_KEY,
                        value_json={
                            "status": "skipped_existing_db_state",
                            "recorded_at": self._now_iso(),
                        },
                    )
                )
                return

            imported = self._import_legacy_json(session)
            session.add(
                PlatformMetadata(
                    key=LEGACY_IMPORT_MARKER_KEY,
                    value_json={
                        "status": "imported" if imported else "skipped_no_legacy_source",
                        "legacy_path": str(self._legacy_json_path),
                        "recorded_at": self._now_iso(),
                    },
                )
            )

    def _import_legacy_json(self, session: Session) -> bool:
        try:
            payload = json.loads(self._legacy_json_path.read_text(encoding="utf-8"))
        except Exception:
            return False

        if not isinstance(payload, dict):
            return False

        tasks = payload.get("tasks", {})
        logs = payload.get("logs", {})
        if not isinstance(tasks, dict):
            tasks = {}
        if not isinstance(logs, dict):
            logs = {}

        imported_any = False
        for task_id, task in tasks.items():
            if not isinstance(task, dict):
                continue
            task_id = str(task_id)
            self._save_task(session, task_id, task)
            task_logs = logs.get(task_id, [])
            if not isinstance(task_logs, list):
                task_logs = []
            self._replace_task_logs(
                session,
                task_id,
                [str(line) for line in task_logs],
            )
            imported_any = True

        return imported_any

    def _save_task(self, session: Session, task_id: str, task: Dict[str, Any]) -> None:
        metadata = task.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        record = session.get(PlatformTask, task_id)
        if record is None:
            record = PlatformTask(task_id=task_id)
            session.add(record)

        record.status = str(task.get("status", "Pending"))
        record.created_at = str(task.get("created_at", ""))
        record.updated_at = str(task.get("updated_at", ""))
        record.metadata_json = metadata
        record.progress = float(task.get("progress", 0.0) or 0.0)
        record.progress_text = str(task.get("progress_text", "") or "")
        record.progress_source = str(task.get("progress_source", "") or "")
        record.archived = bool(task.get("archived", False))
        record.archived_at = task.get("archived_at")

    def save_task(self, task_id: str, task: Dict[str, Any]) -> None:
        with self._session_factory.begin() as session:
            self._save_task(session, task_id, task)

    def append_log(self, task_id: str, log_line: str) -> None:
        for _attempt in range(5):
            try:
                with self._session_factory.begin() as session:
                    self._append_log(session, task_id, log_line)
                return
            except IntegrityError:
                continue
        raise RuntimeError(f"failed to append task log after retries: {task_id}")

    def _append_log(self, session: Session, task_id: str, log_line: str) -> None:
        max_line_no = session.execute(
            select(func.max(PlatformTaskLog.line_no)).where(PlatformTaskLog.task_id == task_id)
        ).scalar_one()
        next_line_no = (int(max_line_no) + 1) if max_line_no is not None else 0
        session.add(
            PlatformTaskLog(
                task_id=task_id,
                line_no=next_line_no,
                log_line=log_line,
            )
        )
        session.flush()

    def _replace_task_logs(self, session: Session, task_id: str, logs: List[str]) -> None:
        existing_logs = session.scalars(
            select(PlatformTaskLog).where(PlatformTaskLog.task_id == task_id)
        ).all()
        for record in existing_logs:
            session.delete(record)

        for index, line in enumerate(logs):
            session.add(
                PlatformTaskLog(
                    task_id=task_id,
                    line_no=index,
                    log_line=line,
                )
            )

    def delete_task(self, task_id: str) -> None:
        with self._session_factory.begin() as session:
            record = session.get(PlatformTask, task_id)
            if record is not None:
                session.delete(record)

    def save_task_and_append_log(self, task_id: str, task: Dict[str, Any], log_line: str) -> None:
        for _attempt in range(5):
            try:
                with self._session_factory.begin() as session:
                    self._save_task(session, task_id, task)
                    self._append_log(session, task_id, log_line)
                return
            except IntegrityError:
                continue
        raise RuntimeError(f"failed to persist task+log after retries: {task_id}")

    def load_all(self) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, List[str]]]:
        tasks: Dict[str, Dict[str, Any]] = {}
        logs: Dict[str, List[str]] = {}

        with self._session_factory() as session:
            task_rows = session.execute(
                select(PlatformTask).order_by(PlatformTask.created_at.desc())
            ).scalars()

            for row in task_rows:
                metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
                tasks[str(row.task_id)] = {
                    "status": str(row.status),
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                    "metadata": metadata,
                    "progress": float(row.progress or 0.0),
                    "progress_text": str(row.progress_text or ""),
                    "progress_source": str(row.progress_source or ""),
                    "archived": bool(row.archived),
                    "archived_at": row.archived_at,
                }

            log_rows = session.execute(
                select(PlatformTaskLog).order_by(
                    PlatformTaskLog.task_id.asc(),
                    PlatformTaskLog.line_no.asc(),
                )
            ).scalars()

            for row in log_rows:
                task_id = str(row.task_id)
                logs.setdefault(task_id, []).append(str(row.log_line))

        for task_id in tasks.keys():
            logs.setdefault(task_id, [])

        return tasks, logs

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
