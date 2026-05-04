# Operational Risk Dashboard

## Purpose

Phase 2 builds an Operational Risk Dashboard for Proxmox operations. Gjallar
reads Proxmox/PBS evidence, stores Gjallar-owned observation/configuration/
operator-intent state in its local platform-state database, and calculates
operational risks without mutating Proxmox resources.

```text
Observe → Govern → Act
```

The current implementation is `Observe + Govern`: it detects risk, lets
operators tune local policy thresholds, and records local acknowledge/suppress
state for known exceptions. The dashboard still does not stop, start, reboot,
delete, or reconfigure Proxmox VMs.

## API

```text
GET /api/operations/risks?include_suppressed=false
GET /api/operations/risks/overrides
PUT /api/operations/risks/overrides
POST /api/operations/risks/overrides/clear
GET /api/operations/risks/thresholds
PUT /api/operations/risks/thresholds
DELETE /api/operations/risks/thresholds
```

`GET /api/operations/risks` collects read-only evidence and returns a normalized
dashboard payload. It includes `threshold_config`, visible `risk_items`, and
acknowledge/suppress summary fields. Suppressed items are hidden from the default
visible list and are returned in `suppressed_risk_items` when
`include_suppressed=true`.

Risk override writes are Gjallar-local DB writes. They never call Proxmox
mutation APIs.

Override payloads:

```json
{
  "risk_id": "deterministic-risk-item-id",
  "status": "acknowledged | suppressed",
  "reason": "operator note",
  "expires_at": 1770000000.0
}
```

Clear payload:

```json
{
  "risk_id": "deterministic-risk-item-id"
}
```

Read-only Proxmox/PBS evidence includes:

```text
VM inventory GET
node monitoring GET
snapshot list GET
task history GET
GET /cluster/backup
GET /cluster/backup-info/not-backed-up
PBS GET /admin/datastore
PBS GET /admin/datastore/{store}/snapshots
```

Gjallar-local evidence/configuration/operator state includes:

```text
platform_state.db / operational_vm_state
platform_state.db / operational_risk_thresholds
platform_state.db / operational_risk_overrides
```

`operational_vm_state` stores observed VM state timestamps such as
`status_since_at` and `last_running_at`. These values survive backend restarts
and make time-based risks possible even when Proxmox only exposes current state.

`operational_risk_thresholds` stores operator-configurable risk policy values.
This is a Gjallar-local policy mutation, not a Proxmox mutation.

`operational_risk_overrides` stores local acknowledge/suppress intent keyed by
the deterministic risk item `id`. Expired overrides are ignored by the dashboard
merge logic and invalid/non-finite/past expiration values are rejected.

Example top-level shape after acknowledge/suppress integration:

```json
{
  "status": "warning",
  "summary": {
    "total_risks": 50,
    "critical": 0,
    "warning": 30,
    "info": 20,
    "acknowledged": 1,
    "suppressed": 0,
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
  "risk_items": [],
  "suppressed_risk_items": []
}
```

## Risk checks

### Node status

- critical if a node is not reported as `online`.

### Storage capacity

Default thresholds:

- warning if storage usage is at or above 80%.
- critical if storage usage is at or above 90%.

These values are configurable through Gjallar threshold policy.

### Guest agent signal

- warning if a VM is running but `qemu-guest-agent` IP evidence is empty.
- This is a practical signal for guest-agent missing/unresponsive cases.

### Governance metadata

- info if a VM is missing required owner/team or environment taxonomy metadata.
- Accepted ownership signals use keys such as `owner`, `owned-by`/`owned_by`, `team`, `app-owner`, or `service-owner` with `:`, `=`, or `/` separators, or an owner/team marker in description/notes.
- Accepted environment signals use keys such as `env`, `environment`, or `stage`, or a simple environment tag such as `prod`, `dev`, `test`, `lab`, `infra`, `ops`, or `sandbox`.
- Free-form/incidental tags such as `linux` or `docker` are reported in evidence when metadata is incomplete, but they no longer clear the governance risk by themselves.

### Snapshot age

Default thresholds:

- warning if a snapshot is older than 14 days.
- critical if a snapshot is older than 30 days.
- `current` pseudo-snapshot is ignored.

These values are configurable through Gjallar threshold policy.

### Backup coverage

