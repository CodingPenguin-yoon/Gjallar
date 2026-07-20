# 운영 Runbook

- 상태: `APPROVED`
- 최종 검토일: `2026-07-20`
- 적용 범위: 현재 single-image FastAPI/React/PostgreSQL runtime

이 문서는 현재 코드의 실행·점검·복구 절차만 다룬다. 목표 operation architecture가 아직 구현된 것처럼 기록하지 않는다.

## 1. 사전 조건

- local 기준: Python 3.13, Node.js 24, pnpm 10, PostgreSQL. `python3.13`이 다른 이름·경로라면 명령의 실행 파일만 해당 경로로 바꾼다.
- container 기준: Docker와 PostgreSQL 접근 경로.
- 필수 설정: `GJALLAR_DATABASE_URL`.
- VM/Inventory/Create/Network/DRS 운영 화면 사용 시: Proxmox API URL, token ID, token secret과 TLS 정책.
- `.env`, password, token, private key를 repository, command history, log, artifact에 남기지 않는다.

product runtime은 Proxmox 설정 누락이나 연결 실패를 fake inventory로 대체하지 않는다. 연결 상태가 `live`일 때만 inventory-dependent 화면과 mutation affordance가 열린다.

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

DB 초기화와 first admin 생성:

```bash
PYTHONPATH=backend backend/venv/bin/alembic -c backend/alembic.ini upgrade head
PYTHONPATH=backend backend/venv/bin/python -m app.db.seed_create_vm_profiles
PYTHONPATH=backend backend/venv/bin/python -m app.auth.users create-admin --username admin
```

- runtime DB는 PostgreSQL만 허용한다.
- `postgresql://`과 `postgres://`는 `postgresql+psycopg://`로 normalize된다.
- SQLite는 `GJALLAR_ALLOW_SQLITE_FOR_TESTS=1`인 test에서만 허용한다.
- profile seed는 기존 profile row가 있으면 no-op하는 idempotent 작업이다.

## 3. 로컬 시작·종료

```bash
pnpm run dev
```

root script는 다음 process를 함께 시작한다.

- backend bind: `0.0.0.0:${BACKEND_PORT:-8000}`; local 접속은 `127.0.0.1` 사용
- frontend: `0.0.0.0:${FRONTEND_PORT:-5173}`
- Vite `/api` proxy: `VITE_BACKEND_URL` 또는 local backend port

터미널의 `Ctrl-C`로 두 process를 종료한다. background process가 남았으면 현재 port listener를 확인한 뒤 해당 process만 종료한다.

## 4. Container 시작

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
- Jobs 화면이 비어 있을 때 DB log/error 여부
- live mutation 전 target node/VM과 credential scope

### DB migration

```bash
set -a
. ./.env
set +a
PYTHONPATH=backend backend/venv/bin/alembic -c backend/alembic.ini current
PYTHONPATH=backend backend/venv/bin/alembic -c backend/alembic.ini heads
```

`current`와 expected head가 다르면 application을 통한 mutation 전에 migration 실패 원인을 해결한다. 적용된 revision file은 수정하지 않는다.

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

현재 `.env.example`의 주요 live inventory/Create VM/VM Start 설정:

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
- DRS migration backend는 별도 `PROXMOX_DRS_API_URL`, `PROXMOX_DRS_API_TOKEN_ID`, `PROXMOX_DRS_API_TOKEN_SECRET`를 사용한다. DRS live execution은 일반 운영 확인에 포함하지 않는다.

필요할 때만 다음 tuning env를 사용한다.

- common inventory/mutation: `PROXMOX_API_CONNECT_TIMEOUT_SECONDS`, `PROXMOX_API_READ_TIMEOUT_SECONDS`, `PROXMOX_API_TIMEOUT_SECONDS`.
- task poll: `PROXMOX_TASK_POLL_INTERVAL_SECONDS`, `PROXMOX_TASK_TIMEOUT_SECONDS`; legacy alias는 `GJALLAR_PROXMOX_TASK_*`.
- DRS client: `PROXMOX_DRS_API_CONNECT_TIMEOUT_SECONDS`, `PROXMOX_DRS_API_READ_TIMEOUT_SECONDS`, `PROXMOX_DRS_TASK_POLL_INTERVAL_SECONDS`, `PROXMOX_DRS_TASK_TIMEOUT_SECONDS`.
- 값과 기본값은 `.env.example`과 현재 client code를 우선하며 관측 근거 없이 timeout을 늘리지 않는다.

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
- DRS recommendation을 execution approval로 간주

## 8. 실패와 복구

### DB 연결 실패

- startup migration 실패 시 service를 정상으로 간주하지 않는다.
- `GJALLAR_DATABASE_URL`, DNS/network, credential, PostgreSQL availability를 확인한다.
- Jobs/Risks가 빈 목록일 때 실제 no-data로 단정하지 않는다. 현재 일부 read path가 DB exception을 empty result로 축소하는 알려진 위험이 있다.

### Proxmox read 실패

