# System Overview

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 System overview](../../../architecture/system/overview.md), [Current implemented state](../../../current/README.md), [Architecture index](../../../architecture/README.md).

Gjallar는 human-facing Proxmox Operations Console입니다. 현재 앱은 operational visibility, gated stopped-VM start action, guided VM creation with stopped/boot-and-verify policies, read-only network readiness/migration pre-check, DRS Advisor recommendation/check, manual policy configuration, local approval packet creation, narrow backend execution substrate, DB-backed job history, job-derived risk summaries를 제공합니다.

## Product identity

| Area | Current identity |
|---|---|
| Product | Proxmox operations and risk console |
| Actual infrastructure source | Proxmox actual VM/node/task/storage/network state |
| Gjallar-owned data | Create VM request/VM records, DRS identity/policy/lock/job/reconciliation records, approval evidence, job records, artifacts |
| Safety posture | read-only by default; live mutation limited to approval-gated Create VM native create/power-policy verification, acknowledgement-gated start for stopped non-template VMs, and narrow operator-only DRS migration-job execute route |
| DRS Advisor | frontend recommendation/check plus manual policy configuration and local approval packet creation; backend has identity/policy evidence, operation locks, local approval/job substrate, narrow execute route, UPID/task tracking, verified post-check, read-only reconcile preview |

## Active routes and domains

| Route | Current domain | 왜 존재하는가 |
|---|---|---|
| `/` | Dashboard | operator가 cluster 상태를 빠르게 보는 첫 화면 |
| `/infra` | Infra Explorer | Proxmox가 실제로 보고하는 VM/node evidence 확인과 stopped VM start |
| `/networks` | Networks | read-only bridge readiness와 migration pre-check evidence 확인 |
| `/create` | Create VM | audited VM creation; default stopped or optional boot-and-verify |
| `/drs` | DRS Advisor | recommendation/check, manual policy configuration, local approval packet creation UI; live execute/corrective reconcile controls 없음 |
| `/jobs` | Jobs/Runs | 작업 진행과 artifact metadata 확인 |
| `/risks` | Risks/Alerts | job-derived risk를 모아 확인 |

## Active data sources

Nodes, VMs, templates, storage, networks는 Proxmox inventory adapter가 제공합니다. Profiles는 `GJALLAR_DATABASE_URL`의 DB-seeded rows입니다. Create VM artifacts와 job status는 `job_runs`/`job_artifacts`에 저장됩니다. Native Create VM은 `vm_create_requests`와 `vm_instances`도 기록합니다. Create VM transitional readiness may inspect shared/IaC roots, but Networks는 Proxmox inventory evidence만 read-only로 사용하고 YAML/file/DB write source가 없습니다. DRS Advisor recommendation/check는 backend calculator가 만들고, DRS execution state는 approval/job/lock/reconciliation DB tables와 artifacts에 저장됩니다.

## Current non-goals

Current implementation에는 live DRS execute UI, corrective reconcile UI, richer policy/rule editor, corrective mutation, background automation, automatic DRS, live DRS smoke, recommendation-level migrate aliases, direct destructive VM controls, SSH/Ansible/app smoke, Proxmox bridge mutation이 없습니다. Existing VM start는 stopped non-template VM에 대한 별도 gated action이고, 새 VM first boot/IP/cloud-init 검증은 Create VM `boot_and_verify`에서만 수행됩니다.
