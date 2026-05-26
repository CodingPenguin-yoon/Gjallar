# DRS Advisor 제품 문서

이 폴더는 한국어 DRS Advisor product target 설명입니다. 기준 우선순위는 active code/tests, [영어 DRS Advisor PRD source](../../../product/drs-advisor/README.md), [current state](../../../current/README.md), [target DRS architecture](../../../architecture/placement-drs-advisor/recommendation-and-execution.md)입니다.

현재 구현은 DRS Advisor read-only Phase 1입니다. Current `/drs`는 backend-owned recommendation read model을 사용하지만 migration 실행은 없습니다.

## 읽는 순서

1. [01_PRODUCT_DIRECTION.md](01_PRODUCT_DIRECTION.md)
2. [03_DATA_DB_AND_IDENTITY.md](03_DATA_DB_AND_IDENTITY.md)
3. [04_DRS_RECOMMENDATION_AND_EXECUTION.md](04_DRS_RECOMMENDATION_AND_EXECUTION.md)
4. [02_UI_AND_FLOWS.md](02_UI_AND_FLOWS.md)
5. [05_IMPLEMENTATION_PLAN.md](05_IMPLEMENTATION_PLAN.md)

## 왜 DRS Advisor인가

Proxmox cluster 운영에서는 "어느 VM을 어느 node로 옮기면 좋은가"보다 "그 이동이 지금 안전하고 감사 가능하며 실패해도 정리 가능한가"가 더 중요합니다. DRS Advisor는 자동 DRS가 아니라 operator가 current evidence를 보고 승인하는 control tower입니다.
