# 현재 구현 상태

기준 문서: [Current implemented state](../current/README.md), [top-tab snapshots](../current/top-tabs/README.md), [system overview](../architecture/system/overview.md). 이 문서는 한국어 설명용이며 source of truth가 아닙니다.

Gjallar는 현재 Proxmox 운영자가 클러스터 상태, VM 배치, network policy, job/artifact, risk를 확인하고, 승인 기반으로 powered-off VM을 생성할 수 있게 하는 Proxmox Operations & Risk Console입니다. DRS Advisor가 다음 MVP 목표지만, 현재 backend DRS 실행 시스템은 없습니다.

## 전체 구현 기준

- Active backend surface는 `/api/v1`입니다.
- Proxmox inventory는 read-only입니다. live Proxmox 연결이 없으면 fake read-only fallback을 사용할 수 있습니다.
- Proxmox actual state가 VM, node, task, storage, network의 source of truth입니다.
- Gjallar가 현재 저장하는 것은 Create VM intent manifest, network policy file, approval evidence, job status, artifact 같은 운영 evidence입니다.
- Terraform plan/apply route와 helper code는 active contract에서 제거되었습니다. 제거된 URL은 자연스럽게 404입니다.
- `/api/v1/drs/*` route는 현재 없습니다.

## 현재 상태: Dashboard

Dashboard는 read-only 운영 요약 화면입니다.

- 사용하는 API: `GET /api/v1/cluster/summary`, `nodes`, `vms`, `storage`, `networks`, `jobs`, `risks`.
- 보여주는 것: node online count, VM count/running count, storage summary, red risk count, active job count, node별 current CPU/Memory.
- 하지 않는 것: migration 실행, DRS final pre-check, 15분 average/peak 기반 DRS 판단.
- 일부 조회가 실패해도 가능한 inventory는 계속 표시하도록 구성되어 있습니다.

## 현재 상태: Infra Explorer

Infra Explorer는 read-only VM/node inventory와 VM detail evidence 화면입니다.

- 현재 frontend loader는 일반적으로 `GET /api/v1/nodes`와 `GET /api/v1/vms` list data를 사용합니다.
- backend에는 `GET /api/v1/vms/{vmid}` detail endpoint도 있지만, 현재 screen이 정상 경로에서 항상 per-VM detail을 fetch하는 구조는 아닙니다.
- VM/node 상태, node 배치, IP/guest-agent evidence, storage/network 관찰값을 확인하는 데 쓰입니다.
- destructive lifecycle control은 active surface가 아닙니다.

## 현재 상태: Networks

Networks는 live bridge inventory와 IaC-backed NetworkPolicy 편집 화면입니다.

- `GET /api/v1/networks`는 Proxmox bridge inventory를 read-only로 반환합니다.
- `GET /api/v1/networks/policy`는 live bridge와 IaC `manifests/networks/network-profiles.yaml` policy state를 합쳐 보여줍니다.
- `PUT /api/v1/networks/policy`는 policy file을 정규화해서 쓰고 local IaC Git commit을 시도할 수 있습니다.
- 이 기능은 Proxmox bridge를 생성, 삭제, 수정하지 않습니다.
- 현재 Create VM의 network source of truth는 NetworkPolicy나 `network_id`가 아니라 selected target node의 active live bridge인 `bridge_id`입니다.

## 현재 상태: Create VM

Create VM은 현재 가장 강한 supporting capability입니다. 목표는 live template에서 powered-off Proxmox VM을 만드는 operator-reviewed workflow입니다.

- active flow: draft -> preflight -> plan -> approve -> manifest commit by `execute` plus non-mutating `proxmox-preview` -> `proxmox-create`.
- `POST /api/v1/vm-create/{draft_id}/execute`는 이름과 달리 VM을 만들지 않습니다. approved `VMInstance` manifest를 쓰고 commit하는 단계입니다.
- 실제 Proxmox mutation은 `POST /api/v1/vm-create/{draft_id}/proxmox-create`에서만 일어납니다.
- 성공 기준은 clone, 필요한 boot disk resize, config, post-check, `observed_after` artifact, Proxmox status `stopped`, manifest `applied`입니다.
- first power-on, cloud-init smoke, guest-agent IP discovery, SSH smoke, Ansible verification은 현재 성공 범위에 포함되지 않습니다.

## 현재 상태: Placement / DRS Advisor

현재 `/placement`는 read-only Placement screen입니다.

- Placement 전용 backend endpoint는 없습니다.
- 화면은 `cluster/summary`, `nodes`, `vms`, `storage`, `networks`, `risks`, `jobs`를 조합해서 frontend에서 recommendation seed를 계산합니다.
- execution은 `available: false`, `readOnly: true`, `allowedActions: []`입니다.
- `/api/v1/drs/*`, backend recommendation authority, identity/fingerprint DB, final pre-check, Proxmox live migration, UPID tracking, operation lock, reconciliation은 구현되어 있지 않습니다.

## 현재 상태: Jobs / Runs

Jobs/Runs는 file-backed job status와 artifact metadata를 보여주는 read-only 화면입니다.

- 사용하는 API: `GET /api/v1/jobs`, `GET /api/v1/jobs/{job_id}`, `GET /api/v1/jobs/{job_id}/artifacts`.
- backend는 `GJALLAR_RUNS_ROOT/<job_id>/job_status.json`을 latest-state persistence로 사용합니다.
- artifact API는 file content를 stream하지 않고 metadata를 반환합니다.
- 현재 주된 job source는 Create VM 단계입니다. DRS migration job model은 아직 1급 구현이 아닙니다.

## 현재 상태: Risks / Alerts

Risks/Alerts는 job-derived risk list입니다.

- 사용하는 API: `GET /api/v1/risks`.
- backend는 job status의 `risks` 배열을 펼쳐 risk row를 만듭니다.
- 현재 risk는 Create VM preflight/plan에서 나온 red/yellow risk가 중심입니다.
- DRS identity mismatch, route unknown, operation lock, migration timeout, needs reconciliation 같은 blocker taxonomy는 아직 구현되어 있지 않습니다.

## 현재 구현이 아닌 항목

- DRS Advisor backend route와 migration execution은 없습니다.
- Terraform executor와 Terraform-named state metadata는 active contract에 없습니다.
- Gjallar DB-backed VM identity/fingerprint/profile seed/DRS policy table은 현재 없습니다.
- Create VM 성공에 first boot, smoke, SSH, Ansible 검증은 포함되지 않습니다.
- Gjallar가 Proxmox bridge나 VM lifecycle destructive action을 직접 제공하는 current UI는 없습니다.
