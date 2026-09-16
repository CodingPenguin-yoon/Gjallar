# 구현 계획: Observe → Explain → Verified Action 핵심 흐름 완성

> 종료된 계획의 당시 조사·승인·검증 기록이다. 현재 구현 지시가 아니며 후속 방향은 [계획 인덱스](../../plans/README.md), 현재 기준은 [문서 안내](../../README.md)를 따른다.

- 상태: `IMPLEMENTED`
- 날짜: `2026-08-26`
- 완료일: `2026-08-26`
- 관련 요구사항: [`Project Specification`](../../specifications/project-specification.md)
- 관련 ADR: [`ADR-007`](../../decisions/adr-007-observe-first-operations-intelligence.md)
- 관련 현재 상태: [`Architecture Overview`](../../architecture/overview.md), [`Current API v1`](../../api/current-api-v1.md), [`Verified Operation Lifecycle`](../../flows/verified-operation-lifecycle.md)
- 상위 방향: [`Observe-first Operations Intelligence 전환`](2026-08-24-observe-first-operations-intelligence-transition.md)
- 승인자: `사용자`
- 승인일: `2026-08-26`

이 Plan은 2026-08-26 기능 전수 감사와 사용자가 승인한 세 가지 추천 범위를 첫 구현 단위로 좁힌다. 제품의 canonical 흐름은 `Workloads(대상) → Insights(원인·근거) → Operations(작업 결과·증거)`로 정한다. Operations는 실행 결과·증거의 canonical surface, Jobs는 역사·호환 surface, legacy Risks는 Insights로 통합할 대상으로 본다. Network Readiness 계산은 유지하되 독립 migration-oriented surface는 Insights에 통합한 뒤 primary 노출을 중단한다. 이 방향의 실제 통합·노출 변경은 첫 구현 이후 별도 Plan으로 수행한다.

## 1. 위험도

- 분류: `HIGH`
- 판단 근거: 실제 상태의 성공·실패 의미, `/api/v1` 공개 read contract, Operation correlation, 화면 간 canonical navigation을 바꾼다.
- 실패 영향: 관찰 실패를 정상 빈 상태로 오인하거나, 다른 VM의 이력을 연결하거나, 작업이 생성되었는데도 사용자가 증거에 도달하지 못할 수 있다.
- 되돌리기 어려운 부분: 이번 범위에는 DB schema·data migration, 기존 route/API 삭제, live Proxmox mutation이 없다. API 변경은 기존 필드를 보존하는 additive field/filter와 명시적 unavailable 오류로 제한한다.

## 2. 확인한 현재·전환·목표 상태

### 현재 상태

- Overview의 구조와 시각 방향은 현재 제품에서 가장 완성도가 높고 유지 대상이다. 다만 inventory sub-source와 Jobs/Risks 저장소 실패가 빈 배열 또는 성공 snapshot으로 축소되어 정상처럼 보일 수 있다.
- inventory 수집은 storage, network, VM config, guest-agent/detail 실패를 `[]` 또는 unknown 값으로 흡수하면서 상위 snapshot을 live/fresh로 표현할 수 있다.
- `/jobs`·legacy `/risks`는 저장소 예외를 빈 결과로 축소하는 compatibility 경로가 있고 Overview가 이를 소비한다.
- `/cluster/summary`는 설정된 cluster identity 대신 고정 문자열을 반환한다. `vm_shutdown`은 Jobs step 정의가 없어 Create VM 단계명으로 fallback한다.
- backend의 `GET /api/v1/vms/{vmid}`와 frontend `getVm()`은 존재하지만 `/instances/:vmid` route와 VM detail 흐름이 없다.
- Workloads·Insights는 대상 텍스트와 category 중심 연결만 제공하며 exact VM, 관련 finding, 관련 Operation 간 왕복 deep link가 닫혀 있지 않다.
- Operation backend detail은 `intent_digest`, `last_event_checksum`, event payload와 checksum chain을 반환하지만 frontend normalizer와 상세 화면이 이를 버린다.
- Operation 목록은 status/type/limit만 필터링하므로 특정 VM의 전체 관련 이력을 정확히 조회하지 못하고 frontend가 최근 최대 200개에서 추정한다.
- VM Start·Shutdown target lock 충돌은 Operation이 먼저 기록될 수 있지만 client 오류에는 해당 Operation 또는 충돌 Operation 식별자가 없다. 비동기 Operation 상세 화면은 terminal 상태까지 갱신되지 않는다.

### 전환 상태

