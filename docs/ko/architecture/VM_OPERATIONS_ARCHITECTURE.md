# Gjallar VM Operations Architecture

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 VM operations architecture](../../architecture/VM_OPERATIONS_ARCHITECTURE.md), [Current implemented state](../../current/README.md), [DRS Advisor product docs](../../product/drs-advisor/README.md).

Gjallar는 Proxmox 운영자를 위한 Operations & Risk Console입니다. 현재 구현은 live/read-only inventory, stopped VM start action, guided VM creation, DRS Advisor read/check UI와 narrow backend execution substrate, job history, risk summary를 제공합니다. CI/CD 시스템, source deployment tool, GitLab environment controller, LLM assistant product가 아닙니다.

## Active system shape

```text
React operator UI
  -> /api/v1 FastAPI router
    -> read-only Proxmox inventory adapter
    -> read-only network readiness and migration pre-check evidence
    -> Create VM draft/preflight/plan/approval helpers
    -> DRS recommendation/check, local approval/job, narrow execute, read-only reconcile preview
    -> DB-backed Jobs/Runs and risk summaries
    -> gated Proxmox native clone/resize/config/post-check helpers
    -> gated existing-VM start helper
```

기본 안전 자세는 read-only입니다. Live side effect는 현재 Create VM native create, stopped non-template VM start, narrow operator-only DRS migration-job execute route에 좁게 열려 있습니다. Create VM은 exact approval metadata와 `proxmox_mutation_acknowledged=true` gate를 통과해야 하며, VM start는 acknowledgement, idempotency key, fresh inventory precheck, task polling, running post-check를 요구합니다. DRS execute는 stored approval/job, fresh gates, live Proxmox evidence, operation locks, verified post-check를 요구합니다.

## Frontend route 책임

| Route | Component | 현재 역할 |
|---|---|---|
| `/` | `Dashboard` in [frontend/src/App.jsx](../../../frontend/src/App.jsx) | cluster/node/VM/storage/job/risk summary. |
| `/infra` | [InstanceList.jsx](../../../frontend/src/components/InstanceList.jsx) | VM inventory, detail evidence, stopped VM Start action. |
| `/networks` | [NetworkReadinessScreen.jsx](../../../frontend/src/components/NetworkReadinessScreen.jsx) | read-only Network Readiness / migration pre-check visualization. |
| `/create` | [CreateInstanceWizard.jsx](../../../frontend/src/components/CreateInstanceWizard.jsx) | guided Create VM flow. |
| `/drs` | [DrsAdvisorScreen.jsx](../../../frontend/src/components/DrsAdvisorScreen.jsx) | DRS Advisor read/check UI. Broad approval/execute/reconcile controls는 아직 없습니다. |
| `/jobs` | [TaskBoard.jsx](../../../frontend/src/components/TaskBoard.jsx) | job/run progress와 artifact metadata. |
| `/risks` | [OperationalRiskDashboard.jsx](../../../frontend/src/components/OperationalRiskDashboard.jsx) | job-derived risk summaries. |

## Backend module 책임

| Module | 역할 |
|---|---|
| [backend/app/api/v1/router.py](../../../backend/app/api/v1/router.py) | `/api/v1` route composition, response envelopes, job recording, gate orchestration. |
| [backend/app/proxmox/inventory.py](../../../backend/app/proxmox/inventory.py) | live/fake read-only inventory. Proxmox mutation을 넣으면 안 되는 경계입니다. |
| [backend/app/proxmox/client.py](../../../backend/app/proxmox/client.py) | gated mutation path에서만 쓰는 explicit mutation client. |
| [backend/app/drs](../../../backend/app/drs) | DRS recommendation/check, identity/policy evidence, operation locks, local approval/job substrate, narrow execution, post-check, read-only reconcile preview. |
| [backend/app/proxmox/drs_migration.py](../../../backend/app/proxmox/drs_migration.py) | Dedicated DRS Proxmox migration client. |
| [backend/app/vm_create](../../../backend/app/vm_create) | draft, preflight, plan, approval, manifest evidence, native runner helpers. |
| [backend/app/vm_actions](../../../backend/app/vm_actions) | Create VM과 read-only inventory에서 분리된 기존 VM action helper. |
| [backend/app/jobs](../../../backend/app/jobs) | DB-backed job status, artifacts, approval records, risk source data. |
| [backend/app/manifests](../../../backend/app/manifests) | transitional profile seed와 manifest schema helpers. |

## Current API surface

Inventory/read-mostly: `cluster/summary`, `nodes`, `vms`, `vms/{vmid}`, `templates`, `storage`, `networks`, `jobs`, `jobs/{job_id}`, `jobs/{job_id}/artifacts`, `risks`, `drs/summary`, `drs/recommendations`, `drs/recommendations/{recommendation_id}`, `drs/recommendations/{recommendation_id}/check`, `drs/recommendations/{recommendation_id}/approval-packets`, `drs/migration-jobs/{job_id}/execute`, `drs/migration-jobs/{job_id}/reconcile-preview`, `nodes/{node_id}/vms/{vmid}/actions/start`.

Create VM: `profiles`, `vm-create/readiness`, `drafts`, `preflight`, `plan`, `approve`, `proxmox-preview`, `proxmox-create`.

Networks는 live bridge readiness와 migration pre-check evidence를 read-only로 보여줍니다. Network YAML/file/DB/API write path나 DRS 실행 권한은 없습니다.

상세는 [api/current-api-v1.md](api/current-api-v1.md)를 봅니다.

## DRS Advisor current boundary

현재 `/drs` frontend는 read/check only입니다. Recommendation/check output은 `read_only=true`, `executable=false`, `allowed_actions=[]`입니다. Backend는 identity/policy evidence, operation locks, local approval/job substrate, narrow operator-only migration-job execute route, UPID/task tracking, verified post-check, read-only reconcile preview를 제공합니다.

남은 target gap은 broad execution UI, policy editor, corrective mutation, background automation, automatic DRS, live DRS smoke, recommendation-level migrate aliases입니다.

## 주요 data flow

Dashboard는 cluster/nodes/vms/storage/networks/jobs/risks를 병렬로 읽어 partial-load summary를 만듭니다.

Read-only inventory flow는 `apiV1Client` -> router -> `get_default_inventory_adapter()` -> live adapter 또는 fake fallback입니다.

Jobs/Risks flow는 Create VM과 VM start route가 `record_job_run()`으로 job_status를 쓰고, `/jobs`가 summaries를 읽으며, `/risks`가 stored risk arrays를 펼칩니다.

Native Create VM flow는 Create wizard -> draft/preflight/plan/approve -> final acknowledgement -> `proxmox-create` -> internal preview artifact -> clone/poll/resize/config/power-policy post-check -> `observed_after` artifact입니다.

## Safety boundaries

현재 제외되는 항목: direct VM stop/reset/delete/snapshot, broad DRS execution UI, recommendation-level DRS migrate aliases, Proxmox bridge mutation, SSH/Ansible/app smoke, LLM/chat product route. Existing VM start는 stopped non-template VM에 대한 별도 gated action이고, 새 VM first boot/IP/cloud-init 검증은 Create VM `boot_and_verify`에서만 수행됩니다.
