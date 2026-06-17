# 문서 리뉴얼 원칙

Status: working rules.

이 문서는 `docs/goal/docs-renewal` 아래의 세 골 전체에 적용되는 작성
원칙이다. 실제 reader-facing 문서를 만들 때 이 원칙을 먼저 따른다.

## 기본 독자

Gjallar를 처음 보는 사람을 기준으로 쓴다. 그 사람은 FastAPI, React,
database schema, Proxmox API 구조를 이미 알고 있다고 가정하지 않는다.

문서는 다음 두 대상에게 동시에 유용해야 한다.

- 사용자가 프로젝트 구조를 직접 이해하고 운영/수정할 때
- 이후 AI/code agent가 코드를 수정하기 전에 흐름을 빠르게 파악할 때

## 언어 규칙

- 설명 문장은 한국어로 쓴다.
- 구현 식별자는 English 그대로 둔다.
- 아래 항목은 번역하지 않는다.
  - API paths: `POST /api/v1/vm-create/{draft_id}/plan`
  - file paths: `backend/app/api/v1/router.py`
  - functions/classes: `build_vm_create_plan()`, `PreflightResult`
  - database tables/fields: `job_runs`, `review_summary_checksum`
  - artifact types: `vm_instance_manifest`, `observed_after`
  - roles/policies/enums: `admin`, `operator`, `read_only`

## Source Of Truth

현재 구현의 기준:

1. 활성 code와 tests
2. 새 `docs/overview`, `docs/features`, `docs/api`, `docs/architecture`,
   `docs/implementation`
3. `docs/archive`는 historical background만 제공

제품 방향의 기준:

1. 새 active product/feature docs
2. 흡수 전까지의 `docs/product/drs-advisor`
3. `docs/archive`는 historical context만 제공

작업 추적 기준:

- `docs/goal/docs-renewal`은 문서 리팩토링 작업을 추적한다.
- 구현 상태의 source of truth가 아니다.
- 리뉴얼이 끝난 뒤에도 reader-facing 문서처럼 커지면 안 된다.

## Archive 정책

- `archive/`는 historical only다.
- 활성 feature, API, architecture, operations 문서는 archive 링크에
  의존하지 않는다.
- 중요한 과거 결정은 `docs/decisions/` ADR로 요약한다.
- legacy PRD는 검색 가능하게 보관하되, 현재 요구사항의 권위로 쓰지 않는다.

## 문서가 답해야 하는 질문

주요 reader-facing 문서는 최소한 아래 질문에 답해야 한다.

- 이 문서는 어떤 질문에 답하는가?
- 누가 먼저 읽어야 하는가?
- 현재 구현된 동작은 무엇인가?
- 관련 UI, API route, backend function, DB/artifact, external system,
  test file은 어디인가?
- 어떤 safety gate와 failure mode가 있는가?
- 다음 수정자가 깨면 안 되는 계약은 무엇인가?

## Diagram 원칙

Mermaid를 적극적으로 사용한다.

- `flowchart`: 시스템 구조, 권한 게이트, feature boundary
- `sequenceDiagram`: 요청 흐름
- `stateDiagram-v2`: lifecycle/state transition
- `erDiagram` 또는 `flowchart`: 데이터 관계

그림만 두지 않는다. 각 diagram 아래에는 예외 상황과 중요한 경계 조건을
짧게 설명한다.

## File Link 원칙

구현 문서와 code map에는 실제 repository path를 직접 쓴다. 넓은 폴더명보다
구체적인 파일을 우선한다.

좋은 예:

- `frontend/src/components/CreateInstanceWizard.jsx`
- `backend/app/api/v1/router.py`
- `backend/app/vm_create/preflight.py`
- `backend/tests/contracts/test_api_v1_vm_create.py`

약한 예:

- "frontend"
- "backend"
- "API 쪽"

## Feature 문서 템플릿

```md
# Feature: Create VM

## 이 문서가 답하는 질문
## 한 줄 요약
## 화면에서 어디에 있는가
## 사용자 흐름
## 요청 흐름 다이어그램
## API 계약
## Backend 구현 위치
## DB / Artifact 사용
## Proxmox 호출 여부
## 권한 / 세션 / 안전 게이트
## 실패 / 차단 조건
## 관련 테스트
## 수정할 때 주의할 점
```

## API 문서 템플릿

```md
# API: Create VM

## 이 문서가 답하는 질문
## Endpoint Summary
## Endpoint Details
### Frontend Caller
### Router
### Domain Logic
### Data / Artifacts
### External Calls
### Permission / Gates
### Tests
```

API 문서는 generated OpenAPI를 대체하는 목록표가 아니다. 이 프로젝트에서
endpoint가 어떤 코드와 계약으로 동작하는지 설명해야 한다.

## Implementation Code Map 템플릿

```md
# Create VM Code Map

## 이 문서가 답하는 질문
## 한 줄 요약
## 요청 흐름 다이어그램
## Frontend Entry Points
## API Routes
## Backend Route Handlers
## Domain Logic
## DB / Artifact Touch Points
## External Calls
## Auth / Permission Gates
## Tests
## 수정할 때 주의할 점
```

## ADR 템플릿

```md
# 0002 Remove Legacy IaC Readiness

## Status
Accepted

## Context
## Decision
## Consequences
## Related Docs
```

ADR은 긴 PRD 복사가 아니다. 현재 유지해야 하는 결정과 그 결과를 짧고
분명하게 남기는 문서다.

## 품질 기준

- 얕은 문서 여러 개보다 완성도 있는 문서 몇 개를 우선한다.
- 길어져도 괜찮다. 단, 읽는 사람이 실제로 프로젝트를 이해할 수 있어야 한다.
- active docs에는 PRD식 추측을 넣지 않는다.
- deferred behavior는 명시한다.
- current와 target을 섞지 않는다.
- 각 phase 이후 링크와 source-of-truth 참조를 검증한다.
