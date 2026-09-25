# 현재 아키텍처

- 기준: 기존 구현 문서와 코드의 공개 진입점. 2026-09-16 문서 통합이며 새 기능·live 검증 완료를 뜻하지 않는다.
- 목표는 [PRD](prd.md), 구현 순서는 [로드맵](roadmap.md), 실행·장애 대응은 [개발 안내](development.md)를 따른다.

## 1. 전체 구조와 현재 범위

React SPA와 FastAPI를 함께 배포하는 modular monolith이며 PostgreSQL과 Proxmox VE API를 사용한다. production image는 빌드된 UI를 같은 origin에서 제공한다. 신규 관리형 Compose는 명시적 초기화와 serve를 분리한다. 기존 수동 배포의 legacy entrypoint는 호환 경로로 유지하며 개발 안내를 따른다.

```text
Browser → React → FastAPI /api/v1 → Proxmox VE API
                          │
                          └→ PostgreSQL (계정·작업·이력·잠금·복구)
옵션 recovery observer ─────→ Proxmox GET + 로컬 기록 정합화
```

현재는 inventory·VM 상세·Insights, 기존 템플릿 복제 기반 Create, Start, graceful Shutdown, Guided `qm unlock`, Operations·Jobs 이력과 로컬 계정을 제공한다. 템플릿 직접 입력과 선택적 DB 프리셋은 구현됐다. 독립 Python CLI·전체 화면 TUI·관리형 Compose bootstrap과 서버 중계 Proxmox 등록의 코드·격리 검증을 구현했다. macOS arm64의 전용 loopback 설치·기존 token 관리형 import·CA 검증·재시작 보존을 확인했으며 신규 PVE 로그인/발급 및 다른 지원 조합 검증은 남아 있다. 정지 VM CPU·메모리·NFS scsi0 디스크 확장·기존 NIC bridge/VLAN 변경·정지 VM full clone·명시적 전체 삭제·인증된 웹 콘솔과 선택적 관리형 권한은 웹·CLI에 추가했다. 7001 CPU·메모리 웹 변경·CLI 원복·전원, 40000 full clone·디스크 확장·NIC 변경/원복·삭제와 소유volume 부재, 7001 입력 없는 콘솔 연결/종료를 실제 확인했다. 준비된 VM 템플릿 전환·공식 이미지 제작/소유 자원 정리·기존 생성 기반 테스트 배포 검사와 접속 증거 기록을 구현했으며 실환경 검증은 남아 있다. 현재 지표/PVE 이력·임계 초과/해제·기존 작업 실패/복구 이력은 웹·CLI로 구현했다. 관리형 설치의 노드/VM 현재·1시간 및 긴 기간 추이와 알림 조회를 확인했으며 storage·실제 초과/해제 사례는 남아 있다. 정지 VM NFS 백업 조회·생성은 웹·CLI로 구현했으며 실제 생성 검증은 남아 있다. 별도 VMID 격리 복원·검사 보고서는 웹·CLI로 구현했고 실환경 검증은 남아 있다. 정지 VM의 공유 NFS 노드 이동과 노드 준비 보고서, 제한된 directory storage/VM bridge 설정은 구현·자동 검증됐으며 실제 PVE 변경 검증은 남아 있다.

## 2. 책임과 코드 찾기

경로는 저장소 루트 기준이다. 상세 함수·필드·endpoint 목록을 문서에 복제하지 않고 코드와 계약 테스트를 함께 확인한다.

| 책임 | 현재 코드 | 유지할 경계 |
|---|---|---|
| 앱·HTTP 조립 | `backend/app/main.py`, `backend/app/api/v1/` | HTTP 매핑과 업무 규칙 분리 |
| 사용자·권한 | `backend/app/auth/` | server-side session의 actor만 신뢰 |
| 관찰·연결 | `backend/app/workloads/`, `setup_integration/` | 실제 상태·관찰 시점·source별 실패 표시 |
| Proxmox 연동 | `backend/app/proxmox/` | read adapter와 mutation client 분리 |
| 작업 상태·기록 | `backend/app/operations/core/` | projection·event·digest와 상태 전이 |
| 잠금·복구 | `backend/app/operations/locks/`, `recovery/` | target 직렬화·lease fencing·GET-only 복구 |
| action별 규칙 | `operations/vm_start/`, `vm_shutdown/`, `vm_create/`, `guided_qm/` (backend/app 아래) | action별 사전 조건·완료·실패 판정 |
| Create 호환 경로 | `backend/app/vm_create/`, `vm_actions/` | 기존 API·Jobs consumer 보존 |
| 인사이트 | `backend/app/insights/` | 읽기 전용, 자동 실행·승인 생성 없음 |
| DB·Jobs | `backend/app/db/`, `jobs/`, `backend/alembic/` | 현재 저장 단위·호환 기록·migration 보존 |
| 독립 client·설치 호스트 | `client/src/gjallar_client/` | API session·조회와 명시적 Compose bootstrap 분리, backend/DB 직접 import 없음 |
| 관리형 서버 초기화 | `backend/app/installation/` | 빈 DB identity marker·일회성 admin, 일반 serve에서 migration 금지 |
| 화면 | `frontend/src/app/`, `pages/`, `features/`, `entities/`, `shared/` | app → pages/features → entities/shared 방향 |

기능별 구조에서 도메인별 구조로 전환 중이다. Create facade는 아직 DB·Jobs·Proxmox workflow를 직접 알며 frontend에도 legacy components/utils가 남아 있다. 별도 Policy/Approval·Evidence 서비스와 새로운 도메인별 DB 소유권은 완성된 구조가 아니다. 다른 도메인의 persistence model을 편의상 직접 참조하지 않는다.

## 3. 현재 상태와 관찰

Proxmox가 VM·노드·config·위치·전원·task actual state를 소유한다. Gjallar DB는 입력·승인·작업 이력과 실행 조정을 담당한다. 과거 workload 결과를 현재 인프라 상태로 사용하지 않는다.

- 필수 연결 설정 부재는 `unconfigured`, base snapshot 조회 성공은 `live/fresh`, snapshot 부재는 `degraded`다. 개별 source 실패로 전체 연결 상태를 낮추지 않는다. fake inventory로 대체하지 않는다.
- authoritative snapshot이 있으면 조회된 데이터를 표시하고 누락 항목은 availability로 구분한다. snapshot 부재 시 과거 inventory를 보여주는 durable stale fallback은 없다.
- read adapter에는 기본 10초 process-local cache가 있다. 최초 Create mutation 직전에는 별도 adapter의 cache 없는 관찰을 사용한다.
- Create 입력·검토는 일부 항목이 누락된 base snapshot에서도 가능하다. 실행은 guest agent 외 source의 complete 관찰과 action별 조건을 요구한다. 연결은 base snapshot 조회 성공 시 live/fresh로 표시하고 항목별 누락은 availability에 남긴다. Start·Shutdown은 새 snapshot의 해당 VM config/detail 관찰과 기존 실행 조건으로 판단하며 다른 자원·guest agent 누락으로 전체 VM을 차단하지 않는다. Guided의 별도 실행 조건은 유지한다.
- 고정 IP는 ping 응답과 기존 VM config·guest-agent IP 정보를 함께 확인한다. 점유 발견은 red 차단, 미발견·확인 불가는 yellow와 사용자 확인이다. 기존 VM guest agent 누락만으로 차단하지 않으며, 미발견을 미사용 보장으로 해석하지 않는다.
- Insights는 risk/readiness/capacity/placement를 요청 시 조합한다. section 장애는 `unknown`/`unavailable`, 최대 200개 초과 finding은 truncation metadata로 표현한다. 별도 TSDB·지속 수집·알림 시스템은 없다.
- VM이 켜져 있다는 사실은 애플리케이션 정상 동작을 뜻하지 않는다. `live`도 mutation 권한이 검증됐다는 뜻은 아니다.

## 4. API와 UI의 중요한 계약

- 기본 prefix는 `/api/v1`, 인증은 `gjallar_session` HttpOnly cookie와 서버 세션이다. read는 `viewer+`, mutation은 `operator+`, 계정 관리는 `admin`이다. payload의 actor를 신뢰하지 않는다.
- 성공 envelope은 `{ "ok": true, "data": ..., "meta": ... }`다. 오류는 다수 경로가 FastAPI `detail`을 사용하며 아직 모든 오류가 하나의 mapper로 통일되지는 않았다.
- 기존 method/path·오류 의미·canonical frontend route를 바꾸는 변경은 consumer·deprecation 검토가 필요하다. route의 실제 목록은 `backend/app/api/v1/router.py`와 child router, `backend/tests/contracts/test_api_v1_route_registry.py`를 따른다.
- Jobs·artifacts persistence 실패는 `503 JOBS_PERSISTENCE_UNAVAILABLE`, Risks는 `503 RISKS_PERSISTENCE_UNAVAILABLE`이며 빈 성공으로 바꾸지 않는다. 없는 job은 `404`다.
- `/insights`는 `execution_mode=observe_only`, `read_only=true`, `allowed_actions=[]`다. `drs_advisor`·`drs-rec-*` 문자열과 historical DRS renderer는 호환 계약이며 DRS 실행 기능이 아니다.
- Operations target filter는 exact equality와 AND 결합이다. 상세의 status 외 `coordination_incomplete`·recovery·target lock도 확인해야 한다.
- `POST /api/v1/operations/{operation_id}/recovery/observe`는 operator가 현재 `expected_version`·`expected_checksum`·`idempotency_key`로 한 작업의 GET-only 관찰을 요청한다. 같은 key·최초 fence는 replay, 다른 fence 재사용·stale 상태·live lease·binding 불일치는 `409`다. key는 최대 160자, digest ledger는 최대 64개이며 퇴출 없이 상한에서 새 key를 거부한다. 일시적 observation/persistence 실패는 `503`, 입력 오류는 `422`, 없는 작업은 `404`다. force-complete·force unlock 권한이 아니다.
- VM 문맥은 `/instances/:vmid`와 `proxmox_vm`·`vmid:<VMID>`로 연결한다. `/operations`·`/insights`·계정 화면을 유지하며 `/instances/networks`·`/networks`는 inventory로 redirect한다. 제거된 DRS route는 복원하지 않는다.
- Operation 상세 polling은 non-terminal 또는 coordination 미완결인 동안 5초 간격 최대 60회다. paused/manual이면 중단하고 뒤늦은 이전 응답을 폐기한다.

2026-09-20 웹 탐색은 `navigationModel`을 단일 기준으로 상단 전체 현황·VM 관리·템플릿·모니터링·인프라·작업 이력 여섯 영역을 항상 표시한다. 연결 확인 중이나 읽기 불가에도 메뉴 위치는 유지하고 기존 route boundary가 조회/실행을 제한한다. 모니터링은 관찰·진단으로, 인프라는 노드 유지보수·Proxmox 연결·스토리지·브리지 설정으로 묶어 데스크톱 왼쪽 메뉴와 모바일 select를 공유한다. 템플릿 제작·정리는 `TemplatesShell`, 인프라는 `InfrastructureShell`, 내 계정·관리자용 사용자/세션은 우측 `AccountMenu`와 `SettingsShell`에서 접근한다. exact route/alias 우선·최장 prefix로 상단과 하위 메뉴를 각각 하나만 활성화하며 canonical URL과 admin guard를 보존한다. VM 상세의 개별 설정 disclosure는 입력/결과를 유지하고 영구 삭제를 분리한다. 공통 workflow 표면·입력 높이·focus 표시·reduced motion은 `index.css`에서 관리한다. 공통 shell은 최대1680px의 작은 간격을 사용하며 모니터링 패널은 어두운 배경에서 수치·축·결측을 구분한다. 전체 현황은 `OverviewShell`의 `/` 클러스터 전체와 `/nodes?node=<node>` 노드 상세로 나눈다. 비교표의 노드 링크는 선택 대상을 상세로 전달한다. 현황의 `ClusterTrends`와 모니터링의 `MetricPanel`/`useMetricsReport`는 기존 GET 지표 API를 공유한다. 노드·자원·기간이 바뀌면 이전 응답을 숨기고 늦은 응답을 무시하며 대상/기간 불일치는 오류로 표시한다. 전체 현황은 선택 범위의 모든 노드를 최대4개 동시 요청으로 조회한다. `clusterMetrics`는 CPU를 현재 관찰된 logical CPU 용량으로 가중 평균하고 메모리·네트워크를 합산한다. 이력은 같은 timestamp에 모든 노드의 해당 지표가 있을 때만 집계하며 결측·실패·용량 불명을0으로 대체하지 않는다. 현재값은 각 노드의 요청 시점 관찰이며 원자적 snapshot이 아니다. 현재 CPU 용량이 과거와 같았다는 보장은 없고 네트워크에는 노드 간 내부 통신이 중복 포함될 수 있다. 해상도가 다르면 구간을 연결하지 않는다. 상세/기존 모니터링 첫 진입은 명시된 대상 또는 첫 노드 한 개를 조회하며 백그라운드 polling은 없다. 현황의 최근4개 작업은 기존 Operation 조회·상세 경로를 사용한다. 스토리지 요약은 관찰된 최대 사용률이며 공유 용량을 합산하지 않는다.

