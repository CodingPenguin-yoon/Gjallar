# DRS Recommendation And Execution

Status source: [current product status](../../current/README.md). Relevant top-tab status: [Placement / DRS Advisor](../../current/top-tabs/05-placement-drs-advisor.md).

This document describes DRS recommendation and execution boundaries after Goals 1-6.

## Current Baseline

Current `/drs` UI reads backend DRS summary/recommendation/detail/check endpoints, uses manual per-VM migration policy endpoints, and creates local approval packet/job intents. It exposes no live migration execution controls. Backend DRS now stores identity/policy evidence, operation locks, approval packets, migration job state, UPID/task/post-check evidence, and reconciliation events behind operator-only API routes.

Recommendation/detail/check output is Proxmox-read-only and remains `read_only=true`, `executable=false`, and `allowed_actions=[]`. It may persist Gjallar-local identity observation evidence.

## Target Recommendation Model

A target DRS recommendation should be a backend-owned record or read model.

| Field group | Target content |
|---|---|
| Recommendation identity | Stable recommendation id, generated time, evidence version/hash. |
| VM identity | Gjallar VM identity id, Proxmox VMID, source node, current fingerprint, identity confidence. |
| Candidate move | Source node, target node, intended migration mode, estimated effect. |
| Evidence | CPU/memory/load windows, storage compatibility, bridge/network compatibility, HA/lock/current task state. |
| Policy | Allowed target groups, exclusions, anti-affinity, maintenance windows, operator restrictions. |
| Blockers | Normalized red/yellow blockers with machine-readable codes. |
| Execution availability | Recommendation/check output always returns false. Narrow execution availability exists only through a stored approval/job execution route after fresh gates. |

## Approval And Final Pre-Check

Approval records the exact recommendation and final-precheck evidence version in local approval/job/artifact rows. Approval packet creation does not start migration.

Immediately before migration, the execute route rereads current state and verifies VM locator, Gjallar identity/fingerprint, task conflicts, power/status compatibility, source/target health, storage/network compatibility, policy permission, locks, and absence of red blockers.

If final pre-check fails, migration must not start.

## Migration Execution

The implemented execution path validates stored approval/job bindings and checksums, creates operation locks, starts Proxmox migration through the dedicated DRS client, records UPID, polls task state, post-checks VM location/status/fingerprint plus active-task evidence, and then records `completed` or `needs_reconciliation`.

Locks cover VM identity, Proxmox locator, and source-to-target route. `active`, `stale`, and `reconciliation_required` locks block or require reconciliation. Locks release only after verified post-check success; otherwise they become `reconciliation_required`.

## Target Jobs/Risks Integration

DRS execution appears in Jobs/Runs as `drs_migration` job evidence. Risks/Alerts still use job-derived risk summaries and do not yet have a full DRS blocker taxonomy.

## Remaining Gaps

- Live execute UI, corrective reconcile UI, and broad approval-to-execute controls.
- Richer policy rule/full metadata editor beyond current per-VM migration policy configuration.
- Corrective reconciliation mutation or Reconcile Now execution.
- Background reconciliation automation or automatic DRS.
- Broad or repeated live DRS migration smoke evidence beyond the approved VMID
  `140` run.
- Recommendation-level approve/migrate/live-migrate aliases remain intentionally absent.
