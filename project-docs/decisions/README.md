# Architecture Decision Records

- 최종 검토일: `2026-09-14`

이 디렉터리는 Gjallar의 구조적 결정과 그 대체 관계를 보존한다. ADR은 현재 상태 설명서가 아니라 결정 당시의 배경, 선택지, 이유와 결과를 기록하는 역사다. 제품의 현재 범위는 [`Project Specification`](../specifications/project-specification.md), 실제 구현은 [`현재 아키텍처 기준선`](../architecture/overview.md)을 따른다.

## 상태 의미

- `ACCEPTED`: 현재 제품·아키텍처 판단에 유효한 결정
- `SUPERSEDED`: 후속 ADR이 대체한 역사적 결정
- `REJECTED`: 검토했으나 채택하지 않았거나 철회한 결정
- `PROPOSED`: 사용자 승인을 기다리는 결정

`SUPERSEDED`와 `REJECTED` ADR은 구현 권한이 아니지만, 같은 실패를 반복하지 않도록 원문과 대체 관계를 보존한다.

## 현재 유효한 결정

| ADR | 결정 | 적용 범위 |
|---|---|---|
| [`ADR-012`](adr-012-create-preset-and-history-retention.md) | 선택적 DB 프리셋과 현재 저장 단위의 이력 보존 | 프리셋 DB 유지·템플릿 직접 입력 독립, 입력·검토·승인·작업 기록의 자동 만료·삭제 없음 |
| [`ADR-011`](adr-011-create-legacy-retirement.md) | current-workload writer·파일 잠금 제거 | Operation 역사 결과, VMID 재사용, 명시적 readiness owner, PostgreSQL 실행 조정 |
| [`ADR-010`](adr-010-create-result-history.md) | Create 완료 결과와 현재 연결 분리 | completed replay의 Operation snapshot 사용, legacy exact linkage |
| [`ADR-002`](adr-002-modular-monolith-domain-boundaries.md) | Domain-oriented Modular Monolith와 Vertical Slice 전환 | 배포 구조, 도메인 경계와 의존 방향 |
| [`ADR-003`](adr-003-production-inventory-connection-truth.md) | Production Inventory 연결 상태와 Test Fixture 격리 | `unconfigured`·`live`·`degraded`, fail-closed observation |
| [`ADR-004`](adr-004-postgresql-durable-operation-recovery.md) | PostgreSQL Durable Target Lock과 In-process Recovery Runner | 유지되는 verified action의 lock·GET-only recovery |
| [`ADR-007`](adr-007-observe-first-operations-intelligence.md) | Observe-first Operations Intelligence와 선택적 Verified Action | 제품 중심, 권한 경계, DRS 폐기와 이식성 방향 |
| [`ADR-008`](adr-008-template-based-create-and-persistence-simplification.md) | 템플릿 기반 생성과 저장 의존성 단순화 방향 | 현재 단계 생성 범위와 설계 기준; 후속 ADR-009~012에서 구체화 |
| [`ADR-009`](adr-009-proxmox-state-authority-and-create-history.md) | Proxmox 현재 상태와 Create 이력 저장 분리 | 직전 상태 조회, DB 이력·실행 조정 역할; 입력 이력 제거를 목표로 하지 않음 |

ADR-008은 ADR-007의 Create 범위를 구체화하며 ADR-003의 관찰 gate나 ADR-004의 lock/lease를 폐기하지 않는다. 템플릿 직접 입력·선택적 프리셋은 구현됐고, ADR-012가 DB 프리셋 유지와 현재 저장 단위의 자동 삭제 없는 보존을 확정한다. 장기 archive·consumer·schema 이관은 별도 설계다.

## 역사적 결정

| ADR | 상태 | 대체 관계·보존 이유 |
|---|---|---|
| [`ADR-001`](adr-001-proxmox-gjallar-authority-boundary.md) | `SUPERSEDED` | `ADR-007`이 권한 원칙을 계승하면서 control-plane-first 제품 중심을 대체 |
| [`ADR-005`](adr-005-drs-placement-and-operation-convergence.md) | `REJECTED` | DRS Common Operation 통합이 왜 철회됐는지 보존; `ADR-006`이 대체했고 최종 방향은 `ADR-007`이 계승 |
| [`ADR-006`](adr-006-drs-deprecation-and-insights-convergence.md) | `SUPERSEDED` | DRS 폐기 결정을 `ADR-007`이 계승하면서 observe-first 제품 경계로 확장 |

## 적용 규칙

1. 사용자가 가장 최근에 승인한 방향을 우선한다.
2. 같은 범위에서는 최신 `ACCEPTED` ADR을 적용한다.
3. 현재 코드·API·DB를 설명할 때는 current 문서를 사용하고 목표 ADR을 구현 완료로 해석하지 않는다.
4. 공개 계약, 데이터와 외부 상태를 바꾸는 구현은 승인된 Plan 없이 시작하지 않는다.

ADR 본문의 `현재`는 결정 당시의 시점을 가리킬 수 있다. 당시 배경·승인 기록을 새 구현 상태로 덮어쓰지 않으며 후속 관계를 안내한다. 당시 구현·검증 기록은 [종료 계획 목록](../archive/plans/README.md), 현재 운영 계약은 [문서 안내](../README.md)의 기준 문서에서 확인한다.
