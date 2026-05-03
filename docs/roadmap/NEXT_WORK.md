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
- frontend risk utility tests

## Immediate next recommendations

1. Add stale `operational_vm_state` cleanup/reconciliation and VMID reuse guard.
2. Add risk suppress/acknowledge state.
3. Add owner/tag taxonomy instead of treating any tag as governance evidence.
4. Add PBS-specific capacity/restore assurance evidence if PBS API access is configured.
5. Add safe action suggestion links that still require explicit approval.

## Why stale cleanup / VMID reuse guard is next

Gjallar now stores historical VM state in its own DB. That is the right foundation
for time-based risks, but long-lived state needs lifecycle hygiene:

- deleted VMs should not stay as active risk candidates forever;
- recreated VMs with reused VMIDs should not inherit stale stopped history;
- reconciliation should be conservative and evidence-based.

This is the most natural next hardening step before adding more policy layers.

## Later integrations

Only after the core VM operations product is stable:

- backup/report exports
- policy/compliance checks
- approval-based remediation
- Ansible/Terraform/OpenTofu integration where it supports VM operations directly
- optional read-only SSH collector for evidence unavailable through Proxmox/PBS APIs
- optional node agent only if API + DB + SSH collector cannot supply needed evidence safely
