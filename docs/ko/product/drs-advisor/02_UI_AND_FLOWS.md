# DRS Advisor UI And Flows

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 UI and flows](../../../product/drs-advisor/02_UI_AND_FLOWS.md), [Placement snapshot](../../../current/top-tabs/05-placement-drs-advisor.md), [Target DRS flow](../../../architecture/flows/drs-approve-migrate-reconcile.md).

## 현재 UI baseline

Current routes are Dashboard `/`, Infra Explorer `/infra`, Networks `/networks`, Create VM `/create`, DRS Advisor `/drs`, Jobs/Runs `/jobs`, Risks/Alerts `/risks`.

현재 `/drs` route는 recommendation/detail/check, manual VM policy configuration, local approval packet/job intent creation을 제공합니다. Recommendation/check output은 계속 `read_only=true`, `executable=false`, `allowed_actions=[]`입니다.

## 왜 각 화면이 필요한가

| 화면 | 필요한 이유 |
|---|---|
| Dashboard | operator가 cluster pressure와 top recommendation을 빠르게 발견하는 entry point. |
| DRS Advisor | recommendation evidence, identity, policy, route, blockers를 비교하고 승인하는 중심 화면. |
| Jobs/Runs | 승인/실행/UPID/post-check/reconciliation을 감사 가능한 작업 이력으로 보여주는 화면. |
| Risks/Alerts | identity mismatch, route unknown, stale lock 같은 실행 차단 요소를 놓치지 않게 하는 화면. |
| Create VM | DRS success line은 아니지만 approval/artifact/job pattern을 제공하는 supporting capability. |

## Target Dashboard

Dashboard는 node row 중심이어야 합니다. Current usage뿐 아니라 15분 average/peak, active task count, HA/storage warnings, blocker count를 보여줘야 합니다. Top 1-3 DRS recommendation summary는 DRS Advisor 상세로 이동하는 entry point이며, Dashboard에서 migration을 바로 실행하지 않습니다.

## Target DRS Advisor screen

Recommendation table fields include rank, recommendation id, VM name, VMID locator, identity status, metadata completeness, migration policy, sensitivity, source/target node, CPU/Memory evidence, route status, blockers, warnings, generated_at, action availability.

Allowed VM만 Approve & Migrate가 활성화됩니다. Unclassified, Identity Mismatch, Restricted, Blocked, Route Unknown은 실행 불가입니다.

## Approve & Migrate flow

```text
recommendation selected
-> Approve & Migrate clicked
-> backend reconstructs current Proxmox state
-> final pre-check
-> blocked/unknown: show blockers, no job
-> pass/warning: confirm modal
-> warning acknowledgement if needed
-> operation lock acquired
-> drs_migration job created
-> Proxmox live migration requested
-> UPID stored and polled
-> post-check target node/running/fingerprint
-> success/failed/needs_reconciliation
```

Confirm modal은 VM identity, fingerprint assertion, source/target, policy, sensitivity, final pre-check result, blockers/warnings, lock scope, timeout, Proxmox action summary를 보여줘야 합니다.

## Current gap

현재 `/drs`에는 live migration execute button이나 corrective reconcile UI가 없습니다. Manual policy configuration과 local approval packet/job intent creation은 current UI에 있고, backend에는 final pre-check, operation locks, UPID/task tracking, DRS job/artifact evidence, verified post-check, read-only reconcile preview, stored-UPID local reconciliation follow-up이 있습니다. Approved VMID `140` live DRS smoke evidence는 기록됐습니다. Live execute UI, corrective reconcile UI, richer policy rule/full metadata editor, blocker taxonomy UI는 남은 gap입니다.
