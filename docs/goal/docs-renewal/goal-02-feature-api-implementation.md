# Goal 2: Feature, API, Implementation Docs

Status: planned.

## 목표

Gjallar의 주요 기능을 UI에서 tests까지 따라갈 수 있는 상세 문서를 작성한다.

새 독자는 각 기능을 보며 다음 흐름을 추적할 수 있어야 한다.

```text
UI -> API client -> FastAPI router -> domain logic -> DB/artifact/Proxmox -> tests
```

이 골이 문서 리뉴얼의 핵심 지식 이전 단계다.

## 하지 않을 일

- operations runbook을 이 골에서 완전히 다시 쓰지 않는다.
- 관련 내용이 흡수되기 전에는 `docs/current/`나 `docs/ko/`를 삭제하지 않는다.
- 현재 code/tests로 확인되지 않은 product/architecture 주장을 넣지 않는다.
- application behavior를 바꾸지 않는다.

## 대상 파일

새로 만든다.

```text
docs/features/
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

docs/api/
  README.md
  auth.md
  inventory.md
  create-vm.md
  drs.md
  jobs-artifacts.md
  admin.md

docs/implementation/
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
```

필요하면 갱신한다.

- `docs/README.md`
- `docs/start/for-dev.md`
- `docs/start/backend-for-beginners.md`
- `docs/overview/current-state.md`
- `docs/architecture/README.md`

## Feature 문서 요구사항

각 feature page는 아래 내용을 포함해야 한다.

- 기능이 하는 일
- UI에서 보이는 위치
- 사용자 흐름
- 요청 흐름 diagram
- 관련 API route
- backend 구현 파일과 중요한 function
- 관련 DB table, artifact type
- Proxmox 호출 여부. read-only면 read-only라고 명시
- auth/session/role gate
- 실패 상태와 blocked 상태
- 관련 tests
- "수정할 때 깨면 안 되는 것"

기능 문서는 화면 설명에서 끝나면 안 된다. 실제 구현 위치까지 내려가야 한다.

## API 문서 요구사항

각 API page는 endpoint contract와 구현 연결 정보를 포함해야 한다.

- method와 path
- request body shape 또는 중요한 field
- response shape 요약
- auth/role 요구사항
- side effect
- router function. 예: `backend/app/api/v1/router.py`
- 호출되는 domain function
- DB/artifact/Proxmox touch point
- endpoint를 보호하는 tests

API 문서는 generated OpenAPI보다 설명적이어야 한다. 이 프로젝트 안에서
endpoint가 어떤 계약과 흐름으로 동작하는지 가르쳐야 한다.

## Implementation 문서 요구사항

### `request-flow-primer.md`

일반 요청 흐름을 설명한다.

```text
React component -> apiV1.js -> FastAPI router -> domain logic -> DB/artifact
store -> Proxmox client -> response envelope -> React model
```

최소 하나의 full example을 포함한다. 예: Create VM review 또는 VM start.

### `backend-code-map.md`

아래 영역을 설명한다.

- `backend/app/main.py`
- `backend/app/api/v1/router.py`
- `backend/app/auth/*`
- `backend/app/db/*`
- `backend/app/jobs/*`
- `backend/app/proxmox/*`
- `backend/app/vm_create/*`
- `backend/app/drs/*`
- `backend/app/vm_actions/*`

### `frontend-code-map.md`

아래 영역을 설명한다.

- `frontend/src/App.jsx`
- `frontend/src/services/apiV1.js`
- `frontend/src/components/*`
- `frontend/src/utils/*`
- route/navigation structure

### `test-code-map.md`

어떤 tests가 무엇을 보호하는지 설명한다.

- API contracts
- Create VM flow
- DRS flow
- auth/session/admin behavior
- frontend model utilities
- legacy cleanup guards

## Mermaid 요구사항

최소한 아래 diagram을 포함한다.

- `docs/implementation/request-flow-primer.md`: request `sequenceDiagram`
- Create VM sequence diagram
- DRS Advisor/DRS execution flow diagram
- auth/session flow diagram
- jobs/artifacts data flow diagram

## 완료 체크리스트

- [ ] 활성 feature마다 feature doc이 있다.
- [ ] 주요 API group마다 구현 링크가 포함된 API doc이 있다.
- [ ] 주요 code area마다 code map이 있다.
- [ ] 새 독자가 Create VM을 UI에서 tests까지 따라갈 수 있다.
- [ ] 새 독자가 DRS Advisor를 UI에서 tests까지 따라갈 수 있다.
- [ ] 새 독자가 auth/admin session management를 UI/API에서 tests까지
      따라갈 수 있다.
- [ ] 기존 current/top-tab 문서가 흡수되었거나 pending absorption으로
      명시되어 있다.
- [ ] 활성 문서가 legacy PRD를 권위로 참조하지 않는다.
- [ ] link와 cleanup test가 통과한다.

## 권장 검증

```bash
find docs/features docs/api docs/implementation -type f -name '*.md' | sort
rg -n "backend/app/api/v1/router.py|frontend/src/services/apiV1.js|관련 테스트|수정할 때 주의" docs/features docs/api docs/implementation
rg -n "docs/product/legacy-prd|product/legacy-prd|docs/ko/" docs/features docs/api docs/implementation docs/README.md
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend backend/venv/bin/python -m pytest -q -p no:cacheprovider backend/tests/contracts/test_legacy_backend_cleanup.py
git diff --check
```

## Goal 3 인계 메모

Goal 3는 새 feature/API/implementation 문서를 기준으로 cleanup을 진행한다.
`docs/current/`나 `docs/ko/`에 아직 유용한 고유 내용이 남아 있으면 먼저
흡수한 뒤 삭제한다.
