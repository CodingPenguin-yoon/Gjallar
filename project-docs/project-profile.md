# 프로젝트 프로필

- 상태: `APPROVED`
- 최종 검토일: `2026-08-24`
- 문서 기준 언어: 한국어

이 문서는 Codex가 매 작업 전에 확인하는 안정 정보 인덱스다. 구현 상세, 실행별 검증 결과와 변경 이력은 누적하지 않고 아래 현재 문서와 Git·CI·evidence에서 관리한다.

## 프로젝트와 기준 문서

- 프로젝트명: `Gjallar`
- 목적: Proxmox의 actual state와 실행 권위를 존중하면서 상태·변화·freshness와 운영 evidence를 설명하고, 필요한 경우 제한된 검증 action을 제공하는 Observe-first Operations Intelligence
- 주요 사용자: Proxmox 인프라 운영자와 관리자(`viewer`, `operator`, `admin`)
- 저장소 형태: React SPA, FastAPI backend, PostgreSQL/Alembic과 Docker runtime을 함께 관리하는 monorepo
- 제품 범위와 현재 구조: [`specifications/project-specification.md`](specifications/project-specification.md), [`architecture/overview.md`](architecture/overview.md)

## 환경

| 영역 | 기준 | 근거 |
|---|---|---|
| Runtime | Docker Python `3.13`, Node.js `24`, pnpm `10.34.5` | `Dockerfile`, `.python-version`, `.nvmrc` |
| Backend | FastAPI, Uvicorn, Pydantic 2, SQLAlchemy 2, psycopg 3 | `backend/requirements*.txt`, `backend/requirements*.lock` |
| Frontend | React 18, React Router 7, Vite 5 | `frontend/package.json`, `frontend/pnpm-lock.yaml` |
| Database | PostgreSQL + Alembic; SQLite는 명시된 test에서만 허용 | `backend/app/db/config.py`, `backend/alembic/` |
| External system | Proxmox VE API | `backend/app/proxmox/`, `.env.example` |

설치, 환경 변수, 실행과 장애 대응은 [`operations/runbook.md`](operations/runbook.md)를 따른다. `.env`, virtualenv, dependency, cache와 build output은 Git에 포함하지 않는다.

## 현재 방향과 경계

- 기능별 monolith에서 domain-oriented modular monolith로 작은 vertical slice 단위 전환 중이다. 현재와 목표 구조를 섞지 않는다.
- 제품의 기본 경로는 `Proxmox observation → 상태·변화·위험 설명 → 필요한 경우 verified action`이다. 상세 제품·권한 경계는 [`ADR-007`](decisions/adr-007-observe-first-operations-intelligence.md)을 따른다.
- Proxmox가 actual state와 low-level execution을 소유하며 Gjallar는 local metadata, observation provenance/freshness, derived finding과 지원 action의 intent·verification·evidence·audit를 소유한다.
- 지원 action은 Create VM, VM Start, graceful VM Shutdown과 allowlist 기반 Guided `qm unlock`으로 제한한다. Insights는 operation을 자동 생성하거나 dispatch하지 않는다.
- 목표 도메인과 의존성 방향은 [`ADR-002`](decisions/adr-002-modular-monolith-domain-boundaries.md)와 [`domains/domain-map.md`](domains/domain-map.md)를 따른다.
- product runtime은 Proxmox 연결 실패를 fake inventory로 대체하지 않는다. `unconfigured`·`live`·`degraded` 의미는 [`ADR-003`](decisions/adr-003-production-inventory-connection-truth.md)을 따른다.
- DRS policy·approval·execution·reconciliation, 전용 UI/API/runtime/schema contract는 제거됐다. historical Jobs/Artifacts renderer와 `/insights` legacy source·ID 값은 active DRS 기능으로 해석하거나 확장하지 않는다.
- generic TSDB·독립 alerting platform, automatic remediation과 multi-provider 지원은 현재 비범위다.
- 현재 구현 사실은 [`architecture/overview.md`](architecture/overview.md)를 따른다. 이후 공개 계약·data ownership·architecture 전환은 다시 승인된 고위험 Plan으로만 수행한다.

