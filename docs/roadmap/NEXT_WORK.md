# Gjallar Next Work

## Completed baseline

### Phase 1 — VM Operations Console MVP

Completed:

- Proxmox inventory screen information structure
- VM detail drawer/page
- lifecycle action safety guardrails
- VM provisioning UX cleanup around `/api/provision`
- task/log UX cleanup
- node/storage monitoring signals
- provisioning readiness/resource/template preflight
- template disk-size preflight
- actual Create VM end-to-end smoke

### Phase 2 — Operational Risk Dashboard

Completed:

- `GET /api/operations/risks` backend endpoint
- pure risk calculation module and tests
- VM metadata enrichment for guest-agent IP evidence and tags/description
- snapshot age checks
- backup task recency fallback checks
- Proxmox backup schedule coverage evidence through `/cluster/backup` and `/cluster/backup-info/not-backed-up`
- Gjallar-local `operational_vm_state` persistence for VM status history
- `long_stopped` risk category using persisted stopped history
- DB-backed configurable thresholds for backup/snapshot/storage/stopped policies
- threshold API: `GET/PUT/DELETE /api/operations/risks/thresholds`
- `/api/operations/risks` response `threshold_config`
- stale `operational_vm_state` cleanup/reconciliation and VMID reuse guard
- inventory completeness/scope guard for lifecycle reconciliation
- risk acknowledge/suppress local override store/API/merge flow
- override API: `GET/PUT /api/operations/risks/overrides` and `POST /api/operations/risks/overrides/clear`
- `/api/operations/risks?include_suppressed=true` suppressed review flow
- `/risks` frontend Risk Dashboard, Risk Thresholds editor, and Acknowledge/Suppress/Clear controls
- frontend risk utility tests
- owner/team/environment taxonomy governance checks
- PBS direct API restore readiness evidence and `restore_readiness` risk
- PBS datastore health/capacity evidence and Gjallar-local restore drill records
- RPO/RTO profile reporting for PBS restore readiness, restore drill staleness, and backup-recency fallback
- optional read-only SSH collector contract, disabled-by-default evidence fields, allowlist blocking, redaction, and `guest_ssh_evidence` failure visibility
- safe action suggestion links/metadata that stay proposal-only and approval-required
- lower-level fail-closed reconciliation guard: state-store reconciliation requires explicit literal `True`, legacy cache without `complete=True` is incomplete, and direct/default callers do not mark omitted VMs missing
- Policy / Compliance baseline: prod/production VMs now get an info-level `compliance` risk when they lack an explicit accepted backup/RPO profile tag

## Immediate next recommendations

1. Decide whether to commit/push the verified-but-uncommitted Set 1~6 working tree.
2. Consider configurable taxonomy/profile policy storage if VM metadata tags are not enough.
3. If real guest SSH targets are later approved, add operator-runbook smoke for known-host setup and read-only identity rotation.
4. Next product Set candidate: Change Journal / Report.

## PBS restore readiness baseline

The dashboard can optionally collect PBS datastore snapshots through read-only API
calls and correlate VM restore points by VMID. When PBS evidence is collected, a
recent PBS restore point satisfies backup recency. Missing or stale PBS restore
points produce `restore_readiness` warnings instead of relying only on Proxmox
task-history fallback. Missing PBS configuration leaves the evidence uncollected
rather than pretending the restore state is healthy. VM-specific RPO/RTO profile
evidence now controls the restore point age window, restore drill staleness
window, and task-history fallback window.

## Owner/tag taxonomy baseline

The dashboard now detects infrastructure risks, keeps local history, protects VM
lifecycle state from stale/deleted/reused IDs, supports configurable thresholds,
lets operators acknowledge or suppress known exceptions in Gjallar-local DB
state, and distinguishes required owner/team/environment metadata from incidental
tags.

The fixed baseline policy is intentionally simple: a VM clears governance risk
only when it has both an owner/team signal (for example `owner`, `owned-by`/`owned_by`, or `team`) and an environment signal. Unknown or
free-form tags can remain on the VM, but they are treated as incidental evidence
rather than ownership metadata.

## Policy / Compliance baseline

The first policy/compliance slice is intentionally read-only and metadata-based.
A VM with `env:prod`/`env:production` should declare an explicit backup/RPO
profile using `backup-profile`, `recovery-profile`, `rpo-profile`, or
`rpo-rto-profile` with one of `critical`, `standard`, or `relaxed`. Missing or
invalid explicit production profile metadata creates an informational
`compliance` risk; Gjallar does not mutate Proxmox tags automatically.

## Later integrations

Only after the core VM operations product is stable:

- backup/report exports
- configurable policy/compliance storage/editor
- approval-based remediation
- Ansible/Terraform/OpenTofu integration where it supports VM operations directly
- optional node agent only if API + DB + SSH collector cannot supply needed evidence safely
