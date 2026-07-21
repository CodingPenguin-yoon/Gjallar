# 프로젝트 프로필

- 상태: `APPROVED`
- 하네스 버전: `1.0.0`
- 최종 검토일: `2026-07-21`
- 최종 승인자: `사용자`
- 문서 기준 언어: 한국어

## 프로젝트 기본 정보

- 프로젝트명: `Gjallar`
- 한 줄 목적: Proxmox의 실제 상태와 실행 권위를 존중하면서 운영 의도, 정책, 승인, 검증, 증거를 통합하는 Verified Operations Control Plane
- 주요 사용자: Proxmox 인프라 운영자와 관리자(`viewer`, `operator`, `admin`)
- 저장소 형태: React SPA, FastAPI backend, PostgreSQL/Alembic, Docker runtime을 함께 관리하는 단일 저장소
- 신규 또는 기존 프로젝트: `existing`

## 선택한 Preset

- 활성 preset: `fastapi + react`
- 선택 이유: 현재 backend와 frontend의 실제 framework에 해당한다. preset은 기술별 확인·검증 기준으로 사용하며 프로젝트 결정은 이 문서와 ADR에 둔다.

Spring Boot preset은 적용하지 않는다.

## 기술 스택과 버전

아래 버전은 저장소 선언과 lock file 기준이다. 신규 기술 선택이 아니며 공식 지원 상태는 별도로 재검증하지 않았다.

| 영역 | 현재 기술·버전 | 근거 | 공식 정보 확인일 |
|---|---|---|---|
| 언어·런타임 | Docker `Python 3.13`, `Node.js 24`, `pnpm 10` | `Dockerfile` | 미확인 — 기존 선언 기준 |
| backend framework | FastAPI `0.104.1`, Uvicorn `0.24.0`, Pydantic `2.13.4` | `backend/requirements.txt`, `backend/requirements.lock` | Python 3.13/Linux lock 기준 |
| frontend framework | React 선언 `^18.2.0`/lock `18.3.1`, React Router 선언 `^7.13.0`/lock `7.14.2`, Vite lock `5.4.21` | `frontend/package.json`, `frontend/pnpm-lock.yaml` | 미확인 — 기존 선언 기준 |
| 데이터 접근 | SQLAlchemy `2.0.51`, psycopg `3.3.4` | `backend/requirements.txt`, `backend/requirements.lock` | Python 3.13/Linux lock 기준 |
| 데이터베이스·migration | PostgreSQL runtime, Alembic `>=1.13,<2.0`; SQLite는 명시적으로 허용된 테스트 전용 | `backend/app/db/config.py`, `backend/alembic/` | 미확인 — 기존 선언 기준 |
| 주요 외부 시스템 | Proxmox VE API | `backend/app/proxmox/`, `.env.example` | 환경별 확인 필요 |

## 재현 가능한 개발 환경

- 배포 기준: Docker frontend build는 `node:24-slim`과 `pnpm@10`, runtime은 `python:3.13-slim`을 사용한다.
- 로컬 격리·버전: `.python-version`은 Python `3.13`, `.nvmrc`와 frontend engines는 Node `24`/pnpm `10`, backend virtualenv는 `backend/venv`를 사용한다.
- lock·wrapper: frontend는 `frontend/pnpm-lock.yaml`과 pnpm `10.34.5`, backend runtime은 `requirements.lock`, development/test는 `requirements-dev.lock`을 사용한다. `requirements*.txt`는 direct dependency 갱신 원본이다.
- 로컬 시작 절차: `README.md`, `backend/README.md`, `frontend/README.md`, `project-docs/operations/runbook.md`.
- Git 제외 산출물: `.env*`, Python virtualenv/cache, runtime DB·task cache, frontend dependency/build output, `.agent-local/`.

## 아키텍처 상태

- 현재 아키텍처: 기능별 package가 있는 monolith에서 domain-oriented modular monolith로 전환 중이다. Setup/Integration·Workloads read boundary, 공통 Operation projection/event 저장 구조, Operations의 VM Start·Create VM·Guided `qm unlock`, Workload Cockpit·Operations·Insights frontend vertical slice가 구현됐고, 나머지는 기존 feature-oriented 구조를 page adapter로 유지한다. 단일 FastAPI application과 React SPA를 하나의 Docker image로 배포한다.
- 현재 기준선: [`architecture/overview.md`](architecture/overview.md)
- 승인된 목표 제품 경계: [`ADR-001`](decisions/adr-001-proxmox-gjallar-authority-boundary.md) (`ACCEPTED`)
- 승인된 목표 구조: [`ADR-002`](decisions/adr-002-modular-monolith-domain-boundaries.md) (`ACCEPTED`)
- 승인된 목표 도메인: Workloads, Operations, Policy/Approval, Evidence/Audit, Insights와 지원 영역 Access, Setup/Integration.
- 실제 전환: 승인된 [`plans/2026-07-20-verified-operations-control-plane-transition.md`](plans/2026-07-20-verified-operations-control-plane-transition.md)에 따라 작은 vertical slice로 수행한다.

