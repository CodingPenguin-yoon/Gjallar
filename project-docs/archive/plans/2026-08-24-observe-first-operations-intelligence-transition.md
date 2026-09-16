# 구현 계획: Observe-first Operations Intelligence 전환과 DRS 안전 폐기

> 종료된 계획의 당시 조사·승인·검증 기록이다. 현재 구현 지시가 아니며 후속 방향은 [계획 인덱스](../../plans/README.md), 현재 기준은 [문서 안내](../../README.md)를 따른다.

- 상태: `IMPLEMENTED`
- 날짜: `2026-08-24`
- 관련 요구사항: [`Project Specification`](../../specifications/project-specification.md)
- 관련 ADR: [`ADR-007`](../../decisions/adr-007-observe-first-operations-intelligence.md)
- 상위 Plan: [`Verified Operations Control Plane 전환` 단계 11](2026-07-20-verified-operations-control-plane-transition.md)
- 승인자: `사용자`
- 승인일: `2026-08-24`
- 추가 구현 승인: `2026-08-24`, discovery 보고 뒤 사용자가 직전 제시된 `UI 중심 1차 정리` 범위에 `구현시작해`로 승인
- 최종 repository 전환 승인: `2026-08-24`, 사용자가 운영 중인 배포·외부 consumer·보존할 DRS production data가 없다는 전제를 수락하고 `그러면 진행`으로 full repository removal을 승인
- 진행 상태: `단계 0~7 repository 구현·검증·독립 quality review 완료; production 적용·외부 credential revoke·live mutation 미승인·미수행`

이 Plan은 기존 전환 Plan의 완료된 단계와 구현 이력을 변경하지 않는다. 미착수 상태인 DRS 단계적 폐기를 구체화하고 Gjallar의 제품 중심을 Observe-first Operations Intelligence로 재정렬한다. 사용자는 2026-08-24 제품 방향과 단계 1 read-only discovery를 먼저 승인했고, discovery 보고 뒤 `/insights` compatibility 보호와 frontend DRS navigation/control/API 호출 제거 및 두 non-mutating deprecation route 유지를 단계 2~3의 repository-only 구현 범위로 추가 승인했다. 이후 사용자는 Gjallar가 운영 중이 아니며 저장소 밖 consumer와 보존할 production DRS state가 없다는 전제를 명시적으로 수락하고 full repository removal을 승인했다. 이에 따라 backend 13개 route/runtime/reconciliation, frontend route/client, DRS 전용 config와 새 forward migration을 통한 DRS 전용 schema contract 제거까지 repository에서 수행한다. 실제 production DB migration 적용, production data 변경, 외부 Proxmox credential revoke와 live mutation은 계속 범위 밖이다.

## 1. 위험도

- 분류: `HIGH`
- 판단 근거:
  - 제품 정체성, domain priority와 dependency direction을 변경한다.
  - `/api/v1/drs/*` 공개 계약과 frontend route를 제거한다.
  - DRS 실행 권한, 별도 Proxmox credential과 reconciliation 경로를 폐기한다.
  - DRS 전용 table과 공유 table의 historical row, foreign key와 lock invariant를 구분해야 한다.
  - unresolved migration, reconciliation 또는 locator lock을 잘못 제거하면 실제 상태와 evidence가 어긋날 수 있다.
- 되돌리기 어려운 부분:
  - production row와 audit/history 삭제
  - 적용된 Alembic contract migration
  - 저장소 외부 API consumer 단절
  - Proxmox DRS credential revoke
- 기본 완화: read-only discovery → 신규 DRS producer 동결 → 내부 consumer 전환 → 공개 계약 deprecation → runtime code 제거 → 별도 data-retirement gate와 forward migration 순서를 사용한다.

## 2. 사용자 목표

Gjallar를 다음 제품 기준선으로 전환한다.

> Gjallar는 Proxmox의 상태와 운영 변화를 먼저 관찰하고 설명하며, 필요한 경우에만 검증된 변경 작업을 제공하는 Observe-first Operations Intelligence 제품이다.

구체적으로:

