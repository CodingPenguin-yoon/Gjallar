# ADR-011: VM 현재 상태 복제와 파일 잠금 제거

- 상태: `ACCEPTED`
- 결정일: `2026-09-07`
- 승인: 사용자의 남은 레거시 전체 제거 요청
- 관계: ADR-009·ADR-010을 계승하고 ADR-004의 파일 guard 병행 및 ADR-008의 current-workload 병행 기록을 대체한다.

## 결정

Proxmox가 현재 VM 존재·설정의 기준이다. 현대 Create는 `vm_instances`를 갱신하지 않는다. 완료된 작업별 결과는 Operation의 `details.workload`, 관찰 근거는 job별 request/artifact에 보존한다. 입력·승인·감사 및 실행 조정용 기록은 필요한 DB 사용이다.

완료된 과거 Create 요청은 VMID를 독점하지 않는다. 새 Create는 fresh Proxmox preflight와 직전 재검증을 통과해야 하며, 진행 중·미확정 Operation과 durable lock은 충돌을 차단한다. unresolved legacy 요청은 자동 완료 처리하지 않는다.

로컬 readiness 증거는 명시된 `create_operation_id`와 artifact에 저장된 owner·target·job을 검증해 succeeded Create에 연결한다. VMID로 최근 생성자를 추정하지 않는다. owner 없는 증거는 Jobs-only로 보존하고 동일 evidence identity의 owner 변경은 거부한다.

Create·Start·Shutdown·Guided는 PostgreSQL locator lock만 사용한다. 파일 잠금 API·port·cleanup 분기를 제거한다. terminal projection·recovery completion·잠금 해제를 exact owner·lock ID·lease fence로 보호된 transaction으로 처리한다. lease 만료는 lock 해제가 아니다.

## 보존과 전환

기존 schema·사용자 데이터·적용된 migration은 변경하거나 삭제하지 않는다. `vm_instances`의 historical exact reader와 과거 Start/Shutdown no-effect marker의 read-only alias는 저장된 이력·복구를 위해 유지한다. 신규 writer는 새 계약만 기록한다.

구버전과 신버전의 mutation worker 혼합 실행은 지원하지 않는다. 전환 시 mutation을 중지하고 진행 중 작업을 관찰·정리한 뒤 단일 버전을 배포한다. 예전 lock 파일을 자동 삭제하지 않는다. 새 Create는 예전 current linkage를 쓰지 않으므로 구버전으로 단순 rollback하면 과거 replay가 차단될 수 있다. roll-forward를 우선한다.

## 검증 기준

같은 VMID 새 작업과 과거 replay 분리, 잘못된 readiness owner 거부, unresolved 작업 차단, stale lease·대체된 lock handle 해제 거부, PostgreSQL 원자적 terminal 복구를 검증한다. 실제 VM 변경이나 운영 DB migration은 이 결정에 포함하지 않는다.
