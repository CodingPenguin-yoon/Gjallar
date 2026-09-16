# ADR-010: Create 완료 결과와 현재 workload 연결 분리

> 후속 적용: [ADR-011](adr-011-create-legacy-retirement.md)이 current-workload write·파일 guard 병행과 readiness owner 이관 범위를 대체한다. 아래는 결정 당시 기록이다.


- 상태: `ACCEPTED`
- 날짜: `2026-09-07`
- 결정자: 사용자
- 근거: 레거시 정리 후 다음 단계 진행에 “ㄱㄱ”로 승인. [ADR-009](adr-009-proxmox-state-authority-and-create-history.md)의 이력/현재 상태 분리 원칙을 적용한다.

> 적용 안내: 후속 [evidence 조회 이관](../archive/plans/2026-09-07-create-evidence-history.md)에서 같은 역사 결과 규칙을 evidence summary에 적용했다. 아래 범위 설명은 최초 replay 전환 당시 결정이다.

## 결정

이미 succeeded Operation에 저장되는 생성 당시 workload 결과를 completed replay의 기준으로 사용한다. 작업 ID·operation type·execution mode·target/node/VMID와 결과 필드를 확인한다. 이 결과는 현재 VM 상태가 아니라 해당 작업 당시 관찰이다. 성공한 Operation의 결과가 누락·손상되면 현재 workload row로 대체하지 않고 복구 필요로 중단한다.

아직 succeeded Operation이 없는 과거 요청을 호환 경로로 채택할 때만 node·VMID·create_job_id가 일치하는 기존 workload 조회를 유지한다. 과거 데이터 자동 backfill이나 정상으로 추정하는 fallback은 하지 않는다.

## 비교·결과

현재 node:VMID row에 계속 의존하면 외부 변경·향후 재사용이 과거 replay를 훼손한다. 새 이력 테이블은 기존 Operation 결과와 중복되므로 도입하지 않는다. 기존 결과 snapshot을 읽는 방식은 schema 변경 없이 소비자를 이관할 수 있지만, 손상된 과거 Operation은 명시적으로 차단한다.

이번 적용은 replay 소비자에 한정한다. evidence summary·readiness 귀속·성공 projector의 현재 workload 저장·완료 요청 VMID guard는 다음 소비자 이관 전까지 유지한다. VMID 재사용은 승인된 현재 작업의 구현 범위가 아니다. [실행 계획](../archive/plans/2026-09-07-create-replay-history.md)을 따른다.
