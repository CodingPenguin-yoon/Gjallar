# Gjallar Next Work

## 1. Finish legacy cleanup

- remove or archive old Heimdall staging/GitLab documents
- keep user-facing copy aligned to `provision` / `VM operation`
- keep `/api/deploy` only as a compatibility endpoint; new calls should use `/api/provision`

## 2. Improve VM provisioning UX

- clarify each wizard step
- show selected node/template/storage/network summary before launch
- improve validation errors for static IP and missing fields
- rename Launch/Deploy copy to Provision/Create VM where appropriate

## 3. Strengthen lifecycle safety

- add confirmation for destructive actions
- add clearer task logs for start/shutdown/stop/reboot/delete
- verify final VM state after each lifecycle operation

## 4. Improve inventory performance model

Current state:

- blocking Proxmox inventory handlers run as sync `def`
- VM inventory uses a short TTL cache

Next steps:

- add singleflight-style request coalescing for duplicate refreshes
- add background inventory collection
- serve UI from cached inventory snapshots
- add per-node concurrency/rate limits

## 5. Phase 2 current state — Operational Risk Dashboard

Completed in the read-only dashboard slices:

- `GET /api/operations/risks` backend endpoint
- pure risk calculation module and tests
- VM metadata enrichment for guest-agent IP evidence and tags/description
- snapshot age checks
- backup task recency fallback checks
- Proxmox backup schedule coverage evidence through `/cluster/backup` and `/cluster/backup-info/not-backed-up`
- Gjallar-local `operational_vm_state` persistence for VM status history
- `long_stopped` risk category using persisted stopped history
- `/risks` frontend route and Risk Dashboard navigation tab
- frontend risk utility tests

Next Phase 2 improvements:

1. Add configurable thresholds for backup/snapshot/storage/stopped policies.
2. Add stale `operational_vm_state` cleanup/reconciliation and VMID reuse guard.
3. Add risk suppress/acknowledge state.
4. Add owner/tag taxonomy instead of treating any tag as governance evidence.
5. Add PBS-specific capacity/restore assurance evidence if PBS API access is configured.
6. Add safe action suggestion links that still require explicit approval.

## 6. Later integrations

Only after the core VM operations product is stable:

- backup/report exports
- policy checks
- approval-based remediation
- Ansible/Terraform/OpenTofu integration where it supports VM operations directly
- optional read-only SSH collector for evidence unavailable through Proxmox/PBS APIs
- optional node agent only if API + DB + SSH collector cannot supply needed evidence safely
