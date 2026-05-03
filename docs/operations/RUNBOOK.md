# Gjallar Runbook

## 1. Local development on Codex VM

```bash
ssh codex-vm
cd /home/yoon/projects/Gjallar
```

Current dev ports:

```text
frontend: 5174
backend: 8001
```

## 2. Backend

```bash
cd backend
. .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

Runtime import smoke test:

```bash
cd backend
.venv/bin/python -c 'from app.main import app; print(app.title)'
```

Expected title:

```text
Gjallar VM Operations API
```

Redis may be unavailable in local development. The backend can still import and
run, but chat/session history may not persist.

## 3. Platform-state DB migrations

Gjallar stores its own operational state and policy in the platform-state SQLite
DB. Apply migrations before running features that need DB-backed observations or
threshold configuration:

```bash
cd /home/yoon/projects/Gjallar/backend
.venv/bin/python -m alembic upgrade head
```

Default DB path:

```text
/home/yoon/projects/Gjallar/data/platform_state.db
```

Important tables:

```text
tasks
task_logs
platform_metadata
operational_vm_state
operational_risk_thresholds
```

Quick DB smoke for VM state history:

```bash
cd /home/yoon/projects/Gjallar/backend
PYTHONPATH=. .venv/bin/python - <<'PY'
from sqlalchemy import text
from app.shared.platform_db import create_platform_engine, resolve_platform_state_database_url
engine = create_platform_engine(resolve_platform_state_database_url())
with engine.connect() as conn:
    print(conn.execute(text('select count(*) from operational_vm_state')).scalar_one())
PY
```

## 4. Frontend

```bash
cd frontend
npm run dev -- --host 0.0.0.0 --port 5174
```

Validation:

```bash
cd frontend
node tests/operationalRisk.test.mjs
npm run lint
npm run build
```

## 5. Common verification

From repo root:

```bash
cd backend && PYTHONPATH=. .venv/bin/python -m unittest discover -s tests -v
cd backend && PYTHONPATH=. .venv/bin/python -m compileall app tests
cd frontend && node tests/operationalRisk.test.mjs && npm run lint && npm run build
cd infra/terraform && terraform validate
git diff --check
```

For pre-commit security review of the current diff:

```bash
bash ~/.hermes/skills/software-development/requesting-code-review/scripts/git_diff_static_scan.sh /home/yoon/projects/Gjallar
```

## 6. VM provisioning smoke path

1. Open frontend.
2. Go to `Create Instance`.
3. Select node, template, storage, and network.
4. Choose CPU/RAM/name and optional static IP.
5. Start VM provisioning.
6. Track progress in `Task Board`.
7. Confirm the VM appears in `Instance List`.

## 7. Safety notes

- Do not commit `.env`, `data/`, tokens, keys/secrets, or local runtime artifacts.
- Use `/api/provision` for new VM provisioning calls. Treat `/api/deploy` as a compatibility endpoint only.
- Proxmox inventory calls are cached briefly; use manual refresh or wait for TTL expiry when checking recent changes.
- Operational Risk Dashboard may write Gjallar-local observation/policy state, but must remain read-only with respect to Proxmox resources.

## 8. Provisioning runtime prerequisites

VM provisioning runs Terraform and Ansible from the backend process environment.
The host running the backend must have these executables on `PATH`:

```bash
command -v terraform && terraform version
command -v ansible-playbook && ansible-playbook --version
terraform -chdir=infra/terraform init -input=false
terraform -chdir=infra/terraform validate
```

Current Codex VM runtime verification:

```text
Terraform: v1.15.1
Ansible: 2.10.8
ansible-playbook: 2.10.8
terraform init/validate: pass
```

## 9. Provisioning readiness check

Before using `Create Instance`, verify the backend can see the required provisioning runtime/config:

```bash
curl http://127.0.0.1:8001/api/provision/readiness
```

Expected healthy result:

```text
HTTP 200
status: ready
```

Credential values are intentionally hidden and must not be logged or committed.

## 10. Provisioning resource preflight smoke

Use this after backend route changes or before Create VM smoke tests.

```bash
curl -sS -X POST http://127.0.0.1:8001/api/provision/preflight \
  -H 'Content-Type: application/json' \
  -d '{"server_id":"yoonmanserver","template_id":"yoonmanserver/118","storage_id":"machine-mainnode","network_ids":["vmbr0"],"server_name":"gjallar-smoke-preflight","disk_size_gb":50}'
