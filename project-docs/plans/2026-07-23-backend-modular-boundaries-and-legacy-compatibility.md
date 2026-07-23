# 구현 계획: Backend 모듈 경계 정리와 Legacy 호환 영역 격리

- 상태: `PARTIALLY_IMPLEMENTED`
- 날짜: `2026-07-23`
- 관련 요구사항: [`Project Specification`](../specifications/project-specification.md) FR-001, FR-003, FR-004, FR-005, FR-008, FR-009, FR-010, FR-012
- 관련 ADR: [`ADR-002 Domain-oriented Modular Monolith`](../decisions/adr-002-modular-monolith-domain-boundaries.md), [`ADR-005 DRS Placement·Operation Convergence`](../decisions/adr-005-drs-placement-and-operation-convergence.md)
- 관련 상위 Plan: [`Verified Operations Control Plane 전환`](2026-07-20-verified-operations-control-plane-transition.md)
- 승인자: `사용자`
- 현재 진행: `단계 1~6 완료, neutral Placement 유지 — DRS Common Operation 단계 8은 사용자 방향 정정으로 롤백`

이 Plan은 이미 승인된 ADR-002의 방향을 실제 backend 모듈 경계에 점진적으로 적용한다. 새로운 아키텍처를 선택하는 작업이 아니므로 별도 ADR은 만들지 않는다.

## 1. 위험도

- 분류: `HIGH`
- 판단 근거:
  - `/api/v1` 공개 계약과 인증·권한 dependency가 걸린 router 구성을 변경한다.
  - Create VM과 DRS route에는 HTTP 처리와 application orchestration이 섞여 있다.
  - DRS와 Jobs/Artifacts는 frontend 화면, 실행 결과 표시, recovery projection이 아직 사용한다.
  - 기존 contract test 다수가 `app.api.v1.router` 내부 심볼을 직접 patch하거나 handler를 직접 호출한다.
- 실패 영향:
  - route 누락, path·method·response·권한 계약 변경
  - 테스트는 통과하지만 실제 adapter가 호출되거나, 반대로 테스트 주입이 작동하지 않는 문제
  - Operation과 legacy job projection 간 실행 이력 불일치
  - DRS 화면·정책·migration history의 조기 손실
- 되돌리기 어려운 부분:
  - 이 Plan의 초기 단계에는 DB schema 변경이나 데이터 삭제를 포함하지 않는다.
  - DRS 또는 Jobs/Artifacts table 제거는 별도 Plan과 사용자 승인을 받아야 한다.

## 2. 확인한 현재 상태

- 현재 동작:
  - `backend/app/main.py`가 auth router, admin router, `app.api.v1.router`를 조립한다.
  - `backend/app/api/v1/router.py`는 약 1,845줄이며 `/api/v1`의 viewer dependency와 41개 route를 한 파일에서 관리한다.
  - auth/admin을 포함한 현재 `/api/v1` 공개 route는 총 52개다.
  - inventory와 query route 일부는 얇지만 Create VM 실행 route는 긴 orchestration을 직접 수행한다.
  - DRS route는 advisor, policy, approval, execution, reconciliation을 한 HTTP 모듈에서 직접 연결한다.
  - Jobs/Artifacts는 read-only 화면뿐 아니라 Create VM·DRS 결과와 recovery용 job projection에도 사용된다.
- 관련 진입점과 호출 흐름:
  - HTTP: `backend/app/main.py` → `backend/app/api/v1/router.py`
  - Operation: route → `backend/app/operations/*` workflow/application 경계
  - Create VM: route → `backend/app/vm_create/*`와 Operation 모듈을 route가 직접 orchestration
  - DRS: route → `backend/app/drs/*` advisor·approval·execution
  - 호환 projection: workflow/recovery → `backend/app/jobs/*` → `job_runs`, `job_artifacts`
- 관련 테스트:
  - `backend/tests/contracts/test_api_v1_*.py`
  - `backend/tests/contracts/test_jobs_risks_contract.py`
  - `backend/tests/vm_actions/test_post_create_readiness.py`
  - 조사 시점의 관련 contract baseline: `59 passed`
