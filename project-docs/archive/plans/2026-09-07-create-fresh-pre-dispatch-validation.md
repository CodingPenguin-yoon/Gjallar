# Create 실행 직전 새 관찰과 레거시 정리

- 상태: `IMPLEMENTED`
- 날짜: `2026-09-07`
- 승인자: 사용자
- 승인 근거: 1단계 완료 후 “진행하고 진행하면서 레거시 코드 걷어낼 수 있으면 전부 걷어내줘”로 후속 진행과 범위 내 불필요 코드 제거 승인
- 기준: [ADR-009](../../decisions/adr-009-proxmox-state-authority-and-create-history.md), [앞 단계](2026-09-07-template-create-state-and-history.md)

## 범위와 완료 조건

Create가 target lock과 durable dispatch preparation을 확보한 뒤, 최초 mutation 전에 캐시를 사용하지 않는 Proxmox 관찰로 승인된 대상·계획의 조건을 다시 확인한다. DB의 과거 관찰은 이 재검증의 입력으로 사용하지 않는다. 새로운 상태로 계획 artifact를 덮어쓰지 않는다. 조회 실패·partial 관찰은 503, 승인 영향이 있는 변경은 409로 중단하고 기존 pre-dispatch failure 복구로 잠금과 기록을 닫는다.

사용처가 없는 Create 계산의 잔여 입력·변수는 삭제한다. 공개 HTTP 계약, 프로필 필수 여부, schema, 기록 시점, mutation checkpoint·GET-only recovery와 진행 중 요청 보호는 유지한다. Start/Shutdown의 관찰 흐름은 변경하지 않는다.

## 조사와 선택

- Live inventory에는 snapshot과 VM detail TTL cache가 있다. 전역 cache를 비우면 동시 조회와 섞일 수 있으므로 별도 adapter로 새 snapshot을 수집하고 요청별 read adapter에 고정한다. 전체 complete live 기준을 유지하는 만큼 조회 비용과 지연이 늘어난다.
- application의 `dispatch_prepared` 이후 최초 clone 이전 검증을 추가한다. 검증 후 외부 상태가 다시 바뀔 가능성은 기존 API 실패와 post-check로 처리하며 자동 mutation 재시도하지 않는다.
- approved plan의 VMID를 고정해 검사한다. 재조회에서 suggest_next_vmid가 바뀌어도 새 VMID를 자동 선택하지 않는다. 승인 관련 plan core와 fresh 계산 결과를 비교한다.
- 완료된 `vm_create_requests`의 target 차단은 `vm_instances.create_job_id` 소유권과 결합돼 있다. 차단만 삭제하면 외부 생성 후 projection 실패가 발생한다. 이력 소유권·VMID 재사용 이관은 이번 삭제 대상에서 제외하고 후속 계약으로 남긴다.
- GitOps 이름 artifact는 approval checksum·manifest·history consumer가 사용하므로 삭제하지 않는다. file guard와 target lock도 복구 consumer가 남아 있어 유지한다.

## 단계와 검증

1. 캐시와 detail cache를 공유하지 않는 fresh snapshot + 요청별 고정 inventory 구현. warm cache 뒤 template/VM 상태 변화와 재조회 실패·partial을 테스트한다.
2. mutation client 생성 전 fresh preflight·승인 내용 비교, 안전한 pre-dispatch 실패 처리 연결. template 삭제·VMID 선점·bridge/storage 변경·비관련 상태 변화, 조회 실패·잠금 해제·evidence 보존·mutation 미호출을 확인한다.
3. 호출 검색으로 미사용 Create 입력·변수 제거. 기존 승인·replay·recovery와 frontend 계약 회귀 테스트, 독립 quality-review 후 완료한다.

검증은 관련 테스트와 전체 backend, frontend tests/lint/build, 문서 링크·diff 검사다. PostgreSQL 전용 검증과 container 검증은 환경이 허용할 때 실행하고 미실행 이유를 기록한다. live mutation과 production DB 작업은 하지 않는다.

## 중단·되돌리기와 승인 범위

이 승인은 Create 최초 mutation 전 새 관찰 검증과 사용처가 없는 범위 내 코드 제거를 의미하며, DB table·이력 삭제, VMID 소유권 이관, file guard 제거, complete live gate 완화와 live 작업을 의미하지 않는다.

schema 이관 없이 이 변경만 되돌릴 수 있다. 기존 사용자 변경은 보존한다. pre-dispatch failure의 transaction/fencing이 깨지거나 미확인 외부 mutation이 생기면 중단한다. lock/lease 만료 또는 기록 실패는 기존 복구 규칙대로 잠금을 보존하고 성공으로 표시하지 않는다.

## 구현·검증 결과

- Live fresh snapshot은 전용 adapter에서 수집하며 snapshot/detail cache를 기존 reader와 공유하지 않는다. complete 관찰을 요청별 `ObservedInventoryAdapter`로 고정한다.
- `dispatch_prepared` 이후 mutation client 생성 전에 새 preflight·plan core를 계산하고 승인 VMID와 조건을 비교한다. 재검증에서 plan artifact를 저장하지 않는다. 409/503 실패를 기존 pre-dispatch 완료 경로에 연결했다.
- 레거시 제거: 사용하지 않는 draft `network_id` 인자와 preflight `observed_ips` 변수를 삭제했다. 공개 HTTP 입력·응답 필드 변경은 없다.
- 완료 request의 VMID 차단은 workload 소유권과 결합되어 유지했다. GitOps artifact·파일 guard도 승인·이력·복구 consumer가 있어 유지한다. DB 이력 삭제·schema 변경·live 작업은 하지 않았다.
- 관련 회귀 테스트 161개 통과, 새 상태 검증과 live inventory 테스트 20개 통과. 전체 backend 608개 통과·PostgreSQL 전용 6개 skip·기존 deprecation warning 462개. frontend 테스트 17개·ESLint·Vite build 통과. 문서 계약 10개와 diff 검사 통과.
- 앞 단계와 같은 환경에서 pnpm wrapper 대기 문제를 피하기 위해 동일 Python/Node 명령을 직접 실행했다. 로컬 Python 3.14.6·Node 26.8.1로 검증했으며 기준 Python 3.13·Node 24 container 검증은 Docker socket 접근 제한으로 실행하지 않았다.
- 독립 quality-review에서 확정 결함은 발견되지 않았다. fresh 전체 조회 전후 heartbeat는 있지만 조회 중 주기 heartbeat는 없다. 60초를 넘겨 lease가 만료되면 기존 fencing으로 실행을 중단하며, 장시간 조회·lease takeover와 실제 클러스터 지연은 이번에 검증하지 않았다.
- 다음 범위는 필수 DB 프로필을 선택적 프리셋과 정책으로 분리하는 템플릿 입력 설계, VMID 재사용 시 과거 workload provenance 보존 계약이다. 이 완료 기록은 후속 schema·소유권 이관 승인으로 사용하지 않는다.
