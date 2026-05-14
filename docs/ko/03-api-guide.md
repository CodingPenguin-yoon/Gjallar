# API 안내

기준 문서: [Current API V1](../architecture/api/current-api-v1.md). 관련 현재 상태: [Current implemented state](../current/README.md). 이 문서는 한국어 endpoint 설명용이며 source of truth가 아닙니다.

현재 active API prefix는 `/api/v1`입니다. 성공 응답은 보통 `ok`, `data`, optional `meta` 형태의 envelope를 사용합니다. Error response는 아직 완전히 정규화되어 있지 않으며 FastAPI `HTTPException`의 `detail` object가 올 수 있습니다. Frontend client는 성공 envelope와 HTTP error detail을 모두 처리합니다.

## 인벤토리와 요약 API

### `GET /api/v1/cluster/summary`

- 하는 일: cluster count와 high-level mode를 요약합니다.
- 데이터 출처: Proxmox inventory adapter snapshot.
- 변경 여부: read-only, side effect 없음.
- Frontend use: Dashboard와 Placement에서 cluster id, node/vm/template count, mode 표시.
- 주의: `risk_level`은 현재 `unknown` 수준입니다. DRS 판단에 필요한 15분 average/peak나 final blocker를 제공하지 않습니다.

### `GET /api/v1/nodes`

- 하는 일: node inventory를 반환합니다.
- 데이터 출처: Proxmox inventory adapter.
- 변경 여부: read-only.
- Frontend use: Dashboard, Infra Explorer, Create VM options, Placement.
- 주의: node row에는 status, CPU/Memory usage, storage, network evidence가 포함됩니다. 현재 값은 실행 gate가 아니라 화면 evidence입니다.

### `GET /api/v1/vms`

- 하는 일: template을 제외한 VM inventory list를 반환합니다.
- 데이터 출처: Proxmox inventory adapter.
- 변경 여부: read-only.
- Frontend use: Dashboard, Infra Explorer, Placement.
- 주의: disks, tags, IP evidence, guest-agent evidence가 가능한 범위에서 포함됩니다. DRS identity/fingerprint DB match는 아직 없습니다.

### `GET /api/v1/vms/{vmid}`

- 하는 일: VMID 하나에 대한 read-only detail을 조회합니다.
- 데이터 출처: inventory adapter lookup by VMID.
- 변경 여부: read-only.
- Frontend use: API client helper가 있습니다. 현재 Infra Explorer screen은 보통 `/nodes`와 `/vms` list data를 사용하며, 정상 화면 load가 항상 per-VM detail을 fetch한다고 보면 안 됩니다.
- 주의: VMID를 찾지 못하면 404입니다. VMID는 identity가 아니라 locator입니다.

## VM 생성 옵션 API: Create VM

### `GET /api/v1/profiles`

- 하는 일: Create VM profile choices를 반환합니다.
- 데이터 출처: transitional `static_seed` profiles.
- 변경 여부: read-only.
- Frontend use: Create VM profile selector와 hardware defaults.
- 주의: 현재 active profile은 `general-vm`, `runtime-server`, `development-vm` 세 개입니다. DB-seeded profile source는 future work입니다.

### `GET /api/v1/vm-create/readiness`

- 하는 일: Create VM에 필요한 IaC readiness를 확인합니다.
- 데이터 출처: `run_iac_readiness()`.
- 변경 여부: read-only.
- Frontend use: Create VM review model을 만들 때 readiness evidence로 사용합니다.
- 주의: shared root, IaC root, write allowlist, Git repo 상태를 봅니다. Proxmox mutation은 하지 않습니다.

### `GET /api/v1/templates`

- 하는 일: Proxmox template inventory를 반환합니다.
- 데이터 출처: Proxmox inventory adapter.
- 변경 여부: read-only.
- Frontend use: Create VM template selector.
- 주의: active template selection source입니다. builtin template defaults가 active source가 아닙니다. cloud-init 또는 qemu guest-agent evidence가 없으면 current initial profiles에서는 ready로 보지 않습니다.

### `GET /api/v1/storage`

- 하는 일: storage candidates를 반환합니다.
- 데이터 출처: Proxmox inventory adapter.
- 변경 여부: read-only.
- Frontend use: Dashboard, Create VM options, Placement.
- 주의: Create VM 화면에서는 selected node, `images` content, free capacity 기준으로 필터링합니다.

### `GET /api/v1/networks`