- 기존 패턴:
  - auth/admin은 이미 독립 router로 분리되어 `main.py`에서 조립한다.
  - VM start/shutdown은 `operations` 아래 application workflow와 port/adapter 경계를 사용한다.
  - ADR-002는 `interface(api) → application(use case) → domain`, infrastructure의 port 구현, composition root 조립을 승인했다.
- 확인되지 않은 항목:
  - DRS 제거와 Insights/Monitoring 통합 방향은 확인했지만, 제거 대상 consumer·보존 이력·contract/data migration 순서는 후속 Plan 승인 대상이다.
  - Jobs/Artifacts의 각 projection을 Operation read model로 완전히 대체할 수 있는 시점과 backfill 필요 여부는 consumer별 검증이 필요하다.

## 3. 목표와 범위

- 목표:
  - `router.py`를 거대한 구현 모듈이 아니라 `/api/v1` composition root로 축소한다.
  - HTTP transport, application orchestration, domain/infrastructure 책임을 분리한다.
  - DRS와 Jobs/Artifacts를 즉시 삭제하지 않고 명시적인 compatibility boundary로 격리한다.
  - 이후 기능 개발이 legacy 구조를 다시 확장하지 않도록 의존성 방향과 테스트 경계를 고정한다.
- 범위:
  - 전체 route registry와 RBAC·response·error 계약 characterization
  - 책임별 child router 도입과 root router 조립
  - VM action과 Create VM orchestration의 application 경계 정리
  - DRS route와 legacy Jobs/Artifacts access의 compatibility 모듈 격리
  - 관련 contract/unit test와 현재 상태 문서 동기화
- 비범위:
  - `/api/v1` path, method, response shape의 의도적 변경
  - frontend route 또는 기능 삭제
  - DRS 데이터·migration history 삭제
  - `job_runs`, `job_artifacts` schema 삭제·rename·backfill
  - 새로운 queue, event bus, microservice, generic repository 도입
- 인수 조건:
  - 기존 52개 `/api/v1` route의 path·method·route name·RBAC가 유지된다.
  - `backend/app/api/v1/router.py`는 child router 조립과 공통 dependency만 담당한다.
  - 새 route handler가 concrete DB/Proxmox 구현을 직접 선택하지 않고 기존 application/service 경계 또는 명시적 provider를 사용한다.
  - Create VM의 긴 orchestration이 HTTP route에서 application service로 이동한다.
  - DRS와 Jobs/Artifacts의 호환 책임과 사용처가 코드·문서에서 식별된다.
  - 각 단계가 독립적으로 test/build되고 이전 단계로 되돌릴 수 있다.
- 유지할 기존 계약:
  - `/api/v1` URL, HTTP method, request/response schema, status code
  - viewer/operator/admin 권한 경계와 unsafe-origin 검증
  - Operation evidence, target lock, recovery semantics
  - 기존 DRS 조회·정책·실행 이력과 Jobs/Artifacts 표시 동작
  - 적용된 DB migration history

## 4. 아키텍처와 데이터 영향

- 도메인·모듈:
  - interface: `backend/app/api/v1/` 아래 composition router와 책임별 route module
  - application: `backend/app/operations/*`, Create VM use case facade, DRS compatibility facade
  - domain/infrastructure: 기존 `operations`, `vm_create`, `drs`, `proxmox`, `db`, `jobs` 모듈
- 책임과 의존성 방향:
  - root router는 child router만 포함한다.
  - route module은 HTTP validation과 transport mapping만 담당한다.
  - mutation orchestration은 application service가 담당한다.
  - DB session과 Proxmox adapter 선택은 application composition/provider 경계에서 수행한다.
- 데이터 소유권:
  - 초기 단계에는 변경하지 않는다.
  - `operations`가 verified execution truth를 소유한다.
  - `job_runs`와 `job_artifacts`는 현재 compatibility/read projection으로 유지한다.
  - DRS table의 최종 소유권·폐기는 후속 결정 전까지 유지한다.
