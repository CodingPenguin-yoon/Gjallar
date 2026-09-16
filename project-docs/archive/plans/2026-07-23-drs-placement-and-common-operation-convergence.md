# 구현 계획: DRS Placement 경계와 Common Operation 점진 통합

> 종료된 계획의 당시 조사·승인·검증 기록이다. 현재 구현 지시가 아니며 후속 방향은 [계획 인덱스](../../plans/README.md), 현재 기준은 [문서 안내](../../README.md)를 따른다.

- 상태: `ROLLED_BACK`
- 날짜: `2026-07-23`
- 관련 요구사항: [`Project Specification`](../../specifications/project-specification.md) FR-003, FR-004, FR-005, FR-008, FR-010, FR-012
- 관련 ADR: [`ADR-002`](../../decisions/adr-002-modular-monolith-domain-boundaries.md), [`ADR-004`](../../decisions/adr-004-postgresql-durable-operation-recovery.md), [`ADR-005`](../../decisions/adr-005-drs-placement-and-operation-convergence.md)
- 관련 상위 Plan: [`Backend 모듈 경계·legacy 격리`](2026-07-23-backend-modular-boundaries-and-legacy-compatibility.md)
- 승인자: `사용자`

> 2026-07-23 정정: neutral Placement를 분리한 단계 1~2는 유지한다. DRS를 유지한 채 Common Operation에 통합하는 단계 3~7은 사용자의 실제 목표와 달라 모두 롤백했다. 현재 DRS는 기존 전용 execution/reconciliation 경로를 사용하며, DRS 제거와 Insights/Monitoring 통합은 별도 Plan 대상이다.
- 승인일: `2026-07-23`
- 현재 진행: `단계 1~2 유지, 단계 3~7 롤백`

이 Plan은 당시 ADR-005의 선택지 A를 적용하려 작성했으나 방향 정정으로 롤백됐다. 아래 단계 3~7은 실행 계획의 역사적 기록이며 현재 구현을 설명하지 않는다.

## 1. 위험도

- 분류: `HIGH`
- 판단 근거:
  - observe-only Insights와 privileged DRS migration 사이의 도메인·의존성 경계를 바꾼다.
  - 외부 Proxmox mutation 전후에 DRS state와 Common Operation을 함께 기록하는 정합성 순서를 추가한다.
  - prepared/no-UPID, accepted UPID 뒤 저장 실패, task/post-check 불일치에서 second mutation과 false success를 막아야 한다.
  - DRS lock owner 의미를 authenticated user에서 operation identity로 바로잡아야 한다.
- 실패 영향:
  - placement 결과·DRS approval binding 회귀
  - 외부 mutation은 실행됐지만 두 projection이 서로 다른 상태로 남는 문제
  - ambiguous result에서 lock 조기 해제 또는 second mutation
  - 기존 13개 DRS API와 frontend maintenance 화면 회귀
- 되돌리기 어려운 부분:
  - 새 Common Operation/event row는 audit evidence이므로 코드 rollback 때 삭제하지 않는다.
  - 이 Plan에는 schema 변경과 기존 데이터 변환이 없어 destructive rollback은 없다.

## 2. 확인한 현재 상태

- Placement:
  - `backend/app/insights/facade.py`가 `_PlacementPort`를 통해 `app.drs.advisor.build_drs_advisor_model()`을 호출한다.
  - `app.drs.advisor`는 inventory normalization·node pressure·candidate·route scoring과 DRS identity resolution, policy/lock 조회, final check를 한 모듈에서 수행한다.
  - advisor 계산 중 `resolve_inventory_identities()`가 `vm_identities`와 observation을 기록하므로 `/insights` GET이 persistent write를 유발할 수 있다.
  - Insights placement section은 recommendation의 VM/source/target/reason/effect/blocker/criteria/route만 필요하며 DRS approval·execution port는 제공하지 않는다.
