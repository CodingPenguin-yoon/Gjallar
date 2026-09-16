# 구현 계획: Insights 제품화와 DRS Maintenance 전환

> 종료된 계획의 당시 조사·승인·검증 기록이다. 현재 구현 지시가 아니며 후속 방향은 [계획 인덱스](../../plans/README.md), 현재 기준은 [문서 안내](../../README.md)를 따른다.

- 상태: `IMPLEMENTED`
- 날짜: `2026-07-21`
- 관련 요구사항: [`FR-001`, `FR-002`, `FR-010`, `FR-012`](../../specifications/project-specification.md)
- 관련 ADR: [`ADR-001`](../../decisions/adr-001-proxmox-gjallar-authority-boundary.md), [`ADR-002`](../../decisions/adr-002-modular-monolith-domain-boundaries.md), [`ADR-003`](../../decisions/adr-003-production-inventory-connection-truth.md)
- 상위 Plan: [`Verified Operations Control Plane 전환` 단계 9](2026-07-20-verified-operations-control-plane-transition.md)
- 승인자: `사용자`

이 Plan은 risk, readiness, capacity, placement를 실행 권한 없는 Insights 제품 경계로 통합하고 DRS를 primary product navigation에서 maintenance 경로로 내리는 단계 9의 상세 범위를 정의한다. 기존 DRS API·실행·정책·DB 데이터와 compatibility route는 별도 폐기 승인 전 유지한다.

> 2026-07-23 방향 정정: 이 Plan의 DRS maintenance 보존은 단계 9에서 즉시 contract/data를 삭제하지 않기 위한 전환 전술이었다. 장기 제품 방향은 [`ADR-006`](../../decisions/adr-006-drs-deprecation-and-insights-convergence.md)의 DRS 단계적 폐기와 Insights/Monitoring 통합이며, DRS Common Operation·automatic recovery·기능 확장은 후속 범위가 아니다.

## 1. 위험도

- 분류: `HIGH`
- 판단 근거: Insights 도메인 경계와 backend/frontend 의존 방향을 새로 적용하고, primary navigation 및 canonical product route를 변경하며, 기존 DRS recommendation과 Jobs/Risks projection을 새 공개 read contract가 소비한다.
- 실패 영향: stale·unavailable 데이터를 정상으로 오인하거나 recommendation이 실행 권한을 가진 것처럼 보일 수 있다. 기존 `/risks`, `/drs/*`, DRS maintenance control과 frontend route가 회귀하거나 DB read failure가 빈 risk로 축소될 수도 있다.
- 되돌리기 어려운 부분: 이번 추천 범위에는 schema/data migration, API·route 삭제, live Proxmox mutation이 없다. 다만 새 `/api/v1/insights`와 `/insights/*`가 공개되면 additive compatibility contract가 되므로 응답 의미를 신중히 고정해야 한다.

## 2. 확인한 현재 상태

- 현재 동작:
  - `GET /api/v1/risks`는 `job_runs.risks`에서 Create VM·operation 관련 risk를 평탄화하며 version·freshness·source availability를 finding 단위로 제공하지 않는다.
  - DRS read API는 current Proxmox inventory에서 node pressure와 placement recommendation을 계산하고 `observed_at`, identity/policy/route evidence, blocker taxonomy를 제공한다. recommendation 자체는 `read_only=true`, `executable=false`, `allowed_actions=[]`다.
  - DRS read 계산은 stable identity observation을 기존 DRS table에 기록할 수 있다. 신규 Insights가 이를 재사용하더라도 새로운 table이나 persistence 의미는 추가하지 않는다.
  - `/drs` 화면은 read-only recommendation/check와 함께 operator용 local approval packet 생성 control을 제공한다. 실제 migration execute/reconcile은 별도 DRS job API다.
  - primary navigation은 `DRS Advisor`를 독립 제품 영역으로 노출하고, Risks는 Operations subnavigation에 있다. `pages/insights`에는 DRS compatibility page만 있고 공통 Insight entity/feature는 없다.
  - product runtime의 inventory는 `unconfigured`/`live`/`degraded`를 구분하며 non-live에서 fake data를 사용하지 않는다. 기존 DRS route는 live connection boundary 뒤에 있다.
- 관련 진입점과 호출 흐름:
  - backend: `backend/app/api/v1/router.py`의 `/risks`, `/drs/*`; `backend/app/jobs/runs.py`; `backend/app/drs/advisor.py`; `backend/app/workloads/inventory.py`.
  - frontend: `frontend/src/app/App.jsx`, `navigationModel.js`, `navigation.jsx`; `OperationalRiskDashboard`; `DrsAdvisorScreen`; `utils/risksScreen.js`, `utils/drsAdvisor.js`; shared API client.
  - data: `job_runs`/`job_artifacts`, DRS identity/policy/approval/execution tables, live `InventorySnapshot`. 별도 Insight table은 없다.
