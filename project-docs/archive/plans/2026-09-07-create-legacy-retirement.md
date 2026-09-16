# Create 레거시 기록·잠금의 안전한 제거

- 상태: `IMPLEMENTED`
- 날짜: `2026-09-07`
- 조사 근거: 사용자가 VM 생성 경로의 중복 책임·사용처를 확인하고 안전한 제거 순서를 정하는 작업에 “ㅇㅇ 진행하자”로 동의했다.
- 기준: [Specification](../../specifications/project-specification.md), [ADR-009](../../decisions/adr-009-proxmox-state-authority-and-create-history.md), [ADR-004](../../decisions/adr-004-postgresql-durable-operation-recovery.md)
- 승인자: 사용자
- 승인 근거: 단계 1과 상태 표시 개선을 함께 진행한다는 제안에 “ㅇㅇ 그러면 진행해보자”로 승인. 단계 2–5는 비승인 후속이다.

## 선행 작업 우선순위

아래는 조사 당시 기록이다. 이후 Create 입력·관찰 조건 분리와 본 계획의 단계 1·상태 표시 개선은 완료됐다. 단계 2–5는 후속 설계이며 이 계획의 구현 완료 범위에 포함하지 않는다.

2026-09-07 실제 Proxmox GET 조사 결과, storage·network는 각각 3/3, VM config·detail은 각각 28/28 관찰됐으나 guest agent는 13개 중 11개만 관찰됐다. VM 101은 agent 설정이 켜져 있지만 API가 agent 미실행 오류를 반환했고, VM 900은 agent 설정이 없으며 agent 조회가 HTTP 500을 반환했다. 현재 collector는 모든 running VM에 agent 조회를 기대하고, frontend Create 진입과 backend mutation은 snapshot 전체 complete를 요구한다.

이 차단은 request/workload 이력이나 파일 guard를 읽기 전에 발생한다. 따라서 **Create 관찰 조건·입력 화면 차단 개선을 먼저 구체화하고, 본 레거시 제거 단계 1을 이어서 수행**하는 순서를 추천한다. 전체 snapshot의 partial 표시는 보존하며, 입력 가능 여부와 실행에 필요한 관찰 조건을 분리해야 한다. 특히 static IP 충돌 검사가 관찰된 VM IP에 의존하므로 guest agent 실패를 단순 무시해 충돌 없음으로 처리해서는 안 된다. 실행 gate 변경은 별도 Plan에서 필요한 source 범위·불완전한 IP 근거 정책을 정한 뒤 수행한다. 이번 조사는 Proxmox GET만 사용했으며 guest agent 설정·실행, VM mutation과 gate 코드는 변경하지 않았다.

## 목표와 범위

Proxmox 현재 상태와 DB의 생성 이력을 분리한다. 입력·승인·결과·복구 근거는 보존하고, 과거 생성 기록이 VMID를 영구 점유하는 구조와 중복 실행 판단을 단계적으로 제거한다. 현재 템플릿 입력·fresh 검증은 유지한다.

첫 구현 범위는 생성 이력 조회를 정확한 생성 작업 ID에 묶는 준비 단계다. VMID 재사용 허용, 테이블 변경, 파일 잠금 삭제를 한 번에 수행하지 않는다. 다른 작업의 기능 변경, 권한·연결 gate 변경, 과거 데이터 삭제, live mutation과 배포는 비범위다.

## 조사한 현재 사용처

