# 운영 Runbook

- 상태: `APPROVED`
- 최종 검토일: `2026-09-07`
- 부분 검토: `2026-09-17`, M1-1 client·M1-2 관리형 bootstrap (실제 설치 검증 전)
- 적용 범위: 현재 single-image FastAPI/React/PostgreSQL runtime

이 문서는 현재 코드의 환경 준비·실행·검증·장애 대응을 위한 단일 절차 기준이다. [문서 홈](README.md), [현재 API](architecture.md), [작업 lifecycle](architecture.md)에서 관련 계약을 찾는다. 템플릿 직접 입력과 선택적 DB 프리셋은 구현됐다. [현재 설계 기준](architecture.md)의 후속 저장 단순화와 구분하며, 아래 운영 절차는 현재 이력·compatibility 저장 구조를 기준으로 한다.

고위험 변경과 live 실행 승인 경계는 [AGENTS.md](../AGENTS.md)를 따른다. 환경과 검증 명령은 이 문서에서만 관리한다.

## 1. 사전 조건

- local 기준: Python 3.13, Node.js 24, pnpm 10.34.5, PostgreSQL. `python3.13`이 다른 이름·경로라면 명령의 실행 파일만 해당 경로로 바꾼다.
- container 기준: Docker와 PostgreSQL 접근 경로.
- 필수 설정: `GJALLAR_DATABASE_URL`; target coordination identity는 `GJALLAR_CLUSTER_ID`이며 기본값은 `gjallar-mvp`다.
- Overview·Workloads 관찰과 Create VM 사용 시: Proxmox API URL, token ID, token secret과 TLS 정책.
- `.env`, password, token, private key를 repository, command history, log, artifact에 남기지 않는다.

product runtime은 Proxmox 설정 누락이나 연결 실패를 fake inventory로 대체하지 않는다. authoritative snapshot이 있으면 `degraded/partial`에서도 Overview·Workloads·VM 상세를 읽을 수 있다. Create 입력·검토는 partial base snapshot에서도 가능하다. Create 실행은 guest agent 외 source의 complete 관찰을 요구한다. 고정 IP는 입력한 주소의 ping 응답과 기존 VM 설정·guest agent IP 정보를 함께 확인한다. 어느 쪽이든 점유가 발견되면 red로 차단하며, 점유 미발견·조회 불가는 yellow로 직접 확보한 IP인지 확인받는다. 기존 VM의 guest agent 누락만으로 차단하지 않는다. DHCP discovery 경고와 최초 mutation 직전 재검증은 유지한다. Start/Shutdown/Guided의 complete-live 조건은 유지한다. snapshot이 없는 경우에만 inventory-dependent 읽기 화면을 연결 안내로 차단한다.

## 2. 최초 로컬 준비

저장소 root에서:

```bash
cp .env.example .env
nvm use
npm install --global pnpm@10.34.5
python3.13 -m venv backend/venv
backend/venv/bin/pip install -r backend/requirements-dev.lock
pnpm --dir frontend install --frozen-lockfile
```

`.env`의 PostgreSQL URL을 실제 값으로 변경하고 load한다.

```bash
set -a
. ./.env
set +a
```

DB 초기화와 first admin 생성은 새 빈 로컬 DB에서만 바로 실행한다. 기존 또는 production DB는 아래 `DB migration`의 `20260824_0029` preflight와 별도 적용 승인을 먼저 완료한다. DRS row나 호환되지 않는 lock이 있으면 삭제·변환·force stamp하지 않는다.

```bash
PYTHONPATH=backend backend/venv/bin/alembic -c backend/alembic.ini upgrade head
PYTHONPATH=backend backend/venv/bin/python -m app.db.seed_create_vm_profiles
PYTHONPATH=backend backend/venv/bin/python -m app.auth.users create-admin --username admin
```

- runtime DB는 PostgreSQL만 허용한다.
- `postgresql://`과 `postgres://`는 `postgresql+psycopg://`로 normalize된다.
- SQLite는 `GJALLAR_ALLOW_SQLITE_FOR_TESTS=1`인 test에서만 허용한다.
- profile seed는 기존 profile row가 있으면 no-op하는 idempotent 작업이다. 템플릿 직접 입력은 DB profile을 조회하지 않는다. 복제 가능한 Proxmox template을 준비하고 프리셋을 사용할 때만 활성 profile을 준비한다. mode를 생략한 기존 API 요청은 profile 경로를 사용한다.
- `boot_and_verify`는 guest agent의 IP 관찰 외에 `guest-exec`로 `cloud-init status --wait`를 조회할 수 있어야 한다. Proxmox agent 설정 활성화만으로 guest 내부 명령 허용이나 cloud-init 성공이 보장되지는 않는다. 템플릿에서 guest-exec를 차단한 경우 완료 검증은 성공하지 않으며 정책을 자동 해제하지 않는다. 접속 계정명은 템플릿의 기존 사용자·그룹과 충돌하지 않도록 선택한다.
- dependency 설치는 `requirements*.lock`과 `frontend/pnpm-lock.yaml` 기준이다. direct dependency를 바꿀 때는 `requirements*.txt`와 Python 3.13/Linux에서 해석한 lockfile을 함께 갱신한다.

## 3. 로컬 시작·종료

```bash
pnpm run dev
```

root script는 다음 process를 함께 시작한다.

- backend bind: `0.0.0.0:${BACKEND_PORT:-8000}`; local 접속은 `127.0.0.1` 사용
- frontend: `0.0.0.0:${FRONTEND_PORT:-5173}`
- Vite `/api` proxy: `VITE_BACKEND_URL` 또는 local backend port

backend만 실행하려면 root에서 `pnpm run backend`, frontend만 실행하려면 `pnpm run frontend`를 사용한다. 두 wrapper는 root `.env`를 읽는다. Vite는 root·frontend env를 읽고 process env를 우선하며 `/api`를 backend로 proxy한다. API client는 cookie session을 포함한다.

터미널의 `Ctrl-C`로 두 process를 종료한다. background process가 남았으면 현재 port listener를 확인한 뒤 해당 process만 종료한다.

## 4. Container 시작

아래는 기존 수동 배포의 legacy entrypoint다. 신규 관리형 설치는 아래 `M1 client와 관리형 bootstrap` 절차를 사용하며 일반 start에서 초기화를 실행하지 않는다.

entrypoint가 `alembic upgrade head`를 자동 실행한다. 기존 또는 production DB에 연결할 image는 아래 read-only preflight와 별도 DB 적용 승인 전 배포·실행하지 않는다.

