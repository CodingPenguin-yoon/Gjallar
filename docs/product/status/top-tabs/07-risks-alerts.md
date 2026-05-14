# Risks/Alerts

평가일: 2026-05-13

검증 기준: coordinator가 backend `PYTHONPATH=backend backend/venv/bin/pytest -q backend/tests` -> 92 passed, frontend `for test_file in frontend/tests/*.mjs; do node "$test_file"; done` -> passed, `pnpm --dir frontend lint` -> passed, `pnpm --dir frontend build` -> passed를 기록했다.

## 구현 수준

현재 Risks/Alerts는 read-only job-derived risk 화면이다. Create VM preflight/plan에서 기록된 risk를 모아 보여주며, DRS blocker taxonomy는 아직 구현되어 있지 않다.

## 구현 API/endpoints

- `GET /api/v1/risks`

## 관련 파일

- Frontend: [frontend/src/components/OperationalRiskDashboard.jsx](../../../../frontend/src/components/OperationalRiskDashboard.jsx), [frontend/src/utils/risksScreen.js](../../../../frontend/src/utils/risksScreen.js), [frontend/src/utils/apiV1ViewModels.js](../../../../frontend/src/utils/apiV1ViewModels.js), [frontend/src/services/apiV1.js](../../../../frontend/src/services/apiV1.js)
- Backend: [backend/app/api/v1/router.py](../../../../backend/app/api/v1/router.py), [backend/app/jobs/runs.py](../../../../backend/app/jobs/runs.py), [backend/app/jobs/models.py](../../../../backend/app/jobs/models.py)
- Tests: [frontend/tests/risksScreen.test.mjs](../../../../frontend/tests/risksScreen.test.mjs), [backend/tests/contracts/test_jobs_risks_contract.py](../../../../backend/tests/contracts/test_jobs_risks_contract.py), [backend/tests/jobs/test_runs.py](../../../../backend/tests/jobs/test_runs.py)

## 현재 구현

backend는 job records의 `risks` 배열을 펼쳐 `/api/v1/risks`로 반환한다. risk item에는 job id/type/status, level, code, message, artifacts URL이 붙는다.

frontend는 red/yellow/green/unknown summary, filter, risk detail, artifact link를 보여준다. policy edit, override, clear, mutation action은 없다.

## DRS Advisor 기준 gaps

[DRS Risks 목표](../../prd/drs-advisor/02_UI_AND_FLOWS.md) 대비 DRS blocker taxonomy가 없다. 특히 identity mismatch, unclassified, metadata incomplete, policy restricted/blocked, route unknown/blocked, stale lock, migration timeout, needs_reconciliation이 정규화되어 있지 않다.

각 risk가 어떤 action을 막는지, Dashboard와 DRS Advisor recommendation에 어떻게 연결되는지도 없다.

## 리스크/메모

현재 risk는 job-derived라서 아직 실행 전 DRS blocker를 포괄하지 못한다. DRS에서는 Identity Mismatch와 route Unknown을 warning처럼 취급하면 안 되며, 실행 차단 risk로 표시해야 한다.

## 다음 구현 slice

DRS recommendation/final-precheck에서 쓰는 blocker code enum을 먼저 정의한다. 이후 `/api/v1/risks`가 Create VM risk와 DRS blocker를 함께 읽되, source와 blocked action을 명시하도록 확장한다.
