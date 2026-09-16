# 종료된 구현 계획

- 상태: `HISTORICAL`
- 분류 검토일: `2026-09-14`

현재 진행할 변경은 [활성 계획](../../plans/README.md), 실제 동작은 [문서 안내](../../README.md)를 따른다. 아래 계획은 당시 범위의 승인·결과를 보존하며 신규 구현 지시로 사용하지 않는다.

종료 Plan의 당시 조사·승인·검증 결과는 원래 날짜와 함께 보존한다. 아래 `IMPLEMENTED`는 기록된 구현 범위의 완료이며 production 배포·live 검증 완료를 일괄 의미하지 않는다. 각 Plan의 미실행 검사와 운영 제한도 함께 읽는다.

| 계획 | 상태 | 보존 의미·후속 관계 |
|---|---|---|
| [2026-09-14 잔여 파일 잠금·저장 정책·검증](2026-09-14-remaining-work-closure.md) | `IMPLEMENTED` | A 완료: Start·Shutdown 요청 잠금 제거·DB 경합 보완·ADR-012·기준 container/PostgreSQL 검증. B 운영 변경과 C Git 마감은 별도 후속 |
| [2026-09-08 서버 3 생성 실증](2026-09-08-live-create-matrix.md) | `IMPLEMENTED` | 네 조합 성공·제한 원인 확인, UPID·lease·Dashboard 수정, 테스트 VM 6개와 디스크 정리 |
| [2026-09-08 단계별 VM 생성·VMID 지정](2026-09-08-create-wizard-and-vmid.md) | `IMPLEMENTED` | 네 단계 UI, 추천·직접 VMID/이름, 검토 무효화·실제 화면 확인 |
| [2026-09-07 VM 생성 레거시 전환 완료](2026-09-07-complete-create-legacy-retirement.md) | `IMPLEMENTED` | current-workload writer·VMID 독점·owner 추정·파일 잠금 제거, PostgreSQL 동시성·복구 검증 |
| [2026-09-07 Create evidence 역사 결과](2026-09-07-create-evidence-history.md) | `IMPLEMENTED` | CLI 증거 조회의 current workload 의존 제거, legacy 중복/다른 target 거부 |
| [2026-09-07 Create replay 결과 이관](2026-09-07-create-replay-history.md) | `IMPLEMENTED` | 성공 Operation의 당시 결과 반환. 현재 linkage 부재/owner 교체와 분리 |
| [2026-09-07 Create 레거시 제거 1단계·상태 표시](2026-09-07-create-legacy-retirement.md) | `IMPLEMENTED` | 정확한 생성 작업 조회·미사용 writer 제거·연결/관찰 표시 분리. 남은 범위는 VM 생성 레거시 전환 완료 계획에서 이관 |
| [2026-09-07 Create 입력과 관찰 조건 분리](2026-09-07-create-partial-observation.md) | `IMPLEMENTED` | partial 입력 허용·guest agent 실패 static/DHCP 구분. 다른 action gate 유지 |
| [2026-09-07 템플릿 중심 생성 입력](2026-09-07-template-first-create-input.md) | `IMPLEMENTED` | DB 프로필 없는 직접 입력·선택적 프리셋, 중복 기본값 제거 |
| [2026-09-07 Create 직전 관찰·레거시 정리](2026-09-07-create-fresh-pre-dispatch-validation.md) | `IMPLEMENTED` | 최초 mutation 전 cache 없는 검증. 프로필 선택화는 템플릿 입력 계획에서 완료, 이력 소유권은 후속 |
| [2026-09-07 Create 계산·저장 분리](2026-09-07-template-create-state-and-history.md) | `IMPLEMENTED` | 승인된 1단계 완료. 직전 조회·템플릿 입력은 각각 후속 계획에서 완료, 이력 정책은 별도 설계 |
| [2026-09-07 Navigation 정리](2026-09-07-navigation-cleanup.md) | `IMPLEMENTED` | 독립 Network readiness 제거·redirect, 중복 진입점과 메뉴 이름 정리 |
| [2026-08-26 Reconciliation·실행 안정화](2026-08-26-operation-reconciliation-and-execution-stabilization.md) | `IMPLEMENTED` | 네 action의 GET-only 복구·operator observe·중단 결과 처리 |
| [2026-08-26 Observe→Explain→Evidence 연결](2026-08-26-observe-explain-evidence-flow-closure.md) | `IMPLEMENTED` | partial 관찰·VM 상세·관련 작업 연결. Network readiness 독립 기능 방향은 9/7 계획으로 대체 |
| [2026-08-24 Observe-first 전환](2026-08-24-observe-first-operations-intelligence-transition.md) | `IMPLEMENTED` | 제품 방향·DRS repository 제거. production DB 적용과 live mutation은 별도 경계 |
| [2026-07-23 Backend 모듈 경계](2026-07-23-backend-modular-boundaries-and-legacy-compatibility.md) | `IMPLEMENTED` | application 경계·legacy 격리의 당시 완료 범위 |
| [2026-07-23 DRS·Common Operation 통합](2026-07-23-drs-placement-and-common-operation-convergence.md) | `ROLLED_BACK` | 철회된 DRS 통합; 보존된 초기 단계와 롤백 범위는 본문 참조 |
| [2026-07-21 Insights·DRS maintenance](2026-07-21-insights-productization-and-drs-maintenance.md) | `IMPLEMENTED` | 당시 과도기 구현. DRS maintenance는 이후 제거됨 |
| [2026-07-21 Graceful Shutdown](2026-07-21-graceful-vm-shutdown-and-recovery-rollout.md) | `IMPLEMENTED` | shutdown·recovery와 당시 검증 기록 |
| [2026-07-21 Frontend Workloads·Operations](2026-07-21-frontend-workload-operations-slice.md) | `IMPLEMENTED` | 초기 도메인별 UI와 exact target 연결 |
| [2026-07-21 Durable recovery 기반](2026-07-21-durable-operation-recovery-foundation.md) | `IMPLEMENTED` | DB locator lock·lease·첫 handler. 현재 네 action으로 확장됨 |
| [2026-07-21 Create 공통 Operation 통합](2026-07-21-create-vm-common-operation-integration.md) | `IMPLEMENTED` | 기존 Create와 공통 Operation 병행 기록 도입 |
| [2026-07-20 Operations core·Guided](2026-07-20-operations-backend-core-and-guided-qm.md) | `IMPLEMENTED` | Operation/event와 첫 Guided action |
| [2026-07-20 Control Plane 상위 전환](2026-07-20-verified-operations-control-plane-transition.md) | `SUPERSEDED` | 완료 단계는 보존. 제품 중심과 후속 범위는 ADR-007·8/24 계획으로 대체 |