```bash
docker build -t gjallar:local .
docker run --rm --env-file .env -p 8000:8000 gjallar:local
```

entrypoint 기본 순서:

1. `alembic upgrade head`
2. Create VM profile seed
3. `bootstrap-admin-from-env`
4. Uvicorn 실행

bootstrap admin은 다음 두 값이 모두 있을 때만 생성한다.

```dotenv
GJALLAR_BOOTSTRAP_ADMIN_USERNAME=admin
GJALLAR_BOOTSTRAP_ADMIN_PASSWORD=change-this-securely
```

first login 후 bootstrap password를 교체하고 배포 secret에서 제거한다. `GJALLAR_SKIP_STARTUP_INIT=1`은 migration·seed·bootstrap을 모두 건너뛰므로 일반 start에 사용하지 않는다.

container에서는 image가 설정한 `GJALLAR_FRONTEND_DIST=/app/frontend-dist`를 사용한다. local `.env`에서 이 값을 별도로 활성화해 Docker 기본값을 덮어쓰지 않는다.

## 5. 기본 상태 점검

### Backend health

```bash
curl --fail --silent http://127.0.0.1:8000/health
```

정상 응답:

```json
{"status":"healthy","service":"backend"}
```

이 endpoint는 DB와 Proxmox의 deep readiness를 보장하지 않는다. 다음 항목을 별도로 확인한다.

- startup log에서 Alembic/seed 성공
- login과 `/api/v1/auth/me`
- inventory endpoint의 `meta.source`
- authenticated `GET /api/v1/setup/proxmox/connection`의 `state`, `source`, `observed_at`, `freshness`
- authenticated `GET /api/v1/insights`의 section별 `available`, `freshness`, `rule_version`, `truncated`
- Jobs 화면이 비어 있을 때 DB log/error 여부
- live mutation 전 target node/VM과 credential scope
- enabled recovery 환경이면 Operation 상세의 `recovery`, `target_lock`과 runner warning log

### DB migration

```bash
set -a
. ./.env
set +a
PYTHONPATH=backend backend/venv/bin/alembic -c backend/alembic.ini current
PYTHONPATH=backend backend/venv/bin/alembic -c backend/alembic.ini heads
```

`current`와 expected head가 다르면 application을 통한 mutation 전에 migration 실패 원인을 해결한다. 적용된 revision file은 수정하지 않는다.

`20260824_0029`는 DRS 전용 schema를 제거하는 roll-forward-only migration이다. 기존 또는 production DB에서는 다음 순서를 지킨다.

1. maintenance window를 확보하고 현재 revision과 backup/복구 가능성을 확인한 뒤 모든 구버전 replica와 DRS API traffic을 완전히 중지한다. `0029`는 제거될 table/column을 참조하는 구버전 code와 rolling-compatible하지 않다.
2. read-only로 DRS 7개 table의 row count, `operation_locks`의 비-generic row, shared `job_runs`의 `drs_migration` status 분포를 확인한다.
3. 저장소 밖 `/api/v1/drs/*` consumer와 배포된 `PROXMOX_DRS_*` credential dependency를 별도로 확인한다. migration은 이 두 항목과 shared job 상태를 감지하지 못한다.
4. DRS 전용 table과 비-generic lock row가 모두 0이고 나머지 항목의 처리 결정을 기록한 뒤 exact DB와 적용 시점에 대한 별도 승인을 받는다.
5. one-off controlled upgrade 뒤 `current`, table/index/constraint, generic lock과 shared job/artifact 보존을 확인하고 `0029`-aware 새 application image만 시작한다.

read-only SQL 예시:

```sql
select 'vm_identities' as contract, count(*) as retained_rows from vm_identities
union all select 'vm_identity_observations', count(*) from vm_identity_observations
union all select 'vm_migration_policies', count(*) from vm_migration_policies
union all select 'vm_migration_policy_events', count(*) from vm_migration_policy_events
union all select 'drs_approval_packets', count(*) from drs_approval_packets
union all select 'drs_migration_jobs', count(*) from drs_migration_jobs
union all select 'drs_reconciliation_events', count(*) from drs_reconciliation_events;

select operation_type, scope_type, status, count(*)
from operation_locks
where operation_type not in ('vm_start', 'vm_create', 'guided_qm_vm_unlock', 'vm_shutdown')
   or scope_type <> 'proxmox_locator'
   or vm_identity_id is not null
   or source_node_id is not null
   or target_node_id is not null
group by operation_type, scope_type, status;

select status, count(*)
from job_runs
where job_type = 'drs_migration'
group by status
order by status;
```

첫 query의 `retained_rows`가 하나라도 0이 아니거나 두 번째 query가 한 row라도 반환하면 `0029`는 DDL 전에 실패한다. 실패 후 row 삭제, Alembic stamp, 기존 revision 수정 또는 destructive downgrade를 하지 않는다. state별 archive/data-retirement와 corrective forward migration을 별도 승인받는다.

### 계정·session

```bash
cd backend
set -a
. ../.env
set +a
PYTHONPATH=. venv/bin/python -m app.auth.users list-users
```

- last enabled admin 보호가 동작한다.
- user disable과 password reset은 existing session을 revoke한다.
- plaintext password, session token, token hash를 출력하거나 수집하지 않는다.

## 6. Proxmox 연결

현재 `.env.example`의 주요 live inventory/Create VM/VM lifecycle 설정:

```dotenv
GJALLAR_INVENTORY_MODE=live
PROXMOX_API_URL=https://pve.example.local:8006/api2/json
PROXMOX_API_TOKEN_ID=root@pam!gjallar
PROXMOX_API_TOKEN_SECRET=secret-reference-only
PROXMOX_TLS_INSECURE=false
```

- read inventory와 mutation client는 코드상 분리돼 있지만 같은 기본 credential env를 사용할 수 있다.
- `auto`는 전환 호환을 위한 live-only alias다. `fake`/`demo`는 product environment mode가 아니다.
- 세 필수 `PROXMOX_API_*` 값이 없으면 connection state는 `unconfigured`이고 실제 inventory row를 반환하지 않는다.
- `PROXMOX_TLS_INSECURE=true`는 검증된 폐쇄 test 환경 외에는 사용하지 않는다.
- token privilege는 필요한 endpoint에 최소화한다.

필요할 때만 다음 tuning env를 사용한다.

