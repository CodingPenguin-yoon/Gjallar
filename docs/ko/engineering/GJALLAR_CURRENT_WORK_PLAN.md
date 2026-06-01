# Gjallar Current Work Plan

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 current work plan](../../engineering/GJALLAR_CURRENT_WORK_PLAN.md), [Create VM stabilization plan](../../engineering/CREATE_VM_STABILIZATION_PLAN.md), [AI workflow principles](../../engineering/AI_CODING_WORKFLOW_PRINCIPLES.md), [Current implemented state](../current/README.md), [DRS Advisor implementation plan](../product/drs-advisor/05_IMPLEMENTATION_PLAN.md).

이 문서는 현재 Gjallar cleanup/Create VM/DRS Advisor work plan을 한국어로 설명합니다.

## Current product context

- Next MVP success line은 DRS Advisor입니다.
- Create VM은 supporting capability입니다.
- Active Create VM mutation path는 Proxmox native API입니다.
- 현재 goal sequencing은 [docs/goal/README.md](../../goal/README.md)를
  기준으로 합니다. Goal Check 01-06, Goal 7, Goal 7.5, minimal local-only
  Goal 8 recorder, Goal 9 local account/session polish는 완료됐습니다.
  Goal 10-12는 candidate/not started follow-on이며, Goal 10은 사용자가
  명시적으로 선택할 때만 다음 planned candidate입니다.
- Goal 9 admin local account operations list/create/role/disable/reset-password,
  session inventory/revocation UI, self password change, sanitized audit
  metadata는 구현됐습니다.
- Current Create VM profile/template/network target design은 DB-backed profiles,
  live template, live bridge, static fields, access/SSH evidence까지 구현되어
  있습니다.
- Current `/drs`는 backend-owned DRS seed에서 narrow approval-gated live
  migration execution, backend post-check/reconciliation까지 진행되어
  있습니다. Broad UI와 live smoke evidence는 아직 없습니다.

## Workstream 요약

| Workstream | 상태와 의미 |
|---|---|
| A: Principles/context | Repo-local workflow principles와 work plan 유지. |
| B: Create VM profile/template/network | DB-backed profiles, live template, live bridge, static fields, access/SSH evidence는 구현. |
| C: Native Proxmox Create quality | exact approval, manifest verification, acknowledgement, stopped success policy를 유지해야 함. |
| D: Legacy cleanup | Old executor routes/helper/state metadata는 active contract에서 제거됨. |
| E: Documentation/status hygiene | current-vs-target language를 유지하고 stale docs를 current truth로 쓰지 않음. |
| F: Validation | focused tests와 broader validation을 상황에 맞게 실행. |
| G: Create VM stabilization | login, server-side session, viewer/operator/admin role, mutation API 보호, live smoke 기록. |

## Next slice candidates

현재 goal sequencing은 [docs/goal/README.md](../../goal/README.md)를 기준으로 합니다. Goal 10 DRS Live Migration Safety And Evidence는 사용자가 명시적으로 선택할 때만 다음 planned candidate입니다. Goal 11 DRS Operations Productization과 Goal 12 Platform Hardening And Decision Quality는 이후 candidate follow-on입니다. Live DRS smoke는 아직 실행되지 않았고, live mutation/smoke/readiness/cleanup/corrective action은 해당 run에 대한 explicit active-session approval이 필요합니다.
