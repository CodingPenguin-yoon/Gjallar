# API 빠른 안내

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [Current API V1](../architecture/api/current-api-v1.md), [Current implemented state](../current/README.md), [VM provisioning contract](../architecture/VM_PROVISIONING_CONTRACT.md).

현재 active API prefix는 `/api/v1`입니다. 성공 응답은 보통 `ok`, `data`, optional `meta` 형태의 envelope를 사용합니다. Error response는 아직 완전히 정규화되어 있지 않으며 FastAPI `HTTPException`의 `detail` object가 올 수 있습니다.

자세한 endpoint별 구현 함수, frontend 호출 함수, side effect는 [architecture/api/current-api-v1.md](architecture/api/current-api-v1.md)를 봅니다.

## 현재 active endpoint 그룹

| 그룹 | Endpoints | 현재 의미 |
|---|---|---|
| Health/root | `GET /`, `GET /health` | 앱/서비스 상태 확인. |
| Inventory | `cluster/summary`, `nodes`, `vms`, `vms/{vmid}`, `templates`, `storage`, `networks` | Proxmox read-only inventory. |
| Profiles/readiness | `profiles`, `vm-create/readiness` | Create VM option/readiness source. |
| Network policy | `GET/PUT /networks/policy` | IaC-backed network policy view/write. Proxmox bridge mutation 아님. |
| Jobs/Risks | `jobs`, `jobs/{job_id}`, `jobs/{job_id}/artifacts`, `risks` | DB-backed job status와 job-derived risks. |
| Create VM | `drafts`, `preflight`, `plan`, `approve`, `proxmox-preview`, `proxmox-create` | Draft부터 approval, native create까지. |

## Create VM에서 가장 헷갈리는 endpoint

- `POST /api/v1/vm-create/{draft_id}/proxmox-preview`: approval-gated but non-mutating preview입니다.
- `POST /api/v1/vm-create/{draft_id}/proxmox-create`: 현재 유일한 active live VM creation endpoint입니다.

## 현재 없는 API

Target DRS API는 future-only입니다. 현재 `/api/v1/drs/*` route는 없습니다. 현재 `/placement`는 기존 inventory/jobs/risks API를 조합하는 frontend read-only read model입니다.

자세한 target 후보는 [architecture/api/target-drs-api.md](architecture/api/target-drs-api.md)를 봅니다.
