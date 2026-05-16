# Risks / Alerts Architecture

Status source: [current product status](../../current/README.md). Relevant top-tab status: [Risks/Alerts](../../current/top-tabs/07-risks-alerts.md).

Risks/Alerts is the `/risks` route. It is a read-only view over risks derived from job status records.

## Current Route And Component

| Concern | Current implementation |
|---|---|
| Route | `/risks` |
| Component | `frontend/src/components/OperationalRiskDashboard.jsx` |
| View model | `frontend/src/utils/risksScreen.js` and `buildRisksViewModel()` |
| Backend source | `GET /api/v1/risks` in `backend/app/api/v1/router.py` |
| Mutation controls | None |

## Current API

| API | Purpose |
|---|---|
| `GET /api/v1/risks` | Flatten risk entries from DB-backed job records. |

The backend loops through `list_job_runs()` and emits one risk summary for each dict in a job's `risks` array.

## Current Risk Shape

Current backend risk rows include:

| Field | Meaning |
|---|---|
| `risk_id` | `<job_id>:<risk_code>` fallback identity. |
| `job_id` | Source job id. |
| `job_type` | Source job type, currently primarily `vm_create`. |
| `job_status` | Source job status. |
| `level` | Risk level from job risk entry, usually red/yellow. |
| `code` | Machine-readable risk code from preflight/plan. |
| `message` | Human-readable explanation. |
| `detail` | Risk details when present. |
| `artifacts_url` | Link to job artifact metadata endpoint. |

The frontend normalizes unknown/missing levels to `unknown` and sorts risks by severity: red, yellow, unknown, green.

## Current Red/Yellow Behavior

Risks originate in Create VM preflight/plan logic:

| Level | Current behavior in Create VM |
|---|---|
| Red | Blocks approval and live native create. |
| Yellow | Requires operator acknowledgement when approval allows it. |
| Green | Mostly represented as passing checks, not usually emitted as `/risks` rows. |
| Unknown | UI fallback for malformed or missing level. |

Examples of current Create VM risk sources:

- unknown or disabled profile
- hardware outside profile limits
- template unavailable or mismatched
- template cloud-init or guest-agent readiness missing when required
- template disk larger than requested disk
- target node unavailable
- storage unavailable
- bridge missing/inactive
- VMID/name collisions
- static IP/prefix/gateway missing or invalid
- static IP already observed
- DHCP discovery warning
- IaC readiness blockers

## Not A Standalone Risk Engine

Current Risks/Alerts does not:

- poll Proxmox independently
- evaluate DRS policy
- maintain alert lifecycle state
- deduplicate over time across jobs
- acknowledge or resolve alerts
- write policy or job state
- execute remediation

It is a read-only projection of current job risk arrays.

## Target DRS Blockers

Target DRS Advisor should extend risk coverage with blocker taxonomy such as:

| Target blocker | Current status |
|---|---|
| `identity_mismatch` | Not implemented. |
| `unclassified_vm` | Not implemented. |
| `metadata_incomplete` | Not implemented. |
| `policy_restricted` / `policy_blocked` | Not implemented. |
| `route_unknown` / `route_blocked` | Not implemented. |
| `storage_constraint_unverified` | Only frontend Placement read model uses a similar advisory; no backend DRS risk. |
| `network_bridge_evidence_missing` / `target_bridge_not_found` | Only frontend Placement read model uses similar blockers; no backend DRS risk. |
| `stale_lock` | Not implemented. |
| `migration_timeout` | Not implemented. |
| `needs_reconciliation` | Create VM can record this status; no DRS reconciliation backend exists. |

DRS blockers should identify source, blocked action, VM identity, evidence artifact, and required operator resolution. That is future work.