- common inventory/mutation: `PROXMOX_API_CONNECT_TIMEOUT_SECONDS`, `PROXMOX_API_READ_TIMEOUT_SECONDS`, legacy `PROXMOX_API_TIMEOUT_SECONDS`.
- inventory snapshot cache/병렬 조회: `PROXMOX_VM_INVENTORY_CACHE_TTL_SECONDS`, `PROXMOX_VM_INVENTORY_WORKERS`, guest-agent read timeout `PROXMOX_GUEST_AGENT_TIMEOUT_SECONDS`. 기본 snapshot cache는 10초의 process-local 메모리 cache이며 durable stale fallback이 아니다.
- auth/cookie: `GJALLAR_ENV`, `GJALLAR_ALLOWED_ORIGINS`, `GJALLAR_SESSION_COOKIE_NAME`, `GJALLAR_SESSION_TTL_SECONDS`, `GJALLAR_SESSION_COOKIE_SECURE`, `GJALLAR_SESSION_COOKIE_SAMESITE`.
- Create access default: `GJALLAR_DEFAULT_SSH_PUBLIC_KEY`, `GJALLAR_DEFAULT_SSH_PUBLIC_KEY_B64`, `GJALLAR_DEFAULT_SSH_PUBLIC_KEY_FILE`. 원문 key를 작업 로그나 공용 evidence에 복사하지 않는다.
- task poll: `PROXMOX_TASK_POLL_INTERVAL_SECONDS`, `PROXMOX_TASK_TIMEOUT_SECONDS`; legacy alias는 `GJALLAR_PROXMOX_TASK_*`.
- operation recovery: `GJALLAR_OPERATION_RECOVERY_ENABLED=false`, poll 기본 5초(1..300), lease 기본 60초(10..900), `GJALLAR_OPERATION_RECOVERY_MAX_ATTEMPTS` 기본 5(1..20). background concurrency는 1로 고정된다.
- 값과 기본값은 `.env.example`과 현재 client code를 우선하며 관측 근거 없이 timeout을 늘리지 않는다.

### 고정 IP의 ping 관찰

- ping은 Gjallar backend가 실행되는 네트워크에서 입력한 numeric IPv4 한 개에만 보낸다. Proxmox 노드·guest 내부에서 실행하거나 다른 주소를 스캔하지 않는다. 해당 VM 네트워크에 대한 routing·VLAN 접근이 없으면 결과는 제한된다.
- Linux는 `iputils-ping`, macOS는 시스템 `ping`을 사용한다. Docker image에는 `iputils-ping`이 포함된다. 별도 privileged/host-network 실행을 요구하지 않으며 현재 권한으로 실행할 수 없으면 확인 불가로 표시한다.
- 1회 전송, 프로세스 상한 3초이며 shell·DNS lookup을 사용하지 않는다. 원시 stdout/stderr는 저장하지 않는다. ping 대기는 API event loop 밖에서 처리한다.
- `reply`는 관찰된 점유, `no_reply`는 응답 없음, `unavailable`은 실행 불가다. 무응답도 방화벽·전원 상태·경로 등에 영향을 받으므로 IP 미사용을 증명하지 않는다. agent가 모두 응답해도 외부 장비·IP 예약 전체는 알 수 없다.
- Create 검토·계획·승인·preview와 최초 실행 직전 preflight에서 검사한다. DHCP에서는 ping을 수행하지 않는다. 템플릿 조건·생성 후 `boot_and_verify`의 guest agent/cloud-init 검증은 이 검사와 별개다.

### Operation recovery runner rollout

runner는 같은 FastAPI image 안의 기본 비활성 opt-in observer다. allowlist는 `vm_start_observation`, `vm_shutdown_observation`, `vm_create_observation`, `guided_qm_unlock_observation` 네 개다. action-specific handler는 Proxmox GET과 local evidence/projection만 사용하며 Create/Start/Shutdown mutation POST, Guided command, hard stop·reboot나 compensation을 실행하지 않는다.

enable 전:

1. maintenance window에서 모든 구버전 replica를 drain하고 완전히 중지한 뒤 위 DB migration read-only preflight와 별도 적용 승인을 완료한다.
2. one-off controlled DB upgrade 뒤 migration head `20260824_0029`와 generic lock/shared history 보존을 확인한다.
3. `0029`-aware durable-lock code만 배포한다.
4. 실제 PostgreSQL에서 open locator lock과 non-completed recovery item을 조회해 owner/operation 상태를 대조한다. lease token은 조회·공유하지 않는다.
5. recovery kind별 저장 evidence를 확인한다. Start/Shutdown은 UPID와 target node/VMID, Create는 last durable mutation/readiness checkpoint와 fingerprint, Guided는 instruction state·expiry·attestation·original config lock을 대조한다. Shutdown row는 guest-aware `status/shutdown`이 이미 제출됐을 가능성을 전제로 하며 hard stop으로 대체하지 않는다.
6. 한 replica 또는 동일 설정의 모든 replica에 `GJALLAR_OPERATION_RECOVERY_ENABLED=true`를 적용한다. 여러 replica여도 PostgreSQL lease가 한 observer만 허용한다.
7. Operation 상세 UI의 Recovery coordination과 event timeline에서 claim/retry/completion을 확인한다. Create readiness roll-forward와 Guided expiry는 live mutation 없이 GET-only evidence가 충분한 test target에서만 검증한다.

진단용 read-only SQL 예시:

```sql
select operation_id, recovery_kind, status, available_at,
       lease_owner, lease_generation, lease_expires_at,
       attempt_count, last_error_code, updated_at
from operation_recovery_items
where status <> 'completed'
order by available_at, operation_id;

select operation_type, scope_key, status, owner_id, reason, updated_at
from operation_locks
where scope_type = 'proxmox_locator'
  and status in ('active', 'stale', 'reconciliation_required')
order by updated_at, operation_lock_id;
```

즉시 runner를 멈추려면 flag를 `false`로 되돌리고 application을 정상 재시작한다. lease는 만료 후 takeover 가능한 상태가 되지만 operation과 durable target lock은 자동 해제되지 않는다. flag가 `false`여도 아래 operator-triggered observe API는 요청 시 동작한다. row를 직접 삭제하거나 status를 임의 terminal로 바꾸지 않는다.

### Operator-triggered recovery observe

background runner를 켜지 않은 환경에서도 Operation 상세가 `recovery.available_actions` 또는 `recovery_available_actions`에 `observe`를 제공하면 operator/admin이 한 exact item의 GET-only 관찰을 요청할 수 있다. 먼저 authenticated `GET /api/v1/operations/{operation_id}`에서 current `operation.version`, `operation.last_event_checksum`, recovery phase, target lock owner를 함께 확인한다.