| 대상 | 확인한 producer·consumer | 판단·제거 선행 조건 |
|---|---|---|
| `vm_create_requests` | `db/vm_runtime.py`의 기록·동일 요청 replay·대상 조회, `vm_create/application.py` 실행 gate, `operations/vm_create/recovery_adapters.py` 성공·실패 projection, `vm_create/evidence.py` | 아직 실행 판단에 쓰인다. 바로 삭제 불가. Operation 중심 판단으로 옮기되 과거 Operation 없는 요청의 처리도 정의해야 한다. |
| 완료 요청의 대상 차단 | `TARGET_BLOCKING_VM_CREATE_STATUSES`에 `completed` 포함, `_existing_vm_create_result_if_blocked`의 `PROXMOX_CREATE_TARGET_CONFLICT` | 현재 VM 부재 여부와 별개로 과거 완료 기록이 새 작업을 막는다. 아래 workload 소유권 전환 후 제거한다. |
| `vm_instances` | 키는 `node:vmid`, `create_job_id`는 단일 생성 작업. recovery projector가 다른 작업 owner를 거부 | 과거 이력과 대상 연결이 결합돼 있다. row를 새 작업으로 덮어쓰면 과거 기록을 잃을 수 있다. |
| replay의 workload 조회 | `_vm_instance_from_existing_result`와 execute replay가 `get_vm_instance_record(node, vmid)` 사용 | 작업 ID를 검증하는 조회 경계부터 필요하다. VMID 재사용을 먼저 허용하면 다른 생성 결과가 섞일 가능성이 있다. |
| readiness와 evidence | `operations/vm_create/post_create_readiness.py`는 `create_job_id`로 Operation 연결. `vm_create/evidence.py`는 해당 job의 workload를 조회 | 동일 VMID라는 이유로 새 관찰을 과거 생성에 연결하면 안 된다. 작업별 생성 근거와 새 VM 여부를 확인할 수 없는 관찰의 처리 정책이 필요하다. |
| `record_vm_instance_from_create` | production 호출은 검색되지 않으며 `test_vm_create_recovery.py`의 직접 테스트만 남음. 실제 성공 기록은 recovery projector가 수행 | 제거 후보. 기존 소유권 보호를 projector 테스트가 검증하는지 확인한 뒤 helper와 그 전용 테스트만 제거 가능하다. |
| Jobs/artifacts | plan 5개 artifact, 승인 checksum, preview, evidence API, foreground·recovery projection | 모두 불필요한 복제가 아니다. 승인·이력 consumer를 먼저 옮겨야 하며 이번 단계에서 artifact를 삭제하지 않는다. |
| 공통 DB·파일 잠금 | `operations/target_lock.py`는 durable lock 획득 후 파일 생성. Create/Start/Shutdown/Guided 및 recovery가 파일 정리를 호출 | 파일 정리 실패가 recovery 완료·DB lock 해제를 막는 계약도 존재한다. Create만 삭제하면 공통 경로가 불일치하므로 네 action을 함께 검증하는 별도 전환이 필요하다. |

코드 경로는 저장소의 `backend/app/` 기준이다. 전체 이름 검색과 실제 호출 경로를 확인했으며 동적 외부 consumer가 없다는 배포 수준의 보증은 아니다.

## 선택과 추천

1. **작업별 이력 조회 → 실행 판단 통합 → 파일 guard 제거 → 저장 구조 정리**를 추천한다. 단계가 늘지만 각 변경에서 보존해야 하는 동작을 확인할 수 있다.
2. completed guard만 먼저 삭제하면 변경량은 작지만 성공 projection의 다른 owner 거부와 과거 replay/readiness 연결 문제가 남는다. 채택하지 않는다.
3. request·workload·Jobs 테이블을 한 번에 제거하면 변경 계약·복구·과거 조회·rollback 범위가 너무 커진다. 채택하지 않는다.

목표는 Operation/event/checkpoint가 실행을 조정하고, 생성 결과는 생성 작업 ID로 식별되며, Proxmox가 현재 존재·상태를 판단하는 구조다. 이력의 물리 저장 위치를 새 테이블로 만들지, 기존 Operation 결과를 사용할지는 consumer와 기존 데이터 충족도를 확인한 후 결정한다. 단계 1에서 새 schema를 추정해 도입하지 않는다.

## 단계별 구현과 인수 조건

### 1. 작업별 조회 경계와 미사용 writer 제거 — 다음 구현 제안