- DRS policy, approval, migration execution, reconciliation과 전용 UI/API를 제거한다.
- Proxmox actual state와 current node를 Gjallar 소유 상태로 복제하지 않는다.
- current state와 topology는 source, observed time, freshness와 provenance를 가진 observation으로 소비한다.
- Create VM, VM Start, graceful VM Shutdown과 현재 승인된 Guided `qm unlock`은 Verified Action으로 유지한다.
- risk, readiness, capacity, placement/topology health와 operation evidence를 운영 판단의 중심에 둔다.
- automatic migration과 automatic remediation은 제공하지 않는다.

## 3. 범위와 비범위

### 범위

- Project Specification, ADR, Project Profile, 목표 Domain Map과 navigation의 제품 중심 재정렬
- active DRS frontend 화면, API client와 저장소 내부 consumer 조사·전환
- 현재 `/api/v1/drs/*` 13개 route의 deprecation과 제거
- `backend/app/drs/`, DRS migration client와 `PROXMOX_DRS_*` runtime 설정 제거
- Insights의 DRS persistence·실행 경계 의존 제거; 공개 `drs_advisor` source와 `drs-rec-*` ID는 호환 값으로 보존
- DRS 전용 row, 열린 migration/reconciliation/lock과 retention 조사
- 승인된 마지막 forward migration을 통한 DRS 전용 DB contract 정리
- shared Jobs/Artifacts의 historical evidence와 renderer 보존

### 비범위

- `operation_locks`, `job_runs`, `job_artifacts` table 자체의 제거
- Jobs/Artifacts 전체를 Common Operation/Evidence로 전환하는 작업
- `operations`, `operation_events`, recovery와 일반 Verified Action lifecycle 재설계
- 일반 VM migration operation 재구현
- 다른 hypervisor 지원 구현
- 범용 시계열 DB, collector scheduler, alert manager 또는 notification system 도입
- automatic remediation, autonomous placement 또는 arbitrary shell/SSH
- 이 Plan만으로 수행하는 live Proxmox mutation
- 사용자 별도 승인 없는 production DB write, archive 삭제 또는 Proxmox token revoke

## 4. 인수 조건

- 현재 제품 문서가 Observe-first Operations Intelligence와 유지할 Verified Action 범위를 일관되게 설명한다.
- Workloads와 Insights는 Proxmox observation을 사용하지만 node/state를 Gjallar-owned actual state로 취급하지 않는다.
- Insights는 `observe_only`, `read_only=true`, `allowed_actions=[]`를 유지하고 DRS persistence, approval, execution 또는 migration client를 호출하지 않는다.
- active frontend navigation과 화면에서 DRS policy·approval·execution control이 사라진다.
- 승인된 deprecation 절차가 끝난 뒤 active `/api/v1/drs/*` 공개 route가 존재하지 않는다.
- `/insights`의 기존 `drs_advisor` source와 `drs-rec-*` ID를 바꿀 때는 저장소 안팎 consumer를 확인하고 stable alias 또는 명시적 deprecation 계약을 적용한다.
- active runtime code와 설정에 DRS migration producer 및 `PROXMOX_DRS_*` credential requirement가 남지 않는다.
- Create VM, VM Start, graceful VM Shutdown과 Guided `qm unlock`의 RBAC, target lock, idempotency, verification과 evidence 계약은 회귀하지 않는다.
- shared `operation_locks`, `job_runs`, `job_artifacts`와 non-DRS row가 보존된다.
- unresolved DRS job, reconciliation 또는 open lock을 삭제하거나 성공으로 재분류하지 않는다. 새 schema migration은 DRS 전용 table 또는 non-generic lock row가 하나라도 있으면 DDL 전에 중단한다.
- production 배포가 있었다면 DRS backend runtime·reconciliation 경로와 credential 제거는 non-terminal DRS job, unresolved reconciliation과 open `drs_migration` lock이 모두 0임을 확인한 뒤에만 시작한다. 사용자는 이번 repository 구현에 대해 운영 배포가 없다는 전제를 수락했으며 실제 production 적용은 수행하지 않는다.
- applied Alembic migration은 수정하지 않고 새 forward migration만 사용한다.
- historical ADR, migration과 승인된 archive를 제외한 active 제품 코드에서 DRS producer/consumer가 0이다.

## 5. 현재·과도기·목표 상태

