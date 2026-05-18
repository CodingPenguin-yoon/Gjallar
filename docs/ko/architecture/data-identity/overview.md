# Data And Identity Overview

> 이 한국어 문서는 설명용입니다. canonical truth는 active code/tests와 영어 기준 문서입니다.

기준 문서: [영어 Data and Identity overview](../../../architecture/data-identity/overview.md), [DRS data/identity product doc](../../../product/drs-advisor/03_DATA_DB_AND_IDENTITY.md), [Current implemented state](../../../current/README.md).

이 문서는 Proxmox actual state와 Gjallar-owned operational data의 경계를 설명합니다.

## Proxmox vs Gjallar boundary

| Data kind | Current source of truth |
|---|---|
| Actual VM existence/location/power | Proxmox |
| Actual node status/load | Proxmox inventory adapter |
| Actual storage/network inventory | Proxmox inventory adapter |
| Create VM intent | Gjallar DB request record |
| Create VM approval evidence | Gjallar DB artifacts/job details |
| Networks readiness | No Gjallar persistence; frontend-composed read-only evidence |
| Jobs/Runs | Gjallar DB job records |
| Risks/Alerts | Gjallar job risks projection |
| DRS identity/fingerprint/policy | Target future Gjallar DB, not implemented |

## Current Gjallar-owned persistence

Job status and artifacts live in `job_runs` and `job_artifacts`. Native Create VM request/result and created VM summaries live in `vm_create_requests` and `vm_instances`. Networks readiness has no persistence.

Writers redact secrets before persistence.

## Current Create VM fingerprint

Native create writes an `observed_after` DB artifact with fingerprint hash from `smbios1`, `vmgenid`, MAC addresses, and disk volume ids. For native Create VM-created VMs this evidence is also copied into `vm_instances`, but it is not yet a generalized DRS identity layer.

## VMID locator rule

VMID alone is not a durable Gjallar identity. DRS target must combine VMID with cluster, current source node, VM name/metadata, fingerprint evidence, last observed time, policy classification. A stale locator must block migration until refreshed and matched.

## Target DB/identity gap

DRS target needs generalized VM identity, Proxmox locator, fingerprint assertion, classification metadata, placement policy, approval record, operation lock, operation/reconciliation records. Current code only has the Create VM-created VM slice in DB, not DRS DB tables.