권한·request·오류의 세부 회귀 검사는 `backend/tests/contracts/`, frontend contract는 `frontend/tests/`가 기준이다. 문서 축약은 API 계약의 변경이 아니다.

## 5. 작업 실행과 성공 판정

공통 개념은 입력·intent 기록 → 현재 상태/권한/필요한 승인 확인 → target lock·recovery 준비 → 실행 → task·실제 상태 검증 → 기록·coordination 정리다. 모든 action이 한 DB transaction이나 같은 순서로 끝나는 것은 아니다.

| action | 실행과 완료 조건 | 중요한 제한 |
|---|---|---|
| Start | recovery 등록 후 POST, terminal task OK와 direct running 확인 | 이미 완료된 같은 intent는 replay, 재실행 금지 |
| Shutdown | graceful POST, task stopped/OK와 direct stopped 확인 | hard stop·reboot·timeout 강제 fallback 없음 |
| CPU·메모리 (`vm_compute`) | digest를 포함한 동기 PUT 응답 완료 뒤 current config·정지 상태 재조회 | 단일 socket cores·memory만, pending/lock/template 차단, 미확정 응답 자동 재전송 없음 |
| NIC 변경 (`vm_network`) | digest 포함 동기 PUT ack와 MAC/model·전체 net0 옵션·bridge/정지 상태 재조회 | 기존 net0 bridge/tag만, host pending 차단, guest 통신 별도 |
| 디스크 확장 (`vm_disk_resize`) | digest 포함 PUT의 exact resize UPID 저장, task stopped/OK와 config·실제 volume bytes 확인 | 정지 VM·NFS·scsi0 raw/qcow2, 절대 GiB 확장만, guest filesystem 별도 |
| Create | 기존 template clone→config/resize→선택적 boot→post-check | exact plan 승인, 최초 mutation 전 fresh 재검토, 단계별 durable checkpoint |
| Guided unlock | typed bundle→사용자의 외부 실행 attestation→config lock·active task 부재 검증 | backend shell/SSH executor 없음, attestation만으로 성공 아님 |

`blocked`는 실행 전 차단, `failed`는 명확한 실패, `needs_reconciliation`은 effect나 결과의 불확실성이다. API 요청 접수·task 발급만으로 성공을 선언하지 않는다. 오류·timeout·missing/invalid UPID·post-check 불일치는 같은 mutation을 무작정 재실행하지 않고 잠금과 근거를 보존한다. 외부 payload는 allowlist/redaction을 거쳐야 하며 raw credential·URL·body·잘못된 UPID를 저장하거나 locator로 사용하지 않는다.

### Create의 보존할 의미

- 템플릿 직접 입력은 DB profile을 조회하지 않는다. 프리셋 선택 시 해당 기본값·제약을 사용한다. draft/preflight는 Proxmox를 변경하지 않지만 Jobs 기록은 쓰므로 DB read-only가 아니다.
- 계산과 저장은 분리됐지만 plan 관련 다섯 artifact와 approval checksum·preview·execute consumer는 유지한다. 생성은 Proxmox API를 사용하고 manifest/planned Git diff는 호환 산출물이다.
- 검토 후 입력 변경·다시 검토는 새 작업 identity와 승인·동의 초기화를 요구한다. VMID 추천은 예약이 아니다. 실행 직전 승인 조건 drift는 `409 PROXMOX_CREATE_STATE_CHANGED`, 필수 관찰 불가는 `503`으로 최초 mutation 전에 중단한다.
- `stopped` 또는 `boot_and_verify`를 지원한다. 후자는 guest agent IP뿐 아니라 허용된 guest-exec로 cloud-init 완료 검사가 필요할 수 있다. 차단된 guest-exec 정책을 자동 해제하지 않는다.
- 현대 완료 replay·evidence는 succeeded Operation의 당시 `details.workload`를 읽는다. 현재 VMID 재사용·이동이 과거 결과를 바꾸지 않는다. 손상된 성공 결과를 현재 row로 대체하지 않고 reconciliation을 요구한다. legacy는 exact job/node/VMID linkage만 사용한다.
- 완료·성공 증거가 있는 Create 실행 재요청은 저장 계획을 사용하며 plan/preflight/review artifact를 새 관찰로 덮어쓰지 않는다. 같은 입력의 순수 계산 결과와 저장 계획을 비교하되 현재 관찰의 위험 요약은 역사적 replay 비교에서 제외한다. 생성된 자기 VM의 VMID·이름 충돌은 재실행 사유가 아니다. 생략한 VMID는 당시 선택값을 사용하며 변경된 설정·승인 checksum은 계속 거부한다. 신규 실행의 fresh 사전 검증은 유지한다.
- 완료 VMID 독점·readiness owner 추정·current-workload writer는 제거됐다. readiness 증거는 명시적 Create Operation에 연결한다.

### Guided unlock의 보존할 의미

서버가 allowlist와 typed parameter로 `qm unlock <vmid>`만 생성한다. 현재 lock·active task·필요 권한을 확인하고 durable handoff와 exact target lock을 결합한 뒤 5분 유효 instruction을 공개한다. 임의 command·option·secret 입력은 거부한다.

만료 시간만으로 미실행을 단정하지 않는다. 원래 lock 유지·active task와 attestation 부재를 실제 관찰했을 때만 expired/release한다. effect 가능성·관찰 실패는 reconciliation/retry다. 만료된 명령은 `do_not_execute`이며 late attestation은 과거 실행 사실만 기록한다. 자동 검증하지 않고 pause하며 수동 verification도 exact active lock 조건을 요구한다.

## 6. 데이터 소유권과 보존

Runtime DB는 PostgreSQL, SQLite는 명시된 테스트 전용이다. 실제 column·constraint·migration은 `backend/app/db/models.py`, `operations/{core,recovery}/infrastructure/models.py`, `backend/alembic/versions/`를 따른다.

| 저장 묶음 | 의미 |
|---|---|
| users·sessions·account_audit_events | 로컬 계정·세션·계정 감사 |
| create_vm_profiles | 선택적 사양 프리셋 |
| vm_create_requests·job_runs·job_artifacts | 입력·검토·승인·작업과 호환 consumer 기록 |
| vm_instances | 과거 exact history reader용. 신규 writer·현재 상태 권위 없음 |
| operations·operation_events | 최신 작업 projection·append-only checksum-linked event |
| operation_locks·operation_recovery_items | target 직렬화·관찰 lease/fencing·복구 상태 |
| proxmox_connections·proxmox_credentials·proxmox_registration_attempts | setup 소유 단일 연결·암호화 revision·등록 CAS/dispatch 상태. 새 migration `20260917_0030` |

현재 저장 단위의 입력·검토·승인·작업 이력은 자동 만료·삭제하지 않는다. `job_runs`는 최신 projection, `job_artifacts`는 동일 identity upsert이므로 모든 revision의 불변 보존이 아니다. event checksum도 application-level tamper evidence이며 WORM·규제 준수를 보장하지 않는다. historical DRS Jobs/Artifacts도 보존한다.

## 7. 트랜잭션·잠금·복구 제약

Proxmox 호출과 PostgreSQL은 원자적 transaction이 아니다. `session_scope()`는 로컬 commit/rollback 경계이며, Operation projection과 대응 event는 같은 transaction에 기록한다.

| 경로 | 완료 기록의 원자성 |
|---|---|
| Start/Shutdown foreground | terminal Operation을 먼저 기록, Jobs 저장은 별도, recovery completion·lock release가 뒤따름 |
| Start/Shutdown restart | 앞선 terminal 전이는 별도, terminal Jobs projector·completion event·recovery·lock release는 fenced transaction |
| Create 성공 | request/job/artifact·Operation 결과·최종 succeeded·recovery completion·lock release를 같은 fenced transaction에 기록 |
| CPU·메모리 | admission의 lock·Operation·recovery 준비가 한 transaction, 성공·완료·해제도 fenced transaction |

따라서 terminal Operation도 잠금과 미완결 recovery를 가질 수 있다. evidence·compatibility 저장 실패는 action-specific `503`과 exact Operation handoff로 드러내며 기존 결과·lock을 임의로 지우지 않는다.

- open locator lock은 한 configured cluster의 VMID를 action type과 node 표기를 가로질러 직렬화한다. scope key는 `{cluster_id}|proxmox_locator|{vmid}`다. 파일 guard는 제거됐다.
- Start/Shutdown은 잠금 획득·충돌 뒤 Jobs·Operation을 재조회한다. same-owner는 replay/in-progress, foreign owner 충돌은 현재 Operation·exact open foreign lock을 transaction 안에서 다시 확인한다.
- client/recovery 등록 전 실패는 no-effect Jobs를 먼저 쓸 수 있다. canonical planned·recovery item 부재·exact owned lock을 확인한 경우에만 실패 전이와 해제를 진행한다. 이미 다른 owner가 복구를 맡았으면 덮어쓰지 않는다.
- lease 만료는 observer 재claim 가능성을 뜻하며 target lock 해제나 외부 미실행의 증거가 아니다. commit은 current lease token/generation/expiry, Operation fence, exact lock owner/ID/cluster를 검사한다. stale observer는 projector도 실행하지 못한다.
- recovery kind는 Start·Shutdown·Create·Guided와 `vm_compute_observation`·`vm_disk_observation`·`vm_network_observation`·`vm_clone_observation` allowlist다. 기본 disabled인 in-process runner와 operator observe가 같은 GET-only handler를 사용한다. 원래 mutation·보상·임의 명령을 다시 실행하지 않는다.
- restart Create는 남은 mutation을 이어서 실행하지 않는다. 중간·미확정 phase는 근거를 수집하고 pause한다. 성공 복구는 persisted readiness/observed-after checkpoint·fresh config/status fingerprint·artifact content SHA-256/JSON 일치와 fenced transaction을 요구한다.
- recovery item 없는 crash를 no-effect로 복구하려면 현재 계약의 marker·checksum·정확한 lock·task/effect 부재 조건이 필요하다. 과거 기록이나 시간 경과만으로 추정하지 않는다.

## 8. 유지할 결정과 남은 설계

Proxmox actual-state authority, modular monolith, 명시적 연결 truth, PostgreSQL durable coordination, action별 검증, 현재 이력 보존을 유지한다. 과거 observe-first의 네 action 제한과 템플릿 제작 제외는 장기 제품 경계로 유지하지 않으며 새 목표는 PRD를 따른다. DRS 자동 배치·무승인 자동 복구·임의 shell은 복원하지 않는다.

현재는 한 configured cluster를 전제로 하며 다중 클러스터 식별·worker 분리·지속 관측·추가 기능의 CLI mutation·새 action 계약은 후속 설계다. 기능 확장을 이유로 기존 API·데이터·복구 계약을 묵시적으로 변경하지 않는다. migration은 새 revision으로만 수행하고 적용된 revision을 고치지 않는다. `20260824_0029`의 DRS hard-zero preflight·production 적용·파일 guard 전환 절차는 개발 안내에 유지한다.

M1의 구조는 웹·CLI·TUI → 선택한 로컬 또는 원격 Gjallar → Proxmox다. 클라이언트가 Proxmox를 직접 조작하는 별도 운영 경로는 없고 기존 서버의 권한·작업·잠금·검증 경계를 공유한다. 등록 설계·실행 근거와 남은 검증은 [M1 작업 기록](work/2026-09-16-m1-installation-connection.md)에 기록한다.

