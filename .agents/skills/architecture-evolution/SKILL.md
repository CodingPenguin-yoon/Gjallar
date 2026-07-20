---
name: architecture-evolution
description: 기존 프로젝트의 아키텍처, 도메인 경계, 데이터 소유권, 의존성 방향 또는 주요 기술 구조를 사용자의 명시적 요청과 승인 아래 점진적으로 변경한다. 거대 레거시 분해, Layered·Clean·Hexagonal 전환, 모듈 분리, 데이터 접근 기술 교체처럼 구조적 마이그레이션이 목표일 때 사용한다. 하네스 최초 도입이나 국소적인 일반 리팩터링에는 사용하지 않는다.
---

# Architecture Evolution

기존 동작과 계약을 보호하면서 아키텍처를 검증 가능한 단계로 발전시킨다.

## 시작 조건

- 사용자가 아키텍처 변경을 명시적으로 요청했거나 승인했다.
- 변경 목적과 기대 효과가 단순한 패턴 선호보다 구체적이다.
- 현재 구조를 조사할 수 있는 코드와 검증 수단이 있다.

조건이 충족되지 않으면 자동으로 구조 변경을 시작하지 않는다.

## 현재 상태 지도화

1. `.agent-harness/core/architecture.md`와 `workflow.md`를 읽는다.
2. Project Profile, Specification, Architecture, ADR, 관련 Plan을 읽는다.
3. 호출자, 공개 계약, 상태, 데이터 접근, transaction, 외부 효과를 조사한다.
4. 기존 테스트와 characterization test 가능성을 확인한다.
5. 변경 빈도, 결함, 테스트 비용 같은 실제 문제를 근거로 정리한다.

현재 아키텍처와 목표 아키텍처를 섞어 설명하지 않는다.

## 목표와 선택지

- 해결할 구조적 문제와 성공 기준을 정의한다.
- 유지할 동작과 비범위를 명확히 한다.
- 현실적인 전환 선택지를 적합도 순으로 최대 세 개 제시한다.
- 각 선택지의 장점, 단점, 데이터·계약 영향, 전환 비용, rollback을 비교한다.
- 추천안과 감수할 단점을 사용자에게 설명한다.

권장 방향을 새 ADR의 `PROPOSED` 상태와 고위험 공유 Plan의 `DRAFT` 상태로 작성한다. 주요 결정을 한 번에 하나씩 사용자에게 확인받은 뒤 ADR을 `ACCEPTED`, Plan을 `APPROVED`로 전환한다. 승인 전에는 되돌리기 어려운 구현을 시작하지 않는다.

## 전환 계획

일괄 재작성보다 작은 수직 전환을 우선한다.

- characterization test로 현재 동작 보호
- 공개 계약과 compatibility seam 확보
- 새 책임을 목표 경계에 구현
- 호출자를 작은 단위로 전환
- 데이터 migration과 이중 읽기·쓰기 필요성 검토
- 단계별 테스트, 관찰, rollback 또는 roll-forward
- 이전 구현 제거 전 소비자와 데이터 전환 확인

Strangler, Branch by Abstraction, 모듈 추출 등은 문제에 적합할 때만 사용한다. 패턴 이름을 적용하는 것 자체를 목표로 삼지 않는다.

## 구현 규율

- 각 단계는 독립적으로 검증하고 가능한 한 되돌릴 수 있게 한다.
- 아키텍처 변경과 무관한 기능 추가를 섞지 않는다.
- 테스트를 약화하거나 silent fallback으로 양쪽 구조의 차이를 숨기지 않는다.
- 데이터 소유권과 transaction 변경은 migration 순서와 정합성을 검증한다.
- 새로운 주요 선택이 나타나면 구현을 멈추고 사용자에게 한 번에 하나씩 묻는다.

## 완료

1. 단계별 인수 조건과 검증을 실행한다.
2. `$quality-review`로 독립 리뷰한다.
3. `$documentation-sync`로 Architecture, ADR, Domain, Flow, API, Database를 실제 상태와 맞춘다.
4. 기존 경로 제거 여부와 잔여 소비자를 확인한다.
5. 남은 단계, 기술 부채, rollback 가능성을 보고한다.
