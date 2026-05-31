# Goal Check 01-06 작업 요약

작성일: 2026-05-31

이 문서는 Goal 1부터 Goal 6까지의 구현 품질 점검 결과를 사람이
확인하기 쉽게 정리한 한국어 요약입니다. 기준 감사 문서는
[`goal-check-01-06-implementation-quality.md`](goal-check-01-06-implementation-quality.md)입니다.

## 결론

Goal Check 결과는 `pass-with-risk`입니다.

Goal 1부터 Goal 6까지는 active code, DB schema, API route, frontend behavior,
tests, current docs 기준으로 구현되어 있다고 판단했습니다.

Goal 7: DRS UI And Operations Polish는 이 감사 이후 시작할 수 있습니다.
다만 이번 작업에서 Goal 7 기능 자체는 시작하지 않았습니다.

남은 risk는 명확합니다.

- live DRS migration smoke는 실행하지 않았습니다.
- live Proxmox mutation/smoke는 active-session user approval 없이는 실행하지
  않는다는 원칙을 지켰습니다.
- broad DRS execution UI, richer policy/rule editor, corrective reconciliation mutation,
  background automation, automatic DRS는 여전히 deferred입니다.

## 왜 이 작업이 필요했나

Goal 7은 DRS UI와 운영 polish 작업입니다.

그 전에 Goal 1부터 Goal 6까지가 실제로 안전하게 구현되어 있는지 확인해야
했습니다. 특히 DRS는 Proxmox live migration과 연결되기 때문에 단순히
화면이나 문서에 "된다"고 적혀 있는 것만으로는 부족합니다.

확인해야 했던 핵심 질문은 다음과 같습니다.

- 구현이 문서뿐 아니라 active code에 실제로 있는가?
- DB model과 migration이 목표에 맞게 존재하는가?
- `/api/v1` route에서 실제로 도달 가능한가?
- frontend가 현재 가능한 일과 불가능한 일을 정확히 보여주는가?
- 테스트가 성공 케이스만 보는 것이 아니라 실패, timeout, ambiguous 상태를
  검증하는가?
- Proxmox task가 `OK`라고 해서 바로 Gjallar 성공으로 처리하지 않는가?
- live migration은 narrow approval/job execution route에서만 가능한가?
- 오래된 문서가 현재 상태와 모순되어 운영자를 헷갈리게 하지 않는가?

이번 감사에서 가장 중요한 안전 원칙은 다음이었습니다.

> Recommendation/check result는 실행 권한이 아니다.
>
> DRS live migration은 stored approval/job, fresh gates, live Proxmox evidence,
> operation locks를 통과한 dedicated execute route에서만 가능하다.

## 진행 방식

AGENTS.md 운영 방식에 따라 메인 세션은 coordinator 역할을 했습니다.

사용한 순서는 다음과 같습니다.

1. explorer가 Goal 1-6 관련 코드, DB, API, 테스트, 문서를 찾았습니다.
2. reviewer가 구현상 위험, 누락된 테스트, stale 문서 문제를 리뷰했습니다.
3. docs_researcher가 현재 API boundary와 문서 표현이 맞는지 확인했습니다.
4. worker가 실제 수정 작업을 수행했습니다.
5. coordinator가 worker diff를 다시 검토하고 validation을 실행했습니다.

메인 세션은 코드 수정자가 아니라 조정자였습니다. 실제 파일 수정은 worker가
수행했습니다.

## 감사 중 발견한 주요 문제

### 1. 문서가 현재 구현보다 오래되어 있었습니다

일부 current/architecture/product/Korean mirror 문서가 아직 아래처럼 말하고
있었습니다.

- DRS는 read-only Phase 1뿐이다.
- DRS migration execution이 없다.
- DRS identity/fingerprint DB가 없다.
- operation locks, UPID tracking, reconciliation backend가 없다.

하지만 active backend에는 Goal 2-6 범위로 다음이 이미 구현되어 있었습니다.

- compact DRS identity/fingerprint evidence
- migration policy memory
- operation locks
- local approval packet/job substrate
- narrow operator-only migration-job execute route
- UPID/task tracking
- verified post-check
- read-only reconcile preview

