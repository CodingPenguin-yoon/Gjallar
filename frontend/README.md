# Gjallar Frontend

Gjallar의 React + Vite operator UI입니다. backend `/api/v1`만 사용합니다.

## 현재 화면

| 영역 | canonical route | 현재 기능 |
|---|---|---|
| Overview | `/` | cluster summary와 dashboard |
| VM Instances | `/instances` | VM inventory와 gated Start |
| Create VM | `/instances/create` | draft부터 native create까지의 wizard |
| Networks | `/instances/networks` | read-only network readiness |
| Insights | `/insights` | risk/readiness/capacity/placement의 observe-only finding과 evidence |
| Operations | `/operations`, `/operations/:operationId` | verified operation 목록·상세 evidence timeline |
| Guided `qm unlock` | `/operations/guided-qm/vm-unlock` | allowlisted manual instruction·attestation·API verification |
| Jobs | `/operations/jobs` | job projection 조회 |
| Risks | `/operations/risks` | job-derived risk 조회 |
| Account | `/settings/account` | current account와 password 변경 |
| Users | `/settings/admin/users` | admin-only user/session 관리 |

일부 legacy deep-link alias가 남아 있으며 별도 deprecation 전 유지합니다.

Overview, VM Instances, Create VM과 Networks는 backend connection state가 authoritative `live`일 때만 실제 화면을 엽니다. `unconfigured`/`degraded`에서는 Workloads navigation을 숨기고 inventory-dependent direct route에 연결 안내를 표시합니다. Insights는 계속 열리며 stored risk와 unavailable inventory category를 구분합니다. Jobs, legacy Risks, Account, Users도 계속 사용할 수 있고 내장 mock/demo inventory는 없습니다.

## 목표 UI 방향

제품 중심은 Workload Cockpit, verified operation, observe-only Insights입니다. DRS 전용 route와 control은 제공하지 않습니다.

- workload state, metadata, capability, freshness, recent operation을 한 컨텍스트에 표시
- `managed_api`, `guided_manual`, `observe_only` mode를 명시
- plan, approval, task, verification, evidence와 recovery action을 timeline으로 표시
- stale/unknown/unavailable을 성공이나 실행 가능으로 추론하지 않음

승인된 목표는 [`../project-docs/specifications/project-specification.md`](../project-docs/specifications/project-specification.md)에 있으며 아직 모든 화면에 구현되지 않았습니다.

## 로컬 실행

Node.js는 저장소 `.nvmrc`, pnpm은 package의 `packageManager`에 기록된 버전을 사용합니다.

```bash
nvm use
npm install --global pnpm@10.34.5
pnpm install --frozen-lockfile
pnpm dev -- --host 0.0.0.0 --port 5173
```

또는 저장소 root에서:

```bash
pnpm run frontend
```

Vite는 repo root와 `frontend/`의 env를 읽습니다.

```dotenv
FRONTEND_PORT=5173
BACKEND_PORT=8000
VITE_BACKEND_URL=http://127.0.0.1:8000
```

`/api` request는 `VITE_BACKEND_URL` 또는 `BACKEND_PORT` 기반 local backend로 proxy됩니다. Cookie-based auth를 사용하므로 frontend API client는 credentials를 포함합니다.

## 검증

`frontend` directory에서:

```bash
pnpm test
pnpm lint
pnpm build
```

저장소 root에서는 공통 wrapper를 사용합니다.

```bash
pnpm run test:frontend
pnpm run lint:frontend
pnpm run build:frontend
```

`pnpm test`는 기존 executable `.mjs` 파일을 순서대로 실행하고 첫 실패에서 중단합니다. 일부 test는 source text/regex에 의존하므로 구조 리팩터링 전에 behavior contract를 보강합니다.

## Docker build

root Dockerfile은 Node 24와 pnpm 10으로 `pnpm install --frozen-lockfile`, `pnpm build`를 수행합니다. 생성된 `dist`는 Python runtime image에 복사되고 FastAPI가 same-origin으로 제공합니다.

## 변경 시 지켜야 할 경계

- frontend가 role, policy, freshness, executability를 자체 추론하지 않습니다.
- backend가 제공한 operation/evidence 의미를 표시합니다.
- 다른 feature의 private module을 직접 import하지 않습니다.
- canonical route와 `/api/v1` compatibility는 명시적 폐기 결정 전 유지합니다.
- secret, token, raw command output을 browser storage나 debug log에 남기지 않습니다.