- 관련 테스트:
  - backend DRS advisor/API와 Jobs/Risks contract baseline `50 passed`.
  - frontend app navigation, auth, DRS Advisor, Risks, API client 5개 script 통과.
  - canonical 전체 기준선은 Python 3.13 backend `443 passed`, Node 24/pnpm 10 frontend test 16개·ESLint·Vite build 통과다.
- 기존 패턴:
  - backend `interface → application → domain`, infrastructure composition facade와 additive `/api/v1` endpoint.
  - frontend `app → pages/features → entities/shared`, 기존 route는 compatibility alias 또는 adapter로 유지.
  - non-live actual state는 unavailable로 명시하고 fake·silent fallback을 금지한다.
- 확인되지 않은 항목:
  - production traffic과 finding 수, metric retention, freshness SLA, 사용자별 정량 usability/a11y 기준.
  - live cluster에서 readiness/capacity rule의 실제 운영 임계값 적합성. 이번 단계는 기존 DRS `hot=70`, `critical=85`, `source_target_delta=25`를 versioned rule로 재사용하고 live mutation을 수행하지 않는다.

## 3. 목표와 범위

- 목표: risk, operational readiness, capacity pressure, placement recommendation을 동일한 evidence·rule version·observed time·freshness 계약으로 조회하고, 어떤 Insight도 approval·operation·Proxmox mutation을 생성하지 못하게 한다.
- 범위:
  - `backend/app/insights/`에 infrastructure-free finding/category contract와 read application service를 추가한다.
  - additive `GET /api/v1/insights`가 네 category의 summary와 finding을 한 aggregate로 반환한다.
  - 각 section은 `status`, `available`, `source`, `observed_at`, `freshness`, `rule_version`, `summary`, `findings`를 가진다. top-level은 `execution_mode=observe_only`, `read_only=true`, `allowed_actions=[]`를 고정한다.
  - Risk는 기존 job projection을 strict query로 읽는다. DB failure를 빈 risk로 축소하지 않고 risk section을 `unavailable`로 표시하며 기존 `/api/v1/risks` 의미는 바꾸지 않는다.
  - Readiness는 current VM inventory에서 power state, guest agent, usable IP, config lock evidence를 보수적인 versioned rule로 설명한다. 관찰되지 않은 값은 pass로 간주하지 않는다.
  - Capacity는 current node CPU/memory와 storage free evidence를 기존 DRS threshold에 맞춰 설명한다.
  - Placement는 기존 DRS advisor의 read-only recommendation/evidence를 compatibility adapter로 재사용하되 Insights contract에서는 approval·execute action/link를 제공하지 않는다.
  - inventory가 non-live이면 stored risk section은 독립적으로 조회하고 readiness/capacity/placement는 `unavailable`과 connection reason을 반환한다.
  - frontend primary navigation을 `Insights`로 전환하고 `/insights`, `/insights/risks`, `/insights/readiness`, `/insights/capacity`, `/insights/placement`를 제공한다.
  - 기존 `/operations/risks`, `/risks`, `/drs`, `/instances/drs-policies`, `/api/v1/risks`, `/api/v1/drs/*`와 DRS data/execution은 유지한다. `/drs`에는 maintenance 상태와 canonical `/insights/placement` link를 명시한다.
- 비범위:
  - Insight DB schema, metric sample persistence, retention/backfill, scheduler/worker/cache, 새 dependency.
  - DRS API/UI/data 삭제, migration execution 변경, DRS common Operation 통합, policy ownership 변경.
  - 자동 remediation, approval packet 자동 생성, operation dispatch, threshold editor, suppression/override.
  - live Proxmox mutation/smoke, stale snapshot persistence, multi-cluster 지원.
- 인수 조건:
  - viewer를 포함한 authenticated 사용자가 `/insights`를 조회할 수 있고 모든 payload와 UI가 `observe_only`/read-only/no actions를 명시한다.
  - 네 category가 evidence, rule version, observed time, freshness를 제공하며 `unknown`/`unavailable`을 green/pass로 축소하지 않는다.
  - non-live inventory에서도 fake data를 표시하지 않고 stored risk와 unavailable inventory section을 구분한다.
  - Insights backend/frontend에는 DRS approval, operation create, mutation client 호출이 없다.
  - primary navigation에서 DRS 중심성을 제거하되 기존 DRS maintenance UI/API와 route는 직접 접근 가능하다.
  - 기존 Jobs/Risks/DRS/API/auth/navigation contract와 전체 regression이 통과한다.
