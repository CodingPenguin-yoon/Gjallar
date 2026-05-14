# Gjallar 한국어 안내서

작성일: 2026-05-15. Current 구현 기준 문서는 2026-05-14 기준으로 갱신되어 있습니다.

이 폴더는 한국어 사용자가 Gjallar의 현재 구조와 API를 빠르게 이해하기 위한 설명 계층입니다. 제품, 아키텍처, API의 최종 기준은 기존 영어/current/architecture/product 문서와 active code/tests입니다. 이 폴더의 설명이 canonical 문서와 충돌하면 canonical 문서를 우선합니다.

## 기준 문서 우선순위

현재 구현을 확인할 때는 다음 순서를 따릅니다.

1. Active code and tests: `frontend/src`, `backend/app`, current tests.
2. [Current implemented state](../current/README.md).
3. [Current top-tab snapshots](../current/top-tabs/README.md).
4. [Architecture docs](../architecture/README.md).
5. [DRS Advisor product target](../product/drs-advisor/README.md)는 목표 방향과 미구현 gap 확인용입니다.

다음 문서는 배경 자료로만 봅니다.

- `docs/archive/**`
- `docs/history/**`
- `docs/product/legacy-prd/**`
- `docs/product/prd/**`

특히 오래된 PRD에는 Terraform, `server-net`, 구현되지 않은 DRS 실행, 단일 profile 전제 같은 superseded 내용이 있을 수 있습니다.

## 읽는 순서

1. [01-current-state.md](01-current-state.md): 지금 구현된 화면과 기능.
2. [02-architecture-overview.md](02-architecture-overview.md): 시스템 구조, source of truth, read/write boundary.
3. [03-api-guide.md](03-api-guide.md): 현재 `/api/v1` endpoint별 한국어 설명.
4. [04-create-vm.md](04-create-vm.md): Create VM draft부터 native create까지의 상세 흐름.
5. [05-drs-advisor.md](05-drs-advisor.md): DRS Advisor 제품 목표와 현재 Placement 상태.
6. [06-remaining-work.md](06-remaining-work.md): 남은 구현 작업과 문서 관리 원칙.

## 기준 문서 링크

- [Root docs index](../README.md)
- [Current implemented state](../current/README.md)
- [Current API V1](../architecture/api/current-api-v1.md)
- [Architecture index](../architecture/README.md)
- [System overview](../architecture/system/overview.md)
- [Create VM architecture](../architecture/create-vm/overview.md)
- [Create VM native flow](../architecture/create-vm/native-create-flow.md)
- [Create VM provisioning contract](../architecture/VM_PROVISIONING_CONTRACT.md)
- [Create VM profile/template/network design](../architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md)
- [Placement and target DRS Advisor](../architecture/placement-drs-advisor/overview.md)
- [Target DRS API candidates](../architecture/api/target-drs-api.md)
- [DRS Advisor product direction](../product/drs-advisor/README.md)

## 용어 표기

한국어 문서에서는 읽기 쉽게 설명하되, API path, method, route, module, artifact type, field name, profile id 같은 구현 식별자는 English 그대로 둡니다.

예: `POST /api/v1/vm-create/{draft_id}/execute`는 한국어로 "manifest commit endpoint"라고 설명하지만 endpoint 이름은 바꾸지 않습니다.
