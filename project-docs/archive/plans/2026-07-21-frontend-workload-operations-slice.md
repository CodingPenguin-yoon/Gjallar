# 구현 계획: Frontend Workload Cockpit·Operations 전환

> 종료된 계획의 당시 조사·승인·검증 기록이다. 현재 구현 지시가 아니며 후속 방향은 [계획 인덱스](../../plans/README.md), 현재 기준은 [문서 안내](../../README.md)를 따른다.

- 상태: `IMPLEMENTED`
- 날짜: `2026-07-21`
- 관련 요구사항: [`Project Specification`](../../specifications/project-specification.md)
- 관련 ADR: [`ADR-002`](../../decisions/adr-002-modular-monolith-domain-boundaries.md)
- 상위 Plan: [`Verified Operations Control Plane 전환`](2026-07-20-verified-operations-control-plane-transition.md)
- 승인자: `사용자`

이 Plan은 상위 Plan의 단계 6과 이미 구현된 Guided `qm unlock` backend를 하나의 frontend vertical slice로 연결한다.

## 1. 위험도

- 분류: `HIGH`
- 판단 근거: frontend 의존성 방향과 route 구성을 바꾸고, 공통 Operation 조회 계약을 추가한다.
- 실패 영향: 기존 화면·URL·RBAC 회귀, operation 상태 오표시, 운영자에게 허용되지 않은 action 노출 가능성이 있다.
- 되돌리기 어려운 부분: 없다. DB schema와 Proxmox mutation 동작은 변경하지 않고 additive API와 호환 route를 사용한다.

## 2. 확인한 현재 상태

- `frontend/src/App.jsx` 886줄에 session bootstrap, connection truth, navigation, route, Dashboard, Account UI가 함께 있다.
- `frontend/src/components/`와 `frontend/src/utils/`가 화면·feature 경계 없이 기능별 상태와 API 호출을 직접 소유한다.
- `/instances`는 `InstanceList`, `/operations/jobs`는 `TaskBoard`, `/operations/risks`는 `OperationalRiskDashboard`를 직접 조합한다.
- `/operations`는 현재 `/operations/jobs`로 redirect하며 공통 Operation 목록·상세 화면이 없다.
- backend에는 Operation projection/event와 Guided `qm unlock` plan·조회·attestation·verification API가 있지만 공통 목록 API가 없다.
- frontend는 React Router와 단일 `apiV1Client`를 사용한다. 새 상태관리 도구나 UI framework는 필요하지 않다.
- 현재 `pnpm --dir frontend test`는 로컬 pnpm 부재로 registry 조회를 시도하다 네트워크 제한으로 실패했다. 구현 검증은 고정된 container 경로 또는 승인된 dependency 준비 후 수행한다.

## 3. 목표와 범위

- 목표: `app → pages/features → entities/shared` 방향을 실제 코드에 적용하고, workload에서 시작해 Operation 계획·외부 실행·검증·이력을 Gjallar 안에서 끝내는 첫 UI를 제공한다.
- 범위:
  - app shell, route, navigation, session/connection composition 분리
  - `/instances`를 유지하는 Workload Cockpit page와 VM별 Guided `qm unlock` 진입점
  - `/operations` 공통 목록, `/operations/:operationId` 상세 timeline
  - Guided `qm unlock` plan, instruction 표시, operator attestation, API verification UI
  - 읽기 전용 `GET /api/v1/operations` 목록 API와 공통 query boundary
  - touched module의 architecture import guard와 동작 테스트
- 비범위:
  - Create VM common operation 통합
  - DRS 화면·API 제거 또는 자동 실행 확장
  - raw shell, arbitrary command 입력, backend SSH/CLI executor
  - DB migration, 새 frontend dependency, 전면 UI 디자인 변경
