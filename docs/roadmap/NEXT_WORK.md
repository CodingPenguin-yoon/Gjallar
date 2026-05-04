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

## Immediate next recommendations

1. Add owner/tag taxonomy instead of treating any tag as governance evidence.
2. Add PBS-specific capacity/restore assurance evidence if PBS API access is configured.
3. Add safe action suggestion links that still require explicit approval.
4. Add optional read-only SSH collector for evidence gaps.
5. Consider a lower-level fail-closed follow-up so direct state-store callers must explicitly opt into missing reconciliation.

## Why owner/tag taxonomy is next

The dashboard now detects infrastructure risks, keeps local history, protects VM
lifecycle state from stale/deleted/reused IDs, supports configurable thresholds,
and lets operators acknowledge or suppress known exceptions in Gjallar-local DB
state.

The next governance gap is data quality: the current governance risk treats any
explicit tag as a signal. Owner/team/environment taxonomy should make the policy
more useful by distinguishing meaningful ownership metadata from incidental tags.

Owner/tag taxonomy should define:

- accepted owner/team/environment tag keys;
- minimum metadata required before clearing a governance risk;
- how unknown or free-form tags should be reported;
- UI copy that explains exactly which metadata is missing.

## Later integrations

Only after the core VM operations product is stable:

- backup/report exports
- policy/compliance checks
- approval-based remediation
- Ansible/Terraform/OpenTofu integration where it supports VM operations directly
- optional read-only SSH collector for evidence unavailable through Proxmox/PBS APIs
- optional node agent only if API + DB + SSH collector cannot supply needed evidence safely
