# Dashboard

평가일: 2026-05-13

검증 기준: 2026-05-27에 backend `PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests` -> 182 passed, 33 warnings, 29 subtests passed, frontend `node --test frontend/tests/*.mjs` -> 13 passed, `pnpm --dir frontend lint` -> passed, `pnpm --dir frontend build` -> passed, `git diff --check` -> passed를 기록했다.

## 구현 수준

현재 Dashboard는 read-only 운영 summary 수준이다. cluster/nodes/vms/storage/networks/jobs/risks를 모아 현재 CPU/Memory와 기본 운영 count를 보여주지만, DRS Advisor 목표의 15분 average/peak나 top DRS recommendation은 없다.

## 구현 API/endpoints

- `GET /api/v1/cluster/summary`
- `GET /api/v1/nodes`
- `GET /api/v1/vms`
- `GET /api/v1/storage`
- `GET /api/v1/networks`
- `GET /api/v1/jobs`
- `GET /api/v1/risks`

## 관련 파일

- Frontend: [frontend/src/App.jsx](../../../frontend/src/App.jsx), [frontend/src/services/apiV1.js](../../../frontend/src/services/apiV1.js), [frontend/src/utils/apiV1ViewModels.js](../../../frontend/src/utils/apiV1ViewModels.js)
- Backend: [backend/app/api/v1/router.py](../../../backend/app/api/v1/router.py), [backend/app/proxmox/inventory.py](../../../backend/app/proxmox/inventory.py), [backend/app/proxmox/models.py](../../../backend/app/proxmox/models.py)
- Tests: [frontend/tests/appNavigation.test.mjs](../../../frontend/tests/appNavigation.test.mjs), [frontend/tests/apiV1Client.test.mjs](../../../frontend/tests/apiV1Client.test.mjs), [frontend/tests/apiV1ViewModels.test.mjs](../../../frontend/tests/apiV1ViewModels.test.mjs), [backend/tests/contracts/test_api_v1_inventory.py](../../../backend/tests/contracts/test_api_v1_inventory.py), [backend/tests/contracts/test_jobs_risks_contract.py](../../../backend/tests/contracts/test_jobs_risks_contract.py)

## 현재 구현

Dashboard는 `Promise.allSettled`로 cluster, node, VM, storage, network, job, risk 데이터를 병렬 조회한다. 일부 조회 실패 시 사용 가능한 inventory는 계속 표시한다.

요약 tile은 node online count, VM count/running count, storage summary, red risk count와 active job count를 보여준다. node row는 VM 수, running VM 수, current CPU usage, current memory usage, storage free, bridge 목록을 표시한다.

화면 action은 새로고침, Infra Explorer 이동, Create VM 이동이다. Dashboard에서 migration을 실행하지 않는다.

## DRS Advisor 기준 gaps

[DRS Advisor UI 목표](../../product/drs-advisor/02_UI_AND_FLOWS.md) 대비 top 1-3 DRS recommendation summary가 없다. CPU/Memory도 current만 있고 최근 15분 average/peak evidence가 없다.

HA/task/quorum/config-lock/blocker summary가 Dashboard node row에 정규화되어 있지 않다. Dashboard가 DRS Advisor 상세로 연결되는 recommendation entry point도 아직 없다.

## 리스크/메모

현재 Dashboard는 운영 개요로는 유효하지만 DRS 실행 판단에 쓰면 안 된다. stale recommendation, Check Now, current-only metric은 실행 gate가 아니며 final pre-check가 별도로 필요하다.

## 다음 구현 slice

먼저 backend read-only DRS recommendation snapshot 계약을 추가한다. 그 다음 Dashboard에는 top 1-3 summary와 node별 15분 average/peak/blocker count만 붙이고, 실행 버튼은 계속 DRS Advisor 상세로 넘긴다.