- `/api/v1/setup/proxmox/connection`의 state와 redacted reason을 먼저 확인한다.
- `unconfigured`이면 `PROXMOX_API_URL`, `PROXMOX_API_TOKEN_ID`, `PROXMOX_API_TOKEN_SECRET` 누락과 `GJALLAR_INVENTORY_MODE`를 확인한다.
- `degraded`이면 TLS, network/DNS, timeout, token 권한과 PVE availability를 확인한 뒤 `연결 다시 확인`을 실행한다.
- API URL, token, TLS, timeout과 PVE availability를 확인한다.
- non-live에서 inventory-dependent API는 `503`과 `PROXMOX_INVENTORY_UNCONFIGURED` 또는 `PROXMOX_INVENTORY_DEGRADED`를 반환한다. retry 전에 reason을 해결한다.
- UI에서는 VM/Create/Network/DRS navigation을 숨기고 direct route도 connection 안내로 차단한다. Jobs/Risks/Account/Admin은 계속 사용할 수 있다.
- stale/unknown/non-live state에서 mutation하지 않는다.

### Dispatch 결과 불명

- timeout, missing UPID, backend crash-after-dispatch는 side effect 없음으로 간주하지 않는다.
- stored job/artifact, task reference와 Proxmox actual state를 먼저 확인한다.
- same mutation 자동 retry를 금지하고 `needs_reconciliation` 의미를 유지한다.

### Create/Start retained target lock

- VM Start와 Create VM은 현재 한 configured cluster 안의 VMID를 `proxmox_vm/vmid:{vmid}`로 잠근다. node가 달라도 같은 VMID는 같은 target이다.
- lock은 platform temporary directory 아래 `gjallar-runtime/target-operation-locks/`에 저장된다. 일반 Linux container의 temporary root는 `/tmp`지만 실제 위치는 Python runtime의 temporary directory 설정을 따른다.
- API evidence에는 target, owner, lock id와 획득 시각만 노출하며 absolute filesystem path는 노출하지 않는다.
- ambiguous result에서 lock은 의도적으로 남는다. 파일 age, backend process 종료 또는 timeout만으로 stale이라고 판단하거나 삭제하지 않는다.
- 현재 operator unlock endpoint는 없다. exact job/request evidence, UPID가 있으면 task, Proxmox actual VM state와 active task를 먼저 확인한다.
- 수동 복구가 불가피하면 해당 target mutation을 중지한 상태에서 복구 결정을 기록하고, metadata로 확인한 정확한 단일 lock file만 별도 quarantine 경로로 이동한다. wildcard나 lock directory 전체 삭제는 금지한다.
- 새 container 배포나 temporary storage 초기화는 retained lock을 유실할 수 있으며 reconciliation이 아니다. 이후 mutation 전에 unresolved VM Start job과 `vm_create_requests`의 `needs_reconciliation`/`apply_failed`를 먼저 확인한다.

### Task OK와 post-check 불일치

- success로 수동 변경하지 않는다.
- expected/observed target, node, power/config/fingerprint와 active task를 비교한다.
- external effect를 reverse action으로 자동 보상하지 않는다.

### DRS reconciliation

- reconcile endpoint는 stored task를 poll하고 local state를 갱신하는 follow-up이며 새 migration이나 corrective mutation을 시작하지 않는다.
- 정확한 acknowledgement와 stored job/UPID가 필요하다.
- live DRS evidence는 historical 자료일 뿐 future mutation의 승인이 아니다.
- `dispatch_attempt.state=prepared`인데 UPID가 없으면 execute 재호출은 migration을 다시 제출하지 않고 job/lock을 reconciliation-required로 전환한다.
- 이 prepared/no-UPID 상태의 reconcile은 VM status/config/active task를 read-only로 확인할 수 있지만, UPID 없이 job을 자동 완료하거나 operation lock을 해제하지 않는다.

## 9. 검증 명령

```bash
git diff --check
pnpm run verify
pnpm run verify:container
```

- `verify`는 backend test, frontend test, frontend lint, frontend build를 순차 실행한다.
- venv 또는 frontend dependency가 없으면 install 전 검증을 성공으로 보고하지 않는다.
- live smoke는 이 기본 명령에 포함하지 않는다.

## 10. 증거 보존

- 현재 operation state와 artifact는 PostgreSQL `job_runs`, `job_artifacts` 등에 저장된다.
- 이 구조는 아직 compliance-grade append-only audit가 아니다.
- historical approved live-smoke 원본은 [`../evidence/legacy-live-smoke/README.md`](../evidence/legacy-live-smoke/README.md)에 보존한다.
- evidence 문서의 과거 제품 방향이나 절차를 현재 운영 기준으로 재사용하지 않는다.

## 11. 알려진 운영 공백

- `/health`는 DB/Proxmox deep readiness가 아니다.
- degraded 상태에서 조회할 durable stale inventory snapshot은 아직 없다.
- long-running operation의 durable worker/lease/restart recovery가 없다.
- job/artifact는 공통 append-only operation audit가 아니다.
- Create/Start target lock은 single-container local file이므로 shared replica coordination과 durable recovery를 제공하지 않는다.
- Create/Start retained lock의 operator reconciliation/unlock API가 없다.
- DRS DB lock과 Create/Start file lock은 같은 VM target을 서로 차단하지 않는다.
- 새 guided `qm` mode는 승인된 목표지만 아직 구현되지 않았다.