| 구분 | 상태 |
|---|---|
| 변경 전 | Insights는 request-time read model이며 일부 source·ID에 DRS 명칭이 남아 있었다. `/drs`, `/instances/drs-policies`와 13개 `/api/v1/drs/*` route가 policy·approval·execution·reconciliation을 제공했고 DRS 전용 client, credential과 persistence도 active했다. |
| 구현 결과 | DRS 전용 frontend route/client, backend route/runtime/client/config와 ORM contract를 제거했다. 새 `20260824_0029` migration은 DRS row가 있으면 중단하며 shared lock/job/artifact를 보존한다. |
| 목표 | active DRS product/runtime surface가 없다. Gjallar는 provider observation과 operation evidence를 바탕으로 상태를 설명하고 승인된 소수의 Verified Action만 제공한다. shared coordination/evidence infrastructure와 필요한 historical evidence는 유지된다. |

## 6. 영향 분석

### 공개 계약

- 제거 완료:
  - `/api/v1/drs/*` 13개 route
  - `/drs`
  - `/instances/drs-policies`
  - frontend shared API의 DRS methods
- 보존한 compatibility:
  - Jobs의 historical `drs_migration` renderer
  - `/insights` 응답의 `drs_advisor` source와 `drs-rec-*` ID
- 저장소 밖 API consumer와 access-log는 로컬에서 관찰할 수 없었고, 사용자가 no-consumer 가정을 명시적으로 수락해 route removal을 승인했다.

### 데이터

| 분류 | 대상 | 원칙 |
|---|---|---|
| DRS 전용 제거 | `vm_identities`, `vm_identity_observations`, `vm_migration_policies`, `vm_migration_policy_events`, `drs_approval_packets`, `drs_migration_jobs`, `drs_reconciliation_events` | generic owner로 이전하지 않는다. 새 migration은 어느 table이든 row가 있으면 삭제하지 않고 중단한다. |
| 공유·보존 | `operation_locks`, `job_runs`, `job_artifacts` | table과 generic/non-DRS row를 제거하지 않는다. `operation_locks`의 DRS 전용 FK/scope/column만 hard-zero 뒤 분리하고 historical job/artifact는 유지한다. |
| 공통 operation/evidence | `operations`, `operation_events`, `operation_recovery_items` | 이 Plan에서 schema와 lifecycle을 변경하지 않는다. |

open `drs_migration` lock은 단순 삭제하지 않는다. Proxmox actual state와 stored evidence를 대조해 상태를 판정하고 필요한 운영자 결정이 끝날 때까지 같은 locator의 다른 mutation을 허용하지 않는다.

### 보안·권한

- DRS operator/admin mutation 권한과 acknowledgement route를 제거한다.
- viewer read 권한이나 현재 Verified Action의 operator/admin 권한을 확대하지 않는다.
- `PROXMOX_DRS_API_URL`, `PROXMOX_DRS_API_TOKEN_ID`, `PROXMOX_DRS_API_TOKEN_SECRET`, TLS와 timeout 설정을 active code·환경 예시·runbook에서 제거한다.
- 실제 Proxmox token revoke는 exact token과 consumer 확인 후 별도 외부 상태 변경 승인을 받는다.
- archive와 discovery 결과에는 secret-bearing payload를 포함하지 않는다.

### 도메인과 의존성

- Insights: evidence·freshness를 가진 read-only finding 소유
- Workloads: current workload identity와 Proxmox observation의 application boundary 소유
- Operations: Create/Start/Shutdown/Guided action과 shared locator lock 유지
- Evidence/Audit: retained job/artifact와 operation evidence 유지
- DRS: active domain에서 제거
- Proxmox adapter: node, VMID, UPID 같은 provider detail을 격리하지만 이번 Plan에서 범용 multi-hypervisor abstraction을 만들지 않는다.

### 외부 시스템

- Proxmox inventory read와 기존 Verified Action API는 유지한다.
- DRS live migration dispatch만 제거한다.
- PostgreSQL production row와 retention은 로컬에서 확인하지 않았고 production DB에는 migration을 적용하지 않는다.
- 저장소 밖 `/api/v1/drs/*` consumer는 도구로 관찰하지 못했으며 사용자가 없다는 전제를 수락했다.

## 7. 선택지와 추천

