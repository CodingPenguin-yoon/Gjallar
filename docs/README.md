# Gjallar Documentation Index

> Gjallar is a Proxmox Operations & Risk Console.

Product direction:

```text
Gjallar = Observe / Govern / Act for Proxmox
```

Short positioning:

```text
vCenter-like auxiliary operations layer + operational risk dashboard for Proxmox
```

---

## Source of truth

Product direction and current project state are tracked first in shared storage:

```text
/mnt/hermes_data/프로젝트/Gjallar
/mnt/hermes_data/프로젝트/AI_Homelab_Control_Plane_방향성.md
```

Read these before implementation work:

1. `/mnt/hermes_data/프로젝트/Gjallar/README.md`
2. `/mnt/hermes_data/프로젝트/Gjallar/CURRENT_STATE.md`
3. `/mnt/hermes_data/프로젝트/Gjallar/TASKS.md`
4. `/mnt/hermes_data/프로젝트/Gjallar/DECISIONS.md`
5. `/mnt/hermes_data/프로젝트/Gjallar/ROADMAP.md`
6. `/mnt/hermes_data/프로젝트/Gjallar/RUNBOOK.md`

---

## Active scope

### Observe

- Proxmox node / VM / LXC / template / storage / network inventory
- VM state, IP, guest-agent signal, resource usage summary
- task/log tracking
- dashboard summaries for daily operations

### Govern

- backup coverage / recency risk
- snapshot age risk
- guest-agent risk
- storage capacity risk
- owner/environment/tag governance risk
- long-stopped VM risk with Gjallar-local state history
- configurable operational risk thresholds stored in Gjallar DB

### Act

- VM provisioning through `/api/provision`
- readiness/resource/template preflight
- lifecycle action safeguards
- task-based execution and verification
- future approval-based remediation

---

## Non-goals

The following are not Gjallar's core scope:

- GitLab/GitHub project inventory
- CI/CD pipeline orchestration
- staging host pool ownership
- source repository app deploy
- webhook-driven deployment automation
- Codex/Claude/OpenCode worker task orchestration
- LLM provider/context/memory/agent loop ownership

Those belong to Heimdall or Hermes.

---

## Relationship with Heimdall

```text
Gjallar provides Proxmox state, risk evidence, policy, and safe VM operations.
Heimdall executes DevOps and agent work on prepared infrastructure.
Hermes coordinates both.
```

Target flow:

```text
Hermes → Gjallar provision/risk plan → user approval → Gjallar VM operation/bootstrap → Heimdall worker/staging registration → Heimdall task execution
```

Ownership boundary:

```text
VM/Proxmox/Terraform state/risk evidence → Gjallar
Repo/agent task/test/build/PR/staging verification → Heimdall
Planning/approval/final report → Hermes
```

---

## Active repo docs

Architecture:

- [architecture/VM_OPERATIONS_ARCHITECTURE.md](architecture/VM_OPERATIONS_ARCHITECTURE.md)
- [architecture/VM_PROVISIONING_CONTRACT.md](architecture/VM_PROVISIONING_CONTRACT.md)

Features:

- [features/VM_lifecycle_action_safety.md](features/VM_lifecycle_action_safety.md)
- [features/Provisioning_Preflight_Readiness.md](features/Provisioning_Preflight_Readiness.md)
- [features/Provisioning_Resource_Preflight.md](features/Provisioning_Resource_Preflight.md)
- [features/Template_Readiness_Preflight.md](features/Template_Readiness_Preflight.md)
- [features/Operational_Risk_Dashboard.md](features/Operational_Risk_Dashboard.md)
- [features/Operational_VM_State_History.md](features/Operational_VM_State_History.md)
- [features/Operational_Risk_Thresholds.md](features/Operational_Risk_Thresholds.md)
- [features/Phase1_VM_Operations_MVP_completion.md](features/Phase1_VM_Operations_MVP_completion.md)

Operations:

- [operations/RUNBOOK.md](operations/RUNBOOK.md)
- [operations/Create_VM_End_to_End_Smoke_2026-05-03.md](operations/Create_VM_End_to_End_Smoke_2026-05-03.md)

Roadmap:

- [roadmap/NEXT_WORK.md](roadmap/NEXT_WORK.md)

---

## Current completed baseline

- Phase 1 VM Operations Console MVP
- Create VM end-to-end smoke and template disk preflight
- Phase 2 read-only Operational Risk Dashboard
- Backup schedule coverage evidence
- Gjallar DB-backed VM state history
- Long-stopped VM risk foundation
- DB-backed operational risk threshold configuration and UI

Recent verified commits:

```text
05f0f41 Add operational risk dashboard
7c2ca71 Add backup schedule risk evidence
854cd15 [verified] Add VM state history risk evidence
```

---

## Next work

1. stale `operational_vm_state` cleanup + VMID reuse guard
2. risk acknowledge/suppress
3. owner/tag taxonomy check
4. PBS direct API / restore readiness
5. optional read-only SSH collector for evidence gaps

If repo docs and shared storage disagree, follow shared storage first and update both.
