# 아키텍처 개요

기준 문서: [architecture index](../architecture/README.md), [system overview](../architecture/system/overview.md), [Current API V1](../architecture/api/current-api-v1.md). 이 문서는 한국어 설명용이며 source of truth가 아닙니다.

## 제품 구조

Gjallar의 현재 구조는 read-only inventory와 제한된 approval-gated mutation을 분리합니다.

```text
Frontend routes
  -> frontend/src/services/apiV1.js
  -> backend /api/v1 router
  -> read-only inventory, jobs/artifacts, network policy, Create VM modules
  -> Proxmox read-only adapter or narrow mutation client
```

현재 active route는 `/`, `/infra`, `/networks`, `/create`, `/placement`, `/jobs`, `/risks`입니다. Backend active prefix는 `/api/v1`입니다.

## 기준 문서 우선순위

현재 구현 truth는 다음 순서입니다.

1. Active code and tests.
2. [Current implemented state](../current/README.md).
3. [Current top-tab snapshots](../current/top-tabs/README.md).
4. [Architecture docs](../architecture/README.md).
5. [DRS Advisor product docs](../product/drs-advisor/README.md)는 target direction과 planned gap 확인용입니다.

인프라 actual state의 source of truth는 Proxmox입니다. VM 존재, node 위치, power state, task status, storage/network visibility는 Proxmox current state를 기준으로 봐야 합니다. Gjallar는 intent, policy, approval evidence, job/artifact, future identity/policy/reconciliation state를 저장하는 쪽입니다.

## 현재 데이터 출처

| Data | Current source |
|---|---|
| Nodes, VMs, templates, storage, networks | Proxmox inventory adapter. live 또는 fake read-only fallback. |
| Profiles | `static_seed` profile data. DB seed는 future work. |
| Create VM artifacts | `GJALLAR_RUNS_ROOT` 아래 job별 artifact files. |
| VMInstance manifest | IaC root의 `manifests/vms/`. `execute`가 쓰고 commit합니다. |
| Network policy | IaC root의 `manifests/networks/network-profiles.yaml`. |
| Jobs/Runs | `GJALLAR_RUNS_ROOT/<job_id>/job_status.json`. |
| Risks/Alerts | job status의 `risks` 배열에서 파생. |
| Placement recommendation | frontend view model이 inventory/jobs/risks를 조합. backend DRS route 없음. |

## 읽기/쓰기 경계

| Boundary | 현재 규칙 |
|---|---|
| Inventory | `backend/app/proxmox/inventory.py`는 read-only입니다. Proxmox를 mutate하지 않습니다. |
| Network policy | IaC network policy file은 쓸 수 있지만 Proxmox network config는 바꾸지 않습니다. |
| Jobs/artifacts | Create VM 단계는 job status와 artifacts를 `GJALLAR_RUNS_ROOT` 아래에 기록합니다. |
| Manifest commit | `execute`는 desired-state manifest만 commit합니다. VM을 만들지 않습니다. |
| Native create | `proxmox-create`만 현재 active live VM creation path입니다. |
| Terraform | plan/apply route, helper code, Terraform-named state metadata는 active contract에서 제거되었습니다. |
| DRS | `/api/v1/drs/*`, migration execution, locks, reconciliation backend는 없습니다. |

## 모듈 책임

| Layer | Module | 역할 |
|---|---|---|
| Frontend routing | `frontend/src/App.jsx` | route shell과 navigation. |
| Frontend API client | `frontend/src/services/apiV1.js` | `/api/v1` 호출과 envelope unwrap. |
| Frontend view models | `frontend/src/utils/*.js` | inventory, placement, jobs, risks, Create VM 화면 모델 정규화. |
| Backend API | `backend/app/api/v1/router.py` | route orchestration, approval gates, job progress 기록. |
| Read-only inventory | `backend/app/proxmox/inventory.py` | fake/live Proxmox read-only adapter. |
| Proxmox mutation | `backend/app/proxmox/client.py` | Create VM native path에서만 쓰는 별도 mutation client. |
| Create VM | `backend/app/vm_create/*` | draft, preflight, plan, approval, manifest, native create. |
| Network policy | `backend/app/network_policy.py` | IaC policy load/save와 live bridge policy view. |
| Jobs/artifacts | `backend/app/jobs/*` | job status, artifact metadata, checksummed files. |
| Manifests | `backend/app/manifests/*` | transitional profile seed와 manifest helper. |

## 작업과 artifact 흐름: Job

Create VM은 operator decision을 나중에 검토할 수 있도록 job과 artifact를 남깁니다.

1. Draft/preflight/plan/approval/commit/create 단계가 `vm_create` job progress로 기록됩니다.
2. Plan 단계는 `preflight_report`, `plan`, `vm_instance_manifest`, `planned_git_diff`, `review_summary` artifact를 씁니다.
3. Approval validation은 run directory가 있을 때 `approval.json`을 쓰거나 갱신할 수 있습니다.
4. Native preview는 `proxmox_create_preview` artifact를 씁니다.
5. Native create post-check는 `observed_after` artifact를 씁니다.
6. `GET /api/v1/jobs/{job_id}/artifacts`는 artifact metadata를 보여주며 file content를 직접 반환하지 않습니다.

현재 job status는 immutable audit log가 아니라 latest-state persistence입니다. 긴 원문 log나 secret-bearing value를 그대로 API response에 노출하지 않는 것이 원칙입니다.

## 안전 기본 원칙

현재 설계의 기본값은 read-only입니다. Live mutation은 Create VM native create에만 좁게 열려 있고, 다음 gate를 통과해야 합니다.

- plan artifact id와 review summary checksum이 정확해야 합니다.
- yellow risk가 있으면 acknowledgement가 필요합니다.
- manifest commit이 먼저 검증되어야 합니다.
- mutation 직전 fresh preflight/plan에 red risk가 없어야 합니다.
- `proxmox_mutation_acknowledged=true`가 필요합니다.

이 gate는 DRS migration gate가 아닙니다. DRS Advisor는 별도의 final pre-check, operation lock, migration UPID tracking, reconciliation flow가 필요합니다.

## 현재 목표가 아닌 항목

- `/api/v1/drs/*` backend와 DRS migration execution.
- automatic DRS, scheduled rebalance, VMware DRS compatibility.
- DB identity/fingerprint/policy/lock/reconciliation tables.
- direct VM start/stop/reset/delete/snapshot UI.
- Create VM 이후 first power-on, smoke, SSH, Ansible verification.
- Proxmox bridge 생성/삭제/수정.
- Terraform plan/apply route surface.
- GitLab environment controller, CI/CD orchestrator, LLM assistant product.