```json
{
  "expected_version": 7,
  "expected_checksum": "sha256:current-last-event-checksum",
  "idempotency_key": "recovery-observe:7:0123456789abcdef"
}
```

authenticated session으로 `POST /api/v1/operations/{operation_id}/recovery/observe`에 제출한다. UI의 `다시 관찰` control은 current version/checksum으로 stable key를 만들고 같은 요청의 late response를 generation guard로 폐기한다.

idempotency key는 재전송 상관관계용 입력이며 비밀값을 넣지 않는다. backend도 원문을 evidence에 저장하지 않고 SHA-256 digest만 보존한다. `manual_action_required=true`인데 observe action이 없으면 missing task/attestation 또는 binding/lock repair가 필요한 상태이므로 endpoint를 우회 호출하지 않는다.

- `409 OPERATION_RECOVERY_STATE_CONFLICT`: Operation version/checksum이 바뀌었다. 새 상세를 읽고 evidence를 다시 판단한다.
- `409 OPERATION_RECOVERY_OBSERVATION_IN_PROGRESS`: 같은 item의 live lease가 있다. 동시 관찰을 추가로 보내지 않는다.
- 기타 `409`: key/fence conflict, unsupported kind, exact binding/lock mismatch, 또는 side-effect-free임을 증명할 수 없는 no-item 상태다. lock을 직접 풀지 않는다.
- `503 OPERATION_RECOVERY_OBSERVATION_UNAVAILABLE` 또는 `OPERATION_RECOVERY_PERSISTENCE_UNAVAILABLE`: authoritative GET 또는 local commit을 완료하지 못했다. 원인을 해결한 후 current fence로 다시 관찰한다.
- 응답의 `recovery_observation.observation_only=true`는 원래 mutation을 재호출하지 않았음을 뜻한다. `paused` 또는 `manual_action_required=true`면 자동 polling을 중지하고 최신 task/status/config, checkpoint, compatibility evidence를 수동 대조한다.

Start/Shutdown action 응답이 `*_OBSERVED_EVIDENCE_PERSISTENCE_UNAVAILABLE` 또는 `*_COMPATIBILITY_PROJECTION_PERSISTENCE_UNAVAILABLE`인 경우 generic 500으로 취급하지 않는다. 응답의 exact `operation_id`, `operation_status`, `recovery_status`, `evidence_recorded`, side effects와 retained lock을 기준으로 Operations 상세로 이동한다. `retry_wait`이면 advertise된 GET-only observe로 local coordination을 재개할 수 있다. 원본 observed-after artifact가 없으면 기존 payload를 추정 생성하지 않으며 recovery event와 Jobs projection을 구분해 본다. secondary handoff 저장도 실패해 `leased`로 남으면 lease expiry 전 강제 claim/release하지 않는다.

이 endpoint는 force unlock, terminal status 지정, mutation retry, reverse action과 arbitrary command를 받지 않는다. terminal Operation에 exact owned lock이 남은 경우에도 action handler가 projection·DB lock binding을 모두 닫을 수 있어야만 해제한다.

## 7. Mutation 실행 규칙

live mutation 전에 다음을 모두 확인한다.

1. 정확한 cluster, node, VMID 또는 create target
2. 현재 actual state와 template/power/location
3. API token scope와 TLS mode
4. 해당 action의 acknowledgement, approval, plan/fingerprint binding
5. idempotency identity와 충돌 중인 operation 여부
6. 예상 side effect와 실패 시 reconciliation 절차
7. 사용자의 run-specific 승인

### 금지

- timeout 직후 같은 mutation을 다른 idempotency key로 재호출
- API 실패를 확인하지 않고 `qm`으로 자동 fallback
- task `OK`만 보고 direct post-check 없이 성공 판정
- arbitrary command, SSH, token, password, raw secret을 evidence endpoint에 제출

## 8. 실패와 복구

### DB 연결 실패

- startup migration 실패 시 service를 정상으로 간주하지 않는다.
- `GJALLAR_DATABASE_URL`, DNS/network, credential, PostgreSQL availability를 확인한다.
- public `/api/v1/jobs`, job detail·artifacts의 persistence read 실패는 `503 JOBS_PERSISTENCE_UNAVAILABLE`, `/api/v1/risks`는 `503 RISKS_PERSISTENCE_UNAVAILABLE`이다. `/api/v1/insights`는 risk source만 `available=false`로 격리한다. 정상 empty success와 이 실패를 구분하고, 내부 legacy fail-open helper의 빈 값으로 public 상태를 추론하지 않는다.

### Proxmox read 실패

- `/api/v1/setup/proxmox/connection`의 state와 redacted reason을 먼저 확인한다.
- `unconfigured`이면 `PROXMOX_API_URL`, `PROXMOX_API_TOKEN_ID`, `PROXMOX_API_TOKEN_SECRET` 누락과 `GJALLAR_INVENTORY_MODE`를 확인한다.
- `degraded`이면 TLS, network/DNS, timeout, token 권한과 PVE availability를 확인한 뒤 `연결 다시 확인`을 실행한다.
- API URL, token, TLS, timeout과 PVE availability를 확인한다.
- snapshot이 없으면 inventory-dependent API는 `503`과 `PROXMOX_INVENTORY_UNCONFIGURED` 또는 `PROXMOX_INVENTORY_DEGRADED`를 반환한다. UI는 Workloads navigation을 숨기고 관련 direct route를 connection 안내로 차단한다.
- `inventory_available=true`인 partial snapshot에서는 Overview·Workloads·VM 상세와 Insights의 정상 source를 유지한다. `availability`의 실패 source/target을 확인하고 guest-agent·VM config·storage 등의 unknown을 실제 부재로 해석하지 않는다.
- Insights는 stored risk를 독립 유지하며 snapshot이 없을 때 inventory category를 `unavailable`로 표시한다. Operations·Job history·Risks·Account·Users & sessions는 자체 데이터와 권한에 따라 유지된다.
- Create VM은 guest agent 외 source 실패에서 실행이 차단된다. 기존 VM의 guest agent 실패는 경고로 표시한다. 고정 IP는 기존 VM IP 또는 ping 응답에서 점유가 확인된 경우 차단하고, 점유 미확인 시 직접 확보 여부를 확인받는다. 상단 `연결됨 · 관찰 일부 누락`(API freshness `partial`)에서 생성이 막혔다고 기능 미구현이나 admin 권한 부족으로 해석하지 않고 실패 source를 먼저 확인한다.
- stale/unknown/non-live state에서 mutation하지 않는다.