- DRS execution:
  - approval은 `DrsApprovalPacketRecord`와 `DrsMigrationJobRecord`를 한 DB transaction으로 저장한 뒤 Jobs projection을 기록한다.
  - execute는 exact approval과 fresh final check를 확인하고 identity/locator/route lock, durable `prepared` attempt, Proxmox migrate POST, accepted UPID, task/post-check, DRS result/reconciliation, job/artifact를 순서대로 기록한다.
  - prepared 뒤 UPID가 없으면 재진입은 mutation을 다시 호출하지 않고 `needs_reconciliation`으로 전환한다.
  - Common Operation 상태기계는 `approved → dispatching → running → verifying → succeeded`, `blocked`, `needs_reconciliation`을 이미 표현할 수 있다.
  - `operations.operation_type`은 `drs_migration`을 막는 DB enum/check가 없어 새 schema migration은 필요하지 않다.
  - DRS operation lock의 `owner_id`는 현재 authenticated user ID지만 Common Operation lock convention은 `operation_id`다. release/reconcile은 저장된 lock ID를 사용하므로 기존 row 일괄 변경은 필요하지 않다.
- 공개·운영 계약:
  - `/api/v1/drs/*` 13개 route와 `/drs` maintenance UI, policy/history/reconciliation은 유지 대상이다.
  - DRS approval/execution은 `job_runs`와 `job_artifacts`를 계속 생산하며 이번 Plan에서는 제거하지 않는다.
  - DRS용 background recovery handler는 없고 operator reconciliation만 존재한다.
- 확인되지 않은 항목:
  - production DRS/job/artifact row 수와 retention
  - 저장소 밖 DRS API consumer
  - 향후 automatic DRS recovery runner 도입 여부

## 3. 목표와 범위

- 목표:
  - placement 계산을 infrastructure-free neutral Insights 경계로 분리하고 `/insights`에서 DRS package·DB write 의존을 제거한다.
  - DRS advisor가 같은 placement 계산에 DRS identity/policy/lock/final-check evidence만 결합하도록 만든다.
  - 신규 DRS migration을 같은 ID의 Common Operation/event에 additive하게 연결한다.
  - 외부 mutation 전 durable 준비 실패는 fail-closed하고 외부 effect 뒤 projection 실패는 reconciliation으로 보존한다.
- 범위:
  - 신규 `backend/app/insights/placement.py` 또는 동등한 neutral placement package
  - `insights/facade.py`의 neutral placement port 사용
  - `drs/advisor.py`의 compatibility enrichment adapter화
  - 신규 `backend/app/operations/drs_migration/` domain/application/facade
  - DRS approval·execute·reconcile의 Common Operation mapping과 additive response link
  - 신규 DRS lock의 `owner_id=operation_id`
  - 관련 unit/contract/failure-injection test와 현재 상태 문서
- 비범위:
  - DRS, Jobs/Risks, Artifacts API·UI·table 삭제 또는 rename
  - Alembic migration, 기존 row 일괄 backfill, retention 변경
  - existing job/artifact producer 제거
  - DRS automatic recovery runner, queue, scheduler, 외부 worker
  - 실제 Proxmox migration 또는 다른 live mutation
  - placement 알고리즘·threshold의 의도적 제품 변경
- 인수 조건:
  - `/insights` placement가 `app.drs` import, DB session, identity/policy/lock write 없이 같은 공개 section 계약을 만든다.
  - 기존 DRS recommendation/check/approval/execute/reconcile 결과와 13개 route·RBAC가 유지된다.
  - 신규 approval은 `operation_id=job_id`, `operation_type=drs_migration`인 Common Operation을 exact approval evidence와 함께 준비한다.
  - Common Operation과 DRS durable pre-dispatch 기록 중 하나라도 실패하면 Proxmox POST는 호출되지 않는다.
  - accepted UPID 이후 verified DRS terminal state가 저장되기 전 projection 실패는 성공이나 automatic retry로 축소되지 않고 reconciliation과 lock retention으로 남는다.
  - DRS verified completion 뒤 마지막 Common Operation projection만 실패하면 migration 없이 projection만 복구하며, 복구 전 성공 응답을 공표하지 않는다.
  - pre-existing DRS job은 execute/reconcile 진입 시 operation을 idempotent하게 lazy ensure하고 bulk backfill하지 않는다.
  - live Proxmox mutation 없이 전체 계약을 fake client로 검증한다.

