# Gjallar UI / API Contract PRD

> Current MVP product source of truth is `drs-advisor/`. If this document conflicts with that folder, `drs-advisor/` wins.
> This document mixes currently implemented `/api/v1` contracts with target/deferred contracts. Sections marked target/deferred are not current implementation.
> Proxmox is the source of truth for actual VM/node/task/HA/storage state. Gjallar stores operational intent, policy, approvals, fingerprints, jobs, artifacts, audit, and reconciliation state.

## 0. 목적

MVP 화면을 만족하는 API 계약을 정의한다.
구현은 이 계약을 통과해야 한다.

## 1. 공통 규칙

Base path:

```text
/api/v1
```

공통 응답:

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "meta": {
    "request_id": "req_xxx",
    "collected_at": "2026-05-08T00:00:00Z",
    "stale": false
  }
}
```

공통 error:

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "RISK_RED_BLOCKED",
    "message": "IP conflict detected",
    "details": {}
  }
}
```

## 1.1 현재 구현 API와 DRS Advisor 목표 API

현재 구현:

- `/api/v1` response envelope
- read-only cluster/node/VM/template/storage/network inventory
- network policy read/write
- Create VM draft/preflight/plan/approve/execute/proxmox-preview/proxmox-create/archive
- Terraform plan/apply as optional/deprecated legacy Create VM executor routes
- read-only Jobs/Runs
- read-only Risks/Alerts

현재 구현 아님:

- `/api/v1/drs/*`
- DB-backed VM identity/fingerprint/metadata/policy
- DRS backend recommendation snapshots
- DRS Check Now
- authoritative final pre-check
- Approve & Migrate
- Proxmox live migration mutation
- UPID tracking
- operation locks
- timeout/reconciliation/Reconcile Now
- Jobs retry/cancel
- Risk acknowledge

DRS Advisor target은 Proxmox 공식 문서와 live cluster response로 migration endpoint, UPID shape, HA/storage/task evidence를 검증한 뒤 구현한다.
PBS/Veeam references are backup evidence or future integration context only.
DRS Advisor is not a VMware DRS replacement, VMware DRS compatible layer, or automatic DRS for Proxmox.

## 2. Dashboard API

```http
GET /cluster/summary
```

반환:

- cluster status
- node count
- VM count
- running/stopped count
- red/yellow risk count
- recent jobs

## 3. Nodes API

```http
GET /nodes
GET /nodes/{node_id}
```

Node fields:

- node_id
- status
- cpu
- memory
- storage
- vm_count
- risks

## 4. VMs API

```http
GET /vms
GET /vms/{vmid}
```

VM fields:

- vmid
- name
- node
- power_state
- ip
- guest_agent_state
- profile_id
- owner
- role
- risk_level
- last_job

## 5. Profiles / Templates / Networks API

```http
GET /profiles
GET /templates
GET /networks
GET /networks/policy
PUT /networks/policy
```

읽기 전용으로 시작한다.
Template 생성/수정은 MVP 제외다.

Target Create VM profile/template/network design은
[`../../engineering/architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md`](../../engineering/architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md)를 따른다.

Target `GET /profiles`는 Gjallar DB seed source of truth를 반환한다. 초기
UI에서는 read-only이며 profile create/edit/delete UI는 future다.

초기 seeded enabled profiles:

| Profile ID | Display name | Korean label | Enabled |
|---|---|---|---:|
| `general-vm` | General VM | 범용 VM | true |
| `runtime-server` | Runtime Server | 서비스 실행용 VM | true |
| `development-vm` | Development VM | 개발/테스트용 VM | true |

각 profile은 hardware default/min/max, template requirement
`require_cloud_init=true`, `require_qemu_guest_agent=true`, access
recommendation `default_user=yoon`, `require_ssh_key=true`,
`allow_password_login=false`, `allow_user_override=true`를 반환한다.

Profile은 target node, storage, `network_id`, bridge, static IP, template
VMID/name, power policy, profile version을 포함하지 않는다.

Target template source of truth는 Proxmox live inventory다. Gjallar template
catalog 또는 registration window는 target에 없다. UI는 live template을
보여주고, 선택 profile 요구사항을 만족하지 못하는 template은 disabled reason과 함께 비활성화한다.
Backend preflight는 같은 조건을 다시 검증하고 red-block한다.