### Dispatch 결과 불명

- timeout, missing/invalid UPID, backend crash-after-dispatch는 side effect 없음으로 간주하지 않는다. invalid locator 원문은 Operation/recovery/Jobs/artifact/API에 남기거나 task GET에 사용하지 않는다.
- stored Operation/recovery checkpoint, job/artifact, task reference와 Proxmox actual state를 먼저 확인한다.
- same mutation 자동 retry를 금지하고 `needs_reconciliation` 의미를 유지한다.

### Create VM recovery

- 현재 생성은 Proxmox template clone → 필요한 disk resize → config → 선택적 start → 해당 power/readiness 검증 순서다. ISO 설치나 빈 VM 생성은 없다. 선택적 DB profile과 Jobs/artifact·request·Operation/recovery 저장을 사용하는 현재 구조를 전제로 진단한다. 현대 Create의 workload 결과는 Operation에 저장되며 `vm_instances`는 과거 exact history 조회용이다.
- artifact는 현재 `job_artifacts.content_text`에 DB 저장되며 `db://job-artifacts/...` reference를 쓴다. `run_dir` 인자나 artifact filename을 실제 filesystem evidence 경로로 해석하지 않는다. 현재 action은 temporary lock 파일을 생성하거나 읽지 않는다.
- Create는 target lock 직후 external mutation 전에 `vm_create_observation` item을 준비한다. item/lease 또는 dispatch checkpoint 저장 실패는 clone을 호출하지 않는다.
- durable phase에서 `clone_pending` 이후라면 clone effect 가능성을 배제하지 않는다. `resize_pending`, `config_pending`, `start_pending`도 해당 mutation의 결과가 불명확한 경계다. 새 job/idempotency key로 create를 다시 제출하지 않는다.
- 형식 검증된 stored clone/start UPID가 실행 중이면 GET-only observer가 bounded `retry_wait`할 수 있다. invalid historical locator는 scrub하고 GET 전에 pause한다. task terminal 결과와 exact VM status/config를 확인하되 handler가 pause한 ambiguous phase를 임의 success/failed로 바꾸지 않는다.
- stored clone/start task가 terminal non-OK여도 strict exact VM status GET이 `404`로 부재를 확인할 때만 failed로 닫는다. timeout, permission 오류, 빈 payload와 target 존재는 부재로 해석하지 않는다.
- persisted 성공 fingerprint와 fresh exact status/config, artifact content/checksum을 확인한 뒤 fenced transaction에서 request/job/artifact·Operation 결과·recovery completion·lock release를 commit한다. stale lease와 손상된 artifact는 projector를 실행하거나 현재 VM 기록을 덮어쓰지 못한다.
- approved Operation과 exact owned lock만 있고 recovery item/request가 없는 current contract-marked acquire 직후 crash는 operator observe가 mutation 없이 `blocked`로 닫을 수 있다. marker가 없거나 task/effect evidence가 있으면 이 no-effect 경로를 사용하지 않는다.
- Operation 상세의 Post-create readiness evidence에서 status/exists, config fingerprint, readiness checks, artifact id/checksum과 workload link를 대조한다. 별도 readiness endpoint의 Jobs evidence는 exact Create owner와 실제 artifact job/type/checksum까지 일치할 때만 Operation에 연결된다. Jobs-only 결과를 임의 owner에 연결하지 않고, projection 실패 시 Proxmox VM을 삭제·재생성하는 자동 보상을 하지 않는다.

### Graceful VM Shutdown

- `POST /api/v1/nodes/{node_id}/vms/{vmid}/actions/shutdown`은 operator role, `vm_shutdown_acknowledged=true`, non-empty idempotency key와 fresh running target context를 요구한다.
- backend는 QEMU `status/shutdown`만 호출한다. timeout, guest shutdown 실패 또는 ambiguous result를 hard `stop`, reboot, 새 idempotency key 재호출로 보상하지 않는다.
- task `stopped/OK`와 direct VM `stopped`가 함께 확인된 경우에만 성공이다. 둘 중 하나가 unknown/mismatch이면 Operation 상세의 recovery/target lock과 Proxmox task/current status를 읽기 전용으로 대조한다.
- live smoke는 정확한 cluster/node/VMID, 현재 workload 영향, 재기동 책임과 사용자 run-specific 승인을 별도로 확보한 경우에만 실행한다. 구현 검증만으로 production VM 종료 권한이 생기지 않는다.

### Guided `qm unlock` expiry와 stale instruction

- active instruction은 Operation 상태가 `awaiting_operator`, server expiry가 미래이고 recorded/current target lock의 id/type/owner/cluster/VMID/scope와 status `active`가 모두 정확하며 `instruction_state.active=true`인 경우뿐이다. 그 밖의 command는 historical `do_not_execute` evidence다.
- initial GET eligibility 뒤 provisional `planned` Operation→recovery item/lease→target lock→atomic exact binding→authoritative config/task recheck 순서로 handoff한다. instruction handoff crash는 같은 binding 아래 같은 digest의 bundle만 공개할 수 있다. checksum-valid no-bundle/no-exposed plan에서 item만 유실됐으면 복원하며 exact own lock도 없으면 Proxmox GET 없이 `blocked`로 닫는다. foreign lock은 변경하지 않는다.
- attestation 없이 expiry가 지나면 original config lock이 그대로 존재하고 active task가 없으며 exact target lock이 유지됨을 GET으로 확인한 경우만 `expired`와 lock release가 가능하다. config lock 부재·변경, active task, lock mismatch 또는 observation 불가는 effect 가능성을 보존한다.
- 만료된 command를 새로 실행하지 않는다. 이미 실행한 사실이 있다면 `command_executed=true` late attestation만 기록하며 Operation은 `needs_reconciliation`으로 다시 열린다. missing/replaced/stale/reconciliation-required lock 또는 invalid expiry도 late evidence로만 취급한다.
- non-late `awaiting_verification`/`verifying`은 GET-only handler가 재개할 수 있다. late attestation은 generic/background recovery가 GET하지 않고 `GUIDED_QM_LATE_ATTESTATION_MANUAL_VERIFICATION_REQUIRED`로 pause한다. 기존 verification endpoint만 manual operator authority이며 exact recorded/current lock이 여전히 `active`일 때만 config lock과 active task를 GET한다. recovery handler와 API에는 `qm` shell executor가 없다.