- 트랜잭션·정합성:
  - 기존 workflow의 transaction, target lock, evidence append, recovery 규칙을 그대로 사용한다.
  - route 분리 과정에서 새로운 dual-write를 추가하지 않는다.
- API·DB·외부 시스템:
  - API 호환 변경 없음.
  - DB migration 없음.
  - Proxmox 호출 순서와 timeout/TLS 설정 변경 없음.
- 보안·권한:
  - `/api/v1` viewer dependency와 mutation별 operator dependency를 characterization test로 고정한다.
  - auth/admin router는 현재 경계를 유지한다.

## 5. 선택지와 결정

| 순위 | 선택지 | 적합한 이유 | 단점·비용 | 추천 여부 |
|---:|---|---|---|---|
| 1 | Route composition → application orchestration → compatibility 격리의 점진 전환 | 공개 계약과 DB를 유지하면서 매 단계 검증·rollback 가능 | 단계별 adapter/test seam 정리가 필요 | 추천 |
| 2 | `router.py`를 파일별로만 분할 | 빠르고 diff가 작음 | HTTP와 orchestration 결합, concrete dependency, legacy 확장이 그대로 남음 | 비추천 |
| 3 | DRS·Jobs를 포함한 일괄 재작성·삭제 | 최종 파일 수는 빠르게 줄 수 있음 | 기능·이력 손실과 API/DB 회귀 위험이 크고 rollback이 어려움 | 제외 |

- 사용자 결정: `1번: Route composition → application orchestration → compatibility 격리의 점진 전환`
- 승인일: `2026-07-23`

추천안은 1번이다. 이 Plan의 승인은 DRS와 Jobs/Artifacts의 **격리와 소비자 조사까지** 승인하는 것이며, 기능 삭제나 DB 정리를 승인하는 것은 아니다.

## 6. 구현 단계

각 단계는 이전 단계의 공개 계약을 유지하며 별도 검증 후 다음 단계로 진행한다.

| 단계 | 결과 | 변경 책임·예상 파일 | 검증 | 복구 지점 |
|---:|---|---|---|---|
| 1 | API 계약과 테스트 주입 경계 고정 | route registry characterization test, RBAC·OpenAPI·error contract 보강 | 전체 52개 route snapshot, 기존 contract test | test-only 변경 revert |
| 2 | root composition router와 query child router 도입 | `api/v1/router.py`, 신규 `api/v1/{inventory,inventory_context,operations,insights,jobs_compat}.py` | path/method/name/RBAC snapshot, inventory/jobs/insights contracts | child router include 제거 |
| 3 | VM action transport 분리 | 신규 `api/v1/vm_actions.py`, 기존 `operations/*` application 호출 유지 | start/shutdown/readiness contract와 workflow test | 기존 handler로 복귀 |
| 4 | Create VM application orchestration 분리 | 신규 `api/v1/vm_create_compat.py`, `vm_create/application.py` | draft→preflight→plan→approve→execute, 실패·멱등성 test | route가 기존 orchestration을 호출하도록 복귀 |
| 5 | DRS compatibility boundary 격리 | 신규 `api/v1/drs_compat.py`, `drs/application.py`, frontend/API consumer map | DRS contract, policy, approval, execute/reconcile test | 기존 DRS handler로 복귀 |
| 6 | Legacy convergence 결정 자료 작성 | DRS·Jobs/Artifacts producer/consumer와 Operation 대체 가능성 정리 | 코드 검색, 실제 화면·contract 확인 | 문서 변경 revert |
| 7 | 사용자 결정 gate | DRS 유지·Operation 통합 또는 단계적 폐기, Jobs projection 전환 범위 선택 | 별도 인수 조건 승인 | 구현하지 않고 현재 호환 영역 유지 |
| 8 | 승인된 legacy expand 전환 | 별도 high-risk Plan의 neutral Placement와 DRS Common Operation dual record; DB migration 불필요 | failure injection·전체 contract·문서·독립 리뷰 | 별도 Plan에 정의 |

