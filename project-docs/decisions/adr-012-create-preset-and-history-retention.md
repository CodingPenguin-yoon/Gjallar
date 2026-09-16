# ADR-012: 선택적 DB 프리셋과 현재 저장 단위의 이력 보존

- 상태: `ACCEPTED`
- 결정일: `2026-09-14`
- 결정자: `사용자`
- 관계: [ADR-008](adr-008-template-based-create-and-persistence-simplification.md)·[ADR-009](adr-009-proxmox-state-authority-and-create-history.md)의 미확정 프리셋 저장 방식과 입력·검토 이력 보존 정책을 구체화한다. [ADR-011](adr-011-create-legacy-retirement.md)의 Proxmox 현재 상태 권위와 PostgreSQL 실행 조정은 유지한다.
- 승인 근거: 남은 작업의 코드·정책·문서·검증 범위를 제시한 뒤 사용자가 진행을 요청했다. 승인 범위와 환경·Git 작업의 별도 경계는 [계획 인덱스](../plans/README.md)에서 확인한다.

## 배경

Create는 템플릿 직접 입력과 선택적 DB 프리셋을 제공한다. 직접 입력은 `vm_create/application.py`의 `_profiles_for_payload()`에서 빈 정책 집합을 반환하므로 DB 프로필을 조회하지 않는다. 프리셋 경로는 기존 운영자가 수정한 기본값·제약을 사용한다.

입력·검토 계산과 artifact 저장은 분리됐지만 저장된 request, Jobs, artifact와 Operation은 승인 비교·replay·recovery·조회에 계속 사용된다. 이를 삭제하거나 설정 파일로 옮기는 데 필요한 consumer 전환과 데이터 이관 근거는 없다.

## 결정

1. 선택적 프리셋은 기존 `create_vm_profiles`에 유지한다. 템플릿 직접 입력은 계속 프리셋 조회와 독립적으로 동작하며 기존 프리셋 값과 제한 정책을 보존한다.
2. 현재 저장 단위의 입력·검토·승인·작업 기록에 기간 기반 자동 만료·삭제를 도입하지 않는다. request, Jobs/Artifacts, Operation/event와 기존 이력 consumer를 유지한다. 저장하지 않은 브라우저 입력이나 모든 수정본을 새로 보존하는 정책은 아니다.
3. 저장 단위의 의미를 유지한다. `job_runs`는 job별 최신 상태 projection이고, `job_artifacts`는 job·artifact type·filename에서 만든 동일 identity에 upsert한다. `operation_events`는 application에서 append-only로 기록한다. 자동 삭제 없음은 모든 입력·artifact revision의 불변 원본 보존이나 external WORM을 의미하지 않는다.
4. 현재 VM 상태는 Proxmox를 새로 관찰해 판단한다. DB의 과거 관찰·입력·작업 이력을 현재 VM 존재·설정의 별도 권위로 사용하지 않는다. exact approval, replay, recovery와 secret redaction 계약을 유지한다.

## 선택지와 비용

| 항목 | 채택 | 대안과 재검토 비용 |
|---|---|---|
| 프리셋 저장 | 선택적 DB 저장 유지 | JSON/YAML 이관은 운영자 수정값 보존, 조회·수정 consumer와 전환 절차가 필요하다. |
| 이력 보존 | 현재 저장 단위에 자동 만료·삭제 없음 | 기간별 삭제는 승인·감사·replay·복구 소비자와 삭제 가능한 identity의 경계를 먼저 정해야 한다. |
| 수정본 보존 | 기존 projection·upsert·event 계약 유지 | 모든 revision의 불변 보존은 별도 version schema, 조회 계약과 저장 비용 검토가 필요하다. |

작업과 evidence가 늘면 저장량·백업량도 늘어난다. 용량·조회 비용이 운영 요구를 충족하지 못하거나 별도 보존·삭제 요구가 생기면 실제 사용량과 consumer를 근거로 재검토한다. 이번 결정은 새 자동 정리 기능·archive pipeline·schema·migration을 추가하지 않는다.

## 적용과 남은 경계

현재 구현의 저장 방식을 정책으로 확정하므로 프리셋이나 기존 이력 데이터를 변환하지 않는다. shared Jobs/Artifacts의 historical DRS row도 현재 저장 단위로 보존하며, 전용 DRS 기능을 복원하지 않는다. 장기 archive·compatibility table 이관·revision별 불변 보존·external WORM과 운영 DB 변경은 별도 설계 범위다. session expiry 같은 인증 수명 정책을 변경하는 결정도 아니다.

실제 저장·transaction 계약은 [DB 기준선](../database/current-schema-and-ownership.md), 제품 범위는 [명세](../specifications/project-specification.md), 운영 대응은 [Runbook](../operations/runbook.md)을 따른다.
