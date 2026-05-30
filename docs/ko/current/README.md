# 현재 구현 상태

이 폴더는 한국어 독자를 위한 현재 구현 설명입니다. 기준 우선순위는 active code/tests, [영어 current state](../../current/README.md), [영어 top-tab snapshots](../../current/top-tabs/README.md), [영어 architecture docs](../../architecture/README.md)입니다.

## 읽는 순서

- [Top tabs index](top-tabs/README.md)
- [Dashboard](top-tabs/01-dashboard.md)
- [Infra Explorer](top-tabs/02-infra-explorer.md)
- [Networks](top-tabs/03-networks.md)
- [Create VM](top-tabs/04-create-vm.md)
- [Placement / DRS Advisor](top-tabs/05-placement-drs-advisor.md)
- [Jobs/Runs](top-tabs/06-jobs-runs.md)
- [Risks/Alerts](top-tabs/07-risks-alerts.md)

## 현재 baseline

Gjallar의 현재 baseline은 Proxmox inventory, Dashboard aggregation, Infra Explorer의 gated stopped-VM Start action, Networks selected-source network comparison view, DRS Advisor read/check UI와 narrow backend execution substrate, Jobs/Runs, Risks/Alerts, 그리고 Create VM supporting capability입니다.

DRS Advisor frontend는 read/check only입니다. Backend DRS는 summary/recommendation/detail/check, compact identity/fingerprint와 policy evidence, operation locks, local approval/job substrate, operator-only migration-job execute route, UPID/task tracking, verified post-check, read-only reconcile preview를 갖고 있습니다. Broad execution UI, policy editor, corrective mutation, background automation, automatic DRS, live DRS smoke evidence는 아직 없습니다.

Create VM은 강한 보조 capability입니다. 현재 active 생성 경로는 Proxmox native create이며, approval과 final acknowledgement 뒤에 실행됩니다. Legacy `execute/archive` manifest route는 active API에서 제거됐습니다. 기본 `stopped` 정책은 VM을 꺼진 상태로 끝내고, 선택 `boot_and_verify` 정책은 VM을 시작한 뒤 guest-agent IP와 cloud-init completion까지 확인합니다.
