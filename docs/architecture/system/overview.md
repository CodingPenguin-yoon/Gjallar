# System Overview

Status source: [current product status](../../current/README.md). Top-tab status index: [top tabs](../../current/top-tabs/README.md).

Gjallar is a human-facing Proxmox Operations Console. The current app provides read-only operational visibility, guided powered-off VM creation, network policy inspection/writes, read-only placement recommendations, file-backed job history, and job-derived risk summaries.

It is not currently a full DRS backend, migration execution engine, app deployment system, GitLab environment controller, CI/CD orchestrator, or LLM assistant product.

## Product Identity

| Area | Current identity |
|---|---|
| Product | Proxmox operations and risk console. |
| Source of truth for actual infrastructure | Proxmox actual VM/node/task/storage/network state. |
| Gjallar-owned operational data | Intent manifests, policy files, approval evidence, job status files, artifacts, and future target identity/policy/reconciliation data. |
| Safety posture | Read-only by default. Live mutation is limited to approval-gated Create VM native clone/config/post-check. |
| DRS Advisor | Target product direction, not current backend execution. |

## Active Routes

| Route | Component | Current domain |
|---|---|---|
| `/` | `Dashboard` | Cluster summary, node table, job/risk counts. |
| `/infra` | `InstanceList` | Read-only VM inventory grouped by node. |
| `/networks` | `NetworkPolicyScreen` | Live bridge policy view and IaC policy write. |
| `/create` | `CreateInstanceWizard` | Guided Create VM review, commit, native create. |
| `/placement` | `PlacementScreen` | Frontend read-only placement read model. |
| `/jobs` | `TaskBoard` | Read-only job/run and artifact inspection. |
| `/risks` | `OperationalRiskDashboard` | Read-only risk list derived from jobs. |

## Active Modules

| Layer | Module | Role |
|---|---|---|
| Frontend routing | `frontend/src/App.jsx` | Route shell, navigation, dashboard implementation. |
| Frontend API client | `frontend/src/services/apiV1.js` | `/api/v1` client and envelope unwrapping. |
| Frontend view models | `frontend/src/utils/*.js` | Domain normalization for inventory, placement, jobs, risks, network policy, and Create VM. |
| Backend API | `backend/app/api/v1/router.py` | `/api/v1` routes and job progress orchestration. |
| Read-only inventory | `backend/app/proxmox/inventory.py` | Fake/live Proxmox read-only adapter. |
| Proxmox mutation | `backend/app/proxmox/client.py` | Separate native mutation client used by Create VM only. |
| Create VM | `backend/app/vm_create/*` | Draft, preflight, plan, approval, GitOps manifest, native create, legacy Terraform helpers. |
| Network policy | `backend/app/network_policy.py` | IaC policy load/save and live bridge policy view. |
| Jobs/artifacts | `backend/app/jobs/*` | File-backed job status, artifacts, approval records. |
| Manifests | `backend/app/manifests/*` | Transitional static Create VM profile seed and manifest helpers. |

## Active Data Sources

| Data | Current source |
|---|---|
| Nodes, VMs, templates, storage, networks | Proxmox inventory adapter. Live when env is configured; fake read-only fallback otherwise. |
| Profiles | Transitional read-only `static_seed` data from `backend/app/manifests/loader.py`. DB seed is future. |
| Create VM artifacts | Generated per job under `GJALLAR_RUNS_ROOT`. |
| VMInstance desired-state manifests | IaC root under `manifests/vms/`, created by `execute`. |
| Network policy | IaC root under `manifests/networks/network-profiles.yaml`. |
| Jobs/Runs | `job_status.json` under `GJALLAR_RUNS_ROOT/<job_id>/`. |
| Risks/Alerts | Derived from `risks` arrays in job status records. |
| Placement recommendations | Frontend view model from inventory, jobs, and risks. No DRS backend route. |

## Non-Goals In Current Implementation

- No `/api/v1/drs/*` backend.
- No approved migration execution, DRS operation locks, migration UPID tracking, or reconciliation backend.
- No DB identity table, VM fingerprint table, policy table, or DRS audit table.
- No direct VM start/stop/reset/delete/snapshot controls.
- No first power-on, cloud-init smoke, guest-agent discovery, SSH smoke, or Ansible verification after Create VM.
- No Proxmox bridge creation/deletion/update from Gjallar.
- No active frontend Terraform plan/apply flow.
