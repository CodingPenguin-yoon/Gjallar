# ADR-007: Observe-first Operations Intelligence와 선택적 Verified Action

- 상태: `ACCEPTED`
- 날짜: `2026-08-24`
- 결정자: `사용자`
- 상위 제품 방향: [`Project Specification`](../specifications/project-specification.md)
- 승인 문장: `이 승인은 Gjallar의 제품 중심을 Proxmox observe-first Operations Intelligence로 전환하고 Create VM·VM Start·graceful VM Shutdown·Guided qm unlock만 선택적 verified action으로 유지하며 DRS policy·approval·execution·reconciliation과 automatic migration을 안전하게 폐기하는 방향을 의미한다. Proxmox actual state의 영구 mirror, 범용 metric TSDB·독립 alerting platform, automatic remediation, arbitrary shell, multi-provider 지원 또는 consumer·retention 확인 전 DRS API·UI·data의 즉시 삭제를 의미하지 않는다.`
- 대체하는 ADR: [`ADR-001`](adr-001-proxmox-gjallar-authority-boundary.md), [`ADR-006`](adr-006-drs-deprecation-and-insights-convergence.md)
- 대체된 ADR: `없음`
- 유지하는 ADR: [`ADR-002`](adr-002-modular-monolith-domain-boundaries.md), [`ADR-003`](adr-003-production-inventory-connection-truth.md), [`ADR-004`](adr-004-postgresql-durable-operation-recovery.md)
- 관련 Plan: [`Observe-first Operations Intelligence 전환`](../plans/2026-08-24-observe-first-operations-intelligence-transition.md) (`APPROVED`)

## 배경

Gjallar는 Proxmox actual state를 존중하면서 Create VM, VM Start, graceful VM Shutdown, Guided `qm unlock`, 공통 Operation evidence와 observe-only Insights를 구현했다. 동시에 DRS policy, approval, migration execution과 reconciliation은 별도 상태기계, 권한, route와 table을 요구하며 제품의 이식성과 운영 초점을 흐린다.

기존 `ADR-001`은 verified operation을 제품 중심에 두고 day-2 운영의 기본 진입점을 Gjallar로 옮기는 방향을 선택했다. `ADR-006`은 DRS maintenance 폐기를 승인했지만 Gjallar를 계속 Verified Operations Control Plane으로 정의했다. 사용자는 DRS와 automatic migration을 제거하고, 상태·변화·운영 맥락의 관찰과 설명을 제품의 첫 번째 책임으로 두되 현재 검증된 변경 작업은 안전한 보조 capability로 유지하는 방향을 승인했다.

현재 Insights는 요청 시점의 Workloads observation과 stored job risk를 조합하는 read model이다. durable metric sample, 일반 시계열 보존, alert lifecycle이나 notification delivery를 소유하지 않는다. 이 ADR은 현재 snapshot 기능을 완성된 monitoring platform으로 선언하지 않고, 제품 우선순위와 향후 구조 경계를 결정한다.

## 결정 기준

- DRS 전용 정책·권한·상태기계와 live migration failure surface 제거
- Proxmox actual-state authority와 `unknown`·`unavailable`·freshness의 보수적 의미 유지
- 관찰, 설명, 검증된 개입 순서가 사용자 경험과 도메인 의존성에 반영될 것
- 이미 구현한 Operation safety와 evidence 투자를 버리지 않을 것
- 다른 Proxmox 환경에 배포할 때 node·profile 하드코딩과 장기 DRS state 의존을 줄일 것
- generic monitoring 제품이나 Proxmox GUI parity 경쟁으로 범위를 확장하지 않을 것
- 공개 계약, 운영 이력과 applied migration을 단계적으로 보호할 것

## 검토한 선택지

### 1순위: Observe-first Operations Intelligence + 선택적 Verified Action

- 연결, inventory/topology, freshness, readiness, capacity, placement health, risk와 operation evidence를 primary product surface로 둔다.
- Create VM, VM Start, graceful VM Shutdown과 Guided `qm unlock`은 명시적으로 지원하는 verified action capability로 유지한다.
- DRS와 automatic migration은 제거한다.
- 장점: 권한과 실패 표면을 줄이면서 관찰과 안전한 개입의 연결이라는 기존 차별점을 유지한다.
- 단점: read model을 운영 intelligence로 강화하려면 observation history, 외부 metric 연동과 finding lifecycle의 범위를 후속 단계에서 결정해야 한다.

