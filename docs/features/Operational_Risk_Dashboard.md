# Operational Risk Dashboard

## Purpose

Phase 2 builds an Operational Risk Dashboard for Proxmox operations. Gjallar
reads Proxmox/PBS evidence, stores Gjallar-owned observation/configuration state
in its local platform-state database, and calculates operational risks without
mutating Proxmox resources.

```text
Observe → Govern → Act
```

The current implementation is still primarily `Observe + Govern`. It recommends
actions and lets operators tune Gjallar-owned policy thresholds, but it does not
stop, start, reboot, delete, or reconfigure Proxmox VMs from the dashboard.

## API

```text
GET /api/operations/risks
```

The endpoint collects read-only evidence and returns a normalized dashboard
payload. The response now includes `threshold_config`, which shows the currently
applied Gjallar policy thresholds and whether they came from defaults or the DB.

Read-only Proxmox evidence includes:

```text
VM inventory GET
node monitoring GET
snapshot list GET
task history GET
GET /cluster/backup
GET /cluster/backup-info/not-backed-up
```

Gjallar-local evidence/configuration includes:

```text
platform_state.db / operational_vm_state
platform_state.db / operational_risk_thresholds
```

`operational_vm_state` stores observed VM state timestamps such as
`status_since_at` and `last_running_at`. These values survive backend restarts
and make time-based risks possible even when Proxmox only exposes current state.

`operational_risk_thresholds` stores operator-configurable risk policy values.
This is a Gjallar-local policy mutation, not a Proxmox mutation.

Example top-level shape from the current lab after threshold integration:

```json
{
  "status": "warning",
  "summary": {
    "total_risks": 50,
    "critical": 0,
    "warning": 30,
    "info": 20,
    "affected_nodes": 3,
    "affected_vms": 21,
    "total_nodes": 3,
    "total_vms": 21,
    "categories": {
      "backup_coverage": 21,
      "governance": 20,
      "guest_agent": 9
    }
  },
  "evidence": {
    "backup_task_history_collected": true,
    "backup_schedule_collected": true,
    "backup_jobs_count": 0,
    "backup_uncovered_vms": 23,
    "vm_state_history_collected": true,
    "vm_state_history_vms": 21
  },
  "threshold_config": {
    "source": "default",
    "thresholds": {
      "storage_warning_percent": 80.0,
      "storage_critical_percent": 90.0,
      "snapshot_warning_days": 14,
      "snapshot_critical_days": 30,
      "backup_warning_days": 7,
      "stopped_warning_days": 30,
      "stopped_critical_days": 90
    }
  },
  "risk_items": []
}
```

## Risk checks

### Node status

- critical if a node is not reported as `online`.

### Storage capacity

Default thresholds:

- warning if storage usage is at or above 80%.
- critical if storage usage is at or above 90%.

These values are now configurable through Gjallar threshold policy.

### Guest agent signal

- warning if a VM is running but `qemu-guest-agent` IP evidence is empty.
- This is a practical signal for guest-agent missing/unresponsive cases.

### Governance metadata

- info if a VM has no owner/team/tag/description signal.
- The first version treats any explicit tag as a governance signal.
- Stricter owner taxonomy can be added later.

### Snapshot age

Default thresholds:

- warning if a snapshot is older than 14 days.
- critical if a snapshot is older than 30 days.
- `current` pseudo-snapshot is ignored.

These values are now configurable through Gjallar threshold policy.

### Backup coverage

- warning if Proxmox `not-backed-up` evidence reports that a VM is not covered by configured backup jobs.
- This is stronger than task-history-only evidence because it checks schedule/job coverage directly.
- If a VM is explicitly uncovered by backup jobs, the dashboard shows `backup_coverage` and suppresses the less-specific `backup_recency` warning for that VM.

### Backup recency fallback

Default threshold:

- warning if no successful `vzdump`/backup task evidence is found within 7 days.

This remains useful when schedule coverage evidence exists but the VM is not
reported as uncovered, or when schedule evidence is unavailable. The days value
is now configurable through Gjallar threshold policy.

### Long stopped VM

Default thresholds:

- warning if Gjallar has observed a VM stopped for at least 30 days.
- critical if Gjallar has observed a VM stopped for at least 90 days.

Proxmox supplies the current VM status. Gjallar's local DB supplies the time
history. A newly observed stopped VM starts with `stopped_days = 0.0` and becomes
a risk only after the configured threshold is reached.

## Threshold policy

Threshold details are documented in
[Operational_Risk_Thresholds.md](Operational_Risk_Thresholds.md).

High-level behavior:

1. Gjallar starts with built-in defaults.
2. If `operational_risk_thresholds` has saved overrides, Gjallar merges them over defaults.
3. Invalid threshold writes are rejected with HTTP 422.
4. If the DB/table is unavailable during risk calculation, Gjallar falls back to defaults rather than failing the dashboard.
5. `DELETE /api/operations/risks/thresholds` resets policy to defaults.

## Frontend

Route:

```text
/risks
```

Navigation label:

```text
Risk Dashboard
```

The screen shows:

- overall status
- critical/warning/info counts
- affected VM/node counts
- category counts, including `Backup coverage` and `Long stopped VM`
- risk item cards with evidence and recommendation
- current threshold source/defaults
- Risk Thresholds editor for storage/snapshot/backup/stopped policies
- manual refresh and 60-second auto refresh

The threshold editor changes only Gjallar-local policy. It does not mutate
Proxmox resources.

## Safety boundary

The dashboard must remain read-only with respect to Proxmox.

Allowed Proxmox/PBS data sources:

- VM inventory GET
- node monitoring GET
- snapshot list GET
- task history GET
- backup job/schedule coverage GET

Allowed Gjallar-local writes:

- upsert current VM observation state into `operational_vm_state`
- store/reset operator threshold policy in `operational_risk_thresholds`

Forbidden from this dashboard:

- VM delete/terminate
- start/shutdown/stop/reboot
- VM config PUT/POST
- snapshot delete
- backup job create/update/delete

## Validation

Last validation after threshold configuration integration:

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
live smoke: /health HTTP 200
live smoke: invalid threshold wrapper payload HTTP 422
live smoke: PUT thresholds source=database
live smoke: /api/operations/risks threshold_config source=database
live smoke: DELETE reset source=default
```

Final smoke summary:

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

## Known follow-ups

- Add stale `operational_vm_state` cleanup/reconciliation for VMs no longer in inventory.
- Add stronger guard for VMID reuse so deleted/recreated VMs do not inherit old stopped history.
- Add risk acknowledge/suppress overlay state.
- Add stricter owner/tag taxonomy checks.
- Add PBS-specific capacity/restore assurance evidence if PBS API access is configured.