- 기존 URL과 response field는 유지한 채 관찰 source별 availability와 Operation target filter/correlation을 additive하게 추가한다.
- Overview UI 구성은 유지하고, 데이터가 unavailable일 때 정상 empty state로 보이지 않도록 data semantics와 최소 상태 표현만 교정한다.
- exact VM detail route를 추가해 Workloads·Insights·Operations를 대상 identity로 연결한다.
- Operation 상세가 backend가 이미 가진 checksum-linked evidence를 손실 없이 보여주고 non-terminal 상태를 제한적으로 갱신한다.

### 목표 상태

- 사용자는 `상태 발견 → 원인과 근거 확인 → 제한된 작업 → 실행 결과와 증거 확인`을 exact target identity와 stable Operation ID로 끝낼 수 있다.
- 실패하거나 관찰되지 않은 source는 healthy·fresh·empty로 표현되지 않는다.
- Operations가 실행 결과·증거의 단일 canonical surface가 되고, 후속 Plan에서 Jobs·legacy Risks·Network Readiness의 primary 노출을 정리할 수 있는 기반이 생긴다.

## 3. 목표, 범위와 비범위

### 목표

1. 관찰 실패와 정상 빈 상태를 구분해 Overview와 inventory 기반 화면의 신뢰를 회복한다.
2. VM exact detail과 deep link로 Workloads·Insights·Operations의 대상 문맥을 연결한다.
3. 제한된 작업이 Operation ID, 상태, checksum-linked evidence로 닫히도록 조회·오류·UI 계약을 완성한다.

### 범위

- source별 observation availability/completeness를 inventory API meta 또는 동등한 additive contract로 제공하고 frontend가 이를 보수적으로 표시한다.
- `/jobs`·legacy `/risks` 저장소 실패를 성공한 빈 목록으로 반환하지 않는다. 저장소 unavailable은 `503`과 stable error code로 구분하고, 정상 조회 결과의 기존 envelope과 data field는 보존한다.
- `/cluster/summary`가 runtime configuration의 cluster identity를 사용하도록 교정한다.
- Jobs compatibility projection에 `vm_shutdown`의 실제 단계 정의를 추가한다.
- `/instances/:vmid`를 추가하고 기존 `GET /api/v1/vms/{vmid}`를 사용해 exact VM 상태, 관련 Insights finding, 관련 Operations를 조합한다.
- `GET /api/v1/operations`에 additive `target_type`·`target_id` filter를 추가한다. 기존 status/type/limit 계약은 유지한다.
- Workloads finding, Insights target, Operation target에서 exact VM detail 또는 exact Operation detail로 이동하는 stable deep link를 추가한다.
- frontend Operation model과 상세 화면이 `intent_digest`, `last_event_checksum`, event payload, `previous_checksum`, `checksum`을 보존·표시한다. secret-bearing 원문은 새로 노출하지 않고 기존 redaction boundary를 유지한다.
- non-terminal Operation 상세는 bounded polling을 사용하고 terminal·not-found·권한/연결 오류에서 중단한다.
- 작업이 이미 기록된 뒤 발생하는 target-lock conflict/error에는 사용자가 열 수 있는 `operation_id`와, 확인 가능한 경우 `conflicting_operation_id`를 additive error detail로 제공한다.
- 관련 backend/frontend contract·failure·navigation 테스트, 현재 상태 문서와 API/flow 문서를 갱신한다.

### 비범위

- Overview의 layout, visual hierarchy, navigation 구조 또는 전체 UI 리뉴얼
- 기존 API/route 삭제, legacy alias 제거, DRS·Jobs artifact/history 삭제 또는 retention 변경
- Network Readiness의 Insights 통합과 standalone 화면 노출 중단
- legacy Risks 화면의 primary 노출 중단과 Jobs 화면의 history-only 재구성
- Create VM target 선택·handoff·post-create readiness 재설계
- Guided `qm unlock` expiry sweeper, generic reconciliation/recovery control 추가
- finding lifecycle, observation history persistence, metric retention, scheduler·worker·새 dependency
- DB schema/data migration, production data 변경, live Proxmox mutation 또는 자동 remediation
- Account/Admin Users의 re-enable, audit history, pagination, rate limiting 확장
- commit, push, rebase 또는 release

## 4. 영향 범위와 경계

- 공개 API:
  - existing inventory payload field는 유지하고 source availability/completeness만 additive하게 추가한다.
  - `GET /api/v1/operations`에 exact target filter를 additive하게 추가한다.
  - Jobs/Risks의 정상 응답 형식은 유지하되 persistence failure의 HTTP 의미를 `200 []`에서 `503`으로 바로잡는다.
  - 기존 39개 route는 삭제하지 않는다.
