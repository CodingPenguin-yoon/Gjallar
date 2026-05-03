# Gjallar Documentation Index

> Gjallar는 Proxmox용 Operations & Risk Console이다.

제품 방향:

```text
Gjallar = Observe / Govern / Act for Proxmox
```

짧게 말하면:

```text
Proxmox용 vCenter 보조 레이어 + 운영 리스크 대시보드
```

---

## Source of truth

제품 방향과 현재 상태는 repo 문서보다 shared storage를 우선한다.

```text
/mnt/hermes_data/프로젝트/Gjallar
/mnt/hermes_data/프로젝트/AI_Homelab_Control_Plane_방향성.md
```

먼저 읽을 문서:

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
- VM 상태, IP, guest agent signal
- resource usage summary
- task/log tracking

### Govern

- backup coverage / recency risk
- snapshot age risk
- guest-agent risk
- storage capacity risk
- owner/environment/tag governance risk
- long-stopped VM risk with Gjallar-local state history

### Act

- VM provisioning via `/api/provision`
- readiness/resource/template preflight
- lifecycle action safeguards
- task-based execution and verification
- future approval-based remediation

---

## Non-goals

아래는 Gjallar의 핵심 범위가 아니다.

- GitLab/GitHub project inventory
- CI/CD pipeline orchestration
- staging host pool ownership
- source repository app deploy
- webhook-driven deployment automation
- Codex/Claude/OpenCode worker task orchestration
- 자체 LLM provider/context/memory/agent loop

이 범위는 Heimdall 또는 Hermes의 책임이다.

---

## Relationship with Heimdall

```text
Gjallar provides infrastructure.
Heimdall executes DevOps and agent work on that infrastructure.
Hermes coordinates both.
```

Target flow:

```text
Hermes → Gjallar provision plan → user approval → Gjallar VM bootstrap → Heimdall worker/staging registration → Heimdall task execution
```

소유권 경계:

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

Recent verified commits:

```text
05f0f41 Add operational risk dashboard
7c2ca71 Add backup schedule risk evidence
854cd15 [verified] Add VM state history risk evidence
```

---

## Next work

1. threshold config/UI
2. stale `operational_vm_state` cleanup + VMID reuse guard
3. risk acknowledge/suppress
4. owner/tag taxonomy check
5. PBS direct API / restore readiness

If repo docs and shared storage disagree, follow shared storage first and update both.
