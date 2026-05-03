# Operational VM State History

## Goal

Gjallar needs time-based operational risks even when Proxmox only exposes current
state. The DB-backed risk foundation stores VM observation history locally,
detects long-stopped VM candidates, and now keeps lifecycle state safe when VMs
disappear or a `node+vmid` is reused.

## Why local DB state is required

Proxmox can tell Gjallar that a VM is currently `stopped`, but it does not give a
portable, dashboard-friendly `stopped_since` value for this use case. Gjallar
therefore stores its own observations:

```text
Proxmox API = current read-only evidence
Gjallar DB = observation/lifecycle history
Risk engine = policy judgment
```

This makes the dashboard resilient across backend restarts and prevents newly
reused VMIDs from inheriting stale stopped history.

## Schema

Migrations:

```text
backend/alembic/versions/20260503_0011_operational_vm_state.py
backend/alembic/versions/20260503_0013_operational_vm_state_lifecycle.py
```

Table:

```text
operational_vm_state
```

Core columns:

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
active
missing_since_at
lifecycle_generation
```

`active`, `missing_since_at`, and `lifecycle_generation` are lifecycle-hardening
columns. They let Gjallar distinguish an old missing VM from a new VM that later
appears with the same VMID.

## Runtime flow

1. `GET /api/operations/risks` collects Proxmox VM inventory as a
   `VMInventorySnapshot(items, complete, scope)` value.
2. `ProxmoxService.get_vms(node=...)` still returns `list[dict]` for public/API
   compatibility and does not store completeness in a service singleton flag.
3. The risk dashboard persists VM state through `get_vm_state_history()`.
4. Missing-VM reconciliation is enabled only when the snapshot is complete and
   cluster-wide:

```python
reconcile_missing = snapshot.scope == "cluster" and snapshot.complete is True
```

5. `OperationalRiskStateStore.observe_vms()` upserts each observed VM and returns
   dashboard-keyed evidence such as `node/vmid`.
6. `build_operational_risk_dashboard()` uses that evidence for `long_stopped`
   risks.

## Lifecycle hardening behavior

- Current VMs are upserted with `active=true` and `missing_since_at=null`.
- VMs omitted from a complete cluster-wide snapshot are marked
  `active=false` with `missing_since_at=<observed_at>`.
- Old inactive rows are purged after the retention window.
- If an inactive `node+vmid` reappears, Gjallar treats it as a new lifecycle:
  - increments `lifecycle_generation`;
  - resets `first_seen_at`, `status_since_at`, and current stopped/running
    evidence;
  - does not inherit the old VM's stopped duration.
- Empty snapshots do not mark all active VMs missing.
- Partial cluster inventory and node-scoped inventory do not perform cluster-wide
  missing reconciliation.

## Risk thresholds

Defaults:

```text
stopped_warning_days = 30
stopped_critical_days = 90
```

Thresholds are operator-configurable through Gjallar's local DB-backed risk
threshold policy/API/UI.

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

## Safety boundary

This feature is read-only with respect to Proxmox. It may mutate only Gjallar's
local platform-state DB (`operational_vm_state`). It must not call Proxmox
start/stop/delete/update APIs from the risk dashboard path.

## Validation

Latest lifecycle-hardening validation:

```text
backend unittest: 54 passed
backend compileall: passed
alembic upgrade head: passed
frontend operationalRisk test: passed
frontend lint/build: passed
terraform validate: passed
git diff --check: passed
static security scan: STATIC_SCAN_OK
independent review: passed=true
live smoke: health_code=200, risk_code=200, vm_state_history_collected=true, vm_state_history_vms=21, state_rows=21, active_rows=21, inactive_rows=0, required_columns_present=true
```

## Follow-ups

- risk acknowledge/suppress state.
- owner/tag taxonomy instead of treating any tag as sufficient governance
  evidence.
- PBS direct API / restore-readiness evidence.
- Optional defense-in-depth: consider making lower-level direct store callers
  opt into missing reconciliation explicitly as well.
