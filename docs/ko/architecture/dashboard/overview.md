# Dashboard Architecture

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 Dashboard architecture](../../../architecture/dashboard/overview.md), [Dashboard snapshot](../../../current/top-tabs/01-dashboard.md), [Current implemented state](../../../current/README.md).

Dashboard는 `/` route의 read-only operational summary입니다. 목적은 operator가 cluster, nodes, VMs, storage, jobs, risks를 빠르게 확인하는 것입니다.

## Current route and implementation

| Concern | Current implementation |
|---|---|
| Route | `/` |
| Component | `Dashboard` inside [frontend/src/App.jsx](../../../../frontend/src/App.jsx) |
| View model | `buildDashboardModel()` inside App.jsx |
| API client | [frontend/src/services/apiV1.js](../../../../frontend/src/services/apiV1.js) |
| Mutation controls | None |

## APIs used

Dashboard는 `Promise.allSettled()`로 `cluster/summary`, `nodes`, `vms`, `storage`, `networks`, `jobs`, `risks`를 병렬 조회합니다. 한 data group이 실패하면 해당 group만 fallback을 쓰고 partial failure notice를 표시합니다.

## Current UI model

Top tiles는 online nodes, total/running VMs, storage summary, red risks/active jobs를 보여줍니다. Node table은 node status, running/total VMs, current CPU usage, current memory usage, active bridges, storage free를 보여줍니다. Actions는 refresh, Infra Explorer 이동, Create VM 이동입니다.

## Target DRS additions

DRS target에서는 15-minute average/peak load, top DRS recommendation card, DRS blocker summary, recent DRS migration health가 필요합니다. 현재 Dashboard는 이런 DRS execution evidence를 제공하지 않습니다.