| 선택지 | 장점 | 단점·위험 | 판단 |
|---|---|---|---|
| 즉시 live code/API/table 일괄 삭제 | 가장 빠르게 코드량 감소 | 외부 consumer, open job/lock, history 손실과 shared data 오삭제 위험 | live 환경에는 제외 |
| discovery와 contract gate를 둔 단계적 폐기 | 공개 계약, 운영 상태와 evidence를 확인하면서 최종 구조에 도달 | 과도기 compatibility와 여러 release가 필요 | 추천 |
| DRS compatibility 장기 유지 | 단기 회귀 위험이 낮음 | 제거 대상 상태기계·credential·권한·테스트 유지 비용 지속 | 제외 |

초기 추천안은 DRS가 한동안 read/history compatibility로 남고 최종 DB contract 제거까지 별도 승인이 필요하다는 단점을 감수했다. 이후 사용자가 운영 배포·외부 consumer·보존할 production DRS state가 없다는 전제를 수락했으므로 repository에서는 중간 deprecation release 없이 최종 제거 상태로 바로 전환한다. 이 결정은 실제 production DB 적용이나 외부 credential 변경을 허용하지 않는다.

## 8. 구현 단계와 검증·복구 지점

| 단계 | 결과 | 검증 | 복구 지점 |
|---:|---|---|---|
| 0 | ADR-007, Specification, Profile과 목표 Domain Map을 승인된 제품 기준선으로 재정렬 | 문서 간 authority, 범위, 링크와 terminology 대조 | runtime code·DB 미변경 |
| 1 | 신규 DRS 기능·producer를 추가하지 않는 freeze 규칙 확인과 read-only discovery manifest 작성 | 내부 consumer, route, frontend, deployed config/credential dependency, table relationship, production row/status/기간, open job·reconciliation·lock, 외부 consumer와 `/insights` field/source/ID 의존 조사 | code·config·DB write, mutation과 migration 없음 |
| 2 | neutral Observation/Insights 경계와 compatibility 방식 확정 | Insights가 DRS DB write, policy/approval, migration client에 의존하지 않는 import/source/contract test; source·freshness·evidence 확인; `drs_advisor`/`drs-rec-*`에 대한 stable alias 또는 deprecation 계약 검증 | schema 변경 없는 adapter/wiring revert |
| 3 | frontend와 저장소 내부 consumer 전환 | DRS navigation/control 제거, Insights/Workloads replacement, Jobs/history 표시 결정, 기존 `/insights` consumer를 승인된 alias/deprecation 경로로 전환, frontend test/lint/build | backend 공개 API와 data 유지 |
| 4 | 신규 DRS migration 중단과 공개 계약 제거 | 운영 배포·외부 consumer가 없다는 사용자 전제를 기록하고 route/client absence contract로 신규 dispatch와 13개 공개 route 부재 검증 | data 미변경 상태에서 Git 기반 compatibility facade 복구 가능; live mutation은 자동 재활성화 금지 |
| 5 | 승인된 no-deployment 전제 아래 DRS backend runtime·client·config 제거 | `app.drs`, router wiring, migration client, `PROXMOX_DRS_*` active reference 0과 non-DRS full regression 검증 | 실제 production state가 뒤늦게 확인되면 새 image를 배포하지 않고 별도 recovery Plan 수립 |
| 6 | hard-zero forward migration으로 DRS 전용 schema contract 정리 | DRS 7개 table/non-generic lock row 존재 시 DDL 전 실패, empty baseline→head, generic lock·shared job/artifact 보존, FK/constraint/index와 downgrade 거부 검증 | destructive downgrade 금지; 별도 승인된 corrective forward migration만 허용 |
| 7 | 전체 검증, 독립 quality review와 current-state 문서 동기화 | `pnpm run verify`, `pnpm run verify:container`, `git diff --check`, boundary/contract/PostgreSQL tests | 검증 실패 시 release 중단; 구현보다 앞서 API/DB current 문서 갱신 금지 |

### Discovery gate 산출물

단계 1 종료 시 다음이 확인돼야 한다.

