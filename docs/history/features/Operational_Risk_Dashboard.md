# Operational Risk Dashboard

> Historical note:
> This `docs/history/features` file is historical implementation/planning context, not current product source of truth or current implementation status.
> Current MVP product source of truth is [`../../product/prd/drs-advisor/`](../../product/prd/drs-advisor/README.md); current implemented status is [`../../product/status/current.md`](../../product/status/current.md).
> PBS/Veeam references in this file are backup evidence or future integration context only. DRS Advisor implementation assumptions must come from Proxmox official docs and live Proxmox state.

## Purpose

Phase 2 builds an Operational Risk Dashboard for Proxmox operations. Gjallar
reads Proxmox/PBS evidence, stores Gjallar-owned observation/configuration/
operator-intent state in its local platform-state database, and calculates
operational risks without mutating Proxmox resources.

```text
Observe → Govern → Act
```

The current implementation is `Observe + Govern`: it detects risk, lets
operators tune local policy thresholds, records local acknowledge/suppress
state for known exceptions, and reports read-only compliance policy findings.
The dashboard still does not stop, start, reboot, delete, or reconfigure
Proxmox VMs.

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
optional SSH guest evidence through fixed read-only command IDs when explicitly enabled
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
Missing-VM reconciliation is fail-closed: direct/default state-store calls only
record observed VMs, and missing reconciliation requires an explicit complete
cluster snapshot signal (`reconcile_missing is True`). Legacy inventory cache
entries without explicit `complete=True` are treated as incomplete evidence.

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
      "compliance": 3,
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

### Policy / Compliance baseline

- info if a `prod`/`production` VM has owner/environment metadata but does not declare an accepted explicit backup/RPO profile tag.
- Accepted profile keys reuse the RPO/RTO profile metadata contract: `backup-profile`, `recovery-profile`, `rpo-profile`, and `rpo-rto-profile` with `:`, `=`, or `/` separators.
- Accepted profile values are `critical`, `standard`, and `relaxed`.
- The default RPO/RTO profile still works for backward compatibility, but the compliance finding tells operators which production VMs need explicit policy metadata.
- Dashboard-level evidence includes `compliance_policy_collected`, `compliance_policy_id`, `compliance_policy_source`, `compliance_policy_rules`, and `compliance_policy_vms`.

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
- If the latest PBS restore point is older than the VM's active RPO profile window, the dashboard emits `restore_readiness` warning.
- If the latest PBS restore point is recent for the VM's active RPO profile, PBS evidence satisfies backup recency and avoids a weaker task-history fallback warning.
- PBS collection failures or missing PBS config are represented as uncollected evidence rather than a false healthy signal.

### RPO/RTO profile policy

RPO/RTO profile reporting is read-only and backward-compatible:

- Default profile: `profile_id=default`, source `default`, `rpo_hours = backup_warning_days * 24`, and `restore_drill_max_age_days = 90`. This preserves the existing 7-day backup readiness default when threshold policy is unchanged.
- VM override profiles are read from Proxmox VM metadata tags only; Gjallar does not mutate the VM. Supported keys are `backup-profile`, `recovery-profile`, `rpo-profile`, and `rpo-rto-profile` with `:`, `=`, or `/` separators.
- Supported override values are `critical` (`RPO 24h`, restore drill `30d`), `standard` (`RPO 168h`, restore drill `90d`), and `relaxed` (`RPO 720h`, restore drill `180d`).
- Risk evidence includes `rpo_rto_profile_id`, `rpo_rto_profile_source`, `rpo_hours`, and `restore_drill_max_age_days` so operators can see which policy produced a warning.
- Dashboard-level evidence includes `rpo_rto_profile_collected`, `rpo_rto_profile_vms`, and `rpo_rto_profile_sources`.

Profile thresholds are applied consistently to PBS restore point staleness, restore drill staleness, and the `backup_recency` task-history fallback when PBS restore readiness evidence is uncollected.

### Backup recency fallback

Default profile behavior:

- warning if no successful `vzdump`/backup task evidence is found within the active profile RPO window. With default threshold policy this remains 7 days.

This remains useful when schedule/PBS evidence exists but does not provide a
stronger answer, or when schedule/PBS evidence is unavailable. The fallback uses
the active VM RPO profile rather than a separate global backup window.

### Optional read-only SSH guest evidence

- disabled by default; missing configuration is reported as `ssh_guest_collected=false`, `ssh_guest_vms=null`, and `ssh_guest_failed_vms=null`.
- when explicitly enabled, Gjallar only accepts predefined read-only command IDs such as `os_release`, `disk_usage`, and `qemu_guest_agent_status`; arbitrary shell text is rejected before execution.
- blocked/failed configured SSH evidence is visible as an informational `guest_ssh_evidence` risk so failed collection is not confused with a healthy guest state.
- raw SSH credentials/private keys/passwords are out of contract. Errors are redacted before being returned as evidence.
- SSH evidence collection never performs guest mutation/remediation and never calls Proxmox/PBS mutation APIs.

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

## Optional read-only SSH collector configuration

The SSH collector is off unless `GJALLAR_SSH_COLLECTOR_ENABLED=true` and a
`GJALLAR_SSH_COLLECTOR_TARGETS_JSON` map are provided by the operator. Target
entries are keyed by `node/vmid` and may point at an already-approved SSH
identity path; private key material and passwords must not be stored in Gjallar
configuration or docs.

```text
GJALLAR_SSH_COLLECTOR_ENABLED=false
GJALLAR_SSH_COLLECTOR_COMMANDS=os_release,disk_usage,qemu_guest_agent_status
GJALLAR_SSH_COLLECTOR_TARGETS_JSON={"node-a/101":{"host":"guest-a.invalid","user":"readonly","key_path":"/path/to/approved/read-only/key"}}
```

Use `StrictHostKeyChecking=yes` compatible host setup before enabling real
targets. Bad JSON, missing targets, missing host, SSH failures, and unknown
command IDs fail closed as uncollected/blocked evidence.

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
- category counts, including `Backup coverage`, `Compliance`, `Restore readiness`, `Restore drill`, and `Long stopped VM`
- risk item cards with evidence, recommendation, and RPO/RTO profile context when present
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
- optional PBS datastore/snapshot GET

Allowed Gjallar-local writes:

- upsert current VM observation state into `operational_vm_state`
- store/reset operator threshold policy in `operational_risk_thresholds`
- store/clear operator acknowledge/suppress overrides in `operational_risk_overrides`
- store operator-recorded restore drill evidence in Gjallar-local state

Forbidden from this dashboard:

- VM delete/terminate
- start/shutdown/stop/reboot
- VM config PUT/POST
- snapshot delete
- backup job create/update/delete

## Validation

Last validation after lower-level fail-closed reconciliation cleanup:

```text
TDD RED/GREEN: default no missing reconciliation, explicit complete-snapshot reconciliation, legacy cached inventory without complete metadata fail-closed, literal True reconciliation intent for service/store boundaries
focused risk-state tests: 15 passed
backend unittest discover -s tests -v: 111 tests passed
backend compileall app tests: passed
frontend operationalRisk Node regression: passed
frontend lint/build: passed
git diff --check: passed
static scan: STATIC_SCAN_OK set5_added_lines=248 invariants=fail_closed_no_secret_like_patterns
independent review: passed; no blockers
commit/push: not run; explicit user approval required
```

## Known follow-ups

- Add configurable taxonomy policy if the fixed defaults are not enough.
- Decide whether to commit/push the verified-but-uncommitted Set 1~5 working tree.
- Next product Set candidate: Policy / Compliance.
