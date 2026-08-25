# ADR-006: DRS Maintenance 단계적 폐기와 Insights/Monitoring 통합

- 상태: `SUPERSEDED`
- 날짜: `2026-07-23`
- 결정자: `사용자`
- 상위 제품 방향: [`Project Specification`](../specifications/project-specification.md) FR-010
- 승인 문장: `이 승인은 Gjallar를 Verified Operations Control Plane으로 유지하면서 DRS policy·approval·execution·reconciliation 제품 기능을 단계적으로 제거하고 Placement/Capacity만 observe-only Insights/Monitoring으로 유지하는 방향을 의미하며, DRS Common Operation 통합·automatic recovery·기능 parity 재구현을 의미하지 않는다.`
- 대체하는 ADR: `ADR-005`
- 대체된 ADR: [`ADR-007`](adr-007-observe-first-operations-intelligence.md)
- 관련 Assessment: [`DRS·Jobs/Artifacts Legacy Convergence Assessment`](../architecture/drs-jobs-convergence-assessment.md)
- 관련 Plan: [`Verified Operations Control Plane 전환`](../plans/2026-07-20-verified-operations-control-plane-transition.md)

> 2026-08-24 제품 방향 갱신: DRS 단계적 폐기, consumer·retention 확인과 forward migration 원칙은 `ADR-007`이 계승한다. Verified Operations Control Plane을 제품 중심으로 유지하는 부분은 observe-first Operations Intelligence 방향으로 대체됐다. 아래 본문은 당시 결정의 역사로 보존한다.

## 배경

Gjallar의 제품 방향은 Proxmox native 기능과 경쟁하는 DRS 제품이 아니라, workload 중심의 verified operation과 observe-only Insights/Monitoring이다. Placement와 Capacity recommendation의 canonical 제품 surface는 이미 `/insights`이며, neutral placement 계산은 DRS identity, policy, lock과 migration client에 의존하지 않는다.

현재 구현에는 기존 `/drs`, `/api/v1/drs/*`, policy, approval, migration execution, reconciliation, DRS table과 Jobs/Artifacts 이력이 compatibility surface로 남아 있다. 이는 즉시 삭제로 인한 공개 계약·운영 이력 손실을 피하기 위한 현재 상태이지 목표 아키텍처가 아니다.

2026-07-23에 DRS execution을 Common Operation에 통합하는 선택지를 잘못 채택해 구현했으나, 사용자의 제품 방향과 반대임을 확인해 전부 롤백했다. 이 결정은 임시 compatibility 보존과 장기 제품 방향을 다시 혼동하지 않도록 경계를 고정한다.

## 결정 기준

- Gjallar의 차별점을 verified operations와 observe-only insight에 집중
- Placement/Capacity read model에서 실행 권한과 DRS persistence 제거
- DRS execution, recovery와 상태 projection에 신규 투자를 추가하지 않음
- 기존 공개 계약과 운영 이력은 consumer·retention 확인 전 보존
- DRS 제거와 Jobs/Artifacts 전환을 서로 다른 작업으로 취급
- contract/data 제거는 forward migration과 명시적 rollback 또는 correction 절차로 수행

## 검토한 선택지

### 1순위: DRS Maintenance 단계적 폐기

- neutral Placement와 Capacity는 Insights/Monitoring에 유지한다.
- DRS policy, approval, execution, reconciliation, history UI/API를 consumer 단위로 deprecate하고 제거한다.
- 장점: 제품 surface와 코드 책임이 실제 제품 방향에 수렴하며 DRS 전용 상태기계 유지 비용이 사라진다.
- 단점: 외부 consumer, 기존 이력, policy/history/reconciliation 표시의 대체 범위를 먼저 확인해야 한다.
- 전환 비용과 위험: 공개 API deprecation, frontend 전환, retention 결정과 마지막 forward DB migration이 필요하다.

### 대안 1: DRS Compatibility 장기 유지

- 현재 DRS API/UI/state를 격리한 채 계속 운영한다.
- 장점: 단기 회귀 위험이 낮다.
- 단점: 목표가 아닌 execution surface와 상태기계를 계속 유지해야 하고 제품 방향이 다시 모호해진다.

### 대안 2: DRS Execution을 Common Operation에 통합

