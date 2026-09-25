# 운영 Runbook

- 상태: `APPROVED`
- 최종 검토일: `2026-09-07`
- 부분 검토: `2026-09-18`, client·관리형 bootstrap·Proxmox 등록의 구현/검증 상태와 최신 제품 방향 대조 (이번 갱신에서 실제 설치/PVE 재검증 없음)
- 적용 범위: 현재 FastAPI/React single image, PostgreSQL과 독립 Python client·관리형 Compose 설치

이 문서는 현재 코드의 환경 준비·실행·검증·장애 대응을 위한 단일 절차 기준이다. [문서 홈](README.md), [현재 API](architecture.md), [작업 lifecycle](architecture.md)에서 관련 계약을 찾는다. 템플릿 직접 입력과 선택적 DB 프리셋은 구현됐으며, 아래 운영 절차는 아키텍처의 현재 이력·compatibility 저장 계약을 따른다.

제품 목표와 웹 UI 개편 방향은 [PRD](prd.md), 웹·CLI 기본 기능의 구현 순서와 완료 기준은 [로드맵](roadmap.md)을 따른다. 정지 VM 이동은 아래 제한된 구현 절차와 실환경 검증 대기를 구분한다. 별도 VM 복원은 아래 절차와 실환경 검증 대기를 구분한다. 템플릿 제작/검사·사용량 추이/알림 이력은 아래 구현 절차와 실환경 검증 대기를 구분한다. 구현된 기능만 이 문서에 실행 절차로 추가한다. 과거 작업의 M1-1~M1-5 검증 기록과 현재 로드맵의 M1~M6 완료 상태는 구분한다.

고위험 변경과 live 실행 승인 경계는 [AGENTS.md](../AGENTS.md)를 따른다. 환경과 검증 명령은 이 문서에서만 관리한다.

## 1. 사전 조건

- local 기준: Python 3.13, Node.js 24, pnpm 10.34.5, PostgreSQL. `python3.13`이 다른 이름·경로라면 명령의 실행 파일만 해당 경로로 바꾼다.
- container 기준: Docker와 PostgreSQL 접근 경로.
- 필수 설정: `GJALLAR_DATABASE_URL`; target coordination identity는 `GJALLAR_CLUSTER_ID`이며 기본값은 `gjallar-mvp`다.
- Proxmox 관찰 시: 기존 env 연결 또는 등록·활성화한 관리형 연결. env 경로는 API URL·token ID·token secret·TLS 정책을 설정하고, 관리형 경로는 아래 등록·암호화 키 절차를 따른다. 관리형 연결은 read와 선택적 power/compute/create/disk/network/clone를 지원하며 Guided 실행 권한은 제공하지 않는다.
- `.env`, password, token, private key를 repository, command history, log, artifact에 남기지 않는다.

product runtime은 Proxmox 설정 누락이나 연결 실패를 fake inventory로 대체하지 않는다. authoritative snapshot을 얻으면 연결은 `live/fresh`로 표시한다. 항목별 조회 누락은 availability에 남기며 전체 VM 작업을 차단하는 `partial` 연결 상태는 사용하지 않는다. Create 입력·검토는 일부 항목이 누락된 base snapshot에서도 가능하다. Create 실행은 guest agent 외 source의 complete 관찰을 요구한다. 고정 IP는 입력한 주소의 ping 응답과 기존 VM 설정·guest agent IP 정보를 함께 확인한다. 어느 쪽이든 점유가 발견되면 red로 차단하며, 점유 미발견·조회 불가는 yellow로 직접 확보한 IP인지 확인받는다. 기존 VM의 guest agent 누락만으로 차단하지 않는다. DHCP discovery 경고와 최초 mutation 직전 재검증은 유지한다. Start/Shutdown은 새 snapshot에서 해당 VM의 config/detail 조회와 기존 대상·상태 조건을 확인한다. 해당 정보 조회 실패는 `PROXMOX_VM_OBSERVATION_UNAVAILABLE`과 대상·source로 안내한다. Guided의 별도 실행 조건은 유지한다. snapshot이 없는 경우에만 inventory-dependent 읽기 화면을 연결 안내로 차단한다.

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

### 관리형 Proxmox 등록 (지원 조합·운영 복구 검증 미완료)

웹 `/settings/proxmox`의 새 연결은 자원 ID 입력 없이 전체 노드·VM·템플릿·스토리지·네트워크를 조회한다. 새 자원도 자동 발견한다. 허용할 작업은 별도 선택하며 선택하지 않으면 read-only다. 선택 작업은 클러스터 전체에 적용되지만 실제 실행의 대상·권한·검토·잠금 검사는 유지한다. 기존 token import는 필요한 권한이 토큰에 이미 있어야 하며 upstream 권한을 바꾸지 않는다. 기존 제한 연결은 새 등록→검증→활성화→모든 서버 process 재시작으로 전환한다.

기본 CLI는 `gjallar proxmox-setup`(셸 안에서는 `proxmox-setup`)이다. Proxmox 주소에 IP만 입력해도 HTTPS/8006으로 정규화하고 계정은 Enter 또는 `root`이면 `root@pam`으로 처리한다. 인증서 SHA256 신뢰 확인 후 비밀번호를 입력하고 전체 연결을 확인하면 전용 토큰을 발급·암호화 저장·검증·전환한다. 노드·VM·스토리지·bridge·기능별 질문은 없다. 최초 신뢰할 지문은 Proxmox 서버 인증서와 대조하며, 이후 인증서가 변경되면 비밀번호/token 전송 전에 차단된다. 비밀번호는 저장하지 않는다.

전환 후 모든 Gjallar 서버 프로세스를 재시작한다. bootstrap 설치는 같은 설치 경로로 `gjallar service stop --install-dir <경로>` 후 `gjallar service start --install-dir <경로>`를 실행한다. 웹·CLI에서 이후 추가된 자원도 재등록 없이 조회·관리한다. 토큰 유효기간은 30일이며 만료 전에 새 등록·전환으로 갱신한다. 이전 토큰은 자동 폐기하지 않는다. CLI와 서버 이미지를 모두 이번 코드로 갱신해야 하며 bootstrap이 기존 설치 이미지를 자동 교체하지 않는다.

기존 연결은 자동 확대되지 않는다. 대상별 제한·기존 env 가져오기와 상세 복구는 `gjallar proxmox-setup --advanced`를 사용한다. 아래 기능별 scope 선택 설명은 이 제한 연결 및 기존 웹/TUI 상세 등록에 적용한다. 기본 전체 연결은 개별 scope 등록을 요구하지 않지만 VM 작업 자체의 지원 조건·검토·실행 확인은 유지한다.

로그인·MFA·token 발급·ACL·암호화 저장·전환·폐기 흐름은 구현돼 있다. 사용자는 `2026-09-18` 실제 Proxmox 연결 성공을 확인했다. 정확한 연결 방식·package/realm/MFA/TLS 조합과 등록 중단·전환·폐기까지 검증했다는 근거는 아니므로 아래 전체 지원·복구 검증은 별도로 남긴다.

신규 manifest v2 bootstrap은 installation UUID와 0600 `secrets/credential_key`를 준비하고 서버에 read-only로 mount한다. master key 원문은 env·manifest·DB에 넣지 않는다. 기존 manifest v1의 start/status/stop 호환은 유지하지만 자동 v2 변환·schema upgrade는 제공하지 않는다. 기존/운영 설치는 아래 migration·identity·키 backup 계획을 먼저 세우며 관리형 Compose를 임의로 수정해 검사를 우회하지 않는다.

