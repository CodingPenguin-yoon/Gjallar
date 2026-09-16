# VM 생성 레거시 전환 완료

- 상태: `IMPLEMENTED`
- 날짜: `2026-09-07`
- 승인자: 사용자
- 승인 근거: “전체적으로 다 걷어내 오래걸려도 상관없으니까 확실하게 딱 지금 필요한 코드만 남겨”
- 기준: ADR-009·ADR-010의 Proxmox 상태 권위/Operation 역사 결과

## 범위와 선택

남은 Create 레거시 소비자와 공통 파일 guard를 한 작업 안에서 이관한다. Operation을 실행 상태·결과·복구 기준으로 사용한다. 입력/승인/감사 기록과 shared Jobs/artifacts는 실제 소비자가 있으므로 보존하되 과거 완료 기록을 현재 VM 소유권으로 판단하지 않는다. 현대 Create 성공은 current vm_instances를 쓰지 않는다. 기존 데이터는 삭제하지 않고 역사 조회만 유지한다.

readiness는 create_operation_id를 명시한 로컬 제출 증거만 해당 succeeded Operation에 연결한다. VMID로 가장 최근 작업을 추정하지 않는다. 같은 evidence identity를 다른 owner로 재사용하면 충돌로 닫는다. 소유자 없는 과거 증거는 Jobs-only로 유지한다.

완료된 과거 요청의 VMID 독점 guard를 제거하되 실제 VM 존재 여부는 fresh Proxmox preflight, 진행 중/불명확 작업은 Operation·durable lock으로 차단한다. 원격 mutation 재실행은 금지한다. unresolved legacy 요청은 자동 성공/실패 처리하지 않는다.

공통 target lock은 PostgreSQL locator/owner/lock ID로만 조정한다. 네 action foreground/recovery의 file cleanup와 파일 존재 기반 결정을 함께 제거한다. lease expiry는 lock release가 아니다. mixed-version 실행은 지원하지 않으며 전환 시 기존 worker 정지·진행 중 작업 관찰 후 단일 버전 배포가 필요하다. 기존 파일을 실행 중 자동 삭제하지 않는다.

새 테이블/범용 계층을 추가하지 않고 기존 Operation·artifact·durable lock을 재사용한다. historical reader는 데이터 보존에 필요한 최소 경로이며 신규 producer로 확장하지 않는다.

## 단계와 인수 조건

1. Create current-workload writer·target owner 의존 제거, Operation/legacy unresolved 요청만 실행 충돌 판단, 역사 replay 보존.
2. readiness owner 입력/이력 binding, 다른 VM 세대의 자동 귀속 제거.
3. 공통 file guard producer·consumer·port 제거, DB locator 잠금으로 통합.
4. 미사용 코드·테스트·문서·운영 지침 일치화. 기존 applied migration은 수정하지 않는다.
5. backend 전체, frontend tests/lint/build, PostgreSQL 동시성/복구 검사, diff·문서 검사, 독립 quality-review. 같은 VMID 신규 생성·과거 replay, foreign recovery 방지, unresolved block, stale lease/다른 lock ID release 거부를 검증한다.

## 안전·복구와 완료 경계

실제 VM 생성·설정 변경, 기존 DB 데이터 삭제, 운영 배포는 수행하지 않는다. schema 파괴 migration도 불필요하면 만들지 않는다. 필요한 이력·복구·감사 코드는 레거시라는 이름으로 제거하지 않는다. 로컬 isolated 테스트 데이터만 변경한다.

현대 current-workload write 중단 뒤 이전 버전 replay는 linkage 누락으로 차단될 수 있어 단순 rollback을 보장하지 않는다. 데이터는 보존하고 전환 실패는 roll-forward를 우선한다. 동시 mutation, 미확정 결과의 lock 해제, 잘못된 owner evidence 귀속이 있으면 완료 처리하지 않는다. 실행 불가능한 기준 검증은 이유를 명시한다.

이 승인은 남은 VM 생성 의존성·중복 구현과 공통 파일 잠금의 코드 이관·삭제·검증을 의미하며 과거 사용자 데이터 삭제·live Proxmox mutation·production 배포를 의미하지 않는다.

## 검증 결과

- 로컬 backend 전체: 652 passed, PostgreSQL 전용 8 skipped.
- 격리 PostgreSQL 전체 integration: 8 passed. locator/lease 복구, DRS 이전 보존 경계, readiness 최초 owner 동시 저장을 검증했다.
- 기준 Python 3.13 backend-test 컨테이너: 전체 테스트 통과, PostgreSQL 전용 검사는 별도 격리 DB에서 실행했다.
- frontend 전체 test script, ESLint, Vite build와 기준 Node 24 production Docker build 통과. pnpm wrapper 대신 같은 하위 검증 명령을 직접 실행했다.
- 독립 quality-review 두 건에서 historical no-effect marker 호환과 readiness 동시 owner 충돌을 발견했고 수정·재검토했다. 추가 actionable finding은 없다.
- 실제 VM mutation·운영 배포·사용자 DB 변경은 수행하지 않았다. 임시 PostgreSQL은 검증 뒤 종료했다.

Create current-workload writer, 완료 VMID 독점 guard, readiness owner 추정과 네 action의 파일 잠금 구현·port·cleanup 분기 제거를 완료했다. historical reader, 입력·감사·Jobs/artifacts와 PostgreSQL 실행 조정·복구는 필요한 코드로 보존한다. ADR-011과 현재 API·DB·아키텍처·운영 문서에 반영했다.