- 각 결과의 확인 범위(`local`, `production`, `external`), 상태(`confirmed`, `unknown`, `not_observable`), 근거 source와 관찰 시각. 확인하지 못한 상태를 `0`이나 consumer 없음으로 바꾸지 않음
- 저장소·배포 설정의 `PROXMOX_DRS_*` config/credential dependency와 consumer. secret 원문이나 secret-bearing payload는 기록하지 않음
- DRS table별 row 수, status 분포, 최초·최종 timestamp
- non-terminal `drs_migration_jobs`
- unresolved `drs_reconciliation_events`
- open `operation_locks` 중 `drs_migration`
- `job_runs`와 `job_artifacts`의 DRS historical row 및 참조 consumer
- DRS history의 보존 목적, 기간과 archive 형식
- 저장소 외부 API consumer 또는 관찰 불가 사실
- `/insights`의 `drs_advisor` source·`drs-rec-*` stable ID consumer와 exact alias/deprecation 결정
- `vm_identities`와 observations의 neutral Workloads 사용 여부
- exact deprecation 방식과 기간
- final data migration에서 drop, retain 또는 archive할 table/row manifest

이 산출물과 구현 전 stop condition을 사용자에게 보고하고 별도 구현 범위를 승인받기 전에는 단계 2 이후로 진행하지 않는다. 2026-08-24 첫 추가 승인은 단계 2~3의 repository-only frontend 전환에만 이 gate를 충족했다. 같은 날 사용자가 운영 배포·외부 consumer·보존할 production DRS state가 없다는 전제를 수락하고 full repository removal을 추가 승인해 단계 4~7의 code·config·schema migration 작성까지 진행할 수 있게 됐다. 확인하지 않은 production 상태를 `0`으로 기록하지 않으며, production 적용 전에는 별도 preflight와 승인이 필요하다.

실제 배포 환경이나 열린 실행 상태가 뒤늦게 발견되면 새 image를 배포하거나 migration을 적용하지 않는다. 기존 환경의 runtime·credential을 임의 제거하지 않고 exact state별 recovery Plan과 별도 승인을 받는다. `20260824_0029` hard-zero guard가 감지하는 범위는 DRS 전용 7개 table의 row와 non-generic `operation_locks` row뿐이다. 이 범위는 삭제하지 않고 startup migration을 실패시키지만, shared `job_runs` 상태·외부 consumer·배포 credential은 별도 read-only preflight로 확인해야 한다.

### Data-retirement gate

단계 6의 repository 작업은 사용자가 운영 배포와 보존할 production DRS data가 없다는 전제를 수락해 승인됐다. 따라서 적용된 revision은 보존하면서 DRS 전용 table과 shared `operation_locks`의 DRS 전용 column·constraint만 제거하는 새 forward migration을 작성한다. migration은 DRS 전용 7개 table 또는 non-generic lock row가 하나라도 있으면 DDL 전에 실패하며 어떠한 row도 자동 삭제·변환하지 않는다. empty baseline 및 generic lock·shared job/artifact 보존을 검증한다. 이 migration을 실제 production DB에 적용하거나 production row를 삭제하는 작업은 승인되지 않았다. 그런 환경이 뒤늦게 확인되면 exact migration manifest, production preflight 결과, archive/checksum, roll-forward correction과 적용 시점을 다시 제시하고 별도 승인받는다.

## 9. rollback과 roll-forward

- 단계 0~3: schema 변경이 없으므로 document, navigation, adapter 단위로 되돌릴 수 있다.
- 단계 4: data를 변경하지 않은 상태에서 승인된 Git 변경으로 compatibility facade를 복구할 수 있다. DRS live mutation은 자동 재활성화하지 않는다.
- 단계 5: 실제 배포 전에는 기존 배포를 그대로 유지한다. runtime 복구가 필요하면 제거된 credential이나 mutation을 자동 활성화하지 않고 별도 승인된 roll-forward correction을 사용한다.
- 단계 6: applied migration을 수정하거나 파괴적 downgrade하지 않는다. hard-zero 뒤 제거된 빈 contract가 다시 필요하면 새 correction migration으로 schema를 parent-first 재생성하며 runtime·credential은 자동 복구하지 않는다.
- 외부 Proxmox effect는 code rollback으로 보상하지 않는다. 이 Plan의 제거 검증에는 DRS live mutation을 사용하지 않는다.
- Proxmox token revoke 후 복원이 필요하면 기존 secret을 되살리지 않고 새 최소 권한 credential 발급을 별도 승인한다.

## 10. 중단 기준

다음 중 하나라도 해당하면 다음 단계로 진행하지 않는다.