### 대안 1: Pure read-only Monitoring

- 모든 Proxmox mutation capability를 제거하고 조회·분석만 제공한다.
- 장점: credential 권한, recovery와 concurrency 책임이 가장 작다.
- 단점: 이미 구현한 verified action/evidence 자산을 버리고 범용 monitoring 도구와 직접 경쟁하게 된다.
- 제외 이유: 사용자는 현재 Create·Start·Shutdown·Guided 작업을 유효한 기능으로 판단했다.

### 대안 2: Verified Operations Control Plane 유지

- observation은 operation을 보조하고 day-2 mutation을 계속 제품 중심으로 확장한다.
- 장점: 기존 명세와 완료된 전환 단계를 가장 적게 바꾼다.
- 단점: 새로운 mutation·policy·recovery 범위가 다시 증가하고 DRS 제거로 얻으려는 단순성과 이식성이 약해진다.
- 제외 이유: 사용자가 승인한 관찰 우선 운영 방향과 맞지 않는다.

## 결정

### 제품 책임 순서

1. **관찰**: Proxmox 연결 상태와 workload/node/storage/network observation을 source·observed time·freshness와 함께 제공한다.
2. **설명**: readiness, capacity, placement health, risk와 operation evidence를 근거가 있는 finding으로 연결한다.
3. **개입**: 사용자가 명시적으로 시작한 allowlisted verified action만 action별 pre-check·권한·gate, lock, external completion evidence와 after-state 검증을 거쳐 수행한다. managed API에서 task를 발급한 action은 terminal task를, guided manual action은 operator attestation을 상관 연결한다.

### 권한과 데이터 소유권

- Proxmox는 VM, node, task, config, power, location, storage와 network actual state 및 low-level execution의 권위자다.
- Gjallar는 connection/source reference, observation provenance와 freshness, derived finding, operation intent, approval, verification, evidence와 audit를 소유한다.
- Gjallar는 Proxmox actual state 전체를 자체 truth로 영구 mirror하지 않는다. durable observation/history가 필요하면 source, retention, stale 의미와 삭제 정책을 별도 Plan으로 승인한다.
- `observe_only` insight에는 approval이나 mutation dispatch capability를 제공하지 않는다.

### 선택적 Verified Action

- 유지하는 action은 Create VM, VM Start, graceful VM Shutdown과 Guided `qm unlock`이다.
- 이 action은 primary product identity가 아니라 명시적으로 지원되는 secondary capability다.
- `managed_api`, `guided_manual`, `observe_only` mode와 현재 action별 안전 계약은 유지한다.
- API failure 후 manual mode로 silent fallback하지 않고, dispatch ambiguity에서 mutation을 자동 재시도하지 않는다.
- arbitrary shell/SSH executor, raw embedded terminal, hard-stop fallback과 automatic remediation은 도입하지 않는다.
- 새 mutation 또는 일반 VM migration은 DRS의 연장으로 해석하지 않고 별도 제품 요구사항과 action-specific Plan 승인을 요구한다.

### DRS와 Placement

- DRS policy, approval, execution, reconciliation, maintenance UI/API와 전용 persistence는 제거 대상 compatibility surface다.
- 신규 DRS producer, Common Operation integration, automatic recovery 또는 기능 parity를 추가하지 않는다.
- DRS 제거 전 external/internal consumer, open migration/lock, evidence와 history retention을 확인한다. 공유 `operation_locks`, `job_runs`, `job_artifacts`는 DRS와 함께 삭제하지 않는다.
- 현재 neutral Placement/Capacity read model은 transition 동안 Insights에 유지한다. target-node recommendation을 placement health finding으로 축소할지는 구현 Plan의 별도 decision gate에서 정한다.

### Monitoring과 이식성 경계

- 초기 Operations Intelligence 범위는 connection truth, current inventory/topology, freshness, readiness, capacity, placement health, risk와 operation evidence correlation이다.
- 범용 metric 수집·시계열 TSDB, 독립 alert delivery와 SLO platform은 이 결정의 범위가 아니다. 필요하면 기존 monitoring source 연동을 우선 검토한다.
- 초기 지원 provider는 Proxmox다. multi-provider 제품화를 약속하지 않는다.
- 목표 core contract는 provider-specific node path, VMID와 UPID를 observation/mutation adapter 뒤에 격리하고 source-scoped resource identity와 capability를 사용한다. 정확한 공개계약 변경과 migration은 별도 승인한다.
- 다른 Proxmox cluster로의 배포를 방해하는 node/profile 하드코딩은 configuration 또는 discovery 경계로 이동한다.

