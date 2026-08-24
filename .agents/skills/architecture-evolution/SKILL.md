---
name: architecture-evolution
description: 사용자가 명시적으로 요청하거나 승인한 Gjallar의 도메인 경계, 데이터 소유권, 의존성 방향 또는 주요 기술 구조 변경을 점진적으로 설계하고 구현한다. 국소 리팩터링이나 Codex 프로젝트 설정 변경에는 사용하지 않는다.
---

# Architecture Evolution

기존 동작과 공개 계약을 보호하면서 승인된 목표 구조로 작은 단계씩 전환한다.

## 시작 조건

- 사용자가 구조 변경을 명시적으로 요청하거나 승인했다.
- 해결할 구조적 문제와 관찰 가능한 성공 기준이 있다.
- 현재 동작을 조사하고 보호할 검증 수단이 있다.

조건이 없으면 아키텍처 변경을 시작하지 않는다.

## 설계

1. Project Profile, 관련 Specification, 현재 Architecture와 최신 ADR·Plan을 확인한다.
2. 호출 경로, 공개 계약, 데이터 소유권, transaction과 외부 효과를 지도화한다.
3. 현재 구조, 임시 호환 구조와 최종 목표 구조를 분리한다.
4. 현실적인 전환안을 최대 세 개 비교하고 추천안, 비용과 rollback을 설명한다.
5. 구조적 결정은 `PROPOSED` ADR과 `DRAFT` 고위험 Plan에 기록한다.

승인 문장으로 허용 범위와 비범위를 재진술하고 사용자의 동의를 받은 뒤 ADR을 `ACCEPTED`, Plan을 `APPROVED`로 전환한다.

## 구현

- characterization test와 공개 계약을 먼저 보호한다.
- 새 책임을 목표 경계에 구현하고 호출자를 작은 수직 단위로 전환한다.
- 데이터 migration이나 이중 읽기·쓰기가 필요하면 정합성과 배포 순서를 명시한다.
- 각 단계에 검증과 rollback 또는 roll-forward 지점을 둔다.
- 이전 경로 제거 전 소비자와 데이터 전환을 확인한다.
- 새 주요 결정이나 승인 범위 변경이 나타나면 구현을 멈추고 다시 승인받는다.

완료 전 `$quality-review`를 수행하고 Architecture, ADR, Domain, Flow, API와 Database 중 실제로 달라진 문서만 현재 구현에 맞춘다.
