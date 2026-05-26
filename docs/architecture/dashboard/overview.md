# Dashboard Architecture

Status source: [current product status](../../current/README.md). Relevant top-tab status: [Dashboard](../../current/top-tabs/01-dashboard.md).

The Dashboard is the `/` route. It is a read-only operational summary over current inventory, job, and risk APIs.

## Current Route And Component

| Concern | Current implementation |
|---|---|
| Route | `/` |
| Component | `Dashboard` inside `frontend/src/App.jsx` |
| API client | `frontend/src/services/apiV1.js` |
| View model | `buildDashboardModel()` inside `frontend/src/App.jsx` |
| Mutation controls | None |

## APIs Used

Dashboard loads all data with `Promise.allSettled()`:

| API | Used for |
|---|---|
| `GET /api/v1/cluster/summary` | Cluster id, node/vm/template counts, read-only mode. |
| `GET /api/v1/nodes` | Node status and CPU/memory usage. |
| `GET /api/v1/vms` | VM count, running VM count, node grouping. |
| `GET /api/v1/storage` | Storage capacity summary and NFS presence. |
| `GET /api/v1/networks` | Bridge count and node network list. |
| `GET /api/v1/jobs` | Active job count. |
| `GET /api/v1/risks` | Red risk count. |

## Partial-Load Behavior

Each API request resolves independently:

| Result | Behavior |
|---|---|
| Fulfilled call | Replaces that slice of snapshot state. |
| Rejected call | Keeps the previous value for that slice or uses a safe empty fallback. |
| One or more rejected calls | Shows a yellow partial-failure notice naming the failed data groups. |

This matters because Jobs/Runs and Risks/Alerts depend on the DB-backed job store, which may be temporarily unavailable. Inventory should still render when job history cannot be read.

## Current Cards And Tables

| UI area | Current content |
|---|---|
| Header pills | Cluster health derived from node online count and red risk count; "Live read-only" label. |
| Top metric tiles | Nodes online/total, total VMs/running VMs, storage summary/free storage, red risks/active jobs. |
| Datacenter sidebar | Cluster id, node list, Networks link with bridge count, Jobs/Runs link with active job count. |
| Cluster Summary table | Node status, running/total VMs, CPU usage, memory usage, active bridges, storage free summary. |
| Actions | Refresh, navigate to Infra Explorer, navigate to Create VM. |

The dashboard does not expose destructive controls, direct VM operations, DRS approval, or migration execution.

## Target DRS Additions

Target DRS Advisor dashboard work is not current.

| Target item | Current status |
|---|---|
| 15-minute average/peak load | Not implemented. Current inventory shows point-in-time or adapter-provided usage only. |
| Top DRS recommendation card | Not implemented on Dashboard. Current `/drs` shows backend read-only candidates. |
| DRS blocker summary | Implemented inside DRS Phase 1 recommendation responses; not yet integrated into Dashboard/Risks. |
| Recent DRS migration health | Not implemented. No DRS migration jobs exist. |

## Non-Goals

- No Dashboard `/api/v1/drs/*` calls.
- No migration approval or execution.
- No VM start/stop/delete/snapshot controls.
- No standalone alert engine.