## 4. 아키텍처와 데이터 영향

- 모듈과 의존성:
  - `insights/placement`: inventory snapshot을 받아 pressure, candidate, route, recommendation을 계산하는 순수 application/domain 경계
  - `insights/facade`: neutral placement와 risk/readiness/capacity를 조합
  - `drs/advisor`: neutral result에 stable identity, policy, lock, final pre-check를 결합하는 compatibility adapter
  - `operations/drs_migration`: stable intent와 DRS lifecycle→Common Operation transition/event mapping
  - `drs/application`·`drs/approval`·`drs/execution`: 기존 workflow 순서를 유지하며 tracker를 명시적으로 호출
- 데이터 소유권:
  - neutral placement는 persistent state를 소유하지 않는다.
  - DRS identity/policy/approval/job/reconciliation table은 계속 DRS compatibility 영역이 소유한다.
  - Common Operation은 신규 DRS migration의 execution projection과 checksum-linked event를 소유한다.
  - Jobs/Artifacts는 기존 compatibility evidence로 유지하되 신규 책임을 추가하지 않는다.
- Operation identity와 intent:
  - `operation_id=job_id`
  - `operation_type=drs_migration`
  - `execution_mode=managed_api`
  - `target_type=proxmox_vm`, `target_id=vmid:{vmid}`
  - `idempotency_key=job_id`
  - stable intent는 cluster, approval/job/recommendation ID, stable VM identity, VMID, source/target node와 exact approval/check checksum을 포함한다.
  - `plan_digest`는 저장된 approval packet checksum에 bind한다.
- 상태 mapping:

| DRS 의미 | Common Operation |
|---|---|
| approval packet·pending job | `approved` |
| clear pre-dispatch blocker | `blocked` |
| durable prepared attempt | `dispatching` |
| accepted UPID | `running` |
| task 완료·direct post-check 진행 | `verifying` |
| verified migration 완료 | `succeeded` |
| missing UPID·task unknown·post-check mismatch·projection uncertainty | `needs_reconciliation` |

- 트랜잭션·정합성 순서:
  1. approval의 DRS packet/job transaction을 완료하고 같은 exact intent의 Common Operation `approved`를 기록한다. Operation 기록 실패 시 approval 응답을 성공으로 공표하지 않으며 재호출로 idempotent repair한다.
  2. execute의 모든 read-only pre-check와 DRS lock 획득 뒤 Common Operation을 `dispatching`으로 전이하고 DRS `prepared`를 저장한다. 둘 중 하나라도 실패하면 POST를 호출하지 않는다. 외부 effect가 없음을 확인한 경우 새 lock을 해제하고 Common Operation을 `failed`로 닫으며 같은 job의 execute retry 대신 새 approval을 요구한다.
  3. POST가 accepted UPID를 반환하면 DRS UPID를 먼저 저장하고 Common Operation을 `running`으로 전이한다.
  4. UPID 뒤 Common Operation 기록 실패는 DRS를 `needs_reconciliation`으로 보존하고 lock을 유지한다. 성공이나 POST 재시도로 바꾸지 않는다.
  5. task/direct post-check가 성공하면 Common Operation을 먼저 `verifying`으로 전이한다. 이 전이가 실패하면 DRS를 아직 terminal success로 확정하지 않고 reconciliation과 lock을 유지한다.
  6. Common Operation `verifying` 뒤 기존 DRS completion, job/artifact와 verified post-check를 저장하고 DRS 규칙에 따라 lock을 해제한 다음 Common Operation을 `succeeded`로 전이한다.
  7. 마지막 `succeeded` 기록만 실패하면 DRS verified completion은 canonical evidence로 유지한다. 성공 응답은 공표하지 않고, execute/reconcile 재진입은 Proxmox POST 없이 `verifying → succeeded` projection만 idempotent하게 repair한다. verified terminal evidence가 있으므로 이 경우 lock을 다시 획득하거나 유지하지 않는다.