- 하는 일: bridge inventory를 반환합니다.
- 데이터 출처: Proxmox inventory adapter.
- 변경 여부: read-only.
- Frontend use: Dashboard, Create VM options, Placement.
- 주의: Create VM은 selected target node의 active bridge를 사용합니다. NetworkPolicy나 `network_id`가 current Create VM source of truth가 아닙니다.

## 네트워크 정책 API: Network Policy

### `GET /api/v1/networks/policy`

- 하는 일: live bridge inventory와 IaC network policy state를 합쳐 보여줍니다.
- 데이터 출처: Proxmox inventory adapter와 `manifests/networks/network-profiles.yaml`.
- 변경 여부: read-only.
- Frontend use: Networks tab.
- 주의: registered/unregistered bridge, missing policy bridge, static IP range 같은 policy view를 보여줍니다. Create VM bridge 선택의 source of truth가 아닙니다.

### `PUT /api/v1/networks/policy`

- 하는 일: normalized network policy를 저장합니다.
- 데이터 출처: request payload와 IaC root.
- 변경 여부: IaC policy file을 쓰고 local IaC Git commit을 시도할 수 있습니다.
- Frontend use: Networks tab policy editor.
- 주의: path는 IaC root 아래로 제한됩니다. Proxmox bridge config를 생성, 삭제, 수정하지 않습니다.

## 작업과 위험 API: Jobs/Risks

### `GET /api/v1/jobs`

- 하는 일: job summaries를 반환합니다.
- 데이터 출처: `GJALLAR_RUNS_ROOT/*/job_status.json`.
- 변경 여부: read-only.
- Frontend use: Dashboard, Placement, Jobs/Runs.
- 주의: runs root glob 실패 시 `[]`로 fail-open합니다. NFS-backed history가 불안정해도 read-only 화면을 유지하려는 목적입니다.

### `GET /api/v1/jobs/{job_id}`

- 하는 일: job 하나의 summary/detail을 반환합니다.
- 데이터 출처: 해당 job status file.
- 변경 여부: read-only.
- Frontend use: Jobs/Runs selected detail.
- 주의: 없으면 404입니다. 현재 status file은 latest-state record이지 append-only audit log가 아닙니다.

### `GET /api/v1/jobs/{job_id}/artifacts`

- 하는 일: job 하나의 artifact metadata를 반환합니다.
- 데이터 출처: job status file의 artifact list.
- 변경 여부: read-only.
- Frontend use: Jobs/Runs selected detail artifact list.
- 주의: artifact file contents를 반환하지 않습니다. id, type, path, checksum, created time 같은 metadata 확인용입니다.

### `GET /api/v1/risks`

- 하는 일: job status에 기록된 risk들을 risk summary row로 펼칩니다.
- 데이터 출처: job status file의 `risks` arrays.
- 변경 여부: read-only.
- Frontend use: Dashboard, Placement, Risks/Alerts.
- 주의: 현재 risk는 job-derived입니다. standalone risk engine이나 DRS blocker engine이 아닙니다.

## VM 생성 흐름 API: Create VM

### `POST /api/v1/vm-create/drafts`

- 하는 일: non-mutating Create VM draft를 만듭니다.
- 데이터 출처: request payload, static profiles, inventory VMID suggestion.
- 변경 여부: draft job status를 기록합니다. Proxmox mutation은 없습니다.
- Frontend use: Create VM review model의 첫 단계.
- 주의: incoming `network_id`/`networkId`는 transition compatibility 때문에 무시됩니다. nested `access` alias를 받을 수 있지만 raw public key는 response에 반환하지 않습니다.

### `POST /api/v1/vm-create/{draft_id}/preflight`

- 하는 일: draft에 대한 non-destructive checks를 실행합니다.
- 데이터 출처: draft, read-only inventory, IaC readiness.
- 변경 여부: preflight job status와 risks를 기록합니다. Proxmox mutation은 없습니다.
- Frontend use: Create VM review model.
- 주의: red risk는 approval/create를 막습니다. yellow risk는 acknowledgement가 필요할 수 있습니다. SSH public key missing/malformed/private-key-looking 값과 password login true는 current profile에서 red-block됩니다.

### `POST /api/v1/vm-create/{draft_id}/plan`

- 하는 일: artifact-backed dry-run plan을 만듭니다.
- 데이터 출처: draft와 preflight result.
- 변경 여부: preflight report, plan, `VMInstance` manifest, planned diff, review summary artifact를 씁니다. Proxmox mutation은 없습니다.
- Frontend use: Create VM review 화면.
- 주의: plan/review artifact에는 access fingerprint/source, selected template evidence, selected bridge evidence가 포함됩니다. raw SSH public key는 저장하지 않습니다.

