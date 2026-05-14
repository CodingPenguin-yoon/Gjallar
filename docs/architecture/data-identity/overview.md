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
| Create VM intent | Gjallar IaC manifest | Created by `execute`; no live mutation by itself. |
| Create VM approval evidence | Gjallar artifacts/job details | File-backed under `GJALLAR_RUNS_ROOT`. |
| Network policy | Gjallar IaC policy file | Networks tab policy, not Proxmox network mutation. |
| Jobs/Runs | Gjallar job status files | Latest status per job id. |
| Risks/Alerts | Derived from Gjallar job risks | Not a standalone engine. |
| DRS identity/fingerprint/policy | Target future Gjallar DB | Not implemented. |

## Current File-Backed Parts

| Area | Current path/source | Current use |
|---|---|---|
| Job status | `GJALLAR_RUNS_ROOT/<job_id>/job_status.json` | Jobs/Runs list/detail, Dashboard active count, Risks/Alerts source. |
| Artifacts | `GJALLAR_RUNS_ROOT/<job_id>/*` | Create VM preflight, plan, manifest, diff, review summary, preview, observed-after evidence. |
| VMInstance manifests | IaC root `manifests/vms/<manifest_id>.yaml` | Desired-state record committed by `execute`. |
| Archived manifests | IaC root `manifests/archive/vms/<manifest_id>.yaml` | Archive path for unapplied manifests. |
| Network policy | IaC root `manifests/networks/network-profiles.yaml` | Networks tab policy view/edit. |

Job and artifact writers redact secrets before persistence.

## Current Create VM Fingerprint

Native create writes `observed_after.json` after Proxmox post-check. It includes a fingerprint hash derived from:

- `smbios1`
- `vmgenid`
- MAC addresses
- disk volume ids

This is current artifact evidence only. It is not a DB-backed identity record and is not reusable by current Placement/DRS execution, because no DRS backend exists.

## Target DB/Identity/Fingerprint/Policy

DRS Advisor target work needs a persistent identity layer before migration execution.

| Target table/record | Purpose | Current status |
|---|---|---|
| VM identity | Stable Gjallar-owned identity for a VM independent of one inventory fetch. | Not implemented. |
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

- No database-backed identity layer exists.
- No background inventory reconciler exists.
- No normalized DRS policy source exists.
- No DRS operation lock or stale-lock cleanup exists.
- Create VM artifacts can help future identity work but do not close the DRS identity gap by themselves.
- Jobs/Risks currently store latest job status, not an immutable audit log.
