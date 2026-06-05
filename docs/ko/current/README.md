# 현재 구현 상태

이 폴더는 한국어 독자를 위한 현재 구현 설명입니다. 기준 우선순위는 active code/tests, [영어 current state](../../current/README.md), [영어 top-tab snapshots](../../current/top-tabs/README.md), [영어 architecture docs](../../architecture/README.md)입니다.

## 읽는 순서

- [Top navigation index](top-tabs/README.md)
- [Overview / Dashboard](top-tabs/01-dashboard.md)
- [VM Instances / Inventory](top-tabs/02-infra-explorer.md)
- [VM Instances / Network readiness](top-tabs/03-networks.md)
- [VM Instances / Create VM](top-tabs/04-create-vm.md)
- [Placement / DRS Advisor](top-tabs/05-placement-drs-advisor.md)
- [Operations / Jobs](top-tabs/06-jobs-runs.md)
- [Operations / Risks](top-tabs/07-risks-alerts.md)

## 현재 baseline

Gjallar의 현재 primary navigation은 Overview, VM Instances, DRS Advisor, Operations, Settings입니다. Canonical frontend route는 `/`, `/instances`, `/instances/create`, `/instances/networks`, `/drs`, `/operations/jobs`, `/operations/risks`, `/settings/account`, `/settings/admin/users`이고, legacy `/infra`, `/create`, `/networks`, `/jobs`, `/risks`, `/account`, `/admin/users`는 deep link alias로 같은 화면을 렌더링합니다.

Gjallar의 현재 baseline은 Proxmox inventory, Overview/Dashboard aggregation, VM Instances의 gated stopped-VM Start action과 row-based DRS policy configuration, Network readiness selected-source comparison view, DRS Advisor recommendation/check UI와 narrow backend execution substrate, Operations/Jobs, Operations/Risks, 그리고 Create VM supporting capability입니다.

DRS Advisor frontend는 recommendation/detail/check, compact policy evidence, criteria taxonomy, local approval packet creation을 제공합니다. Manual policy configuration은 VM Instances/InstanceList row workflow에 있습니다. Recommendation/check result는 `read_only=true`, `executable=false`, `allowed_actions=[]`입니다. Backend DRS는 summary/recommendation/detail/check, compact identity/fingerprint와 policy evidence, operation locks, local approval/job substrate, operator-only migration-job execute route, UPID/task tracking, verified post-check, read-only reconcile preview, stored-UPID local reconciliation follow-up을 갖고 있습니다. Approved VMID `140` live DRS smoke evidence는 기록됐습니다. Live execute UI, bulk policy edit UI, corrective reconcile UI, richer policy/rule editor, corrective mutation, background automation, automatic DRS는 아직 없습니다.

Create VM은 강한 보조 capability입니다. 현재 active 생성 경로는 Proxmox native create이며, approval과 final acknowledgement 뒤에 실행됩니다. Legacy `execute/archive` manifest route는 active API에서 제거됐습니다. 기본 `stopped` 정책은 VM을 꺼진 상태로 끝내고, 선택 `boot_and_verify` 정책은 VM을 시작한 뒤 guest-agent IP와 cloud-init completion까지 확인합니다.
