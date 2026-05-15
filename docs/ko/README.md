# Gjallar 한국어 문서

작성일: 2026-05-15. 이 폴더는 한국어 독자를 위한 설명 계층입니다.

현재 동작의 최종 기준은 active code/tests와 영어 기준 문서입니다. 한국어 문서가 기준 문서와 충돌하면 다음 순서를 따릅니다.

1. Active code and tests: `frontend/src`, `backend/app`, current tests.
2. [Current implemented state](../current/README.md).
3. [Current top-tab snapshots](../current/top-tabs/README.md).
4. [Architecture docs](../architecture/README.md).
5. [DRS Advisor product target](../product/drs-advisor/README.md)는 목표 방향과 미구현 gap 확인용입니다.

배경 자료로만 볼 문서:

- `docs/archive/**`
- `docs/history/**`
- `docs/product/legacy-prd/**`
- `docs/product/prd/**`

## 빠른 읽기

기존 평면 문서는 빠른 길잡이입니다. 자세한 도메인별 설명은 아래 mirrored tree를 봅니다.

- [01-current-state.md](01-current-state.md): 지금 구현된 화면과 기능 요약.
- [02-architecture-overview.md](02-architecture-overview.md): 시스템 구조와 read/write boundary 요약.
- [03-api-guide.md](03-api-guide.md): 현재 `/api/v1` endpoint 빠른 안내.
- [04-create-vm.md](04-create-vm.md): Create VM 흐름 빠른 안내.
- [05-drs-advisor.md](05-drs-advisor.md): DRS Advisor 목표와 현재 Placement gap.
- [06-remaining-work.md](06-remaining-work.md): 남은 작업 요약.

## 자세한 한국어 트리

- [current/](current/README.md): 현재 구현 상태와 상단 탭별 설명.
- [architecture/](architecture/README.md): 시스템, API, 도메인, flow, stale 문장 정리.
- [product/](product/README.md): DRS Advisor 제품 목표와 왜 이 도메인이 필요한지.
- [engineering/](engineering/README.md): 작업 원칙과 현재 work plan.

## 표기 원칙

한국어 설명을 사용하되 API path, HTTP method, route, module, function, artifact type, field name, profile id 같은 구현 식별자는 English 그대로 둡니다.

예: `POST /api/v1/vm-create/{draft_id}/execute`는 "manifest commit endpoint"로 설명할 수 있지만 endpoint 자체는 번역하지 않습니다.
