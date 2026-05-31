# Data And Identity Overview

Status source: [current product status](../../current/README.md). Relevant top-tab statuses: [Create VM](../../current/top-tabs/04-create-vm.md), [Placement / DRS Advisor](../../current/top-tabs/05-placement-drs-advisor.md).

This document explains the boundary between Proxmox actual state and Gjallar-owned operational data.

## Proxmox Vs Gjallar Boundary

| Data kind | Current source of truth | Notes |
|---|---|---|
| Actual VM existence | Proxmox | Gjallar reads this through inventory and native create post-check. |
| Actual VM node/location | Proxmox | DRS execution rereads current state through fresh advisor checks and dedicated live Proxmox DRS evidence before migration. |
| Actual VM power status | Proxmox | Current Create VM success requires observed `stopped`. |
| Actual node status and load | Proxmox inventory adapter | Current point-in-time/read-only evidence. |
| Actual storage/network inventory | Proxmox inventory adapter | Storage, disk, and bridge evidence. |
| Create VM intent | Gjallar DB request record | Native create records request/result in DB. |
| Create VM approval evidence | Gjallar artifacts/job details | DB-backed in `job_runs` and `job_artifacts`. |
| Jobs/Runs | Gjallar DB job records | Latest status per job id. |
| Risks/Alerts | Derived from Gjallar job risks | Not a standalone engine. |
| DRS identity/fingerprint/policy | Gjallar DB plus current Proxmox evidence | Implemented as compact identity observations and migration policy records; Proxmox remains source of truth for actual state. |

## Current Gjallar-Owned Persistence

| Area | Current path/source | Current use |
|---|---|---|
| Job status | `job_runs` table | Jobs/Runs list/detail, Dashboard active count, Risks/Alerts source. |
| Artifacts | `job_artifacts` table | Create VM preflight, plan, manifest, diff, review summary, preview, observed-after evidence. |
| Create VM requests | `vm_create_requests` table | Latest Create VM request/result summary. |
| Created VMs | `vm_instances` table | Gjallar-owned record for VMs created through native Create VM. |
| DRS identities | `vm_identities` table | Compact stable fingerprint and locator evidence for DRS recommendation/check/execution gates. |
| DRS migration policies | `vm_migration_policies` table | Operator-owned policy memory: `unknown`, `allowed`, `restricted`, or `blocked`. |
| DRS operation locks | `operation_locks` table | VM identity, Proxmox locator, and route locks for DRS checks and execution. |
| DRS approvals/jobs/reconciliation | `drs_approval_packets`, `drs_migration_jobs`, `drs_reconciliation_events` tables | Approval packet binding, migration job execution state, UPID/task/post-check evidence, and open reconciliation events. |

Job and artifact writers redact secrets before persistence.

## Current Create VM Fingerprint

Native create writes `observed_after.json` after Proxmox post-check. It includes a fingerprint hash derived from:

- `smbios1`
- `vmgenid`
- MAC addresses
- disk volume ids

This is current create evidence and is copied into the `vm_instances` record for VMs created through the native Create VM path. DRS has a separate compact identity/fingerprint observation layer; Create VM records can support identity context but do not authorize DRS execution by themselves.

## Current DRS DB/Identity/Fingerprint/Policy

DRS Advisor now has a persistent identity, policy, approval/job, lock, and reconciliation substrate for Goals 2-6.

| Table/record | Purpose | Current status |
|---|---|---|
| VM identity | Stable Gjallar-owned identity for a VM independent of one inventory fetch. | Implemented as compact fingerprint/locator observation records for DRS evidence and gates. |
| Proxmox locator | Current/proven `(cluster_id, node_id, vmid)` locator and last observed evidence. | Implemented inside identity evidence and DRS recommendation/check artifacts. |
| Fingerprint | Stable hash from SMBIOS UUID, VM generation ID, MAC addresses, and disk volume ids. | Implemented for DRS identity evidence and direct post-check comparison. |
| Classification metadata | Owner, role, environment, criticality, richer DRS eligibility metadata. | Still limited; no metadata editor. |
| Placement policy | Allowed/restricted/blocked migration policy. | Implemented as `vm_migration_policies`; richer policy rules/full metadata editor remain deferred. |
| Approval record | Exact recommendation/final-precheck evidence approved by operator. | Implemented as checksummed `drs_approval_packets` plus artifacts. Approval creation does not start migration. |
| Operation lock | Active/released/stale/reconciliation-required locks for VM identity, locator, and route. | Implemented for DRS check and execution gates. |
| Operation/reconciliation | Migration UPID, task result, post-check, terminal/uncertain state, reconciliation event. | Implemented through `drs_migration_jobs`, `drs_reconciliation_events`, and read-only reconcile preview. No corrective mutation/background automation. |

## VMID Locator Rule

VMID alone is not a durable Gjallar identity. It is a Proxmox locator scoped by cluster and node/current inventory context.

Current code uses VMID for:

- `GET /api/v1/vms/{vmid}` lookup
- Create VM proposed VMID collision checks
- Create VM native create target id
- Proxmox post-check endpoint path

DRS execution combines VMID with:

- cluster identity
- current source node
- VM name and metadata
- fingerprint evidence
- last observed time
- policy classification

A stale VMID locator blocks migration execution until refreshed and matched to a Gjallar identity.

## Current Gaps And Risks

- DRS identity is compact and gate-oriented, not a full metadata/catalog system for all Proxmox VMs.
- No background inventory reconciler exists.
- No richer DRS policy rule engine or full metadata editor exists beyond current per-VM policy configuration.
- No stale-lock cleanup service or corrective reconciliation mutation exists.
- Create VM DB records can help future identity work but do not close the DRS identity gap by themselves.
- Jobs/Risks currently store latest job status, not an immutable audit log.