`GET /networks`는 Proxmox에서 발견한 live vmbr inventory다.
`GET /networks/policy`는 live vmbr inventory와 공용 IaC의 `manifests/networks/network-profiles.yaml` 정책 파일을 합쳐 등록/미등록 상태를 반환한다.
`PUT /networks/policy`는 해당 정책 파일을 저장하고, IaC root가 Git checkout이면 local commit을 만든다.
정책 파일에는 vmbr의 display name, subnet, gateway, DNS, 고정 IP 범위 같은 Gjallar 의미 정보를 저장한다.
고정 IP 범위는 여러 구간을 표현할 수 있도록 `static_ip_ranges: [{start, end}]` 배열로 저장한다.

Current implementation gap: 현재 code는 아직 built-in/current profile 경로이며
`general-vm`만 create-enabled다. 현재 Create VM 경로는 target node 선택 후
active live bridge의 explicit `bridge_id`를 사용하고, incoming
`network_id`/`networkId`는 transition compatibility로 ignore한다. Static
mode는 `static_ip`, `prefix`, `gateway`를 요구한다. 위 내용 중 profile seed,
template requirement disable, access key red-block 등은 아직 target contract다.

## 6. Create VM API

```http
POST /vm-create/drafts
POST /vm-create/{draft_id}/preflight
POST /vm-create/{draft_id}/plan
POST /vm-create/{draft_id}/approve
POST /vm-create/{draft_id}/execute
POST /vm-create/{draft_id}/proxmox-preview
POST /vm-create/{draft_id}/proxmox-create
POST /vm-create/{draft_id}/terraform-plan        # legacy optional
POST /vm-create/{draft_id}/terraform-apply       # legacy optional
```

Draft request 핵심 필드:

```json
{
  "name": "gjallar-vm-20260508-a1b2",
  "profile_id": "runtime-server",
  "target_node_id": "yoonmanserver2",
  "storage_id": "local-lvm",
  "template": {
    "node_id": "yoonmanserver2",
    "vmid": 9000,
    "name": "ubuntu-template"
  },
  "network": {
    "bridge": "vmbr0",
    "ip_mode": "static",
    "static_ip": "192.168.2.150",
    "prefix": 24,
    "gateway": "192.168.2.1"
  },
  "hardware": {
    "cpu": 4,
    "memory_mb": 8192,
    "disk_gb": 100
  },
  "access": {
    "username": "yoon",
    "ssh_public_key": "ssh-ed25519 AAAA...",
    "password_login": false
  }
}
```

첫 구현 MVP의 draft request에는 Runtime Target 생성 옵션을 넣지 않는다.
Runtime Target 후보/ready API는 VM 생성 flow가 안정화된 뒤 별도 slice에서 붙인다.

MVP에서는 VMID를 draft request에서 직접 받지 않는다.
Gjallar는 plan/preflight 단계에서 Proxmox `nextid`로 `proxmox_vmid`를 resolved 하고, apply 직전 중복을 다시 확인한다.
`name`을 생략하면 `general-vm` profile은 `gjallar-vm-<YYYYMMDD>-<short_job_id>` 형식으로 추천한다.

Target draft request는 `network_id`를 받지 않는다. 사용자가 target node를
선택한 뒤 해당 node의 live active bridge를 선택한다.
`ip_mode`는 `dhcp`, `static` 둘 다 허용하지만 기본값은 `static`이다.
Static mode는 `static_ip`, `prefix`, `gateway`를 모두 요구한다. DHCP mode는
허용하지만 이후 guest-agent/inventory discovery warning을 반환한다.
`gateway`는 명시 입력값이며, backend/frontend/runner는 static IP에서 `.1`
gateway를 추론하지 않는다.

초기 seeded profile 공통 access 값은 `username=yoon`,
`require_ssh_key=true`, `password_login=false`, `allow_user_override=true`다.
기본 SSH public key는 environment-backed backend 설정에서 올 수 있다. key가 없으면 red block이다.
API와 artifact에는 private key나 password 값을 저장/반환하지 않는다.

