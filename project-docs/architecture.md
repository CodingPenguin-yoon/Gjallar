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

현재는 inventory·VM 상세·Insights, 기존 템플릿 복제 기반 Create, Start, graceful Shutdown, Guided `qm unlock`, Operations·Jobs 이력과 로컬 계정을 제공한다. 템플릿 직접 입력과 선택적 DB 프리셋은 구현됐다. 독립 Python CLI·최소 메뉴 TUI·관리형 Compose bootstrap과 서버 중계 Proxmox 등록의 코드·격리 검증을 구현했다. 실제 OS 설치·PVE 연결 검증은 남아 있다. 템플릿 제작·내장 콘솔·일반 VM 수정·삭제·백업·복원·마이그레이션·시계열 모니터링·알림은 미구현이다.

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

- 필수 연결 설정 부재는 `unconfigured`, complete snapshot은 `live/fresh`, 일부 source 실패는 `degraded/partial`, snapshot 부재는 `degraded`다. fake inventory로 대체하지 않는다.
- authoritative partial snapshot이 있으면 관찰된 데이터를 표시한다. snapshot 부재 시 과거 inventory를 보여주는 durable stale fallback은 없다.
- read adapter에는 기본 10초 process-local cache가 있다. 최초 Create mutation 직전에는 별도 adapter의 cache 없는 관찰을 사용한다.
- Create 입력·검토는 partial base snapshot에서도 가능하다. 실행은 guest agent 외 source의 complete 관찰과 action별 조건을 요구한다. Start·Shutdown·Guided의 complete-live 조건은 유지한다.
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

권한·request·오류의 세부 회귀 검사는 `backend/tests/contracts/`, frontend contract는 `frontend/tests/`가 기준이다. 문서 축약은 API 계약의 변경이 아니다.

## 5. 작업 실행과 성공 판정

공통 개념은 입력·intent 기록 → 현재 상태/권한/필요한 승인 확인 → target lock·recovery 준비 → 실행 → task·실제 상태 검증 → 기록·coordination 정리다. 모든 action이 한 DB transaction이나 같은 순서로 끝나는 것은 아니다.

| action | 실행과 완료 조건 | 중요한 제한 |
|---|---|---|
| Start | recovery 등록 후 POST, terminal task OK와 direct running 확인 | 이미 완료된 같은 intent는 replay, 재실행 금지 |
| Shutdown | graceful POST, task stopped/OK와 direct stopped 확인 | hard stop·reboot·timeout 강제 fallback 없음 |
| Create | 기존 template clone→config/resize→선택적 boot→post-check | exact plan 승인, 최초 mutation 전 fresh 재검토, 단계별 durable checkpoint |
| Guided unlock | typed bundle→사용자의 외부 실행 attestation→config lock·active task 부재 검증 | backend shell/SSH executor 없음, attestation만으로 성공 아님 |

`blocked`는 실행 전 차단, `failed`는 명확한 실패, `needs_reconciliation`은 effect나 결과의 불확실성이다. API 요청 접수·task 발급만으로 성공을 선언하지 않는다. 오류·timeout·missing/invalid UPID·post-check 불일치는 같은 mutation을 무작정 재실행하지 않고 잠금과 근거를 보존한다. 외부 payload는 allowlist/redaction을 거쳐야 하며 raw credential·URL·body·잘못된 UPID를 저장하거나 locator로 사용하지 않는다.

### Create의 보존할 의미

- 템플릿 직접 입력은 DB profile을 조회하지 않는다. 프리셋 선택 시 해당 기본값·제약을 사용한다. draft/preflight는 Proxmox를 변경하지 않지만 Jobs 기록은 쓰므로 DB read-only가 아니다.
- 계산과 저장은 분리됐지만 plan 관련 다섯 artifact와 approval checksum·preview·execute consumer는 유지한다. 생성은 Proxmox API를 사용하고 manifest/planned Git diff는 호환 산출물이다.
- 검토 후 입력 변경·다시 검토는 새 작업 identity와 승인·동의 초기화를 요구한다. VMID 추천은 예약이 아니다. 실행 직전 승인 조건 drift는 `409 PROXMOX_CREATE_STATE_CHANGED`, 필수 관찰 불가는 `503`으로 최초 mutation 전에 중단한다.
- `stopped` 또는 `boot_and_verify`를 지원한다. 후자는 guest agent IP뿐 아니라 허용된 guest-exec로 cloud-init 완료 검사가 필요할 수 있다. 차단된 guest-exec 정책을 자동 해제하지 않는다.
- 현대 완료 replay·evidence는 succeeded Operation의 당시 `details.workload`를 읽는다. 현재 VMID 재사용·이동이 과거 결과를 바꾸지 않는다. 손상된 성공 결과를 현재 row로 대체하지 않고 reconciliation을 요구한다. legacy는 exact job/node/VMID linkage만 사용한다.
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

