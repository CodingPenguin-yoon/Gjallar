# 상단 navigation별 현재 구현

이 폴더는 한국어 독자를 위한 상단 navigation별 구현 설명입니다. 기준 우선순위는 active code/tests, [영어 current state](../../../current/README.md), [영어 top-tabs](../../../current/top-tabs/README.md), [영어 architecture docs](../../../architecture/README.md)입니다.

## Primary navigation

- Overview: [Dashboard](01-dashboard.md), route `/`
- VM Instances: [Inventory](02-infra-explorer.md), [Network readiness](03-networks.md), [Create VM](04-create-vm.md), routes `/instances`, `/instances/networks`, `/instances/create`
- [Placement / DRS Advisor](05-placement-drs-advisor.md)
- Operations: [Jobs](06-jobs-runs.md), [Risks](07-risks-alerts.md), routes `/operations/jobs`, `/operations/risks`
- Settings: Account `/settings/account`, admin users `/settings/admin/users`

## 전체 요약

현재 active primary UI nav는 `Overview`, `VM Instances`, `DRS Advisor`, `Operations`, `Settings`입니다. Canonical frontend route는 `/`, `/instances`, `/instances/create`, `/instances/networks`, `/drs`, `/operations/jobs`, `/operations/risks`, `/settings/account`, `/settings/admin/users`입니다. Legacy `/infra`, `/create`, `/networks`, `/jobs`, `/risks`, `/account`, `/admin/users`는 deep link alias로 같은 화면을 렌더링합니다. Active backend prefix는 `/api/v1`입니다.

Current `/drs`는 DRS Advisor recommendation/detail/check, compact policy evidence, criteria taxonomy, local approval packet/job intent creation UI입니다. Manual policy configuration은 VM Instances/InstanceList row workflow에 있습니다. Backend에는 local approval/job substrate, narrow operator-only migration execution route, UPID/task tracking, verified post-check, read-only reconcile preview가 있지만, live execute/corrective reconcile UI는 아직 없습니다.