- 기존 DRS 상태와 Common Operation을 dual record한 뒤 점진 전환한다.
- 장점: migration lifecycle을 공통 timeline에 표시할 수 있다.
- 단점: 제거 대상에 신규 projection, recovery와 정합성 비용을 추가한다.
- 제외 이유: 제품 방향과 반대이며 `ADR-005`와 관련 구현은 이미 거부·롤백됐다.

## 결정

- 선택: DRS Maintenance 단계적 폐기.
- neutral Placement와 Capacity recommendation의 canonical 제품 경계는 Insights/Monitoring이다.
- 기존 DRS policy, approval, execution, reconciliation, history UI/API와 전용 table은 제거 대상 compatibility surface다.
- DRS에는 신규 Common Operation 통합, automatic recovery handler, 신규 producer/consumer 또는 기능 확장을 추가하지 않는다.
- 제거 완료 전 보안·데이터 손실·중복 mutation을 막는 필수 안전 수정과 기존 계약 회귀 수정은 허용하지만, 이를 DRS 제품 확장 근거로 사용하지 않는다.
- 현재 DRS API/UI/data는 별도 high-risk 제거 Plan이 consumer, deprecation, history retention, forward migration과 검증을 승인할 때까지 유지한다.
- DRS 제거는 Jobs/Artifacts 전환과 분리한다. 공유 이력이 있다는 이유로 DRS execution을 Common Operation에 먼저 통합하지 않는다.
- 향후 일반 VM migration operation이 필요해지면 DRS의 연장으로 간주하지 않고 별도 제품 요구사항과 action-specific Plan으로 결정한다.

## 결정 이유

사용자가 승인한 제품 방향은 DRS를 유지·확장하는 것이 아니라 Placement/Capacity 정보를 실행 권한 없는 Insights/Monitoring으로 통합하는 것이다. 현재 compatibility surface를 안전하게 보존하는 전환 전술과 DRS를 장기 유지하는 제품 결정을 분리해야, 임시 상태가 다시 목표 구조로 오해되지 않는다.

## 결과와 영향

- 영향을 받는 모듈·도메인: `app.insights`, `app.drs`, DRS frontend route, Jobs/Artifacts consumer, Workloads/Operations/Policy/Evidence 경계.
- 공개 계약: 이번 ADR만으로 route를 삭제하지 않는다. 후속 Plan에서 deprecation과 consumer 전환을 먼저 수행한다.
- 데이터·트랜잭션: 이번 ADR만으로 schema, row, lock 또는 이력을 변경하지 않는다.
- 테스트: neutral Insights가 `app.drs`와 DB write에 의존하지 않는 경계, DRS Common Operation/recovery가 추가되지 않는 경계, 기존 계약의 제거 단계별 regression을 검증한다.
- 마이그레이션: 마지막 contract/data 단계에서만 승인된 forward Alembic migration을 사용한다.
- 문서: Specification, Architecture, 상위 전환 Plan, Project Profile과 DRS convergence assessment가 이 결정을 기준으로 한다.

## 감수한 단점

- 실제 제거가 끝날 때까지 현재 DRS compatibility 코드와 table 유지 비용이 남는다.
- 기존 DRS policy/history/reconciliation 중 Insights/Monitoring이 보존할 정보 범위를 별도로 설계해야 한다.
- 외부 API consumer와 production row/retention을 확인하기 전에는 route와 data를 즉시 삭제할 수 없다.

## 검증 방법

- `/insights` placement 계산은 `app.drs`, DRS identity/policy/lock 저장소와 migration client를 import하거나 호출하지 않는다.
- 신규 변경에서 DRS Common Operation, automatic recovery handler, 신규 DRS producer/consumer가 추가되지 않았는지 경계 테스트와 diff로 확인한다.
- DRS 제거 단계마다 저장소 내부 consumer가 0이거나 승인된 replacement를 사용한다.
- 공개 API deprecation, history retention과 DB forward migration을 PostgreSQL integration 및 frontend/backend contract로 검증한다.
- live Proxmox mutation은 DRS 제거 검증에 사용하지 않는다.

## 재검토 조건

- 사용자가 DRS 제품을 다시 명시적으로 요구하고 제품 범위·운영 가치·실행 권한을 새로 승인할 때
- 독립적인 일반 VM migration operation이 필요해 별도 action 요구사항을 검토할 때
- 외부 consumer 또는 법적·감사 retention이 특정 DRS read contract의 장기 보존을 요구할 때
