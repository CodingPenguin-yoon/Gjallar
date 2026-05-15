# System Overview

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 System overview](../../../architecture/system/overview.md), [Current implemented state](../../../current/README.md), [Architecture index](../../../architecture/README.md).

Gjallar는 human-facing Proxmox Operations Console입니다. 현재 앱은 read-only operational visibility, guided powered-off VM creation, network policy inspection/writes, read-only placement recommendations, file-backed job history, job-derived risk summaries를 제공합니다.

## Product identity

| Area | Current identity |
|---|---|
| Product | Proxmox operations and risk console |
| Actual infrastructure source | Proxmox actual VM/node/task/storage/network state |
| Gjallar-owned data | intent manifests, policy files, approval evidence, job status files, artifacts, future identity/policy/reconciliation data |
| Safety posture | read-only by default; live mutation limited to approval-gated Create VM native create |
| DRS Advisor | target product direction, not current backend execution |

## Active routes and domains

| Route | Current domain | 왜 존재하는가 |
|---|---|---|
| `/` | Dashboard | operator가 cluster 상태를 빠르게 보는 첫 화면 |
| `/infra` | Infra Explorer | Proxmox가 실제로 보고하는 VM/node evidence 확인 |
| `/networks` | Networks | bridge inventory와 IaC policy 정합성 관리 |
| `/create` | Create VM | audited powered-off VM creation |
| `/placement` | Placement seed | future DRS Advisor의 read-only seed |
| `/jobs` | Jobs/Runs | 작업 진행과 artifact metadata 확인 |
| `/risks` | Risks/Alerts | job-derived risk를 모아 확인 |

## Active data sources

Nodes, VMs, templates, storage, networks는 Proxmox inventory adapter가 제공합니다. Profiles는 transitional `static_seed`입니다. Create VM artifacts와 job status는 `GJALLAR_RUNS_ROOT` 아래에 file-backed로 저장됩니다. VMInstance manifests와 network policy는 IaC root 아래 파일입니다. Placement recommendations는 현재 frontend view model이 만듭니다.

## Current non-goals

Current implementation에는 `/api/v1/drs/*`, DRS migration execution, operation locks, DB identity/policy tables, direct destructive VM controls, first power-on/smoke after Create VM, Proxmox bridge mutation이 없습니다.
