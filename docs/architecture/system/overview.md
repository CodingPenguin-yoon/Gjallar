# System Overview

Status source: [current product status](../../current/README.md). Top-tab status index: [top tabs](../../current/top-tabs/README.md).

Gjallar is a human-facing Proxmox Operations Console. The current app provides operational visibility, a gated stopped-VM start action, guided VM creation with stopped or boot-and-verify policies, read-only network readiness evidence, read-only DRS Advisor Phase 1 recommendations, DB-backed job history, and job-derived risk summaries.

It is not currently a full DRS backend, migration execution engine, app deployment system, GitLab environment controller, CI/CD orchestrator, or LLM assistant product.

## Product Identity

| Area | Current identity |
|---|---|
| Product | Proxmox operations and risk console. |
| Source of truth for actual infrastructure | Proxmox actual VM/node/task/storage/network state. |
| Gjallar-owned operational data | Create VM requests/VM records, approval evidence, job records, artifacts, and future target identity/policy/reconciliation data. |
| Safety posture | Read-only by default. Live mutation is limited to approval-gated Create VM native clone/config/power-policy post-check and acknowledgement-gated start for stopped non-template VMs. |
| DRS Advisor | Read-only Phase 1 recommendations, not current backend execution. |

## Active Routes

| Route | Component | Current domain |
|---|---|---|
| `/` | `Dashboard` | Cluster summary, node table, job/risk counts. |
| `/infra` | `InstanceList` | VM inventory grouped by node, plus gated Start for stopped non-template VMs. |
| `/networks` | `NetworkReadinessScreen` | Read-only Network Readiness / migration pre-check visualization. |
| `/create` | `CreateInstanceWizard` | Guided Create VM review, approval, native create. |
| `/drs` | `DrsAdvisorScreen` | Backend-owned read-only DRS Advisor Phase 1 read model. |
| `/jobs` | `TaskBoard` | Read-only job/run and artifact inspection. |
| `/risks` | `OperationalRiskDashboard` | Read-only risk list derived from jobs. |

## Active Modules

| Layer | Module | Role |
|---|---|---|
| Frontend routing | `frontend/src/App.jsx` | Route shell, navigation, dashboard implementation. |
| Frontend API client | `frontend/src/services/apiV1.js` | `/api/v1` client and envelope unwrapping. |
| Frontend view models | `frontend/src/utils/*.js` | Domain normalization for inventory, DRS Advisor, jobs, risks, network readiness, and Create VM. |
| Backend API | `backend/app/api/v1/router.py` | `/api/v1` routes and job progress orchestration. |
| DRS Advisor | `backend/app/drs/*` | Read-only Phase 1 recommendation calculation. |
| Read-only inventory | `backend/app/proxmox/inventory.py` | Fake/live Proxmox read-only adapter. |
| Proxmox mutation | `backend/app/proxmox/client.py` | Separate native mutation client used by gated mutation paths only. |
| Create VM | `backend/app/vm_create/*` | Draft, preflight, plan, approval, manifest evidence, and native create. |
| VM actions | `backend/app/vm_actions/*` | Existing-VM action helpers kept separate from Create VM and read-only inventory. |
| Jobs/artifacts | `backend/app/jobs/*` | DB-backed job status, artifacts, approval records. |
| Database | `backend/app/db/*` | SQLAlchemy/Alembic connection, Create VM profile repository, and manual seed command. |
| Manifests | `backend/app/manifests/*` | Initial Create VM profile seed-definition data and manifest helpers. |

## Active Data Sources

| Data | Current source |
|---|---|
| Nodes, VMs, templates, storage, networks | Proxmox inventory adapter. Live when env is configured; fake read-only fallback otherwise. |
| Profiles | `create_vm_profiles` DB table through `GJALLAR_DATABASE_URL`; initial rows are manual `db_seed` presets and disabled/archived rows are hidden. |
| Create VM artifacts | Generated per job into the `job_artifacts` table. |
| Create VM records | `vm_create_requests` and `vm_instances` tables. |
| Jobs/Runs | `job_runs` rows plus `job_artifacts`, including `vm_create` and `vm_start` jobs. |
| Risks/Alerts | Derived from `risks` arrays in job status records. |
| DRS Advisor recommendations | Backend read-only calculator from inventory and job-derived risks. |

## Non-Goals In Current Implementation

- No Networks API write path, YAML persistence, DB migration, or Proxmox network mutation.
- No approved migration execution, DRS operation locks, migration UPID tracking, or reconciliation backend.
- No DB identity table, VM fingerprint table, policy table, or DRS audit table.
- No direct VM stop/reset/delete/snapshot controls. Existing-VM start is the only current power action and is gated to stopped non-template VMs.
- No SSH smoke, Ansible verification, or app bootstrap after Create VM. First boot, guest-agent IP discovery, and cloud-init completion exist only when the request uses `boot_and_verify`.
- No Proxmox bridge creation/deletion/update from Gjallar.
- No Terraform plan/apply route surface.