- 인수 조건:
  - viewer는 Operation 목록·상세·timeline을 조회할 수 있지만 mutation control은 볼 수 없거나 실행할 수 없다.
  - operator/admin은 live Proxmox connection일 때만 Guided `qm unlock`을 계획·attest·verify할 수 있다.
  - command는 server가 만든 `qm unlock <vmid>`만 표시하며 browser가 command 문자열을 전송하지 않는다.
  - 기존 canonical/alias URL과 Jobs·Risks·Create VM·DRS 화면은 계속 동작한다.
- 유지할 기존 계약: `/instances`, `/operations/jobs`, `/operations/risks`, `/jobs`, `/risks`와 기존 `/api/v1` response envelope.

## 4. 아키텍처와 데이터 영향

- frontend 의존성:
  - `app`: provider, shell, navigation, router composition
  - `pages`: route 단위 조합
  - `features`: workload inventory와 Guided `qm unlock` 사용자 흐름
  - `entities`: Operation·Workload DTO/view model과 공개 UI 조각
  - `shared`: API transport, 권한·connection 공통 helper, 범용 UI
- 신규 코드는 상위 계층을 import하지 않으며 feature 간 private import를 금지한다.
- 아직 옮기지 않는 Create VM·DRS·Admin 화면은 page adapter를 통해 기존 코드를 사용하고, 이 slice에서 억지로 재작성하지 않는다.
- Operations가 `operations`·`operation_events` 조회를 소유한다. list query는 projection만 읽고 detail query가 event timeline을 조합한다.
- 목록 API는 additive read-only 계약이며 status/type/limit filter를 제공한다. schema·transaction·external side effect는 바꾸지 않는다.
- server-side session과 `viewer < operator < admin` RBAC를 유지한다. frontend gating은 편의 UI이고 backend authorization을 대체하지 않는다.

## 5. 선택지와 결정

| 순위 | 선택지 | 적합한 이유 | 단점·비용 | 추천 여부 |
|---:|---|---|---|---|
| 1 | 앱 셸·Workloads·Operations만 vertical slice로 전환 | 제품 핵심 흐름을 완성하면서 기존 화면 회귀 범위를 제한한다 | 당분간 legacy adapter가 남는다 | 추천 |
| 2 | 모든 frontend 파일을 한 번에 새 폴더로 이동 | 물리 구조를 즉시 통일한다 | 대규모 import/test churn이며 동작 개선 없이 위험이 크다 | 비추천 |
| 3 | 폴더는 유지하고 새 화면만 추가 | 변경량이 작다 | `App.jsx` 집중과 의존성 혼합이 계속 커진다 | 비추천 |

- 사용자 결정: `앱 셸·Workloads·Operations vertical slice 전환 승인`
- 승인일: `2026-07-21`

## 6. 구현 단계

| 단계 | 결과 | 변경 책임·예상 파일 | 검증 | 복구 지점 |
|---:|---|---|---|---|
| 1 | 현재 route/behavior 보호와 계층 규칙 | `frontend/tests/`, architecture import contract | 기존 URL·권한·connection gate characterization | production code 전 |
| 2 | 공통 Operation query | Operations core query/store, `/api/v1/operations`, API contract | repository filter/order/limit, auth, envelope, detail 호환 | additive endpoint 제거 |
| 3 | frontend 공통 기반과 app shell 분리 | `src/app/`, `src/shared/`, 기존 service compatibility export | auth bootstrap, navigation, connection boundary | 기존 `App.jsx` composition 복구 |
| 4 | Operations list/detail/timeline | `src/pages/operations/`, `src/entities/operation/` | loading/empty/error/status/timeline, deep link | 새 route 제거; Jobs/Risks 유지 |
| 5 | Guided `qm unlock` UI | `src/features/guided-qm-unlock/` | RBAC, live gate, typed payload, expiry, attestation, verification, reconciliation | feature entry 제거; backend 불변 |
| 6 | Workload Cockpit 연결 | `src/pages/workloads/`, workload feature/compatibility adapter | inventory·VM Start 회귀, VM context prefill | 기존 `InstanceList` route 복구 |
| 7 | 전체 검증·독립 리뷰·문서 동기화 | tests, architecture/spec/API/flow docs | frontend test/lint/build, backend focused/full, `git diff --check`, `$quality-review` | 단계별 revert 가능 |

