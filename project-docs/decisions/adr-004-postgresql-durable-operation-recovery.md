# ADR-004: PostgreSQL Durable Target Lock과 In-process Recovery Runner

- 상태: `ACCEPTED`
- 날짜: `2026-07-21`
- 결정자: `사용자`
- 대체하는 ADR: `없음`
- 대체된 ADR: `없음`
- 관련 Plan: [`단계 10-A Durable Operation Recovery Foundation`](../plans/2026-07-21-durable-operation-recovery-foundation.md), [`단계 10-B Graceful VM Shutdown`](../plans/2026-07-21-graceful-vm-shutdown-and-recovery-rollout.md)

## 배경

VM Start, Create VM, Guided `qm unlock`은 한 container의 temporary file lock을 공유하고 요청 중 task polling을 수행한다. 이 구조는 process/container restart 뒤 retained lock을 잃을 수 있고 여러 replica가 같은 VM을 동시에 변경하는 것을 막지 못한다. DRS는 PostgreSQL `operation_locks`를 사용하지만 operation type별 unique scope라 다른 workflow와 같은 VM을 공통 직렬화하지 않는다.

Gjallar는 dispatch ambiguity를 mutation retry가 아닌 reconciliation으로 보존해야 한다. 따라서 restart recovery는 이미 dispatch된 operation의 task와 after-state를 다시 관찰해야 하며, lease expiry나 process death만으로 side effect 없음·성공·실패·lock release를 판단하면 안 된다.

## 결정 기준

- same target/different operation type의 second mutation을 DB constraint로 차단
- process restart와 multi-replica에서 하나의 observer만 recovery 수행
- stale worker write와 lock release를 fencing
- Proxmox actual-state authority와 no-auto-retry invariant 유지
- 현재 single-image modular monolith와 PostgreSQL 재사용
- 외부 queue/scheduler와 새 운영 dependency를 선행 도입하지 않음
- action별 작은 수직 전환과 feature disable 가능성

## 검토한 선택지

### 1순위: FastAPI image 내부의 in-process runner + PostgreSQL coordination

- 기존 `operation_locks`를 cross-operation durable locator lock으로 확장한다.
- `operation_recovery_items`가 due work, time-bounded lease, generation/token fencing과 redacted result를 소유한다.
- FastAPI lifespan에서 opt-in runner를 시작하고 초기 concurrency를 1로 제한한다.
- action handler는 allowlist이며 첫 handler는 VM Start의 stored task/direct state GET만 수행한다.
- 장점: 배포 단위와 dependency를 유지하면서 restart/multi-replica coordination을 검증할 수 있다.
- 단점: API process와 recovery resource를 공유하고, 처리량이 늘면 별도 worker 분리가 필요하다.

### 대안 1: 같은 image의 별도 worker process

- API와 recovery process를 분리하고 PostgreSQL lease를 공유한다.
- 장점: resource와 lifecycle 격리가 쉽다.
- 단점: 현재 확인되지 않은 deployment supervision, health, scale contract가 즉시 늘어난다.

### 대안 2: 외부 queue/scheduler worker

- queue delivery와 scheduler를 recovery trigger로 사용한다.
- 장점: 높은 처리량과 독립 scale에 유리하다.
- 단점: 새 운영 dependency와 distributed delivery semantics가 추가되고 현재 규모와 ADR-002의 점진 전환 원칙보다 크다.

## 결정

- 1순위를 선택한다.
- PostgreSQL target lock과 recovery lease는 서로 다른 의미를 가진다.
  - target lock은 충돌 mutation을 차단하며 ambiguity에서 자동 만료·해제하지 않는다.
  - recovery lease는 한 observer의 제한된 처리 권한이며 만료되면 다른 observer가 claim할 수 있다.