`2026-09-17` M1-1·M1-2는 사용자 승인 후 구현했다. Python client는 기존 cookie API를 사용하며 connection UUID/origin별 keyring 또는 명시적 process-memory session을 관리한다. 원격 HTTPS·고정 origin·redirect 금지·별칭의 atomic 저장과 동기식 CLI/TUI application을 공유한다. 기존 env Proxmox 설정을 자동 전환하지 않는다.

신규 Compose는 기본 loopback 앱/비공개 PostgreSQL 17 named volume과 image ID 고정을 사용한다. 2026-09-23 사용자 요청으로 신규 설치에 명시적 IPv4 wildcard bind 옵션을 추가했다. v3 manifest의 bind_address를 Compose 포트에 적용하고 VM IP를 저장하지 않는다. 외부 bind에서만 GJALLAR_ALLOW_SAME_ORIGIN을 활성화해 요청 URL의 scheme·host·port와 동일한 Origin을 HTTP와 콘솔 WebSocket에서 허용한다(ws/wss는 http/https로 대조). 기존 명시적 Origin 허용 목록은 유지하며 다른 Origin·null은 거부한다. 기본값은 비활성이어서 기존 배포의 인증 경계는 그대로다. CLI 자동 연결은 loopback, cookie는 HttpOnly/SameSite=Lax이며 원격 CLI HTTPS 정책은 변경하지 않는다. v1/v2 설치와 기존 공개 설정은 자동 변환하지 않고 재시작·동일 schema upgrade에도 보존한다. 외부 웹 HTTP는 전송 암호화를 제공하지 않으며 TLS proxy 자동 구성은 포함하지 않는다. 설치 manifest/volume label/DB marker identity를 결합하며 secret 전용 파일·mount와 관리자 stdin을 쓴다. `GJALLAR_DATABASE_URL_FILE`은 기존 URL env와 상호 배타적 입력이다. 빈 DB에서만 `gjallar_installation(singleton, installation_id, state)`를 만드는 infrastructure 초기화는 기존 Alembic revision을 수정하지 않으며, 일반/기존 DB에 자동 marker를 추가하지 않는다. PostgreSQL advisory lock으로 schema 초기화를 직렬화하고 users table EXCLUSIVE lock 아래 zero-user/history 검사·admin·account audit·ready marker를 원자적으로 기록한다. 기존 VM lock/recovery는 변경하지 않는다.

`init-schema`만 새 설치 migration/seed를 실행하고 `serve`·start는 현재 Alembic head/ready 확인만 한다. 같은 schema의 image upgrade만 제공하며 revision 변경·기존 DB migration은 별도 승인 경계에 남긴다. 검증한 image ID에는 digest 기반 로컬 보존 tag를 추가해 원래 tag 이동 뒤에도 image 참조를 유지한다. 실행 중 upgrade의 기존 readiness는 해당 container에서, 정지 설치와 candidate는 one-off maintenance에서 검사하며 후보 schema/설치 identity 불일치 시 서비스 전환을 시작하지 않는다. host manifest의 준비/volume 준비/완료 상태와 upgrade journal로 중단을 재개하고 volume·secret·계정·이력을 자동 삭제/덮어쓰지 않는다. PostgreSQL 17의 격리 동시성 검증은 통과했으며 OS keyring·VM 설치는 미검증이다. manifest v2부터 credential key 파일·mount를 추가한다. v1 설치는 읽기·서비스 관리 호환을 유지하고 자동 변환하지 않는다.

### Proxmox 등록과 credential 선택

기본 CLI는 `access_mode=cluster`와 빈 scope로 신규 발급한다. features를 생략하면 서버가 현재 지원하는 17개 feature를 확정하고 전용 privilege-separated token에 `GjallarClusterV1`의 지원 권한을 `/`·propagate=1 ACL로 부여한다. 현재·미래 자원을 포함하며 임의 PVE API/명령 실행 기능을 추가하지 않는다. 기존 intent의 기본값은 `scoped`이며 이전 canonical hash·암호화 AAD·DB schema를 보존한다. 아래 기능별 사전 대상 목록 계약은 `scoped`에 적용된다. 전체 연결도 각 작업의 실제 상태·지원 필드·역할·검토·잠금·복구 계약을 사용한다. runtime은 요청에 등장하는 대상을 기존 입력 정책에 투영하고, 자원 목록을 사전 등록 목록으로 필터링하지 않는다. 신규 자원마다 재등록할 필요가 없다.

웹 신규 등록은 `access_mode=cluster`, 빈 scope와 명시적 features를 사용한다. 기본 read로 클러스터 전체·미래 자원을 조회하고 선택한 기능만 작업을 허용한다. 선택 기능의 기존 역할을 `/`·propagate=1로 계획·검증하며 전체 기능을 선택한 기존 연결은 `GjallarClusterV1`을 유지한다. features를 생략한 기존 기본 CLI의 전체 기능 계약은 보존한다. cluster도 기존 token import를 지원하며 plan digest에 access_mode를 포함한다. 기존 토큰의 실제 권한을 검사하고 PVE token/ACL을 수정하지 않는다. 이전 scoped 연결·암호화 AAD는 자동 변경하지 않으며 표준 등록·활성화·재시작으로 전환한다. 웹에서 자원별 등록 입력은 제거했지만 기존 등록 이력과 제한 연결 API/고급 CLI의 호환은 유지한다.

관리자 전용 collection `POST /trust`는 endpoint만 받아 인증정보 없는 TLS handshake로 유효기간과 leaf SHA256을 조회한다. CLI가 지문 신뢰 확인을 받은 뒤 `certificate_sha256`을 intent에 저장한다. 이 profile은 매 HTTP 요청 및 WSS handshake의 인증 header/ticket 전송 **전에** leaf 지문·기간을 확인한다. CA/hostname profile과 동시 지정하지 않으며 인증서 변경 시 실패하고 자동 재신뢰하지 않는다. 계획의 trust digest와 credential AAD에 pin이 결합된다. 기본 CLI는 30일 토큰을 발급하며 자동 갱신은 제공하지 않는다. 자체 인증서의 최초 지문 신뢰는 사용자가 확인한다. 아래 CA/hostname 검증 설명은 기존 CA profile에 적용한다.

관리자 전용 `/settings/proxmox`, `gjallar proxmox-setup`, TUI `p`가 같은 `/api/v1/setup/proxmox/registrations` API를 사용한다. collection GET/POST는 본인 이력/등록, item GET은 상태, item POST `/{action}`은 login·mfa·plan·confirm·verify·activate·observe·cancel·revoke·import-plan·import-env다. create는 strict intent와 idempotency key, action은 expected_version을 요구한다. confirm/import-env는 plan_digest, revoke는 전체 token_id도 요구한다. 비밀번호·OTP는 login/mfa body로만 받으며 validation/upstream 오류에 원문을 반환하지 않는다.

검증 대상은 사용자가 제공한 pve-manager `9.0.11`, pam/pve 비밀번호·TOTP다. 실제 package/realm 조합 지원을 확정한 것은 아니다. 서버는 HTTPS CA/hostname 검증 후 비밀번호를 전송한다. 명시적으로 제공한 단일 self-issued CA가 critical BasicConstraints CA=true이며 KeyUsage 확장을 생략한 구형 PVE root 형식일 때만 `setup_integration/tls.py`가 Python 3.13의 VERIFY_X509_STRICT 형식 검사를 완화한다. CERT_REQUIRED·chain signature·hostname·기간·TLS protocol/cipher 검증은 유지하고 system CA·현대 CA·복수 bundle은 기본 strict 정책을 따른다. 이 정책은 trust anchor 로드 시 결정하며 실패 후 insecure fallback/retry하지 않는다. DNS 목적지를 고정하고 loopback/link-local 등을 거부하며 proxy·redirect·자동 retry를 사용하지 않는다. PVE ticket/CSRF는 Gjallar actor/session에 결합한 최대 5분의 process 메모리 context이며 재시작·만료 후 재로그인이 필요하다. 다중 worker 간 context 공유는 없다.

계획은 exact node/VM/storage/local bridge, read 및 선택적 power/compute/create/disk/network/clone, owner/token ID·만료·CA digest·ACL·connection version을 결합한다. compute는 기존 역할을 바꾸지 않고 선택 VM ACL에 별도 `GjallarVmComputeV1`(`VM.Config.CPU`, `VM.Config.Memory`)을 추가한다. 같은 이름의 다른 역할을 덮어쓰지 않는다. owner/effective token 권한과 실제 선택 자원 조회를 검사한다. 기존 연결은 새 등록·검증·명시적 전환·전체 재시작으로 갱신하며 이전 revision/token을 보존한다. Guided 권한 profile은 아직 제공하지 않으며 managed provider에서 해당 mutation을 거부한다. env adapter의 기존 action 권한 경로는 유지한다.

Create는 기존 조회 `vmids`와 별도 `template_vmids`·`create_vmids`를 받는다. 생성 대상은 기존 VM·원본과 중복할 수 없고 선택 storage·bridge가 필요하다. 원본은 실제 template임을 조회 검증한다. 원본 `GjallarTemplateCloneV1`은 Audit/Clone, 생성 대상 `GjallarVmCreateV1`은 Allocate/Audit·기존 생성 config 필드에 필요한 권한·PowerMgmt·GuestAgent.Audit/Unrestricted를 갖는다. `GjallarStorageAllocateV1`은 Datastore.AllocateSpace, `GjallarBridgeUseV1`은 SDN.Use다. ACL은 개별 자원에만 부여한다. guest-exec의 넓은 PVE 권한은 등록 전에 안내하며 managed request는 기존 `cloud-init status --wait` argv만 허용한다. 원본/대상/node/storage/bridge·config allowlist는 `setup_integration/capabilities.py`에서 검사한다. 신규 생성은 기존 plan/승인/Operation/복구를 재사용하며 별도 실행기를 만들지 않는다.

등록 Operation과 attempt는 같은 transaction에 기록한다. `token_dispatching`을 먼저 commit하고 발급 secret을 AES-256-GCM으로 즉시 staging한 후 ACL·조회 검증을 진행한다. AAD는 installation/connection/revision과 전체 설정에 결합하고 key/nonce uniqueness를 검사한다. secret·비밀번호·ticket·OTP·upstream 원문은 Operation에 넣지 않는다. `token_dispatching`/`acl_applying`에서 멈추면 결과 미확정이며 자동 재발급·ACL 재전송을 하지 않는다. exact 발급 token의 확인·명시적 폐기를 제공하고, 폐기 응답 유실은 부재 조회로만 마무리한다. 공유 역할이나 가져온 env token은 자동 삭제하지 않는다.

검증된 pending revision의 활성화는 fresh 조회 후 connection version CAS와 PostgreSQL transaction advisory lock으로 직렬화한다. 같은 lock을 VM target lock 획득 시에도 사용한다. 다른 nonterminal Operation·open lock·미완결 recovery가 있으면 전환/활성 token 폐기를 거부한다. 활성화는 기존 revision을 retiring으로 보존하며 폐기는 별도다. process마다 최초 source/revision을 고정하므로 전환 후 **모든 서버 process 재시작**이 필요하다. managed 선택 후 key/DB 오류는 degraded/실행 차단이며 env fallback은 없다.

명시적 env import는 서버의 기존 token을 읽어 같은 endpoint/owner·TLS·scope를 검증하고 암호화 저장한다. upstream mutation은 없다. 키 backup 복원은 가능하지만 자동 키 교체, 이전 source/revision 복귀 버튼, 불명 발급의 강제 종료, 긴급 drain 우회는 제공하지 않는다. 운영 전환 전 복구·지원 범위를 검토해야 하며 전체 M1 완료로 간주하지 않는다.

과거 상세 ADR·API/DB 목록·단계별 기록은 [보관본](archive/README.md)에서 복원할 수 있다. 현재 문서는 여기와 PRD·개발 안내를 갱신하고, 별도 도메인·API·DB·ADR 문서를 관성적으로 추가하지 않는다.

### 전체 화면 TUI