- 단계 7 정정: 사용자는 DRS 기능을 유지·확장하려는 것이 아니라 제거하고 Insights/Monitoring으로 통합하려는 방향임을 명확히 했다. 선택지 A 기록은 철회됐고, neutral placement 경계만 유지한다.
- 단계 8 롤백: [`DRS Placement·Common Operation 전환 Plan`](2026-07-23-drs-placement-and-common-operation-convergence.md)의 Common Operation 통합 구현은 롤백했다. DRS 제거의 세부 단계는 별도 Plan에서 다룬다.

### 단계별 진행 규칙

1. 한 단계의 구현·검증·문서 동기화를 끝낸 뒤 다음 단계로 이동한다.
2. 단계 1~6에서는 공개 API, frontend 기능, DB schema를 변경하지 않는다.
3. 단계 7의 사용자 결정 전에는 DRS route, 화면, table 또는 Jobs/Artifacts table을 삭제하지 않는다.
4. route module은 기존 내부 심볼을 무조건 재수출하지 않는다. 테스트가 concrete module global을 patch하는 대신 명시적 provider/application seam을 사용하도록 함께 정리한다.

## 7. 성공·실패·데이터 흐름

- 성공 흐름:
  - `main.py` → `/api/v1` composition router → 책임별 route → application service → port/adapter → DB/Proxmox
- 실패 흐름:
  - application error를 기존 HTTP status와 response shape로 매핑한다.
  - mutation ambiguity, lock conflict, recovery-required 상태는 기존 Operation 규칙을 유지한다.
- 데이터 변환:
  - 단계 1~6에는 persistent data 변환이 없다.
  - HTTP schema ↔ application command/result 변환만 route 경계에서 명시한다.
- 재시도·멱등성·보상:
  - 기존 Operation idempotency, durable lock, evidence, recovery 규칙을 재사용한다.
  - route 분리 자체는 재시도 정책을 바꾸지 않는다.

## 8. 테스트와 검증 계획

- 단위 테스트:
  - application facade의 성공·실패·adapter 호출 순서
  - route provider seam과 error mapping
- 통합·계약 테스트:
  - 전체 `/api/v1` route registry snapshot
  - 기존 `backend/tests/contracts/test_api_v1_*.py`
  - Jobs/Risks, auth/admin, forbidden endpoint 계약
- 경계·실패 테스트:
  - viewer/operator/admin 권한
  - unsafe origin
  - Proxmox timeout/ambiguous failure
  - Operation lock conflict와 recovery-required
- Formatter·Lint·타입:
  - Project Profile의 backend compile/test와 frontend lint 명령
- 빌드·수동 확인:
  - backend 전체 test
  - frontend lint/test/build
  - `/instances`, `/operations`, `/operations/jobs`, `/insights/risks`, Create VM, DRS maintenance 화면 smoke

## 9. 문서 영향

- Project Specification:
  - 외부 동작을 바꾸지 않으므로 초기 단계에는 변경하지 않는다.
  - DRS 최종 정책 결정 시 scope/non-goal을 갱신한다.
- Architecture·ADR:
  - 구현 결과를 `architecture/overview.md`에 반영한다.
  - ADR-002 방향을 유지하므로 새 ADR은 만들지 않는다.
  - DRS 최종 정책이 새로운 장기 결정을 만들면 별도 ADR을 검토한다.
- Domain·Flow:
  - route/application 책임과 legacy compatibility 흐름을 실제 구현에 맞춰 갱신한다.
- API·Database:
  - route registry는 유지하며 내부 책임만 갱신한다.
  - DB schema 변경은 단계 8의 별도 Plan에서만 문서화한다.

## 10. 복구와 위험 완화

- 주요 위험:
  - child router include 시 prefix/dependency 중복 또는 누락
  - handler 이동 후 monkeypatch가 실제 호출 지점에 적용되지 않음
  - Create VM/DRS orchestration 이동 중 호출 순서 또는 evidence 변경
  - legacy projection을 사용하지 않는다고 오판해 화면·recovery가 깨짐
- 예방·관찰 방법:
  - 이동 전 전체 route registry와 RBAC를 snapshot으로 고정한다.
  - 단계마다 작은 route 묶음만 이동하고 전체 contract test를 실행한다.
  - mutation은 application workflow test와 실제 smoke를 함께 확인한다.
  - producer/consumer가 0으로 확인되기 전에는 compatibility data를 삭제하지 않는다.