- 유지할 기존 계약: `/api/v1` envelope과 auth/RBAC, `/api/v1/risks`, `/api/v1/drs/*`, `/operations/risks`, `/risks`, `/drs`, DRS policy/approval/execute/reconcile 의미, DB migration history.

## 4. 아키텍처와 데이터 영향

- 도메인·모듈: Insights가 derived finding의 공통 언어와 query orchestration을 소유한다. Workloads는 live observation, Evidence/Operations compatibility는 stored risk provenance, DRS는 placement calculation adapter를 제공한다. Insights는 어떤 command port도 소유하지 않는다.
- 책임과 의존성 방향:
  - backend: `api facade → insights application → insight domain + read ports`; `jobs`, Workloads observation, DRS advisor는 facade/infrastructure adapter에서 조립한다.
  - frontend: `app → pages/insights → features/insights → entities/insight + shared/api`. Insights feature는 legacy DRS component나 mutation helper를 import하지 않는다.
- 데이터 소유권: 새 persistent data가 없다. Job risk와 DRS identity/policy data의 현재 owner를 바꾸지 않으며 Insight payload는 요청 시 계산되는 derived read model이다.
- 트랜잭션·정합성: inventory snapshot과 job risk query는 하나의 transaction이 아니다. section별 provenance와 observed time을 따로 표시해 cross-source atomic snapshot처럼 보이지 않게 한다. 기존 DRS identity observation write는 현재 transaction 의미를 유지한다.
- API·DB·외부 시스템: `GET /api/v1/insights`만 additive하게 추가한다. migration과 Proxmox mutation은 없고 live inventory read만 사용한다. DRS·Risks endpoint는 compatibility facade로 유지한다.
- 보안·권한: global `viewer+` read boundary를 사용한다. request actor나 mutable threshold를 받지 않으며 secret-bearing raw payload를 finding evidence에 포함하지 않는다.

## 5. 선택지와 결정

| 순위 | 선택지 | 적합한 이유 | 단점·비용 | 추천 여부 |
|---:|---|---|---|---|
| 1 | Additive Insights aggregate와 primary navigation을 추가하고 DRS를 maintenance route로 유지 | 승인된 ADR·단계 9와 일치하며 no-migration, no-delete로 rollback 가능하다. partial availability와 실행 권한 분리를 새 계약에서 명확히 할 수 있다. | old/new Risks·DRS 화면이 한동안 공존하고 compatibility adapter가 늘어난다. | 추천 |
| 2 | 기존 Risks·DRS UI만 `Insights`로 재명명 | 빠르고 변경량이 작다. | 공통 evidence/version/freshness 계약과 non-live partial state가 없어 FR-010 제품화를 충족하지 못한다. DRS approval control도 Insights에 섞인다. | 비추천 |
| 3 | DRS API/UI/data를 즉시 폐기하고 Insight schema로 이전 | 최종 제품 표면은 단순하다. | destructive migration, history·execution consumer 단절, 별도 폐기 승인과 roll-forward가 필요하다. | 이번 단계 제외 |

- 사용자 결정: `1순위 승인 — additive Insights aggregate와 primary navigation을 추가하고 기존 DRS를 maintenance route로 보존한다.`
- 승인일: `2026-07-21`

기존 ADR-001/002가 Insights의 `observe_only` 권한과 domain-oriented vertical slice를 이미 승인했으므로 새 ADR은 만들지 않는다. DRS 삭제나 persistent Insight storage를 선택하면 별도 ADR·Plan 승인이 필요하다.

## 6. 구현 단계

| 단계 | 결과 | 변경 책임·예상 파일 | 검증 | 복구 지점 |
|---:|---|---|---|---|
| 1 | 현재 Risks/DRS contract와 Insight taxonomy 고정 | 이 Plan, backend/frontend characterization tests | 현재 focused backend 50, frontend 5 scripts | production code 미변경 |
| 2 | 공통 Insight domain/application | `backend/app/insights/domain.py`, `ports.py`, `application.py`, unit tests | severity/freshness/rule/evidence, partial unavailable, no command port | 신규 module 제거 |
| 3 | 기존 source adapter와 additive API | `backend/app/insights/facade.py`, jobs strict query, `api/v1/router.py`, API tests | live/non-live, DB unavailable, redaction, DRS adapter, old endpoint regression | `/insights` wiring 제거; 기존 API 유지 |
| 4 | frontend Insight entity/feature/page | `entities/insight`, `features/insights`, `pages/insights`, shared API | four category rendering, evidence/freshness, no mutation helper/import | 신규 page/route 제거 |
| 5 | navigation과 DRS maintenance 표시 | `app/App.jsx`, navigation, DRS compatibility screen, navigation/auth tests | primary Insights, legacy direct routes, viewer access, non-live partial UI | 기존 DRS primary nav 복원 |
| 6 | 전체 검증·독립 리뷰·문서 동기화 | tests, project-docs | backend/full, frontend test/lint/build, container, diff, quality review | 실패 단계 이후 진행 중단 |

