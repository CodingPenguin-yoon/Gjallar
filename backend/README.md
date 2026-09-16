# Gjallar Backend

Gjallar의 FastAPI backend입니다. PostgreSQL에 사용자·작업·증거를 저장하고 Proxmox VE API로 인프라를 관찰하며 제한된 VM action을 실행합니다.

- 현재 구현 확인일: `2026-09-07`
- 기준 runtime: Python `3.13`, PostgreSQL, SQLAlchemy 2, psycopg 3
- 전체 안내: [문서 홈](../project-docs/README.md)

## 현재 책임

- local user/session과 `viewer < operator < admin` 권한
- authoritative Proxmox inventory와 source별 partial observation
- DB profile 기반 template clone, resize/config, 선택적 start와 생성 결과 검증
- VM Start, graceful VM Shutdown, post-create readiness evidence
- 공통 Operation·event timeline과 Guided `qm unlock`의 안내·attestation·API verification
- durable target lock, fenced recovery lease와 네 action의 GET-only recovery
- DB-backed Jobs/Artifacts/Risks와 observe-only Insights
- production React SPA의 same-origin serving

현재 Create VM은 기존 Proxmox template을 복제합니다. DB profile이 필요하며 draft/preflight/plan 단계에서도 Jobs/artifact를 기록합니다. template 우선 폼·profile 선택화·persistence 단순화는 [ADR-008의 후속 방향](../project-docs/decisions/adr-008-template-based-create-and-persistence-simplification.md)이고 아직 구현하지 않았습니다.

partial snapshot은 읽기에 사용할 수 있지만 생성·시작·종료에는 complete `live`가 필요합니다. DB target lock은 서로 충돌하는 mutation을 막고 recovery lease는 관찰자의 처리 권한을 제한합니다. 전환 중인 파일 guard와 Create request/Jobs/workload projection도 여전히 병행합니다.

Recovery handler는 `vm_start_observation`, `vm_shutdown_observation`, `vm_create_observation`, `guided_qm_unlock_observation`입니다. background runner는 기본 비활성, concurrency 1이며 operator-triggered observe와 같은 GET-only 경계를 사용합니다. 원래 Proxmox mutation·Guided 명령·보상 작업을 재실행하지 않습니다.

## 코드와 계약 찾기

| 경로 | 책임 |
|---|---|
| `app/main.py` | FastAPI composition, lifespan recovery runner, SPA serving |
| `app/api/v1/` | inventory, Operations, Insights, Jobs, VM action, Create 호환 HTTP route |
| `app/auth/` | 인증·session·계정 관리 |
| `app/workloads/`, `app/setup_integration/` | inventory query와 연결 상태 |
| `app/operations/` | 공통 lifecycle·event·lock·recovery와 action별 검증 |
| `app/vm_create/` | 기존 Create draft·preflight·plan·approval·Proxmox runner |
| `app/insights/` | risk/readiness/capacity/placement 계산 |
| `app/db/`, `app/jobs/`, `alembic/` | 현재 persistence·호환 projection·migration |

domain-oriented modular monolith로 전환 중이며 기존 package/table이 모두 새 경계로 옮겨진 것은 아닙니다. 상세 책임은 [현재 아키텍처](../project-docs/architecture/overview.md), 공개 계약은 [API](../project-docs/api/current-api-v1.md)와 [DB 문서](../project-docs/database/current-schema-and-ownership.md)를 봅니다.

## 실행과 검증

환경 준비, lockfile 설치, DB migration·profile seed·계정 CLI, Docker entrypoint, 환경 변수와 검증 명령은 [운영 Runbook](../project-docs/operations/runbook.md)을 단일 기준으로 사용합니다. 준비된 환경에서 저장소 root의 `pnpm run backend`로 backend를 시작합니다.

direct dependency 선언은 `requirements*.txt`, 설치 기준은 Python 3.13/Linux에서 해석한 `requirements*.lock`입니다. SQLite는 명시적으로 허용한 test 전용이며 runtime DB가 아닙니다. `/health`는 DB·Proxmox deep readiness 검사가 아닙니다.

변경 시 trusted actor를 session에서 얻고, read adapter와 mutation capability를 분리하며, task 접수만으로 성공을 선언하지 않습니다. 구조·계약·lock/recovery 변경과 live 작업의 승인 경계는 [프로젝트 프로필](../project-docs/project-profile.md)을 따릅니다.
