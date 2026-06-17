# VM Instances / Create VM

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 Create VM snapshot](../../../current/top-tabs/04-create-vm.md), [영어 Create VM architecture](../../../architecture/create-vm/overview.md), [VM provisioning contract](../../../architecture/VM_PROVISIONING_CONTRACT.md), [native architecture](../../../architecture/CREATE_VM_NATIVE_ARCHITECTURE.md).

Create VM은 canonical `/instances/create` route의 operator-reviewed VM 생성 flow이며 legacy `/create` deep link도 같은 화면을 렌더링합니다. DRS Advisor의 next MVP success line은 아니지만, approval, artifact, job progress, native Proxmox mutation gate를 제공하는 supporting capability입니다.

## 사용하는 API와 frontend 함수

| 단계 | Endpoint | Frontend 함수 |
|---|---|---|
| Option load | `GET /api/v1/nodes`, `templates`, `storage`, `networks`, `profiles` | [CreateInstanceWizard.jsx](../../../../frontend/src/components/CreateInstanceWizard.jsx) |
| Draft | `POST /api/v1/vm-create/drafts` | `createVmDraft()` via [apiV1.js](../../../../frontend/src/services/apiV1.js) |
| Preflight | `POST /api/v1/vm-create/{draft_id}/preflight` | `preflightVmDraft()` |
| Plan | `POST /api/v1/vm-create/{draft_id}/plan` | `planVmDraft()` |
| Approve | `POST /api/v1/vm-create/{draft_id}/approve` | `approveVmDraft()` |
| Native create | `POST /api/v1/vm-create/{draft_id}/proxmox-create` | `createVmDraftProxmox()` |

Legacy `execute/archive` manifest commit route는 active API에서 제거됐습니다.

## backend 구현 함수

Router handlers는 [backend/app/api/v1/router.py](../../../../backend/app/api/v1/router.py)에 있습니다. 핵심 primary UI 흐름은 payload normalization, `build_default_vm_draft()`, `run_preflight()`, `build_vm_create_plan()`, `validate_approval_request()`, final acknowledgement, `build_proxmox_create_preview()`, `run_proxmox_create()` 순서입니다. 별도 manifest commit/save-request 버튼은 current primary UI에서 제거됐습니다.

자세한 함수별 설명은 [architecture/create-vm/native-create-flow.md](../../architecture/create-vm/native-create-flow.md)를 봅니다.

## 현재 성공 기준

Native create success는 clone task OK, 필요한 disk resize 완료 또는 불필요, config 적용, target node에서 VM 존재, `observed_after` artifact 존재, job `completed`입니다. 기본 `stopped` 정책은 Proxmox status가 `stopped`여야 하고, 선택 `boot_and_verify` 정책은 VM start 후 guest-agent IP와 `cloud-init status --wait` 완료까지 확인해야 합니다.

성공에 포함하지 않는 것: SSH, Ansible, app deploy, DRS identity registration. 단, `boot_and_verify`를 선택한 요청은 first power-on, guest-agent IP discovery, cloud-init completion을 포함합니다.

## Target gap

Profiles는 현재 DB seed 기반 read-only preset입니다. Native create가 `needs_reconciliation`을 남길 수 있지만 background reconciliation worker는 아직 없습니다. DRS migration은 별도 final pre-check와 operation lock이 필요합니다.