### Durable target lock과 retained ambiguity

- VM Start, VM Shutdown, Create VM과 Guided `qm unlock`은 현재 `GJALLAR_CLUSTER_ID`/VMID의 PostgreSQL `proxmox_locator` lock을 공유한다. node가 달라도 같은 VMID는 같은 target이다.
- 네 action의 파일 잠금 생성·cleanup·port는 제거됐다. PostgreSQL locator lock의 owner·lock ID와 recovery lease fence로 조정하며, terminal projection·recovery completion·잠금 해제는 DB transaction으로 처리한다. lease 만료만으로 잠금을 해제하지 않는다.
- API evidence에는 target, owner, lock id, operation type과 획득 시각만 노출하며 absolute filesystem path와 recovery lease token은 노출하지 않는다. 저장된 과거 file guard evidence는 읽기 호환 자료이며 현재 파일 cleanup을 실행하지 않는다.
- ambiguous result에서 durable lock은 의도적으로 남는다. lease expiry, backend process 종료 또는 timeout만으로 stale이라고 판단하거나 삭제하지 않는다.
- operator-triggered recovery observe endpoint는 있지만 arbitrary unlock endpoint는 아니다. exact job/request evidence, UPID가 있으면 task, Proxmox actual VM state와 active task를 먼저 확인하고 backend가 advertise한 observe action만 사용한다.
- 수동 복구가 불가피하면 해당 target mutation을 중지하고 operation/task/checkpoint/actual state와 compatibility projection을 대조한 뒤 승인된 roll-forward 절차를 만든다. DB row 직접 삭제와 wildcard lock directory 삭제는 금지한다.

### Task OK와 post-check 불일치

- success로 수동 변경하지 않는다.
- expected/observed target, node, power/config/fingerprint와 active task를 비교한다.
- external effect를 reverse action으로 자동 보상하지 않는다.

## 9. 검증 명령

저장소 root에서 변경 범위에 맞는 명령을 실행한다.

| 명령 | 확인 대상 |
|---|---|
| `git diff --check` | whitespace와 patch 오류 |
| `PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests/contracts/test_legacy_backend_cleanup.py` | 문서 구조·상대 링크·anchor와 레거시 제거 계약 |
| `pnpm run test:backend` | local venv의 backend tests |
| `pnpm run test:frontend` | executable `frontend/tests/*.mjs` |
| `pnpm run lint:frontend` | ESLint, warning 0 |
| `pnpm run build:frontend` | Vite production build |
| `pnpm run test:client` | 독립 client의 mock transport·keyring·bootstrap tests |
| `pnpm run verify` | client test → backend test → frontend test → lint → build |
| `pnpm run test:backend:container` | Python 3.13 `backend-test` Docker stage |
| `pnpm run test:client:container` | Python 3.13 독립 client-test image build |
| `pnpm run verify:container` | client·backend test image와 production image build (서비스 기동 없음) |

- Docker frontend stage는 Node 24/pnpm 10.34.5로 frozen install 후 test·lint·build를 실행한다. backend-test stage는 Python 3.13에서 pytest를 실행한다.
- frontend test 일부는 source text/regex contract이며 browser 동작 검증과 같지 않다. 변경에 맞는 직접 확인이 별도로 필요할 수 있다.
- 이 명령 목록이나 과거 Plan의 통과 기록은 현재 checkout에서 검증을 실행했다는 의미가 아니다. 완료 보고에는 실제 명령·결과·미실행 범위를 구분한다.
- venv 또는 frontend dependency가 없으면 install 전 검증을 성공으로 보고하지 않는다.
- live smoke는 이 기본 명령에 포함하지 않는다.

## 10. 증거 보존

- canonical Operation current state와 checksum-linked event는 PostgreSQL `operations`, `operation_events`에, coordination은 `operation_recovery_items`, `operation_locks`에 저장된다. 기존 Jobs/Artifacts와 Create request는 입력·작업 이력으로 병행하며 현대 Create의 workload 결과는 Operation에 저장한다.
- `operation_events` checksum chain은 application-level tamper evidence지만 external WORM/signing은 아니다. `job_runs` 최신 projection과 `job_artifacts` upsert 구조도 compliance-grade append-only audit가 아니다.
- [현재 설계 기준](architecture.md)에 따라 선택적 프리셋은 기존 DB에 유지하고 현재 저장 단위의 입력·검토·승인·작업 기록은 자동 만료·삭제 없이 보존한다. 장기 archive·삭제·이관은 실제 용량과 승인·감사·replay·recovery consumer를 검토한 별도 작업이다. 저장량·백업량이 늘 수 있으며 모든 입력·artifact revision의 불변 보존을 보장하지 않는다.
- historical approved live-smoke 원본은 [정리 전 원본 묶음](archive/README.md)에 보존한다.
- evidence 문서의 과거 제품 방향이나 절차를 현재 운영 기준으로 재사용하지 않는다.

## 11. 알려진 운영 공백

- `/health`는 DB/Proxmox deep readiness가 아니다.
- degraded 상태에서 조회할 durable stale inventory snapshot은 아직 없다.
- 네 action의 GET-only durable restart handler가 있지만 background runner는 기본 비활성이다. Create 중간 phase는 관찰만 가능하고 나머지 mutation을 자동 이어서 실행하지 않는다.
- Create는 검토 단계부터 DB에 쓰며 request/Jobs/artifact는 승인·replay·recovery consumer에 계속 필요하다. 검토 계산·저장 분리와 current-workload writer 제거는 구현됐고, [현재 설계 기준](architecture.md)가 현재 저장 정책을 확정한다. 장기 consumer·archive 이관은 별도 설계다.
- Start/Shutdown은 terminal Operation을 기록한 뒤에도 Jobs projection·recovery completion·DB lock release가 남을 수 있다. status와 `coordination_incomplete`/recovery/lock을 함께 확인한다.
- job/artifact는 공통 append-only operation audit가 아니다.
- fenced operator observe API는 있지만 arbitrary force-complete/unlock, reverse compensation과 ambiguous Create effect를 승인하는 generic manual resolution API는 없다.
- recovery runner는 API process와 resource를 공유하며 concurrency 1이다. 처리량/SLA와 별도 worker 분리 기준은 미확정이다.
- Guided `qm unlock`에는 의도적으로 backend command executor가 없으며 recovery는 expiry/verification observation만 재개한다.