```

If `storage_id`, `network_ids`, VM identity, or static IP/gateway values are
invalid, the endpoint should return `status: error` with next actions instead of
starting Terraform. The Create VM wizard blocks Launch on readiness/resource-
preflight errors and allows warnings after operator review.

## 11. Template disk-size safety

Before running actual Create VM smoke, check `POST /api/provision/preflight`. If
the selected template disk is larger than requested `disk_size_gb`, preflight
returns `template_disk_size=error` because Proxmox/Terraform cannot shrink cloned
disks.

Do not use `/api/instances/terminate` for smoke cleanup unless explicitly
approved. Stop/shutdown test VMs only.

## 12. Operational Risk Dashboard smoke

After backend route/service changes, apply migrations, restart the backend dev
server, and verify the risk endpoint:

```bash
cd /home/yoon/projects/Gjallar/backend
.venv/bin/python -m alembic upgrade head
curl -sS http://127.0.0.1:8001/api/operations/risks
```

Expected result:

```text
HTTP 200
status: healthy | info | warning | critical
summary.total_nodes and summary.total_vms are populated
threshold_config.source is default or database
```

Evidence fields:

```text
evidence.backup_task_history_collected: true|false
evidence.backup_schedule_collected: true|false
evidence.backup_jobs_count: number|null
evidence.backup_uncovered_vms: number|null
evidence.vm_state_history_collected: true|false
evidence.vm_state_history_vms: number|null
summary.categories.backup_coverage: optional number
summary.categories.long_stopped: optional number
threshold_config.source: default|database|fallback
```

Current lab smoke after threshold integration:

```text
HTTP 200
status: warning
total_nodes: 3
total_vms: 21
total_risks: 50
categories:
  backup_coverage: 21
  governance: 20
  guest_agent: 9
evidence:
  backup_jobs_count: 0
  backup_uncovered_vms: 23
  vm_state_history_collected: true
  vm_state_history_vms: 21
threshold_config:
  source: default after reset
  storage_warning_percent: 80.0
operational_vm_state rows: 21
```

Safety boundary:

- This endpoint is read-only with respect to Proxmox.
- It may call Proxmox GET endpoints such as `/cluster/backup` and `/cluster/backup-info/not-backed-up`.
- It may write Gjallar-local observations to `operational_vm_state`.
- It may read Gjallar-local threshold policy from `operational_risk_thresholds`.
- It must not call terminate/delete/start/stop/shutdown/reboot, config mutation APIs, snapshot delete, or backup job create/update/delete.
- Risk recommendations may mention manual actions, but the dashboard itself does not execute them.

## 13. Operational Risk Thresholds smoke

Threshold API changes Gjallar-local policy only.

```bash
curl -sS http://127.0.0.1:8001/api/operations/risks/thresholds
```

Invalid wrapper payload should fail with HTTP 422:

```bash
curl -sS -o /tmp/threshold_invalid.json -w '%{http_code}\n' \
  -X PUT http://127.0.0.1:8001/api/operations/risks/thresholds \
  -H 'Content-Type: application/json' \
  -d '{"thresholds":{"storage_warning_percent":95}}'
```

Temporary update smoke:

```bash
curl -sS -X PUT http://127.0.0.1:8001/api/operations/risks/thresholds \
  -H 'Content-Type: application/json' \
  -d '{"storage_warning_percent":95,"storage_critical_percent":99}'
curl -sS http://127.0.0.1:8001/api/operations/risks
```

Always reset after smoke:

```bash
curl -sS -X DELETE http://127.0.0.1:8001/api/operations/risks/thresholds
```

Expected final reset result:

```text
after_reset_source: default
after_reset_storage_warning: 80.0
```
