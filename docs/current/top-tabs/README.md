# Top Navigation Implementation Status

평가일: 2026-05-30

이 폴더는 현재 상단 navigation별 구현 스냅샷을 기록한다. 제품 방향의 최종 기준은 [DRS Advisor target direction](../../product/drs-advisor/README.md)이며, 구현 baseline은 [current implemented state](../README.md)를 따른다. 제품 목표와 현재 구현이 다르면 `docs/product/drs-advisor/`는 target을 설명하고, 이 폴더는 지금 앱에서 보이는 상태와 gap을 설명한다.

최신 통합 검증 baseline은 [current implemented state](../README.md)에 기록된 최근 결과를 따른다. 개별 top-tab 문서는 원래 평가일의 스냅샷을 유지할 수 있으며, 최신 검증 결과를 새로 실행했다고 주장하지 않는다.

## Primary navigation

- Overview: [Dashboard](01-dashboard.md), route `/`
- VM Instances: [Inventory](02-infra-explorer.md), [DRS Policies](08-drs-policies.md), [Create VM](04-create-vm.md), [Network readiness](03-networks.md), routes `/instances`, `/instances/drs-policies`, `/instances/create`, `/instances/networks`
- DRS Advisor: [Placement / DRS Advisor](05-placement-drs-advisor.md), route `/drs`
- Operations: [Jobs](06-jobs-runs.md), [Risks](07-risks-alerts.md), routes `/operations/jobs`, `/operations/risks`
- Settings: Account at `/settings/account`; admin user management at `/settings/admin/users`

## 전체 요약

현재 active primary UI nav는 [frontend/src/App.jsx](../../../frontend/src/App.jsx)의 `Overview`, `VM Instances`, `DRS Advisor`, `Operations`, `Settings`다. Canonical frontend route는 `/`, `/instances`, `/instances/drs-policies`, `/instances/create`, `/instances/networks`, `/drs`, `/operations/jobs`, `/operations/risks`, `/settings/account`, `/settings/admin/users`이며 legacy `/infra`, `/create`, `/networks`, `/jobs`, `/risks`, `/account`, `/admin/users`는 deep link 보존용 alias로 같은 화면을 렌더링한다. active backend prefix는 [backend/app/api/v1/router.py](../../../backend/app/api/v1/router.py)의 `/api/v1`이며, auth/admin route는 [backend/app/auth/](../../../backend/app/auth/)에서 같은 `/api/v1` contract로 등록된다.

구현 baseline은 Proxmox inventory, Overview/Dashboard aggregation, VM Instances inventory의 gated stopped-VM Start action, dedicated VM Instances / DRS Policies configuration, Network readiness selected-source comparison view, DRS Advisor identity/policy readiness evidence plus narrow approval-gated execution/post-check/reconciliation backend, DB-backed Operations/Jobs, job-derived Operations/Risks, Create VM supporting capability, Goal 8 local-only post-create readiness evidence recorder, 그리고 Settings account/session polish다. Admin Users는 local account operations와 session inventory/revocation을 포함하고, Account는 self password change를 제공한다.

DRS Advisor는 identity/fingerprint DB model, compact migration policy evidence,
policy audit substrate, read-only final pre-check, DB-backed operation lock
lookup/acquisition/release, config-lock evidence, approval packet/job substrate,
dedicated DRS live migration client, UPID/task evidence, verified post-check,
reconciliation events, read-only Reconcile preview, stored-UPID local
reconciliation follow-up, and approved VMID `140` live DRS smoke evidence가
구현/기록되어 있다. 남은 gap은 15분 average/peak metric substrate, backend-owned
blocker taxonomy display, broad execution UI, corrective reconciliation mutation,
background reconciliation automation, and deeper read-only advisor active
task/HA/quorum collection이다.

Manual per-VM DRS policy review/edit is currently the dedicated VM Instances / DRS Policies screen at `/instances/drs-policies`, not the Inventory table and not the `/drs` screen.

Create VM은 강한 보조 capability지만 MVP success line이 아니다. 현재 active 생성 경로는 Proxmox API native create다. 실제 생성은 `proxmox-create`가 approval과 final acknowledgement 뒤에 clone UPID polling, 필요한 boot disk resize, config, power-policy post-check, `observed_after` artifact와 DB request/VM record를 끝낸 뒤에만 완료로 기록한다. 기본 `stopped` 정책은 VM을 꺼진 상태로 끝내고, 선택 `boot_and_verify` 정책은 VM start, guest-agent IP discovery, cloud-init completion check까지 수행한다. Terraform plan/apply와 legacy `execute/archive` route surface는 제거됐고 old URL은 404다. SSH/Ansible/app bootstrap smoke는 deferred다.
