# Native Create Flow

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 Native Create Flow](../../../architecture/create-vm/native-create-flow.md), [Create VM native architecture](../../../architecture/CREATE_VM_NATIVE_ARCHITECTURE.md), [Current Create VM snapshot](../../../current/top-tabs/04-create-vm.md).

이 문서는 현재 구현된 native Proxmox Create VM flow를 endpoint/function 순서로 설명합니다.

## Native preview

`POST /api/v1/vm-create/{draft_id}/proxmox-preview`는 approval-gated and non-mutating입니다.

1. Router가 payload에서 draft/preflight/plan을 다시 만듭니다.
2. `validate_approval_request()`가 exact `plan_artifact_id`, `review_summary_checksum`, yellow acknowledgement를 확인합니다.
3. `build_proxmox_create_preview()`가 clone/config/post-check payload를 만듭니다.
4. `proxmox_create_preview` artifact를 씁니다.
5. 응답은 Proxmox mutation이 enabled/running되지 않았음을 보여줍니다.

Preview는 `sshkeys`와 raw public key material을 redacted evidence로만 보여줍니다.

## Approval recheck

`POST /api/v1/vm-create/{draft_id}/proxmox-create`는 create 직전에 plan과 approval을 다시 검증합니다. 필요한 값:

- exact `plan_artifact_id`
- exact `review_summary_checksum`
- yellow risk acknowledgement when needed
- `proxmox_mutation_acknowledged=true`
- `manifest_commit_sha`
- fresh plan/preflight no red risk

Gate 실패 시 HTTP error를 반환하고 Proxmox live mutation을 호출하지 않습니다.

## Manifest commit verification

UI는 native create 전에 `POST /api/v1/vm-create/{draft_id}/execute`를 호출합니다. 이 endpoint는 `commit_plan_manifest()`만 호출하며 mode는 `gitops_commit_only`입니다.

Native create는 `verify_plan_manifest_commit(plan, manifest_commit_sha)`로 supplied commit이 expected manifest path를 포함하는지 검증합니다. 검증 후에만 manifest status를 `applying`으로 바꾸고 Proxmox mutation client를 호출합니다.

## Proxmox operation order

| Order | Operation | Backend helper | Success requirement |
|---:|---|---|---|
| 1 | Full clone from template | `clone_vm()` | UPID 반환 |
| 2 | Poll clone task | `wait_for_task()` | task stopped and `exitstatus=OK` |
| 3 | Inspect cloned config | `get_vm_config()` | boot disk와 size 식별 |
| 4 | Resize boot disk if needed | `resize_vm_disk()` | requested disk가 더 클 때 완료 |
| 5 | Apply VM config | `set_vm_config()` | CPU/memory/agent/onboot/net/cloud-init config 적용 |
| 6 | Read status | `get_vm_status()` | target node에서 VM 관찰 |
| 7 | Read config | `get_vm_config()` | fingerprint evidence 구성 |
| 8 | Write observed artifact | `write_json_artifact()` | `observed_after` 존재 |

## Config payload

`config_payload_from_plan()`은 `cores`, `memory`, `agent=enabled=1`, `onboot=0`, `net0=virtio,bridge=<bridge_id>`, reviewed `ciuser`, optional transient `sshkeys`, `ipconfig0`를 만듭니다.

Static mode는 explicit `static_ip`, `prefix`, `gateway`를 사용합니다. Current code는 `/24`나 `.1`을 추론하지 않습니다.

## Disk resize decision

Runner는 boot disk를 `scsi0`, boot order, first non-CDROM disk 순서로 찾습니다. Requested `disk_gb`가 observed cloned boot disk보다 클 때만 resize합니다. Same-size 또는 smaller request는 resize하지 않습니다.

Cloned boot disk size가 unknown이면 Gjallar가 reviewed disk request와 일치한다고 안전하게 말할 수 없으므로 `needs_reconciliation`입니다.

## Observed after and stopped success

`observed_after.json`은 operation identifiers, existence/power status, sanitized status/config evidence, fingerprint hash를 담습니다. Fingerprint는 `smbios1`, `vmgenid`, MAC addresses, disk volume IDs에서 만듭니다.

Current success는 Proxmox status `stopped`일 때만 성립합니다. First power-on, cloud-init completion, guest-agent discovery, SSH, Ansible verification은 current flow에 포함되지 않습니다.