1. 현재 DB head는 `20260919_0042`다. 관리형 연결의 `20260917_0030`은 `proxmox_connections`, `proxmox_credentials`, `proxmox_registration_attempts`를 추가하며 기존 env token이나 이력을 이동하지 않는다. 후속 0031~0041은 VM 작업, 0042는 host configuration의 lock/action 계약을 확장한다. 기존 DB는 backup/검증/정확한 대상 승인 후 one-off upgrade한다. `0029` 이전 DB는 앞의 hard-zero preflight도 필요하다. downgrade는 credential/audit 삭제를 막기 위해 거부한다. 새 코드와 현재 head를 함께 배포하며 혼합 버전 운영은 하지 않는다.
2. 기존 수동 배포에 등록 기능을 추가할 때는 이 설치에서 계속 유지할 UUID를 `GJALLAR_INSTALLATION_ID`로 설정한다. 이미 installation marker가 있는 관리형 설치는 그 UUID를 유지한다. 별도 0700 디렉터리의 0600 일반 파일에 암호학적으로 생성한 32 random bytes 또는 64 ASCII hex 문자를 보관하고 `GJALLAR_CREDENTIAL_KEY_FILE`에 경로만 설정한다. trailing newline·symlink·그룹/기타 읽기 권한은 허용하지 않는다. **기존 ciphertext가 있으면 새 키를 만들지 않는다.** 이 변경은 기존 설치의 controlled migration 계획에 포함한다.
공개 CA 호환: Python 3.13의 strict X.509 검사는 일부 기본 PVE root의 KeyUsage 누락을 거부한다. 사용자가 지정한 단일 self-issued CA이며 critical BasicConstraints CA=true·KeyUsage 없음인 경우에만 RFC 형식 strict 검사를 완화하고 인증서 서명·주소·기간 검증은 유지한다. 현대 CA·system trust·복수 CA bundle은 기존 strict 정책을 유지한다. 잘못된 CA/hostname·만료 root/leaf·미래 leaf·잘못된 server 용도는 실제 TLS handshake 테스트로 거부를 확인했다. CA 원본·PVE 인증서·호스트 trust store를 변경하지 않으며 검증 실패 시 재시도나 insecure fallback은 없다. [Python SSL 변경 근거](https://docs.python.org/3/library/ssl.html#create_default_context).

3. Gjallar 관리자로 로그인한 뒤 웹 `설정 → Proxmox 연결`, CLI `gjallar proxmox-setup`, TUI `p`를 사용한다. 웹에 등록 이력이 있으면 먼저 기존 등록을 선택하거나 `새 연결 등록 준비`를 누른다. 신규 입력에서 기능별 권한을 펼쳐 선택하며 접힌 제목의 선택 개수와 최종 권한 계획을 함께 확인한다. 이력이 없는 첫 등록은 바로 입력 폼을 표시한다. 기존 서버에 접속하는 client에는 Proxmox token/key 파일이 필요 없다. HTTPS endpoint·pam/pve owner·선택 자원·공개 CA를 입력한다. 현재 발급 검증 대상은 사용자 제공 `9.0.11`이며 실제 package/realm 지원 검증은 별도다.
4. 비밀번호/필요한 TOTP를 비표시 입력하고 권한 계획의 endpoint·owner/token ID·대상·만료·역할/ACL을 확인한다. wizard 발급 token은 30일이며 API는 5분 초과·90일 이내다. 기본 read와 선택적 power/compute/create/disk/network/clone를 제공한다. 기존 TUI 등록 질문은 read/power를 유지한다. Guided는 이 관리형 profile에서 차단된다. 기존 env token import는 서버에서 동일 token을 가져오며 PVE token/ACL/만료일을 변경하지 않는다. import한 token의 원래 scope가 줄어드는 것은 아니며 Gjallar adapter가 선택 범위만 사용한다.
5. 발급/저장/ACL 뒤 token의 effective 권한·선택 자원 조회를 검증한다. `verified`는 아직 기존 연결을 바꾸지 않은 상태다. 명시적 전환은 fresh 재검증과 미완결 Operation·open lock·recovery 부재를 요구한다. 전환 뒤 **모든 Gjallar 서버 process를 재시작**하고 웹/CLI의 노드·VM·템플릿/연결 상태를 대조한다. 이전 token은 별도 폐기 전까지 보존된다. 기존 secret env 제거는 전환과 복구 준비 확인 후 운영자가 별도 수행한다.

전체 클러스터 노드 조회:

- 웹 `전체 현황 → 클러스터 전체`에서 선택된 모든 노드의 요약·비교표·합산 추이를 확인한다. 비교표의 노드 이름 또는 `노드 상세` 탭에서 개별 노드의 자원 구성과 기간별 추이를 조회한다. CPU는 노드 CPU 용량 가중 평균이며, 일부 노드의 관찰이 누락되면 전체 합계를 표시하지 않는다. 공유 스토리지는 중복 합산하지 않고 최대 사용률을 보여준다. 기존 `모니터링`에서는 VM·스토리지도 선택할 수 있다.
- 관리형 연결은 등록 때 명시한 `scope.nodes`만 조회한다. 같은 클러스터에 세 노드가 있어도 하나만 선택했다면 웹·CLI에는 하나만 보인다. 웹 `인프라 → Proxmox 연결` 또는 `gjallar proxmox-setup`에서 새 등록의 노드 목록에 필요한 노드 이름을 모두 입력하고, 기존 기능·VM·storage·bridge 범위와 함께 검토한다. CLI 노드 입력은 쉼표로 구분한다.
- 기존 env 토큰을 재사용하면 import 검증·활성화·전체 서버 재시작을 따른다. 노드가 늘어도 모든 VM·storage·bridge가 자동 선택되지는 않는다. VM 수·유지보수 보고서는 현재 선택 범위의 관찰이다. 숨겨진 VM/LXC가 있을 수 있으므로 `no_visible_targets`를 빈 노드나 종료 가능으로 해석하지 않는다.
- 이전 테스트에서 삭제한 VMID가 기존 VM 목록에 남으면 `PROXMOX_SCOPE_UNAVAILABLE`로 검증을 거부한다. 실제 점유와 잔여 작업을 확인하고, 존재하지 않는 기존 VMID를 제외한 새 계획을 준비한다. 검증을 우회하거나 삭제한 VM을 다시 만들지 않는다.
- 전환 후 `gjallar nodes`, 웹 전체 현황, 노드별 `gjallar metrics node <node>`, `gjallar maintenance node <node>`를 대조한다. 2026-09-20 전용 설치에서는 현재 클러스터 세 노드와 각 노드의 다섯 기간 RRD·선택 nas-server/vmbr0/vmbr2 조회를 실제 웹·CLI/API로 확인했다. VM 변경 범위는7001로 유지했으며 새 노드의 VM 변경 검증을 의미하지 않는다.

중단 복구:

- `gjallar proxmox-setup --list` 또는 웹 등록 목록으로 본인 attempt ID·상태를 읽는다. CLI는 `gjallar proxmox-setup --resume <attempt-id>`, TUI는 `p`에서 ID를 입력한다. 응답 유실 시 먼저 상태를 조회한다.
- 로그인/TOTP context는 동일 Gjallar session의 서버 메모리에 최대 5분만 유효하다. 재시작·만료·다른 worker라면 다시 로그인한다. 재로그인이 token을 재발급하지 않는다. 다중 worker 운영은 검증 전이며 최초 검증은 단일 API process로 한다.
- `token_dispatching`은 생성됐으나 응답/저장에 실패했을 수 있다. `acl_applying`은 권한 적용이 일부 끝났을 수 있다. 자동 재발급/ACL 재전송은 없다. CLI/TUI의 `observe` 또는 웹의 토큰 존재 확인을 사용한다. 저장된 secret이 있으면 같은 token 조회 검증을 재시도할 수 있다.
- 폐기는 해당 등록에서 발급한 전체 token ID를 직접 확인한 뒤 실행한다. 활성 token은 조회·조작이 중단되며 미완결 작업이 있으면 폐기를 거부한다. 응답 유실 뒤 `revocation_pending`은 metadata 부재 확인만 수행하며 DELETE를 자동 반복하지 않는다. 가져온 외부 token·공유 role·사용자는 자동 삭제하지 않는다.
- 토큰 부재 관찰만으로 늦은 발급 요청이 종료됐다고 단정하지 않는다. 소유 근거 불일치, ACL 부분 실패, 불명 발급의 강제 종료는 PVE 관리자의 정확한 요청·token 확인이 필요하다. 강제 성공·강제 종료 API는 없다.
- managed 선택 후 키/DB 오류는 `degraded`와 mutation 차단이며 env로 자동 전환하지 않는다. DB backup과 **해당 설치의 원래 키**를 분리 보관하고 UUID·cluster identity를 유지해 복원한다. 원래 키 복원 테스트는 격리 ciphertext로 통과했으나 실제 운영 backup/restore 연습은 남았다. 키가 완전히 유실되면 secret은 복구할 수 없다. key rotation·이전 revision/source 복귀를 위한 자동 명령은 아직 없으므로 운영 전환 전 별도 복구 계획을 확정한다. DB row 삭제나 stamp로 우회하지 않는다.

### 고정 IP의 ping 관찰

- ping은 Gjallar backend가 실행되는 네트워크에서 입력한 numeric IPv4 한 개에만 보낸다. Proxmox 노드·guest 내부에서 실행하거나 다른 주소를 스캔하지 않는다. 해당 VM 네트워크에 대한 routing·VLAN 접근이 없으면 결과는 제한된다.
- Linux는 `iputils-ping`, macOS는 시스템 `ping`을 사용한다. Docker image에는 `iputils-ping`이 포함된다. 별도 privileged/host-network 실행을 요구하지 않으며 현재 권한으로 실행할 수 없으면 확인 불가로 표시한다.
- 1회 전송, 프로세스 상한 3초이며 shell·DNS lookup을 사용하지 않는다. 원시 stdout/stderr는 저장하지 않는다. ping 대기는 API event loop 밖에서 처리한다.
- `reply`는 관찰된 점유, `no_reply`는 응답 없음, `unavailable`은 실행 불가다. 무응답도 방화벽·전원 상태·경로 등에 영향을 받으므로 IP 미사용을 증명하지 않는다. agent가 모두 응답해도 외부 장비·IP 예약 전체는 알 수 없다.
- Create 검토·계획·승인·preview와 최초 실행 직전 preflight에서 검사한다. DHCP에서는 ping을 수행하지 않는다. 템플릿 조건·생성 후 `boot_and_verify`의 guest agent/cloud-init 검증은 이 검사와 별개다.

### Operation recovery runner rollout

runner는 같은 FastAPI image 안의 기본 비활성 opt-in observer다. allowlist는 `vm_start_observation`, `vm_shutdown_observation`, `vm_create_observation`, `guided_qm_unlock_observation`, `vm_compute_observation`, `vm_disk_observation`이다. action-specific handler는 Proxmox GET과 local evidence/projection만 사용하며 mutation 재전송, Guided command, hard stop·reboot나 compensation을 실행하지 않는다.

enable 전:

1. maintenance window에서 모든 구버전 replica를 drain하고 완전히 중지한 뒤 위 DB migration read-only preflight와 별도 적용 승인을 완료한다.
2. one-off controlled DB upgrade 뒤 현재 migration head `20260919_0042`과 generic lock/shared history 보존을 확인한다.
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
- `unconfigured`인 관리형 설치는 관리자 로그인 후 첫 화면의 `Proxmox 연결 설정` 또는 `Settings → Proxmox 연결`에서 등록한다. 다른 역할에는 관리자 요청 안내가 표시된다. 기존 env 방식만 `PROXMOX_API_URL`, `PROXMOX_API_TOKEN_ID`, `PROXMOX_API_TOKEN_SECRET` 누락과 `GJALLAR_INVENTORY_MODE`를 확인한다. env 진단은 관리자에게 접힌 보조 정보로 제공한다.
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

- VM Start, VM Shutdown, Create VM, Guided `qm unlock`, CPU·메모리와 디스크 확장은 현재 `GJALLAR_CLUSTER_ID`/VMID의 PostgreSQL `proxmox_locator` lock을 공유한다. node가 달라도 같은 VMID는 같은 target이다.
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

PostgreSQL 통합 검사는 `GJALLAR_POSTGRES_TEST_URL`이 없으면 건너뛴다. 별도의 폐기 가능한 PostgreSQL 17 테스트 DB를 만들고 URL을 비공개 환경변수로 설정한다. 일부 검사는 초기화된 기본 schema를 요구하므로 **새 테스트 DB에만** 아래 순서로 실행한다. 실제 Gjallar 설치 DB나 운영 DB를 지정하지 않는다.

```bash
GJALLAR_DATABASE_URL="$GJALLAR_POSTGRES_TEST_URL" PYTHONPATH=backend backend/venv/bin/alembic -c backend/alembic.ini upgrade head
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests/integration
```

2026-09-20 현재 코드의 별도 tmpfs PostgreSQL 17에서 통합 검사78개가 모두 통과했다. 테스트 후 해당 임시 DB·컨테이너·임시 secret만 정리했으며 실제 설치 DB는 사용하지 않았다.

## 10. 증거 보존

- canonical Operation current state와 checksum-linked event는 PostgreSQL `operations`, `operation_events`에, coordination은 `operation_recovery_items`, `operation_locks`에 저장된다. 기존 Jobs/Artifacts와 Create request는 입력·작업 이력으로 병행하며 현대 Create의 workload 결과는 Operation에 저장한다.
- `operation_events` checksum chain은 application-level tamper evidence지만 external WORM/signing은 아니다. `job_runs` 최신 projection과 `job_artifacts` upsert 구조도 compliance-grade append-only audit가 아니다.
- [현재 설계 기준](architecture.md)에 따라 선택적 프리셋은 기존 DB에 유지하고 현재 저장 단위의 입력·검토·승인·작업 기록은 자동 만료·삭제 없이 보존한다. 장기 archive·삭제·이관은 실제 용량과 승인·감사·replay·recovery consumer를 검토한 별도 작업이다. 저장량·백업량이 늘 수 있으며 모든 입력·artifact revision의 불변 보존을 보장하지 않는다.
- historical approved live-smoke 원본은 [정리 전 원본 묶음](archive/README.md)에 보존한다.
- evidence 문서의 과거 제품 방향이나 절차를 현재 운영 기준으로 재사용하지 않는다.

## 11. 알려진 운영 공백

- `/health`는 DB/Proxmox deep readiness가 아니다.
- degraded 상태에서 조회할 durable stale inventory snapshot은 아직 없다.
- 지원 action의 GET-only durable restart handler가 있지만 background runner는 기본 비활성이다. Create 중간 phase는 관찰만 가능하고 나머지 mutation을 자동 이어서 실행하지 않는다.
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

아래는 현재 독립 client와 관리형 설치의 실행 절차다. 과거 M1-1·M1-2의 client/bootstrap과 M1-3·M1-4의 Proxmox 로그인·MFA·token 발급·credential DB 핵심 구현·격리 검증이 반영돼 있다. 전용 PostgreSQL 17 DB의 통합 검사 28개 통과는 [기존 설치·연결 기록](work/2026-09-16-m1-installation-connection.md)에 있으며 이번 문서 갱신에서 재실행한 결과는 아니다. client는 서버가 선택한 env 또는 관리형 연결의 자원을 조회하며, 미설정 서버는 `unconfigured`를 그대로 표시한다. 사용자 연결 성공 확인을 전체 설치·운영 검증 완료로 간주하지 않는다.

2026-09-19 macOS 26.6.2 arm64·Docker 28.4.0·Compose 2.39.2의 승인된 전용 설치에서 실제 bootstrap 중단 후 같은 경로 재개, 웹/CLI 로그인, 잘못된 인증 거부, service stop/start·bootstrap 재실행·같은 schema 이미지 전환 후 계정/설정/이력/secret 보존을 확인했다. CLI는 명시적 memory 세션으로 검사했다. [현재 work의 설치 근거](work/2026-09-19-basic-features.md)를 따른다. 최초 시도 Docker 오류 원인은 미확정이며 OS keyring·Linux 설치·관리형 PVE 등록/권한 갱신·운영 복구 지원 검증은 남아 있다.

bootstrap은 검증한 app/PostgreSQL 이미지에 `gjallar-pinned:sha256-<digest>` 로컬 보존 tag를 추가하고 manifest는 계속 정확한 image ID를 사용한다. 원래 개발 tag가 새 빌드로 이동해도 설치 이미지를 보존하기 위한 참조다. 현재 설치·되돌릴 이미지의 보존 tag는 유지하며 자동 삭제하지 않는다. 실행 중인 설치의 upgrade 전 readiness는 해당 기존 컨테이너에서, 정지 설치는 one-off maintenance에서 확인한다. 후보 이미지는 별도 schema/설치 identity 검사에 통과해야 전환하며 migration은 실행하지 않는다.

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

- 인자 없는 `gjallar`는 CLI 도움말을 표시한다. `gjallar tui`는 Python curses 기반 전체 화면 TUI다. 두 시작 경로와 로그인·연결 선택·조회를 제공한다. 대화형 터미널과 최소 76열 × 20행이 필요하다. `Tab`/좌우 방향키로 패널 전환, 상하 방향키로 선택, `Enter`로 열기, `/`로 검색, `l`로 로그인, `r`로 새로고침, `?`로 도움말, `q`로 종료한다. 저장된 연결은 목록에서 고르고 계정에는 설치 시 만든 이름(예: `admin`)을 입력한다. `Esc`는 현재 입력을 취소하며 이미 완료된 설치·등록 단계를 되돌리지 않는다. 비밀번호는 마스킹하고 서버의 제어문자는 escape한다. 전체 VM 관리 TUI는 아니다.
- 기본 session 저장은 macOS Keychain/Linux SecretService만 허용한다. 사용할 수 없거나 잠긴 경우 자동 fallback 없이 실패한다. OS keyring이 없는 대화형 터미널에서는 `gjallar --session-mode memory shell`을 명시적으로 실행한다. 전체 화면이 필요하면 `tui`도 사용할 수 있다. 이 프로세스 안에서 로그인·조회·전환을 계속하며 종료 후 cookie를 보관하지 않는다. 비밀번호는 항상 비표시 입력이다.
- 설정 경로는 `${XDG_CONFIG_HOME:-~/.config}/gjallar`, `--config-dir`로 변경 가능하다. 0700 디렉터리·0600 JSON에는 profile UUID·origin·CA 참조·cookie 이름·선택만 저장한다. 별칭을 덮어쓰지 않는다. session은 UUID/origin/cookie 이름별로 분리한다.
- HTTPS 검증은 필수다. HTTP는 `127.0.0.1`·`::1` 같은 literal loopback에만 허용한다. URL userinfo/path prefix/query/fragment·redirect·원격 HTTP는 거부한다. private CA는 `connect ... --ca-file /path/to/ca.pem`, 커스텀 cookie는 `--cookie-name`을 사용한다. proxy 환경 변수는 자동 사용하지 않는다.
- CLI는 터미널에서 사람이 읽는 표·요약, 파이프에서는 JSON 한 개를 출력한다. `--json`은 JSON을 강제하고 `--human`은 사람이 읽는 출력을 강제한다. 입력·실행 확인 prompt/진행 안내는 stderr, TUI는 별도 전체 화면이다. 0 정상(부분 관찰은 warning 포함), 2 입력, 3 로그인/session 만료, 4 권한, 5 TLS/통신/서버 계약, 6 Proxmox 미설정/관찰 불가, 7 저장/설치 오류, 8 VM 작업 차단·미완료·결과 미확정, 130 중단이다. 연결 관찰의 `observed_at`·`freshness`·`availability`를 확인한다.
- logout 통신 실패에도 로컬 cookie 삭제를 시도하며 서버 폐기 미확인을 오류로 알린다. keyring 삭제 자체가 실패하면 삭제 성공을 주장하지 않는다. 서버 관리자 sessions 화면에서 폐기하거나 만료를 기다린다. TUI 종료는 logout·서비스 stop·Proxmox token 폐기를 호출하지 않는다.

### CLI 운영 흐름

일반 명령의 `--connection`, `--config-dir`, `--session-mode`, `--json`/`--human`은 명령 앞뒤에 지정할 수 있다. `--connection`은 이번 호출의 서버를 선택하며 조회만으로 기본 선택을 바꾸지 않는다. `login` 성공과 `connection use`는 기본 선택을 저장한다. 로그인할 서버가 하나면 별칭 생략이 가능하고 여러 개면 명시적으로 고른다.

```bash
client/.venv/bin/gjallar
client/.venv/bin/gjallar connection list
client/.venv/bin/gjallar login --connection local-8000 --username admin
client/.venv/bin/gjallar status
client/.venv/bin/gjallar connection status
client/.venv/bin/gjallar nodes
client/.venv/bin/gjallar vms --json
client/.venv/bin/gjallar vm show 101
client/.venv/bin/gjallar operations list --vmid 101
```

계정명은 설치 시 만든 **Gjallar 계정**이다. 비밀번호는 비표시 prompt로만 입력한다. `bootstrap`은 설치/서비스 기동과 연결 별칭 저장까지 완료하고 별도 `login` 명령을 안내한다. 로그인 실패가 설치 실패로 보이지 않게 분리했다. 기존 TUI 설치 경로는 화면 내 로그인 단계를 유지한다.

OS keyring을 쓰지 않을 때는 `gjallar --session-mode memory shell`에서 `login --username admin`, `status`, `vms` 등을 연속 입력한다. `help`와 `exit`를 제공하며 shell 명령을 OS shell로 실행하지 않는다. `exit`는 서비스를 종료하거나 로그아웃하지 않으며 memory session만 보관하지 않는다. 일반 단발 memory 명령 사이에는 session이 유지되지 않는다. shell 안에서는 session 모드를 바꾸거나 shell/TUI를 중첩 실행하지 않는다.

다음 변경 명령은 **예시**이며 실제 실행 전에 대상·영향 승인을 받아야 한다. `--yes`가 없으면 명시적 `yes`를 입력해야 한다. 파이프/자동화는 `--yes`가 필요하다. 요청 ID는 한 실행 의도의 고유한 64자 이하 값이며 응답 유실 시 바꾸지 않는다.

```bash
client/.venv/bin/gjallar vm start 101 --node pve --request-id start-example-101
client/.venv/bin/gjallar vm shutdown 101 --node pve --request-id shutdown-example-101
```

현재 VM의 node/VMID·이름·상태를 확인한 뒤 기존 서버 action API에 같은 idempotency key·expected context·acknowledgement를 제출한다. 서버 권한/preflight/lock을 우회하지 않는다. 강제 종료·자동 retry는 없다. 기존 start/shutdown 응답의 `job_id`는 같은 canonical Operation ID로 사용한다. CLI는 Operation을 다시 GET하고 종류·node/VMID·요청 ID를 대조한다. POST 뒤 Operation을 다시 GET해서 `succeeded`이며 coordination이 완료된 경우에만 0을 반환한다. 결과 불명은 8이며 `operations list --vmid` 또는 `operations show <ID>`로 먼저 확인한다. `operations show` 자체의 0은 **조회 성공**이지 해당 VM 작업의 성공을 뜻하지 않는다.

템플릿 기반 생성은 파일 검토와 실행을 나눈다.

```bash
client/.venv/bin/gjallar vm create example > vm-input.json
# 위 예제의 node/template/VMID/storage/network/공개 SSH 키를 실제 대상에 맞게 편집한다.
client/.venv/bin/gjallar vm create plan --file vm-input.json --request-id create-example-101 --review-file vm-review.json
client/.venv/bin/gjallar vm create execute --review-file vm-review.json --ack-yellow
client/.venv/bin/gjallar operations show create-example-101
```

- 예제의 ID·이름·사양은 실제 자원이나 추천값이 아니다. 입력은 `creation_mode`, 정확한 `vmid`, `vm_name`, `target_node_id`, `storage_id`, `bridge_id`, `power_policy`를 명시한다. `power_policy`는 `stopped`/`boot_and_verify`, mode는 `template`/`profile`이다. profile mode에서는 `profile_id`, template mode에서는 `template_node_id`/`template_vmid`를 사용한다. 노드·VM·템플릿은 목록에서 먼저 확인한다.
- `plan`은 VM을 변경하지 않지만 서버에 draft/preflight/plan·Jobs/Artifacts/Operation을 기록한다. 검토 파일에는 입력과 서버 review/checksum·연결 identity가 들어가며 0600 신규 파일만 만든다. 공개 SSH 키·게스트 계정 입력이 있으므로 검토 파일을 공용 로그·저장소에 올리지 않는다. 기존 파일을 덮어쓰지 않는다. 계획 중 오류가 나면 빈 파일이나 서버 기록이 남을 수 있으며 새 경로를 지정하기 전 기존 작업을 확인한다.
- `execute`는 같은 서버/profile 검토 파일로만 승인·미리보기·실행을 요청한다. `--ack-yellow`는 yellow 위험을 확인했다는 명시적 동의다. red는 실행하지 않는다. 서버는 checksum과 fresh 관찰을 재검증하고 drift/conflict를 차단한다. 손상 파일·권한 부족·결과 불명을 성공으로 표시하지 않는다.
- 관리형 read/power만 선택한 연결은 Create 권한이 없다. 아래 선택적 생성 권한의 새 등록·검증·전환을 거쳐야 한다. 기존 env adapter의 권한 경로를 포함해 실제 mutation 검증은 별도다.

### 새 로컬 설치 (별도 실행 승인·검증 대상)

다음 명령은 실제 설치·서비스 기동을 수반한다. 이번 구현 작업에서는 실행하지 않았다. 새 disposable Linux VM/macOS 환경과 정확한 설치 경로·port를 지정해 승인 후 실행한다. 기존 운영 DB/volume에 적용하지 않는다.

```bash
docker build -t gjallar:local .
client/.venv/bin/gjallar --session-mode memory bootstrap --install-dir "$HOME/.local/share/gjallar" --port 8000 --image gjallar:local
```

VM의 웹을 다른 컴퓨터에서 직접 열려면 신규 설치에 `--bind-address 0.0.0.0`을 지정한다. VM IP나 DNS 이름을 코드·설정에 등록할 필요는 없다.

```bash
client/.venv/bin/gjallar --session-mode memory bootstrap \
  --install-dir "$HOME/.local/share/gjallar" --image gjallar:local \
  --bind-address 0.0.0.0 --port 8000
```

설치 뒤 브라우저에서 `http://<VM IP>:8000`으로 접속한다. 앱은 모든 IPv4 interface에 공개되며 `GJALLAR_ALLOW_SAME_ORIGIN=true`로 실제 요청 주소와 Origin의 scheme·host·port가 일치하는 웹 요청과 콘솔 WebSocket을 허용한다. 다른 Origin은 기존 명시적 허용 목록 외에 허용하지 않으며, 신뢰 주소를 Origin/X-Forwarded-Host에서 만들어내지 않는다. HTTP는 로그인 정보·세션을 암호화하지 않으므로 신뢰하는 내부망에서 사용한다. VM 방화벽은 자동 변경하지 않고 DB port는 비공개다. TLS proxy 자동 구성과 원격 CLI HTTPS 정책은 변경하지 않는다. 설치 VM의 CLI는 계속 loopback을 사용한다. 대화형 마법사는 loopback 기본값이므로 외부 웹 설치는 위 명령을 사용한다.

현재 배포 입력은 사용자가 준비한 **이번 코드의 이미지**이며 공개 release registry/서명된 배포 manifest는 아직 제공하지 않는다. 앱 이미지를 자동 build하지 않는다. PostgreSQL은 `postgres:17-bookworm`을 가져와 실제 image ID로 고정하고, 앱도 image ID로 고정한다. 재시작에서 tag를 다시 해석하지 않으며 PostgreSQL major를 변경하는 option은 없다. 검증된 patch/digest의 공개 release 배포와 OS별 지원 확정은 후속 검증이다.

1. Linux/macOS amd64·arm64, Compose 2.20 이상, local Unix-socket Docker context·Linux engine, engine/image CPU 일치, 선택 bind 주소의 port, 전용 설치 경로와 기존 파일/volume을 검사한다. Linux 배포판별·macOS 버전별 지원 완료 선언은 아직 하지 않는다. Docker가 없으면 공식 설치 링크를 안내하고 중단한다. 패키지·권한·Docker 서비스를 자동 설치/기동하지 않는다.
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

- 설치 중단은 **같은 경로/port/bind-address**으로 bootstrap을 재실행한다. 외부 웹 설치의 옵션을 생략하거나 기존 설치의 공개 주소를 변경하면 거부한다. ready 설치의 bootstrap은 기존 이미지를 유지하고 start로 간다. 다른 `--image`는 upgrade 명령으로 안내한다. start는 migration·seed·admin을 실행하지 않는다.
- stop은 앱 다음 PostgreSQL을 중지하며 volume/config/계정/작업 기록을 남긴다. `down -v`, uninstall, prune, DB major upgrade·데이터 이동/삭제를 제공하지 않는다.
- upgrade는 후보 이미지의 현재 DB head/identity/ready 검사에 통과한 **동일 schema** 전환만 한다. 이전 두 설정을 `before-upgrade-*`에 보존하고 `upgrade.json`으로 두 파일 교체의 중단을 복구한다. status가 `upgrade_pending`이면 service start로 이어간다. DB revision 변경은 앱을 정지하기 전에 거부하고 기존 DB migration의 별도 backup/승인 절차로 보낸다. 되돌릴 때도 schema가 같은 기존 image ID만 사용한다. image prune을 하지 않고 이전 이미지와 volume을 보존한다.
- missing/손상 secret·누락된 기존 volume·외부 수정 config·identity 충돌은 자동 덮어쓰기/재생성하지 않는다. backup에서 해당 설치의 원본을 복구해야 한다. initdb 자체가 불완전한 volume도 삭제하지 않는다. PostgreSQL 로그/파일을 검토하는 별도 복구가 필요할 수 있다. CLI 오류는 subprocess 원문을 출력하지 않으므로 민감정보를 제외한 정확한 단계와 Docker 상태를 확인한다.
- 기본 공개는 `127.0.0.1:<port>`이며 신규 설치의 명시적 `--bind-address 0.0.0.0`로 외부 웹을 지원한다. v3 manifest에 공개 설정을 보존하며 기존 v1/v2 설치를 자동 변환하지 않는다. DB port는 publish하지 않는다. TLS proxy·canonical HTTPS origin·Secure cookie는 별도 배포 구성 대상이다. bootstrap은 proxy를 자동 설치하지 않고 수동 변경된 관리형 Compose를 덮어쓰지 않는다. loopback 설치에는 SSH tunnel을 사용할 수 있다.

### 실제 환경에서 남은 검증 순서

첫 실사용은 현재 사용할 환경 하나를 기록해 아래 흐름을 검증한다. 다른 OS/CPU/PVE 조합의 지원 확대는 후속으로 진행하며 첫 환경의 완료와 구분한다. 아래의 과거 검사 통과 기록을 현재 checkout이나 사용자 환경의 새 검증 결과로 간주하지 않는다.

1. disposable Linux VM 및 macOS의 Docker/Compose·CPU·OS keyring/명시적 memory 경로를 확인하고 위 새 설치 명령을 실행한다. 원격 연결만 선택했을 때 Docker/DB가 필요 없는지도 별도로 확인한다.
2. 전용 PostgreSQL 테스트 DB URL로 `backend/tests/integration/`을 실행한다. 별도 PostgreSQL 17 tmpfs DB에서 28개 검사가 통과했으며 setup의 중복 등록·CAS·VM admission/전환 경합도 포함한다. 기존 운영 DB를 테스트 대상으로 사용하지 않는다.
3. 관리자 생성 전/후, migration/응답 유실·서비스 기동 전후 중단을 재현해 같은 경로로 재실행하고 사용자/hash·volume identity·이력 보존을 확인한다. secret이 프로세스 argv/환경 값·Compose 일반 설정·로그에 나타나지 않는지 확인한다.
4. 브라우저 login/origin/cookie·CLI role·TUI 종료 후 서비스 유지·stop/start·동일 schema upgrade와 실패 복구를 확인한다. 필요 시 별도 승인된 TLS 원격 공개를 검증한다.
5. Proxmox 미설정은 `unconfigured`여야 한다. 정확한 live target·조회/발급/ACL/폐기 영향 승인 후 기존 env와 관리형 연결의 실제 노드/VM/template 동등성, PVE 9.0.11 로그인/TOTP·TLS·등록·중단 복구·전환·폐기를 확인한다. fixture 통과를 실제 PVE token 등록 완료로 표시하지 않는다.

### 정지 VM의 CPU·메모리 변경 (M2 VM-01)

VM 상세에서 사양·디스크·NIC는 `CPU·메모리 / 디스크 / 네트워크`, 복제·템플릿은 `VM 복제 / 템플릿 전환`, 삭제는 `VM 영구 삭제 · 되돌릴 수 없음`을 펼친다. 폼을 접어도 입력·요청·결과는 유지된다. 실행 후 결과는 해당 작업 영역과 Operation 이력에서 확인한다. 웹 콘솔은 바로 접근할 수 있으며 설정 관찰 상세는 화면 마지막에서 펼쳐 본다.

구현·격리 자동 검증과 실제 PVE 변경 검증을 구분한다. 최신 검증 상태는 [기본 기능 work](work/2026-09-19-basic-features.md)를 따른다. migration `20260919_0031`이 필요하며 운영 DB에 자동 적용하지 않는다.

관리형 VM 생성도 등록 화면·CLI에서 선택할 수 있다. 기존 조회 VM 목록과 별도로 복제할 실제 템플릿 ID, 생성 대상 VMID를 지정한다. template/node/storage/bridge와 대상 VMID가 모두 권한 계획에 들어간다. 생성 대상 ID 목록은 예약이 아니며 기존 자원이 있으면 생성 사전 검토가 거부해야 한다. 원본 템플릿의 bridge와 배포할 bridge를 모두 선택한다. 생성 대상에만 할당·설정·전원·guest-agent 실행 권한을 부여한다. PVE `VM.GuestAgent.Unrestricted`는 토큰 자체로는 넓은 권한이므로 신뢰하는 전용 토큰으로 운영하고, Gjallar는 기존 cloud-init 상태 확인 명령 외 실행을 거부한다. 생성의 웹/CLI 검토·승인·실행 절차와 Operation 확인은 기존 명령을 그대로 쓴다. 예전 read/power/compute 연결은 자동으로 생성 권한을 얻지 않는다.

1. 관리형 연결은 관리자 `설정 → Proxmox 연결` 또는 `gjallar proxmox-setup`에서 CPU·메모리 권한을 선택한다. 기존 연결은 새 등록·권한 계획 검토·새 token 검증·명시적 연결 전환·모든 서버 프로세스 재시작 순서로 갱신한다. 기존 token은 남겨두며 별도 폐기 절차를 따른다. read/power만으로 compute 권한이 생기지 않는다.
2. operator 이상으로 VM 상세의 `VM 작업 → CPU·메모리 / 디스크 / 네트워크 → CPU·메모리 변경 준비`에서 현재 값을 읽는다. 코어 수와 메모리 MiB를 입력하고 변경 내용을 검토한 뒤 실행한다. 실제 설정이 확인되어야 완료로 표시한다. 서버/브라우저 연결이 끊겼다면 표시된 요청 ID와 Operations 이력을 보존한다.
3. CLI는 같은 서버에 로그인한 뒤 다음 흐름을 사용한다. 아래 VMID·노드·변경 값은 예시이며 실제 변경 대상에 대한 승인을 대신하지 않는다.

```bash
gjallar vm compute show 40000 --node node1
gjallar vm compute plan 40000 --node node1 --cores 4 --memory-mib 4096 \
  --request-id compute-40000-review-1 --review-file compute-40000.json
gjallar vm compute execute --review-file compute-40000.json
```

`plan`은 Proxmox를 변경하지 않고 새 0600 검토 파일을 만든다. `execute`는 대상과 변경을 보여주고 명시적 확인을 받으며, `--yes`는 그 확인을 미리 제공한다. 검토 파일은 원래 서버/profile, 설정 digest·이름, 요청 ID와 값을 묶는다. 다른 서버에서 실행하거나 내용을 임의로 바꾸지 않는다. 검토 이후 VM 설정이 바뀌면 다시 조회하고 새 요청 ID·파일로 검토한다.

첫 지원은 정지된 단일 socket VM의 cores 1~128, memory 128~1048576 MiB다. 1024 MiB는 1 GiB이며 요청 범위가 호스트 여유 메모리를 보장하지는 않는다. pending 변경·PVE lock·template·vcpus/custom NUMA는 먼저 별도로 해결해야 한다. CPU 종류·balloon·디스크·네트워크와 게스트 파일시스템을 변경하지 않는다.

결과 불명·부분 반영·lease 만료는 성공이 아니다. 같은 요청의 자동 재전송은 없고 target lock을 보존한다. Operation 상세의 GET-only 관찰은 실제 값과 dispatch 완료 근거를 재확인한다. 응답 완료 근거가 없는 요청은 값이 일치해도 자동 완료하지 않는다. 강제 잠금 해제나 원래 값으로의 자동 보상은 제공하지 않으며, 별도 운영 조사와 명시적 변경이 필요하다. 외부 PVE에서 동시에 전원을 시작하는 상황은 API가 원자적으로 막아주지 않으므로 작업 동안 다른 관리 경로의 변경을 피한다. TUI는 기존 기능을 유지하며 compute 동등 지원은 후속이다.

### 정지 VM의 디스크 확장 (M2 VM-02)

관리형 연결에서 선택 VM의 `disk` 기능과 실제 volume이 있는 storage를 선택해 새 연결로 갱신한다. `VM.Config.Disk`와 선택 storage의 `Datastore.Audit/AllocateSpace`가 필요하다. 기존 read/power/compute만 선택한 연결은 자동 확대하지 않는다. migration `20260919_0032`의 운영 적용은 별도 승인한다.

웹은 VM 상세 `VM 작업 → CPU·메모리 / 디스크 / 네트워크 → 디스크 확장 준비`에서 실제 용량을 읽고 확장 후 **전체 GiB**를 검토한다. 첫 지원은 정지 VM의 NFS storage에 있는 `scsi0` raw/qcow2이며, 실제 volume 용량과 config가 일치해야 한다. 다음은 CLI 예시다.

```bash
gjallar vm disk show 40000 --node node1
gjallar vm disk plan 40000 --node node1 --size-gib 24 \
  --request-id disk-40000-review-1 --review-file disk-40000.json
gjallar vm disk execute --review-file disk-40000.json
```

`--size-gib 24`는 24 GiB로 확장한다는 뜻이며 추가 24 GiB가 아니다. 검토 파일은 서버·대상·원래 volume·digest·현재 bytes와 요청 ID를 보존한다. 같은 크기·축소·실행 중 VM·pending 변경·잠긴 VM·template·공유/읽기 전용/CDROM 디스크는 거부한다. 지원 범위를 벗어난 storage/bus는 자동 변환하지 않는다.

확장 후 PVE task의 stopped/OK와 실제 volume bytes·config size·정지 상태를 함께 확인한다. PVE task만 성공하거나 config만 커진 경우 완료가 아니다. 게스트 partition과 filesystem은 별도로 확장해야 한다. 확장을 되돌리는 축소나 자동 보상은 제공하지 않는다. 응답 유실·task 실패·실제 용량 불일치는 Operation·target lock을 보존한다. UPID가 저장됐으면 재시작 후 GET-only 복구 관찰을 사용할 수 있고, UPID가 없는 미확정 요청은 자동 완료·재전송하지 않는다. 서버 외부의 동시 설정·전원 변경은 작업 중 피한다.

### 정지 VM의 기존 NIC bridge·VLAN 변경 (VM-03)

웹의 VM 상세 → **네트워크 변경 준비**에서 현재 net0/model/MAC와 사용 가능한 bridge를 조회한다. bridge와 tag를 선택하고 변경 전후·통신 영향을 검토한 뒤 실행한다. tag를 비우면 untagged다. 정지 VM의 net0만 지원하고 VLAN tag는 VLAN-aware Linux bridge에서만 가능하다. MAC/model과 기존 옵션·게스트 IP는 유지하므로 다른 망으로 옮기면 이전 IP로 접속할 수 없을 수 있다.

관리형 연결은 `network`와 현재/대상 bridge를 명시적으로 선택해 새 등록·검증·전환하고 모든 서버 프로세스를 재시작한다. 읽기 bridge 권한만으로는 변경할 수 없다. 미적용 host network 변경이 있다면 PVE에서 해당 변경의 소유자와 의도를 확인하고 정리한 뒤 새로 검토한다. 이 기능은 호스트 설정을 적용하지 않는다.

```bash
gjallar vm network show 40000 --node <node>
gjallar vm network plan 40000 --node <node> --bridge <bridge> --vlan-tag 100 --request-id network-40000-1 --review-file /tmp/network-40000.json
gjallar vm network execute --review-file /tmp/network-40000.json
```

untagged 변경은 plan에서 `--vlan-tag` 대신 `--untagged`를 명시한다. 검토 파일은 새 파일(0600)이며 원래 target·digest·net0·request ID를 유지한다. pending·running·잠금·권한·bridge 조건 실패는 변경 전에 차단한다. 결과 미확정은 Operation·복구 조회로 확인하고 새 요청으로 재전송하거나 잠금을 강제 해제하지 않는다. PVE 설정 검증 뒤 게스트 통신은 별도로 확인한다. 운영 DB의 0033 적용과 실제 PVE 변경 검증은 별도 승인 대상이다.

### 정지 VM full clone (VM-04)

VM 상세의 **VM full clone**에서 새 VMID·복제본 이름·대상 NFS storage ID를 입력한다. 원본과 대상 조회 후 디스크·복제 범위·guest identity 경고를 확인하고 실행한다. 첫 지원 범위는 같은 node, NFS raw/qcow2 scsi0 한 개·net0 및 선택적 ide2 cloud-init이다. 원본은 정지하고 onboot를 꺼야 한다. 기존 VM·원본·template/create와 겹치지 않는 새 VMID를 선택한다.

관리형 등록에서 `clone`과 `clone_vmids`를 선택하고 기존 연결 갱신 절차(새 등록·검증·전환·전체 재시작)를 따른다. 원본·새 대상의 실제 disk 조회에 Config.Disk도 필요하므로 PVE 토큰은 disk 수정 권한도 가진다. Gjallar의 이 기능은 검토한 복제만 허용한다. 이후 전원/수정 작업은 해당 VM을 기존 관리 VM 범위로 등록해 필요한 기능을 명시적으로 선택한다.

```bash
gjallar vm clone show 40000 --node <node> --new-vmid 40001 --storage <nfs-storage>
gjallar vm clone plan 40000 --node <node> --new-vmid 40001 --name copy-test --storage <nfs-storage> --ack-guest-identity --request-id clone-40000-1 --review-file /tmp/clone-40000.json
gjallar vm clone execute --review-file /tmp/clone-40000.json
```

검토 저장은 VM을 변경하지 않는다. 실행 후 Operation에서 원본 보존·정지된 복제본·새 MAC/UUID·실제 disk bytes를 확인한다. 복제본 설명은 Operation ID로 설정된다. 게스트 IP·hostname·SSH host key·애플리케이션 identity와 디스크 내용은 복사된다. 원본과 함께 시작하기 전에 충돌을 정리해야 하며 이 버전은 guest 내부를 자동 변경하지 않는다. 실패/응답 유실은 원본·새 VMID 두 잠금을 유지하고 GET-only 복구로 확인한다. 새 요청으로 반복하거나 잔여 disk를 임의 삭제하지 않는다. PVE 자체 cleanup 뒤에도 잔여 여부가 미확정이면 그대로 보고한다. 운영 DB 0034 적용 및 실제 복제/정리는 별도 승인 대상이다.

### VM-05 정지 VM 삭제 사용

PVE DELETE 선택값은 managed/legacy transport 모두 URL query로 보내며 body를 사용하지 않는다. purge=0·destroy-unreferenced-disks=0 제한은 유지한다. 구버전 body 전송으로 이미 미확정 Operation이 생겼다면 수정 배포만으로 해당 작업을 재실행하거나 잠금을 해제하지 않는다. UPID·실제 자원·기존 이력을 확인하고 별도 복구 범위를 정한다.

관리형 연결의 선택 `delete` 기능은 VM.Allocate와 선택 storage Audit/Allocate 권한을 검토한다. VM 삭제 후 VM ACL이 없어져도 잔여 disk를 빠짐없이 조회하려면 Datastore.Allocate가 필요하다. PVE 토큰 자체는 해당 storage 설정·다른 내용 삭제도 가능하므로 필요한 storage만 선택한다. Gjallar는 이 기능으로 storage 설정이나 임의 volume 삭제를 허용하지 않는다. 기존 token은 자동 확대하지 않으므로 새 등록·검증·전환·서버 프로세스 재시작 경로를 사용한다. 첫 범위는 정지된 일반 VM의 선택 NFS scsi0 raw/qcow2와 선택적 ide2 cloud-init이다. 삭제 보호·snapshot·추가/unused disk·passthrough 등은 먼저 별도 운영 검토가 필요하며 자동 해제하지 않는다.

VM 상세의 `VM 영구 삭제 → 삭제할 자원 확인`에서 config·연결 disk·전용 ACL/firewall의 삭제 영향과 미참조 volume·backup 보존을 읽는다. `VMID/이름`을 그대로 입력하고 복구 불가 영향을 확인한 뒤 최종 삭제 버튼으로 실행한다. 삭제 전 설정과 자원을 재조회하지만 PVE DELETE는 digest 조건부 실행을 지원하지 않는다. 해당 VM의 외부 동시 변경을 중지한 상태에서 사용한다.

```bash
gjallar vm delete show 40000 --node node1
gjallar vm delete plan 40000 --node node1 --confirmation 40000/test-vm --ack-delete \
  --request-id delete-40000-review-1 --review-file delete-40000.json
gjallar vm delete execute --review-file delete-40000.json
```

명령의 대상은 예시이며 live 승인 자체가 아니다. plan은 조회와 새 0600 검토 파일 저장만 수행한다. execute는 원래 서버/profile·요청 ID·manifest·입력한 대상을 유지하며 명시적 실행 확인을 받는다. `--yes`는 이 마지막 CLI 확인만 미리 제공하며 plan의 이름 확인·ack를 생략하지 않는다.

완료는 PVE task OK와 VMID 미사용·승인 volume 부재·검토한 미참조 volume 보존이 모두 확인됐다는 뜻이다. 삭제 후 ACL이 사라질 수 있으므로 VM GET 403/404를 성공 근거로 사용하지 않는다. 실패·단절·응답 유실·일부 잔여물은 자동 재삭제하지 않는다. 기존 요청 ID와 Operation을 보존하고 잔여 자원을 조사한다. backup에서 복원하는 업무는 별도 흐름이며 삭제에는 자동 복구가 없다. HA/replication 등록 VM은 purge=false인 PVE 삭제가 거부하며 외부 backup job 설정은 남는다. 운영 DB 0035 적용·실제 삭제/정리는 별도 승인 대상이다.

### VM-06 웹 콘솔 접속·종료

PVE가 포트를 문자열로 반환하는 조합도 지원한다. 실제7001에서는 RFB 연결·화면과 종료를 확인했으며 게스트 화면은 display 미초기화 안내였다. 이 경우 연결 성공과 게스트 OS 화면 준비 여부를 구분하고 테스트를 위해 임의 키보드 입력이나 VGA 설정 변경을 하지 않는다.

관리자는 `설정 → Proxmox 연결` 또는 CLI 등록에서 선택한 기존 VM의 console 권한을 포함한다. 기존 연결은 새 token/권한 계획·검증·전환·모든 서버 프로세스 재시작이 필요하다. operator 이상으로 실행 중인 VM 상세의 `웹 콘솔 → 콘솔 접속 준비 → 확인한 VM 콘솔 연결`을 선택한다. 대상과 입력 영향을 읽고 연결하며, `콘솔 연결 종료`는 화면 연결만 닫고 VM은 끄지 않는다. 최대 15분 뒤 연결이 끝나고 자동 재접속하지 않는다. 로그인 폐기·만료·권한 감소도 주기적으로 확인해 종료한다.

```bash
gjallar vm console 40000 --node node1
```

CLI는 같은 대상의 지원 여부·권한을 조회하고 `/instances/40000#console` 웹 주소를 출력한다. 브라우저에서 별도로 로그인해야 하며 CLI session이나 PVE token을 URL에 붙이지 않는다. 이 명령 자체는 PVE vncproxy를 만들거나 VM을 시작하지 않는다.

콘솔은 최신 Chrome/Edge/Firefox/Safari의 secure context(HTTPS 또는 localhost 개발 환경)가 필요하다. noVNC ESM의 top-level await를 지원하지 않는 브라우저는 콘솔을 사용할 수 없다. 비콘솔 bundle의 기존 변환 target은 유지한다. Vite 개발 proxy는 `/api` WebSocket upgrade를 전달한다. 운영 reverse proxy도 `/api/v1/nodes/.../console/socket`의 upgrade를 같은 Gjallar 서버로 전달하고 cookie/Origin을 유지해야 한다. 실제 웹 origin을 `GJALLAR_ALLOWED_ORIGINS`에 정확히 등록한다. 외부 proxy에 raw header/console frame 로깅을 설정하지 않는다.

PVE 연결은 HTTPS CA/hostname 검증이 필수다. legacy env의 `PROXMOX_TLS_INSECURE=true`를 콘솔에는 사용하지 않으며, 자체 CA 환경은 공개 CA를 관리형 등록에 넣어 검증한다. 화면 장치가 없는 VM·serial-only·template·정지 VM은 지원하지 않는다. 권한 부족은 VM.Console/VM.Audit와 정확한 node/VM 선택을 확인한다. 생성·복제 대상 미래 VMID에 console 권한을 자동 부여하지 않으므로 필요하면 기존 VM 범위로 다시 등록한다.

접속 실패·단절 시 자동 새 proxy 생성/재접속은 없다. 브라우저의 종료 안내와 연결 권한을 확인하고 직접 재검토한다. 현재 제한은 process당 전체 32개, 사용자당 2개다. 여러 서버 process의 전역 콘솔 할당이나 지속 세션 복구는 제공하지 않는다. 실제 화면 handshake·입력·종료와 reverse proxy 경로는 승인된 테스트 VM에서 별도 검증해야 한다.

### 준비된 VM 템플릿 전환 (TPL-01, 실환경 검증 대기)

관리형 연결에서 기존 VMID와 NFS storage를 선택하고 template 기능을 새 등록·검증·전환한 뒤 서버를 재시작한다. VM.Allocate와 실제 volume 조회에 필요한 VM.Config.Disk는 PVE에서 전환보다 넓은 권한이므로 exact VMID 범위를 확인한다. 이미 준비된 게스트의 계정·키·machine-id/SSH host key 재생성·cloud-init 상태·IP 설정·민감 파일을 먼저 점검하고 정상 종료한다. Gjallar가 게스트 내부를 청소하지 않는다.

웹 VM 상세의 `준비된 VM을 템플릿으로 전환`에서 전환 조건 → 정확한 VMID/이름 → 게스트 준비 및 원본 부팅 불가 확인 → 최종 실행을 따른다. 첫 조합은 NFS scsi0와 ide2 cloud-init, guest agent 활성 설정이다. 추가 disk/장치·snapshot·pending 등은 차단된다. 실행 전 외부 관리자의 동시 변경을 중지한다.

```bash
gjallar vm template show 40000 --node <node>
gjallar vm template plan 40000 --node <node> --confirmation '40000/<조회한 이름>' \
  --guest-prepared --ack-conversion --request-id <고유요청ID> --review-file template-review.json
gjallar vm template execute --review-file template-review.json
```

위 명령은 사용 예이며 현재 VMID의 존재·소유·실행 승인을 뜻하지 않는다. 검토 파일은 원래 서버/profile에 묶이고 0600으로 새로 저장한다. 실행은 원본 요청 ID를 유지한다. 성공은 PVE task·정지 template·실제 base volume/용량·cloud-init/설정 보존까지 확인한 것이다. 게스트 배포 적합성은 아직 확인되지 않았으므로 생성용 template scope를 명시적으로 갱신하고 별도 테스트 배포를 수행한다.

오류/응답 유실 때 template flag만 보고 성공 처리하거나 새 요청으로 전환하지 않는다. Operation과 GET-only 복구 결과를 확인한다. 일부 전환 상태의 자동 역변환·삭제는 제공하지 않는다. 운영 DB의 0036 적용·실제 전환은 정확한 대상/영향을 별도 승인한 뒤 수행한다.

### 공식 cloud image로 템플릿 제작 (TPL-02, 실환경 검증 대기)

관리형 등록의 공식 이미지 제작 권한과 새 image_vmids를 선택하고 기존 연결 갱신 절차를 따른다. 이미 사용 중인 VMID는 넣지 않는다. import content를 지원하는 dir/NFS staging, images content를 지원하는 NFS target과 Linux bridge가 필요하다. host storage 설정은 자동 변경하지 않는다. Gjallar 임시 공간·PVE 업로드 임시 공간·staging 파일과 10 GiB 가상 disk 공간을 확보한다.

웹 `Workloads → 템플릿 제작`에서 고정 지원 이미지·node·새 VMID/이름·staging/target storage·bridge를 입력한다. 조건·출처·SHA-256·공간/실패 영향을 읽고 VMID/이름을 입력하여 실행한다. CPU 2 cores, 2048 MiB, 10 GiB disk, DHCP cloud-init·guest agent 설정으로 만들며 부팅하지 않는다.

```bash
gjallar vm image-build catalog
gjallar vm image-build show 40004 --node node1 --image-id almalinux-9.8-x86_64-20260810 \
  --name alma-template --staging-storage image-stage --storage nfs-images --bridge vmbr1
gjallar vm image-build plan 40004 --node node1 --image-id almalinux-9.8-x86_64-20260810 \
  --name alma-template --staging-storage image-stage --storage nfs-images --bridge vmbr1 \
  --confirmation 40004/alma-template --ack-image-build \
  --request-id image-build-review-1 --review-file image-build-review.json
gjallar vm image-build execute --review-file image-build-review.json
```

위 값은 예시이며 실제 실행 승인이 아니다. 검토 파일은 서버/profile에 묶인 새 0600 파일이다. 실행은 업로드·import 생성·전환을 각각 한 번만 요청하며 실제 template/base disk를 조회한다. 성공한 제작도 배포 검증은 아니므로 생성 원본 권한을 새로 등록하고 별도 테스트 배포가 필요하다. 실패·응답 유실·서버 재시작 때 원래 요청 ID와 Operation의 단계·잔여 자원을 확인한다. 중간 단계 뒤 남은 변경을 자동 시작하거나 새 요청으로 반복하지 않는다. staging 원본은 보존한다. 제품 내 소유 자원 정리 흐름은 아래 절을 따른다. 임의로 다른 volume을 삭제하지 않는다. 0037 운영 DB 적용·실제 제작과 삭제는 별도 승인 대상이다.

### 제작한 template·업로드 원본 정리 (TPL-02, 실환경 검증 대기)

성공한 제작 Operation ID를 보존한다. 템플릿을 테스트 배포 원본으로 사용할 연결을 새로 등록할 때 제작 VMID를 기존 vmids·template_vmids에 넣고 미래 image_vmids에서는 뺀다. 정리할 storage만 image_cleanup_storages로 명시해 image_cleanup 권한을 선택한다. 원본 staging과 template target을 모두 정리하려면 둘 다 선택한다. Datastore.Allocate는 PVE 토큰 자체의 권한이 넓으므로 작업에 필요한 storage만 검토한다. 새 등록·검증·전환·전체 서버 재시작을 따른다. 성공한 제작 소유 기록이 없는 일반 템플릿은 이 정리 기능으로 삭제하지 않는다.

웹 `템플릿 제작 → 제작한 자원 정리` 또는 제작 성공 결과의 링크에서 node/VMID/제작 Operation/정리 종류를 확인한다. 삭제·보존 자원 → `VMID/이름/template` 또는 `VMID/이름/source` 입력 → 영구 삭제 동의 → 최종 실행을 따른다. template 삭제 후 source 검토는 별도 입력/실행이며 자동 삭제되지 않는다.

```bash
gjallar vm image-cleanup show 40004 --node node1 --build-operation <제작OperationID> --resource template
gjallar vm image-cleanup plan 40004 --node node1 --build-operation <제작OperationID> --resource template \
  --confirmation 40004/alma-template/template --ack-cleanup \
  --request-id template-cleanup-review-1 --review-file template-cleanup.json
gjallar vm image-cleanup execute --review-file template-cleanup.json
```

업로드 원본은 별도 plan에서 `--resource source`, `--confirmation 40004/alma-template/source`, 새 요청 ID·검토 파일을 사용한다. 위 대상은 예시이며 live 삭제 승인이 아니다. source는 제작의 정확한 전용 파일명·현재 형식/크기를 검사한다. 원격 hash를 다시 계산하는 것은 아니므로 작업 중 외부에서 staging 파일을 변경하지 않는다.

linked clone·보호·제작 후 설정/volume 변경·권한 부족은 차단된다. 미확정 제작·삭제의 잠금은 강제 해제하지 않는다. PVE task OK만으로 완료하지 않으며 실제 부재·보존 조건까지 확인한다. 응답 유실/실패 때 원래 Operation의 GET-only 복구를 사용하고 새 DELETE를 반복하지 않는다. template 삭제로 VM ACL이 제거돼도 등록한 storage 권한으로 원본 파일을 별도로 정리할 수 있다. 운영 DB 0038·실환경 template/staging 삭제는 별도 승인 대상이다.

### 템플릿 테스트 배포·검사·정리 (TPL-03)

1. 관리형 연결을 갱신해 완성한 템플릿을 `existing_vmids`/`template_vmids`, 별도 테스트 VMID를 `create_vmids`로 선택한다. create와 정상 종료에 필요한 power, 명시적 삭제를 위한 delete 및 선택 storage 권한을 검토한다. 변경된 연결을 검증·활성화하고 모든 Gjallar process를 재시작한다. 생성 범위 VM에는 create role이 제공하는 필요한 권한을 사용한다.
2. 웹 제작/전환 결과의 **테스트 VM 배포**로 진입한다. 첫 cloud image는 AlmaLinux이며 기본 계정 이름을 무조건 Ubuntu로 가정하지 않는다. 운영자가 사용할 사용자 이름·SSH 공개키·storage·bridge·확보한 IP 또는 DHCP를 입력하고 `부팅 후 확인`의 영향을 검토한다. CLI는 기존 `gjallar vm create plan/execute`를 사용하고 spec의 `power_policy`를 `boot_and_verify`로 지정한다. 원본과 다른 미사용 VMID를 사용한다.
3. 생성 Operation 상세의 **배포 검사·접속 결과 기록·테스트 VM 정리**에서 부팅/cloud-init/guest agent/IP 관찰을 확인한다. `생성만` 선택은 부팅 검사가 미실행이다. 현재 VM 상세에서 IP와 계정을 확인한 뒤 본인의 SSH 클라이언트로 직접 접속하고 성공 또는 실패를 기록한다. 개인키·비밀번호·명령 출력은 Gjallar에 입력하지 않는다.

```bash
gjallar vm template-test show <생성-Operation-ID>
gjallar vm template-test record-access <생성-Operation-ID> \
  --status passed --request-id <접속-증거-고유-ID> --ack-evidence
```

`passed`는 운영자가 실제 접속 성공을 확인했을 때만 선택한다. failed/not_run/unavailable도 기록할 수 있다. 동일 요청 ID는 원래 증거를 재사용하며 기존 결과를 확인했다고 표시한다. 새 기록은 대상·상태·시각·증거 파일이 재조회 보고서에 연결됐는지 대조한다. 불일치나 오래된 응답은 기록 확인 미완료로 남긴다. 결과 수정은 새로운 증거 ID로 기록하고 과거 이력은 보존한다. 응답이 끊기면 작업/증거를 조회하고 자동 재제출하지 않는다.

4. 테스트 VM 상세에서 현재 대상을 다시 확인하고 정상 종료한 후 **영구 삭제**를 검토한다. CLI는 기존 `vm shutdown`, `vm delete show/plan/execute`를 사용한다. 원본 템플릿과 테스트 VM을 혼동하지 않도록 node·VMID·이름·연결 volume을 확인한다. 삭제 Operation의 성공·VMID 미사용·삭제 volume 부재·보존 volume 확인까지 검토한다. 검사 보고서 자체는 정리 완료 증거가 아니다.
5. 템플릿과 staging 원본도 필요 없으면 TPL-02의 `image-cleanup` 경로로 각각 명시적으로 정리한다. 실패·미확정 작업의 자원은 자동 정리하지 않는다. 이 절차의 실제 PVE 생성/부팅/게스트 명령/종료/삭제는 별도 승인 대상이며 아직 실환경 검증하지 않았다.

### 현재 사용량·PVE 추이 조회 (OBS-01~02)

웹 **Insights → 사용량·추이** 또는 VM 상세의 같은 링크에서 자원·노드·기간을 고르고 조회한다. 현재 값과 PVE 평균 이력을 구분하며 시각 선택과 최근 관찰 표로 실제 값을 확인할 수 있다.

```bash
gjallar metrics node <node> --timeframe hour
gjallar metrics vm 40000 --node <node> --timeframe day
gjallar metrics storage <storage> --node <node> --timeframe week
```

- hour/day/week/month/year를 지원한다. 실제 환경에서 관찰한 첫 해상도는 hour/day 60초, week 1800초, month/year 21600초였다. PVE 버전·보존 상태에 따라 달라질 수 있으므로 응답의 실제 범위와 해상도를 기준으로 판단한다.
- CPU는 %, 메모리·공간은 bytes, 이력 network/disk IO는 bytes/s다. 정지 VM CPU/사용 메모리/IO 관찰 누락을 0으로 추정하지 않는다. 현재 IO 속도는 제공하지 않는다. 미관찰·오래된 값·부분 오류는 정상 상태를 뜻하지 않는다.
- 관리형 read의 선택 node/VM/storage와 Audit 권한을 사용하며 추가 쓰기 권한은 필요 없다. 연결 범위를 바꾸려면 기존 등록→검증→전환→전체 process 재시작을 따른다.
- 현재 지표 조회는 요청 시 실행된다. 이력 원본·보존은 PVE가 소유하며 Gjallar가 별도 시계열을 수집하거나 보존하지 않는다. 격리 UI/자동 검사와 env 토큰의 실제 PVE 읽기 검증을 수행했으나 설치된 관리형 웹/CLI 전체 환경 검증은 남아 있다.

### M4 임계·작업 실패 이력 확인

사용량·추이 화면과 `gjallar metrics` 응답은 현재 임계 상태와 선택 기간의 초과/해제 구간을 포함한다. CPU/메모리 주의 70%·위험 85%, storage 주의 80%·위험 90%다. 결측 구간은 정상이나 해제로 표시하지 않으며, PVE 평균 표본 사이의 순간 초과는 확인할 수 없다. 별도 알림 저장소가 아니므로 오래된 구간은 PVE 보존/재집계에 따라 달라질 수 있다.

웹 Insights → 알림 이력 또는 다음 명령으로 최신 작업의 실행 실패와 이후 성공을 조회한다.

```bash
gjallar alerts --limit 50
```

기본 20개·최대 50개 작업에서 최근 실패 구간 최대 100개를 보여준다. 한도 도달·개별 기록 조회 실패를 반드시 확인하고 전체 Operations/개별 작업으로 이동해 상태를 판단한다. 사전 blocked/rejected·외부에서 수행한 미기록 작업은 이 목록에 포함하지 않는다. 보고서 조회는 복구·재실행을 수행하지 않는다. 대상별 현재 상태와 작업의 증거를 확인한 후 기존 명시적 복구 절차를 따른다.

### M5 BAK-01 백업 목록·생성

관리형 연결 등록/갱신에서 기존 원본 VMID·source NFS storage를 선택하고 backup 기능과 명시적 NFS backup storage 부분집합을 추가한다. VM.Backup·선택 backup storage AllocateSpace와 읽기 권한만 필요하다. 역할/ACL 검토→갱신→서비스 재시작의 기존 절차를 따른다. 실제 권한 변경·0039 운영 DB 적용·백업 실행은 별도 승인 대상이다.

웹 VM 상세 → 백업 목록·새 백업에서 노드/storage를 확인하고 목록을 읽는다. 일반 VM을 정상 종료한 뒤 새 백업 조건·영향을 검토하고 VMID/이름 입력과 공간·IO 영향 동의 후 실행한다. 첫 범위는 NFS·scsi0 + ide2 cloud-init이며 snapshot/대기 설정/외부 장치·스크립트·백업 제외 disk는 지원하지 않는다. CLI 예시:

```bash
gjallar vm backup list 40000 --node node1 --storage nfs-backup
gjallar vm backup plan 40000 --node node1 --storage nfs-backup --confirmation '40000/test-vm' --ack-backup --request-id backup-40000-01 --review-file /tmp/backup-40000-01.json
gjallar vm backup execute --review-file /tmp/backup-40000-01.json
```

위 값은 예시이며 실제 실행 승인이 아니다. 검토 파일은 서버/profile에 묶인 새 0600 파일이다. 원본·백업 기본값·기존 archive의 외부 동시 변경을 중지한다. 기존 백업 삭제·보존 정책 변경·외부 알림 발송을 요청하지 않는다. 필요 공간은 보수적인 가상 disk 용량 기준이며 다른 쓰기·압축률에 따라 실제 task가 실패할 수 있다.

결과는 PVE task, 정확한 새 archive, 원본·기존 파일 보존으로 확인한다. 결과 불명·단절·재시작 때 새 요청으로 반복하지 말고 원래 Operation의 GET-only 복구와 PVE task/archive를 확인한다. 부분 파일을 자동 삭제하지 않는다. 백업 파일 확인 성공과 별도 VM 복원·부팅 검사는 구분하며 아직 실행하지 않은 검사는 성공으로 표현하지 않는다.

### M5 BAK-02 별도 VM 복원·격리 부팅 검사

1. 관리형 연결에 restore, 기존 정지 원본 VMID, 백업 원본 NFS storage와 복원 대상 NFS images storage, 활성 bridge, 다른 모든 범위와 분리한 새 restore_vmids를 등록한다. 복원 권한의 role/ACL 검토·갱신·서비스 재시작을 따른다. backup 생성 기능 없이 restore만 선택할 수도 있다. 0040 운영 DB 적용·실제 PVE 권한/복원/부팅 변경은 별도 승인 대상이다.
2. 웹 VM 상세 → 백업 목록에서 archive의 **별도 VM으로 복원**을 선택한다. 같은 node의 새 VMID·NFS storage·Linux bridge를 입력하고 조건을 조회한다. 새 이름과 `원본VMID/새VMID/새이름` 입력, 격리/공간/IO 영향 확인 후 최종 내용과 실행 버튼을 검토한다. 첫 지원은 SeaBIOS·scsi0 + ide2 cloud-init·단일 virtio NIC이며 VLAN/trunk/추가 장치·외부 script는 제외한다.

```bash
gjallar vm restore plan 40000 --node node1 \
  --archive 'nfs-backup:backup/vzdump-qemu-40000-2026_09_19-05_00_00.vma.zst' \
  --new-vmid 40006 --name restore-test --storage nfs-images --bridge vmbr1 \
  --confirmation '40000/40006/restore-test' --ack-isolation \
  --request-id restore-40006-01 --review-file /tmp/restore-40006-01.json
gjallar vm restore execute --review-file /tmp/restore-40006-01.json
gjallar vm restore report <복원-Operation-ID>
```

위 node/storage/archive/VMID는 예시이며 live 승인이 아니다. 실제 목록에서 archive를 선택해야 한다. 새 0600 검토 파일은 서버/profile/원본/새 대상에 묶이며 자동 덮어쓰지 않는다. 원본·archive·호스트의 외부 동시 변경을 중지한다. 다른 저장소 쓰기나 압축률에 따라 실제 공간이 부족할 수 있다.

3. 복원 성공은 원본/백업 보존·새 VM 정지·disk/hardware·NIC link_down·자동 시작 해제를 확인한 상태다. 부팅은 하지 않았다. 결과 불명/응답 유실 때 새 요청으로 반복하거나 남은 disk를 삭제하지 말고 원래 Operation과 GET-only 복구를 확인한다. task OK만으로 완료를 판단하지 않는다.
4. 웹 성공 화면/Operation의 **별도 VM 복원 검사** 또는 CLI report에서 현재 보존·격리·설정 결과를 확인한다. NIC 링크를 끊은 채 VM 상세의 명시적 시작 또는 `gjallar vm start 40006 --node node1 --request-id <부팅-ID>`로 부팅 검사를 별도로 실행하고 report를 다시 조회한다. QEMU running은 OS/서비스 성공이 아니며 guest agent 응답이 없으면 미확인이다. 외부 접속은 이 격리 검사에서 검증하지 않는다. 원본 IP·hostname·SSH key가 복제돼 있으므로 identity/IP를 별도로 정리하기 전에 NIC를 연결하지 않는다.
5. 검사 후 정상 종료한다. 정리할 때는 연결 갱신에서 해당 ID를 restore_vmids에서 기존 vmids로 옮기고 필요한 delete/선택 storage 권한을 검토·적용한 뒤 서버 process를 재시작한다. 현재 VMID/이름/volume을 다시 조회해 기존 명시적 전체 삭제 흐름을 실행하고 실제 부재를 확인한다. 복원 검사·목록 화면은 자동 정리하지 않으며 원본 VM·백업 파일은 보존한다.

구현 검증과 실제 관리형 설치/PVE archive protocol·복원·부팅·정리 검증은 별개다. 아직 실제 backup/restore/boot mutation은 수행하지 않았다.


### M6 OPS-01 정지 VM 노드 이동

관리형 연결 등록/갱신에서 migrate 기능과 원본·목적 node, 기존 VMID, shared NFS storage와 bridge를 선택한다. 두 node의 PVE 9 version/build·CPU model이 같고 같은 NFS images volume과 활성 bridge를 읽을 수 있어야 한다. VM.Migrate/Config.Disk·bridge SDN.Use와 기존 Audit 권한을 검토한 뒤 기존 토큰 등록/전환/서비스 재시작을 따른다. 0041 운영 적용·실제 권한/VM 이동은 별도 승인 대상이다.

웹 VM 상세 → **정지 VM 노드 이동**에서 양쪽 node를 확인한다. 정상 종료·onboot 해제·비HA·snapshot/대기 변경 없는 scsi0 + ide2 cloud-init·단일 virtio NIC를 지원한다. local disk 복사·storage remap·VLAN/trunk·HA/live/강제 이동은 지원하지 않는다. 목적 bridge 이름만으로 실제 L2 연결을 보장할 수 없으므로 네트워크·필요 백업·부팅 호환성을 별도로 확인한다.

```bash
gjallar vm migrate show 40000 --node node1 --destination node2
gjallar vm migrate plan 40000 --node node1 --destination node2 \
  --confirmation '40000/test-vm/node1->node2' --ack-migration \
  --request-id migrate-40000-01 --review-file /tmp/migrate-40000-01.json
gjallar vm migrate execute --review-file /tmp/migrate-40000-01.json
```

위 값은 예시이며 live 승인이 아니다. 새 0600 검토 파일은 서버/profile/원본/목적/요청에 묶인다. 검토 이후 외부 VM/storage/network 변경을 중지한다. 실행 결과는 원본 node의 PVE task와 cluster 현재 위치·목적 VM/config/volume/정지 상태를 함께 확인한다. 성공 후 VM 상세에서 현재 위치를 다시 읽고 시작·접속 검사는 별도로 수행한다. 이동 API 자체는 자동 시작하지 않는다.

응답 유실·task 실패·위치 불명 시 새 ID로 반복하거나 임의 역이동/삭제하지 않는다. 원래 Operation의 GET-only 복구와 양쪽 node·PVE task를 확인한다. canonical Operation의 node는 task를 제출한 원본이며 실제 목적 위치는 observed_after에 있다. 구현·fixture 화면 검증은 실제 관리형 PVE 이동·부팅·접속 성공과 구분한다.

### M6 OPS-02 노드 유지보수 준비 확인

웹 Insights → **노드 유지보수**에서 유지보수할 node를 입력한다. 목적 node와 NFS backup storage를 함께 선택하면 대상별 최근 백업·정지 이동 조건을 추가 확인한다. operator 이상 권한이며 VM.Backup/storage AllocateSpace와 VM.Migrate/Config.Disk 등 선택 기능의 기존 조회 권한이 필요할 수 있다. 이 보고서가 권한을 추가하거나 실제 백업·이동·호스트 변경을 수행하지 않는다.

대상 VM의 **정지 VM 이동 검토**를 열면 보고서에서 선택한 원본·목적 노드를 이어받는다. 이동 화면에서 양쪽 노드·공유 자원 조건을 다시 조회하고 대상·영향을 확인한 뒤 실행한다. 링크를 여는 것만으로 이동하지 않는다.

```bash
gjallar maintenance node node1
gjallar maintenance node node1 --destination node2 --backup-storage nfs-backup \
  --backup-max-age-hours 24 --check-limit 10
```

위 값은 예시다. 현재 연결이 볼 수 있는 QEMU 범위·관찰 시각·누락과 최대 200개 영향 목록의 잘림을 확인한다. 5분보다 오래된 snapshot, offline node, 필요한 inventory source 누락은 준비 확인을 진행하지 않는다. 추가 검사는 기본 10/최대 20 VM이며 나머지는 개별 VM 상세에서 확인한다. 검사 한도를 실제 대상 수보다 작게 선택하면 전체 준비 확인으로 표시되지 않는다.

‘수동 이동 준비 확인’은 아직 원본에 남은 VM에 대해 현재 이동 조건과 선택 기간 내 backup 파일 metadata를 확인했다는 뜻이다. 복원 가능성·백업 내용의 최신성·노드 종료 안전성을 보장하지 않는다. template·실행 중 VM·권한 오류·백업 없음·미검사 항목을 해결하고 필요한 백업/이동은 연결된 화면에서 별도로 실행한다. 실행 후 보고서를 다시 읽고, 연결 범위 밖 VM·LXC·클러스터 서비스/호스트 의존성도 별도로 확인한 뒤 실제 유지보수를 결정한다. 빈 목록만으로 호스트를 종료하지 않는다.


### M6 OPS-03 기존 directory storage 등록·수정

관리자 웹 **설정 → 호스트 storage** 또는 CLI `host storage`를 사용한다. 관리형 연결에서 `host_storage`와 별도 `host_storages` ID(새 등록할 ID 포함), 선택 node를 명시해 기존 연결 갱신·검증·전환·전체 process 재시작을 수행한다. PVE는 설정 API에 `/storage`의 Datastore.Allocate를 요구하므로 토큰 자체의 권한은 cluster 전체 storage 설정에 미친다. 선택 ID의 Datastore.Audit·node Sys.Audit도 필요하다. Gjallar는 별도로 대상·필드를 제한하지만 PVE token 자체의 권한이 좁아지는 것은 아니다. volume 작성/삭제 권한은 자동 추가하지 않는다.

등록은 미리 준비한 절대 directory 경로·선택 node 하나·비공유 dir storage만 지원한다. 수정은 기존 content 종류·사용 여부를 바꾸며 path·nodes·shared를 유지한다. 기존 nodes가 없으면 모든 node의 설정에 영향을 준다. 두 동작 모두 자동 base/content directory 생성을 해제하며 기존 volume/file을 삭제하지 않는다. 필요한 기존 content directory는 별도로 준비돼 있어야 한다. 예시:

```bash
gjallar host storage plan test-dir --node node1 --mode create --directory /mnt/existing \
  --content images iso --confirmation node1/test-dir/create --ack-cluster-impact \
  --request-id host-storage-create-1 --review-file /tmp/host-storage-create-1.json
gjallar host storage execute --review-file /tmp/host-storage-create-1.json

gjallar host storage plan test-dir --node node1 --mode update --content images iso --disable \
  --confirmation node1/test-dir/update --ack-cluster-impact \
  --request-id host-storage-disable-1 --review-file /tmp/host-storage-disable-1.json
```

위 값은 예시이며 실제 PVE 변경 승인이 아니다. plan은 기존/변경 후 설정·영향 노드·경고를 서버/profile에 묶인 새 0600 파일에 저장한다. 웹은 동일 검토 뒤 `node/storage/mode` 재입력·cluster 영향 동의·최종 실행을 요구한다. 검토 이후 외부 storage/호스트 변경을 중지한다. 실행은 한 번만 요청하며 정확한 Operation 대상과 전체 요청을 대조한다.

성공은 설정 보존/변경 확인과 enabled인 경우 **선택 node의 active 확인**이다. 다른 node·하위 content directory 존재·실제 VM/backup 작성 성공은 별도 검사다. disabled 성공은 unmount 완료가 아니다. 활성 검사는 PVE의 node storage 상태 조회를 사용하며 PVE 내부에서 다른 enabled storage도 점검·활성화할 수 있다. 실제 실행 승인에는 이 부수 효과도 포함해야 한다.

응답 유실·부분 변경·설정 drift·활성 미확인은 잠금을 유지하고 Operation의 GET-only 복구로 재관찰한다. 새 요청으로 반복하거나 자동 rollback/삭제하지 않는다. 응답 확인이 없으면 원하는 설정이 보여도 자동 완료로 바꾸지 않는다. 현재 구현·격리 화면·자동 검증은 통과했으며 실제 PVE 권한/등록/수정·하위 directory 사용 검증·운영 0042 적용·설치는 별도 승인 대기다.


### M6 OPS-03 VM용 Linux bridge 설정·노드 전체 반영

관리자 웹 **설정 → 호스트 bridge** 또는 CLI `host network`를 사용한다. 관리형 연결에서 host_network와 별도 host_bridges(신규 vmbrN 포함), 선택 node를 지정해 기존 연결 갱신·검증·전환·전체 process 재시작을 따른다. 선택 node Sys.Modify·Sys.Audit와 전체 local bridge 변경 감지용 `/sdn/zones/localnetwork` SDN.Audit가 필요하다. token 자체는 bridge보다 넓은 node 설정 권한을 가지며 Gjallar의 요청 제한과 구분한다.

1. 별도 관리 접속/복구 경로와 유지보수 시간을 확보한다. PVE node 전체의 기존 pending 변경이 없어야 하며 다른 관리자의 동시 network/SDN 변경을 중지한다. node 전체 network reload는 다른 연결과 관리 접속에 영향을 줄 수 있다. UI/API가 읽는 scope 밖 VM·LXC·외부 서비스의 영향도 별도 확인한다.
2. 신규 내부 VM bridge 또는 host IP/gateway·DHCP·추가 inet6 stanza·임의 hook/options가 없는 기존 Linux bridge를 선택한다. 새 bridge에는 물리 port를 연결하지 않는다. 기존 port·MTU·기타 설정은 보존하고 autostart·VLAN-aware·허용 VLAN만 수정한다. 외부 uplink 배치·관리망/주소 수정·OVS/SDN·bridge 삭제는 지원하지 않는다.
3. 노드/bridge/작업 종류와 기존→변경 설정·전체 node 영향·VLAN 목록을 검토한다. 웹은 확인 문구와 node 전체 reload 동의 후 최종 버튼으로 실행한다. CLI는 새 0600 서버/profile 검토 파일과 별도 execute를 사용한다.

```bash
gjallar host network plan vmbr40 --node node1 --mode create --vlan-aware --vlan-ids '10 20-30' \
  --confirmation node1/vmbr40/create --ack-node-reload --request-id bridge-create-1 \
  --review-file /tmp/bridge-create-1.json
gjallar host network execute --review-file /tmp/bridge-create-1.json

gjallar host network plan vmbr40 --node node1 --mode update --no-autostart \
  --confirmation node1/vmbr40/update --ack-node-reload --request-id bridge-update-1 \
  --review-file /tmp/bridge-update-1.json
```

위 node/bridge/VLAN은 예시이며 live 변경 승인이 아니다. `--vlan-aware`를 켜면 `--vlan-ids`를 지정하고, 끄면 목록을 지정하지 않는다. 공백 구분 ID·범위를 1~4094 안에서 정규화한다. `--no-autostart`는 다음 host 부팅 설정이며 즉시 link down을 의미하지 않는다.

4. 저장된 pending 설정의 대상/다른 interface 보존을 확인한 뒤에만 한 번 node 전체 반영을 요청한다. 결과는 정확한 PVE networking reload task·대기 변경 없음·설정 보존, autostart=true일 때 정확한 iface/type=bridge와 active=1로 확인한다. optional exists는 물리 장치 표시이므로 가상 bridge 필수 조건이 아니다. task만 발급되거나 stage만 저장된 상태는 성공이 아니다. 연결된 VM의 실제 통신·VLAN 경로·커널 VLAN table은 별도로 검사한다.
5. 접속 단절·응답 유실·중간 중단·foreign pending이 있으면 새 요청으로 반복하지 말고 원래 Operation의 단계와 GET-only 복구를 확인한다. 저장만 된 상태에서 복구는 자동 reload하지 않는다. PVE에서 현재 파일/대기 파일·작업 상태·다른 변경 소유자를 조사하고 운영자의 별도 승인된 복구 절차를 정한다. 임의 revert/삭제·전체 pending 적용·잠금 강제 해제는 하지 않는다.

구현·격리 화면·자동 검증과 실제 PVE 반영 검증은 별개다. node-wide reload와 PVE SDN 설정 생성, 현재 0042 운영 적용·token/ACL 변경·설치는 정확한 대상·영향·복구 경로의 별도 승인 전 수행하지 않는다.
