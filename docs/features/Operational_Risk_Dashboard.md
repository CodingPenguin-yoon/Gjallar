# Operational Risk Dashboard

## Purpose

Phase 2 builds a read-only Operational Risk Dashboard for Proxmox operations.
Gjallar reads Proxmox/PBS evidence, stores Gjallar-owned observation history in
its local platform-state database, and calculates operational risks without
mutating Proxmox resources.

```text
Observe → Govern → Act
```

The current implementation is still `Observe + Govern`. It recommends actions,
but does not stop, start, reboot, delete, or reconfigure VMs.

## API

```text
GET /api/operations/risks
```

The endpoint collects read-only evidence and returns a normalized dashboard
payload.

Read-only Proxmox evidence includes:

```text
VM inventory GET
node monitoring GET
snapshot list GET
task history GET
GET /cluster/backup
GET /cluster/backup-info/not-backed-up
```

Gjallar-local evidence includes:

```text
platform_state.db / operational_vm_state
```

This local table stores the latest observed VM state and timestamps such as
`status_since_at` and `last_running_at`. These values survive backend restarts
and make time-based risks possible even when Proxmox only exposes current state.

Example top-level shape from the current lab:

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
  "risk_items": []
}
```

## Risk checks

### Node status

- critical if a node is not reported as `online`.

### Storage capacity

- warning if storage usage is at or above 80%.
- critical if storage usage is at or above 90%.

### Guest agent signal

- warning if a VM is running but `qemu-guest-agent` IP evidence is empty.
- This is a practical signal for guest-agent missing/unresponsive cases.

### Governance metadata

- info if a VM has no owner/team/tag/description signal.
- The first version treats any explicit tag as a governance signal.
- Stricter owner taxonomy can be added later.

### Snapshot age

- warning if a snapshot is older than 14 days.
- critical if a snapshot is older than 30 days.
- `current` pseudo-snapshot is ignored.

### Backup coverage

- warning if Proxmox `not-backed-up` evidence reports that a VM is not covered by configured backup jobs.
- This is stronger than task-history-only evidence because it checks schedule/job coverage directly.
- If a VM is explicitly uncovered by backup jobs, the dashboard shows `backup_coverage` and suppresses the less-specific `backup_recency` warning for that VM.

### Backup recency fallback

- warning if no successful `vzdump`/backup task evidence is found within 7 days.
- This remains useful when schedule coverage evidence exists but the VM is not reported as uncovered, or when schedule evidence is unavailable.

### Long stopped VM

- warning if Gjallar has observed a VM stopped for at least 30 days.
- critical if Gjallar has observed a VM stopped for at least 90 days.
- Proxmox supplies the current VM status. Gjallar's local DB supplies the time history.
- A newly observed stopped VM starts with `stopped_days = 0.0` and becomes a risk only after the configured threshold is reached.

## State persistence model

Table:

```text
operational_vm_state
```

Important columns:

```text
resource_key               qemu:<vmid> by default
node
vmid
name
status
first_seen_at
last_seen_at
status_since_at
last_running_at
last_observed_payload_json
```

Current behavior:

1. `/api/operations/risks` reads VM inventory from Proxmox.
2. Gjallar upserts the latest VM status into `operational_vm_state`.
3. If status changed, `status_since_at` resets to the current observation time.
4. If status is `running`, `last_running_at` is updated.
5. Risk calculation uses the returned state evidence for `long_stopped` checks.

If the DB schema has not been migrated yet, the endpoint continues without VM
state evidence and sets `vm_state_history_collected=false`.

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
- manual refresh and 60-second auto refresh

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

Forbidden from this dashboard:

- VM delete/terminate
- start/shutdown/stop/reboot
- VM config PUT/POST
- snapshot delete
- backup job create/update/delete

## Validation

Last validation for this feature:

```text
backend unittest discover -s tests: 42 tests passed
python compileall app tests: passed
frontend utility tests: passed
frontend lint: passed
frontend build: passed
alembic upgrade head: passed
terraform validate: passed
git diff --check: passed
static security scan: passed
independent code review: passed
live smoke: /health HTTP 200
live smoke: /api/operations/risks HTTP 200
live smoke: operational_vm_state rows = 21
```

## Known follow-ups

- Add configurable thresholds UI/config for stopped/snapshot/backup/storage policies.
- Add stale `operational_vm_state` cleanup/reconciliation for VMs no longer in inventory.
- Add stronger guard for VMID reuse so deleted/recreated VMs do not inherit old stopped history.
- Add risk acknowledge/suppress overlay state.
- Add stricter owner/tag taxonomy checks.