Plan response에는 Review & Confirm payload가 포함되어야 한다.

```json
{
  "draft_id": "draft_xxx",
  "resolved_proxmox_vmid": 142,
  "review_confirm": {
    "vm_name": "gjallar-vm-20260508-a1b2",
    "vmid": 142,
    "target_node": "yoonmanserver3",
    "storage": "local-lvm",
    "profile": "runtime-server",
    "template": { "node_id": "yoonmanserver2", "vmid": 9000, "name": "ubuntu-template" },
    "hardware": { "cpu": 4, "memory_mb": 8192, "disk_gb": 100 },
    "access": { "username": "yoon", "ssh_key_present": true, "password_login": false },
    "network": { "bridge": "vmbr0", "ip_mode": "static", "static_ip": "192.168.2.150", "prefix": 24, "gateway": "192.168.2.1" },
    "terraform_state_path": "/mnt/hermes_data/IaC-state/gjallar/gjallar-vm-20260508-a1b2/terraform.tfstate",
    "first_power_on_included": false,
    "smoke_timeout_summary": {
      "cloud_init": "15m",
      "guest_agent": "5m",
      "ip_discovery": "5m",
      "ssh": "5m"
    },
    "risk_summary": { "red": [], "yellow": [] },
    "plan_artifact_id": "artifact_plan_xxx",
    "planned_git_diff_summary": ["manifests/vms/gjallar-vm-20260508-a1b2.yaml"]
  },
  "review_summary_checksum": "sha256:..."
}
```

Approve request:

```json
{
  "plan_artifact_id": "artifact_plan_xxx",
  "review_summary_checksum": "sha256:...",
  "yellow_risk_acknowledged": false
}
```

VM 생성 approve에는 typed confirmation을 요구하지 않는다.
yellow risk가 있으면 `yellow_risk_acknowledged=true`가 필요하다.
red risk가 있으면 approve/execute는 실패해야 한다.

현재 구현된 execute slice는 `gitops_commit_only`다.
승인된 plan의 `VMInstance` manifest를 `IaC/manifests/vms/<manifest_id>.yaml`에 쓰고 local Git commit을 만든 뒤 종료한다.
응답은 `terraform_apply_enabled=false`, `proxmox_mutation_enabled=false`를 명시해야 하며, native Proxmox create와 legacy Terraform apply 모두 실행하지 않는다.

현재 active 생성 slice는 Proxmox API native다.
`proxmox-preview`는 승인된 plan의 review checksum과 plan artifact id를 다시 검증한 뒤 clone/config/post-check payload와 artifact를 반환한다. Proxmox mutation을 하지 않으며 응답은 `proxmox_mutation_enabled=false`, `terraform_apply_enabled=false`를 유지한다.

`proxmox-create`는 실제 생성 endpoint다. 필수 gate:

- approval metadata 재검증
- red risk 없는 fresh preflight/plan
- `manifest_commit_sha`
- committed manifest verification
- `proxmox_mutation_acknowledged=true`

성공은 Proxmox actual state로만 판단한다. clone UPID task `OK`, requested `disk_gb` resize가 불필요하거나 완료됨, VM exists on target node, `/status/current.status=stopped`, `/config` read, `observed_after` artifact/fingerprint가 모두 필요하다. task failure, cloned disk size unknown, resize failure, VM missing, powered-on observed state는 failed 또는 `needs_reconciliation`으로 기록하고 manifest `applied`가 아니다.

Terraform slice는 optional/deprecated legacy executor다. active UI는 `terraform-plan`/`terraform-apply`를 호출하지 않는다.

Current implementation gap: target payload의 `template` object, live bridge
network object, static `prefix`/`gateway`, DB seeded profiles, and three enabled
profile choices are not all current code yet. 현재 code still uses built-in
profiles, only `general-vm` enabled, and `network_id`/`server-net` until the
implementation update lands.

## 7. Jobs API

Current implemented:

```http
GET /jobs
GET /jobs/{job_id}
GET /jobs/{job_id}/artifacts
```

Target/deferred, not current implementation:

```http
POST /jobs/{job_id}/retry
POST /jobs/{job_id}/cancel
```

Retry는 허용된 단계만 가능하다.