정확한 현재 상태는 다음입니다.

- frontend `/drs` UI는 recommendation/check 화면 only입니다.
- recommendation/check output은 `read_only=true`, `executable=false`,
  `allowed_actions=[]`입니다.
- approval packet creation은 local approval/job/artifact state만 쓰고
  migration을 시작하지 않습니다.
- backend live migration은 operator-only
  `POST /api/v1/drs/migration-jobs/{job_id}/execute` route에서만 가능합니다.
- corrective mutation, background automation, automatic DRS, broad execution UI는
  아직 없습니다.

### 2. 테스트가 일부 위험 경로를 직접 증명하지 못했습니다

기존 테스트는 성공 경로와 일부 blocker는 확인했지만, 운영에서 중요한
불명확한 상태를 충분히 직접 검증하지 않았습니다.

추가가 필요했던 예시는 다음입니다.

- Proxmox task failed
- task timeout
- ambiguous task result
- migration request failure after locks
- missing UPID
- post-check config read failure
- active task evidence read failure
- stale approval/checksum mismatch
- execute/reconcile-preview route authorization

이런 케이스는 DRS에서 매우 중요합니다. 왜냐하면 성공으로 확신할 수 없는
상태는 절대 completed로 처리하면 안 되고, `needs_reconciliation`으로 남겨야
하기 때문입니다.

### 3. "DRS execution이 없다"는 표현이 너무 넓었습니다

추천/check 화면은 실행 권한이 없는 것이 맞습니다.

하지만 backend에는 narrow operator-only execution route가 있습니다.

따라서 문구를 다음처럼 좁혔습니다.

- 틀린 표현: DRS execution is not exposed.
- 맞는 표현: recommendation/check output is execution-closed; execution exists
  only through stored approval/job execution gates.

## 실제로 수정한 내용

### Backend runtime wording

다음 파일에서 실행 경계 설명을 정확히 바꿨습니다.

- `backend/app/drs/advisor.py`
- `backend/app/drs/approval.py`
- `backend/app/db/models.py`

행동은 바꾸지 않았습니다. 주로 docstring, reason text, comment를 정리했습니다.

핵심 변경은 다음입니다.

- recommendation/check는 Proxmox-read-only입니다.
- `executable=false`, `allowed_actions=[]`를 유지합니다.
- local identity observation evidence는 저장될 수 있습니다.
- narrow live migration execution은 stored approval/job route에서만 가능합니다.

### Backend tests

`backend/tests/drs/test_execution.py`에 DRS execution 실패 경로 검증을
추가했습니다.

추가한 주요 검증은 다음입니다.

- task result가 `failed`이면 `needs_reconciliation`
- task result가 `timeout`이면 `needs_reconciliation`
- task result가 `ambiguous`이면 `needs_reconciliation`
- migration request가 UPID 없이 실패하면 `migration_request_failed`
- post-check에서 VM config를 못 읽으면 `post_check_config_unavailable`
- active task evidence를 못 읽으면
  `post_check_active_task_evidence_unavailable`
- stale approval, cancelled job, already-used UPID, checksum mismatch는 client
  factory 호출 전에 차단

이 테스트는 단순히 함수 호출 여부만 보는 것이 아니라 다음 상태까지 확인합니다.

- `drs_migration_jobs` status
- `operation_locks` status
- `drs_reconciliation_events`
- `proxmox_upid`
- `reconciliation_reason`
- mutation call/no-call behavior

`backend/tests/contracts/test_api_v1_auth.py`에는 authorization 테스트를
추가했습니다.

- unauthenticated execute/reconcile-preview 요청은 `401`
- viewer execute/reconcile-preview 요청은 `403`
- 이 경우 execution helper, reconcile preview helper, Proxmox client가 호출되지
  않아야 함

`backend/tests/contracts/test_api_v1_drs.py`와
`backend/tests/contracts/test_forbidden_mvp_endpoints.py`에서는 오래된 테스트
이름과 메시지를 수정했습니다.

