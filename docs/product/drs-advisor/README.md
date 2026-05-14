# DRS Advisor PRD Source of Truth

이 폴더가 Gjallar의 현재 MVP 방향 source of truth다.
`../legacy-prd/24_DRS_ADVISOR_MVP_PRD.md`는 숫자형 PRD navigation을 위한 index로만 사용한다.
현재 구현 상태는 [`../../current/README.md`](../../current/README.md)를 기준으로 확인한다.

## 현재 방향

Gjallar는 백업 제품이 아니라 Proxmox 엔터프라이즈 운영 플랫폼이다.
MVP 중심은 DRS Advisor이며, VMware DRS 대체품이라고 주장하지 않는다.
Gjallar는 Proxmox-native inventory, migration, HA, storage, task state를 관찰하고, CPU/Memory 중심 추천을 만들고, 운영자 승인 후 Proxmox live migration을 실행/추적하는 advisor/control tower다.

Create VM native Proxmox/GitOps flow는 삭제하지 않는다.
현재 구현된 보조 capability로 유지하고, legacy Terraform executor route/helper code와 Terraform-named state metadata는 active contract에서 제거됐다. DRS Advisor는 기존 Dashboard, Placement, Jobs/Runs, Risks/Alerts, Proxmox inventory, job/artifact substrate를 확장한다.

## 문서 구성

| Document | Purpose |
|---|---|
| `01_PRODUCT_DIRECTION.md` | 제품 방향, MVP scope, current implemented baseline, exclusions |
| `02_UI_AND_FLOWS.md` | Dashboard, DRS Advisor, Jobs/Runs, Risks/Alerts, Create VM 보조 flow |
| `03_DATA_DB_AND_IDENTITY.md` | Source of truth, DB boundary, identity/fingerprint, metadata/policy, DB field validation usage |
| `04_DRS_RECOMMENDATION_AND_EXECUTION.md` | Recommendation model, pre-check, execution, UPID tracking, reconciliation, Proxmox assumptions |
| `05_IMPLEMENTATION_PLAN.md` | 현재 코드 기반 gap analysis와 구현 순서 |

## 현재 코드 기반 요약

문서 작성 시 확인한 현재 구현 기반:

- Frontend navigation은 `Dashboard`, `Infra Explorer`, `Networks`, `Create VM`, `Placement`, `Jobs/Runs`, `Risks/Alerts`를 제공한다.
- Dashboard는 `/api/v1/cluster/summary`, `nodes`, `vms`, `storage`, `networks`, `jobs`, `risks`를 조합해 노드/VM/storage/risk summary를 보여준다.
- Placement는 `frontend/src/utils/placement.js`에서 read-only view model을 만든다. CPU/Memory current usage, node imbalance, bridge/storage evidence, red risk exclusion을 사용하며 execution은 `available: false`다.
- Jobs/Runs는 `/api/v1/jobs`, `/api/v1/jobs/{job_id}`, `/api/v1/jobs/{job_id}/artifacts` 기반 read-only 화면이다.
- Risks/Alerts는 `/api/v1/risks`를 읽어 job-derived risk를 높은 위험도부터 보여준다.
- Backend `/api/v1`은 read-only Proxmox inventory, Jobs/Runs, Risks, Create VM draft/preflight/plan/approval/GitOps manifest commit/Proxmox native create gates를 제공한다.
- Proxmox inventory adapter는 현재 read-only이며 node CPU/Memory current usage, VM disk volume, tags, IP/guest-agent 일부 evidence를 수집한다.
- Create VM flow는 `general-vm` 중심 draft/preflight/plan, artifact-backed review, approval checksum, GitOps manifest commit/archive, Proxmox native preview/create acknowledgement gate를 갖고 있다. Active mutation은 Proxmox native create이며 Terraform plan/apply route surface는 제거됐다.

## DRS Advisor로 확장할 gap

- Backend DRS recommendation API가 없다.
- DB-backed identity/fingerprint/metadata/policy/lock/reconciliation table이 없다.
- SMBIOS UUID/vmgenid/MAC list fingerprint가 아직 inventory model에 명시적으로 없다.
- 15분 average/peak metric series와 1분 polling substrate가 없다.
- HA state, quorum, config lock, passthrough, active Proxmox task evidence가 DRS final pre-check용으로 정규화되어 있지 않다.
- Proxmox live migration request, UPID tracking, post-check, timeout, Reconcile Now가 없다.
- Placement UI는 read-only이고 `Placement` label을 사용한다. DRS Advisor label/flow로 전환해야 한다.

## 읽는 순서

1. `01_PRODUCT_DIRECTION.md`
2. `03_DATA_DB_AND_IDENTITY.md`
3. `04_DRS_RECOMMENDATION_AND_EXECUTION.md`
4. `02_UI_AND_FLOWS.md`
5. `05_IMPLEMENTATION_PLAN.md`
