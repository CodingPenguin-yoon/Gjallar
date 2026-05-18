# Create VM Architecture

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 Create VM architecture](../../../architecture/create-vm/overview.md), [Current Create VM snapshot](../../../current/top-tabs/04-create-vm.md), [VM provisioning contract](../../../architecture/VM_PROVISIONING_CONTRACT.md).

Create VM은 `/create` route입니다. 목적은 운영자가 profile, template, node, storage, bridge, access, network fields, power policy를 검토한 뒤 Proxmox VM을 만드는 것입니다. 기본은 powered-off 생성이고, 선택 `boot_and_verify`는 부팅 후 IP/cloud-init까지 검증합니다.

## Current frontend modules

| Concern | 구현 |
|---|---|
| Route | `/create` |
| Component | [frontend/src/components/CreateInstanceWizard.jsx](../../../../frontend/src/components/CreateInstanceWizard.jsx) |
| Defaults | [frontend/src/utils/createVmDefaults.js](../../../../frontend/src/utils/createVmDefaults.js) |
| Flow helpers | [frontend/src/utils/createVmFlow.js](../../../../frontend/src/utils/createVmFlow.js) |
| API client | [frontend/src/services/apiV1.js](../../../../frontend/src/services/apiV1.js) |

Frontend는 options를 로드한 뒤 `loadCreateVmReviewModel()`로 readiness, draft, preflight, plan을 호출합니다. Approval 후에는 선택적으로 preview를 만들 수 있고, final acknowledgement 뒤 `createVmWithProxmox()`가 native create를 호출합니다.

## Current backend modules

| Module | 역할 |
|---|---|
| [backend/app/api/v1/router.py](../../../../backend/app/api/v1/router.py) | Route orchestration, approval gates, job status recording. |
| [backend/app/manifests/loader.py](../../../../backend/app/manifests/loader.py) | Initial Create VM profile seed definitions. |
| [backend/app/vm_create/drafts.py](../../../../backend/app/vm_create/drafts.py) | Draft construction and VMID suggestion usage. |
| [backend/app/vm_create/preflight.py](../../../../backend/app/vm_create/preflight.py) | Read-only checks. |
| [backend/app/vm_create/planner.py](../../../../backend/app/vm_create/planner.py) | Artifact-backed plan/review. |
| [backend/app/vm_create/approval.py](../../../../backend/app/vm_create/approval.py) | Exact approval metadata validation. |
| [backend/app/vm_create/proxmox_runner.py](../../../../backend/app/vm_create/proxmox_runner.py) | Native preview/create runner. |
| [backend/app/proxmox/client.py](../../../../backend/app/proxmox/client.py) | Proxmox mutation client for Create VM only. |

## Current selection sources

| Selection | Source of truth | Notes |
|---|---|---|
| Profile | DB-seeded backend data, frontend fallback | 세 enabled choices. |
| VMID | inventory adapter suggestion | UI normal flow에서 operator-supplied VMID 아님. |
| Target node | `GET /api/v1/nodes` | operator/UI default selection. |
| Template | `GET /api/v1/templates` | live/fake inventory; failing templates visible but disabled. |
| Storage | `GET /api/v1/storage` | selected node, `images` content, free capacity filter. |
| Bridge | `GET /api/v1/networks` | selected target node의 active bridge. |
| Access | wizard input + backend default SSH key fallback | password login fixed disabled. |
| Static networking | operator input | `static_ip`, `prefix`, `gateway` required. |

Networks readiness는 current Create VM source of truth가 아닙니다.

## Current flow

| Step | Frontend helper | Backend endpoint | Effect |
|---|---|---|---|
| Options load | component `useEffect` | nodes/templates/storage/networks/profiles | Read-only options. |
| Review start | `loadCreateVmReviewModel()` | readiness -> draft -> preflight -> plan | job/artifacts, no Proxmox mutation. |
| Approval | `approveCreateVmReview()` | `POST /approve` | exact metadata validation. |
| Native preview | `previewCreateVmProxmox()` | `POST /proxmox-preview` | preview artifact only. |
| Native create | `createVmWithProxmox()` | `POST /proxmox-create` | live Proxmox clone/resize/config/power-policy post-check. |

## Current success and gaps

Success는 선택 power policy 검증입니다. `stopped`는 stopped VM 생성이고, `boot_and_verify`는 VM start, guest-agent IP discovery, cloud-init completion까지 포함합니다. SSH, Ansible, app deploy, DRS identity registration은 deferred입니다.

Background reconciliation service와 DRS identity reuse는 아직 구현되지 않았습니다.
