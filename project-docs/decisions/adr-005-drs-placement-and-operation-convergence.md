# ADR-005: DRS Placement 경계와 Common Operation 점진 통합

- 상태: `REJECTED`
- 날짜: `2026-07-23`
- 결정자: `사용자`
- 대체하는 ADR: `없음`
- 대체된 ADR: `ADR-006`
- 관련 ADR: [`ADR-002`](adr-002-modular-monolith-domain-boundaries.md), [`ADR-004`](adr-004-postgresql-durable-operation-recovery.md)
- 관련 Plan: [`DRS Placement·Common Operation 전환`](../plans/2026-07-23-drs-placement-and-common-operation-convergence.md)

> 2026-07-23 정정: 아래 선택지 A는 DRS를 유지·통합하는 방향으로 잘못 이해해 기록한 결정이다. 사용자는 DRS 기능을 제거하고 제품 read surface를 Insights/Monitoring으로 통합하려는 방향임을 명확히 했으며, 이에 따라 Common Operation 통합 구현은 롤백했다. neutral Placement 경계만 유지하고 DRS 제거의 구체 범위는 후속 Plan에서 확정한다.

후속 결정은 [`ADR-006`](adr-006-drs-deprecation-and-insights-convergence.md)에 기록한다.

## 배경

DRS recommendation의 canonical 제품 화면은 이미 Insights이지만 계산 구현은 `app.drs.advisor`에 남아 있다. 이 advisor는 placement 점수뿐 아니라 DRS identity observation 저장, policy와 operation lock 조회, final pre-check까지 함께 수행한다. 따라서 observe-only `/insights`가 DRS 실행 package에 의존하고 조회 중 identity observation을 기록할 수 있다.

DRS migration은 exact approval, durable prepared attempt, UPID/task, post-check, reconciliation을 전용 table과 상태기계에 기록한다. 같은 VMID의 locator lock은 Common Operation과 공유하지만 operation projection/event는 아직 기록하지 않는다. 반면 DRS maintenance API/UI와 policy/history는 현재 사용자와 Jobs/Artifacts consumer가 사용하므로 즉시 제거할 수 없다.

## 검토한 선택지

### A. Placement 경계 분리와 DRS execution의 점진 통합

- 순수 placement 계산을 neutral Insights/placement 경계가 소유한다.
- DRS advisor는 이 계산을 재사용하고 identity, policy, lock, approval/execution evidence를 덧붙이는 compatibility adapter가 된다.
- DRS migration은 기존 상태를 유지하면서 같은 ID의 Common Operation과 event를 additive하게 기록한다.
- DRS maintenance API/UI와 table, Jobs/Artifacts 계약은 replacement parity와 별도 폐기 승인 전 유지한다.

### B. 현재 compatibility 구조 장기 유지

- 격리된 DRS와 Jobs 구조를 유지하고 추가 전환하지 않는다.
- 단기 변경 위험은 작지만 observe-only 조회와 DRS 실행 책임이 계속 결합되고 두 execution projection의 유지 비용이 남는다.

### C. DRS maintenance 단계적 폐기

- Insights placement만 남기고 DRS policy, approval, execution, reconciliation과 history를 제거한다.
- 현재 대체 계약과 외부 소비자·retention 근거가 없어 기능과 이력을 조기에 잃을 위험이 있다.

## 당시 결정 — 철회됨

- 선택지 A를 채택한다.
- placement recommendation의 중립 계산과 canonical 제품 read boundary는 Insights가 소유한다.
- DRS는 중립 placement 결과에 stable identity, policy, lock, exact approval, execution/reconciliation을 결합하는 maintenance compatibility 영역으로 유지한다.
- DRS migration의 초기 canonical execution state는 DRS table로 유지하고 Common Operation은 같은 `job_id`를 `operation_id`로 쓰는 additive projection/evidence로 도입한다.
- 신규 DRS migration은 Common Operation 없이 외부 mutation을 시작하지 않는다. prepared/no-UPID 상황에서는 mutation을 자동 재호출하지 않는다.
- Jobs/Artifacts에는 신규 책임을 추가하지 않는다. 기존 producer/consumer는 대체 계약이 생긴 순서대로 별도 Plan에서 전환한다.
- DRS와 Jobs/Artifacts의 API, UI, table, 기존 row를 삭제하거나 일괄 backfill하지 않는다.
- DRS용 자동 recovery runner는 이번 결정에 포함하지 않는다. 현재 operator reconciliation과 read-only 확인 경계를 유지한다.

## 결정 이유

이 방향은 제품의 placement read model과 privileged migration 실행을 분리하면서 현재 maintenance 기능과 이력을 보존한다. expand-first dual record로 Common Operation의 상태·evidence parity를 검증할 수 있고, 계약 삭제와 데이터 이동은 실제 consumer와 운영 row를 확인한 뒤 별도로 결정할 수 있다.

## 구현 결과와 철회 영향

- `/insights`는 DRS identity/policy/lock 저장소나 migration client에 의존하지 않는 read-only 계산 경계를 갖게 된다.
- DRS advisor는 독립 계산의 소유자가 아니라 maintenance evidence를 결합하는 adapter가 된다.
- neutral Placement 경계는 구현되어 `/insights`의 DRS persistence 의존을 제거했다.
- DRS Common Operation tracker, approval/execute/reconcile dual record, additive operation link와 lock owner 변경은 모두 롤백했다.
- 현재 DRS migration은 기존 전용 state와 operator reconciliation 계약만 사용한다.
- 기존 공개 API와 DB schema는 이 결정만으로 바뀌지 않는다.

## 감수한 단점

- 전환 기간 두 상태 projection을 함께 유지하고 정합성 실패를 처리해야 한다.
- 기존 DRS identity/policy/history와 Jobs/Artifacts 의존은 즉시 사라지지 않는다.
- 과거 DRS job은 Common Operation이 없을 수 있어 조회·실행 진입 시 lazy repair가 필요할 수 있다.
- automatic recovery를 추가하지 않으므로 일부 모호한 상태는 operator reconciliation으로 남는다.

## 철회 후 검증 방법

- `/insights` placement 계산이 `app.drs`를 import하거나 DB write를 수행하지 않는 경계 계약을 둔다.
- 기존 13개 DRS route, request/response, RBAC, exact approval과 execution/reconciliation 계약을 유지한다.
- DRS approval/execute/reconcile 응답에 Common Operation link가 추가되지 않았는지 확인한다.
- `backend/app/operations/drs_migration/`과 관련 failure-injection test가 남지 않았는지 확인한다.
- 기존 DRS execution/reconciliation 회귀 테스트와 `/api/v1` route/RBAC 계약을 확인한다.
- 전체 backend와 frontend 계약을 실행하며 live Proxmox mutation은 별도 승인 없이는 수행하지 않는다.

## 후속 결정 조건

- DRS maintenance 사용자가 없어지고 policy/history/reconciliation 대체 계약이 완성됐을 때
- DRS maintenance API/UI, policy, approval, execution, reconciliation 중 무엇을 제거하고 무엇을 Insights/Monitoring으로 옮길지 확정할 때
- 저장소 내부·외부 DRS consumer와 보존해야 할 이력의 범위를 확인했을 때
- production DRS/job/artifact row 수, retention과 외부 API 소비자가 확인됐을 때
- DRS table과 Jobs/Artifacts의 contract/data migration을 제안할 때
