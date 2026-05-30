# 상단 탭별 현재 구현

이 폴더는 한국어 독자를 위한 상단 탭별 구현 설명입니다. 기준 우선순위는 active code/tests, [영어 current state](../../../current/README.md), [영어 top-tabs](../../../current/top-tabs/README.md), [영어 architecture docs](../../../architecture/README.md)입니다.

## 탭별 문서

- [Dashboard](01-dashboard.md)
- [Infra Explorer](02-infra-explorer.md)
- [Networks](03-networks.md)
- [Create VM](04-create-vm.md)
- [Placement / DRS Advisor](05-placement-drs-advisor.md)
- [Jobs/Runs](06-jobs-runs.md)
- [Risks/Alerts](07-risks-alerts.md)

## 전체 요약

현재 active UI route는 `/`, `/infra`, `/networks`, `/create`, `/drs`, `/jobs`, `/risks`입니다. Active backend prefix는 `/api/v1`입니다.

Current `/drs`는 backend-owned DRS Advisor read/check UI입니다. Backend에는 local approval/job substrate, narrow operator-only migration execution route, UPID/task tracking, verified post-check, read-only reconcile preview가 있지만, broad approval/execute/reconcile UI는 아직 없습니다.