따라서 terminal Operation도 잠금과 미완결 recovery를 가질 수 있다. evidence·compatibility 저장 실패는 action-specific `503`과 exact Operation handoff로 드러내며 기존 결과·lock을 임의로 지우지 않는다.

- open locator lock은 한 configured cluster의 VMID를 action type과 node 표기를 가로질러 직렬화한다. scope key는 `{cluster_id}|proxmox_locator|{vmid}`다. 파일 guard는 제거됐다.
- Start/Shutdown은 잠금 획득·충돌 뒤 Jobs·Operation을 재조회한다. same-owner는 replay/in-progress, foreign owner 충돌은 현재 Operation·exact open foreign lock을 transaction 안에서 다시 확인한다.
- client/recovery 등록 전 실패는 no-effect Jobs를 먼저 쓸 수 있다. canonical planned·recovery item 부재·exact owned lock을 확인한 경우에만 실패 전이와 해제를 진행한다. 이미 다른 owner가 복구를 맡았으면 덮어쓰지 않는다.
- lease 만료는 observer 재claim 가능성을 뜻하며 target lock 해제나 외부 미실행의 증거가 아니다. commit은 current lease token/generation/expiry, Operation fence, exact lock owner/ID/cluster를 검사한다. stale observer는 projector도 실행하지 못한다.
- recovery kind는 Start·Shutdown·Create·Guided 네 allowlist다. 기본 disabled인 in-process runner와 operator observe가 같은 GET-only handler를 사용한다. 원래 mutation·보상·임의 명령을 다시 실행하지 않는다.
- restart Create는 남은 mutation을 이어서 실행하지 않는다. 중간·미확정 phase는 근거를 수집하고 pause한다. 성공 복구는 persisted readiness/observed-after checkpoint·fresh config/status fingerprint·artifact content SHA-256/JSON 일치와 fenced transaction을 요구한다.
- recovery item 없는 crash를 no-effect로 복구하려면 현재 계약의 marker·checksum·정확한 lock·task/effect 부재 조건이 필요하다. 과거 기록이나 시간 경과만으로 추정하지 않는다.

## 8. 유지할 결정과 남은 설계

Proxmox actual-state authority, modular monolith, 명시적 연결 truth, PostgreSQL durable coordination, action별 검증, 현재 이력 보존을 유지한다. 과거 observe-first의 네 action 제한과 템플릿 제작 제외는 장기 제품 경계로 유지하지 않으며 새 목표는 PRD를 따른다. DRS 자동 배치·무승인 자동 복구·임의 shell은 복원하지 않는다.

현재는 한 configured cluster를 전제로 하며 다중 클러스터 식별·worker 분리·지속 관측·CLI mutation·콘솔 인증·새 action 계약은 후속 설계다. 기능 확장을 이유로 기존 API·데이터·복구 계약을 묵시적으로 변경하지 않는다. migration은 새 revision으로만 수행하고 적용된 revision을 고치지 않는다. `20260824_0029`의 DRS hard-zero preflight·production 적용·파일 guard 전환 절차는 개발 안내에 유지한다.

M1의 구조는 웹·CLI·TUI → 선택한 로컬 또는 원격 Gjallar → Proxmox다. 클라이언트가 Proxmox를 직접 조작하는 별도 운영 경로는 없고 기존 서버의 권한·작업·잠금·검증 경계를 공유한다. 등록 설계·실행 근거와 남은 검증은 [M1 작업 기록](work/2026-09-16-m1-installation-connection.md)에 기록한다.

`2026-09-17` M1-1·M1-2는 사용자 승인 후 구현했다. Python client는 기존 cookie API를 사용하며 connection UUID/origin별 keyring 또는 명시적 process-memory session을 관리한다. 원격 HTTPS·고정 origin·redirect 금지·별칭의 atomic 저장과 동기식 CLI/TUI application을 공유한다. 기존 env Proxmox 설정을 자동 전환하지 않는다.

신규 Compose는 loopback 앱/비공개 PostgreSQL 17 named volume과 image ID 고정을 사용한다. 설치 manifest/volume label/DB marker identity를 결합하며 secret 전용 파일·mount와 관리자 stdin을 쓴다. `GJALLAR_DATABASE_URL_FILE`은 기존 URL env와 상호 배타적 입력이다. 빈 DB에서만 `gjallar_installation(singleton, installation_id, state)`를 만드는 infrastructure 초기화는 기존 Alembic revision을 수정하지 않으며, 일반/기존 DB에 자동 marker를 추가하지 않는다. PostgreSQL advisory lock으로 schema 초기화를 직렬화하고 users table EXCLUSIVE lock 아래 zero-user/history 검사·admin·account audit·ready marker를 원자적으로 기록한다. 기존 VM lock/recovery는 변경하지 않는다.