- non-terminal DRS migration, unresolved reconciliation 또는 open DRS locator lock이 하나라도 남아 있음. 이 상태에서는 합의된 보존 여부와 관계없이 단계 5의 runtime·client·credential 제거를 시작하지 않음
- production row, retention 또는 external consumer를 확인하지 못했고 사용자도 그 불확실성을 수락하지 않음
- DRS 제거가 `operation_locks`, `job_runs`, `job_artifacts` 전체 제거를 요구함
- neutral Insights가 DRS policy/persistence/migration execution을 다시 필요로 함
- unknown/unavailable/stale state가 healthy 또는 executable로 축소됨
- Create/Start/Shutdown/Guided action의 lock, idempotency, RBAC, verification 또는 evidence regression 발생
- PostgreSQL migration과 forward correction을 검증할 환경이 없음
- migration이 applied revision 수정 또는 destructive downgrade를 요구함
- exact external credential을 확인하지 않고 revoke해야 함
- live Proxmox mutation이 제거 검증에 필요해짐
- focused/full regression 또는 independent quality review의 고위험 finding이 해결되지 않음

## 11. 남은 불확실성

- production DB가 실제로 존재하는지와 DRS/job/artifact row·open state·retention. 이번 repository 구현에서는 확인하지 않았고 migration도 적용하지 않음
- 외부 credential이 실제로 배포됐는지와 revoke 대상. 이번 구현에서는 확인·변경하지 않음
- shared Jobs/Artifacts에 남을 수 있는 historical DRS evidence의 장기 retention
- neutral Placement recommendation을 placement/topology health로 축소할 범위
- operational intelligence의 observation cadence, history와 alert integration 범위

이 항목은 임의로 추측하지 않는다. 실제 deployment가 생기거나 확인되면 별도 preflight와 승인으로 결정한다.

## 12. 승인 문장

`이 승인은 Gjallar의 제품 기준선을 Observe-first Operations Intelligence with Verified Actions로 전환하고, Create VM·VM Start·graceful VM Shutdown·Guided qm unlock과 공통 operation/evidence 기반을 유지하면서 DRS policy·approval·migration execution·reconciliation·전용 UI/API를 단계적으로 폐기하는 방향과 단계 1 read-only discovery만 수행하는 것을 의미한다. discovery 결과와 구현 전 stop condition을 보고하고 별도 범위 승인을 받기 전에는 단계 2 이후 code·config·frontend·API·runtime 변경을 시작하지 않는다. DRS 전용 table을 generic Operations·Policy·Evidence owner로 이전하거나 vm_identities·vm_identity_observations를 Workloads owner로 승격하는 것을 의미하지 않는다. DRS 전용 DB contract와 data retirement는 별도 gate 승인 후 새 forward migration으로만 정리한다. production row write·삭제·archive, operation_locks·job_runs·job_artifacts 제거, 일반 VM migration 재구현, 다른 hypervisor 지원, 자체 시계열·알림 플랫폼, automatic remediation, live Proxmox mutation 또는 외부 credential revoke 승인을 의미하지 않는다.`

사용자가 2026-08-24 위 범위로 Plan과 단계 1 read-only discovery를 승인했다. discovery 보고 뒤 다음 추가 범위를 승인했다.

`단계 2~3의 repository-only 전환으로 /insights의 drs_advisor·drs-rec-* compatibility를 유지하고 contract test를 보강하며, Workloads의 DRS navigation과 React runtime의 DRS 조회·policy·approval control/API 호출을 제거한다. /drs와 /instances/drs-policies는 authenticated non-mutating deprecation route로 유지한다. backend 13개 DRS route/runtime/reconciliation, shared frontend API client method, DB/data, operation_locks·job_runs·job_artifacts와 Jobs history, config/credential은 변경하지 않는다.`

이후 사용자는 Gjallar가 운영 중이 아니므로 DRS를 저장소에서 완전히 제거해도 된다는 전제를 제시했고 `그러면 진행`으로 다음 repository 범위를 추가 승인했다.

