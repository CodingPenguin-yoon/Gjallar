# Gjallar Current Work Plan

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 current work plan](../../engineering/GJALLAR_CURRENT_WORK_PLAN.md), [Create VM stabilization plan](../../engineering/CREATE_VM_STABILIZATION_PLAN.md), [AI workflow principles](../../engineering/AI_CODING_WORKFLOW_PRINCIPLES.md), [Current implemented state](../current/README.md), [DRS Advisor implementation plan](../product/drs-advisor/05_IMPLEMENTATION_PLAN.md).

이 문서는 현재 Gjallar cleanup/Create VM/DRS Advisor work plan을 한국어로 설명합니다.

## Current product context

- Next MVP success line은 DRS Advisor입니다.
- Create VM은 supporting capability입니다.
- Active Create VM mutation path는 Proxmox native API입니다.
- 다음 즉시 작업은 token guard가 아니라 Gjallar login/session/role 기반
  Create VM 안정화입니다.
- Current Create VM profile/template/network target design은 부분 구현되어 있습니다.
- Current `/drs`는 backend-owned read-only DRS Phase 1 seed이고 backend DRS execution은 아직 없습니다.

## Workstream 요약

| Workstream | 상태와 의미 |
|---|---|
| A: Principles/context | Repo-local workflow principles와 work plan 유지. |
| B: Create VM profile/template/network | 세 static-seed profiles, live template, live bridge, static fields, access/SSH evidence는 구현. DB seed는 future. |
| C: Native Proxmox Create quality | exact approval, manifest verification, acknowledgement, stopped success policy를 유지해야 함. |
| D: Legacy cleanup | Old executor routes/helper/state metadata는 active contract에서 제거됨. |
| E: Documentation/status hygiene | current-vs-target language를 유지하고 stale docs를 current truth로 쓰지 않음. |
| F: Validation | focused tests와 broader validation을 상황에 맞게 실행. |
| G: Create VM stabilization | login, server-side session, viewer/operator/admin role, mutation API 보호, live smoke 기록. |

## Next slice candidates

추천 다음 slice는 [Create VM stabilization plan](../../engineering/CREATE_VM_STABILIZATION_PLAN.md)에 따라 Gjallar login/session/role을 추가하고, Create VM live mutation과 VM Start를 `operator` 이상으로 보호하는 것입니다. 이 안정화가 끝난 뒤 DRS identity/fingerprint DB와 read-only resolver로 넘어갑니다.