### 상단 연결·관찰 표시

API의 state/freshness와 실행 gate는 그대로 유지한다. authoritative base snapshot이 있으면 상단에 `Proxmox 연결됨`을 표시하고, 전체 source 완전성에 따라 `관찰 완료` 또는 `관찰 일부 누락`을 따로 표시한다. 조회 중은 `확인 중`, 미설정은 `설정 필요`, 요청 실패·snapshot 부재는 `연결 확인 필요`다. `연결됨`만으로 모든 VM 내부 정보 또는 action 실행 가능성을 보장하지 않는다.

## 파일 잠금 제거 버전으로 전환

[현재 설계 기준](architecture.md)에 따라 mutation 진입을 중지하고 기존 worker를 정지한 후 미확정 Operation·lock을 관찰한다. 구버전/신버전 worker를 혼합 실행하지 않는다. 새 버전은 PostgreSQL lock만 사용하며 옛 lock 파일을 자동 삭제하지 않는다.

Start/Shutdown의 과거 `pre_dispatch_file_guard_cleaned=true`는 기존 no-effect 조건과 exact DB lock 검증을 함께 충족할 때만 읽기 호환한다. 새 기록은 `pre_dispatch_no_effect_verified`를 사용한다. 기록 없는 미확정 작업을 추정해서 해제하지 않는다. 신규 Create는 `vm_instances`를 갱신하지 않으므로 구버전 단순 rollback보다 roll-forward를 우선한다.


## M1 client와 관리형 bootstrap

M1-1·M1-2의 코드·격리 검증 경로다. 실제 OS keyring·PostgreSQL 동시성·macOS/Linux VM 설치는 별도 검증해야 하며 전체 M1 완료가 아니다. 새 Proxmox 로그인·MFA·token 발급·credential DB는 아직 없다. 기존 env 연결이 있는 Gjallar 서버를 client에서 조회할 수 있고, 미설정 서버는 `unconfigured`를 그대로 표시한다.

### Client 준비와 기존 서버 연결

Python 3.13 이상과 독립 client만 필요하다. 원격 연결에는 Docker·로컬 DB·Proxmox token이 필요 없다. 개발 검증용 설치는 저장소 안에서 수행한다.

```bash
python3.13 -m venv client/.venv
client/.venv/bin/pip install --require-hashes -r client/requirements.lock -r client/requirements-dev.lock
client/.venv/bin/pip install --no-deps ./client
client/.venv/bin/gjallar connect primary https://gjallar.example.com
client/.venv/bin/gjallar login --connection primary
client/.venv/bin/gjallar status
client/.venv/bin/gjallar connection status
client/.venv/bin/gjallar nodes
client/.venv/bin/gjallar vms
client/.venv/bin/gjallar templates
client/.venv/bin/gjallar connection list
client/.venv/bin/gjallar connection use primary
client/.venv/bin/gjallar logout
```

lock 재생성은 `uv lock --project client`, `uv export --project client --no-emit-project --no-dev --format requirements-txt --output-file client/requirements.lock`, `uv export --project client --no-emit-project --only-group dev --format requirements-txt --output-file client/requirements-dev.lock`이다. `uv sync --project client --frozen`도 개발 설치에 사용할 수 있다. production image에는 client 의존성을 넣지 않는다.

- 인자 없는 `gjallar` 또는 `gjallar tui`는 두 시작 경로와 로그인·연결 선택·조회를 제공하는 동기식 메뉴 TUI다. 전체 VM 관리 TUI가 아니다.
- 기본 session 저장은 macOS Keychain/Linux SecretService만 허용한다. 사용할 수 없거나 잠긴 경우 자동 fallback 없이 실패한다. headless에서는 `gjallar --session-mode memory tui`를 명시적으로 실행한다. 이 프로세스 안에서 로그인·조회·전환을 계속하며 종료 후 cookie를 보관하지 않는다. 비밀번호는 항상 비표시 입력이다.
- 설정 경로는 `${XDG_CONFIG_HOME:-~/.config}/gjallar`, `--config-dir`로 변경 가능하다. 0700 디렉터리·0600 JSON에는 profile UUID·origin·CA 참조·cookie 이름·선택만 저장한다. 별칭을 덮어쓰지 않는다. session은 UUID/origin/cookie 이름별로 분리한다.
- HTTPS 검증은 필수다. HTTP는 `127.0.0.1`·`::1` 같은 literal loopback에만 허용한다. URL userinfo/path prefix/query/fragment·redirect·원격 HTTP는 거부한다. private CA는 `connect ... --ca-file /path/to/ca.pem`, 커스텀 cookie는 `--cookie-name`을 사용한다. proxy 환경 변수는 자동 사용하지 않는다.
- CLI 결과는 JSON 하나와 종료 코드다. 입력 prompt/진행 안내는 stderr, TUI는 사람이 읽는 메뉴다. 0 정상(부분 관찰은 warning 포함), 2 입력, 3 로그인/session 만료, 4 권한, 5 TLS/통신/서버 계약, 6 Proxmox 미설정/관찰 불가, 7 저장/설치 오류, 130 중단이다. 연결 관찰의 `observed_at`·`freshness`·`availability`를 확인한다.
- logout 통신 실패에도 로컬 cookie 삭제를 시도하며 서버 폐기 미확인을 오류로 알린다. keyring 삭제 자체가 실패하면 삭제 성공을 주장하지 않는다. 서버 관리자 sessions 화면에서 폐기하거나 만료를 기다린다. TUI 종료는 logout·서비스 stop·Proxmox token 폐기를 호출하지 않는다.

### 새 로컬 설치 (별도 실행 승인·검증 대상)

다음 명령은 실제 설치·서비스 기동을 수반한다. 이번 구현 작업에서는 실행하지 않았다. 새 disposable Linux VM/macOS 환경과 정확한 설치 경로·port를 지정해 승인 후 실행한다. 기존 운영 DB/volume에 적용하지 않는다.

```bash
docker build -t gjallar:local .
client/.venv/bin/gjallar --session-mode memory bootstrap --install-dir "$HOME/.local/share/gjallar" --port 8000 --image gjallar:local
```

현재 배포 입력은 사용자가 준비한 **이번 코드의 이미지**이며 공개 release registry/서명된 배포 manifest는 아직 제공하지 않는다. 앱 이미지를 자동 build하지 않는다. PostgreSQL은 `postgres:17-bookworm`을 가져와 실제 image ID로 고정하고, 앱도 image ID로 고정한다. 재시작에서 tag를 다시 해석하지 않으며 PostgreSQL major를 변경하는 option은 없다. 검증된 patch/digest의 공개 release 배포와 OS별 지원 확정은 후속 검증이다.

