# Gjallar Backend

The backend is a FastAPI API server for Proxmox VM operations, inventory, monitoring, and task/log tracking.

## Main domains

- `app/domains/proxmox`
  - Proxmox node, VM/LXC, template, storage, and network inventory
  - VM lifecycle operations
  - short TTL inventory caching
- `app/domains/deploy`
  - legacy domain name for the current VM provisioning endpoint
  - `POST /api/deploy` should be treated as VM provisioning, not app deployment
- `app/domains/task`
  - task persistence, logs, progress, and SSE
- `app/domains/llm`
  - assistant/chat support

Removed legacy domains:

- GitLab project inventory/API
- GitLab webhooks
- staging host registry/pools
- Deploy Staging application deployment

## Run

```bash
cd backend
. .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

## Smoke checks

```bash
cd backend
.venv/bin/python -c 'from app.main import app; print(app.title)'
```

Expected:

```text
Gjallar VM Operations API
```

From repo root:

```bash
python3 -m compileall backend
git diff --check
```

## Notes

- The app loads the repo root `.env`.
- Do not commit `.env`, tokens, secrets, `data/`, or local runtime artifacts.
- Redis connection warnings during import are acceptable in local development if Redis is not running; chat/session persistence may be disabled.
