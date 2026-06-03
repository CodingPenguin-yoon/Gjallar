# DRS Advisor Implementation Plan

Status note: this is a historical phased plan. Goals 2-6 backend DRS substrate is implemented: compact identity/policy evidence, operation locks, local approval/job substrate, a narrow operator-only migration-job execute route, UPID/task tracking, verified post-check, and read-only reconcile preview. Goal 7 and Goal 7.5 added the minimal safe DRS UI slice plus manual VM migration policy UI/API. Goal 10 later added approved VMID `140` live DRS smoke evidence and stored-UPID local reconciliation completion. Recommendation/check output remains execution-closed; live migration execute UI, corrective reconcile UI, richer policy rule/full metadata editing, corrective mutation, background automation, and automatic DRS remain deferred.

## 1. Current code inventory

현재 구현을 기반으로 DRS Advisor를 붙인다.

Frontend:

- `frontend/src/App.jsx`: route/nav, Dashboard aggregation
- `frontend/src/components/DrsAdvisorScreen.jsx`: DRS Advisor recommendation/check screen with manual policy configuration and local approval packet/job intent creation, but without live execute or corrective reconcile controls
- `frontend/src/utils/drsAdvisor.js`: DRS recommendation/check view model
- `frontend/src/components/TaskBoard.jsx`: Jobs/Runs read-only UI
- `frontend/src/utils/jobsScreen.js`: job/artifact view model
- `frontend/src/components/OperationalRiskDashboard.jsx`: Risks/Alerts UI
- `frontend/src/utils/risksScreen.js`: risk sorting/view model
- `frontend/src/components/CreateInstanceWizard.jsx`: Create VM wizard and approval/Proxmox native create gates
- `frontend/src/services/apiV1.js`: `/api/v1` client

Backend:

- `backend/app/api/v1/router.py`: inventory, jobs, risks, VM create endpoints
- `backend/app/drs/advisor.py`: execution-closed DRS recommendation/check calculator
- `backend/app/drs/identity.py`, `backend/app/drs/policies.py`, `backend/app/drs/operation_locks.py`, `backend/app/drs/approval.py`, `backend/app/drs/execution.py`: identity/policy evidence, manual policy API service, operation locks, local approval/job substrate, narrow execution, post-check, and read-only reconcile preview
- `backend/app/proxmox/drs_migration.py`: dedicated DRS Proxmox migration client
- `backend/app/proxmox/inventory.py`: fake/live read-only Proxmox inventory adapter
- `backend/app/proxmox/models.py`: inventory dataclasses
- `backend/app/jobs/runs.py`: DB-backed job run status
- `backend/app/jobs/artifacts.py`: DB-backed artifact writing
- `backend/app/vm_create/preflight.py`: Create VM preflight checks
- `backend/app/vm_create/planner.py`: artifact-backed plan/review
- `backend/app/vm_create/approval.py`: review checksum and yellow risk gate
- `backend/app/proxmox/client.py`: native Proxmox mutation client for gated Create VM clone/config/status
- `backend/app/vm_create/proxmox_runner.py`: native Create VM preview/create runner, UPID polling, post-check, observed_after/fingerprint artifacts
- Terraform executor route/helper code and Terraform-named state metadata are removed from active contracts

Tests that lock useful current behavior:

- `frontend/tests/drsAdvisor.test.mjs`
- `frontend/tests/apiV1Client.test.mjs`
- `frontend/tests/jobsScreen.test.mjs`
- `frontend/tests/risksScreen.test.mjs`
- `backend/tests/proxmox/test_inventory_adapter.py`
- `backend/tests/drs`
- `backend/tests/contracts/test_jobs_risks_contract.py`
- `backend/tests/contracts/test_api_v1_vm_create*.py`
- `backend/tests/contracts/test_forbidden_mvp_endpoints.py`

## 2. Implementation principle

DRS Advisor should extend current code rather than replace everything.

Reuse:

- `/api/v1` envelope and client pattern
- read-only inventory adapter shape
- DRS Phase 1 view model tests as seed
- job/artifact run storage concepts
- risk display pattern
- Create VM approval artifact/checksum pattern
- Create VM native Proxmox UPID polling and observed_after/fingerprint artifact pattern
- secret redaction
- forbidden endpoint guard philosophy

Do not reuse as-is:

- frontend-only recommendation as execution source
- recommendation/check contract as final executable product
- Create VM preflight as DRS final pre-check
- VMID as identity
- DB observed snapshot as execution source of truth

## 3. Phase 1 - Backend DRS read model

Goals:

- Maintain DRS recommendation backend read API.
- Keep Proxmox mutations disabled in this phase.
- Keep recommendation logic server-side with contract tests.

Candidate endpoints:

```http
GET /api/v1/drs/summary
GET /api/v1/drs/recommendations
GET /api/v1/drs/recommendations/{recommendation_id}
POST /api/v1/drs/recommendations/{recommendation_id}/check
```

Implementation details:

- Use current inventory adapter for nodes/vms/storage/networks.
- Keep current thresholds as initial compatibility: 70 hot, 85 critical, 25 delta.
- Add response fields for target model even if value is `unknown`: VM Mobility, Route Status, identity status, metadata status.
- Mark all recommendations non-executable until metadata/identity tables exist.

Tests:

- DRS Advisor tests should keep passing.
- Backend contract tests should assert unsafe recommendation-level approve/migrate/live-migrate aliases and broad shortcuts are absent. They must not assert absence of the stored `/api/v1/drs/migration-jobs/{job_id}/execute` route.
- DRS recommendations should exclude red-risk VMs and offline targets.

## 4. Phase 2 - Metrics, identity, and metadata

Goals:

- Add DB-backed identity/fingerprint/metadata/policy concepts.
- Add inventory evidence needed for fingerprint.
- Add 15m average/peak metric model.

Work:

- Extend Proxmox inventory detail collection for SMBIOS UUID, vmgenid, MAC address list, disk volume id list.
- Add metric samples or observed node metric table.
- Add metadata CRUD/import flow scoped to DRS requirements.
- Add Confirm Identity, Confirm Same VM, Treat as New VM decisions.
- Add policy validation for allowed/restricted/blocked.

Tests:

- same VMID + different fingerprint creates Identity Mismatch.
- unknown fingerprint blocks migration.
- name/tag/IP/owner/profile alone cannot confirm identity.
- restricted/blocked policies disable Approve & Migrate.
- Allowed + confirmed + complete metadata can become executable if route/final pre-check allows.

## 5. Phase 3 - DRS Advisor UI transition

Goals:

- Keep `/drs` label and route as DRS Advisor.
- Replace card-only recommendations with full table + detail drawer.
- Add Dashboard top 1~3 recommendations.

Work:

- Keep nav label as DRS Advisor.
- Dashboard consumes DRS summary.
- DRS Advisor screen shows identity, metadata, policy, mobility, route status.
- Add Check Now panel.
- Keep execution disabled unless backend says action is available.

Tests:

- App navigation includes `/drs` and label is DRS Advisor.
- Dashboard shows max 3 recommendations.
- DRS Advisor table displays identity/policy/route fields.
- Unknown route disables migration.
- Check Now result is marked reference-only.

## 6. Phase 4 - Final pre-check and approval

Goals:

- Implement authoritative final pre-check.
- Add Approve & Migrate confirm modal.
- Add operation locks.

Candidate endpoints:

```http
POST /api/v1/drs/recommendations/{recommendation_id}/approve-migrate
POST /api/v1/drs/jobs/{job_id}/confirm
```

Or one endpoint can run final pre-check and return confirm packet before a second confirm endpoint starts migration.

Required final pre-check:

1. identity confirmed
2. metadata complete
3. migration policy allowed
4. no operation lock
5. VM still on source node
6. VM running
7. target node online
8. cluster health/quorum OK
9. no active conflicting task
10. route feasible/warning

Tests:

- Check Now cannot authorize execution.
- stale recommendation requires final pre-check.
- source node mismatch blocks.
- active lock blocks.
- warning requires acknowledgement.
- blocker/unknown does not create migration job.

## 7. Phase 5 - Proxmox migration execution

Goals:

- Execute manual approved live migration through Proxmox.
- Track UPID and logs.
- Publish Jobs/Runs artifacts.

Work:

- Add Proxmox migration client separate from read-only inventory adapter.
- Keep mutation surface narrow and DRS-only.
- Store UPID in `proxmox_tasks`.
- Poll task status/log.
- Post-check VM target node, running state, fingerprint.
- Release lock only after clear success/failure.

Tests:

- migration request stores UPID.
- task success plus target/fingerprint success marks job success.
- task failure marks job failed.
- task success but wrong target or fingerprint mismatch marks needs_reconciliation.
- secrets do not appear in logs/artifacts/API response.

## 8. Phase 6 - Reconciliation and restart safety

Goals:

- Gjallar restart can rebuild DRS view from Proxmox current state.
- running/unknown jobs can be reattached by UPID and current state.
- metadata/policy reattach only by fingerprint match.

Work:

- Add startup reconciliation scan.
- Add Reconcile Now endpoint/action.
- Add lock stale/reconciliation_required handling.
- Store reconciliation_events.

Candidate endpoint:

```http
POST /api/v1/drs/jobs/{job_id}/reconcile
```

Tests:

- restart with same fingerprint reattaches metadata.
- restart with same VMID but different fingerprint creates Identity Mismatch.
- timeout after 30m marks needs_reconciliation.
- Reconcile Now success requires target node running + fingerprint match.
- ambiguous state keeps needs_reconciliation.

## 9. Deferred

- automatic DRS
- scheduled/nightly rebalance
- restricted exception approval
- node drain
- maintenance mode automation
- affinity/anti-affinity editor
- backup/snapshot orchestration
- cleanup or artifact auto deletion
- VMware DRS compatibility language
