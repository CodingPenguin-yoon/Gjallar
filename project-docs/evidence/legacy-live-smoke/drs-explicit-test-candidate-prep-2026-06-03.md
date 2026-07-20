# DRS Explicit Test Candidate Prep - 2026-06-03

Status: live DRS migration was later submitted after parser-fix readiness,
Proxmox task completed `OK`, and Gjallar required local reconciliation because
the direct post-check fingerprint parser included a cloud-init cdrom volume.

This records the approved backend-only DRS smoke preparation and subsequent
approved live DRS migration attempt for VMID `140`. It did not perform cleanup,
delete, reverse migration, retry migration, or corrective reconciliation
mutation.

## Target

| Field | Value |
| --- | --- |
| VMID | `140` |
| VM name | `gjallar-vm-job-drs-test-vm-create-20260601t045853z` |
| Source node | `yoonmanserver` |
| Intended target node | `yoonserver3` |
| VM identity id | `vmid-96b58c8276a84f70bbdae645fc8f0f78` |
| Recommendation id | `drs-rec-explicit-test-vm-140-yoonmanserver-yoonserver3` |
| Operator | `yoon / admin` |

## Preconditions

The first policy update attempt exposed that the local Gjallar DB was still at
Alembic revision `20260530_0023`. The policy audit table
`vm_migration_policy_events` is introduced by `20260531_0024`, so the local DB
was upgraded to head before retrying the approved 1-3 sequence:

```bash
cd backend
set -a
. ../.env
set +a
venv/bin/alembic upgrade head
```

Observed migration:

```text
20260530_0023 -> 20260531_0024
20260531_0024 -> 20260601_0025
```

## Step 1: Explicit Check

Before policy update, the explicit test candidate check was recognized as a
current explicit candidate with high-confidence identity. It was blocked only
by migration policy:

| Field | Value |
| --- | --- |
| `would_be_executable` | `false` |
| Identity confidence | `high` |
| Policy | `unknown` |
| Blockers | `migration_policy_unknown`, `drs_final_precheck_failed` |

## Step 2: Policy Allowed

Gjallar-local DRS migration policy was set to `allowed` with operator
acknowledgement and current high-confidence observation guard.

| Field | Value |
| --- | --- |
| Previous policy | `unknown` |
| New policy | `allowed` |
| Policy id | `vmpol-f8c45a20e6a546b18ba8df1918473a14` |
| Audit event id | `vmpolevt-6eacefaa4d5e4555a01433a4cacf90b7` |
| Side effects | `gjallar_local_policy_update` |

After policy update, the explicit check passed:

| Field | Value |
| --- | --- |
| `would_be_executable` | `true` |
| Blockers | none |
| Policy | `allowed` |
| Identity confidence | `high` |

## Step 3: Approval Packet And Job

The explicit approval packet and pending `drs_migration` job intent were
created as local Gjallar evidence only.

| Field | Value |
| --- | --- |
| Approval packet id | `drsap-b1dafb109b76407cb22329565f0649cc` |
| Packet status | `approved` |
| Job id | `drs-mig-drs-rec-explicit-test-vm-140-yoonmanserver-yoonserver3-d816c0688c8c` |
| Job status | `pending` |
| Runnable | `false` |
| Proxmox mutation enabled | `false` |
| Job side effects | `[]` |

Runtime blockers remain as expected before live execution because live Proxmox
evidence is collected only by the final execute route:

```text
proxmox_active_task_not_collected
proxmox_ha_state_not_collected
proxmox_cluster_quorum_not_collected
```

## Artifacts

| Type | Artifact id | Checksum |
| --- | --- | --- |
| `drs_recommendation_evidence` | `artifact_drs_recommendation_evidence_drs_mig_drs_rec_explicit_test_vm_140_yoonmanserver_yoonserver3_d816c0688c8c_drs_recommendation_evidence` | `sha256:f946d13831ee66eca36aa0492775787d63b0af10a2bee9e4fab8fd06978f1104` |
| `drs_final_precheck` | `artifact_drs_final_precheck_drs_mig_drs_rec_explicit_test_vm_140_yoonmanserver_yoonserver3_d816c0688c8c_drs_final_precheck` | `sha256:7c6e056b04978dbdd34c5ffca67c509145bb704dfc799423533e5828c76d9a13` |
| `drs_approval_packet` | `artifact_drs_approval_packet_drs_mig_drs_rec_explicit_test_vm_140_yoonmanserver_yoonserver3_d816c0688c8c_drs_approval_packet` | `sha256:ae4b96bcfd00f949dc5789bc4f97897758334281f47c1dd633da8346e757790b` |
| `drs_job_intent` | `artifact_drs_job_intent_drs_mig_drs_rec_explicit_test_vm_140_yoonmanserver_yoonserver3_d816c0688c8c_drs_job_intent` | `sha256:169b95d9d06451c3aaa6c3e62b11f60f27c73200e9bf60a6bcb072fa8b664db8` |

