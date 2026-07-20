# Gjallar

Gjallar는 Proxmox를 위한 **Verified Operations Control Plane**을 지향합니다.

Proxmox는 VM·node·task의 actual state와 low-level execution을 소유하고, Gjallar는 workload 운영 의도, 정책, 승인, 실행 검증, evidence와 reconciliation을 소유합니다. 최초 연결과 break-glass를 제외한 day-2 운영을 Gjallar에서 시작하고 결과 확인까지 끝내는 것이 목표입니다.

## 현재 상태와 목표

현재 코드는 React SPA, FastAPI, PostgreSQL/Alembic, Proxmox API로 구성된 feature-oriented monolith입니다. 인증, inventory, Create VM, VM Start, DRS, Jobs/Risks 기능이 이미 있지만 목표 domain/operation 구조로의 전환은 진행 중입니다.

- 목표 제품 정의: [`project-docs/specifications/project-specification.md`](project-docs/specifications/project-specification.md)
- 현재 코드 기준선: [`project-docs/architecture/overview.md`](project-docs/architecture/overview.md)
- 승인된 아키텍처 결정: [`ADR-001`](project-docs/decisions/adr-001-proxmox-gjallar-authority-boundary.md), [`ADR-002`](project-docs/decisions/adr-002-modular-monolith-domain-boundaries.md), [`ADR-003`](project-docs/decisions/adr-003-production-inventory-connection-truth.md)
- 전환 순서: [`project-docs/plans/2026-07-20-verified-operations-control-plane-transition.md`](project-docs/plans/2026-07-20-verified-operations-control-plane-transition.md)

기존 DRS 중심 문서는 폐기했습니다. DRS는 앞으로 제품의 중심이 아니라 placement/capacity insight와 제한된 기존 operation으로 다룹니다.

## 현재 제공 기능

- local user/session과 `viewer < operator < admin` RBAC
- Proxmox node, VM, template, storage, network inventory
- approval-gated native Create VM
- acknowledgement/idempotency-gated VM Start
- Jobs/Artifacts/Risks 조회
- DRS recommendation, policy, approval packet, 제한된 migration/reconciliation backend
- same-origin production SPA/API Docker image

Proxmox 연결은 `unconfigured`/`live`/`degraded`로 표시됩니다. product runtime은 mock/demo inventory로 fallback하지 않으며, `live`가 아니면 VM/Create/Network/DRS 화면을 닫고 Jobs/Risks/Account/Admin만 유지합니다.

현재 기능과 목표 기능을 혼동하지 않습니다. 목표 operation lifecycle은 승인됐지만 아직 모든 workflow에 구현되지 않았습니다.

## 로컬 실행

기준 runtime은 Dockerfile의 Python 3.13, Node.js 24, pnpm 10입니다. PostgreSQL과 실행 가능한 `python3.13` binary 또는 동일한 Python 3.13 경로가 필요합니다.

```bash
cp .env.example .env
nvm use
npm install --global pnpm@10.34.5
python3.13 -m venv backend/venv
backend/venv/bin/pip install -r backend/requirements-dev.lock
pnpm --dir frontend install --frozen-lockfile
```

`.env`의 `GJALLAR_DATABASE_URL`을 실제 PostgreSQL에 맞춘 뒤 초기화합니다.

```bash
set -a
. ./.env
set +a
PYTHONPATH=backend backend/venv/bin/alembic -c backend/alembic.ini upgrade head
PYTHONPATH=backend backend/venv/bin/python -m app.db.seed_create_vm_profiles
PYTHONPATH=backend backend/venv/bin/python -m app.auth.users create-admin --username admin
pnpm run dev
```

- frontend: `http://127.0.0.1:5173`
- backend: `http://127.0.0.1:8000`
- health: `http://127.0.0.1:8000/health`

`.python-version`, `.nvmrc`, package engines, `packageManager`와 lockfile이 local 기준을 명시합니다. 생성되는 venv와 `node_modules`는 Git에 포함하지 않습니다. Python direct dependency를 바꿀 때는 `requirements*.txt`와 Python 3.13/Linux에서 해석한 `requirements*.lock`을 함께 갱신합니다.

## Docker

```bash
docker build -t gjallar:local .
docker run --rm --env-file .env -p 8000:8000 gjallar:local
```

container startup은 Alembic migration, Create VM profile seed, 선택적 bootstrap admin을 수행한 뒤 Uvicorn을 시작합니다. bootstrap admin은 `GJALLAR_BOOTSTRAP_ADMIN_USERNAME`과 `GJALLAR_BOOTSTRAP_ADMIN_PASSWORD`가 모두 있을 때만 생성됩니다.

## 안전 원칙

- live Proxmox mutation과 smoke test는 target과 side effect를 확인한 별도 승인이 필요합니다.
- API 결과가 불확실할 때 `qm`으로 자동 fallback하거나 같은 mutation을 재호출하지 않습니다.
- arbitrary shell/SSH executor는 제품 범위가 아닙니다.
- `.env`, password, API token, session token과 private key를 commit·log·artifact에 남기지 않습니다.
- 적용된 Alembic migration을 수정하거나 삭제하지 않습니다.

## 검증

```bash
git diff --check
pnpm run verify
pnpm run verify:container
```

`verify`는 local backend test → frontend test → frontend lint → frontend build 순서로 실행합니다. `verify:container`는 Python 3.13 backend test stage와 Node 24/pnpm 10 frontend 검증을 포함한 production image build를 실행합니다.

## 문서

공동 source of truth는 `project-docs/` 하나입니다.

- [`project-docs/project-profile.md`](project-docs/project-profile.md): 기술·검증·저장소 기준
- [`project-docs/api/current-api-v1.md`](project-docs/api/current-api-v1.md): 현재 API
- [`project-docs/database/current-schema-and-ownership.md`](project-docs/database/current-schema-and-ownership.md): 현재 DB와 목표 ownership
- [`project-docs/flows/verified-operation-lifecycle.md`](project-docs/flows/verified-operation-lifecycle.md): 승인된 operation 흐름
- [`project-docs/operations/runbook.md`](project-docs/operations/runbook.md): 실행·장애 대응

역사적 live-smoke 자료는 `project-docs/evidence/legacy-live-smoke/`, 과거 rewrite raw artifact는 `artifacts/rewrite-baseline/`에 보존하지만 active 요구사항의 근거로 사용하지 않습니다.