`2026-09-18` client의 `terminal.py`는 curses 화면·키 입력·마스킹·제어문자 escape를, `tui.py`는 기존 Application을 호출하는 탐색 흐름을 담당한다. CLI JSON 출력·서버 API·session 저장·등록 확인 계약은 유지한다. 조회와 설치는 기존 동기식 호출이며 작업 중 표시를 제공한다. 주기적 자동 갱신이나 백그라운드 실행은 추가하지 않았다. 목록·상세·검색·저장된 연결 선택과 화면 내 입력을 제공하며 `q`는 session 폐기나 서비스 종료를 호출하지 않는다. [작업 기록](work/2026-09-18-fullscreen-tui.md)에 검증 범위를 기록한다.

### CLI 운영 명령

`2026-09-18` CLI 우선 흐름을 추가했다. `cli.py`는 명령/확인/종료 코드, `output.py`는 터미널 표·요약과 파이프/명시적 JSON, `workflows.py`는 기존 VM power/Create/Operation API 조합을 담당한다. 인자 없는 실행은 도움말이며 TUI는 명시적 `tui`다. memory `shell`은 동일 Application session 저장소를 공유하는 동기식 CLI 루프이고 OS 명령 실행기가 아니다. 기본 Keychain/SecretService 저장 계약은 유지한다.

CLI bootstrap은 설치·별칭 저장 후 로그인을 별도로 안내한다. VM 시작·정상 종료는 exact target과 요청 identity를 확인하며, 생성은 신규 0600 검토 파일의 원래 payload·서버 checksum·origin/profile identity를 사용한다. 서버 권한·승인·잠금·idempotency/recovery는 기존 계약을 재사용한다. 변경 POST 뒤 Operation GET의 성공 및 coordination 완료를 확인하고 결과 미확정/차단은 nonzero로 반환한다. 자동 mutation retry·보상이나 DB 변경은 없다. 자세한 명령·제약은 개발 안내, 검증 결과는 [CLI 작업 기록](work/2026-09-18-cli-workflows.md)에 둔다.

웹 VM 변경·템플릿 제작/정리의 결과 확인은 공통 `assertChangeResult`로 실행 응답과 canonical Operation의 ID·종류·VM target·node/VMID·전체 제출 내용을 대조한다. 복제/복원은 새 VMID를 결과 대상으로 사용한다. 다른 요청의 성공 또는 조정 미완료는 완료로 표시하지 않으며 요청 ID와 작업 조회 경로를 유지한다.

### 정지 VM CPU·메모리 계약

- operator 이상의 `GET /api/v1/nodes/{node_id}/vms/{vmid}/compute`는 현재 설정·digest를 검토한다. `POST /api/v1/nodes/{node_id}/vms/{vmid}/actions/compute`는 strict body `idempotency_key`, `expected_digest`, `expected_name`, `cores`, `memory_mib`를 받는다. 같은 요청 ID와 다른 의도는 409, 입력 오류 422, 권한 부족 403, 관찰/저장소 불가는 503이다.
- 단일 socket, cores 1~128, memory 128~1048576 MiB 범위다. vcpus/custom NUMA, pending 변경, template, lock, 실행 중 VM은 거부한다. 기존 balloon 최소값보다 작게 줄이지 않는다. digest는 PVE 동시 설정 변경 감지에 사용하며 skiplock은 허용하지 않는다.
- 현재 설정은 PVE config의 `current=1`로 읽는다. 기본 config GET은 pending 값을 포함할 수 있으므로 성공 근거로 사용하지 않는다. PUT config의 동기 null 응답을 확인하며 UPID 작업으로 취급하지 않는다. 직전·직후 정지 상태를 관찰하지만 PVE 외부의 동시 시작까지 원자적으로 차단하지는 못한다.
- `vm_compute` 결과·이력은 canonical Operation에 저장하고 새 Jobs/Artifacts 복제본을 만들지 않는다. 원자적 admission과 lease fence 이후 한 번만 dispatch한다. 동기 응답 완료 checkpoint와 직접 읽은 결과가 모두 있어야 succeeded·recovery completed·잠금 해제할 수 있다. 응답 유실은 값이 같더라도 paused로 보존하며 자동 재전송/강제 해제하지 않는다.
- 신규 migration `20260919_0031`은 기존 lock action check에 compute만 추가한다. 새 action 이력이 있으면 downgrade를 거부한다. 기존 이력·인덱스·다른 action의 target 직렬화는 보존한다. 잠금 삽입의 savepoint는 PostgreSQL 충돌 후에도 공유 admission transaction에서 정확한 owner를 읽을 수 있도록 한다.

### 정지 VM 디스크 확장 계약

`GET /api/v1/nodes/{node_id}/vms/{vmid}/disks/scsi0`와 `POST /api/v1/nodes/{node_id}/vms/{vmid}/actions/disk-resize`는 operator 이상이다. strict body는 idempotency_key·expected_digest·expected_name·expected_volume·expected_size_bytes·size_gib다. size_gib는 1~65536 정수이며 현재 실제 bytes보다 커야 한다. 선택 `disk` feature는 개별 VM의 `GjallarVmDiskV1`(VM.Config.Disk)과 선택 storage의 기존 Audit 및 `GjallarStorageAllocateV1`을 사용한다. grant 중복은 plan에서 제거한다.

`operations/vm_admission.py`는 compute/disk/network의 lock·Operation·recovery 최초 기록과 완료 직후 replay 경계를 공유한다. disk adapter는 PVE current config·pending·status, node storage, exact storage volume info를 읽는다. NFS·scsi0·자기 VMID의 raw/qcow2 volume과 실제 bytes를 제한적으로 지원하며 volume의 host 경로는 저장하지 않는다. config digest를 포함한 절대 크기 resize PUT 뒤 node/VMID/type이 일치하는 UPID만 Operation/recovery에 원자적으로 바인딩한다. foreground wait는 lease를 갱신하며 stale worker는 결과 commit·잠금 해제를 할 수 없다.

`vm_disk_observation`은 저장된 exact UPID의 GET과 실제 volume/config만 읽는다. 진행 중 task는 retry_wait, 실패·관찰 불가·값 불일치는 paused로 두며 mutation을 재실행하지 않는다. task stopped/OK와 동일 volume·기대 bytes·정지 상태가 맞아야 succeeded와 coordination 완료를 기록한다. UPID 없는 dispatching은 자동 성공 근거가 없으며 잠금을 보존한다. 새 migration `20260919_0032`는 lock action check만 추가하고 해당 action 이력이 있으면 downgrade를 거부한다. CPU·메모리와 disk의 결과는 canonical Operation에 남기며 기존 Jobs/Artifacts 이력은 보존한다.

### VM-03 기존 NIC bridge·VLAN 변경

operator 이상의 `GET /api/v1/nodes/{node_id}/vms/{vmid}/network`와 `POST /api/v1/nodes/{node_id}/vms/{vmid}/actions/network`를 제공한다. strict 요청은 idempotency_key·expected_digest·expected_name·expected_net0·bridge_id·vlan_tag(null 또는 1~4094)다. 정지 VM의 기존 net0만 지원하며 model/MAC와 모든 나머지 NIC 옵션을 보존한다. 추가 NIC·trunk·호스트 네트워크 변경은 이 경로에서 수행하지 않는다.

VM current config/pending/status와 node network를 직접 읽는다. PVE network 응답의 최상위 `changes`를 포함한 envelope를 보존하고 미적용 호스트 설정이 있으면 차단한다. managed 경로는 이때도 선택 bridge 필터를 적용한다. diff 본문은 Operation·응답에 넣지 않는다. Linux bridge의 관찰된 iface·type=bridge·active=1 및 SDN.Use를 확인하며 tag 지정에는 bridge_vlan_aware를 추가 요구한다. optional `exists`는 물리 장치 표시로 가상 bridge 필수 조건이 아니다. 호스트 설정과 VM 설정을 아우르는 원자적 PVE transaction은 없으므로 dispatch 전과 결과 확인에서 각각 검사하며, 외부 동시 변경이 있으면 미확정으로 남을 수 있다.

선택 `network`는 개별 VM에 GjallarVmNetworkV1(VM.Config.Network), 선택 bridge에 기존 GjallarBridgeReadV1/UseV1을 계획한다. 기존 token은 자동 확대하지 않는다. 기존 생성 대상도 network를 명시적으로 선택한 연결에서만 이 수정 경로를 사용할 수 있다.

`operations/vm_config.application.ConfigChangeService`는 compute/network의 원자적 admission·idempotency·동기 PUT 응답 근거·GET-only 검증을 공유한다. 기능별 domain과 adapter는 입력·관찰·비교를 소유한다. MAC/옵션을 포함한 기대 NIC 설정과 정지 상태가 일치하고 dispatch ack가 저장된 경우에만 성공·잠금 해제를 기록한다. 응답 유실은 값이 같아도 paused이며 mutation 재전송은 없다. `vm_network_observation`은 조회만 수행한다. 새 migration `20260919_0033`은 lock action에 vm_network만 추가하고 해당 이력이 있으면 downgrade를 거부한다. 결과 확인은 PVE NIC 설정의 확인이며 게스트 IP·라우팅·연결 성공을 보장하지 않는다.

### VM-04 정지 VM full clone

operator `GET /api/v1/nodes/{node_id}/vms/{vmid}/clone?new_vmid=...&storage_id=...`는 원본과 새 대상의 사용 가능 여부를 검토한다. `POST /api/v1/nodes/{node_id}/vms/{vmid}/actions/clone`은 idempotency_key·expected_digest·expected_name·expected_volume·expected_size_bytes·new_vmid·name·storage_id·guest_identity_acknowledged를 받는다. 첫 조합은 같은 node, 활성 NFS의 raw/qcow2 scsi0 한 개·net0 한 개와 선택적 ide2 cloud-init이다. 정지·onboot=0인 일반 VM만 지원한다. 추가 disk/NIC·passthrough·EFI/TPM·외부 ISO·custom cloud-init/script·custom CPU는 제한한다. 게스트 IP·hostname·SSH host key 등 내부 identity는 그대로 복제되며 시작하지 않는다.

선택 `clone`은 기존 vmids를 원본으로, 별도 clone_vmids를 새 대상으로 사용한다. 두 집합과 template/create target은 겹치지 않는다. 원본 GjallarVmCloneV2(Audit/Clone/Config.Disk), 새 대상 GjallarVmCloneTargetV2(Allocate/Audit/Config.Disk), 선택 storage Audit/AllocateSpace, bridge Audit/Use를 계획한다. 복제 대상에 power·guest-exec 권한을 자동 부여하지 않는다. 관리형 조회는 선택 ID를 유지하면서 다른 노드의 동일 ID·LXC 점유도 감지한다. 불명확한 resource 목록을 빈 목록으로 해석하지 않는다.

`vm_admission`은 vm_clone·vm_restore의 원본과 대상 두 lock을 VMID 순으로 같은 transaction에서 확보한다. canonical target은 복제본이고 source는 별도 details에 기록한다. Operation/recovery의 동일한 related_target_locks와 각 lock의 owner/type/cluster/VMID를 확인한다. recovery commit은 두 잠금을 함께 전환·해제하며 일부 유실·binding 불일치 시 성공을 금지한다. 한 대상 작업은 기존 contract를 유지한다. 0034 migration은 action check만 추가하고 vm_clone 이력이 있으면 downgrade를 거부한다.

`vm_config.task_application.TaskChangeService`는 disk/clone의 단일 비동기 dispatch·UPID checkpoint·lease heartbeat·GET-only 검증을 공유한다. full=1·원본 형식·선택 storage로 복제하며 PVE가 반환한 qmclone UPID는 **원본 VMID**와 node/type을 검사한다. 복제본 description에는 Operation ID를 넣고 원본 description은 유지한다. PVE clone은 digest 인자를 지원하지 않으므로 dispatch 직전 source digest를 재검증하고 task 완료 뒤 원본 digest·volume·주요 설정 보존, 복제본 marker/name/VMID/정지 상태, 독립 소유 volume의 실제 bytes, 새로운 MAC/SMBIOS UUID와 주요 설정을 확인한다. 원본의 외부 동시 변경과 원자적 compare-and-clone은 보장하지 않는다. 값이 맞아도 저장된 UPID와 task stopped/OK가 없으면 성공 처리하지 않는다. 실패·응답 유실·잔여 자원은 자동 재복제/삭제 없이 두 잠금과 미확정 상태를 유지한다.

