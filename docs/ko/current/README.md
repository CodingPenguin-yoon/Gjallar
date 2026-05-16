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

Gjallar의 현재 baseline은 Proxmox inventory, Dashboard aggregation, Infra Explorer의 gated stopped-VM Start action, Networks bridge/policy view, read-only Placement, Jobs/Runs, Risks/Alerts, 그리고 Create VM supporting capability입니다.

DRS Advisor는 목표 제품 방향입니다. 현재 backend DRS recommendation API, `/api/v1/drs/*`, DB identity/fingerprint/policy/lock/reconciliation, final pre-check, live migration, UPID tracking은 구현되어 있지 않습니다.

Create VM은 강한 보조 capability입니다. 현재 active 생성 경로는 Proxmox native create이며, approval과 final acknowledgement 뒤에 실행됩니다. Legacy `execute/archive` manifest route는 active API에서 제거됐습니다. 기본 `stopped` 정책은 VM을 꺼진 상태로 끝내고, 선택 `boot_and_verify` 정책은 VM을 시작한 뒤 guest-agent IP와 cloud-init completion까지 확인합니다.
