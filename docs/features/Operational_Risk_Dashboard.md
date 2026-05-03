# Operational Risk Dashboard

## Purpose

Phase 2 starts with a read-only Operational Risk Dashboard. The goal is to show Proxmox operational risks before turning them into actions.

```text
Observe → Govern → Act
```

This feature is currently `Observe + Govern` only. It does not mutate, stop, start, reboot, or delete VMs.

## API

```text
GET /api/operations/risks
```

The endpoint collects read-only Proxmox evidence through existing GET-style inventory, monitoring, snapshot, and task APIs, then returns a normalized dashboard payload.

Example top-level shape:

```json
{
  "status": "warning",
  "generated_at": 1777785386,
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
      "backup_recency": 21,
      "governance": 20,
      "guest_agent": 9
    }
  },
  "risk_items": []
}
```

## Risk checks in the first version

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
- Stricter owner policy can be added later.

### Snapshot age

- warning if a snapshot is older than 14 days.
- critical if a snapshot is older than 30 days.
- `current` pseudo-snapshot is ignored.

### Backup recency

- warning if no successful `vzdump`/backup task evidence is found within 7 days.
- This uses available Proxmox task history; later versions should integrate backup schedules/PBS data directly.

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
- category counts
- risk item cards with evidence and recommendation
- manual refresh and 60-second auto refresh

## Safety boundary

The dashboard must remain read-only.

Allowed data sources:

- VM inventory GET
- node monitoring GET
- snapshot list GET
- task history GET

Forbidden from this dashboard:

- VM delete/terminate
- start/shutdown/stop/reboot
- VM config PUT/POST
- snapshot delete
- backup job mutation

## Validation

Last validation for this feature:

```text
backend unittest discover: 34 tests passed
frontend utility tests: passed
frontend lint: passed
frontend build: passed
python compileall: passed
terraform validate: passed
git diff --check: passed
live endpoint smoke: /api/operations/risks HTTP 200
```