이제 금지하는 것은 "모든 DRS execution"이 아니라 다음입니다.

- unsafe recommendation-level approve/migrate/live-migrate alias
- broad shortcut route

### Frontend copy

다음 파일의 문구만 수정했습니다.

- `frontend/src/utils/drsAdvisor.js`
- `frontend/src/components/DrsAdvisorScreen.jsx`
- `frontend/README.md`

frontend 기능은 추가하지 않았습니다.

변경한 의미는 다음입니다.

- frontend DRS 화면은 recommendation/check 화면 only입니다.
- backend에는 별도 approval/job execution route가 있습니다.
- UI에는 approval/execute/UPID/reconcile controls가 아직 없습니다.

### Docs

영어 current/architecture/product 문서와 한국어 mirror 문서를 현재 상태에
맞게 정리했습니다.

대표적으로 업데이트한 영역은 다음입니다.

- `docs/architecture/api/current-api-v1.md`
- `docs/architecture/system/overview.md`
- `docs/architecture/data-identity/overview.md`
- `docs/architecture/jobs-runs/overview.md`
- `docs/architecture/placement-drs-advisor/recommendation-and-execution.md`
- `docs/architecture/flows/drs-approve-migrate-reconcile.md`
- `docs/architecture/risks-alerts/overview.md`
- `docs/product/drs-advisor/*`
- `docs/ko/*`

문서에서 명확히 나눈 경계는 다음입니다.

#### DRS read/check routes

- `GET /api/v1/drs/summary`
- `GET /api/v1/drs/recommendations`
- `GET /api/v1/drs/recommendations/{recommendation_id}`
- `POST /api/v1/drs/recommendations/{recommendation_id}/check`

특징:

- Proxmox-read-only
- recommendation/check result는 execution authority가 아님
- `read_only=true`
- `executable=false`
- `allowed_actions=[]`
- local identity observation evidence는 저장될 수 있음

#### DRS local approval/job route

- `POST /api/v1/drs/recommendations/{recommendation_id}/approval-packets`

특징:

- operator-only
- local approval/job/artifact state만 기록
- Proxmox mutation 없음
- migration 시작 안 함

#### DRS narrow execution route

- `POST /api/v1/drs/migration-jobs/{job_id}/execute`

특징:

- operator-only
- stored approval/job binding 검증
- artifact checksum 검증
- fresh final pre-check 재실행
- live Proxmox DRS evidence 수집
- operation locks 획득
- dedicated DRS migration client 사용
- UPID 저장
- task polling
- verified post-check 후에만 completed
- 불명확하면 `needs_reconciliation`

#### DRS reconcile preview route

- `POST /api/v1/drs/migration-jobs/{job_id}/reconcile-preview`

특징:

- operator-only
- read-only
- corrective mutation 없음

## Goal별 판단

| Goal | 판단 | 요약 |
| --- | --- | --- |
| Goal 1: Create VM Live Smoke Matrix | pass | live smoke evidence, Create VM safety gates, post-check contract, negative no-mutation gate를 확인했습니다. |
| Goal 2: DRS Identity And Final Pre-Check Preparation | pass | DB-backed identity/policy evidence, stable fingerprint resolver, read-only final check, identity/policy blockers를 확인했습니다. |
| Goal 3: DRS Final Pre-Check And Operation Lock Foundation | pass | operation locks, lock blockers, config-lock evidence, unsupported evidence가 healthy로 fake되지 않는 점을 확인했습니다. |
| Goal 4: DRS Approval And Migration Job Substrate | pass | local approval packet/job intent, checksum binding, operator auth, no Proxmox mutation을 확인했습니다. |
| Goal 5: DRS Live Migration Execution And UPID Tracking | pass-with-risk | narrow operator-only execute route, dedicated DRS client, fresh gates, locks, UPID/task handling을 확인했습니다. Live DRS smoke는 실행하지 않았습니다. |
| Goal 6: DRS Post-Check And Reconciliation | pass-with-risk | task OK만으로 성공 처리하지 않고, target status/config/fingerprint/active-task post-check와 `needs_reconciliation` 처리를 확인했습니다. Live DRS reconciliation smoke는 실행하지 않았습니다. |