1. Linux/macOS amd64·arm64, Compose 2.20 이상, local Unix-socket Docker context·Linux engine, engine/image CPU 일치, loopback port, 전용 설치 경로와 기존 파일/volume을 검사한다. Linux 배포판별·macOS 버전별 지원 완료 선언은 아직 하지 않는다. Docker가 없으면 공식 설치 링크를 안내하고 중단한다. 패키지·권한·Docker 서비스를 자동 설치/기동하지 않는다.
2. 새로운 UUID/project/volume을 기록하고 전용 `secrets/`를 준비한다. postgres superuser·제한된 `gjallar` DB role의 비밀번호와 DB URL은 host 0600 전용 파일이며 manifest/Compose에는 파일 참조만 있다. 평문 일반 설정 fallback이 아니다. host 접근 통제·디스크 암호화·secret 별도 backup은 운영 책임이다. PostgreSQL용 secret은 root wrapper가 컨테이너 tmpfs에 postgres 소유 0400으로 복사하며 host 파일 권한을 넓히지 않는다.
3. named volume label과 manifest identity를 확인한다. DB 최초 실행 전 `storage_ready`를 기록해 이후 volume 유실 시 빈 DB 재생성을 금지한다. DB에는 빈 schema에서만 `gjallar_installation` marker를 만들고 명시적 `init-schema`가 Alembic/초기 profile seed를 실행한다. marker 없는 기존 DB·identity 불일치는 거부한다.
4. 최초 관리자 입력은 server maintenance의 stdin으로 전달한다. 현재 head·설치 marker·users 전체 0건·업무 이력 부재를 검사하고 users write lock 아래 관리자·account audit·ready marker를 같은 transaction에 기록한다. 기존 계정/비밀번호를 덮어쓰지 않는다. commit 후 응답 유실은 재실행에서 ready를 읽어 관리자 입력을 건너뛴다.
5. 일반 serve는 DB revision/ready를 확인하고 Uvicorn만 실행한다. Compose 앱 health 후 웹 URL을 안내하고 공통 client flow로 Gjallar 로그인·연결 관찰을 진행한다. Proxmox 미설정은 설치 성공과 별도로 표시한다. 웹은 같은 Gjallar 이미지에서 제공한다.

### 재시작·상태·종료·업그레이드와 복구

```bash
client/.venv/bin/gjallar service status --install-dir "$HOME/.local/share/gjallar"
client/.venv/bin/gjallar service start --install-dir "$HOME/.local/share/gjallar"
client/.venv/bin/gjallar service stop --install-dir "$HOME/.local/share/gjallar"
client/.venv/bin/gjallar upgrade --install-dir "$HOME/.local/share/gjallar" --image gjallar:next
```

- 설치 중단은 **같은 경로/port**로 bootstrap을 재실행한다. ready 설치의 bootstrap은 기존 이미지를 유지하고 start로 간다. 다른 `--image`는 upgrade 명령으로 안내한다. start는 migration·seed·admin을 실행하지 않는다.
- stop은 앱 다음 PostgreSQL을 중지하며 volume/config/계정/작업 기록을 남긴다. `down -v`, uninstall, prune, DB major upgrade·데이터 이동/삭제를 제공하지 않는다.
- upgrade는 후보 이미지의 현재 DB head/identity/ready 검사에 통과한 **동일 schema** 전환만 한다. 이전 두 설정을 `before-upgrade-*`에 보존하고 `upgrade.json`으로 두 파일 교체의 중단을 복구한다. status가 `upgrade_pending`이면 service start로 이어간다. DB revision 변경은 앱을 정지하기 전에 거부하고 기존 DB migration의 별도 backup/승인 절차로 보낸다. 되돌릴 때도 schema가 같은 기존 image ID만 사용한다. image prune을 하지 않고 이전 이미지와 volume을 보존한다.
- missing/손상 secret·누락된 기존 volume·외부 수정 config·identity 충돌은 자동 덮어쓰기/재생성하지 않는다. backup에서 해당 설치의 원본을 복구해야 한다. initdb 자체가 불완전한 volume도 삭제하지 않는다. PostgreSQL 로그/파일을 검토하는 별도 복구가 필요할 수 있다. CLI 오류는 subprocess 원문을 출력하지 않으므로 민감정보를 제외한 정확한 단계와 Docker 상태를 확인한다.
- 기본 공개는 `127.0.0.1:<port>`뿐이며 DB port는 publish하지 않는다. 원격 HTTP 공개 option은 없다. 원격 브라우저 공개는 별도 검증된 TLS proxy·canonical HTTPS origin·Secure cookie·SameSite 정책을 먼저 준비한 별도 배포 구성에서만 수행한다. 현재 bootstrap은 proxy를 자동 설치하지 않고 수동 변경된 관리형 Compose를 덮어쓰지 않는다. Linux VM의 로컬 웹 검증에는 승인된 SSH tunnel을 사용할 수 있다.

### 실제 환경에서 남은 검증 순서

1. disposable Linux VM 및 macOS의 Docker/Compose·CPU·OS keyring/명시적 memory 경로를 확인하고 위 새 설치 명령을 실행한다. 원격 연결만 선택했을 때 Docker/DB가 필요 없는지도 별도로 확인한다.
2. 전용 PostgreSQL 테스트 DB URL로 `backend/tests/integration/test_installation_postgresql.py`의 두 동시성/lock 검사를 실행한다. 기존 운영 DB를 테스트 대상으로 사용하지 않는다.
3. 관리자 생성 전/후, migration/응답 유실·서비스 기동 전후 중단을 재현해 같은 경로로 재실행하고 사용자/hash·volume identity·이력 보존을 확인한다. secret이 프로세스 argv/환경 값·Compose 일반 설정·로그에 나타나지 않는지 확인한다.
4. 브라우저 login/origin/cookie·CLI role·TUI 종료 후 서비스 유지·stop/start·동일 schema upgrade와 실패 복구를 확인한다. 필요 시 별도 승인된 TLS 원격 공개를 검증한다.
5. Proxmox 미설정은 `unconfigured`여야 한다. 기존 env 연결의 실제 노드/VM/template 동등성은 정확한 live target·조회 영향 승인 후 확인한다. 새 PVE token 등록 완료로 표시하지 않는다.
