# Gjallar Current Work Plan

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 current work plan](../../engineering/GJALLAR_CURRENT_WORK_PLAN.md), [AI workflow principles](../../engineering/AI_CODING_WORKFLOW_PRINCIPLES.md), [Current implemented state](../current/README.md), [DRS Advisor implementation plan](../product/drs-advisor/05_IMPLEMENTATION_PLAN.md).

이 문서는 현재 Gjallar cleanup/Create VM/DRS Advisor work plan을 한국어로 설명합니다.

## Current product context

- Next MVP success line은 DRS Advisor입니다.
- Create VM은 supporting capability입니다.
- Active Create VM mutation path는 Proxmox native API입니다.
- Current Create VM profile/template/network target design은 부분 구현되어 있습니다.
- Current `/placement`는 frontend-only/read-only seed이고 backend DRS는 아직 없습니다.

## Workstream 요약

| Workstream | 상태와 의미 |
|---|---|
| A: Principles/context | Repo-local workflow principles와 work plan 유지. |
| B: Create VM profile/template/network | 세 static-seed profiles, live template, live bridge, static fields, access/SSH evidence는 구현. DB seed는 future. |
| C: Native Proxmox Create quality | exact approval, manifest verification, acknowledgement, stopped success policy를 유지해야 함. |
| D: Legacy cleanup | Old executor routes/helper/state metadata는 active contract에서 제거됨. |
| E: Documentation/status hygiene | current-vs-target language를 유지하고 stale docs를 current truth로 쓰지 않음. |
| F: Validation | focused tests와 broader validation을 상황에 맞게 실행. |

## Next slice candidates

영어 work plan 기준의 추천 다음 slice는 DB/ORM profile seed source 결정과, Create VM mutation semantics를 DRS authorization으로 재사용하지 않는 DRS Advisor read model/final pre-check contract 시작입니다.