- Create replay에 쓰는 workload 조회에서 요청한 `job_id`와 저장된 `create_job_id`의 일치를 검증한다. 조회 함수의 production 사용처 두 곳을 함께 변경한다.
- 정확한 작업의 linkage가 없으면 기존 reconciliation-required 처리로 닫고 다른 작업 결과를 replay하지 않는다. 정상 completed replay의 응답과 중복 mutation 방지는 유지한다.
- production 미사용인 `record_vm_instance_from_create`를 제거한다. 같은 다른-owner 보호를 실제 성공 projector 테스트에서 확인하고 미사용 helper만 테스트하던 케이스를 정리한다.
- 이 단계에서는 completed-target guard, request/Jobs write, recovery transaction과 잠금 구조를 유지한다. API 응답 필드는 유지하며 잘못된 linkage 허용만 차단한다.
- 검증: 동일 job 정상 replay, 같은 node/VMID의 다른 job row, linkage 누락, 성공 projection owner 충돌, foreground·recovery 성공 및 중복 실행 방지. 관련 테스트 후 backend 전체와 frontend 계약 테스트, diff 검사, 독립 quality-review.

### 2. 생성 이력과 현재 대상 연결 분리 — 별도 구체화

- 과거 replay/evidence를 변경 가능한 `node:vmid` row 없이 정확한 작업 결과에서 읽을 수 있게 한다. 기존 요청·Operation 없는 과거 데이터도 읽을 수 있는 정책과 필요한 migration을 정의한다.
- readiness의 생성 작업 귀속은 단순히 가장 최근 생성 이력이라는 이유로 선택하지 않는다. 외부 삭제·재생성·이동의 식별 근거가 부족하면 생성 이력에 자동 연결하지 않는다.
- 성공·실패·복구 projector를 작업별 결과 모델로 옮긴 다음 completed-target guard를 제거한다. 현재 Proxmox 점유와 진행 중/불명확 작업의 durable lock은 계속 차단한다.
- 검증: 완료 A → 외부 삭제 → 신규 B에 같은 VMID 사용, A replay는 A 결과 유지, A recovery가 B를 덮어쓰지 않음, 외부 생성·노드 이동·조회 실패, 동일 VMID 동시 생성, unresolved 작업 차단. PostgreSQL transaction·동시성 검증을 포함한다.

### 3. 실행 판단·호환 기록 통합 — 별도 구체화

- request status와 Operation status의 우선순위 및 legacy 요청 처리 정책을 명시하고 실행 판단을 Operation으로 통합한다.
- API의 `vm_create_request`, `vm_instance`, Jobs/evidence 응답 consumer를 이관한 뒤 중복 writer를 제거한다. 승인 artifact와 과거 이력 읽기는 보존한다.
- 검증: 동일 키 다른 intent, 중단 지점별 재시작, checkpoint/최종 projection 실패, stale worker 차단, historical API/UI 조회. DB 기록 실패를 성공으로 숨기지 않는다.

### 4. 공통 파일 guard 제거 — 별도 구체화

- 네 action 모두 durable lock을 획득하는지와 file-only 진입점이 있는지 확인하고, recovery의 파일 cleanup 요구를 함께 이관한다.
- 구버전 worker와 신버전의 혼용 및 남은 파일/진행 작업에 대한 rollout 절차를 정한다. 기존 파일을 일괄 삭제하지 않는다.
- 검증: action 간 같은 cluster/VMID 경쟁, 다중 process, 재시작, lease expiry와 stale worker, 불명확 mutation의 lock 유지. PostgreSQL 검증 없이 파일 guard 제거를 완료 처리하지 않는다.

### 5. 저장 구조 정리

producer·consumer가 사라진 뒤 별도 새 Alembic migration과 보존·복구 절차로 불필요 테이블/필드를 제거한다. 적용된 migration과 과거 데이터를 임의로 수정하거나 삭제하지 않는다.

## 영향·복구·중단 기준