- lock:
  - 신규 DRS identity/locator/route lock은 `owner_id=job_id=operation_id`를 사용하고 actor는 event/evidence에 별도로 남긴다.
  - 기존 user-owned open lock은 lock ID 기반 reconcile/release를 유지하며 일괄 수정하지 않는다.
- API·DB:
  - 기존 field/path는 제거하지 않는다.
  - DRS response에 `operation_id`와 operation link를 additive하게 제공한다.
  - 새 table/column/index는 만들지 않는다.

### 실패 단계별 보존 규칙

| 실패 시점 | 외부 effect 판단 | DRS 상태 | Common Operation | lock | 재진입 |
|---|---|---|---|---|---|
| Common `dispatching` 또는 DRS `prepared` 저장 전/중 | POST 0회로 확정 | `pending`/`blocked` | `failed` 또는 local repair 필요 | 새 lock 해제 | 같은 job mutation 금지, 새 approval |
| DRS `prepared` 뒤 UPID 없음 | mutation 여부 불명확 | `needs_reconciliation` | `needs_reconciliation` | 유지 | read-only reconciliation만 |
| UPID 저장 뒤 Common `running` 실패 | migration accepted | `needs_reconciliation` | `dispatching` 또는 `needs_reconciliation` | 유지 | projection repair와 task 관찰만 |
| task unknown·post-check mismatch·`verifying` 준비 실패 | terminal 결과 불명확 | `needs_reconciliation` | `needs_reconciliation` 가능한 범위까지 | 유지 | read-only reconciliation만 |
| DRS verified completion 뒤 Common `succeeded` 실패 | 성공 verified | `completed` | `verifying` | DRS 규칙에 따라 해제 | Common projection만 repair, POST 금지 |

## 5. 선택지와 결정

| 순위 | 선택지 | 적합한 이유 | 단점·비용 | 추천 여부 |
|---:|---|---|---|---|
| 1 | DRS state canonical + Common Operation additive, neutral placement 우선 분리 | 공개·DB 계약을 보존하고 단계별 실패를 격리할 수 있음 | 과도기 dual projection과 repair test 필요 | 추천 |
| 2 | Common Operation을 즉시 유일한 canonical state로 전환 | 목표 구조가 단순함 | 기존 DRS API/history/reconcile 의미와 row migration이 동시에 바뀜 | 제외 |
| 3 | placement만 분리하고 DRS Operation 통합 보류 | 조회 side effect는 제거 가능 | DRS execution/evidence 상태기계 이중화가 계속됨 | 차선 |

- 아키텍처 방향 결정: `1번`, ADR-005에서 사용자 승인
- 이 구현 Plan 승인: `사용자 승인, 2026-07-23`

승인 요청의 핵심은 “기존 DRS state를 초기 canonical로 유지하면서 Common Operation을 additive하게 기록하고, 위 순서의 dual-record 실패를 reconciliation으로 처리한다”는 구현 경계다.

## 6. 구현 단계

| 단계 | 결과 | 변경 책임·예상 파일 | 검증 | 복구 지점 |
|---:|---|---|---|---|
| 1 | neutral placement characterization | 기존 Insights/DRS recommendation fixture, no-write 경계 test | 출력·ID·blocker/route snapshot | test-only revert |
| 2 | placement 계산 분리 | `insights/placement.py`, `insights/facade.py`, `drs/advisor.py` | Insights no-DRS-import/no-DB-write, DRS advisor regression | DRS adapter가 기존 계산 호출 |
| 3 | DRS Operation tracker | `operations/drs_migration/{domain,application,facade}.py` | in-memory store 상태·intent·event unit test | 호출하지 않는 additive module 유지 |
| 4 | approval 연결과 lazy ensure | `drs/approval.py`, `drs/application.py` | exact checksum, replay, pre-existing job repair | tracker 호출 제거; DRS row 유지 |
| 5 | execute 연결과 lock owner 정리 | `drs/execution.py`, `drs/operation_locks.py` | pre-dispatch failure, UPID, task/post-check, lock failure injection | mutation 전 dual record gate 비활성화 |
| 6 | reconcile·response 연결 | DRS facade/API response mapping | 성공/미해결 reconcile, additive link, 13 route/RBAC | optional link와 tracker adapter 제거 |
| 7 | 전체 검증·문서·독립 리뷰 | backend/frontend contract, current docs, quality review | full suite, diff audit, no migration/mutation audit | 발견 사항별 roll-forward |

