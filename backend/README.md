# Gjallar Backend

Gjallar의 FastAPI backend입니다. 현재 `/api/v1`과 local auth/admin API를 제공하고 PostgreSQL과 Proxmox VE API를 사용합니다.

## 현재 책임

- local user, server-side session, `viewer < operator < admin` 권한
- read-only Proxmox inventory와 normalization
- Create VM draft/preflight/plan/approval/native create
- VM Start와 post-create readiness evidence
- DRS recommendation/policy/approval/migration/reconciliation
- DB-backed jobs, artifacts, risks
- production React SPA serving

목표 backend 구조는 Workloads, Operations, Policy/Approval, Evidence/Audit, Insights domain을 사용하는 modular monolith입니다. 현재 package가 이미 그 경계를 구현했다는 의미는 아닙니다.

- 현재 구조: [`../project-docs/architecture/overview.md`](../project-docs/architecture/overview.md)
- 현재 API: [`../project-docs/api/current-api-v1.md`](../project-docs/api/current-api-v1.md)
- DB 기준선: [`../project-docs/database/current-schema-and-ownership.md`](../project-docs/database/current-schema-and-ownership.md)

## 로컬 준비

저장소 root에서 실행합니다. `python3.13`이 다른 이름·경로에 설치됐다면 첫 명령의 실행 파일만 해당 Python 3.13 경로로 바꿉니다.

```bash
cp .env.example .env
python3.13 -m venv backend/venv
backend/venv/bin/pip install -r backend/requirements-dev.lock
set -a
. ./.env
set +a
PYTHONPATH=backend backend/venv/bin/alembic -c backend/alembic.ini upgrade head
PYTHONPATH=backend backend/venv/bin/python -m app.db.seed_create_vm_profiles
PYTHONPATH=backend backend/venv/bin/python -m app.auth.users create-admin --username admin
```

`create-admin`은 password를 터미널에서 두 번 입력받습니다. CLI 인자에 평문 password를 넣지 마십시오.

## 실행

저장소 root의 script가 `.env`를 읽고 `backend/venv`를 사용합니다.

```bash
pnpm run backend
```

직접 실행하려면:

```bash
set -a
. ./.env
set +a
cd backend
PYTHONPATH=. venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port "${BACKEND_PORT:-8000}"
```

## 주요 환경

- 필수 runtime: `GJALLAR_DATABASE_URL` PostgreSQL URL. `postgresql://`과 `postgres://`는 psycopg driver URL로 normalize된다.
- local dev: `FRONTEND_PORT`, `BACKEND_PORT`, `VITE_BACKEND_URL`.
- connection: `GJALLAR_INVENTORY_MODE`, `PROXMOX_API_URL`, `PROXMOX_API_TOKEN_ID`, `PROXMOX_API_TOKEN_SECRET`, `PROXMOX_TLS_INSECURE`.
- inventory/mutation tuning: `PROXMOX_API_CONNECT_TIMEOUT_SECONDS`, `PROXMOX_API_READ_TIMEOUT_SECONDS`, legacy fallback `PROXMOX_API_TIMEOUT_SECONDS`, `PROXMOX_TASK_POLL_INTERVAL_SECONDS`, `PROXMOX_TASK_TIMEOUT_SECONDS`와 `GJALLAR_PROXMOX_TASK_*` alias.
- auth/cookie: `GJALLAR_ENV`, `GJALLAR_ALLOWED_ORIGINS`, `GJALLAR_SESSION_COOKIE_NAME`, `GJALLAR_SESSION_TTL_SECONDS`, `GJALLAR_SESSION_COOKIE_SECURE`, `GJALLAR_SESSION_COOKIE_SAMESITE`.
- Create VM access default: `GJALLAR_DEFAULT_SSH_PUBLIC_KEY`, `GJALLAR_DEFAULT_SSH_PUBLIC_KEY_B64`, `GJALLAR_DEFAULT_SSH_PUBLIC_KEY_FILE`.
- existing DRS backend: `PROXMOX_DRS_API_URL`, `PROXMOX_DRS_API_TOKEN_ID`, `PROXMOX_DRS_API_TOKEN_SECRET`, `PROXMOX_DRS_API_CONNECT_TIMEOUT_SECONDS`, `PROXMOX_DRS_API_READ_TIMEOUT_SECONDS`, `PROXMOX_DRS_TASK_POLL_INTERVAL_SECONDS`, `PROXMOX_DRS_TASK_TIMEOUT_SECONDS`.

product inventory는 authoritative Proxmox API만 사용합니다. `GJALLAR_INVENTORY_MODE=live`가 기본이며 `auto`는 live-only 호환 alias입니다. 필수 connection 설정이 빠지면 `unconfigured`, 설정 후 read가 실패하면 `degraded`를 반환하고 fixture inventory로 fallback하지 않습니다. 상태는 authenticated `GET /api/v1/setup/proxmox/connection`에서 확인합니다.

전체 기본값과 현재 지원 여부는 `.env.example`과 각 config/client 코드가 우선합니다. optional tuning 값을 이유 없이 설정하지 않습니다.

SQLite는 runtime DB가 아닙니다. `GJALLAR_ALLOW_SQLITE_FOR_TESTS=1`인 test에서만 허용됩니다.

## 계정 관리

`backend` directory에서 `.env`를 load한 뒤 실행합니다.

```bash
PYTHONPATH=. venv/bin/python -m app.auth.users create-user --username viewer1 --role viewer
PYTHONPATH=. venv/bin/python -m app.auth.users create-user --username operator1 --role operator
PYTHONPATH=. venv/bin/python -m app.auth.users list-users
PYTHONPATH=. venv/bin/python -m app.auth.users set-role --username viewer1 --role operator
PYTHONPATH=. venv/bin/python -m app.auth.users disable-user --username viewer1
PYTHONPATH=. venv/bin/python -m app.auth.users reset-password --username operator1
```

disable과 password reset은 해당 사용자의 session을 revoke합니다. 마지막 enabled admin은 disable하거나 admin role에서 내릴 수 없습니다.

## 검증

저장소 root에서:

```bash
pnpm run test:backend
pnpm run test:backend:container
```

`backend/requirements.txt`와 `backend/requirements-dev.txt`는 직접 dependency 선언입니다. 실제 runtime과 개발 설치는 Python 3.13/Linux에서 해석한 `requirements.lock`과 `requirements-dev.lock`을 사용합니다.

## Docker runtime

root Dockerfile은 frontend를 build한 뒤 FastAPI runtime에 포함합니다. entrypoint는 기본적으로 다음 순서를 실행합니다.

1. `alembic upgrade head`
2. Create VM profile seed
3. configured bootstrap admin 생성
4. Uvicorn 실행

`GJALLAR_SKIP_STARTUP_INIT=1`은 migration/seed/bootstrap을 모두 건너뛰므로 일반 운영 시작에 사용하지 않습니다.

## 변경 시 지켜야 할 경계

- trusted actor는 request payload가 아니라 server-side session에서 얻습니다.
- inventory read adapter와 mutation client를 합치지 않습니다.
- task 접수만으로 operation 성공을 선언하지 않습니다.
- ambiguous external result를 자동 재시도하지 않습니다.
- applied Alembic revision을 수정하지 않습니다.
- DB schema, auth, public API, Proxmox mutation 변경은 승인된 Plan과 검증을 먼저 확인합니다.