### VM-05 정지 VM 전체 삭제

operator `GET /api/v1/nodes/{node_id}/vms/{vmid}/deletion`은 삭제·보존 manifest를 조회한다. `POST /api/v1/nodes/{node_id}/vms/{vmid}/actions/delete`는 idempotency_key·expected_digest·expected_name·expected_resources_digest·confirmation·delete_acknowledged를 받는다. confirmation은 정확한 `VMID/이름`, acknowledgement는 true여야 한다. 정지·일반·미보호 VM의 선택 NFS raw/qcow2 scsi0와 선택 ide2 cloud-init만 지원한다. snapshot·pending·lock·추가/unused disk·공유/타 VM volume·외부 ISO·passthrough·EFI/TPM·custom script는 차단한다.

`operations/vm_delete`는 VM·snapshot·storage content·exact volume info와 VM.Audit/Allocate·Datastore.Audit/Allocate를 검토한다. 선택 `delete` feature는 정확한 기존 VM에 GjallarVmDeleteV1(VM.Allocate)을 추가한다. GjallarVmDeleteStorageV1(Datastore.Allocate)을 선택 storage에 추가한다. PVE는 VM 삭제 시 VM ACL도 지워 이후 Config.Disk 기반 volume 목록이 숨겨질 수 있으므로, 삭제 전후 storage Allocate를 확인해야 빈 목록을 부재 근거로 쓸 수 있다. 이 PVE 권한은 storage 설정/다른 내용 삭제까지 가능하므로 등록 검토에 명시하며 Gjallar의 storage 변경 allowlist는 확대하지 않는다. PVE token 자체의 VM.Allocate 권한은 삭제보다 넓지만 Gjallar managed transport는 선택 대상의 `DELETE`와 고정 `purge=0,destroy-unreferenced-disks=0`만 이 feature로 허용한다. 기존 연결은 새 등록·검증·전환·재시작을 거쳐야 한다.

원자적 admission·TaskChangeService·vm_delete_observation을 공유하며 정확한 qmdestroy UPID의 task stopped/OK 이후에만 삭제 결과를 관찰한다. VM 전용 ACL/firewall이 함께 삭제되므로 VM GET 오류는 부재 증거가 아니다. GET `/cluster/nextid?vmid=<exact ID>`가 정확한 ID(int 또는 canonical 숫자 문자열)를 반환하고, 해당 storage/images/VMID 목록에서 승인된 volume 부재와 검토된 미참조 volume 보존을 확인해야 succeeded다. 불명확한 목록·조회 불가·VMID 재사용·잔여 volume·보존 자원 불일치는 paused와 잠금 유지다. task 실패는 삭제를 확정하지 않으며 운영자가 잔여 자원을 조사해야 한다. mutation 재시도·잔여물 자동 삭제는 없다.

PVE DELETE에는 digest 조건부 인자가 없으므로 최초 dispatch 직전 상태·manifest를 재검증하더라도 외부 관리자와의 원자적 compare-and-delete는 보장하지 않는다. 실행 승인 범위는 해당 VM과 그 소유의 연결 자원 전체다. 동시 외부 변경을 중지해야 하며 PVE가 실제 사용/소유 자원·보호·전원·HA/replication 조건을 최종 검사한다. backup·미참조 disk·외부 backup job 설정을 지우지 않는다. 자동 역연산은 없다. 0035는 lock action check만 확장하고 vm_delete 이력이 있으면 downgrade를 거부한다. 웹 완료 화면은 삭제 전 상태와 작업 버튼을 제거하고 삭제·보존 근거 및 Operation을 표시한다.

2026-09-20 실제 검증에서는 승인된 수동 취소로 옛 미확정 삭제 이력을 보존하고, 새 Operation의 정상 삭제·정확한 소유 2개 volume 및 VMID 부재·원본 7001 보존을 확인했다. 이는 일반 자동 잠금 해제나 미확정 mutation 재전송 기능을 추가한 것이 아니다. 구체적 승인·백업·fencing 근거는 현재 work에 기록한다.

### VM-06 인증된 웹 화면 콘솔

operator `GET /api/v1/nodes/{node_id}/vms/{vmid}/console`은 화면 VM의 상태·Console/Audit 권한과 입력 영향을 검토한다. `/api/v1/nodes/{node_id}/vms/{vmid}/console/socket` WebSocket은 기존 Gjallar HttpOnly cookie를 서버 세션으로 재검증하고 정확한 허용 Origin을 요구한다. query parameter·viewer·만료/폐기/비활성 session은 거부한다. HTTP dependency를 WebSocket에 억지 적용하지 않고 별도 명시적 upgrade 인증 경계를 둔다. 실행 중인 일반 QEMU 화면 VM만 지원하며 serial-only/none VGA·정지 VM·template은 거부하고 자동 시작하지 않는다.

선택 `console`은 기존 vmids에 GjallarVmConsoleV1(VM.Console)을 추가한다. 생성/복제 미래 ID에는 묵시적으로 부여하지 않으므로 필요하면 생성 이후 기존 VM 범위로 등록·검증·전환한다. console_selection은 기존 credential pin·admission·node/VM scope를 확인하며 연결 전환 중/재시작 필요 상태를 차단한다.

`console.infrastructure`는 검증한 PVE origin·CA/hostname·고정 DNS 주소에 연결한다. HTTP/환경변수 proxy·redirect·TLS 검증 생략을 콘솔에서 허용하지 않는다. PVE vncproxy POST는 접속 시 한 번만 호출하며 응답의 port/ticket/password를 엄격히 확인한다. token/ticket은 서버→PVE 인증과 WSS query에만 사용한다. 서버의 WS 초기 ready 메시지에 임시 RFB password를 넣고 noVNC 연결 메모리에서만 사용한다. 브라우저 URL·localStorage·DB·Operation에 비밀정보를 남기지 않는다. upstream protocol logger는 wire 내용을 출력하지 않고 Uvicorn WebSocket DEBUG의 raw header/frame도 필터로 대체한다. 외부 reverse proxy는 cookie/header/frame 본문을 로그로 수집하지 않아야 한다.

`console.gateway`는 process별 전체 32개/사용자 2개로 제한하고 최대 15분 뒤 종료한다. 5초 주기로 Gjallar 로그인·역할과 현재 연결 scope/pin을 다시 확인한다. max frame·queue·send chunk를 제한하고 클라이언트 이탈·서버 오류·만료·취소 시 양쪽 연결과 slot을 정리한다. 재시작 시 콘솔은 종료되며 자동 재연결하지 않는다. VM config 변경이나 background recovery 업무가 아니므로 durable target lock·Operation·신규 DB schema는 만들지 않는다. 게스트 입력은 상태를 바꿀 수 있으나 입력 내용/화면은 기록하지 않는다.

웹 VM 상세는 noVNC 1.7.0을 연결 시 lazy load해 기존 대시보드 bundle을 유지한다. RFB handshake 완료 전에는 연결 중으로 표시하고 오류·종료 후에는 직접 준비/연결을 요구한다. 클립보드 자동 공유·전원 제어·호스트 shell은 제공하지 않는다. CLI는 같은 검토 API와 웹 상세의 console anchor를 안내하며 cookie나 임시 PVE credential을 브라우저에 넘기지 않는다.

PVE의 port는 정수 또는 5900~5999의 ASCII decimal 문자열을 허용하고 후자는 정수로 정규화한다. 범위외·공백·bool·float는 거부하며 ticket/password 검증은 유지한다. 브라우저 disconnect를 받은 뒤 서버가 중복 close를 보내지 않는다. 2026-09-20 PVE 9.0.11/기존 token 관리형 연결에서 실제7001의 RFB handshake·화면·명시적 종료를 확인했다. 화면은 게스트 display 미초기화 안내였으며 OS 로그인·게스트 입력 검증은 하지 않았다. 권한 거부·만료 검사는 자동 검증과 구분한다.