- lease generation/token을 fencing identity로 사용하고, recovery transition/event append/target lock release는 유효 lease 확인과 같은 transaction에서 commit한다.
- runner는 allowlisted read-only recovery port만 사용한다. Proxmox mutation POST, silent manual fallback, inverse action을 수행하지 않는다.
- first handler는 stored UPID가 있는 VM Start task와 direct VM state를 재관찰한다. UPID가 없거나 task/state가 불명확하면 `needs_reconciliation`과 target lock을 유지한다.
- 기존 file lock은 전환 중 compatibility guard로 dual acquire한다. durable PostgreSQL lock을 먼저 획득한다.
- runner는 `GJALLAR_OPERATION_RECOVERY_ENABLED=false` 기본값의 opt-in runtime으로 시작한다. 초기 concurrency는 1이다.
- schema와 code를 배포하고 PostgreSQL concurrency/restart 검증을 통과한 뒤에만 enable한다.
- `shutdown`/`reboot` 등 새 mutation action은 이 기반과 별도 action-specific Plan 승인을 요구한다.

## 결정 이유

현재 제품은 single image와 PostgreSQL을 이미 운영하며 operation projection/event도 DB에 저장한다. 같은 DB에서 target lock과 fenced recovery claim을 관리하면 추가 서비스 없이 restart safety와 multi-replica coordination을 만들 수 있다. recovery port에서 mutation capability를 제거하면 worker 도입이 기존 no-auto-retry 권한 경계를 넓히지 않는다.

## 결과와 영향

- Operations가 durable target lock, recovery item, lease/fencing과 handler allowlist를 소유한다.
- DRS와 VM Start/Create/Guided는 같은 cluster/VMID locator unique constraint를 공유한다.
- FastAPI application lifecycle에 optional background component가 추가되지만 deployment image와 외부 dependency는 유지된다.
- VM Start foreground는 dispatch 전에 recovery item/lease를 준비하고 task poll 중 lease를 heartbeat한다.
- Operation detail은 token을 제외한 recovery/target lock read model을 additive하게 제공한다.
- recovery runner가 disabled여도 durable state는 보존되고 existing synchronous mutation API는 유지된다.

## 감수한 단점

- API와 recovery가 같은 process resource를 사용한다.
- 초기 구현은 VM Start만 자동 observation recovery를 지원하며 Create VM/Guided/DRS는 기존 명시적 recovery 의미를 유지한다.
- file lock과 DB lock이 전환 기간 공존한다.
- actual PostgreSQL concurrency와 deployment restart 검증이 필수이고 SQLite test만으로 enable할 수 없다.
- code rollback 전에 open durable lock과 recovery item을 audit하고 mutation을 drain해야 한다.

## 검증 방법

- operation type이 달라도 같은 cluster/VM locator open lock은 DB constraint로 하나만 허용한다.
- 두 runner가 같은 due item을 claim하면 하나만 lease를 얻는다.
- lease를 잃은 worker는 event/transition/lock release를 commit하지 못한다.
- crash 후 새 runner는 stored UPID를 GET으로 관찰하며 VM Start POST를 다시 호출하지 않는다.
- lease expiry만으로 target lock이나 terminal status가 바뀌지 않는다.
- runner disabled/non-live/unsupported handler가 fail-closed한다.
- PostgreSQL partial unique, `SKIP LOCKED`, fencing과 restart/failover test를 통과해야 enable할 수 있다.

## 재검토 조건

- recovery 처리량이나 API latency가 in-process bounded runner로 감당되지 않을 때
- API와 recovery의 독립 availability, scale, release cadence가 실제로 필요할 때
- multi-cluster connection profile과 cluster별 worker partition이 도입될 때
- external queue가 필요한 다른 durable workload가 승인돼 운영 비용을 공유할 수 있을 때
- action handler가 read-only recovery 경계를 넘어 privileged execution을 요구할 때

## 후속 구현 기록

2026-07-21 승인된 10-B Plan으로 두 번째 allowlisted handler인 `vm_shutdown_observation`을 추가했다. 이 확장은 ADR의 GET-only recovery 권한 경계를 유지한다. foreground만 QEMU graceful shutdown POST를 수행하고 recovery handler는 stored UPID task와 direct VM status GET만 받으며 hard stop, reboot, shutdown 재제출 capability를 갖지 않는다. migration `20260721_0028`은 기존 locator constraint에 `vm_shutdown` type만 추가했고 새 table이나 외부 dependency는 만들지 않았다.
