# Operational Risk Thresholds

## Purpose

Operational risk thresholds are Gjallar-owned policy settings for the Risk
Dashboard. They let an operator tune when storage, snapshot, backup, and stopped
VM findings become warning/critical risks.

This feature intentionally stores policy in Gjallar's platform-state DB. It does
not create, update, delete, start, stop, or reconfigure any Proxmox resource.

## API

```text
GET    /api/operations/risks/thresholds
PUT    /api/operations/risks/thresholds
DELETE /api/operations/risks/thresholds
```

Related dashboard endpoint:

```text
GET /api/operations/risks
```

`GET /api/operations/risks` includes the currently applied `threshold_config` so
operators can see which policy basis was used for the risk calculation.

## Storage model

Table:

```text
operational_risk_thresholds
```

Purpose:

```text
Gjallar-local operational policy override for risk calculation thresholds.
```

Important fields:

```text
key              default policy key, currently "default"
thresholds_json  JSON object with operator overrides
updated_at        last update timestamp
```

Migration:

```bash
cd /home/yoon/projects/Gjallar/backend
.venv/bin/python -m alembic upgrade head
```

## Default thresholds

```json
{
  "storage_warning_percent": 80.0,
  "storage_critical_percent": 90.0,
  "snapshot_warning_days": 14,
  "snapshot_critical_days": 30,
  "backup_warning_days": 7,
  "stopped_warning_days": 30,
  "stopped_critical_days": 90
}
```

## Merge/fallback semantics

1. Built-in defaults are always available.
2. Saved DB values are partial overrides merged over defaults.
3. The returned config includes a `source` such as `default` or `database`.
4. If the DB/table is unavailable during dashboard calculation, Gjallar falls back to defaults and keeps the dashboard available.
5. `DELETE /api/operations/risks/thresholds` resets the persisted policy so defaults apply again.

## Validation rules

Invalid inputs return HTTP 422.

Rules:

```text
storage_warning_percent > 0
storage_critical_percent <= 100
storage_warning_percent <= storage_critical_percent
snapshot_warning_days >= 1
snapshot_critical_days <= 3650
snapshot_warning_days <= snapshot_critical_days
backup_warning_days >= 1
backup_warning_days <= 3650
stopped_warning_days >= 1
stopped_critical_days <= 3650
stopped_warning_days <= stopped_critical_days
unknown fields are rejected
wrapper payloads such as {"thresholds": {...}} are rejected
```

The frontend uses matching validation before sending updates so obvious policy
mistakes are blocked in the UI and still enforced by the backend.

## Frontend behavior

The `/risks` screen includes a `Risk Thresholds` editor.

Current editable policy groups:

- storage warning/critical percent
- snapshot warning/critical days
- backup recency warning days
- stopped VM warning/critical days

The UI shows:

- current threshold source
- editable draft values
- validation messages
- save/reset actions
- safety note that only Gjallar-local policy changes are made

## Smoke test

Example smoke sequence:

```bash
curl -sS http://127.0.0.1:8001/health
curl -sS http://127.0.0.1:8001/api/operations/risks/thresholds
curl -sS -X PUT http://127.0.0.1:8001/api/operations/risks/thresholds \
  -H 'Content-Type: application/json' \
  -d '{"storage_warning_percent":95,"storage_critical_percent":99}'
curl -sS http://127.0.0.1:8001/api/operations/risks
curl -sS -X DELETE http://127.0.0.1:8001/api/operations/risks/thresholds
```

Final lab smoke result:

```json
{
  "health_code": 200,
  "invalid_payload_code": 422,
  "put_code": 200,
  "updated_source": "database",
  "updated_storage_warning": 95.0,
  "risk_code": 200,
  "risk_total_nodes": 3,
  "risk_total_vms": 21,
  "risk_total_risks": 50,
  "risk_threshold_source": "database",
  "risk_threshold_storage_warning": 95.0,
  "reset_code": 200,
  "after_reset_code": 200,
  "after_reset_source": "default",
  "after_reset_storage_warning": 80.0
}
```

The smoke intentionally resets the threshold policy at the end.

## Verification

```text
backend targeted threshold/risk tests: passed
backend unittest discover -s tests: 46 tests passed
python compileall app tests: passed
frontend operationalRisk tests: passed
frontend lint: passed
frontend build: passed
alembic upgrade head: passed
terraform validate: passed
git diff --check: passed
static security scan: passed
independent code review: passed
live smoke: passed
```

## Safety boundary

Allowed writes:

- Gjallar-local `operational_risk_thresholds` insert/update/delete

Forbidden writes:

- Proxmox VM lifecycle actions
- Proxmox VM config mutation
- Proxmox snapshot mutation
- Proxmox backup job mutation

Operational meaning:

```text
Threshold API mutates Gjallar policy, not Proxmox infrastructure.
```
