# VM 생성: Create VM

기준 문서: [Create VM architecture](../architecture/create-vm/overview.md), [native create flow](../architecture/create-vm/native-create-flow.md), [Create VM provisioning contract](../architecture/VM_PROVISIONING_CONTRACT.md), [profile/template/network design](../architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md). 이 문서는 한국어 설명용이며 source of truth가 아닙니다.

Create VM은 live Proxmox template에서 powered-off VM을 만들기 위한 operator-reviewed workflow입니다. DRS Advisor MVP의 success line은 아니지만, approval, artifact, job progress, Proxmox mutation acknowledgement 같은 substrate를 제공합니다.

## 현재 흐름

```text
load options
-> draft
-> preflight
-> plan artifacts + review
-> approve
-> execute manifest commit
-> optional proxmox-preview
-> proxmox-create
-> Jobs/Runs에서 progress 확인
```

중요한 구분은 `execute`, `proxmox-preview`, `proxmox-create`입니다. `execute`는 manifest commit only이고, `proxmox-preview`는 approval-gated but non-mutating preview입니다. 실제 Proxmox VM 생성은 `proxmox-create`에서만 일어납니다. Current UI에서는 approval 후 preview와 manifest commit을 각각 실행할 수 있지만, live create에는 commit SHA가 필요합니다.

## 옵션 로드

Frontend는 Create VM 화면이 열리면 다음 option API를 읽습니다.

- `GET /api/v1/nodes`
- `GET /api/v1/templates`
- `GET /api/v1/storage`
- `GET /api/v1/networks`
- `GET /api/v1/profiles`

UI는 selected node에 맞는 storage와 bridge를 필터링하고, selected profile requirements에 맞지 않는 template을 disabled로 보여줍니다. UI disabled state는 안내일 뿐이며 backend preflight가 authoritative gate입니다.

## 프로필 동작: Profile

현재 profile source는 transitional `static_seed`입니다. DB seed는 future work입니다.

현재 active profile은 세 개입니다.

| Profile | 목적 | Default hardware | Limits 요약 | Template requirements |
|---|---|---|---|---|
| `general-vm` | 범용 VM | 2 CPU, 4096 MB, 50 GB | CPU 1-8, memory 1024-32768, disk 50-500 | cloud-init, qemu guest agent required |
| `runtime-server` | 서비스 실행용 VM | 4 CPU, 8192 MB, 100 GB | CPU 2-16, memory 4096-65536, disk 80-1000 | cloud-init, qemu guest agent required |
| `development-vm` | 개발/테스트용 VM | 2 CPU, 4096 MB, 50 GB | CPU 1-12, memory 2048-32768, disk 50-500 | cloud-init, qemu guest agent required |

Profile은 target node, storage, bridge, static IP, template, power policy를 포함하지 않습니다. Profile 변경 시 CPU/RAM/Disk는 새 profile default로 reset되고, operator가 min/max 안에서 수정할 수 있습니다.

## 템플릿 동작: Template

- Template source of truth는 `GET /api/v1/templates`의 Proxmox live/fake inventory입니다.
- Gjallar template catalog나 registration window는 active selection path에 없습니다.
- 모든 initial profile은 cloud-init과 qemu guest-agent capable template을 요구합니다.
- live Proxmox inventory에서 `agent` config가 missing/unknown이면 guest-agent-ready로 보지 않습니다.
- selected template disk가 requested disk보다 크면 preflight가 red risk로 막습니다.

## 네트워크 동작: Network

현재 Create VM network source of truth는 selected target node의 active live bridge입니다.

- UI는 target node를 먼저 선택하고 그 node의 active bridge를 고릅니다.
- backend는 explicit `bridge_id`가 target node에 있고 active인지 확인합니다.
- incoming `network_id`/`networkId`는 transition compatibility로 무시되고 active draft/plan/review/manifest/job output에 echo되지 않습니다.
- NetworkPolicy, `server-net`, static range membership은 current Create VM red gate가 아닙니다.

Static mode에서는 `static_ip`, `prefix`, `gateway`가 모두 필요합니다. Native create는 `static_ip`에서 `.1` gateway나 `/24` prefix를 추론하지 않고 operator input을 그대로 사용합니다. DHCP mode는 허용되지만 이후 guest-agent 또는 inventory discovery가 필요하다는 warning 성격을 갖습니다.

## 접근 설정과 SSH: Access

Access section은 현재 구현되어 있습니다.

- operator는 cloud-init username과 SSH public key를 입력할 수 있습니다.
- backend env/file default key fallback도 사용할 수 있습니다.
- current profiles는 SSH public key를 요구합니다.
- missing, malformed, private-key-looking SSH input은 red preflight입니다.
- password login은 fixed disabled입니다.
- raw public key는 Proxmox `sshkeys` config call에 transient하게만 사용됩니다.
- API response, plan/review/manifest/preview/observed artifact에는 key presence, source, fingerprint 같은 safe evidence만 기록됩니다.

## 초안 단계: Draft

`POST /api/v1/vm-create/drafts`는 request payload와 profile defaults/overrides를 사용해 server-side draft를 만듭니다.

- VMID는 inventory adapter의 suggestion을 사용합니다. normal UI flow에서 operator가 직접 VMID를 공급하지 않습니다.
- draft job status가 기록됩니다.
- live Proxmox mutation은 없습니다.

## 사전 점검 단계: Preflight

`POST /api/v1/vm-create/{draft_id}/preflight`는 non-destructive checks입니다.

