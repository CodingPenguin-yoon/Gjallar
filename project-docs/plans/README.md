# 구현 계획과 후속 방향

- 최종 검토일: `2026-09-14` (잔여 코드·저장 정책·격리 검증 완료, 운영·Git 후속 분리)

이 인덱스는 합의한 방향, 구현 승인과 완료 이력을 구분한다. 제품·문서 상태 규칙은 [문서 안내](../README.md), 실제 구현은 [아키텍처](../architecture/overview.md)를 따른다.

## 다음 수정 방향

[ADR-008](../decisions/adr-008-template-based-create-and-persistence-simplification.md)에 따라 현재 단계 Create는 템플릿 기반에 집중한다. 템플릿 선택·사양 입력 중심의 UI, 검토 계산·저장 분리, Operation별 완료 결과 이관과 current-workload 중복 기록 제거를 완료했다.

이번 구체화는 [ADR-009](../decisions/adr-009-proxmox-state-authority-and-create-history.md)를 따른다. Proxmox가 현재 인프라 상태의 기준이고 DB는 입력·검토·작업 이력과 실행 조정을 담당한다. 검토 이력의 일괄 제거를 목표로 하지 않는다.

[ADR-012](../decisions/adr-012-create-preset-and-history-retention.md)에 따라 선택적 DB 프리셋과 현재 저장 단위 이력의 자동 만료·삭제 없는 보존을 확정했다. 수정본별 불변 보존·장기 archive는 별도 설계 범위다.

남은 운영 작업은 VM 101·900의 guest agent 상태 진단과 필요한 조치, 템플릿 3000의 guest-exec 정책 선택이다. guest OS 관리 접근, 정확한 변경과 중단 영향을 확인한 뒤 수행한다. production 배포와 기존 변경의 Git 정리·commit/push도 별도 후속 작업이며, [종료 Plan의 B·C](../archive/plans/2026-09-14-remaining-work-closure.md)에 관찰 상태와 실행 경계를 보존했다.

## 활성 Plan

[남은 파일 잠금·저장 정책·검증과 운영 작업 마감](../archive/plans/2026-09-14-remaining-work-closure.md)의 A 범위를 완료했다. Start·Shutdown 요청 파일 잠금 제거, DB 잠금 획득 뒤 상태 재검증, 실행 전 실패와 replay 경합 보완, 저장 정책·문서 일치와 격리 PostgreSQL·기준 container 검증을 마쳤다. 현재 `APPROVED` 구현 Plan은 없다.

[서버 3 생성 실증과 테스트 VM 정리](../archive/plans/2026-09-08-live-create-matrix.md)를 완료했다. Ubuntu 두 모드·Rocky stopped는 성공했고, Rocky boot는 부팅·IP 확인 후 템플릿의 guest-exec 금지로 초기화 검증이 제한됐다. 총 6개 테스트 VM과 디스크를 모두 정리했다. 기존 VM agent와 Rocky 템플릿 정책 변경은 별도 범위다.

[단계별 VM 생성·VMID 지정](../archive/plans/2026-09-08-create-wizard-and-vmid.md)을 완료했다. [VM 생성 레거시 전환 완료](../archive/plans/2026-09-07-complete-create-legacy-retirement.md)는 `IMPLEMENTED`로 보관돼 있다. current-workload writer·완료 VMID 독점·readiness owner 추정·공통 target 파일 잠금은 제거됐고, 남아 있던 Start·Shutdown 요청 잠금은 9월 14일 후속 구현에서 제거했다. 입력·감사·복구와 실제 소비자가 있는 Jobs/artifacts는 필요한 기능으로 유지한다.

## 종료된 계획

완료·대체·철회된 계획은 [종료 계획 보관 목록](../archive/plans/README.md)에서 확인한다. 이 페이지에는 앞으로 수행할 방향과 활성 계획만 관리한다.

## 계획의 종료와 보관

- `IMPLEMENTED`·`SUPERSEDED`·`CANCELLED`·`ROLLED_BACK` Plan은 `archive/plans/`로 이동하고 [보관 목록](../archive/plans/README.md)에 연결한다.
- 기존 승인 기록·검증 결과는 유지한다. 후속이 대체하는 범위를 안내하고 내부 링크를 갱신한다.
- 구현 변경 이력만 남기기 위한 Plan·별도 요약 문서를 추가하지 않는다. 일반 변경 이력은 Git이 담당한다.