## 8. Actions API — deferred after first create MVP

```http
POST /vms/{vmid}/actions/power-on
POST /vms/{vmid}/actions/shutdown
POST /vms/{vmid}/actions/reboot
```

현재 powered-off create slice에서는 VM 생성 apply가 first power on을 포함하지 않는다.
first power on + smoke는 apply/config 성공 뒤 별도 create-readiness slice로 제공한다.
기존 VM 대상 graceful power action은 `general-vm` 생성과 smoke가 안정화된 뒤 다음 slice로 제공한다.
`hard-stop`, `reset`, `kill` action endpoint는 만들지 않는다.

각 action은 safety policy를 통과해야 한다.
red risk가 있으면 실패해야 하며, yellow risk가 있으면 확인 체크가 필요하다.

Power action request:

```json
{
  "confirm": true,
  "yellow_risk_acknowledged": false,
  "expected_current_power_state": "running"
}
```

Power action confirm 화면에는 VM name, VMID, node, IP, current power_state, requested action을 표시해야 한다.

## 9. Risks API

Current implemented:

```http
GET /risks
GET /risks/{risk_id}
```

Target/deferred, not current implementation:

```http
POST /risks/{risk_id}/acknowledge
```

acknowledge는 표시 억제일 뿐 red action unblock이 아니다.

## 10. Runtime Target API — deferred after first create MVP

```http
GET /runtime-targets
GET /runtime-targets/{target_id}/readiness
```

이 API는 첫 구현 MVP 완료 기준에 포함하지 않는다.
Runtime Target slice에서 붙일 때도 read-only다.
외부 시스템이 VM readiness/risk를 확인할 수 있게 하지만, Gjallar action을 우회하지 않는다.
Runtime Target slice에서는 Runtime Target을 `candidate`, `candidate_ready`, `blocked` 상태로만 반환한다.
`active=true` 확정은 2차 기능이며, MVP 외부 소비자는 이 값을 배포 허가로 해석하면 안 된다.

Heimdall 연계는 MVP에서 read-only 조회까지만 허용한다.
Gjallar API는 Heimdall deploy target registry에 직접 등록/수정/삭제하는 endpoint를 제공하지 않는다.

## 11. 금지 API

MVP에서 만들지 않는다.

```text
POST /apps/deploy
POST /apps/restart
GET /apps/logs
POST /db/migrate
POST /proxmox/raw-shell
POST /vms/{vmid}/actions/hard-stop
POST /vms/{vmid}/actions/reset
```

## 12. DRS Advisor API — target, not current implementation

Current MVP product source of truth is `drs-advisor/`.
아래 API는 후보 계약이며, 현재 backend에는 없다.

Read model:

```http
GET /api/v1/drs/summary
GET /api/v1/drs/recommendations
GET /api/v1/drs/recommendations/{recommendation_id}
POST /api/v1/drs/recommendations/{recommendation_id}/check
```

Execution and reconciliation:

```http
POST /api/v1/drs/recommendations/{recommendation_id}/approve-migrate
POST /api/v1/drs/jobs/{job_id}/confirm
POST /api/v1/drs/jobs/{job_id}/reconcile
```

Target response concepts:

- recommendation id, VM locator, source node, target node
- identity status and fingerprint assertion summary
- metadata completeness and migration policy
- VM Mobility: Unclassified, Identity Mismatch, Allowed, Restricted, Blocked
- Route Status: Feasible, Warning, Blocked, Unknown
- CPU/Memory recent 15m average and peak evidence
- blockers and warnings
- generated_at and stale status
- action availability

Execution rules:

- Check Now is operator reference only and cannot authorize execution.
- Approve & Migrate always rebuilds current Proxmox state and runs final pre-check.
- Only Allowed VM with confirmed identity, complete metadata, policy `allowed`, no blocker, and route Feasible/Warning can proceed.
- Unknown route blocks migration.
- Warnings require explicit acknowledgement in the confirm modal.
- Operation lock must be acquired before calling Proxmox migration.
- Proxmox migration UPID must be stored and tracked.
- Success requires post-check: target node running state plus fingerprint match.
- Timeout or ambiguous state becomes `needs_reconciliation`; Reconcile Now uses Proxmox current state.