## 저장소 지도

| 책임 | 경로 |
|---|---|
| Backend application | `backend/app/` |
| Frontend application | `frontend/src/` |
| Backend tests | `backend/tests/` |
| Frontend tests | `frontend/tests/` |
| DB migration | `backend/alembic/`, `backend/alembic.ini` |
| Runtime·build | `Dockerfile`, `docker/`, `.env.example`, `package.json` |
| 공동 기준 문서 | `project-docs/` |

## 검증 명령

| 목적 | 명령 | 조건 |
|---|---|---|
| Diff | `git diff --check` | 항상 사용 가능 |
| Backend 전체 테스트 | `pnpm run test:backend` | `backend/venv`에 dev dependency 필요 |
| Backend container 테스트 | `pnpm run test:backend:container` | Docker daemon과 image download 필요 |
| Frontend 전체 테스트 | `pnpm run test:frontend` | frontend dependency 필요 |
| Frontend Lint | `pnpm --dir frontend lint` | frontend dependency 필요 |
| Frontend build | `pnpm --dir frontend build` | frontend dependency 필요 |
| 로컬 공통 검증 | `pnpm run verify` | backend·frontend dependency 필요 |
| Container 기준 검증 | `pnpm run verify:container` | backend container test + production image build |
| 로컬 실행 | `pnpm run dev` | `.env`, PostgreSQL, backend venv와 frontend dependency 필요 |

Backend formatter, Lint와 type-check 전용 명령은 현재 확인되지 않았다. 명령을 추측하거나 대체 검사로 성공을 주장하지 않는다.

## 프로젝트별 고위험·승인 경계

- live Proxmox mutation 또는 smoke test
- DB schema, 새 migration, 데이터 이동, 소유권, transaction과 정합성 변경
- 인증, 권한, session, 개인정보와 시크릿 처리 변경
- `/api/v1` 호환성 또는 canonical frontend route를 깨는 변경
- domain boundary, dependency direction과 주요 배포 구조 전환
- idempotency, target lock, lease, retry, recovery와 reconciliation 변경
- raw shell/SSH executor, background worker, queue, scheduler, cache 또는 신규 외부 시스템 도입
- DRS 제거 migration의 production preflight·적용, historical Jobs/Artifacts retention 또는 제거된 contract 복구
- telemetry collector, TSDB, alert delivery 또는 신규 monitoring dependency 도입

처리 workflow는 [`AGENTS.md`](../AGENTS.md)의 “위험과 승인”을 따른다. live 작업은 정확한 target과 side effect를 별도로 승인받는다.

## 문서 라우팅

| 주제 | 현재 source of truth |
|---|---|
| 제품 범위 | [`specifications/project-specification.md`](specifications/project-specification.md) |
| 현재 아키텍처·도메인·위험 | [`architecture/overview.md`](architecture/overview.md), [`domains/domain-map.md`](domains/domain-map.md) |
| API·DB | [`api/current-api-v1.md`](api/current-api-v1.md), [`database/current-schema-and-ownership.md`](database/current-schema-and-ownership.md) |
| Operation lifecycle·운영·복구 | [`flows/verified-operation-lifecycle.md`](flows/verified-operation-lifecycle.md), [`operations/runbook.md`](operations/runbook.md) |
| Durable lock·recovery 결정 | [`ADR-004`](decisions/adr-004-postgresql-durable-operation-recovery.md) |
| 현재 Architecture Decision | [`decisions/README.md`](decisions/README.md), [`ADR-007`](decisions/adr-007-observe-first-operations-intelligence.md) |
| 활성 전환과 세부 Plan | [`plans/`](plans/) |
| Historical live evidence | [`evidence/legacy-live-smoke/README.md`](evidence/legacy-live-smoke/README.md) |

작업에는 직접 관련된 문서만 추가로 읽는다. 과거 Plan이나 evidence를 현재 구현 권한으로 사용하지 않는다.