- rollback 또는 roll-forward:
  - DB가 변하지 않는 단계 1~6은 child router include와 module 이동을 단계 단위로 되돌릴 수 있다.
  - 일부 route만 문제가 생기면 해당 route 묶음만 기존 handler로 roll-forward/rollback한다.
  - DB 전환은 후속 Plan에 expand/migrate/contract와 복구 절차를 별도로 정의한다.
- 중단 기준:
  - route registry, RBAC, response/status 계약 차이
  - Operation evidence/lock/recovery semantic 차이
  - DRS 또는 Jobs/Artifacts consumer를 대체하지 못한 상태
  - 테스트 주입이 실제 adapter 호출을 막지 못하는 상태

## 11. 구현 후 대조

- 현재 완료 범위: 단계 1~6과 neutral Placement. Guided `qm` route까지 child router로 이동해 root router는 composition만 담당한다. 잘못 진행한 단계 8의 DRS Common Operation 통합은 롤백했다.
- 계획과 달라진 부분: child router는 기존 flat package 관례에 맞춰 `api/v1/routes/` 하위가 아니라 `api/v1/vm_create_compat.py`와 `api/v1/drs_compat.py`에 두었다. application facade는 각각 `vm_create/application.py`, `drs/application.py`에 구현했다.
- 달라진 이유: 단계 2~3에서 확립한 `api/v1/*.py` child router 조립 규칙을 유지하고, HTTP framework dependency가 Create VM·DRS application orchestration으로 역류하지 않게 하기 위해서다.
- 품질 리뷰 조치: Create VM application 내부 default mutation client 선택과 child router의 테스트 재수출을 제거했다. DRS도 HTTP 경계가 inventory·risk·전용 migration client provider를 명시적으로 주입하고 테스트는 실제 application 소유 심볼을 patch한다. application의 HTTP/interface 역의존과 Create VM 6개·DRS 13개 route 소유 모듈은 architecture contract로 고정했다.
- DRS·legacy consumer 확인: `frontend/src/shared/api/apiV1.js`와 `DrsAdvisorScreen.jsx`·`DrsPoliciesScreen.jsx`가 DRS read/check/approval/policy/reconcile-preview를 소비한다. frontend에는 live execute helper나 mutation control이 없다. DRS approval/execution은 계속 `job_runs`·`job_artifacts`를 생산하고 Jobs 화면이 `/jobs`·artifact 계약으로 이를 표시하며, Insights placement는 advisor 계산만 read-only로 재사용한다. 따라서 DRS route/table과 Jobs/Artifacts는 단계 7 결정 전 제거할 수 없다.
- Legacy convergence 조사와 결정: [`DRS·Jobs/Artifacts Legacy Convergence Assessment`](../architecture/drs-jobs-convergence-assessment.md)에 producer/consumer, 공개 계약, table logical ownership과 replacement gap을 기록했다. 선택지 A는 철회됐고 [`DRS Placement·Common Operation Plan`](2026-07-23-drs-placement-and-common-operation-convergence.md)의 단계 3~7도 롤백했다. DRS 제거와 Jobs/Artifacts 전환은 서로 분리해 진행한다.
- 현재 검증 결과: neutral Placement와 router/application 경계를 보존한 롤백 후 local Python 3.14 backend 전체 `514 passed, 2 skipped`, DRS·route·Placement 집중 `120 passed`, 관련 module `py_compile`과 `git diff --check`가 통과했다. live Proxmox mutation과 DB migration은 실행하지 않았다.
- 갱신한 현재 상태 문서: `project-profile.md`, `architecture/overview.md`, `api/current-api-v1.md`, `database/current-schema-and-ownership.md`, `domains/domain-map.md`, `architecture/drs-jobs-convergence-assessment.md`와 두 구현 Plan.
- 남은 위험: production row 수·retention과 저장소 밖 API consumer는 확인하지 않았다. DRS API/UI/table 제거, history 보존, backfill과 deprecation은 별도 승인 대상이다.