각 단계는 focused test를 통과한 뒤 다음 단계로 진행한다. 단계 2 뒤 Insights 경계가 안정된 상태를 독립 복구 지점으로 유지한다.

## 7. 성공·실패·데이터 흐름

- 성공:
  - inventory → neutral placement → Insights section
  - inventory → neutral placement → DRS evidence enrichment → approval packet/job + Common Operation approved
  - execute gate → Common dispatching + DRS prepared → Proxmox POST → DRS accepted UPID + Common running → task/post-check → DRS completion + Common verifying/succeeded
- 명확한 dispatch 전 실패:
  - blocker → POST 없음 → DRS/Common `blocked`
  - durable 준비 기록 실패 → POST 없음 → 새 lock 해제와 Common `failed` 가능한 범위까지 기록 → 같은 job mutation 재시도 금지
- 모호한 dispatch 이후 실패:
  - missing UPID, accepted task unknown, post-check mismatch, dual-record failure → DRS/Common `needs_reconciliation` 가능한 범위까지 기록 → 모든 operation lock 유지 → second POST 없음
- manual reconcile:
  - 기존 acknowledgement와 read-only preview/check를 유지한다.
  - 성공 판정이면 Common `needs_reconciliation → verifying → succeeded`를 repair한다.
  - 확인 불가면 event만 추가하고 `needs_reconciliation`과 lock을 유지한다.
  - DRS verified completion 뒤 Common projection만 남은 경우에는 task나 migration을 다시 실행하지 않고 `verifying → succeeded`만 복구한다.
- 보상:
  - reverse migration, automatic retry, lock TTL expiry를 보상으로 사용하지 않는다.

## 8. 테스트와 검증 계획

- Placement:
  - 동일 inventory fixture에서 기존 recommendation ID, source/target, blocker, route와 Insights section 유지
  - `insights` application/placement의 `app.drs` import 금지 source contract
  - `/insights` GET 중 DRS identity/policy/lock DB write가 없다는 test
  - missing metric, empty node, unavailable source의 보수적 결과
- DRS Operation:
  - stable intent/digest와 approval replay/conflict
  - pending→approved, dispatching, running, verifying, succeeded mapping
  - clear blocker와 reconciliation mapping
  - pre-existing job lazy ensure와 bulk backfill 부재
- Failure injection:
  - Common dispatching 실패와 DRS prepared 실패 모두 POST 0회
  - POST timeout/missing UPID에서 second POST 0회
  - accepted UPID 뒤 Common `running`/`verifying` write 실패에서 false success 0회, lock retained
  - verified DRS completion 뒤 Common `succeeded` write 실패에서 POST 0회 projection repair와 안전한 lock 해제
  - task failure/post-check mismatch/terminal event failure와 manual repair
  - new lock owner가 operation ID이고 existing lock ID 기반 reconcile이 유지됨
- 계약:
  - `/api/v1` 52개 route와 DRS 13개 path/RBAC
  - Insights와 DRS response 기존 field 유지, operation link additive
  - frontend DRS/Insights consumer test
- 실행 명령:
  - focused pytest
  - `PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests`
  - `pnpm run test:frontend`, `pnpm --dir frontend lint`, `pnpm --dir frontend build`
  - `git diff --check`
- 미실행:
  - live Proxmox migration
  - production DB backfill·schema migration

## 9. 문서 영향

