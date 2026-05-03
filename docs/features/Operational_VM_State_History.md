# Operational VM State History

## Goal

Gjallar needs time-based operational risks even when Proxmox only exposes current
state. The first DB-backed risk foundation stores VM observation history locally
and uses it to detect long-stopped VM candidates.

## Why local DB state is required

Proxmox can tell Gjallar that a VM is currently `stopped`, but it does not give a
portable, dashboard-friendly `stopped_since` value for this use case. Gjallar
therefore stores its own observations:

```text
Proxmox API = current evidence
Gjallar DB = time history
Risk engine = policy judgment
```

This makes the dashboard resilient across backend restarts.

## Schema

Migration:

```text
backend/alembic/versions/20260503_0011_operational_vm_state.py
```

Table:

```text
operational_vm_state
```

Columns:

```text
resource_key
resource_type
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

The current resource key is `qemu:<vmid>` by default.

## Runtime flow

1. `GET /api/operations/risks` collects Proxmox VM inventory.
2. `OperationalRiskStateStore.observe_vms()` upserts each VM into the platform-state DB.
3. If a VM status changes, `status_since_at` resets.
4. If a VM is running, `last_running_at` updates.
5. The store returns dashboard-keyed evidence such as `node/vmid`.
6. `build_operational_risk_dashboard()` uses that evidence for `long_stopped` risks.

## Risk thresholds

Defaults:

```text
stopped_warning_days = 30
stopped_critical_days = 90
```

Current thresholds are code defaults. A later threshold config/UI slice should
move them into Gjallar policy settings.

## Failure behavior

If the local DB table is missing or cannot be opened, the risk endpoint continues
without failing the whole dashboard. Evidence makes this explicit:

```json
{
  "vm_state_history_collected": false,
  "vm_state_history_vms": null
}
```

When collection succeeds:

```json
{
  "vm_state_history_collected": true,
  "vm_state_history_vms": 21
}
```

## Validation

```text
backend tests: 42 passed
frontend tests/lint/build: passed
alembic upgrade head: passed
terraform validate: passed
live smoke: vm_state_history_collected=true, vm_state_history_vms=21, operational_vm_state rows=21
```

## Follow-ups

- VMID reuse guard: a deleted/recreated VM should not accidentally inherit old stopped history.
- Stale row cleanup: rows for VMs no longer present in current inventory should be archived or reconciled.
- Threshold config/UI: stopped thresholds should become operator-configurable.
- Risk acknowledge/suppress: operators should be able to document intentional long-stopped VMs.