- 데이터:
  - 기존 `operations`, `operation_events`, `job_runs`, `job_artifacts`를 그대로 읽는다.
  - schema, migration, backfill, row update/delete는 없다.
- 도메인 책임:
  - Workloads는 actual target observation, Insights는 explanation, Operations는 action result/evidence를 소유한다.
  - Jobs·legacy Risks는 이번 단계에서 compatibility source로만 유지하고 새 기능을 확장하지 않는다.
- 보안·권한:
  - `viewer < operator < admin`과 backend authorization을 유지한다.
  - evidence payload는 기존에 저장·반환되는 redacted data만 표시한다. token, password, raw credential, 임의 명령 입력은 추가하지 않는다.
- 외부 시스템:
  - Proxmox read failure 의미만 교정한다. 실제 Start/Shutdown/Create/Unlock을 새로 실행하는 검증은 하지 않는다.

## 5. 선택지와 추천 결정

| 순위 | 선택지 | 적합한 이유 | 단점·비용 | 결정 |
|---:|---|---|---|---|
| 1 | 관찰 신뢰 → VM 문맥 → Operation 증거를 한 vertical slice로 완성 | 핵심 사용자 흐름의 세 단절을 같은 target/operation identity로 닫고, schema·삭제 없이 단계별 복구할 수 있다. | backend와 frontend 공개 read contract를 함께 검증해야 한다. | 승인 |
| 2 | UI deep link와 evidence 표시만 먼저 추가 | 눈에 보이는 개선은 빠르다. | fail-open observation과 부정확한 최근 200개 추정이 남아 신뢰할 수 없는 연결이 된다. | 비추천 |
| 3 | Jobs/Risks/Network/Create/Guided까지 한 번에 통합 | 최종 표면을 빨리 단순화할 수 있다. | contract·recovery·retention·UI 노출 결정을 한 변경에 섞어 회귀와 복구 범위가 지나치게 커진다. | 이후 별도 Plan |

세부 계약은 다음을 추천한다.

- source failure는 정상 empty와 별도인 `unavailable`로 표현한다.
- persistence query 자체가 실패한 compatibility endpoint는 `503`과 stable error code를 반환한다.
- exact Operation 조회는 기존 target identity(`target_type`, `target_id`)를 재사용하고 새 식별 체계를 만들지 않는다.
- evidence는 원문 dump가 아니라 actor, transition, time, redacted payload, digest/checksum chain을 구조화해 표시한다.

## 6. 구현 단계와 단계별 검증

| 단계 | 결과 | 주요 변경 책임 | 검증 | 복구 지점 |
|---:|---|---|---|---|
| 0 | 현재 fail-open·deep-link·evidence 손실을 고정하는 characterization | backend/frontend tests | source exception, DB exception, target filter 부재, normalizer field loss 재현 | production code 변경 전 |
| 1 | 관찰 성공 의미 교정 | Proxmox inventory/connection facade, Jobs/Risks compatibility query, cluster summary, Jobs step definition | partial source failure가 live/fresh empty가 아님, DB failure `503`, 정상 empty 회귀, configured cluster ID, Shutdown 단계 | additive meta/error wiring 제거 |
| 2 | exact VM context와 대상 조회 | Operation read application/API, frontend API client, `/instances/:vmid`, Workloads/Insights links | target filter/order/auth/envelope, VM not-found/unavailable, finding·Operation exact link, 기존 `/instances` 회귀 | 새 filter/route/link 제거 |
| 3 | Operation evidence와 correlation 완성 | frontend Operation entity/detail, Start/Shutdown error mapping, bounded polling | digest/checksum/payload 보존, redaction, operation/conflict IDs, polling start/stop/error, terminal deep link | 새 표시·polling·error field 제거 |
| 4 | 전체 회귀와 현재 상태 문서 동기화 | tests, project-docs | backend full, frontend contracts/lint/build, `pnpm run verify`, 가능하면 `pnpm run verify:container`, `git diff --check`, route count | 문서와 구현 불일치 시 완료 중단 |
| 5 | 구현과 분리된 고위험 검토 | `$quality-review` | 공개 계약·권한·failure semantics·target identity·evidence redaction 검토와 발견사항 해소 | 미해결 high finding 시 완료 중단 |

각 단계는 앞 단계 검증 후 진행한다. 단계 1~3은 독립적으로 되돌릴 수 있어야 하며, 범위 밖 schema나 삭제가 필요해지면 구현을 중단하고 새 Plan 승인을 받는다.