`active /api/v1/drs/* 13개 route, backend app.drs runtime과 DRS Proxmox client, PROXMOX_DRS_* 설정 의존, frontend DRS route·screen·shared API client, DRS 전용 ORM과 table contract를 제거한다. 적용된 Alembic revision은 보존하고 새 forward migration만 작성한다. operation_locks·job_runs·job_artifacts table과 non-DRS row, 일반 Verified Action, Jobs의 historical drs_migration renderer, /insights의 drs_advisor source와 drs-rec-* stable ID는 보존한다.`

이 추가 승인은 repository 구현과 빈/로컬 DB migration 검증만 허용한다. 확인되지 않은 production 상태를 `0`으로 바꾸거나 실제 production DB에 migration을 적용하는 것, production data 삭제·archive, 외부 Proxmox credential revoke와 live mutation은 계속 별도 승인을 요구한다.

## 13. 구현 결과와 검증

### Plan 대비 실제 구현

- 최초 승인 범위는 단계 1 discovery였고, 첫 추가 승인은 frontend-only deprecation까지였다. 사용자가 운영 배포·외부 consumer·보존할 production DRS state가 없다는 불확실성을 수락하고 full repository removal을 다시 승인한 뒤에만 backend·config·schema contract 제거로 확장했다.
- active frontend route·screen·API client, backend의 13개 route·`app.drs` runtime·migration client, `PROXMOX_DRS_*` 의존과 DRS ORM model을 제거했다.
- `/insights`의 `source=drs_advisor`, `drs-rec-*` stable ID와 Jobs의 historical `drs_migration` renderer는 opaque compatibility로 보존했다.
- applied migration `0019`~`0028`은 변경하지 않았다. 새 `20260824_0029`는 DRS 전용 7개 table과 shared `operation_locks`의 DRS 전용 column·constraint만 제거하고 `operation_locks`, `job_runs`, `job_artifacts` table과 generic/history row를 유지한다.
- migration은 DRS table row 또는 비-generic lock row가 있으면 DDL 전에 실패하고 자동 삭제·변환하지 않는다. PostgreSQL write-blocking lock과 SQLite `BEGIN IMMEDIATE`를 추가해 hard-zero 검사와 contract DDL 사이 race 및 부분 적용을 막았다.
- production DB, production data, 외부 credential과 live Proxmox는 조회·변경하지 않았다. local/external discovery에서 관찰할 수 없었던 값은 unknown으로 유지한다.

### 실행한 검증

| 검증 | 결과 |
|---|---|
| `PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests` | `406 passed, 5 skipped` |
| SQLite/Alembic focused schema·config test | `13 passed, 3 skipped` (`3 skipped`는 opt-in PostgreSQL test) |
| PostgreSQL 18.4 isolated schema migration test | `3 passed`; empty `0028→0029`, retained DRS row/lock hard-stop, generic lock·shared Jobs/Artifacts 보존 |
| frontend Node 24 contract tests | 15개 test file 통과 |
| frontend ESLint와 Vite production build | 통과 |
| `docker build --target backend-test -t gjallar-backend-test:local .` | Python 3.13 기준 `406 passed, 5 skipped` |
| `docker build -t gjallar:local .` | frontend test/lint/build와 production image 조립 통과 |
| active backend/frontend DRS reference 검색 | `app.drs`, `/api/v1/drs`, `PROXMOX_DRS_*`, DRS migration client 참조 0 |
| `git diff --check` | 통과 |
| 독립 quality review | Critical/High/Medium finding 0; 문서·docstring Low 2건 수정 완료 |

시스템 `pnpm`은 Corepack package-manager version 확인에서 완료되지 않아 `pnpm run verify`를 그대로 사용하지 못했다. 같은 package script의 backend pytest, frontend test·lint·build를 고정된 Node 24 runtime으로 각각 실행했고, Docker 기준 `pnpm` 단계도 성공했다.

### 남은 운영 경계

- `20260824_0029`를 production DB에 적용하지 않았다. 기존 DB나 deployment가 뒤늦게 확인되면 Runbook의 read-only hard-zero·shared job·external consumer·credential preflight와 별도 적용 승인이 필요하다.
- migration은 shared `job_runs`의 non-terminal 상태, 저장소 밖 consumer와 배포 credential을 감지하지 않는다. 이 항목은 migration 성공만으로 0이라고 판단하지 않는다.
- destructive downgrade, row 삭제·archive, Alembic force stamp, 외부 token revoke와 live Proxmox mutation은 수행하지 않았다.