## 실행한 검증

### Backend

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q \
  backend/tests/drs \
  backend/tests/contracts/test_api_v1_drs.py \
  backend/tests/contracts/test_api_v1_auth.py \
  backend/tests/contracts/test_forbidden_mvp_endpoints.py \
  backend/tests/contracts/test_legacy_backend_cleanup.py \
  backend/tests/db \
  backend/tests/jobs \
  backend/tests/proxmox
```

결과:

```text
131 passed, 19 warnings, 10 subtests passed
```

### Frontend tests

```bash
node --test \
  frontend/tests/drsAdvisor.test.mjs \
  frontend/tests/apiV1Client.test.mjs \
  frontend/tests/jobsScreen.test.mjs
```

결과:

```text
3 passed
```

### Frontend build

```bash
pnpm --dir frontend build
```

결과:

```text
passed
```

### Diff hygiene

```bash
git diff --check
```

결과:

```text
passed
```

### Stale 문구 검색

DRS Phase 1/no-execution 관련 stale phrase를 current docs, architecture docs,
product docs, Korean mirror, frontend/backend code에서 검색했습니다.

결과:

```text
문제가 되는 stale current-state hit 없음
```

## 이번 작업에서 하지 않은 것

안전과 scope를 지키기 위해 다음은 하지 않았습니다.

- live Proxmox DRS migration smoke 실행 안 함
- live Proxmox cleanup/mutation 실행 안 함
- Goal 7 UI 구현 시작 안 함
- DRS approval/execute/reconcile UI controls 추가 안 함
- richer policy/rule editor 추가 안 함
- corrective reconciliation mutation 추가 안 함
- background reconciliation automation 추가 안 함
- automatic DRS 추가 안 함
- tests를 약화하거나 skip하지 않음

## 남은 risk

남은 risk는 구현 누락이라기보다 live evidence 부재입니다.

- Goal 5/6 backend execution path는 fake/mock 기반 자동 테스트로 검증했습니다.
- 하지만 live Proxmox DRS migration smoke는 실행하지 않았습니다.
- 따라서 실제 Proxmox cluster에서 DRS migration을 한 번 end-to-end로 확인하는
  것은 별도 explicit approval을 받은 세션에서만 진행해야 합니다.

이 risk는 Goal 7 시작을 막는 blocker로 보지는 않았습니다. 다만 운영상
중요한 risk로 계속 기록해야 합니다.

## 확인할 때 보면 좋은 파일

감사 기준:

- [`goal-check-01-06-implementation-quality.md`](goal-check-01-06-implementation-quality.md)

현재 DRS 상태:

- [`../current/README.md`](../current/README.md)
- [`../current/top-tabs/05-placement-drs-advisor.md`](../current/top-tabs/05-placement-drs-advisor.md)
- [`../architecture/api/current-api-v1.md`](../architecture/api/current-api-v1.md)
- [`../architecture/placement-drs-advisor/recommendation-and-execution.md`](../architecture/placement-drs-advisor/recommendation-and-execution.md)

핵심 코드:

- `backend/app/drs/advisor.py`
- `backend/app/drs/identity.py`
- `backend/app/drs/operation_locks.py`
- `backend/app/drs/approval.py`
- `backend/app/drs/execution.py`
- `backend/app/proxmox/drs_migration.py`
- `backend/app/api/v1/router.py`

핵심 테스트:

- `backend/tests/drs/test_execution.py`
- `backend/tests/drs/test_advisor_readiness.py`
- `backend/tests/drs/test_identity_resolution.py`
- `backend/tests/drs/test_operation_locks.py`
- `backend/tests/contracts/test_api_v1_drs.py`
- `backend/tests/contracts/test_api_v1_auth.py`

## 한 줄 요약

Goal 1-6은 production-quality 기준으로 통과했습니다. Goal 7은 시작할 수
있지만, live DRS smoke는 아직 하지 않았고 반드시 별도 explicit approval을
받은 세션에서만 실행해야 합니다.
