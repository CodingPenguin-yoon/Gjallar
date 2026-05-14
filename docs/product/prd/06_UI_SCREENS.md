# Gjallar UI Screens PRD

> 2026-05-13 Create VM profile/template/network update: DRS Advisor remains the
> current MVP source of truth. For Create VM UI details, use
> [`docs/engineering/architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md`](../../engineering/architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md).
> Older single-profile, `server-net`/NetworkProfile, template catalog, and
> first-power-on-in-create-flow text below is superseded where it conflicts.

## 0. 목적

사람이 보는 화면을 먼저 정의한다.
API와 구현은 이 화면을 만족해야 한다.

## 1. MVP 화면

현재 MVP 우선순위는 [`drs-advisor/`](drs-advisor/README.md)의 DRS Advisor다.
Create VM은 기존 보조 capability로 유지하되, 화면 책임의 중심은 Dashboard, DRS Advisor, Jobs/Runs, Risks/Alerts의 운영 control tower 흐름이다.

1. Dashboard
2. Infra Explorer: Nodes + VMs + VM Detail
3. DRS Advisor (`/placement`)
4. Jobs / Runs
5. Risks / Alerts
6. Create VM (secondary existing capability)

2차:

- Settings / Inventory
- Independent VM power actions
- Approval / Hermes Control
- Snapshots / Backups
- Template Management

3차:

- VM Console

## 2. Dashboard

목적: 전체 상태를 한눈에 보여준다.

표시:

- cluster health
- node별 행 단위 CPU/RAM/Disk/VM 상태
- node별 최근 15분 CPU/Memory average와 peak
- VM 수 / running 수
- red/yellow risk 개수
- 상위 1~3개 DRS 추천 요약
- 최근 jobs
- 최근 실패 smoke

DRS 추천 요약 표시:

- candidate VM
- source node -> target node
- expected source relief
- route status
- blocker/warning summary
- action: DRS Advisor 상세로 이동

Dashboard에서는 migration을 직접 실행하지 않는다.
Approve & Migrate는 DRS Advisor 상세 화면에서만 시작한다.

## 2.1 DRS Advisor

`/placement` route는 유지하되 상단 라벨은 `DRS Advisor`로 바꾼다.
상세 화면은 전체 추천 테이블과 실행 전 검토 흐름을 담당한다.

표시:

- Cluster load summary
- Node load table
- Full DRS recommendation table
- recommendation detail drawer
- VM identity/metadata status
- VM Mobility: Unclassified / Identity Mismatch / Allowed / Restricted / Blocked
- Route Status: Feasible / Warning / Blocked / Unknown
- Check Now result, 단 참고용
- final pre-check result
- Approve & Migrate action
- Recent DRS jobs

Approve & Migrate UX:

- Allowed VM만 실행 가능하다.
- Restricted/Blocked/Unclassified/Identity Mismatch는 실행 버튼 disabled다.
- Route Status Unknown은 final pre-check로 확정 전 migration 불가다.
- 실행 직전 final pre-check를 새로 수행한다.
- Check Now 또는 이전 pre-check 결과를 실행 허가에 재사용하지 않는다.
- final pre-check 통과 후 Confirm modal을 보여준다.
- warning이 있으면 명시적 acknowledgement를 요구한다.
- operation lock 획득 실패 시 migration job을 시작하지 않는다.

## 3. Infra Explorer

Nodes, VMs, VM Detail을 한 화면에서 본다.

구성:

```text
왼쪽: Nodes
가운데: VM list
오른쪽: VM detail drawer/panel
```

VM list 표시:

- name / VMID
- node
- status
- IP
- profile
- owner
- risk
- guest-agent

VM detail 표시:

- hardware
- disk/storage
- network
- template/profile
- observed state
- 최근 jobs
- 최근 preflight/smoke
- 가능한 action

VM Detail의 2차 전원 action:

- power on
- graceful shutdown
- reboot

Create VM target은 생성 성공 시 powered-off/stopped로 완료한다.
VM start와 기존 VM에 대한 독립 power on / graceful shutdown / reboot 버튼은 future Infra Explorer row action으로 Jobs/Runs audit를 붙여 노출한다.

전원 action UX:

- 일반 Confirm modal을 사용한다.
- modal에는 VM name, VMID, node, IP, 현재 power_state, 실행할 action을 표시한다.
- red risk가 있으면 action 버튼을 비활성화한다.
- yellow risk가 있으면 경고 체크박스를 요구한다.
- hard stop/reset 버튼은 MVP에서 표시하지 않는다.