## 7. 성공·실패·데이터 흐름

- 성공 흐름:
  1. authenticated viewer가 `GET /api/v1/insights`를 요청한다.
  2. application이 Proxmox connection observation과 strict job risk query를 독립적으로 수집한다.
  3. live snapshot이면 readiness/capacity rule을 평가하고 existing DRS advisor adapter로 placement evidence를 만든다.
  4. 각 source를 common finding으로 변환하며 source, observed time, freshness, rule version, redacted evidence를 연결한다.
  5. 모든 section과 top-level에 read-only/observe-only/no-actions contract를 적용한다.
  6. frontend는 category별 summary와 finding detail을 표시하되 mutation control을 렌더링하지 않는다.
- 실패 흐름:
  - Proxmox unconfigured/degraded: readiness/capacity/placement `unavailable`; connection reason 표시; fake/previous snapshot fallback 없음.
  - Jobs DB unavailable: risk `unavailable`; `findings=[]`만으로 정상/green을 표현하지 않음; 기존 `/risks` 공개 의미는 보류 상태로 유지.
  - placement adapter 실패: placement만 `unavailable`; 다른 section은 유지한다.
  - 일부 값 미관찰: finding 또는 section을 `unknown`/`incomplete`로 표시하고 pass count에 포함하지 않는다.
- 데이터 변환: `InventorySnapshot`·job risk·DRS recommendation → common `InsightFinding` → additive API envelope → frontend Insight entity. DB row와 DRS payload를 외부 계약으로 그대로 노출하지 않는다.
- 재시도·멱등성·보상: read-only 요청이므로 external mutation retry·보상은 없다. refresh는 새 observation을 다시 계산하며 finding ID는 category/rule/target/source identity로 deterministic하게 만든다.

## 8. 테스트와 검증 계획

- 단위 테스트:
  - common finding validation, deterministic ID, severity/status/freshness normalization.
  - readiness: guest agent/IP/config lock/unknown state rule.
  - capacity: CPU/memory/storage threshold와 missing metric 보수 처리.
  - placement/risk adapter mapping과 secret redaction.
- 통합·계약 테스트:
  - `GET /api/v1/insights` viewer access, envelope, four sections, observe-only/no-actions.
  - live snapshot evidence/version/freshness와 non-live partial response.
  - 기존 `/risks`, `/drs/*`, DRS auth/execute/reconcile 계약 회귀.
  - frontend API client, `/insights/*`, primary/subnavigation, legacy `/operations/risks`, `/risks`, `/drs` route.
- 경계·실패 테스트:
  - Jobs DB exception과 placement calculation exception을 empty healthy state로 축소하지 않는다.
  - unknown/missing metric이 green/pass가 되지 않는다.
  - Insights backend import graph에 Proxmox mutation client·Operation command store가 없고 frontend source에 approval/create/execute helper가 없다.
  - DRS maintenance screen은 기존 operator approval control을 유지하되 canonical Insight placement와 명확히 분리한다.
- Formatter·Lint·타입: backend 별도 formatter/lint/type 명령은 없다. frontend ESLint를 실행한다.
- 빌드·수동 확인: focused/full backend, frontend test/lint/build, canonical container build, `git diff --check`, changed docs link check. 가능하면 browser에서 viewer/non-live/live navigation과 category display를 수동 확인한다. live Proxmox mutation은 수행하지 않는다.

## 9. 문서 영향

- Project Specification: FR-010 범위는 이미 승인돼 있어 요구사항 변경이 없으면 수정하지 않는다.
- Architecture·ADR: Architecture current state와 Project Profile을 갱신한다. 기존 ADR을 구현하는 범위라 새 ADR은 만들지 않는다.
- Domain·Flow: Domain Map의 Insights 현재 구현 범위를 갱신한다. operation lifecycle이 바뀌지 않으므로 기존 operation flow는 영향이 있을 때만 수정한다.
- API·Database: current API에 additive `/insights`와 compatibility route 상태를 기록한다. schema 변경은 없으며 Database 문서에는 no-migration과 current source ownership만 필요한 경우 갱신한다.
- 상위 Plan: 단계 9 결과와 다음 단계 10 상태를 갱신한다.