## 7. 인수 조건

- 일부 inventory source가 실패하면 UI와 API에서 해당 source가 unavailable/incomplete로 보이며 healthy·fresh empty로 계산되지 않는다.
- Jobs/Risks 저장소 실패가 `200 []` 또는 정상 no-risk 상태로 보이지 않는다.
- Overview의 기존 화면 구조와 시각 방향은 유지된다.
- configured cluster identity와 Shutdown Jobs 단계가 실제 값·흐름과 일치한다.
- `/instances/:vmid`에서 exact VM 상태, 관련 finding, 관련 Operation을 조회할 수 있고 Workloads·Insights·Operations 사이를 같은 VM identity로 왕복할 수 있다.
- Operation 목록 target filter가 exact `target_type`·`target_id`만 반환하며 기존 filter와 정렬·limit 계약을 깨지 않는다.
- 지원 작업에서 Operation이 생성된 경우 성공·실패·target-lock conflict 어느 경로에서도 사용자가 관련 Operation detail에 도달할 수 있다.
- Operation detail에서 intent digest, 마지막 event checksum, 각 event의 redacted payload와 checksum chain을 확인할 수 있다.
- non-terminal detail은 bounded polling으로 갱신되고 terminal·오류·unmount에서 중단한다.
- 기존 39개 API route와 legacy URL은 제거되지 않고 auth/RBAC·response envelope 회귀 테스트가 통과한다.
- backend full test, frontend 계약 테스트, ESLint, production build, `git diff --check`가 통과한다. 실행하지 못한 검증은 이유와 잔여 위험을 명시한다.

## 8. 성공·실패·복구 흐름

- 성공: Overview/Workloads에서 상태 발견 → exact VM detail → Insights evidence → 허용된 action → stable Operation detail → terminal status와 checksum-linked evidence 확인.
- 관찰 실패: source별 unavailable을 유지하고 다른 정상 source와 구분한다. stale snapshot이나 empty list로 대체하지 않는다.
- 작업 충돌: 먼저 생성된 Operation과 현재 lock owner를 가능한 범위에서 모두 식별하고, 사용자를 해당 evidence로 연결한다. conflict를 새 작업 성공처럼 표현하지 않는다.
- polling 실패: 마지막으로 확인된 상태와 갱신 실패를 구분해 표시하고 무한 재시도하지 않는다.
- rollback: additive meta/filter/route/UI/correlation field를 단계별 제거해 기존 read contract로 되돌릴 수 있다. DB와 외부 Proxmox 상태는 변경하지 않는다.
- roll-forward: 외부 consumer가 새 `503` 의미에 영향을 받는 것이 확인되면 fail-open으로 되돌리지 않고 stable unavailable envelope 또는 versioned compatibility adapter를 별도 승인해 추가한다.

## 9. 중단 조건과 불확실성

다음 중 하나가 확인되면 현재 Plan 구현을 중단한다.

- source failure와 정상 empty를 구분하려면 inventory domain ownership 또는 persistence schema를 바꿔야 한다.
- API route 제거, DB migration/backfill/delete, legacy history retention 결정이 필요하다.
- evidence 표시가 credential·token·raw secret 또는 임의 외부 명령을 노출한다.
- target identity가 operation type마다 호환되지 않아 새 canonical ID migration이 필요하다.
- 테스트를 위해 live Proxmox mutation이나 production data 변경이 필수다.
- 기존 consumer가 Jobs/Risks의 `200 []` 실패 의미에 의존한다는 증거가 발견되고 호환 전략이 합의되지 않았다.

현재 남은 불확실성은 실제 외부 `/api/v1/jobs`·`/api/v1/risks` consumer 존재 여부, source availability를 어느 aggregate meta shape로 제공할지, Operation event payload의 UI 표시 허용 key다. 구현 단계 0에서 repository 내부 consumer와 기존 redaction contract를 먼저 고정하고, 공개 호환 범위를 넘으면 사용자에게 다시 승인받는다.

## 10. 후속 작업 순서

첫 Plan 완료 뒤에는 다음을 각각 별도 승인 범위로 진행한다.

