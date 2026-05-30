# 아키텍처 개요 빠른 안내

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [architecture index](../architecture/README.md), [system overview](../architecture/system/overview.md), [Current API V1](../architecture/api/current-api-v1.md).

이 문서는 구조를 빠르게 잡는 입구입니다. 자세한 도메인별 설명은 [architecture/README.md](architecture/README.md)를 봅니다.

## 큰 구조

```text
React operator UI
  -> frontend/src/services/apiV1.js
  -> backend /api/v1 router
  -> read-only inventory, network readiness, jobs/artifacts, Create VM helpers
  -> Proxmox read-only adapter or narrow Create VM mutation client
```

현재 active route는 `/`, `/infra`, `/networks`, `/create`, `/drs`, `/jobs`, `/risks`입니다. Backend active prefix는 `/api/v1`입니다.

## 기준 우선순위

현재 구현 truth:

1. Active code and tests.
2. [Current implemented state](../current/README.md).
3. [Current top-tab snapshots](../current/top-tabs/README.md).
4. [Architecture docs](../architecture/README.md).
5. [DRS Advisor product docs](../product/drs-advisor/README.md)는 target direction과 planned gap 확인용.

## 읽기/쓰기 경계

| Boundary | 현재 규칙 |
|---|---|
| Inventory | `backend/app/proxmox/inventory.py`는 read-only입니다. |
| Network readiness | live bridge inventory와 migration pre-check evidence만 read-only로 봅니다. YAML/file/DB/API write path나 DRS 실행 권한은 없습니다. |
| Jobs/artifacts | Create VM과 VM start 단계가 `job_runs`/`job_artifacts`에 상태와 artifact를 기록합니다. |
| Manifest commit | `execute`는 desired-state manifest만 commit합니다. |
| Native create | `proxmox-create`만 현재 active live VM creation path입니다. |
| DRS | Frontend `/drs`는 read/check only입니다. Backend DRS에는 identity/policy evidence, operation locks, local approval/job substrate, narrow operator-only execute route, UPID/task tracking, verified post-check, read-only reconcile preview가 있습니다. Broad UI/policy editor/corrective mutation/background automation/automatic DRS/live smoke/recommendation-level migrate aliases는 없습니다. |

## 자세한 한국어 아키텍처 문서

- [System overview](architecture/system/overview.md)
- [Current API V1](architecture/api/current-api-v1.md)
- [Create VM overview](architecture/create-vm/overview.md)
- [Native Create flow](architecture/create-vm/native-create-flow.md)
- [Placement / DRS Advisor](architecture/placement-drs-advisor/overview.md)
- [Jobs/Runs](architecture/jobs-runs/overview.md)
- [Risks/Alerts](architecture/risks-alerts/overview.md)