- 보안: 기존 권한과 secret redaction을 유지한다. 실행 승인·artifact binding을 우회하지 않는다.
- 단계 1은 schema 변경 없이 코드 rollback 가능하다. 서로 다른 owner를 허용하는 rollback은 안전성이 낮아지므로 배포 시 오류 원인을 먼저 확인한다.
- 단계 2 이후 VMID 재사용 데이터가 생기면 구버전으로 단순 rollback할 수 있다고 가정하지 않는다. 새 기록을 보존하는 roll-forward 또는 쓰기 중단·호환 reader 확보 절차를 구현 전에 확정한다.
- 과거 이력 변경, 잘못된 작업에 evidence 귀속, 두 번째 mutation, incomplete recovery의 조기 lock 해제, 검증되지 않은 migration이 발견되면 해당 단계 진행을 중단한다.
- 이번 조사에서는 실환경 mutation, DB 데이터 변경, container/PostgreSQL 동시성 검증을 실행하지 않았다. 이것들은 문서·코드 조사로 대체할 수 없다.

## 승인 범위

이 승인은 **단계 1의 작업 ID 기반 workload 조회 강화와 production 미사용 writer 제거·관련 검증**을 의미하며, **VMID 재사용 허용, 단계 2–5 구현, DB migration·데이터 삭제, 파일 guard 제거, live mutation과 배포**를 의미하지 않는다. 단계 2–5는 순서와 검토 항목이며 해당 계약을 구체화한 뒤 승인 범위를 갱신한다.

## 함께 승인한 상태 표시 개선

표시 책임만 분리한다. authoritative base inventory가 있으면 연결됨을 표시하고 별도로 관찰 완료/일부 누락을 표시한다. 요청 실패·조회 중·미설정은 연결됨으로 표시하지 않는다. 내부 state/freshness, collector의 수집 기준, 권한과 모든 실행 gate는 유지한다. guest agent 미설정·미응답은 기존 VM 관찰 evidence로 남기며 실제 VM 설정을 변경하지 않는다. 별도 backend 상태 모델이나 새 API는 도입하지 않는다. 이 선택은 내부 partial 의미를 유지하면서 사용자에게 연결과 관찰을 구분해 설명한다.

연결/관찰 조합·오류 전환·fixture 거부를 frontend 테스트로 확인하고 실제 화면을 읽기 전용으로 확인한다. schema 변경 없이 표시 코드 rollback 가능하다.

## 승인 범위 구현 결과

- 단계 1 완료: 두 production replay 조회와 호출자에 `create_job_id`를 필수로 전달하고 정확한 owner·node·VMID를 검증한다. 미사용 `record_vm_instance_from_create`와 전용 테스트를 제거했다. 실제 성공 projector의 다른 owner 보호 테스트는 유지한다.
- 함께 승인한 상태 표시 개선 완료: 연결됨/연결 확인 필요와 관찰 완료/일부 누락을 구분한다. 오류·조회 중·미설정·fixture는 연결됨으로 표시하지 않는다. collector·내부 상태·실행 gate는 바꾸지 않았다.
- 검증: backend 전체 **638 passed, 6 skipped**, 관련 테스트 **58 passed**, frontend 17개 스크립트·ESLint·Vite build 통과, 문서 계약 10개와 diff 검사 통과. 독립 quality-review에서 확정 결함 없음.
- Chrome에서 `Proxmox 연결됨 · 관찰 일부 누락`과 Create 입력 화면을 확인했다. local backend를 변경 코드로 재시작하고 background recovery disabled를 유지했다. 실제 VM mutation·agent 변경·DB migration·데이터 삭제는 수행하지 않았다.
- 로컬 Python 3.14/Node 26에서 검증했다. 기준 container·PostgreSQL 통합·실환경 생성은 이번 검증에 포함하지 않았다.

VMID 재사용·실행 판단 통합·중복 기록 이관·파일 guard 제거·schema 정리(단계 2–5)는 여전히 남아 있다. 이 완료 상태는 해당 후속의 구현 승인이 아니다.