`init-schema`만 새 설치 migration/seed를 실행하고 `serve`·start는 현재 Alembic head/ready 확인만 한다. 같은 schema의 image upgrade만 제공하며 revision 변경·기존 DB migration은 별도 승인 경계에 남긴다. host manifest의 준비/volume 준비/완료 상태와 upgrade journal로 중단을 재개하고 volume·secret·계정·이력을 자동 삭제/덮어쓰지 않는다. PostgreSQL 17의 격리 동시성 검증은 통과했으며 OS keyring·VM 설치는 미검증이다. 신규 manifest v2는 credential key 파일·mount를 추가한다. v1 설치는 읽기·서비스 관리 호환을 유지하고 자동 변환하지 않는다.

### Proxmox 등록과 credential 선택

관리자 전용 `/settings/proxmox`, `gjallar proxmox-setup`, TUI `p`가 같은 `/api/v1/setup/proxmox/registrations` API를 사용한다. collection GET/POST는 본인 이력/등록, item GET은 상태, item POST `/{action}`은 login·mfa·plan·confirm·verify·activate·observe·cancel·revoke·import-plan·import-env다. create는 strict intent와 idempotency key, action은 expected_version을 요구한다. confirm/import-env는 plan_digest, revoke는 전체 token_id도 요구한다. 비밀번호·OTP는 login/mfa body로만 받으며 validation/upstream 오류에 원문을 반환하지 않는다.

검증 대상은 사용자가 제공한 pve-manager `9.0.11`, pam/pve 비밀번호·TOTP다. 실제 package/realm 조합 지원을 확정한 것은 아니다. 서버는 HTTPS CA/hostname 검증 후 비밀번호를 전송한다. DNS 목적지를 고정하고 loopback/link-local 등을 거부하며 proxy·redirect·자동 retry를 사용하지 않는다. PVE ticket/CSRF는 Gjallar actor/session에 결합한 최대 5분의 process 메모리 context이며 재시작·만료 후 재로그인이 필요하다. 다중 worker 간 context 공유는 없다.

계획은 exact node/VM/storage/local bridge, read 및 선택적 power, owner/token ID·만료·CA digest·ACL·connection version을 결합한다. 새 역할은 고정 Audit/Power 권한만 사용하고 같은 이름의 다른 역할을 덮어쓰지 않는다. owner/effective token 권한과 실제 선택 자원 조회를 검사한다. Create/Guided 권한 profile은 제공하지 않으며 managed provider에서 해당 mutation을 거부한다. env adapter의 기존 action 권한 경로는 유지한다.

등록 Operation과 attempt는 같은 transaction에 기록한다. `token_dispatching`을 먼저 commit하고 발급 secret을 AES-256-GCM으로 즉시 staging한 후 ACL·조회 검증을 진행한다. AAD는 installation/connection/revision과 전체 설정에 결합하고 key/nonce uniqueness를 검사한다. secret·비밀번호·ticket·OTP·upstream 원문은 Operation에 넣지 않는다. `token_dispatching`/`acl_applying`에서 멈추면 결과 미확정이며 자동 재발급·ACL 재전송을 하지 않는다. exact 발급 token의 확인·명시적 폐기를 제공하고, 폐기 응답 유실은 부재 조회로만 마무리한다. 공유 역할이나 가져온 env token은 자동 삭제하지 않는다.

검증된 pending revision의 활성화는 fresh 조회 후 connection version CAS와 PostgreSQL transaction advisory lock으로 직렬화한다. 같은 lock을 VM target lock 획득 시에도 사용한다. 다른 nonterminal Operation·open lock·미완결 recovery가 있으면 전환/활성 token 폐기를 거부한다. 활성화는 기존 revision을 retiring으로 보존하며 폐기는 별도다. process마다 최초 source/revision을 고정하므로 전환 후 **모든 서버 process 재시작**이 필요하다. managed 선택 후 key/DB 오류는 degraded/실행 차단이며 env fallback은 없다.

명시적 env import는 서버의 기존 token을 읽어 같은 endpoint/owner·TLS·scope를 검증하고 암호화 저장한다. upstream mutation은 없다. 키 backup 복원은 가능하지만 자동 키 교체, 이전 source/revision 복귀 버튼, 불명 발급의 강제 종료, 긴급 drain 우회는 제공하지 않는다. 운영 전환 전 복구·지원 범위를 검토해야 하며 전체 M1 완료로 간주하지 않는다.

과거 상세 ADR·API/DB 목록·단계별 기록은 [보관본](archive/README.md)에서 복원할 수 있다. 현재 문서는 여기와 PRD·개발 안내를 갱신하고, 별도 도메인·API·DB·ADR 문서를 관성적으로 추가하지 않는다.