ADR의 전체 목표 구조가 구현된 것은 아니다. Setup/Integration·Workloads read boundary, VM Start·Create VM·Guided `qm unlock`, frontend app shell·Workloads·Operations처럼 slice별 구현·검증이 끝난 부분만 현재 아키텍처로 간주한다.

## 저장소 지도

| 책임 | 경로 | 비고 |
|---|---|---|
| backend application | `backend/app/` | FastAPI, auth, DB, Proxmox, VM workflow, DRS, jobs, additive Insights query |
| frontend application | `frontend/src/app/`, `pages/`, `features/`, `entities/`, `shared/` | route shell과 page composition, Workloads·Operations·Insights feature, Operation·Insight entity, 공통 API·auth·connection |
| frontend compatibility | `frontend/src/components/`, `utils/`, `services/` | 아직 전환하지 않은 screen·view model과 기존 import 경로 adapter |
| backend tests | `backend/tests/` | contract, DB, auth, jobs, Proxmox, VM workflow, DRS |
| frontend tests | `frontend/tests/` | Node `.mjs` contract·view-model·source checks |
| runtime·build | `Dockerfile`, `docker/`, `.env.example`, root `package.json` | single image와 local dual-process 흐름 |
| DB migration | `backend/alembic/`, `backend/alembic.ini` | 적용 이력을 보존하며 덮어쓰지 않는다 |
| 공동 기준 문서 | `project-docs/` | 명세, 현재 기준선, ADR, domain, flow, API, DB, 고위험 Plan |
| 역사적 증거 | `artifacts/rewrite-baseline/` | active source of truth가 아니며 원본 evidence로만 보존 |
| 공통 하네스 | `AGENTS.md`, `.agent-harness/`, `.agents/skills/` | 프로젝트 문서 초기화 대상이 아니다 |

## 검증 명령

| 목적 | 실행 위치 | 명령 | 필수 조건·현재 상태 |
|---|---|---|---|
| diff 검사 | 저장소 루트 | `git diff --check` | 사용 가능 |
| Frontend Lint | 저장소 루트 | `pnpm --dir frontend lint` | dependency 설치 필요 |
| 타입 검사 | - | 해당 없음 | 별도 명령이 없음 |
| Backend 전체 테스트 | 저장소 루트 | `pnpm run test:backend` | `backend/venv`에 `requirements-dev.lock` 설치 필요 |
| Backend Python 3.13 테스트 | 저장소 루트 | `pnpm run test:backend:container` | Docker daemon 필요 |
| Frontend 전체 테스트 | 저장소 루트 | `pnpm run test:frontend` | frontend dependency 필요 |
| Frontend build | 저장소 루트 | `pnpm --dir frontend build` | frontend dependency 필요 |
| Container build | 저장소 루트 | `docker build -t gjallar:local .` | Docker와 dependency download 가능 환경 필요 |
| 로컬 실행 | 저장소 루트 | `pnpm run dev` | `.env`, PostgreSQL, backend venv, frontend dependency 필요 |
| 공통 검증 | 저장소 루트 | `pnpm run verify` | backend/frontend dependency 필요 |
| 기준 container 검증 | 저장소 루트 | `pnpm run verify:container` | Python 3.13 backend test와 Node 24/pnpm 10 frontend test/lint/build 포함 |

## 프로젝트별 고위험 영역

- Create VM, VM lifecycle, migration처럼 실제 Proxmox 상태를 변경하는 경로
- API dispatch, `qm` guided-manual handoff, UPID/task polling, post-check 사이의 불확실성
- idempotency, target-scoped concurrency, operation lock·lease와 restart recovery
- 승인 evidence, plan digest, actor, audit, artifact redaction과 보존
- 인증·권한·session과 production/demo 연결 모드
- PostgreSQL schema, migration, data ownership, transaction 경계
- `/api/v1` 공개 계약과 frontend route 호환성

## 추가 승인 경계

- live Proxmox mutation 또는 smoke test
- DB schema, 적용 migration 이후의 새 migration, 데이터 이동, transaction boundary 변경
- `/api/v1` 호환성을 깨는 변경과 canonical frontend route 변경
- raw shell/SSH executor, background runner, queue, scheduler, cache 또는 신규 외부 시스템 도입
- 인증·권한 구조, 별도 approver role, WORM audit 수준의 도입
- domain boundary, data ownership, dependency direction의 실제 전환

## 문서 지도

