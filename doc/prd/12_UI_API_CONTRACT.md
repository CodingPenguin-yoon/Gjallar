# Gjallar UI / API Contract PRD

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

`GET /networks`는 Proxmox에서 발견한 live vmbr inventory다.
`GET /networks/policy`는 live vmbr inventory와 공용 IaC의 `manifests/networks/network-profiles.yaml` 정책 파일을 합쳐 등록/미등록 상태를 반환한다.
`PUT /networks/policy`는 해당 정책 파일을 저장하고, IaC root가 Git checkout이면 local commit을 만든다.
정책 파일에는 vmbr의 display name, subnet, gateway, DNS, 고정 IP 범위 같은 Gjallar 의미 정보를 저장한다.
고정 IP 범위는 여러 구간을 표현할 수 있도록 `static_ip_ranges: [{start, end}]` 배열로 저장한다.

MVP `GET /profiles`는 기본적으로 실제 생성 가능한 `general-vm` 하나만 반환한다.
`runtime-server`, `dev-server`, `db-server`는 2차 profile 후보로 문서/스키마 방향에만 남기고 MVP 화면 선택지에는 노출하지 않는다.
만약 API가 future profile을 반환해야 한다면 `enabled=false`, `status=coming_soon`이어야 하며 create draft/plan/apply 대상이 될 수 없다.

## 6. Create VM API

```http
POST /vm-create/drafts
POST /vm-create/{draft_id}/preflight
POST /vm-create/{draft_id}/plan
POST /vm-create/{draft_id}/approve
POST /vm-create/{draft_id}/terraform-plan
POST /vm-create/{draft_id}/execute
```

Draft request 핵심 필드:

```json
{
  "name": "gjallar-vm-20260508-a1b2",
  "profile_id": "general-vm",
  "node_id": "yoonmanserver2",
  "template_id": "ubuntu-template",
  "network_id": "server-net",
  "ip_mode": "static",
  "ip": "192.168.2.150",
  "hardware_overrides": {
    "cpu": 2,
    "memory_mb": 4096,
    "disk_gb": 40
  },
  "access": {
    "cloud_init_user": "yoon",
    "ssh_key_source": "operator_default_public_key",
    "password_login": false
  }
}
```

첫 구현 MVP의 draft request에는 Runtime Target 생성 옵션을 넣지 않는다.
Runtime Target 후보/ready API는 VM 생성 flow가 안정화된 뒤 별도 slice에서 붙인다.

MVP에서는 VMID를 draft request에서 직접 받지 않는다.
Gjallar는 plan/preflight 단계에서 Proxmox `nextid`로 `proxmox_vmid`를 resolved 하고, apply 직전 중복을 다시 확인한다.
`name`을 생략하면 `general-vm` profile은 `gjallar-vm-<YYYYMMDD>-<short_job_id>` 형식으로 추천한다.

Bridge도 draft request에서 raw 값으로 직접 받지 않는다.
Gjallar는 `node_id`와 `network_id`를 기준으로 `NetworkProfile.node_bridges[node_id]`를 resolve 한다.
MVP NetworkProfile fixture는 `yoonmanserver2`, `yoonmanserver3` 두 target node를 모두 지원하고, 초기 bridge 후보는 두 노드 모두 `vmbr0`이다.
`ip_mode`는 `dhcp`, `static` 둘 다 허용하지만 기본값은 `static`이다.
`general-vm` 기본 access 값은 `cloud_init_user=yoon`, `ssh_key_source=operator_default_public_key`, `password_login=false`다.
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
    "template": "ubuntu-template",
    "hardware": { "cpu": 2, "memory_mb": 4096, "disk_gb": 40 },
    "network": { "bridge": "vmbr0", "ip": "192.168.2.150" },
    "terraform_state_path": "/mnt/hermes_data/IaC-state/gjallar/gjallar-vm-20260508-a1b2/terraform.tfstate",
    "first_power_on_included": true,
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
응답은 `terraform_apply_enabled=false`, `proxmox_mutation_enabled=false`를 명시해야 하며, Terraform apply와 Proxmox VM 생성은 아직 실행하지 않는다.

현재 구현된 Terraform slice는 `terraform_plan_prepare_only`다.
승인된 plan의 review checksum과 plan artifact id를 다시 검증한 뒤 temp job workspace에 `main.tf`, `backend.hcl`, `backend.tf`, `terraform.auto.tfvars.json`을 생성하고 `terraform init/plan` 명령 배열을 반환한다.
기본값으로는 `terraform plan`도 실행하지 않는다.
`run_terraform_plan=true`를 요청하려면 `terraform_plan_acknowledged=true`가 반드시 필요하며, 이 경우에도 응답은 `terraform_apply_enabled=false`, `proxmox_mutation_enabled=false`를 유지한다.

## 7. Jobs API

```http
GET /jobs
GET /jobs/{job_id}
GET /jobs/{job_id}/artifacts
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

첫 구현 MVP에서는 VM 생성 flow 안의 first power on만 필수다.
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

```http
GET /risks
GET /risks/{risk_id}
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