## 10. 복구와 위험 완화

- 주요 위험: recommendation/approval 경계 혼합, unavailable→healthy 축소, cross-source freshness 혼동, DRS/Risks route 회귀, legacy component를 새 domain에 재노출, unbounded finding payload.
- 예방·관찰 방법: common read-only invariant, section별 availability/provenance, deterministic bounded findings, compatibility characterization, import/source guard, additive API와 direct legacy route 유지.
- rollback 또는 roll-forward: schema/data 변화가 없으므로 new Insights endpoint/module/page/nav wiring을 code rollback할 수 있다. 기존 DRS·Risks는 계속 독립 동작한다. 공개 후 contract 오류는 additive field/rule version bump로 roll-forward한다.
- 중단 기준:
  - Insight request/UI에서 approval packet, operation, DRS execute 또는 Proxmox mutation을 생성할 수 있음.
  - non-live/DB failure/unknown metric이 green·balanced·no-risk로 표현됨.
  - existing DRS data/API/route가 삭제되거나 execution semantics가 바뀜.
  - DB schema, data migration, scheduler/cache/new dependency가 필요해짐.
  - source/observed_at/freshness/rule version/evidence 중 하나가 없는 finding이 공개됨.
  - focused 또는 full regression이 실패함.

## 11. 구현 후 대조

- 계획과 달라진 부분:
  - finding payload를 section당 200개로 제한하는 동시에 `finding_count`, `returned_finding_count`, `truncated`를 추가해 제한 밖 total을 숨기지 않았다.
  - live snapshot이라도 CPU/memory/storage가 일부 미관찰이거나 node inventory가 비어 있으면 capacity를 `unknown`으로 표시하고, placement가 빈 healthy 결과로 축소되지 않도록 source evidence completeness를 전달했다.
- 달라진 이유: 독립 품질 검토에서 partial metric과 unknown placement가 `ready`로 축소될 수 있고 bounded payload의 실제 total이 과소 보고되는 세 결함을 확인했기 때문이다.
- 최종 구현 결과:
  - `backend/app/insights/`에 common finding/section/snapshot, read ports, application orchestration, versioned rule, existing source facade를 추가했다.
  - `GET /api/v1/insights`와 frontend Insight entity/feature/page, 다섯 canonical route를 추가했다.
  - primary `DRS Advisor` navigation은 `Insights`로 교체하고 `/drs`에는 maintenance 상태와 `/insights/placement` link를 표시했다. 기존 DRS/Risks route, API, control, data는 삭제하지 않았다.
  - 기존 `list_job_runs()`는 fails-open compatibility를 유지하고 `list_job_runs_strict()`만 새 Insights에 사용한다.
- 최종 검증 결과:
  - focused backend Insights/DRS/Risks/Jobs suite `40 passed`; 실제 facade와 DRS adapter compatibility test 포함.
  - host Python 3.14 backend 전체 `457 passed`.
  - host Node 26 frontend test 17개, ESLint, Vite production build 통과. Vite는 500 kB 초과 chunk 경고를 출력했지만 build는 성공했다.
  - canonical Python 3.13 backend 전체 `457 passed`; canonical Node 24/pnpm 10 frontend test 17개·ESLint·Vite production build와 production image build 통과.
  - `git diff --check` 통과. DB migration, browser 수동 확인, live Proxmox mutation은 수행하지 않았다.
- 갱신한 현재 상태 문서: Project Profile, Architecture Overview, Domain Map, current API, 상위 전환 Plan, 이 상세 Plan. 요구사항과 ADR은 승인된 방향이 바뀌지 않아 수정하지 않았고 DB schema/operation lifecycle도 변경하지 않았다.
- 남은 위험:
  - Insights는 request-time derived model이며 metric retention/stale snapshot persistence가 없다. Proxmox non-live에서는 inventory category를 다시 볼 수 없다.
  - legacy Jobs/Risks endpoint의 DB error → empty list 의미와 DRS maintenance execution은 별도 제거 Plan 전 남아 있다. DRS는 유지·확장 대상이 아니라 제거 대상 compatibility surface다.
  - browser 수동 a11y/navigation과 live cluster rule 적합성은 확인하지 않았다. live Proxmox mutation은 범위 밖이다.
