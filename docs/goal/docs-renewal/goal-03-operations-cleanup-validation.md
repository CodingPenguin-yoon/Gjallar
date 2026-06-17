# Goal 3: Operations, Cleanup, Validation

Status: planned.

## 목표

문서 리뉴얼을 마무리한다. 운영 문서를 분리하고, 중요한 ADR을 작성하고,
기존 중복 문서를 흡수/삭제하고, 최종 docs tree를 검증한다.

이 골이 끝나면 새 구조가 Gjallar의 유일한 active documentation surface가
되어야 한다.

## 하지 않을 일

- application behavior를 바꾸지 않는다.
- 사용자가 명시적으로 원하지 않는 한 오래된 deep link 호환 stub을 유지하지
  않는다.
- `docs/ko/`를 영구 한국어 미러로 남기지 않는다.
- `docs/current/`를 active source-of-truth 폴더로 남기지 않는다.
- archive/legacy PRD를 active requirement로 사용하지 않는다.

## Operations 문서 대상

새로 만들거나 기존 `docs/operations/runbook.md`를 분리한다.

```text
docs/operations/
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
```

기존 `docs/operations/runbook.md`는 남은 고유 내용에 따라 index로 바꾸거나,
위 문서들로 흡수한 뒤 archive로 보낸다.

## ADR 대상

아래 ADR을 작성한다.

```text
docs/decisions/
  0001-proxmox-native-create-vm.md
  0002-remove-legacy-iac-readiness.md
  0003-local-auth-sessions-and-roles.md
  0004-approval-gated-drs-migration.md
  0005-db-backed-jobs-and-artifacts.md
  0006-read-only-inventory-baseline.md
```

각 ADR은 현재 결정과 결과를 요약한다. legacy PRD의 긴 본문을 복사하지 않는다.

## Cleanup 대상

흡수한 뒤 제거한다.

- `docs/current/`
- `docs/ko/`
- `features/`, `api/`, `implementation/`과 중복되는 domain-level old
  architecture docs
- 이제 historical인 engineering handoff/roadmap docs

active로 남길 구조:

- `docs/start/`
- `docs/overview/`
- `docs/architecture/`
- `docs/implementation/`
- `docs/features/`
- `docs/api/`
- `docs/operations/`
- `docs/decisions/`
- `docs/archive/`
- `docs/goal/`

## 최종 docs tree

```text
docs/
  README.md
  start/
  overview/
  architecture/
  implementation/
  features/
  api/
  operations/
  decisions/
  archive/
  goal/
```

## Cleanup guardrail

- 문서를 삭제하기 전에 inbound link를 검색한다.
- `docs/ko/` 삭제 전, 유용한 한국어 내용이 root Korean-primary docs에
  흡수되었는지 확인한다.
- `docs/current/` 삭제 전, `docs/overview/current-state.md`와
  `docs/features/*`가 현재 구현 세부사항을 담고 있는지 확인한다.
- `docs/operations/`의 historical live evidence는 의도적으로
  `docs/archive/operations/`로 옮기기 전에는 삭제하지 않는다.
- `docs/archive/legacy-prd/`는 historical only로 유지한다.

## Validation 요구사항

필요하면 guard test를 추가하거나 갱신해서 제거한 구조가 다시 active docs로
돌아오지 않게 한다.

- `docs/ko/` active mirror
- `docs/current/` active source-of-truth folder
- `docs/product/status`
- `docs/product/legacy-prd`
- `docs/engineering/architecture`
- active docs에서 legacy PRD를 권위처럼 참조하는 링크

## 필수 검증 명령

최소한 아래 명령을 실행한다.

```bash
find docs -maxdepth 2 -type d | sort
rg -n "docs/ko|docs/current|docs/product/status|docs/product/legacy-prd|docs/engineering/architecture|product/legacy-prd|PRD 기준" docs README.md backend frontend
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend backend/venv/bin/python -m pytest -q -p no:cacheprovider backend/tests/contracts/test_legacy_backend_cleanup.py
git diff --check
```

frontend/backend command 예시를 문서에 넣었다면, repo에서 가능한 가장 작은
smoke check도 같이 실행한다.

## 완료 체크리스트

- [ ] Operations 문서가 분리되어 탐색하기 쉽다.
- [ ] Runtime config 문서에 Docker, Heimdall, PostgreSQL, Proxmox, auth,
      allowed origins, SSH public key config가 포함되어 있다.
- [ ] Troubleshooting 문서가 login/origin failure, DB config, Proxmox API
      failure, Create VM blocked state, DRS blocked state, artifact/job lookup을
      다룬다.
- [ ] 중요한 결정에 대한 ADR이 존재한다.
- [ ] `docs/current/`가 흡수 후 제거되었다.
- [ ] `docs/ko/`가 흡수 후 제거되었다.
- [ ] `docs/architecture/`는 시스템 수준 architecture만 담는다.
- [ ] Feature/API/implementation 문서가 상세 code map을 담는다.
- [ ] Archive가 historical only로 명확히 표시되어 있다.
- [ ] Link cleanup과 docs tests가 통과한다.

## 최종 인계

Goal 3 마지막에는 `docs/README.md`를 갱신해서 새 독자가 여기를 유일한 시작점으로
써도 충분하게 만든다.

최종 source-of-truth 순서는 아래처럼 정리되어야 한다.

1. 활성 code/tests
2. `docs/overview`, `docs/features`, `docs/api`, `docs/architecture`,
   `docs/implementation`
3. `docs/operations`
4. `docs/decisions`
5. `docs/archive` as historical only