주요 check:

- profile 존재/활성 여부.
- CPU/RAM/Disk가 selected profile limits 안에 있는지.
- selected template이 존재하고 cloud-init/qemu guest-agent requirement를 만족하는지.
- requested disk가 template disk floor보다 작은지.
- target node online 여부.
- storage availability/capacity.
- selected bridge가 target node에서 active인지.
- VMID/name collision.
- static IP/prefix/gateway validity와 observed IP conflict.
- IaC root, Git checkout, write allowlist readiness.
- SSH key requirement와 password login disabled rule.

Red risk는 approval과 create를 막습니다. Yellow risk는 approval에서 acknowledgement가 필요할 수 있습니다.

## 계획과 review 단계: Plan

`POST /api/v1/vm-create/{draft_id}/plan`은 dry-run plan과 review artifacts를 만듭니다.

생성되는 주요 artifact:

- `preflight_report`
- `plan`
- `vm_instance_manifest`
- `planned_git_diff`
- `review_summary`

Plan/review에는 selected profile, profile limits, target node, storage, live template evidence, hardware, access safe evidence, bridge evidence, static network fields, risk summary, artifact ids/checksum이 포함됩니다. 생성되는 `VMInstance` manifest는 `desired_power_state: stopped`를 요청하고 `first_power_on_included=false`를 기록합니다.

## 승인 단계: Approval

`POST /api/v1/vm-create/{draft_id}/approve`는 operator가 본 review와 backend artifact가 정확히 일치하는지 검증합니다.

필요한 approval metadata:

- `plan_artifact_id`
- `review_summary_checksum`
- `yellow_risk_acknowledged` when needed

Approval은 validation-only입니다. 이 단계는 manifest를 commit하지 않고 Proxmox도 호출하지 않습니다. run directory가 있으면 `approval.json`을 쓰거나 갱신할 수 있습니다.

## 실행 단계: Execute, manifest commit only

`POST /api/v1/vm-create/{draft_id}/execute`는 approved plan의 `VMInstance` manifest를 IaC root 아래에 쓰고 commit합니다.

- 반환 mode는 `gitops_commit_only`입니다.
- job은 commit stage에서 pending 성격으로 기록됩니다.
- Proxmox를 호출하지 않습니다.
- VM을 생성하지 않습니다.

이 단계의 commit SHA는 이후 `proxmox-create`에서 manifest verification gate로 쓰입니다.

## 미리보기 단계: Proxmox preview

`POST /api/v1/vm-create/{draft_id}/proxmox-preview`는 approval-gated but non-mutating 단계입니다.

- plan과 approval을 다시 확인합니다.
- clone/config/post-check payload preview를 만듭니다.
- `proxmox_create_preview` artifact를 씁니다.
- `sshkeys`와 public key material은 redacted evidence로만 보여줍니다.
- Proxmox API mutation call은 하지 않습니다.

## 생성 단계: Proxmox create

`POST /api/v1/vm-create/{draft_id}/proxmox-create`가 현재 active live VM creation path입니다.

필수 gate:

- approval metadata가 정확해야 합니다.
- `manifest_commit_sha`가 있어야 합니다.
- commit에 expected manifest path가 포함되어야 합니다.
- `proxmox_mutation_acknowledged=true`가 필요합니다.
- mutation 직전에 fresh preflight/plan을 다시 만들고 red risk가 없어야 합니다.

Proxmox operation order:

1. template에서 full clone.
2. clone task UPID polling.
3. cloned config를 읽어 boot disk를 식별.
4. requested disk가 cloned boot disk보다 크면 resize.
5. CPU, memory, agent, onboot, net0, `ciuser`, optional transient `sshkeys`, `ipconfig0` config 적용.
6. `/status/current`와 `/config` post-check.
7. `observed_after` artifact 작성.

## 성공과 실패 경계

Success는 powered-off/stopped VM 생성입니다.

성공 조건:

- clone task exitstatus가 OK.
- 필요한 disk resize가 완료되었거나 불필요함.
- config call이 완료됨.
- VM이 target node에서 관찰됨.
- Proxmox status가 `stopped`.
- `observed_after` artifact가 있음.
- manifest status가 `applied`.
- job status가 completed.

성공에 포함되지 않는 것:

- first power-on.
- cloud-init completion check.
- guest-agent IP discovery after boot.
- SSH login.
- Ansible verification.
- app deployment.
- DRS identity registration.

Failure 또는 uncertain state:

- clone task failure는 failed로 기록합니다.
- cloned boot disk size unknown, resize failure, config failure after clone, VM missing, powered-on observed state는 `needs_reconciliation` 또는 failed 계열로 남기고 manifest를 `applied`로 표시하지 않습니다.
- 현재 background reconciliation service는 없습니다.

## 보관 단계: Archive

`POST /api/v1/vm-create/{draft_id}/archive`는 unapplied manifest를 archive합니다.

- `archive_acknowledged=true`가 필요합니다.
- manifest를 `manifests/archive/vms/`로 이동하고 commit합니다.
- 이미 applied된 manifest는 거부합니다.
- current frontend의 primary path는 아닙니다.

## 제거된 Terraform 경계

Terraform executor route surface는 active tree에서 제거되었습니다.

- `terraform-plan`과 `terraform-apply`는 current routes가 아닙니다.
- Terraform helper code와 Terraform-named state metadata는 active API/frontend/artifact contract에 없습니다.
- old URLs는 404입니다.
