# Gjallar Documentation Index

Gjallar is being realigned from the old Heimdall staging/GitLab deployment codebase into a Proxmox VM operations and monitoring console.

## Current documentation rule

The shared storage project folder is the source of truth for product direction and active state:

```text
/mnt/hermes_data/프로젝트/Gjallar
```

Read that folder first, especially:

1. `README.md`
2. `CURRENT_STATE.md`
3. `TASKS.md`
4. `DECISIONS.md`
5. `RUNBOOK.md`

## Active scope

Current Gjallar scope:

- Proxmox inventory
- VM creation from templates
- basic VM lifecycle management
- instance/node/storage monitoring
- task and log tracking for long-running operations

Current non-goals:

- GitLab integration
- CI/CD orchestration
- staging host pools
- Deploy Staging
- app deployment from repositories
- webhook-driven deployment automation

## Active repo docs

- `architecture/VM_OPERATIONS_ARCHITECTURE.md`
- `architecture/VM_PROVISIONING_CONTRACT.md`
- `features/VM_lifecycle_action_safety.md`
- `features/Provisioning_Preflight_Readiness.md`
- `operations/RUNBOOK.md`
- `roadmap/NEXT_WORK.md`

Old staging/GitLab documents were removed from active docs. If this repo's docs and shared storage disagree, follow shared storage.
