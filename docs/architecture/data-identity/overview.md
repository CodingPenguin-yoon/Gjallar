# Data And Identity Overview

Status source: [current product status](../../current/README.md). Relevant top-tab statuses: [Create VM](../../current/top-tabs/04-create-vm.md), [Placement / DRS Advisor](../../current/top-tabs/05-placement-drs-advisor.md).

This document explains the boundary between Proxmox actual state and Gjallar-owned operational data.

## Proxmox Vs Gjallar Boundary

| Data kind | Current source of truth | Notes |
|---|---|---|
| Actual VM existence | Proxmox | Gjallar reads this through inventory and native create post-check. |
| Actual VM node/location | Proxmox | DRS target must reread immediately before migration. |
| Actual VM power status | Proxmox | Current Create VM success requires observed `stopped`. |
| Actual node status and load | Proxmox inventory adapter | Current point-in-time/read-only evidence. |
| Actual storage/network inventory | Proxmox inventory adapter | Storage, disk, and bridge evidence. |
| Create VM intent | Gjallar DB request record | Native create records request/result in DB. |
| Create VM approval evidence | Gjallar artifacts/job details | DB-backed in `job_runs` and `job_artifacts`. |
| Network policy | Gjallar IaC policy file | Networks tab policy, not Proxmox network mutation. |
| Jobs/Runs | Gjallar DB job records | Latest status per job id. |
| Risks/Alerts | Derived from Gjallar job risks | Not a standalone engine. |
| DRS identity/fingerprint/policy | Target future Gjallar DB | Not implemented. |

## Current Gjallar-Owned Persistence

| Area | Current path/source | Current use |
|---|---|---|
| Job status | `job_runs` table | Jobs/Runs list/detail, Dashboard active count, Risks/Alerts source. |
| Artifacts | `job_artifacts` table | Create VM preflight, plan, manifest, diff, review summary, preview, observed-after evidence. |
| Create VM requests | `vm_create_requests` table | Latest Create VM request/result summary. |
| Created VMs | `vm_instances` table | Gjallar-owned record for VMs created through native Create VM. |
| Network policy | IaC root `manifests/networks/network-profiles.yaml` | Networks tab policy view/edit. |

Job and artifact writers redact secrets before persistence.

## Current Create VM Fingerprint

Native create writes `observed_after.json` after Proxmox post-check. It includes a fingerprint hash derived from:

- `smbios1`
- `vmgenid`
- MAC addresses
- disk volume ids

This is current create evidence and is copied into the `vm_instances` record for VMs created through the native Create VM path. It is not yet a full DRS identity/fingerprint layer, because no DRS backend exists.

## Target DB/Identity/Fingerprint/Policy

DRS Advisor target work needs a persistent identity layer before migration execution.

| Target table/record | Purpose | Current status |
|---|---|---|
| VM identity | Stable Gjallar-owned identity for a VM independent of one inventory fetch. | Partially implemented for native Create VM-created VMs in `vm_instances`; not generalized to all inventory/DRS. |
| Proxmox locator | Current/proven `(node_id, vmid)` locator and last observed time. | Not implemented as DB. |
| Fingerprint | Last known fingerprint hash and evidence source. | Artifact-only in Create VM. |
| Classification metadata | Owner, role, environment, criticality, DRS eligibility. | Not implemented. |
| Placement policy | Allowed/restricted nodes, anti-affinity, exclusions, windows. | Not implemented for DRS. |
| Approval record | Exact recommendation evidence approved by operator. | Not implemented for DRS. |
| Operation lock | Active/stale locks for VM/source/target. | Not implemented. |
| Operation/reconciliation | Migration UPID, post-check, terminal/uncertain state. | Not implemented. |

## VMID Locator Rule

VMID alone is not a durable Gjallar identity. It is a Proxmox locator scoped by cluster and node/current inventory context.

Current code uses VMID for:

- `GET /api/v1/vms/{vmid}` lookup
- Create VM proposed VMID collision checks
- Create VM native create target id
- Proxmox post-check endpoint path

Target DRS must combine VMID with:

- cluster identity
- current source node
- VM name and metadata
- fingerprint evidence
- last observed time
- policy classification

A stale VMID locator must block migration execution until refreshed and matched to a Gjallar identity.

## Current Gaps And Risks

- No generalized database-backed identity layer exists for all Proxmox VMs.
- No background inventory reconciler exists.
- No normalized DRS policy source exists.
- No DRS operation lock or stale-lock cleanup exists.
- Create VM DB records can help future identity work but do not close the DRS identity gap by themselves.
- Jobs/Risks currently store latest job status, not an immutable audit log.