- `project-profile.md`: neutral placement와 DRS Operation 통합의 실제 구현 상태·검증 기준선
- `architecture/overview.md`: Insights/DRS/Operations 경계와 dual-record 흐름
- `domains/domain-map.md`: placement read ownership과 DRS execution projection ownership
- `api/current-api-v1.md`: additive operation link와 유지되는 DRS compatibility 계약
- `database/current-schema-and-ownership.md`: schema가 아니라 logical ownership과 신규 row 관계
- `architecture/drs-jobs-convergence-assessment.md`: 선택지 A의 실제 진행 상태
- 이 Plan: 승인, 실제 구현 차이, 검증·리뷰 결과

## 10. 복구와 위험 완화

- 예방:
  - placement 출력 characterization을 먼저 고정한다.
  - external mutation 전 두 durable 준비 기록을 fail-closed한다.
  - external effect 이후 error는 성공/재시도가 아닌 reconciliation으로 분류한다.
  - operation/event payload는 redaction하고 approval checksum과 actor를 server-side evidence로 기록한다.
- rollback 또는 roll-forward:
  - placement 분리는 공개 결과가 유지되면 DRS compatibility adapter를 이전 계산 경계로 되돌릴 수 있다.
  - Common Operation 호출을 제거해도 이미 생긴 operation/event row는 삭제하지 않는다.
  - accepted UPID 이후에는 코드 rollback보다 저장된 DRS job/lock/evidence를 통한 operator reconciliation을 우선한다.
  - schema migration이 없으므로 DB downgrade는 수행하지 않는다.
- 배포 전 점검:
  - non-terminal DRS job, Common Operation, open DRS/locator lock을 함께 조회한다.
  - 새 코드와 구버전 replica가 동시에 DRS mutation을 처리하지 않도록 mutation drain한다.
- 중단 기준:
  - placement/DRS 공개 결과 또는 route/RBAC drift
  - dual-record 실패가 false success나 second mutation으로 이어짐
  - ambiguity에서 lock이 해제됨
  - 기존 DRS job을 lazy repair할 수 없음
  - secret/raw upstream error가 Operation evidence로 유출됨

## 11. 롤백 후 대조

- 유지한 범위: 단계 1~2. `backend/app/insights/placement.py`가 inventory normalization, pressure/candidate/route 계산을 소유하고, `insights/facade.py`는 DRS import 없이 neutral model을 사용한다. `drs/advisor.py`는 기존 호환 계약을 위해 neutral candidate에 identity/policy/final gate를 보강한다.
- 롤백한 범위: 단계 3~7의 `backend/app/operations/drs_migration/`, approval·execute·reconcile Common Operation 호출, additive operation response link, DRS lock owner 변경, 전용 failure-injection test와 artifact/repository transaction 확장.
- 현재 계약: 기존 13개 DRS route, RBAC, DRS/Jobs/Artifacts table과 기존 response field는 유지한다. DRS migration은 Common Operation을 만들거나 링크하지 않는다.
- 데이터 영향: schema migration, backfill, production DB write, live Proxmox migration은 수행하지 않았다. 롤백 대상은 commit되지 않은 코드·테스트·문서 변경뿐이다.
- 롤백 검증: local Python 3.14 backend 전체 `514 passed, 2 skipped`, DRS·route·Placement 집중 `120 passed`, 관련 module `py_compile`, `git diff --check`가 통과했다. 통합 전부터 존재하던 DRS execution/approval/artifact/repository 테스트 파일은 HEAD와 diff가 0임을 확인했다.
- 품질 리뷰: 롤백 대상 source·test·문서의 잔존 참조는 없었다. 삭제된 모듈과 테스트에서 생성된 ignored `__pycache__`만 발견해 제거했고, 라우터 분리·neutral Placement·기존 사용자 변경은 보존했다.
- 후속: DRS maintenance 기능을 제거하고 Insights/Monitoring으로 통합할 실제 범위, consumer, 이력 보존과 DB contract 단계를 별도 Plan으로 확정한다.
