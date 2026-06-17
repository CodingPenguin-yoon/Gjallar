# Flow: Create VM Review To Native Create

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 Create VM review flow](../../../architecture/flows/create-vm-review-to-create.md), [Current Create VM snapshot](../../../current/top-tabs/04-create-vm.md), [Jobs/Runs snapshot](../../../current/top-tabs/06-jobs-runs.md).

이 문서는 options load부터 native `proxmox-create`까지 현재 구현된 flow를 단계별로 설명합니다.

## Actors and modules

| Layer | Module |
|---|---|
| UI | [CreateInstanceWizard.jsx](../../../../frontend/src/components/CreateInstanceWizard.jsx) |
| Frontend helpers | [createVmFlow.js](../../../../frontend/src/utils/createVmFlow.js) |
| API client | [apiV1.js](../../../../frontend/src/services/apiV1.js) |
| Backend router | [router.py](../../../../backend/app/api/v1/router.py) |
| Backend Create VM | [backend/app/vm_create](../../../../backend/app/vm_create) |
| Proxmox mutation | [client.py](../../../../backend/app/proxmox/client.py), [proxmox_runner.py](../../../../backend/app/vm_create/proxmox_runner.py) |
| Jobs/artifacts | [backend/app/jobs](../../../../backend/app/jobs) |

## Step-by-step

| Step | Frontend action | Backend action | Artifact/job |
|---:|---|---|---|
| 1 | Component mounts and loads nodes/templates/storage/networks/profiles | read-only API calls | none |
| 2 | UI normalizes options | filters storage/bridge/template by selected node/profile | none |
| 3 | Operator edits profile/hardware/node/template/storage/bridge/IP/access | no backend call | none |
| 4 | Operator clicks review | `loadCreateVmReviewModel()` builds payload | none yet |
| 5 | Draft | `POST /drafts` builds draft and suggested VMID | job stage `draft` |
| 6 | Preflight | `POST /preflight` runs read-only checks | job stage `preflight`, risks |
| 7 | Plan | `POST /plan` builds artifacts | `preflight_report`, `plan`, `vm_instance_manifest`, `planned_git_diff`, `review_summary` |
| 8 | Review UI | displays risk summary and artifact metadata | no new state |
| 9 | Approve | `POST /approve` validates exact metadata | approval job state |
| 10 | Preview | `POST /proxmox-preview` builds native preview | `proxmox_create_preview` |
| 11 | Final acknowledgement | UI requires checkbox | no backend call |
| 12 | Native create | `POST /proxmox-create` with ack | job stage `create` |
| 13 | Proxmox runner | clone, poll UPID, resize if needed, config, post-check | `observed_after` |
| 14 | Terminal state | job/request/VM records updated | completed, failed, or `needs_reconciliation` |

## Payload and approval boundary

Payload includes compatibility `operator_id`, `job_id`, `profile_id`,
`target_node_id`, `storage_id`, `bridge_id`, explicit static fields,
`template_id`, `template_vmid`, `template_node_id`, hardware overrides, access
fields. Current UI derives `operator_id` from the authenticated session user,
and trusted actor evidence comes from session fields, not payload
`operator_id`. Incoming `network_id`/`networkId` is not the source of truth.

Approval packet includes `plan_artifact_id`, `review_summary_checksum`, `yellow_risk_acknowledged`. Native create additionally requires `proxmox_mutation_acknowledged`.

## Output boundary

`drafts`, `preflight`, `plan`, `approve`, and `proxmox-preview` do not mutate Proxmox. `proxmox-create` is the only current active VM creation path.