- warning if Proxmox `not-backed-up` evidence reports that a VM is not covered by configured backup jobs.
- This is stronger than task-history-only evidence because it checks schedule/job coverage directly.
- If a VM is explicitly uncovered by backup jobs, the dashboard shows `backup_coverage` and suppresses the less-specific `backup_recency` warning for that VM.

### Restore readiness / PBS direct API

- optional PBS evidence is collected through read-only PBS API calls when `PBS_API_URL`, `PBS_API_TOKEN_ID`, and `PBS_API_TOKEN_SECRET` are configured.
- Gjallar lists configured/discovered datastores and reads datastore snapshots, then normalizes `vm/<vmid>/<backup-time>` restore points by VMID.
- If PBS evidence is collected and a VM has no PBS restore point, the dashboard emits `restore_readiness` warning.
- If the latest PBS restore point is older than the configured backup threshold, the dashboard emits `restore_readiness` warning.
- If the latest PBS restore point is recent, PBS evidence satisfies backup recency and avoids a weaker task-history fallback warning.
- PBS collection failures or missing PBS config are represented as uncollected evidence rather than a false healthy signal.

### Backup recency fallback

Default threshold:

- warning if no successful `vzdump`/backup task evidence is found within 7 days.

This remains useful when schedule/PBS evidence exists but does not provide a
stronger answer, or when schedule/PBS evidence is unavailable. The days value is
configurable through Gjallar threshold policy.

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

## PBS restore readiness configuration

Optional environment variables:

```text
PBS_API_URL=https://pbs.example:8007/api2/json
PBS_API_TOKEN_ID=root@pam!gjallar
PBS_API_TOKEN_SECRET=<secret>
PBS_TLS_INSECURE=false
PBS_DATASTORES=store-a,store-b
```

If `PBS_DATASTORES` is omitted, Gjallar attempts read-only datastore discovery
through `GET /admin/datastore`. Secrets are never included in risk evidence.

## Risk acknowledge/suppress policy

1. Risk overrides are keyed by deterministic `risk_items[].id`.
2. `acknowledged` risks remain visible and include override metadata.
3. `suppressed` risks are hidden from the default visible risk list and counted in `summary.suppressed`.
4. `include_suppressed=true` returns suppressed items in `suppressed_risk_items` for review/clear flows.
5. Expired overrides are ignored. Invalid status, empty risk IDs, unknown fields, non-finite expiration values, and past expiration values are rejected.
6. Override writes are stored only in `operational_risk_overrides`; Proxmox remains a read-only evidence source.

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
- acknowledged/suppressed counts
- affected VM/node counts
- category counts, including `Backup coverage` and `Long stopped VM`
- risk item cards with evidence and recommendation
- current threshold source/defaults
- Risk Thresholds editor for storage/snapshot/backup/stopped policies
- Acknowledge/Suppress/Clear controls for each risk item
- override metadata such as reason, updated time, expiration, and actor
- suppressed risk review toggle backed by `include_suppressed=true`
- manual refresh and 60-second auto refresh

Threshold and override controls change only Gjallar-local DB state. They do not
mutate Proxmox resources.

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
- store/clear operator acknowledge/suppress overrides in `operational_risk_overrides`

Forbidden from this dashboard:

- VM delete/terminate
- start/shutdown/stop/reboot
- VM config PUT/POST
- snapshot delete
- backup job create/update/delete

## Validation

Last validation after risk acknowledge/suppress integration:

```text
backend focused risk override tests: passed
backend override store tests: passed
backend unittest discover -s tests: 62 tests passed
python compileall app tests: passed
frontend operationalRisk tests: passed
frontend all Node tests: passed
frontend lint: passed
frontend build: passed
alembic temp DB upgrade/downgrade/re-upgrade: passed
real dev DB alembic upgrade head: passed
terraform validate: passed
git diff --check: passed
independent pre-commit review: passed after requested fixes
live smoke: /health HTTP 200
live smoke: /api/operations/risks?include_suppressed=true HTTP 200
live smoke: PUT/list/clear temporary risk override HTTP 200
live smoke: temporary override cleared
```

Final smoke summary:

```text
LIVE_SMOKE_OK risks 50 suppressed 0
```

## Known follow-ups

- Add configurable taxonomy policy if the fixed defaults are not enough.
- Add PBS-specific capacity/restore assurance evidence if PBS API access is configured.
- Add safe action suggestion links that still require explicit approval.
- Consider a lower-level fail-closed follow-up so direct state-store callers must explicitly opt into missing reconciliation.