## 결정 이유

이 선택은 DRS의 privileged migration 상태기계를 제거해 운영 부담과 장애 표면을 줄이면서, Gjallar가 이미 구현한 freshness-aware observation, conservative failure semantics, Operation evidence와 검증된 action을 함께 살린다. 관찰만 제공하는 dashboard도, 모든 day-2 작업을 흡수하는 control plane도 아닌 범위를 선택해 프로젝트가 가장 잘 설명할 수 있는 문제에 집중한다.

## 결과와 영향

- 제품 명세와 navigation의 중심은 Operations보다 Insights/Operations Intelligence가 된다.
- Operations는 유지되는 action의 side-effect와 evidence 경계이며 모든 read flow의 중앙 조정자가 아니다.
- Workloads/Setup Integration이 normalized current observation을 제공하고 Insights가 mutation 권한 없이 finding을 계산한다.
- DRS route, UI와 table은 후속 승인된 high-risk Plan이 단계적으로 제거한다. 이 ADR만으로 공개 계약이나 DB를 삭제하지 않는다.
- 기존 `ADR-004` durable lock/recovery는 유지되는 VM Start/Shutdown action에 계속 적용된다.
- 기존 `/api/v1`, DB schema와 현재 UI는 구현 단계별 deprecation 전까지 호환 상태로 남는다.

## 감수한 단점

- DRS 코드와 데이터는 제거 Plan이 승인·완료될 때까지 일시적으로 남는다.
- 완전한 metric history와 alert delivery를 제공하지 않으므로 외부 monitoring 시스템과의 역할 경계를 설명해야 한다.
- Proxmox-specific API를 adapter 뒤로 이동하는 동안 old/new target contract가 공존할 수 있다.
- 지원하지 않는 변경 작업은 계속 Proxmox UI/CLI 또는 별도 승인된 flow를 요구한다.

## 검증 방법

- 제품 명세, Project Profile, Domain Map과 ADR index가 observe-first 우선순위와 action allowlist를 동일하게 표현한다.
- `/insights`와 후속 read model은 DRS persistence나 mutation/approval port에 의존하지 않는다.
- 유지되는 action은 trusted actor, fresh pre-check, idempotency와 target lock을 공통으로 검증한다. task를 발급한 action은 terminal task, guided manual action은 authenticated operator attestation을 상관 연결하고, 모든 action은 required direct after-state와 evidence 없이는 성공하지 않는다.
- DRS 제거 단계마다 내부 consumer 0 또는 승인된 replacement, external consumer, open state와 retention을 확인한다.
- 적용된 Alembic migration을 수정·삭제하지 않고 마지막 contract/data 단계에서 새 forward migration을 검증한다.
- current Architecture/API/DB 문서는 실제 코드가 바뀐 단계에만 갱신한다.

## 재검토 조건

- 사용자가 pure read-only 제품으로 전환하거나 유지되는 verified action을 제거하려 할 때
- 일반 VM migration, automatic remediation 또는 새로운 mutation action의 운영 가치가 확인될 때
- metric retention, alert delivery 또는 SLO를 Gjallar가 직접 소유해야 할 구체적인 요구가 생길 때
- multi-cluster 또는 non-Proxmox provider가 실제 제품 요구가 될 때
- external consumer나 감사 retention 때문에 특정 DRS read contract를 장기 유지해야 할 때

## 대체 범위

- `ADR-001`의 Proxmox actual-state authority, mode 분리, no-silent-fallback과 arbitrary shell 금지 원칙은 계승한다. day-2 mutation을 제품 중심으로 두는 우선순위는 이 ADR이 대체한다.
- `ADR-006`의 DRS 단계적 폐기, consumer·retention 확인과 forward migration 원칙은 계승한다. Verified Operations Control Plane을 상위 제품 정체성으로 유지하는 부분과 Placement/Capacity만으로 monitoring 범위를 제한한 부분은 이 ADR이 대체한다.
