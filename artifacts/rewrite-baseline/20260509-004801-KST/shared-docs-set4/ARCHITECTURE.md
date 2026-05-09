# ARCHITECTURE

Last updated: 2026-05-09 00:42 KST

## Current target shape

```text
Frontend UI
  -> /api/v1 client
Backend FastAPI /api/v1
  -> manifests/profile/network/template schema
  -> jobs/artifacts store
  -> read-only Proxmox inventory adapter
  -> vm-create draft/preflight/plan/review/approval policy
  -> GitOps/apply executor only after explicit approval
```

## Backend target packages

- `app/api/v1`: router, response/error shape
- `app/manifests`: profile/network/template schema and loader
- `app/jobs`: job, approval, artifact models/store
- `app/proxmox`: read-only inventory/readiness adapter first
- `app/vm_create`: draft, preflight, planner, approval, gitops, executor
- `app/smoke`: Stage A smoke result models

## Frontend target areas

- Dashboard
- Infra Explorer
- Create VM
- Review & Confirm
- Jobs
- Risks

## Execution lanes

- Shared docs: `/mnt/hermes_data/프로젝트/Gjallar`
- Code repo: `codex-vm:/home/yoon/projects/Gjallar`
- Lock: `/mnt/hermes_data/프로젝트/Gjallar/.agent_lock/lock.json`
- Detailed implementation plan: `PRD/22_CODEBASE_REWRITE_EXECUTION_PLAN.md`

## Boundary

IaC/GitOps/apply/power-on is architecture target but not autonomous side effect. It requires explicit approval and live inventory gates.
