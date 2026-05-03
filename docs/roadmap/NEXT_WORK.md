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
- `/risks` frontend Risk Dashboard and Risk Thresholds editor
- stale `operational_vm_state` cleanup/reconciliation and VMID reuse guard
- inventory completeness/scope guard for lifecycle reconciliation
- frontend risk utility tests

## Immediate next recommendations

1. Add risk suppress/acknowledge state.
2. Add owner/tag taxonomy instead of treating any tag as governance evidence.
3. Add PBS-specific capacity/restore assurance evidence if PBS API access is configured.
4. Add safe action suggestion links that still require explicit approval.
5. Consider a lower-level fail-closed follow-up so direct state-store callers must explicitly opt into missing reconciliation.

## Why risk acknowledge/suppress is next

The dashboard now detects infrastructure risks, keeps local history, and protects
VM lifecycle state from stale/deleted/reused IDs. The next operator-facing gap is
intent: some risks are known exceptions, maintenance windows, or accepted debt.

Risk acknowledge/suppress should add controlled local Gjallar state so operators
can record:

- who acknowledged or suppressed a risk;
- why it is acceptable;
- when suppression expires;
- whether the underlying evidence changed enough to require re-review.

## Later integrations

Only after the core VM operations product is stable:

- backup/report exports
- policy/compliance checks
- approval-based remediation
- Ansible/Terraform/OpenTofu integration where it supports VM operations directly
- optional read-only SSH collector for evidence unavailable through Proxmox/PBS APIs
- optional node agent only if API + DB + SSH collector cannot supply needed evidence safely
