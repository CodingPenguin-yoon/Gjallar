# Dashboard

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 Dashboard snapshot](../../../current/top-tabs/01-dashboard.md), [영어 Dashboard architecture](../../../architecture/dashboard/overview.md), [Current implemented state](../../../current/README.md).

Dashboard는 `/` route의 read-only 운영 요약 화면입니다. 목적은 운영자가 cluster/node/VM/storage/job/risk 상태를 한 화면에서 빠르게 보는 것입니다. DRS 실행 판단이나 migration 시작 화면이 아닙니다.

## 사용하는 API와 호출 위치

| API | 하는 일 | Frontend 호출 |
|---|---|---|
| `GET /api/v1/cluster/summary` | cluster id, node/vm/template count, mode summary | `Dashboard` in [frontend/src/App.jsx](../../../../frontend/src/App.jsx) |
| `GET /api/v1/nodes` | node status, current CPU/Memory, storage/network evidence | `Dashboard` data load |
| `GET /api/v1/vms` | VM count, running VM count, node grouping | `Dashboard` data load |
| `GET /api/v1/storage` | storage capacity summary | `Dashboard` data load |
| `GET /api/v1/networks` | bridge count와 node network 목록 | `Dashboard` data load |
| `GET /api/v1/jobs` | active job count | `Dashboard` data load |
| `GET /api/v1/risks` | red risk count | `Dashboard` data load |

Backend route는 [backend/app/api/v1/router.py](../../../../backend/app/api/v1/router.py)에 있고, inventory 계열은 read-only Proxmox inventory adapter를 사용합니다. Jobs/Risks는 DB-backed job status에서 읽습니다.

## 구현 방식

Dashboard는 여러 API를 `Promise.allSettled()` 방식으로 병렬 조회합니다. 한 API가 실패해도 이전 snapshot 또는 safe fallback으로 나머지 화면을 유지합니다. 이 설계는 job/risk DB read가 일시적으로 실패해도 inventory 첫 화면을 비우지 않기 위한 것입니다.

화면은 node online count, VM/running count, storage free summary, red risk count, active job count를 보여줍니다. Node row에는 current CPU/Memory, VM 수, storage free, active bridge 목록이 표시됩니다.

## 현재 하지 않는 일

- `/api/v1/drs/*` 호출.
- DRS recommendation final authority 제공.
- migration approval 또는 execution.
- VM start/stop/delete/snapshot 같은 destructive control.
- 15분 average/peak metric 기반 판단.

## Target gap

DRS Advisor 목표에서는 Dashboard가 top 1-3 recommendation summary와 node별 15분 average/peak/blocker count를 보여줘야 합니다. 현재는 point-in-time inventory와 job-derived risks 중심이므로, 실행 gate로 사용하면 안 됩니다.