## 7. 성공·실패·데이터 흐름

- 조회: Browser → Operations list/detail API → Operation projection/event store → list/timeline UI.
- Guided 성공: workload 선택 → typed plan request → server instruction bundle → 운영자가 Proxmox node shell에서 실행 → explicit attestation → Proxmox API verification → succeeded timeline.
- 실패: API·connection·권한·precheck·expiry·verification 실패를 숨기지 않고 상태와 다음 행동을 표시한다.
- 재시도: 같은 idempotency key의 plan replay를 표시하고, attestation/verification은 backend 상태기계의 conflict를 그대로 노출한다.
- 보상: frontend는 추정 성공을 만들지 않는다. 불명확한 실행은 `needs_reconciliation`로 남긴다.

## 8. 테스트와 검증 계획

- frontend 단위: Operation/workload normalize, status/expiry/action availability view model.
- frontend 계약: 계층 import 방향, 기존 route/alias, API client payload, viewer/operator UI 경계.
- backend 단위·계약: list ordering/filter/limit, detail timeline 호환, session/RBAC, secret redaction.
- 전체: `pnpm run test:backend`, `pnpm run test:frontend`, `pnpm run lint:frontend`, `pnpm run build:frontend`, `git diff --check`.
- 수동: viewer/operator별 `/instances` → Guided unlock → `/operations/:id` 흐름과 좁은 화면 navigation/a11y 확인.
- live Proxmox에서 실제 `qm unlock` 실행은 별도 명시 승인 없이는 수행하지 않는다.

## 9. 문서 영향

- 구현 후 Architecture에 frontend physical boundary와 route composition을 반영한다.
- API 문서에 Operation 목록 filter와 response를 추가한다.
- verified operation lifecycle에 Workload Cockpit·UI handoff를 반영한다.
- 제품 목표·authority 결정이 바뀌지 않으므로 새 ADR은 만들지 않는다.

## 10. 복구와 위험 완화

- 주요 위험: route 누락, legacy import 역방향, stale operation 표시, mutation control 오노출, 사용자가 instruction 표시를 backend 실행으로 오인.
- 예방: 기존 URL 유지, source import guard, server authorization 유지, explicit external-execution 문구, stale/expiry 상태 표시.
- rollback: additive API와 새 route/page를 단계별 제거하고 compatibility adapter를 기존 screen으로 되돌린다.
- 중단 기준: 기존 route 회귀, RBAC 우회, command 문자열 입력 허용, server-side CLI 실행, 전체 test/lint/build 검증 불가 상태가 해소되지 않음.

## 11. 구현 후 대조

- 계획과 달라진 부분: Workload inventory는 임시 page adapter에만 두지 않고 `features/workloads/inventory`로 실제 이동했다. 공통 상세 query도 Guided facade에서 분리해 managed operation에 Guided 전용 메타가 붙지 않게 했다.
- 달라진 이유: touched feature의 의존성 방향을 실제로 적용하고, `/operations` 목록에서 VM Start 상세를 열 때 공통 read contract를 유지하기 위해서다.
- 최종 검증 결과: backend focused `17 passed`, local Python 3.14 backend 전체 `436 passed`; local Node 24 frontend test 16개, ESLint, Vite production build, `git diff --check` 통과.
- 갱신한 현재 상태 문서: Project Profile, Architecture, API, Verified Operation Lifecycle, 상위 전환 Plan.
- 남은 위험: Create VM·DRS·Jobs·Risks·Admin 내부는 page adapter 뒤 legacy 구조다. browser 수동 navigation/a11y, container build, live Proxmox command/API smoke는 실행하지 않았다.
