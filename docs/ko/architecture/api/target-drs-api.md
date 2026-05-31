# DRS API Boundary And Future Candidates

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 DRS API boundary](../../../architecture/api/target-drs-api.md), [Placement / DRS snapshot](../../../current/top-tabs/05-placement-drs-advisor.md), [DRS product direction](../../../product/drs-advisor/README.md), [DRS recommendation/execution](../../../product/drs-advisor/04_DRS_RECOMMENDATION_AND_EXECUTION.md).

이 문서는 DRS Advisor API boundary와 future candidates를 설명합니다. 현재 backend에는 recommendation/check routes, manual VM migration policy API, local approval/job substrate, narrow operator-only migration-job execute route, UPID/task tracking, verified post-check, read-only reconcile preview가 있습니다.

## 현재 baseline

현재 `/drs` frontend는 [frontend/src/components/DrsAdvisorScreen.jsx](../../../../frontend/src/components/DrsAdvisorScreen.jsx)와 [frontend/src/utils/drsAdvisor.js](../../../../frontend/src/utils/drsAdvisor.js)가 backend DRS recommendation/check endpoint, manual policy endpoint, local approval packet endpoint를 소비합니다. Recommendation/check output은 `read_only=true`, `executable=false`, `allowed_actions=[]`를 유지합니다. Backend에는 identity/policy evidence, operation locks, local approval/job substrate, narrow execute route, UPID/task tracking, verified post-check, read-only reconcile preview가 있습니다.

## Target candidate endpoints

| Candidate endpoint | 목표 | 현재 상태 |
|---|---|---|
| `GET /api/v1/drs/summary` | blockers, candidates, policy gap summary | Implemented; Proxmox-read-only |
| `GET /api/v1/drs/recommendations` | current Proxmox inventory/risk evidence 기반 backend-owned recommendation list | Implemented; `executable=false` |
| `GET /api/v1/drs/recommendations/{recommendation_id}` | recommendation 하나의 evidence bundle | Implemented |
| `POST /api/v1/drs/recommendations/{recommendation_id}/check` | operator 참고용 final-check recalculation. 실행 허가는 아님 | Implemented; `executable=false` 유지 |
| `POST /api/v1/drs/recommendations/{recommendation_id}/approval-packets` | local approval/job/artifact write; migration 시작 안 함 | Implemented; operator-only |
| `POST /api/v1/drs/migration-jobs/{job_id}/execute` | stored approval/job, fresh gates, live Proxmox evidence, locks 이후 narrow execution | Implemented; operator-only |
| `POST /api/v1/drs/migration-jobs/{job_id}/reconcile-preview` | uncertain job state evidence를 read-only로 preview | Implemented; corrective mutation 없음 |
| `GET /api/v1/drs/policies` | DRS policy coverage/blockers view | Implemented |
| `GET /api/v1/drs/policies/{vm_identity_id}` | one VM policy item | Implemented |
| `PUT /api/v1/drs/policies/{vm_identity_id}` | manual local policy update with audit evidence | Implemented |
| `GET /api/v1/drs/locks` | active/stale operation lock inspection | Not implemented as public API |

## Target execution rule

Current DRS는 "approve means migrate"가 아닙니다. 구현된 순서는 recommendation evidence version 생성, optional Check, local approval packet/job, stored job execute, fresh gates, live Proxmox evidence, operation locks, Proxmox migration, UPID polling, post-check, completed 또는 `needs_reconciliation` 기록입니다.

Check Now와 stale recommendation snapshot은 실행 허가가 아닙니다. Final pre-check가 execution 직전 Proxmox current state와 Gjallar identity/policy/lock state를 다시 읽어야 합니다.

## Explicit non-current items

- Recommendation-level approve/migrate/live-migrate aliases.
- Live execute UI, corrective reconcile UI, and broad approval-to-execute controls.
- Richer policy rule/full metadata editor.
- Corrective reconciliation mutation.
- Background reconciliation automation or automatic DRS.
- Live DRS smoke evidence.
- DRS blocker taxonomy integrated into `/api/v1/risks`.
