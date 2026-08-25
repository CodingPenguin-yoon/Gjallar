# Gjallar

Gjallar는 Proxmox를 위한 **Observe-first Operations Intelligence with Verified Actions**를 지향합니다.

Proxmox는 VM·node·task의 actual state와 low-level execution을 소유합니다. Gjallar는 상태의 source·freshness·운영 맥락과 evidence를 연결해 설명하고, 개입이 필요할 때 Create VM, VM Start, graceful VM Shutdown과 allowlist 기반 Guided `qm unlock`만 검증된 action으로 제공합니다.

## 현재 상태와 목표

현재 코드는 React SPA, FastAPI, PostgreSQL/Alembic, Proxmox API로 구성된 점진 전환 중인 modular monolith입니다. 인증, inventory, Create VM, VM Start, graceful VM Shutdown, Operations/Guided `qm unlock`, observe-only Insights와 Jobs/Risks를 제공합니다. DRS 전용 UI·API·runtime·schema contract는 제거됐고, 기존 Jobs/Artifacts의 historical `drs_migration` 표시는 evidence compatibility로만 유지합니다.

- 목표 제품 정의: [`project-docs/specifications/project-specification.md`](project-docs/specifications/project-specification.md)
- 현재 코드 기준선: [`project-docs/architecture/overview.md`](project-docs/architecture/overview.md)
- 현재 Architecture Decision: [`ADR index`](project-docs/decisions/README.md), [`ADR-007`](project-docs/decisions/adr-007-observe-first-operations-intelligence.md)
- 구현된 기존 전환 이력: [`project-docs/plans/2026-07-20-verified-operations-control-plane-transition.md`](project-docs/plans/2026-07-20-verified-operations-control-plane-transition.md)
- DRS 제거 전환 Plan: [`project-docs/plans/2026-08-24-observe-first-operations-intelligence-transition.md`](project-docs/plans/2026-08-24-observe-first-operations-intelligence-transition.md)

`/insights`의 기존 `source=drs_advisor`와 `drs-rec-*` ID는 공개 응답 compatibility 값으로 유지하지만 DRS persistence나 실행 경로를 가리키지 않습니다.

목표 우선순위는 다음과 같습니다.

1. Proxmox observation과 freshness를 정확히 표시
2. 상태·변화·risk·readiness·capacity와 evidence를 연결해 설명
3. 필요한 경우에만 제한된 verified action 제공

DRS와 migration, automatic remediation, arbitrary shell, generic TSDB·독립 alerting platform과 multi-provider 지원은 현재 목표 범위가 아닙니다.

## 현재 제공 기능

- local user/session과 `viewer < operator < admin` RBAC
- Proxmox node, VM, template, storage, network inventory
- approval-gated native Create VM
- acknowledgement/idempotency-gated VM Start와 force fallback 없는 graceful VM Shutdown
- PostgreSQL durable target lock과 opt-in VM Start/Shutdown observation recovery
- Jobs/Artifacts/Risks 조회
- source·freshness·rule·evidence를 제공하는 observe-only Insights
- same-origin production SPA/API Docker image

Proxmox 연결은 `unconfigured`/`live`/`degraded`로 표시됩니다. product runtime은 mock/demo inventory로 fallback하지 않으며, `live`가 아니면 inventory-dependent 화면을 닫습니다. Insights는 stored risk를 유지하고 readiness/capacity/placement를 `unavailable`로 표시하며 Jobs/Risks/Account/Admin도 계속 사용할 수 있습니다.

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

`.env`의 `GJALLAR_DATABASE_URL`을 실제 PostgreSQL에 맞춘 뒤 초기화합니다. 아래 `upgrade head`는 새 빈 로컬 DB 기준입니다. 기존 또는 production DB에는 `20260824_0029` hard-zero preflight와 별도 적용 승인 전 실행하지 마십시오. DRS row가 발견되면 삭제·강제 stamp하지 말고 [`운영 Runbook`](project-docs/operations/runbook.md)의 DB migration 절차를 따릅니다.

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

production image entrypoint는 `alembic upgrade head`를 자동 실행합니다. 기존 또는 production DB를 연결한 image는 `20260824_0029` preflight와 별도 적용 승인 전 build 결과를 배포·실행하지 마십시오.

```bash
docker build -t gjallar:local .
docker run --rm --env-file .env -p 8000:8000 gjallar:local
```

container startup은 Alembic migration, Create VM profile seed, 선택적 bootstrap admin을 수행한 뒤 Uvicorn을 시작합니다. bootstrap admin은 `GJALLAR_BOOTSTRAP_ADMIN_USERNAME`과 `GJALLAR_BOOTSTRAP_ADMIN_PASSWORD`가 모두 있을 때만 생성됩니다.

VM Start/Shutdown recovery runner는 기본적으로 꺼져 있습니다. `GJALLAR_OPERATION_RECOVERY_ENABLED=true`는 모든 replica가 migration head와 durable-lock-aware code로 전환되고 open lock/recovery row를 확인한 환경에서만 사용합니다. runner는 저장된 UPID와 VM 상태를 GET으로 재관찰하며 start/shutdown mutation POST를 재호출하지 않습니다.

## 안전 원칙

- live Proxmox mutation과 smoke test는 target과 side effect를 확인한 별도 승인이 필요합니다.
- API 결과가 불확실할 때 `qm`으로 자동 fallback하거나 같은 mutation을 재호출하지 않습니다.
- insight와 recommendation은 mutation을 자동 시작하지 않습니다.
- DRS, VM migration과 automatic remediation은 목표 action 범위가 아닙니다.
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
- [`project-docs/decisions/README.md`](project-docs/decisions/README.md): 현재·역사적 Architecture Decision 인덱스
- [`project-docs/api/current-api-v1.md`](project-docs/api/current-api-v1.md): 현재 API
- [`project-docs/database/current-schema-and-ownership.md`](project-docs/database/current-schema-and-ownership.md): 현재 DB와 목표 ownership
- [`project-docs/flows/verified-operation-lifecycle.md`](project-docs/flows/verified-operation-lifecycle.md): 승인된 operation 흐름
- [`project-docs/operations/runbook.md`](project-docs/operations/runbook.md): 실행·장애 대응

역사적 live-smoke 자료는 `project-docs/evidence/legacy-live-smoke/`, 과거 rewrite raw artifact는 `artifacts/rewrite-baseline/`에 보존하지만 active 요구사항의 근거로 사용하지 않습니다.