| 주제 | 현재 문서 |
|---|---|
| 프로젝트 명세 | [`specifications/project-specification.md`](specifications/project-specification.md) |
| 현재 아키텍처 기준선 | [`architecture/overview.md`](architecture/overview.md) |
| 제품 권한·실행 경계 | [`ADR-001`](decisions/adr-001-proxmox-gjallar-authority-boundary.md) |
| Production 연결 상태 | [`ADR-003`](decisions/adr-003-production-inventory-connection-truth.md) |
| 목표 모듈 구조 | [`ADR-002`](decisions/adr-002-modular-monolith-domain-boundaries.md) |
| 목표 도메인 | [`domains/domain-map.md`](domains/domain-map.md) |
| 목표 operation lifecycle | [`flows/verified-operation-lifecycle.md`](flows/verified-operation-lifecycle.md) |
| 현재 API 기준선 | [`api/current-api-v1.md`](api/current-api-v1.md) |
| 현재 DB·소유권 기준선 | [`database/current-schema-and-ownership.md`](database/current-schema-and-ownership.md) |
| 운영 Runbook | [`operations/runbook.md`](operations/runbook.md) |
| Historical live evidence | [`evidence/legacy-live-smoke/README.md`](evidence/legacy-live-smoke/README.md) |
| 전환 Plan | [`plans/2026-07-20-verified-operations-control-plane-transition.md`](plans/2026-07-20-verified-operations-control-plane-transition.md) |
| Operations Core·Guided `qm` Plan | [`plans/2026-07-20-operations-backend-core-and-guided-qm.md`](plans/2026-07-20-operations-backend-core-and-guided-qm.md) |
| Frontend Workload·Operations Plan | [`plans/2026-07-21-frontend-workload-operations-slice.md`](plans/2026-07-21-frontend-workload-operations-slice.md) |
| Create VM Common Operation Plan | [`plans/2026-07-21-create-vm-common-operation-integration.md`](plans/2026-07-21-create-vm-common-operation-integration.md) |
| Insights Productization Plan | [`plans/2026-07-21-insights-productization-and-drs-maintenance.md`](plans/2026-07-21-insights-productization-and-drs-maintenance.md) |

## 미확정 사항과 알려진 위험

- 목표 구조는 일부 vertical slice만 구현됐다. frontend app shell·Workloads·Operations·Insights는 전환됐지만 Create VM·DRS maintenance·Jobs·legacy Risks·Admin의 내부 screen은 page adapter 뒤 기존 구조를 사용하므로 현재 기준선과 목표 문서를 계속 구분한다.
- 단계 3에서 product runtime의 fake inventory를 제거하고 `unconfigured`/`live`/`degraded` connection truth와 frontend route gate를 구현했다.
- VM Start의 domain command·application use case·external port·workflow 상태기계를 `operations/vm_start`에 두고 기존 endpoint·job/artifact를 compatibility facade로 유지한다. 공통 Operation projection/event를 함께 기록한다.
- Create VM의 stable intent와 공통 lifecycle tracking을 `operations/vm_create`에 두고 기존 `/vm-create/*`, `vm_create_requests`, `vm_instances`, job/artifact를 compatibility facade와 dual record로 유지한다. 신규 plan부터 common Operation을 만들며 별도 migration이나 기존 row backfill은 하지 않았다.
- 첫 Guided Manual action은 `qm unlock <vmid>`만 지원한다. backend는 명령을 실행하지 않으며 5분짜리 고정 instruction, trusted actor attestation, Proxmox API after-state 검증을 사용한다.
- backend formatter, lint, type-check 명령이 확인되지 않았다.
- long-running operation의 durable runner/lease와 자동 restart recovery 구조가 없다. Guided verification은 저장된 `verifying` 상태에서 명시적으로 재요청할 수 있다.
- VM Start/Create VM/Guided `qm unlock`은 같은 VMID local file lock으로 동시 mutation과 ambiguity를 보호하지만 single-container 전용이며 multi-cluster identity와 shared replica coordination이 없다.
- DRS는 dispatch 전 durable prepared evidence를 기록하지만 별도 DB lock을 사용해 Create/Start와 공통 target을 직렬화하지 않는다.
- 기존 Jobs/Risks read의 DB exception을 empty result로 축소하는 공개 의미는 별도 승인 전 유지한다. 새 Insights risk source는 strict query를 사용해 같은 장애를 `unavailable`로 구분한다.
- `operations`/`operation_events`는 projection과 checksum-linked append-only event를 분리하지만 application-level tamper evidence이며 external WORM이 아니다. `job_runs`와 `job_artifacts`는 기존 compatibility projection/evidence로 남아 있다.
- Guided bundle 발급 전후에 외부 Proxmox GUI·CLI가 별도 작업을 시작하는 경쟁은 local lock으로 차단할 수 없다. 짧은 expiry, active-task 재조회, after-state 검증으로 성공 오판을 막는다.
- 기존 `docs/`는 제거했고 live-smoke 원본과 `artifacts/rewrite-baseline/`은 historical evidence로 보존했다.

## 최신 검증 기준선

- canonical Python 3.13 container: backend 전체 `457 passed`.
- local Python 3.14 venv: backend 전체 `457 passed`, Insights/DRS/Risks/Jobs focused `40 passed`.
- host Node 26: frontend test 17개, ESLint, Vite production build 통과. canonical runtime이 아니므로 보조 검증으로만 사용했다.
- canonical Node 24/pnpm 10: frontend test 17개, ESLint, Vite production build 통과.
- production image: `docker build -t gjallar:local .` 통과.
- live Proxmox mutation: 실행하지 않음.
