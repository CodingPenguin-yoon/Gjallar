# ADR-002: Domain-oriented Modular Monolith와 Vertical Slice 전환

- 상태: `ACCEPTED`
- 날짜: `2026-07-20`
- 결정자: `사용자`
- 대체하는 ADR: `없음`
- 대체된 ADR: `없음`

## 배경

현재 Gjallar는 single FastAPI/React deployment 안에서 feature package를 사용하지만 HTTP, DB, Proxmox, jobs/evidence 책임이 workflow별로 결합돼 있다. 제품 중심을 DRS에서 verified operations로 바꾸려면 모든 코드를 일괄 재작성하기보다 operation slice 하나씩 public contract와 safety invariant를 보존하며 경계를 이동해야 한다.

## 결정 기준

- Proxmox mutation과 evidence regression 위험 최소화
- 기존 `/api/v1`, DB migration history, test asset 재사용
- logical data ownership과 dependency direction 명확화
- 기능별 독립 테스트와 rollback 가능성
- 현재 단일 배포·소규모 운영 복잡도 유지

## 검토한 선택지

### 1순위: Domain-oriented Modular Monolith + Vertical Slice + selective Ports/Adapters

- 구조: Workloads, Operations, Policy/Approval, Evidence/Audit, Insights를 logical module로 두고 `interface → application → domain` 방향을 사용한다. infrastructure adapter는 composition root에서 연결한다.
- 전환: 기존 public endpoint를 facade로 유지하고 한 operation slice씩 내부 use case로 위임한다.
- 장점: 현재 deployment와 test를 재사용하면서 data ownership과 side-effect boundary를 선명하게 만든다.
- 단점: 전환 중 old/new structure가 공존하고 compatibility layer 제거 기준이 필요하다.
- 전환 위험: 과도한 abstraction, transaction semantics 변화, test patch target 파손.

### 대안 1: Router와 service 파일만 분할

- 구조: 큰 파일을 작은 service로 옮기되 data ownership과 dependency rule은 두지 않는다.
- 적합한 경우: 단기 가독성 개선만 필요할 때.
- 장점: 낮은 초기 비용.
- 단점: jobs/evidence/Proxmox 결합과 operation inconsistency가 남는다.
- 추천안보다 낮은 이유: 제품 핵심 경계가 코드 구조에 반영되지 않는다.

### 대안 2: 전면 Clean/Hexagonal rewrite 또는 Microservice

- 구조: 모든 기능을 새 layer/service로 일괄 이동한다.
- 적합한 경우: 독립 scale·release·team ownership 요구가 이미 확정됐을 때.
- 장점: 강한 물리 경계 가능.
- 단점: 현재보다 큰 migration, distributed consistency와 운영 비용.
- 추천안보다 낮은 이유: 단일 제품·배포 단계에서 위험과 비용이 이익보다 크다.

## 결정

- 선택: Domain-oriented Modular Monolith를 유지하고 vertical slice로 점진 전환한다.
- backend dependency: `interface(api) → application(use case) → domain`; infrastructure는 port를 구현하고 composition root에서 주입한다.
- frontend dependency: `app → pages/features → entities/shared`; feature가 다른 feature private module을 직접 import하지 않는다.
- conceptual data ownership을 먼저 정하고 물리 table 이동은 별도 migration 승인 전 수행하지 않는다.
- generic repository, event bus, queue, microservice를 선행 도입하지 않는다.
- 첫 architecture pilot은 기존 VM Start behavior를 operation lifecycle로 감싸는 slice로 한다.

## 결정 이유

현재 코드와 test asset을 보존하면서도 제품 핵심인 operation/policy/evidence를 공통 언어로 만들 수 있다. VM Start는 실제 mutation, idempotency, lock, task poll, post-check가 이미 있어 architecture pattern과 safety gap을 검증하기에 가장 작은 완결된 pilot이다.

## 결과와 영향

- module: target domain과 support 영역에 public application contract가 생긴다.
- API: existing endpoint는 facade, 신규 operation API는 additive contract다.
- DB: initial slice는 기존 table을 사용한다. 새 schema나 data migration은 별도 승인 후 forward migration으로만 추가한다.
- transaction: application use case가 local transaction과 external call의 순서를 명시한다.
- test: domain unit, application fake-port, HTTP contract, adapter integration, end-to-end flow 경계를 구분한다.
- migration: characterization → pilot → review → next slice 순서를 지킨다.

## 감수한 단점

- 일정 기간 두 구조와 naming이 공존한다.
- logical ownership과 physical ORM location이 즉시 일치하지 않는다.
- facade와 adapter code가 일시적으로 늘어난다.

## 검증 방법

- migrated HTTP handler가 transport, auth dependency, error mapping에 집중한다.
- application use case는 concrete FastAPI/SQLAlchemy/Proxmox client가 아닌 명시적 contract를 사용한다.
- target·idempotency·dispatch ambiguity·post-check invariant가 fake-port test로 검증된다.
- 기존 endpoint와 frontend behavior contract가 유지된다.
- slice별 full regression과 independent architecture review를 통과한다.

## 재검토 조건

- 특정 domain이 독립 scale, release cadence, availability 또는 team ownership을 실제로 요구할 때
- single database가 compliance/security isolation 요구를 만족하지 못할 때
- compatibility facade가 장기적으로 새로운 변경을 방해할 때
- selective port가 concrete implementation보다 복잡해지고 test value를 만들지 못할 때