### `POST /api/v1/vm-create/{draft_id}/approve`

- 하는 일: review approval metadata를 검증합니다.
- 데이터 출처: rebuilt plan artifacts와 approval payload.
- 변경 여부: `approval.json`을 쓰거나 갱신할 수 있고 approval job status를 기록합니다.
- Frontend use: Create VM approval step.
- 주의: exact `plan_artifact_id`, exact `review_summary_checksum`, 필요한 경우 yellow acknowledgement가 맞아야 합니다. approval 자체는 manifest commit이나 Proxmox call이 아닙니다.

### `POST /api/v1/vm-create/{draft_id}/proxmox-preview`

- 하는 일: native create preview를 만듭니다.
- 데이터 출처: approved rebuilt plan.
- 변경 여부: approval revalidation 과정에서 `approval.json`이 갱신될 수 있고 preview artifact를 씁니다. Proxmox mutation은 없습니다.
- Frontend use: final confirmation 전에 clone/config/post-check payload를 보여주는 단계.
- 주의: approval-gated but non-mutating입니다. preview config는 `sshkeys`를 redact합니다.

### `POST /api/v1/vm-create/{draft_id}/proxmox-create`

- 하는 일: 현재 active live Proxmox VM creation path입니다.
- 데이터 출처: approved rebuilt plan, committed manifest, Proxmox mutation client.
- 변경 여부: approval revalidation과 job/artifact write 후 Proxmox clone/task/config/resize/post-check를 실행하고 manifest status를 갱신합니다.
- Frontend use: Create VM의 final mutation button.
- 주의: `manifest_commit_sha`, valid approval, fresh red risk 없음, `proxmox_mutation_acknowledged=true`가 필요합니다. 성공은 powered-off/stopped VM 생성입니다. first boot, smoke, SSH, Ansible verification은 포함되지 않습니다.

### `POST /api/v1/vm-create/{draft_id}/execute`

- 하는 일: approved `VMInstance` manifest를 commit합니다.
- 데이터 출처: approved rebuilt plan과 IaC root.
- 변경 여부: manifest를 쓰고 필요하면 commit합니다. job status는 pending/commit 단계로 기록됩니다.
- Frontend use: Create VM의 "save request" 단계.
- 주의: mode는 `gitops_commit_only`입니다. VM을 만들지 않고 Proxmox를 호출하지 않습니다. 실제 VM creation은 `proxmox-create`입니다.

### `POST /api/v1/vm-create/{draft_id}/archive`

- 하는 일: unapplied `VMInstance` manifest를 archive합니다.
- 데이터 출처: rebuilt plan과 IaC root.
- 변경 여부: manifest를 `manifests/archive/vms/`로 이동하고 commit합니다.
- Frontend use: current `apiV1.js`에서 primary screen call은 아닙니다.
- 주의: `archive_acknowledged=true`가 필요합니다. 이미 applied된 manifest는 거부합니다.

## 제거된 Terraform routes

현재 active API에는 Terraform plan/apply route가 없습니다.

- `terraform-plan`과 `terraform-apply` endpoint는 제거되었습니다.
- Terraform executor helper와 Terraform-named state metadata도 active draft/preflight/plan/review/API/frontend/artifact contract에서 제거되었습니다.
- old URL은 FastAPI route table에 없으므로 자연스럽게 404입니다.

## 현재 구현이 아닌 DRS target APIs

[Target DRS API candidates](../architecture/api/target-drs-api.md)는 future work 후보입니다. 현재는 다음이 모두 미구현입니다.

- `GET /api/v1/drs/summary`
- `GET /api/v1/drs/recommendations`
- `GET /api/v1/drs/recommendations/{recommendation_id}`
- `POST /api/v1/drs/recommendations/{recommendation_id}/check-now`
- `POST /api/v1/drs/recommendations/{recommendation_id}/precheck`
- `POST /api/v1/drs/recommendations/{recommendation_id}/approve-migrate`
- `GET /api/v1/drs/jobs/{job_id}`
- `POST /api/v1/drs/jobs/{job_id}/reconcile`
- DRS policy/lock APIs

현재 `/placement`는 기존 inventory/jobs/risks API를 조합하는 read-only frontend read model입니다. DRS execution authority가 아닙니다.
