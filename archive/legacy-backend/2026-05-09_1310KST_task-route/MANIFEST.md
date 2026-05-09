# Legacy task route/domain archive

Timestamp: 2026-05-09_1310KST
Project: Gjallar
Branch: rewrite/prd-v1-mvp
Approval: user said "진행해" after Hermes recommended approval-gated task route archive cleanup.

## Scope

Moved the remaining legacy task/status/log domain out of the active backend import tree now that `/api/v1/jobs` and `/api/v1/jobs/{job_id}/artifacts` exist and backend pytest is GREEN.

## Moved paths

- `backend/app/domains/task` -> `archive/legacy-backend/2026-05-09_1310KST_task-route/backend/app/domains/task`

## Entrypoint changes

- Removed `task_router` import from `backend/app/main.py`.
- Removed legacy `/api/tasks`, `/api/status/{task_id}`, `/api/logs/{task_id}`, `/api/tasks/stream`, `/api/tasks/{task_id}`, and `/api/tasks/{task_id}/archive` exposure from `backend/app/main.py`.

## Kept active

- `/api/v1/jobs` and `/api/v1/jobs/{job_id}/artifacts` remain the MVP read API replacement.
- `backend/app/shared/tasks.py` remains active for now because this slice only archives the public legacy task route/domain.
- Frontend legacy `frontend/src/services/api.js` references are left for the upcoming frontend salvage slice.

## Explicitly not run

- No commit or push.
- No cron/heartbeat restart.
- No Terraform/IaC apply or write.
- No Proxmox write, VM create, or power action.
- No live delete outside git working tree/archive move.
