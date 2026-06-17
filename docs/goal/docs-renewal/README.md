# Gjallar 문서 리뉴얼 골

Status: planned workspace.

이 폴더는 Gjallar 문서 리팩토링을 3개 골 안에서 끝내기 위한 작업
지침서다. 최종 사용자용 문서가 아니다. 최종 문서는 `docs/start`,
`docs/overview`, `docs/architecture`, `docs/implementation`, `docs/features`,
`docs/api`, `docs/operations`, `docs/decisions`, `docs/archive` 아래에 둔다.

`docs/goal/docs-renewal`은 작업을 추적하는 공간일 뿐, 구현 상태의
source of truth가 되면 안 된다.

## 고정 독자

문서는 한 명의 독자를 기준으로 쓴다.

> Gjallar를 처음 보는 사람. FastAPI, React, 백엔드 구조, Proxmox 연동을
> 잘 모를 수 있지만, 이 프로젝트를 이해하고 운영하고 안전하게 수정해야
> 하는 사람.

이 독자는 사용자 본인이고, 동시에 이후 작업을 이어받는 AI/code agent이기도
하다. 그래서 문서는 단순 소개가 아니라 코드 위치, 요청 흐름, 안전 게이트,
테스트 위치까지 추적할 수 있어야 한다.

## 확정 방향

- 설명은 한국어를 기본으로 쓴다.
- 구현 식별자는 English 그대로 둔다. 예: `backend/app/api/v1/router.py`,
  `POST /api/v1/vm-create/{draft_id}/plan`, `job_runs`,
  `vm_instance_manifest`.
- `docs/ko/`는 별도 한국어 미러로 유지하지 않고, 필요한 내용을 root 문서에
  흡수한 뒤 제거한다.
- `docs/current/`는 현재 구현 요약 역할을 `docs/overview/current-state.md`와
  `docs/features/*`로 흡수한 뒤 제거한다.
- `docs/architecture/`는 시스템 수준 아키텍처만 남긴다. 기능별 상세 구현은
  `docs/features`, `docs/api`, `docs/implementation`으로 보낸다.
- `archive/`는 historical only다. 활성 문서가 archive/legacy PRD를 요구사항
  근거로 삼으면 안 된다.
- 중요한 과거 결정은 `docs/decisions/`의 ADR로 요약한다.
- Mermaid diagram을 적극적으로 쓴다. 시스템 구조, 요청 흐름, 권한 게이트,
  상태 전이, 데이터 관계는 그림으로 먼저 잡고 설명한다.
- 짧은 인덱스 문서보다, 모르는 사람이 실제로 따라갈 수 있는 자세한 문서를
  우선한다.

## 목표 폴더 구조

```text
docs/
  README.md
  start/
    README.md
    new-reader.md
    for-dev.md
    for-ops.md
    for-product.md
    backend-for-beginners.md
  overview/
    current-state.md
    system-summary.md
    glossary.md
  architecture/
    README.md
    system.md
    backend.md
    frontend.md
    data.md
    proxmox.md
    auth-sessions.md
  implementation/
    README.md
    request-flow-primer.md
    backend-code-map.md
    frontend-code-map.md
    database-code-map.md
    test-code-map.md
    feature-code-maps/
      create-vm.md
      drs-advisor.md
      auth-sessions.md
      jobs-artifacts.md
      inventory.md
      vm-actions.md
      admin-users.md
  features/
    README.md
    dashboard.md
    vm-instances.md
    network-readiness.md
    create-vm.md
    drs-advisor.md
    drs-policies.md
    jobs-runs.md
    risks-alerts.md
    settings-auth-admin.md
  api/
    README.md
    auth.md
    inventory.md
    create-vm.md
    drs.md
    jobs-artifacts.md
    admin.md
  operations/
    README.md
    docker-deploy.md
    runtime-config.md
    database.md
    proxmox-connection.md
    auth-admin.md
    create-vm-runbook.md
    drs-runbook.md
    jobs-artifacts.md
    troubleshooting.md
    live-smoke-checks.md
  decisions/
    README.md
    0001-proxmox-native-create-vm.md
    0002-remove-legacy-iac-readiness.md
    0003-local-auth-sessions-and-roles.md
    0004-approval-gated-drs-migration.md
    0005-db-backed-jobs-and-artifacts.md
    0006-read-only-inventory-baseline.md
  archive/
```

## 골 구성

| Goal | 목적 | 문서 |
| --- | --- | --- |
| Goal 1 | 새 문서 기반, 첫 진입점, 독자 경로를 만든다. | `goal-01-foundation.md` |
| Goal 2 | Feature, API, implementation 문서를 작성해서 UI에서 코드와 테스트까지 추적 가능하게 만든다. | `goal-02-feature-api-implementation.md` |
| Goal 3 | Operations 문서, ADR, 기존 문서 흡수/삭제, 링크 검증까지 끝낸다. | `goal-03-operations-cleanup-validation.md` |

문서 리뉴얼은 이 3개 골 안에서 끝내는 것을 기본값으로 한다. 기능마다 새 골을
만들지 않는다.

## 완료 기준

- `docs/README.md`가 프로젝트 설명, 문서 대시보드, 학습 경로를 제공한다.
- 새 독자가 주요 기능을 UI -> API client -> FastAPI router -> domain logic
  -> DB/artifact/Proxmox -> tests 순서로 따라갈 수 있다.
- `docs/current/`와 `docs/ko/`는 필요한 내용이 흡수된 뒤 제거된다.
- `docs/architecture/`는 시스템 수준 문서만 담는다.
- `docs/features/`는 기능 동작과 현재 구현 상태를 담는다.
- `docs/api/`는 API 계약과 구현 연결 정보를 담는다.
- `docs/implementation/`은 코드 맵과 요청 흐름 입문서를 담는다.
- `docs/operations/`는 배포, 런타임 설정, 장애 대응, runbook을 담는다.
- `docs/decisions/`는 현재 중요한 결정의 ADR을 담는다.
- `docs/archive/`는 historical only로 유지된다.
- 링크 검증과 문서 정리 guard 테스트가 통과한다.

## 검증 명령

각 골이 끝날 때, 변경 범위에 맞게 아래 명령을 실행한다.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend backend/venv/bin/python -m pytest -q -p no:cacheprovider backend/tests/contracts/test_legacy_backend_cleanup.py
git diff --check
rg -n "docs/ko|docs/current|product/legacy-prd|product/status|engineering/architecture" docs README.md backend frontend
```

마지막 `rg`는 초반 골에서는 0건을 기대하지 않는다. 진행 상황을 확인하는
감사용 명령이다. Goal 3 완료 시점에는 제거된 문서 구조를 활성 문서가
권위처럼 참조하지 않아야 한다.
