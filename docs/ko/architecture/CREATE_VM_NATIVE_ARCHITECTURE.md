# Create VM Native Architecture

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 Create VM native architecture](../../architecture/CREATE_VM_NATIVE_ARCHITECTURE.md), [Current Create VM snapshot](../../current/top-tabs/04-create-vm.md), [native create flow](../../architecture/create-vm/native-create-flow.md).

이 문서는 현재 구현된 Proxmox API native Create VM path를 설명합니다. Legacy executor route surface는 current active path가 아니며, active UI는 native preview/create를 사용합니다.

## Active direction

- Primary create path: Proxmox API native clone/resize-if-needed/config/post-check.
- Powered-off policy: create/config only. First power-on과 smoke는 deferred.
- Source of truth: Proxmox actual state. Post-check와 `observed_after` 없이는 성공을 주장하지 않습니다.
- Inventory boundary: [backend/app/proxmox/inventory.py](../../../backend/app/proxmox/inventory.py)는 read-only이고 mutation code는 [backend/app/proxmox/client.py](../../../backend/app/proxmox/client.py)에 분리되어 있습니다.

## Frontend flow

[frontend/src/components/CreateInstanceWizard.jsx](../../../frontend/src/components/CreateInstanceWizard.jsx)는 options를 로드하고 review/approval/create flow를 진행합니다.

[frontend/src/utils/createVmFlow.js](../../../frontend/src/utils/createVmFlow.js)의 주요 함수:

- `buildCreateVmInputFromConfig()`: form config를 payload input으로 변환.
- `loadCreateVmReviewModel()`: readiness, draft, preflight, plan 호출.
- `approveCreateVmReview()`: exact approval metadata 검증 호출.
- `previewCreateVmProxmox()`: optional non-mutating native preview 호출.
- `createVmWithProxmox()`: final acknowledgement 후 native create 호출.

## Backend endpoint flow

1. `create_vm_draft()`는 `_api_draft_from_payload()`와 `build_default_vm_draft()`를 호출하고 draft job progress를 기록합니다.
2. `preflight_vm_draft()`는 `run_preflight()`를 read-only inventory adapter로 실행합니다.
3. `plan_vm_draft()`는 `build_vm_create_plan()`으로 artifacts를 씁니다.
4. `approve_vm_draft()`는 `validate_approval_request()`로 exact metadata와 yellow acknowledgement를 검증합니다.
5. `preview_vm_draft_proxmox_create()`는 approval을 다시 검증하고 `build_proxmox_create_preview()`를 호출합니다.
6. `create_vm_draft_proxmox_native()`는 approval, red risk, acknowledgement gate를 통과한 뒤 `run_proxmox_create()`를 호출합니다.

## Proxmox operation order

| 순서 | 작업 | 성공 조건 |
|---:|---|---|
| 1 | template에서 full clone | clone endpoint가 UPID를 반환 |
| 2 | clone task polling | task `exitstatus=OK` |
| 3 | cloned config inspect | boot disk와 size를 안전하게 식별 |
| 4 | boot disk resize if needed | requested disk가 더 클 때만 resize 완료 |
| 5 | VM config apply | CPU/memory/agent/onboot/network/cloud-init 적용 |
| 6 | status/config post-check | target node에서 VM과 config 관찰 |
| 7 | observed artifact | `observed_after` artifact 작성 |

Config payload는 `cores`, `memory`, `agent=enabled=1`, `onboot=0`, `net0`, reviewed `ciuser`, optional transient `sshkeys`, `ipconfig0`를 포함합니다. Preview/result artifact는 `sshkeys`를 redact합니다.

## Success and failure

Success requires exact approval, no fresh red risk, clone task OK, disk resize unnecessary or completed, config call completed, target node existence, status `stopped`, and `observed_after_artifact`.

Failure/uncertain cases include approval mismatch, red risk, clone task failure, unknown cloned disk size, resize failure, config failure, VM missing, powered-on observed state, missing observed artifact. Uncertain post-mutation states are recorded as failed or `needs_reconciliation`.

## DRS caution

Create VM native runner is clone/config/create logic. It is not a DRS migration executor. DRS Advisor needs its own final pre-check, operation locks, live migration client, UPID tracking, post-check, and reconciliation.