## 4. Create VM

Profile 기반 wizard.

2026-05-13 target profile/template/network 정책:

- UI-visible enabled profile은 `general-vm`, `runtime-server`, `development-vm` 세 개다.
- Profile은 read-only creation preset이며 target node/storage/network/template/power/version을 bind하지 않는다.
- Template list는 Proxmox live inventory다. Profile requirement를 만족하지 못하는 template은 disabled reason과 함께 보이되 선택할 수 없다.
- Network는 target node 선택 후 해당 node의 active live bridge를 선택한다.
- Create VM target은 `network_id` 또는 `server-net`을 사용하지 않는다.
- static mode는 `static_ip`, `prefix`, `gateway`를 모두 입력해야 한다.
- DHCP mode는 허용하지만 later guest-agent/inventory discovery warning을 표시한다.
- Network tab policy/subnet/range는 future integration이며 Create VM source of truth가 아니다.

중요 UX:

- 추천 profile 먼저
- 고급 설정 접기
- preflight 결과를 실행 전 명확히 표시
- red면 실행 버튼 disabled
- plan diff 확인 후 승인
- 원터치/단계별 실행 선택

Review & Confirm 표시 항목:

1. 생성될 VM 이름
2. VMID
3. target node
4. storage
5. template
6. CPU/RAM/Disk
7. bridge / IP mode / static IP fields
8. Terraform state path
9. power policy: `stopped`
10. smoke timeout 요약
11. red/yellow risk summary
12. plan artifact link
13. Git commit 예정 diff 요약

승인 UX:

- VM 생성은 일반 Confirm 버튼을 사용한다.
- yellow risk가 있으면 경고 체크박스를 요구한다.
- red risk가 있으면 approve/execute 버튼을 비활성화한다.
- typed confirmation은 MVP VM 생성에는 쓰지 않고 삭제/rollback/destructive 작업에만 쓴다.

## 5. Jobs / Runs

표시:

- job id
- type: `drs_migration`, `vm_create` 등
- target VM
- actor/requested_by/approved_by
- status
- source node / target node for DRS migration
- Proxmox UPID
- operation lock status
- started/finished
- final pre-check summary
- artifact links
- retry 가능한 단계
- needs_reconciliation 상태와 Reconcile Now action

DRS migration job status:

- queued
- prechecking
- running
- success
- failed
- needs_reconciliation

## 6. Risks / Alerts

가장 중요한 화면 중 하나다.

표시:

- Identity Mismatch
- Unclassified VM
- metadata incomplete
- migration policy restricted/blocked
- operation lock active/stale
- VM not found/running/source mismatch
- target offline
- quorum unhealthy
- active conflicting task
- config lock
- passthrough blocker
- route unknown/blocked
- migration timeout
- IP 충돌
- storage 부족
- guest-agent 미응답
- stale observed state
- Terraform state issue
- credential issue
- template mismatch
- 오래된 snapshot/backup 경고는 2차

각 risk는 원인, 영향, 가능한 조치, 막힌 action을 보여준다.

생성 후 검증 실패 VM은 자동 삭제하지 않고 아래처럼 표시한다.

```text
생성은 됐지만 준비 실패
상태: created_but_not_ready
원인: smoke/cloud-init/SSH/guest-agent/Ansible 실패 중 해당 항목
Runtime Target: inactive
Cleanup: 후보로만 표시, 자동 삭제 없음
```

사용자 액션:

- smoke 재시도
- 상세 로그/아티팩트 보기
- cleanup 후보로 표시
- 실제 삭제는 2차 기능의 명시 승인 flow에서만 가능

## 7. Deferred: Settings / Inventory

첫 구현 MVP에서는 별도 설정 화면을 만들지 않는다.
아래 정보는 read-only inventory API와 Create VM/Review & Confirm 화면에서 필요한 만큼만 노출한다.

표시:

- Proxmox endpoint/credential 상태
- node/storage/live bridge inventory
- live Proxmox template 목록
- IaC repo 경로
- Terraform state 위치
- Network tab policy source 상태, 단 Create VM source of truth는 아님

## 8. 제외 화면

MVP에서는 앱 배포 화면, 앱 로그 화면, DB migration 화면을 만들지 않는다.
이들은 Gjallar 제품 정체성과 다르다.