## Step 4 Attempt 1: Missing DRS Credentials

Step 4, live DRS migration, was approved and attempted, but it did not execute
because the DRS-specific Proxmox credential environment was not configured:

```text
PROXMOX_DRS_API_URL missing
PROXMOX_DRS_API_TOKEN_ID missing
PROXMOX_DRS_API_TOKEN_SECRET missing
```

The generic Create VM Proxmox credentials were present, but the DRS execution
path intentionally requires the separate `PROXMOX_DRS_*` credential set. The
attempt failed before DRS client creation, live pre-check, operation lock
acquisition, Proxmox migrate request, UPID storage, task polling, or post-check.

Post-attempt local state:

| Field | Value |
| --- | --- |
| Job status | `pending` |
| Proxmox UPID | none |
| Proxmox task node | none |
| Operation lock ids | `[]` |
| Side effects | `[]` |
| Reconciliation events | none |

Live DRS migration still requires a configured DRS credential set or a separate
operator decision to map the existing Proxmox credentials into `PROXMOX_DRS_*`,
then a fresh execute attempt with exact `drs_live_migration_acknowledged=true`.
Missing or failed live evidence, task ambiguity, or post-check mismatch must
remain `needs_reconciliation`.

## Step 4 Attempt 2: Live Precheck Blocked

After operator approval, the existing generic Proxmox credentials were mapped
into the DRS-specific environment for this run:

```text
PROXMOX_DRS_API_URL=$PROXMOX_API_URL
PROXMOX_DRS_API_TOKEN_ID=$PROXMOX_API_TOKEN_ID
PROXMOX_DRS_API_TOKEN_SECRET=$PROXMOX_API_TOKEN_SECRET
PROXMOX_DRS_TLS_INSECURE=$PROXMOX_TLS_INSECURE
```

The execute route performed a fresh final precheck and the Gjallar-side checks
passed:

| Field | Value |
| --- | --- |
| Final precheck status | `would_pass` |
| `would_be_executable` | `true` |
| Final precheck blockers | none |
| Recommendation id | `drs-rec-explicit-test-vm-140-yoonmanserver-yoonserver3` |

The live Proxmox precheck then blocked the operation before operation lock
acquisition and before the Proxmox migrate request:

| Field | Value |
| --- | --- |
| HTTP result | `409 DRS_EXECUTION_LIVE_PRECHECK_BLOCKED` |
| Blocker | `proxmox_target_not_allowed` |
| Proxmox mutation enabled | `false` |
| Side effects | `[]` |
| Job run status | `blocked` |
| Job run stage | `final_precheck` |

Live precheck evidence:

| Check | Status | Evidence |
| --- | --- | --- |
| `proxmox_active_task` | `pass` | active task count `0` |
| `proxmox_cluster_quorum` | `pass` | quorate `1`, nodes `3` |
| `proxmox_ha_state` | `pass` | managed `false`, resources `[]` |
| `proxmox_migration_preconditions` | `failed` | blocker `proxmox_target_not_allowed` |

The Proxmox migration-preconditions evidence included:

```text
allowed_nodes: ["yoonserver3", "yoonmanserver2"]
not_allowed_nodes: ["yoonmanserver2", "yoonserver3"]
running: 1
local_disks: []
local_resources: []
dependent_ha_resources: []
mapped_resource_info_present: true
```

Follow-up raw read-only diagnosis from the Proxmox migration-preconditions API:

```json
{
  "allowed_nodes": ["yoonmanserver2", "yoonserver3"],
  "has-dbus-vmstate": 1,
  "local_disks": [],
  "local_resources": [],
  "mapped-resource-info": {},
  "mapped-resources": [],
  "not_allowed_nodes": {
    "yoonmanserver2": {},
    "yoonserver3": {}
  },
  "running": 1
}
```

Parser conclusion: this is a Gjallar evidence parser issue, not a confirmed
Proxmox migration precondition block for `yoonserver3`. Proxmox can return a
node in both `allowed_nodes` and `not_allowed_nodes`; empty per-node
`not_allowed_nodes` details are autovivified and should not be treated as a
blocking reason. Gjallar must still block non-empty per-node details and must
continue treating legacy list-style `not_allowed_nodes` as blocking because
that shape has no details to inspect.

After the parser fix, the same read-only live precheck passed:

| Field | Value |
| --- | --- |
| Live precheck status | `pass` |
| Blockers | none |
| `not_allowed_nodes_shape` | `object` |
| `not_allowed_nodes_with_blocking_details` | `[]` |
| `not_allowed_node_blocking_details` | `{}` |

Post-attempt local state:

| Field | Value |
| --- | --- |
| Job status | `blocked` |
| Runnable | `false` |
| Runnable blockers | `proxmox_target_not_allowed` |
| Proxmox UPID | none |
| Proxmox task node | none |
| Migration started at | none |
| Migration finished at | none |
| Operation lock ids | `[]` |
| Side effects | `[]` |
| Reconciliation events | none |

No live migration was submitted. The original job remains blocked and should
not be reset. The next live retry requires a fresh approval packet/job and a
fresh exact `drs_live_migration_acknowledged=true` operator acknowledgement.

## Fresh Approval Packet After Parser Fix

After the parser fix and read-only live precheck pass, a fresh explicit test
approval packet/job intent was created locally. This did not submit a Proxmox
migration request.

| Field | Value |
| --- | --- |
| Explicit check | passed |
| `would_be_executable` | `true` |
| Check blockers | none |
| Policy | `allowed` |
| Identity confidence | `high` |
| Approval packet id | `drsap-0a96847e687d4406adaa6362ac1caf40` |
| Packet status | `approved` |
| Job id | `drs-mig-drs-rec-explicit-test-vm-140-yoonmanserver-yoonserver3-33cb1b78addc` |
| Job status | `pending` |
| Runnable | `false` |
| Proxmox mutation enabled | `false` |
| Side effects | `[]` |

Runtime blockers remain expected until the execute route collects live Proxmox
evidence:

```text
proxmox_active_task_not_collected
proxmox_ha_state_not_collected
proxmox_cluster_quorum_not_collected
```

The next step, if approved, is live execution of job
`drs-mig-drs-rec-explicit-test-vm-140-yoonmanserver-yoonserver3-33cb1b78addc`
with exact `drs_live_migration_acknowledged=true`.

## Step 4 Attempt 3: Live Migration Submitted

After exact operator acknowledgement, job
`drs-mig-drs-rec-explicit-test-vm-140-yoonmanserver-yoonserver3-33cb1b78addc`
was executed.

| Field | Value |
| --- | --- |
| Fresh final precheck | passed |
| Live Proxmox precheck | passed |
| Operation locks | acquired |
| Proxmox migrate request | submitted |
| Proxmox UPID | `UPID:yoonmanserver:002E5769:0E52B273:6A1FD43B:qmigrate:140:root@pam!terraform-macbook:` |
| Initial task result | `running` |
| Initial job status | `running` |

The execute route returned while the Proxmox task was still running. Operation
locks remained active at that point, as expected.

Follow-up read-only task evidence showed the migration completed successfully:

| Field | Value |
| --- | --- |
| Task status | `stopped` |
| Task exitstatus | `OK` |
| Task log | `TASK OK` |
| Duration | `00:00:40` |
| Average migration speed | `121.0 MiB/s` |
| Downtime | `13 ms` |
| Source VM status endpoint | config missing on `yoonmanserver` |
| Target VM status endpoint | VMID `140` running on `yoonserver3` |

Relevant task log lines:

```text
migration completed, transferred 3.8 GiB VM-state
migration status: completed
migration finished successfully (duration 00:00:40)
TASK OK
```

## Post-Check Reconciliation

Gjallar direct post-check found the VM on the target node and running, but did
not mark the DRS job completed because the identity fingerprint changed:

| Field | Value |
| --- | --- |
| Job status | `needs_reconciliation` |
| Task result | `ok` |
| Task status | `stopped` |
| Task exitstatus | `OK` |
| Post-check status | `needs_reconciliation` |
| Reconciliation reason | `fingerprint_mismatch` |
| Reconciliation event | `drsrec-6fbf1efbadcd44b18f487983d4c71b54` |
| Operation locks | `reconciliation_required` |

Post-check passed these direct observations:

```text
vm_exists: pass on yoonserver3
vm_config: pass on yoonserver3
active_tasks: pass, count 0 on yoonmanserver and yoonserver3
power_state: running
```

Fingerprint evidence:

| Field | Value |
| --- | --- |
| Expected stable fingerprint | `sha256:4f1ca5614e2cf5dcaf9d711c9caedc73cdd5d8dabd2b016196a4730781d8a251` |
| Observed stable fingerprint | `sha256:63bc641b57ff2fea13fb01f08662d4c7aab3173a111b25da9a2d319e07adeb84` |
| Observed `smbios1_uuid` | `5db28321-b419-4a98-91d1-9935bdd4f10d` |
| Observed `vmgenid` | `a6c29a6e-c035-4b6c-97ce-679b02efd4da` |
| Observed MAC | `bc:24:11:77:88:75` |
| Observed disk volumes | `nas-server:140/vm-140-cloudinit.qcow2`, `nas-server:140/vm-140-disk-0.qcow2` |

This is not a Proxmox migration failure. The live migration succeeded, but
Gjallar identity reconciliation needs follow-up before the DRS job can be
considered fully completed and before the reconciliation-required locks should
be released.

## Root Cause: Cloud-Init Cdrom Fingerprint Inclusion

Expected DRS fingerprint components before migration included only the VM's
identity disk:

```text
disk_volume_ids: ["nas-server:140/vm-140-disk-0.qcow2"]
```

The direct post-check parser in `backend/app/drs/execution.py` was reading raw
target-node config values and included the cloud-init cdrom volume:

```text
disk_volume_ids: [
  "nas-server:140/vm-140-cloudinit.qcow2",
  "nas-server:140/vm-140-disk-0.qcow2"
]
```

Inventory identity extraction already skips config entries with `media=cdrom`.
The direct post-check path now applies the same identity disk-volume
normalization and also skips cloud-init volume names. SMBIOS UUID, VMGenID, MAC,
and non-cloud-init disk volume matching remain required; this only removes a
non-identity cdrom/cloud-init config entry from the disk identity set.

## Local Follow-Up Parser-Fix Conclusion

The VMID `140` result should be treated as:

- Proxmox technical result: migration task `OK`; VM running on `yoonserver3`.
- Gjallar local result before parser fix: `needs_reconciliation` due to
  `fingerprint_mismatch`.
- Gjallar parser conclusion: mismatch was caused by direct post-check
  cloud-init cdrom inclusion, not by SMBIOS, VMGenID, MAC, or identity disk
  drift.

The narrow local follow-up endpoint is:

```http
POST /api/v1/drs/migration-jobs/{job_id}/reconcile
{
  "drs_reconciliation_acknowledged": true
}
```

This route is operator-only, requires exact boolean acknowledgement before
inventory/client/DB work, polls the stored UPID, collects direct post-check
evidence, and updates only local Gjallar job, lock, artifact, Jobs/Runs, and
reconciliation-event state. It does not call `migrate_vm`, does not create a
new approval packet or job, and does not perform corrective Proxmox mutation.

DRS authority split for this case:

- Proxmox precondition/task evidence is the technical authority for migration
  feasibility and task completion.
- Gjallar policy, identity/fingerprint, audit artifacts, operation locks,
  approval/job binding, and reconciliation status are the DRS authority for
  local completion.
- Advisor route/storage/passthrough/network evidence is advisory/pre-filter
  evidence and is not the final technical authority once Proxmox preconditions
  and task evidence are available.

## Final Local Reconciliation Completion

After the direct post-check parser fix, the stored-UPID reconciliation follow-up
route was run for job
`drs-mig-drs-rec-explicit-test-vm-140-yoonmanserver-yoonserver3-33cb1b78addc`.
This did not call `migrate_vm`, did not create a new approval packet/job, and
did not perform corrective Proxmox mutation.

| Field | Value |
| --- | --- |
| Route | `POST /api/v1/drs/migration-jobs/{job_id}/reconcile` |
| Acknowledgement | `drs_reconciliation_acknowledged=true` |
| Job status | `completed` |
| Task result | `ok` |
| Task status | `stopped` |
| Task exitstatus | `OK` |
| Post-check status | `completed` |
| Reconciliation reason | none |
| Reconciliation event | `drsrec-6fbf1efbadcd44b18f487983d4c71b54` resolved |
| Operation locks | released |
| Execution artifact checksum | `sha256:a206f3cb7fd8ad4fe636396b98e6741b0715810320d3bec32dae4a85f40eaf0d` |

Final post-check fingerprint evidence:

| Field | Value |
| --- | --- |
| Expected stable fingerprint | `sha256:4f1ca5614e2cf5dcaf9d711c9caedc73cdd5d8dabd2b016196a4730781d8a251` |
| Observed stable fingerprint | `sha256:4f1ca5614e2cf5dcaf9d711c9caedc73cdd5d8dabd2b016196a4730781d8a251` |
| Observed disk volumes | `nas-server:140/vm-140-disk-0.qcow2` |
| Post-check blockers | none |

Final result: VMID `140` live migration completed on Proxmox and the Gjallar
DRS job was locally completed with verified post-check evidence and released
operation locks.