1. **Operation reconciliation과 실행 흐름 안정화**: Create VM target/handoff, Guided expiry·lock release, generic recovery control의 실제 필요 범위를 정한다.
2. **제품 표면 통합**: Network Readiness evidence를 Insights topology/readiness에 통합하고 standalone surface를 primary navigation에서 내린다. legacy Risks는 Insights로, Jobs는 history/compatibility로 역할과 문구를 정리하되 route/API/data는 삭제하지 않는다.
3. **이력·수명주기 정책**: finding lifecycle, observation history, Operation/Jobs/artifact/DRS retention과 실제 deprecation 조건을 별도 데이터 Plan으로 결정한다.
4. **관리 기능 보강**: Account/Admin Users의 re-enable, audit history, pagination, rate limiting은 핵심 운영 흐름 완성 뒤 우선순위를 다시 정한다.
5. **전체 UI 정리**: 기능 범위와 정보 구조가 고정된 뒤에만 Overview를 기준으로 일관성을 다듬는다. Overview 자체 리뉴얼은 포함하지 않는다.

## 11. 승인 문구

이 Plan의 승인은 **저장소 내부에서 관찰 실패 의미를 교정하고, additive Operation target filter와 VM detail/deep link를 추가하며, 이미 저장된 Operation evidence와 correlation을 UI/API에서 손실 없이 연결하고, 관련 테스트·현재 상태 문서를 갱신하는 것**을 의미한다.

이 승인은 **Overview UI 리뉴얼, 기존 route/API/data 삭제, DB schema 또는 production data 변경, live Proxmox mutation, Network Readiness·legacy Risks·Jobs의 노출 통합 구현, Create VM·Guided Action recovery 확장, Account/Admin 확장, commit·push**를 의미하지 않는다.

## 12. 구현 결과

승인된 vertical slice를 다음과 같이 구현했다.

1. inventory endpoint의 data와 meta를 한 snapshot에서 만들고 storage·network·VM config·guest-agent·VM detail의 availability/completeness를 공개했다. partial snapshot은 read에 유지하되 Start/Shutdown과 최종 VM Create는 별도 complete-live provider로 차단했다.
2. Jobs/Risks persistence 실패를 stable `503`으로 교정하고 runtime cluster identity와 Shutdown Jobs 단계를 실제 계약에 맞췄다.
3. `/instances/:vmid` exact VM detail, exact Operation target filter, Workloads·Insights·Operations deep link를 추가했다. partial/unknown/stale/truncated coverage와 오래된 finding link를 정상 no-finding으로 축소하지 않는다.
4. Operation detail에 intent/plan digest, event payload와 checksum chain, recovery/target lock을 보존하고 5초·최대 60회 bounded polling과 stale-response generation guard를 추가했다.
5. Start/Shutdown target-lock conflict에서 현재 요청 Operation을 terminal `blocked`로 닫고 현재 `operation_id`, 확인 가능한 `conflicting_operation_id`와 lock evidence를 반환·보존했다.
6. partial Insights source 실패는 unknown finding으로 남기되, 다른 source에서 이미 관측한 config lock 같은 known critical을 함께 보존한다.

구현과 분리된 `$quality-review`의 최초 High 1건과 Medium 3건, 후속 재검토에서 찾은 exact-target empty/stale finding 및 known-risk 보존 경계를 모두 수정했다. 최종 재검토 결과는 Critical·High·Medium·Low 각각 0건이며 기존 네 finding은 모두 `Resolved`다.

### 최종 검증

| 검증 | 결과 |
|---|---|
| `PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests` | `422 passed, 5 skipped`, 기존 dependency deprecation warning 454건 |
| Node 24로 `frontend/tests/*.mjs` 전체 실행 | 17개 contract test 파일 통과 |
| Node 24로 frontend ESLint 실행 | warning/error 없이 통과 |
| Node 24로 Vite production build | 1,419 modules, build 통과 |
| `docker build --target backend-test -t gjallar-backend-test:local .` | Python 3.13 container에서 `422 passed, 5 skipped` |
| `docker build -t gjallar:local .` | Node 24/pnpm 10.34.5 frontend test·Lint·build와 production image 생성 통과 |
| `git diff --check` | 통과 |

로컬에 설치된 pnpm 11.x는 repository의 `>=10 <11` engine과 맞지 않아 `pnpm run verify`를 그대로 사용하지 않고, 같은 네 구성 명령을 repository 요구 Node 24로 직접 실행했다. Container 검증은 `verify:container`가 조합하는 두 Docker build를 직접 실행해 pnpm 10.34.5 기준까지 확인했다.

이번 구현은 기존 39개 API route와 RBAC를 유지했고 DB schema/data, live Proxmox mutation, production PostgreSQL data, 기존 route/API 삭제, Overview layout·visual hierarchy, commit·push를 변경하지 않았다. 실제 live Proxmox mutation과 운영 PostgreSQL을 대상으로 한 검증은 비범위로 남는다.