계약 근거는 [PVE QEMU API source](https://git.proxmox.com/?p=qemu-server.git;a=blob;f=src/PVE/API2/Qemu.pm), [PVE HTTP server source](https://git.proxmox.com/?p=pve-http-server.git;a=blob;f=src/PVE/APIServer/AnyEvent.pm), [noVNC RFB API](https://novnc.com/noVNC/docs/API.html)다.

### TPL-01 준비된 VM의 템플릿 전환

operator `GET /api/v1/nodes/{node_id}/vms/{vmid}/template-conversion`은 정지 VM의 준비 조건과 volume을 검토한다. `POST /api/v1/nodes/{node_id}/vms/{vmid}/actions/template`은 idempotency_key·expected_digest·expected_name·expected_resources_digest·confirmation·guest_prepared·conversion_acknowledged를 받는다. 정확한 VMID/이름과 두 확인이 필요하다. 첫 조합은 NFS의 자기 소유 raw/qcow2 scsi0, ide2 cloud-init, guest agent 활성 설정이다. 추가 disk·unused·snapshot·pending·lock·외부 장치/스크립트·EFI/TPM은 제외한다.

`operations/vm_template`는 VM.Audit/Allocate/Config.Disk와 storage Audit, 현재 config/status/pending/snapshot 및 exact volume의 bytes/format을 확인한다. 선택 template feature는 기존 vmids에 GjallarVmTemplateV2(VM.Allocate/Config.Disk)을 추가한다. PVE 권한 자체는 전환보다 넓지만 managed transport는 선택 VM의 빈 body 전체 template POST만 허용한다. 부분 disk 변환·skiplock은 없다. 기존 연결·role은 자동 확대하지 않으며 전환된 VM을 생성용 template_vmids로 사용하는 것도 명시적 새 등록·검증·전환을 요구한다.

단일 VM admission·TaskChangeService·vm_template_observation을 사용한다. qmtemplate UPID의 exact node/VMID/type과 task stopped/OK, 정지 template flag, 같은 이름, scsi0 base image와 유지된 cloud-init의 실제 bytes/format, 나머지 config fingerprint 보존을 함께 확인한다. 원문 config·키·비밀번호는 이력에 저장하지 않는다. fingerprint는 digest/template flag와 전환 root volume 이름만 제외하고 drive 옵션 순서를 정규화한다. 게스트 준비 확인은 operator attestation이며 실제 부팅/cloud-init/네트워크/접속 검증과 구분한다.

PVE API에는 digest 조건부 인자가 없으며 flag 또는 일부 volume을 바꾼 뒤 실패할 수 있다. dispatch 직전 재검토하되 외부 동시 변경의 원자적 차단은 보장하지 않는다. 실패/유실/부분 전환은 paused와 잠금 유지이며 재전환·역변환하지 않는다. 복구는 GET만 수행한다. 0036 migration은 lock action만 추가하고 이력이 있으면 downgrade를 거부한다. 웹 완료 화면은 원본 부팅/변경 버튼 대신 실제 volume 결과, Operation과 생성 권한 갱신·테스트 배포 안내를 표시한다.

외부 동작의 근거는 [PVE template API](https://github.com/proxmox/qemu-server/blob/master/src/PVE/API2/Qemu.pm)와 [template_create](https://github.com/proxmox/qemu-server/blob/master/src/PVE/QemuServer.pm)다. 조사한 upstream과 실제 PVE 9.0.11 조합의 실환경 검증은 구분한다.

### TPL-02 고정 공식 이미지 제작

첫 catalog는 서명을 검토한 AlmaLinux 9.8 GenericCloud x86_64의 날짜 고정 qcow2다. `cloud_images`는 URL·SHA-256·배포 bytes·virtual bytes·검토 지문을 제공한다. runtime은 해당 HTTPS 출처만 DNS public IP 고정·TLS 검증·redirect/proxy 금지로 내려받고 exact bytes/hash와 backing/encryption/snapshot 없는 qcow2 header를 확인한다. 0600 익명 임시 파일은 context 종료/프로세스 종료 시 닫히며 동시 2개·600초·heartbeat로 제한한다. 임의 URL/파일/host shell은 입력받지 않는다.

관리형 image_build는 다른 VM scope와 겹치지 않는 image_vmids, 선택 import dir/NFS staging·NFS images target·Linux bridge를 요구한다. GjallarImageBuildV1은 새 VM Allocate/Audit와 CPU/Memory/HWType/Options/Disk/Network, GjallarImageUploadV1은 storage AllocateTemplate을 부여한다. 기존 storage Audit/AllocateSpace·bridge Audit/Use와 합치며 루트 Sys.Modify/SSH를 요구하지 않는다. role/token의 자동 확대 없이 새 등록·검증·전환·전체 프로세스 재시작을 사용한다.

`GET /api/v1/templates/cloud-images`, `GET /api/v1/nodes/{node_id}/vms/{vmid}/image-build`와 `POST .../actions/image-build`는 operator 이상이다. GET은 image_id/name/storage_id/staging_storage_id/bridge_id를 받아 미래 VMID 부재와 권한·content·공간·bridge 조건을 검토한다. POST는 해당 입력과 idempotency_key, expected_review_digest, 정확한 VMID/name confirmation, image_build_acknowledged를 요구한다. 변경 전 snapshot은 자격 조건의 stable digest이며 용량을 예약하지 않는다.

`vm_image_build` Operation은 upload(imgcopy, 빈 VMID) → import(qmcreate, 새 VMID) → conversion(qmtemplate, 같은 VMID)의 각 dispatch/UPID/task/실제 관찰을 저장한다. recovery ledger에도 stage/dispatch state/UPID/stages digest를 같은 transaction에 기록한다. 새 0037은 해당 VM lock action만 확장하며 기존 이력을 보존하고 사용 이력 downgrade를 거부한다. 복구는 GET-only이고 중간 완료 뒤 남은 mutation은 자동 시작하지 않는다. 단일 요청 반복은 원래 Operation을 반환하며 진행 중 admission 경합은 busy로 거부할 수 있다.

최종 성공은 검증한 원본 hash·업로드/생성 완료 근거와 실제 정지 template/base volume·고정 설정/소유 Operation description을 모두 확인해야 한다. guest boot/cloud-init/network/접속 검증은 별도다. 원본 staging은 성공 후에도 보존되며 아래 명시적 소유 자원 정리 흐름으로 제거한다. 실제 PVE 제작·정리 검증도 별도 승인 대기다. 웹 `/instances/templates/build`와 CLI `vm image-build catalog/show/plan/execute`는 검토·명시적 실행·canonical Operation 결과를 사용한다.

### TPL-02 제작 소유 template·원본 정리

`operations/vm_image_cleanup`는 성공한 vm_image_build와 completed recovery, 같은 cluster/node/VMID, 고정 source integrity와 제작 template 증거를 요구한다. `GET /api/v1/nodes/{node_id}/vms/{vmid}/image-cleanup`은 parent_operation_id와 resource(template/source)를 받아 삭제·보존 manifest를 제공한다. `POST .../actions/image-cleanup`은 그 값과 expected_name/expected_review_digest/idempotency_key, 정확한 `VMID/name/resource` confirmation, cleanup_acknowledged를 요구한다. 두 자원은 별도 요청이며 자동 연쇄 삭제하지 않는다.

image_cleanup은 기존 vmids와 선택 storages의 명시적 부분집합인 image_cleanup_storages를 사용한다. VM은 GjallarImageCleanupV1(Allocate/Audit), 정리 storage만 GjallarImageCleanupStorageV1(Datastore.Allocate)다. 이 PVE 권한은 storage 설정·다른 내용 삭제까지 가능하므로 등록 화면·CLI에서 밝힌다. 관리형 transport는 전용 import 파일 또는 정확한 VM의 고정 DELETE만 허용한다. 기존 image_build는 정리 권한을 자동 얻지 않는다. 제작이 끝난 VMID를 미래 image_vmids에서 기존 vmids로 옮겨 새 연결을 등록·검증·전환한다.

template는 보호/lock/pending/snapshot 없는 정지 상태·원래 description/config fingerprint/volume manifest를 확인한다. 선택 NFS storage Allocate 권한으로 전체 images 목록을 관찰하되 선택 base의 parent reference 개수만 반환한다. linked clone이 있으면 차단한다. qmdestroy 성공 뒤 VMID 미사용·승인 disk 부재·미참조 disk 보존을 확인한다. PVE가 VM ACL을 제거한 뒤에도 storage Allocate로 누락 없는 volume 목록을 관찰한다. source는 부모 Operation의 정확한 전용 파일명·현재 qcow2/virtual bytes를 검토하며 imgdel의 storage binding과 파일 부재를 확인한다. 현재 원격 파일의 hash 재계산 API는 없으므로 provenance hash와 현재 size/format 관찰을 구분하고 외부 staging 변경을 금지한다.

0038은 vm_image_cleanup lock action만 추가하며 이력 downgrade를 거부한다. 공통 TaskChangeService·단일 VMID admission·UPID 기록·GET-only recovery·lease fence를 재사용한다. 미확정 제작 잠금을 강제로 해제하거나 실패한 삭제를 자동 재실행하지 않는다. 웹 `/instances/templates/cleanup`, CLI `vm image-cleanup show/plan/execute`는 제작 Operation과 resource를 보존한다. 실제 PVE 삭제 검증은 별도 승인 대기다.

### 템플릿 테스트 배포 검사 (TPL-03)

- 테스트 VM 생성은 기존 template `vm_create`의 검토·승인·`boot_and_verify`를 재사용한다. 신규 생성 Operation에는 `template_source`의 node/VMID와 `power_policy`만 추가 기록한다. 과거 Operation을 추정 보완하거나 재작성하지 않는다.
- `GET /api/v1/operations/{operation_id}/template-test`는 인증된 viewer가 읽는 역사적 보고서다. 정확한 managed VM 생성 대상만 허용하고 생성 관찰의 running/cloud-init/guest agent/IP 항목을 접속 증거와 구분한다. 생성만(`stopped`) 선택은 `not_run`, 증거 누락은 `unavailable`, false 검사는 `not_verified`다. IP 관찰은 외부 네트워크·SSH 성공을 뜻하지 않는다. 조회에서 PVE/게스트 명령·현재 상태 관찰을 실행하지 않는다.
- 접속 결과는 기존 operator `post-create-readiness-evidence` API와 동일한 actor·artifact·멱등 기록·정확한 성공 Create 연결을 사용한다. 웹/CLI는 `access` 하나의 passed/failed/not_run/unavailable만 보내며 비밀·자유형 명령·출력을 수집하지 않는다. 보고서는 연결된 증거의 Operation ID·node/VMID·artifact ID/checksum을 검사하고 다른 대상의 기록을 채택하지 않는다. 웹/CLI도 조회 report의 작업·대상을 대조하고, 기록 응답의 access 상태·시각·artifact ID/checksum이 재조회 report에 연결된 경우에만 기록 확인을 표시한다. 명시적 idempotent replay는 새 입력으로 원래 증거를 덮어쓰지 않고 원래 상태·시각을 대조하며 기존 기록임을 표시한다. 조정 미완료나 생성 미성공을 전체 검사 성공으로 승격하지 않는다.
- 웹 `/instances/templates/tests/:operationId`는 생성 작업 상세에서 진입한다. 제작/전환 결과는 원본 식별자를 가진 `/instances/create?template_node=...&template_vmid=...`로 연결하며 조회되지 않는 원본을 다른 템플릿으로 자동 대체하지 않는다. 생성 원본·새 VMID·create/power/guest-agent 및 삭제 storage 권한은 명시적 관리형 연결 갱신이 필요하다.
- 정리는 보고서에서 현재 VM 상세로 이동해 정상 종료와 VM-05 삭제 검토를 각각 수행한다. 동일 VMID 재사용 위험 때문에 역사적 검사만으로 삭제 대상 소유를 확정하지 않는다. 실제 삭제 완료 증거는 별도 삭제 Operation에 남으며 테스트 결과는 보존한다. 템플릿/업로드 원본 정리는 TPL-02의 독립 경로다. 새로운 schema·executor·자동 삭제는 없다.

### 현재 사용량과 PVE 이력 (OBS-01~02)

- `GET /api/v1/monitoring/nodes/{node_id}`, 하위 `/vms/{vmid}`, `/storage/{storage_id}`는 인증된 viewer 조회다. timeframe은 hour/day/week/month/year, aggregation은 AVERAGE만 허용한다. 현재 status와 RRD를 독립 조회하고 source·수신 시각·실제 sample 시각/범위·해상도·지표별 결측과 최신 여부를 반환한다. 요청 실패를 0이나 정상으로 대체하지 않는다.
- 관리형 transport는 기존 selected node/VM/storage와 read 권한만 사용한다. RRD 고정 query와 storage status를 허용하되 미선택 자원·임의 query·mutation은 거부한다. env 연결도 동일 domain 정규화를 거친다. 관리형 연결 실패 시 env 자동 fallback은 없다.
- node CPU/메모리/네트워크, QEMU VM CPU/메모리/네트워크/disk IO, storage 사용/전체 bytes를 지원한다. CPU는 0~1 fraction을 percent로 변환한다. RRD network/disk IO는 bytes/s이며 현재 status 누적 카운터는 rate로 사용하지 않는다. 정지 VM 현재 CPU/사용 메모리는 null, 구성 메모리 한도는 별도 관찰값이다.
- 응답은 10,000개 이하 정렬된 고유 정수 timestamp만 허용한다. 비정상 숫자·없는 metric은 null이다. 해상도는 실제 timestamp 간격이 일정할 때만 고정 숫자로 반환한다. 지표별 마지막 실제 값이 두 sample 간격+60초보다 오래되거나 간격/값이 없으면 최신 여부 미확인이다. 요청 기간 전체 보존을 보장하지 않는다.
- 웹 `/insights/metrics`는 실제 관찰 범위·단절된 차트·시각 선택·최근 20개 표를 제공하고 VM 상세와 연결한다. 현재 관찰값만 카드로 표시하고 미관찰 지표는 이름을 모아 안내하며 0과 결측을 구분한다. 모바일 차트는 높이와 축 텍스트를 확보하고 결측 segment는 유지한다. CLI `metrics node/vm/storage`는 같은 보고서를 반환한다. 기존 TUI는 유지한다. 웹은 승인된 공통 탐색·스타일 개편을 따른다. 수집기·스케줄러·TSDB·외부 알림은 추가하지 않았다.

### M4 임계 상태·실패/복구 이력

`monitoring/thresholds.py`는 정규화된 PVE AVERAGE 이력에서 CPU/메모리 70/85%, storage 80/90%의 주의/위험 구간을 계산한다. 연속 초과는 한 구간으로 합치고 최고 심각도와 최대 20개 변화만 보존한다. null·stale·불규칙 간격은 정상 또는 해제를 증명하지 않는다. 이후 실제 정상 표본으로만 관찰된 해제를 표시한다. 구간 첫 초과의 이전 상태가 없으면 발생 시각이 불확실함을 표시한다. 대상·규칙 버전·최초 초과 표본으로 ID를 만들고 최근 100개 구간, 전체 개수·잘림 여부를 반환한다. 별도 수집기·알림 DB·불변 보존은 없다. PVE의 보존/재집계 범위와 평균 사이 순간 초과의 한계를 그대로 표시한다.

GET `/api/v1/monitoring/operation-alerts?limit=20`은 viewer가 최신 1~50개 Operation과 각 append-only event를 읽는 보고서다. `failed/needs_reconciliation` 연속 구간을 합치고 이후 `succeeded`를 해제로 표시한다. 조정 미완료는 재확인 필요로 남긴다. 사전 blocked/rejected는 실행 실패가 아니다. 최근 실패 구간 최대 100개·전체 개수·잘림·개별 조회 실패를 반환한다. 외부 mutation·기록 변경·자동 복구·메시지 발송을 하지 않는다. raw event payload·오류 메시지·명령 출력은 보고서에 복사하지 않는다. 연결 등록/폐기 Operation도 조회 대상에 포함한다. `proxmox_connection`은 별도 connection transaction으로 직렬화하므로 공통 상세 조회에서 VM/host durable target lock을 찾지 않는다. VM locator 검증과 실제 lock 취득·해제는 그대로 유지한다.

웹 `/insights/metrics`의 임계 이력과 `/insights/alerts`의 작업 실패/복구·원본 작업 링크, CLI `metrics`·`alerts`가 같은 보고서를 사용한다. 기존 TUI는 유지하며 웹은 공통 UI 개편을 따른다. 자동·격리 화면 검증 및 env PVE 읽기 protocol 검증에 더해, 설치된 관리형 서버에서 node yoonmanserver3·VM 7001의 현재/1시간 이력과 작업 알림을 실제 웹·CLI로 확인했다. 이어서 VM/node의 day/week/month/year를 실제 CLI로 조회하고 동일 timestamp의 직접 PVE RRD와 CPU·메모리·network 및 VM disk rate 값·결측·단위를 대조했다. 웹 VM year/node month와 모바일 결측 표시도 확인했다. 요청 기간 전체의 원천 보존을 보장하지 않으며 storage와 실제 초과/해제 사례의 실환경 검증은 남아 있다.

### M5 BAK-01 명시적 백업

`backups/`는 지원 archive와 원본 VM·PVE 요청 정책을, `operations/vm_backup/`는 검토→동일 VMID admission→단일 vzdump task→결과 검증을 담당한다. 첫 지원은 정지·일반 QEMU VM, 잠금/대기 변경/snapshot/외부 장치·hook 없는 scsi0와 ide2 cloud-init, 활성 NFS images/backup storage다. source volume 소유·가상 크기는 config metadata로 확인하고 원본 config fingerprint만 저장한다. 비밀번호·공개키·기본 mailto/script 원문은 Operation에 저장하지 않는다. 실제 disk 내용 보존·archive 무결성은 복원 검증의 별도 대상이다.

관리형 opt-in `backup`은 기존 `vmids`, 명시적 `backup_storages`(storages subset)에만 적용한다. VM.Backup, backup storage Datastore.AllocateSpace와 기존 Audit 권한을 사용한다. `GjallarVmBackupV1`을 추가하며 기존 역할을 변경하지 않는다. 신규 연결/갱신 plan v13을 검토·적용한 뒤 모든 Gjallar 서비스를 재시작하는 기존 절차를 따른다. 환경변수 fallback은 없다. source disk 조회를 위한 Config.Disk·삭제용 Datastore.Allocate는 추가하지 않는다.

GET `/nodes/{node}/vms/{vmid}/backups?storage=...`는 viewer 목록, GET `.../backup-review?storage=...`·POST `.../actions/backup`은 operator 검토/실행이다. 실제 경로는 `/api/v1` 아래다. 검토 digest는 config·기존 archive·defaults를 포함하며 free space는 매번 재검사한다. 한 archive 목록은 최대 10000개를 허용하고 불완전/잘못된 소유·시점·크기 응답은 거절한다. 여유 공간은 root 가상 크기 + max(1 GiB, 10%)를 요구하지만 예약이나 압축률 보장은 아니다.

PVE POST는 한 VMID, snapshot mode, zstd, remove=0/all=0/stop=0, fleecing off, lockwait=0, legacy-sendmail/빈 mailto, exact Operation notes-template만 허용한다. defaults는 Sys.Audit로 조회하고 host script가 있으면 거부한다. 요청 이후 외부 설정 변경을 PVE digest로 잠글 수는 없으므로 동시 관리를 중지해야 한다. 기존 backup·보존 정책·외부 알림은 이 요청에서 변경하지 않는다.

0039는 lock action에 `vm_backup`만 추가하며 이력 존재 시 downgrade를 거부한다. `vm_backup_observation`은 task node/type/VMID를 검증하고 GET으로만 결과를 확인한다. task OK + 정확한 Operation marker의 단일 신규 양수 크기 archive + 원본 설정/정지/volume metadata와 기존 archive 보존이 확인돼야 성공이다. 응답 유실·task 실패·부분 결과는 잠금을 유지한 needs_reconciliation이며 자동 재백업/삭제하지 않는다. archive 성공은 restore_verified=false다.

웹 `/instances/:vmid/backups`는 VM 상세에서 연결하고 CLI `vm backup list/plan/execute`는 같은 보고서/Operation을 쓴다. 웹과 CLI는 canonical Operation ID를 실행 응답과 대조하며 백업은 type/node/VMID/전체 제출 payload도 확인한다. 실제 PVE 생성·restore 검증은 별도 승인 대기다.

### M5 BAK-02 별도 VMID 격리 복원·검사

`backups/archive.py`는 선택 NFS VMA archive config를 메모리에서 검사하고 원문 대신 fingerprint·허용 장치·가상 용량만 반환한다. 첫 지원은 동일 node, 기존 정지 원본 VM, SeaBIOS scsi0 + ide2 cloud-init, VLAN/trunk 없는 단일 virtio net0다. snapshot/PENDING/외부 hook/host 장치/미지원 key·중복 key와 root mapping 모순을 거부한다. config/파일 metadata 비교는 archive disk 전체 hash 검증이 아니다.

`operations/vm_restore/`는 원본/백업·새 미사용 VMID·NFS images storage·활성 Linux bridge의 검토→정렬된 두 VM 잠금 admission→단일 qmrestore→GET-only 결과 확인을 소유한다. VMID 부재는 필터된 inventory가 아니라 PVE nextid로 확인한다. 검토 digest에 원본 config/volume metadata·archive 파일/config·목적지/bridge를 묶고 최초 dispatch 직전 재검증한다. 저장소 가용 공간은 변동하므로 digest 대신 매번 최소 용량을 확인한다. PVE에 VMID/공간을 예약하거나 archive compare-and-swap을 제공하지 않으므로 외부 동시 변경 중지가 필요하다.

POST `/nodes/{node}/qemu`는 정확한 archive/new VMID/name/storage와 Operation description, 새 local MAC·선택 bridge·link_down=1의 net0를 지정하고 force=0/unique=1/start=0/live-restore=0/onboot=0으로 고정한다. 게스트 IP·hostname·SSH key는 복사되므로 NIC를 연결하지 않는다. MAC은 재시도 의도에 안정적이며 원본과 다르지만 전역 유일성을 주장하지 않는다. 복원 완료에는 정확한 node/qmrestore/new VMID task OK, 원본·archive 보존, target 이름/Operation marker/정지/onboot off, 새 SMBIOS/VM generation identity(원본에 존재한 경우), hardware·소유 NFS volume의 실제 크기/형식과 NIC 격리가 필요하다.

관리형 `restore`와 `restore_vmids`·`restore_storages`를 선택한다. future VMID는 모든 기존/생성/clone/image 범위와 분리한다. `backup_storages`는 backup 또는 restore에 필요한 명시적 subset이다. 기존 원본 VM.Audit/Backup, source backup storage Audit/AllocateSpace, destination VM Allocate/Audit/Config.Disk/PowerMgmt/GuestAgent.Audit, destination storage Audit/AllocateSpace, bridge SDN.Use, node Sys.Audit를 사용한다. Config.Disk는 실제 volume 조회에 필요하며 Gjallar는 복원 대상의 임의 disk 변경을 허용하지 않는다. 계획 version은 v14이며 기존 연결 등록/검증/전환/재시작으로만 갱신한다. 운영 권한은 자동 확대하지 않는다.

0040은 `operation_locks` action에 vm_restore만 추가하고 이력 존재 시 downgrade를 거부한다. `vm_restore_observation`은 source/target binding이 양쪽 이력과 잠금에 같아야 진행·해제한다. 불명/실패/부분 결과는 두 잠금을 유지하며 재복원·자동 부팅·삭제하지 않는다. 원래 Operation의 GET-only 관찰만 재개한다.

공개 API는 operator의 `GET /api/v1/nodes/{node_id}/vms/{vmid}/restore-review`와 `POST .../actions/restore`, viewer의 `GET /api/v1/operations/{operation_id}/restore-report`다. 복원 Operation의 target은 새 VMID이고 source는 별도 기록한다. 웹 `/instances/:vmid/restore`·`/instances/restore-tests/:operationId`, CLI `vm restore plan/execute/report`는 canonical Operation ID/type/node/new VMID/전체 제출 payload를 대조한다. 보고서는 성공한 정확한 복원 Operation에 대해 현재 원본·archive·target과 격리/전원/agent를 개별 조회한다. QEMU running, agent 응답, 외부 접속 성공은 구분하고 외부 접속은 미검증으로 표시한다. 새 부팅은 기존 Start, 정상 종료는 Shutdown에서 별도 실행한다. 검사 보고서 자체는 조회 전용이며 DB schema·보고서 보존·자동 정리 흐름을 추가하지 않는다.


### M6 OPS-01 정지 VM 노드 이동

`operations/vm_migrate/`는 VM·노드·공유 자원 검토와 단일 PVE 이동 task·GET-only 복구를 소유한다. 첫 지원은 같은 cluster의 다른 online node, 동일 PVE 9 version/build·CPU model, 동일 ID의 활성 shared NFS images storage, 동일 이름의 활성 Linux bridge다. VM은 정지/onboot=0·비HA 일반 QEMU, SeaBIOS·scsi0 + ide2 cloud-init·VLAN/trunk 없는 단일 virtio net0다. local disk·storage remap·snapshot/pending/lock·외부 장치·custom CPU·HA·live/강제 이동은 거부한다. bridge 이름 일치와 CPU model 일치는 실제 L2 연결·부팅 성공 보장이 아니다.

관리형 opt-in `migrate`는 기존 선택 VMID, 최소 두 node, storage/bridge 범위를 사용한다. `GjallarVmMigrateV1`의 VM.Migrate/Config.Disk, bridge SDN.Use와 기존 VM.Audit/node Sys.Audit/storage Audit가 필요하다. Config.Disk는 양쪽의 실제 volume 크기/형식 조회에 필요하다. 공간 할당·host 수정·전원 권한은 추가하지 않는다. 신규 계획 version은 v15이며 기존 등록→검증→전환→전체 process 재시작으로만 갱신한다. 기존 연결이 자동으로 확장되지는 않는다.

검토 digest는 config fingerprint·실제 volume·원본/목적 환경·PVE migrate precondition을 포함한다. 양쪽에서 실제 같은 shared volume의 크기/형식을 읽고, PVE allowed_nodes·running/local/mapped/HA dependent resources를 확인한다. POST는 정확한 원본 node/VMID와 target, online=0, with-local-disks=0, force=0만 허용한다. root 전용 migration_type/network override·raw shell을 도입하지 않으며 PVE의 이동 transport/cluster 정책을 따른다. 최초 dispatch 직전 재검토하되 외부 동시 변경을 완전히 잠근다고 주장하지 않는다.

`vm_migrate`는 기존 cluster+VMID 단일 admission·idempotency·lease를 사용한다. canonical target은 같은 VMID와 **원본 node**(task 조회 위치)이고 destination은 별도 details다. 신규 0041은 lock action check만 추가하며 이력 존재 시 downgrade를 거부한다. 성공은 정확한 source-node qmigrate/VMID task OK, cluster index의 단일 VM이 목적 node에 있음, 목적 VM의 설정/identity·disk 크기/형식·NIC와 환경 보존·정지/onboot=0을 함께 요구한다. PVE config digest 자체의 이동 후 변경은 허용하되 실제 config fingerprint는 동일해야 한다. `vm_migrate_observation`은 GET-only로 관찰하며 불명/부분 실패 때 잠금을 유지하고 자동 재이동·역이동·부팅·삭제하지 않는다.

operator API는 `GET /api/v1/nodes/{node_id}/vms/{vmid}/migrate?destination_node=...`, `POST .../actions/migrate`다. 웹 `/instances/:vmid/migrate`·CLI `vm migrate show/plan/execute`는 동일 검토·명시적 VMID/이름/원본->목적 확인을 사용하며 canonical Operation ID/type/source node/VMID/전체 payload를 대조한다. 결과의 목적 위치·설정 보존과 별도 부팅/접속 검사를 구분한다. 실제 PVE 이동·관리형 권한 적용·설치 검증은 별도 승인 대기다.

### M6 OPS-02 노드 유지보수 준비 조회

`maintenance/`는 기존 workload inventory와 backup listing·migration review의 application 경계를 조합한다. operator `GET /api/v1/maintenance/nodes/{node_id}`는 선택적 destination_node/backup_storage, 최근 백업 기준 1~720시간(기본 24), 추가 검사 1~20개(기본 10)를 받는다. 웹 `/insights/maintenance`, CLI `maintenance node`는 같은 조회 보고서를 사용한다. 새 Operation·DB 저장·background 수집·PVE mutation은 없다. 조회에 기존 선택 기능 권한이 필요할 수 있으나 자동 추가하지 않는다.

영향 범위는 현재 연결에 보이는 해당 node의 QEMU VM/template와 storage/bridge다. 최대 200개와 전체 관찰 개수·잘림을 표시하며 template은 중복 collection을 합친다. 권한으로 숨겨진 VM·LXC·HA/cluster service·호스트 의존성은 관찰했다고 주장하지 않는다. 빈 목록은 `no_visible_targets`이고 `node_shutdown_safe=false`를 유지한다. 원본에 남은 VM을 이동 완료로 간주하지 않는다.

5분 이내 시각·online node·storage/network/vm_config/vm_detail의 완전한 관찰이 있어야 추가 검사를 진행한다. 미래/미상 시각·누락·중복 ID·미지원 template은 준비 완료가 아니다. 정지 VM의 optional guest_agent 미응답은 이 준비 검사에 필요하지 않다. 실행 중 VM은 정상 종료 필요, 이동 검토 오류는 대상별 blocked/unavailable, 검사 한도 초과는 not_checked다. 예상 조회 오류만 정형화하고 다른 대상 결과를 보존한다.

`ready_for_manual_migration`은 OPS-01의 현재 검토 통과와 선택 기간 내 BAK-01 archive metadata 존재를 함께 확인했다는 뜻이다. 정확한 원본/목적/VM identity를 대조하며 미래 archive 시각은 거부한다. 실제 이동·archive 내용 무결성·복원·부팅·접속은 별도다. snapshot/검사 시점 이후 상태는 변할 수 있으므로 실행은 기존 백업/이동의 새 검토·명시적 확인을 거친다. 전체 결과가 preparation_checked라도 노드 종료 안전성을 보증하지 않는다.

현재 관리형 설치의 노드 yoonmanserver3 보고서를 실제 웹·CLI로 조회해 선택 VM7001의 위치·전원·사양·disk storage·bridge를 PVE config/status와 대조했다. 목적 node/backup storage 미선택은 not_checked이며 준비 미완료·노드 종료 안전성 미확인을 유지한다. 선택 범위 밖 자원이나 추가 백업/이동 준비 검증은 이 결과에 포함하지 않는다.

### M6 OPS-03 호스트 변경 조정 기반

`operations/host_config/`는 VMID 없이 storage·bridge의 변경 admission을 소유한다. `host_storage` target은 `proxmox_storage`/`storage:<id>`, `host_network`는 `proxmox_network`/`node:<node>/bridge:<iface>`다. `proxmox_configuration` scope는 cluster별 하나이며 기존 연결 전환의 transaction gate를 재사용한다. 열린 VM/host lock이 있으면 host 변경을 막고, host lock이 있으면 새 VM mutation을 막는다. 서로 다른 VM 사이의 기존 동시 실행은 보존한다. 외부 PVE 작업은 이 잠금의 통제 범위가 아니다.

lock·Operation·recovery lease는 같은 transaction에서 준비한다. Operation/recovery의 종류·cluster·scope·target·lock ID와 실제 lock owner/evidence/VMID null을 매 checkpoint에서 대조한다. 대상 binding은 observation patch나 projector로 바꿀 수 없다. 불일치 시 dispatch·완료·해제를 거부하고 상태 전환/해제 없는 paused 오류 기록만 허용한다. 기존 연결 전환의 미완료 검사에는 host lock과 recovery도 포함된다.

웹과 CLI의 호스트 설정 완료 표시는 canonical Operation ID·종류·대상·전체 요청이 일치하고 status가 succeeded이며 Operation과 상세 응답의 coordination_incomplete가 모두 해제됐을 때만 제공한다. 조정이 남은 성공 기록은 결과 확인 필요로 표시하고 기존 Operation의 잠금·복구 확인으로 연결한다. 이 표시가 새로운 설정 요청이나 자동 재전송을 유발하지 않는다.

0042는 기존 VM index·이력·VMID를 보존하고 host action/scope check, host VMID null 제약과 열린 host lock unique index를 추가한다. host 이력이 있으면 downgrade를 거부한다. 관리형 admission은 명시적 host 기능과 node/resource 선택, 기존 source/revision pin·암호화 키를 요구한다. 기존 연결에는 권한을 자동 추가하지 않는다. directory storage의 adapter·관리형 권한·공개 API·웹/CLI·GET-only 복구 handler는 연결했다. Linux bridge 저장·노드 전체 반영·단계별 결과 확인도 연결했다. 실제 PVE 검증은 남아 있다. 운영 DB 적용과 실제 호스트 반영은 별도 승인 대상이다.


#### OPS-03 directory storage 등록·수정

admin `POST /api/v1/nodes/{node_id}/host-storage/{storage_id}/review`는 create/update·path(create 전용)·content·enabled를 검토한다. `POST .../actions/configure`는 같은 변경과 검토 digest·idempotency key·`node/storage/mode` 확인 문구·명시적 cluster 영향 동의를 받는다. 웹 `/settings/host-storage`와 CLI `host storage plan/execute`는 같은 계약을 사용하고 canonical Operation의 종류·전체 target·전체 요청을 대조한다.

첫 등록은 기존 절대 경로의 비공유 dir storage, 선택 node 하나, 사용 상태만 지원한다. 수정은 content·사용 여부와 자동 디렉터리 생성 해제만 바꾸며 path/nodes/shared/기타 설정을 보존한다. 삭제·mount·포맷·경로 이동은 없다. 기존 nodes가 없으면 전체 노드에 영향을 주며 이 범위를 검토에 표시한다. `create-base-path=0`·`create-subdirs=0`으로 기존 directory만 사용한다. 하위 content directory 존재·실제 VM/backup 작성은 별도 미검증이다.

`operations/host_storage/`는 최초 검토와 원자 host admission 후 직전 검토를 대조한다. PUT에는 PVE config digest를 전달하고 POST는 대상 부재 재확인과 PVE ID 충돌 거부를 사용한다. durable dispatch 기록 뒤 한 번만 요청하며 응답 유실 시 자동 재요청/완료/해제를 하지 않는다. `host_storage_observation` handler는 기존 lease·canonical binding을 확인한 뒤 GET만 사용해 설정과 선택 node 활성 상태를 재관찰한다. 성공에는 응답 확인·원래 옵션 보존·원하는 설정·enabled일 때 실제 active 확인이 모두 필요하다. disabled는 설정만 확인하며 unmount 완료를 주장하지 않는다.

활성 관찰에 쓰는 PVE node storage 상태 조회는 PVE 내부에서 다른 enabled storage도 점검·활성화할 수 있다([공식 Storage 구현](https://raw.githubusercontent.com/proxmox/pve-storage/master/src/PVE/Storage.pm)). HTTP GET-only는 호스트 내부 부수 효과가 전혀 없다는 뜻이 아니다. 검토 경고와 live 승인 범위에 이 영향을 포함한다. 대상의 자동 directory 생성 옵션이 남아 있거나 disabled면 활성 조회를 하지 않는다.

관리형 v16의 `host_storage` opt-in과 별도 `host_storages` ID 범위는 새 등록 예정 ID도 허용한다. 추가 role `GjallarHostStorageV1`은 공식 API가 요구하는 `/storage` Datastore.Allocate이며 선택 host ID의 Datastore.Audit·기존 node Sys.Audit를 함께 사용한다. PVE token 자체는 전체 storage 설정 권한이 넓다는 경고를 보여주고 Gjallar 요청 policy가 선택 dir ID·허용 필드·정확한 method/path/body를 제한한다. volume 삭제/생성 권한은 자동 추가하지 않는다. 기존 연결 갱신·전환·전체 process 재시작이 필요하며 이전 연결은 암묵 확장하지 않는다. 구현 검증과 실제 PVE token/설정 protocol 검증은 구분한다.


#### OPS-03 VM용 Linux bridge 설정·반영

admin `POST /api/v1/nodes/{node_id}/host-network/{bridge_id}/review`는 create/update·autostart·vlan_aware·vlan_ids를 검토한다. `POST .../actions/configure`는 동일 변경·검토 digest·요청 ID·`node/bridge/mode` 확인 문구·명시적 node reload 동의를 받는다. 웹 `/settings/host-network`와 CLI `host network plan/execute`는 같은 계약과 canonical Operation target/payload 대조를 사용한다. VLAN은 1~4094 ID·공백 구분 범위를 정규화한다.

신규 vmbrN은 물리 port 없는 내부 VM bridge다. 기존 Linux bridge는 자동 시작·VLAN-aware·허용 VLAN만 수정하며 port·MTU·기타 설정을 보존한다. host IP/gateway·DHCP/IPv6 auto·추가 inet6 stanza·임의 hook/options·OVS/SDN 대상은 지원하지 않는다. 관리망 주소·물리 NIC 재배치·bridge 삭제·SSH는 제공하지 않는다.

`operations/host_network/`는 pending 없음·online node·대상과 다른 모든 local interface 설정 fingerprint를 검토한다. `ProxmoxMutationClient.get_host_network_snapshot`의 명시적 내부 옵션만 관리형 전체 interface와 raw diff를 읽을 수 있고, 기존 VM NIC 선택/일반 inventory는 원래 scope를 유지한다. raw 주소·diff는 메모리에서만 대조하며 DB·로그·API 결과에는 target 요약과 fingerprint만 남긴다. PVE unified diff의 파일/구간 길이/변경 지시문을 검사하고 다른 interface의 fingerprint도 대조해 foreign pending을 반영하지 않는다. 인식할 수 없는 writer 변화는 실패로 남긴다.

단계는 durable stage dispatch→한 번 POST/PUT→ack→staged 설정/한정된 diff 검증→직전 재조회→durable reload dispatch→한 번 PUT→exact node/srvreload/networking UPID 원자 저장→task·pending 없음·설정 보존·정확한 iface/type과 active 검증이다. stage만 완료한 상태를 성공으로 표시하지 않는다. autostart=true일 때 active를 요구한다. optional `exists`는 물리 장치 표시이므로 가상 bridge의 존재 조건으로 요구하지 않으며 autostart=false는 부팅 설정 확인이고 즉시 down을 뜻하지 않는다. VM 통신·커널 VLAN table 검사는 별도다.

PVE network API에는 digest 조건부 변경이 없어 외부 동시 관리를 중지해야 한다. reload는 노드 전체 `ifreload -a`와 PVE SDN 설정 생성에 영향을 줄 수 있으며 `regenerate-frr=0`을 고정한다. Gjallar host lock은 외부 PVE 동시 변경을 막지 못한다. 관리 접속 단절·다른 network 영향은 검토와 실제 반영 승인에 포함한다([공식 Network API](https://raw.githubusercontent.com/proxmox/pve-manager/master/PVE/API2/Network.pm), [pending 파일/diff 처리](https://raw.githubusercontent.com/proxmox/pve-common/master/src/PVE/INotify.pm)). 실제 PVE 9.0.11의 stage/reload protocol은 미검증이다.

`host_network_observation` handler는 canonical target·두 이력의 lock/lease와 task binding을 확인하고 GET-only로 재관찰한다. stage/reload 응답 유실·중간 중단·실패·foreign 변경은 잠금을 유지한다. stage만 저장됐더라도 자동 reload·revert·삭제·새 요청을 하지 않는다. 정확한 reload task가 바인딩되고 성공·실제 상태가 관찰된 경우에만 복구가 완료될 수 있다.

관리형 v17은 명시적 `host_network`/별도 `host_bridges`(신규 vmbrN 포함)를 요구한다. 선택 node의 Sys.Modify(`GjallarHostNetworkV1`)·기존 Sys.Audit, 전체 local bridge 관찰용 `/sdn/zones/localnetwork` SDN.Audit가 필요하다. token의 Sys.Modify는 bridge만의 권한이 아니므로 발급·env import 계획과 웹/CLI에 경고한다. Gjallar 정책은 정확한 선택 bridge·고정된 변경 필드/메서드·node 전체 reload만 허용하며 guest NIC·전원·host reboot·삭제 권한을 추가하지 않는다. 기존 연결의 opt-in 갱신·검증·전환·전체 process 재시작이 필요하다. DB는 기존 0042를 사용하며 운영 적용·실제 host 변경은 별도 승인한다.
