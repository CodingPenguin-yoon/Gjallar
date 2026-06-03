# Create VM Live Smoke Result - 2026-06-01

Status: complete.

This records the approved live Create VM run used to prepare a test VM for a
future DRS live migration smoke. The run used the active
`/api/v1/vm-create/{draft_id}/proxmox-create` path. It did not execute DRS
migration, cleanup, delete, corrective reconciliation, or any automatic DRS
action.

## Approved Target

| Field | Value |
| --- | --- |
| Code revision under test | `a7e3355 Harden DRS migration execute acknowledgement` |
| Proxmox API / cluster | `.env` `PROXMOX_API_URL`; value redacted |
| Purpose | Create a test VM for a later, separately approved DRS migration smoke |
| Target node | `yoonmanserver` |
| Template | `yoonmanserver / VMID 118 / ubuntu-templte` |
| Storage | `nas-server` |
| Bridge | `vmbr0` |
| Static network | `192.168.2.143/24`, gateway `192.168.2.1` |
| SSH/cloud-init user | `yoon` |
| Operator | `yoon / admin` |
| Power policy | `boot_and_verify` |
| Cleanup policy | No cleanup approved in this run; leave final state `running` |

Preflight inventory confirmed three online nodes, selected the Ubuntu template
on `yoonmanserver`, found `vmbr0` active, and proposed VMID `140`. Existing
guard-range smoke VMs `137`, `138`, and `139` were observed as stopped; no
running VM occupied `192.168.2.143/24`.

## Non-Live Gates

Validation before live mutation:

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests/contracts backend/tests/vm_create backend/tests/proxmox
node --test frontend/tests/createVmFlow.test.mjs
git diff --check
```

Result: backend `187 passed, 47 warnings, 34 subtests passed`; frontend
`createVmFlow` passed; `git diff --check` passed.

Non-mutating draft/preflight/plan/approval/preview result:

| Field | Value |
| --- | --- |
| Draft id | `drs-test-vm-create-20260601T045853Z` |
| Job id | `job-drs-test-vm-create-20260601T045853Z` |
| Proposed VMID | `140` |
| Risk | `green`, no red/yellow codes |
| Review checksum | `sha256:f26a9784f0a3cf983dad0e33d2f82ebc481ec6062bffaf0be5883ab516c2aff4` |
| Plan artifact | `artifact_plan_job_drs_test_vm_create_20260601T045853Z_plan` |
| Preview mode | `proxmox_native_preview_no_mutation` |
| Preview side effects | `[]` |

## Live Result

| Field | Value |
| --- | --- |
| Endpoint path | `/api/v1/vm-create/{draft_id}/proxmox-create` |
| Result | success / completed |
| VMID / name | `140 / gjallar-vm-job-drs-test-vm-create-20260601t045853z` |
| Target node | `yoonmanserver` |
| Requested network | `192.168.2.143/24`, gateway `192.168.2.1` |
| Observed status | `running` |
| Observed primary IP | `192.168.2.143` |
| Post-check | `completed` |
| Fingerprint | `sha256:6e9de519798185ef6f5c31d4c94d1c57763e7c312b5d3486230ec2d24aa6f139` |
| Clone task | exitstatus `OK` |
| Start task | exitstatus `OK` |
| Resize | `not_needed`, `requested_not_larger_than_current` |
| Observed at | `2026-06-01T05:29:40Z` |

Boot verification checks:

| Check | Result |
| --- | --- |
| running | `true` |
| guest-agent available | `true` |
| IP observed | `true` |
| cloud-init completed | `true` |

Config spot-checks from observed create evidence:

| Field | Value |
| --- | --- |
| `ipconfig0` | `ip=192.168.2.143/24,gw=192.168.2.1` |
| `net0` | `virtio=BC:24:11:77:88:75,bridge=vmbr0` |
| `ciuser` | `yoon` |
| `scsi0` | `nas-server:140/vm-140-disk-0.qcow2,iothread=1,size=50G` |
| `ide2` | `nas-server:140/vm-140-cloudinit.qcow2,media=cdrom,size=4M` |

The successful Create VM request and VM instance rows are present. Actor
evidence recorded `actor_username=yoon` and `actor_role=admin`; internal actor
ids are intentionally omitted from this document.

## Artifact Evidence

Artifact paths use `db://job-artifacts/<artifact_id>`. The raw artifact content
remains in the DB; this document records safe ids and checksums only.

| Type | Artifact id | Checksum |
| --- | --- | --- |
| `job_status` | `artifact_job_status_job_drs_test_vm_create_20260601T045853Z_job_status` | `sha256:808477ef9c091cb6c7d8bc1421435c582ddee1f8febd8e0be417b90d5ff5e616` |
| `preflight_report` | `artifact_preflight_report_job_drs_test_vm_create_20260601T045853Z_preflight_report` | `sha256:6e59fd1d8c372c90bab23751a4db2230934e64281663f392fc415d4608fa3608` |
| `vm_instance_manifest` | `artifact_vm_instance_manifest_job_drs_test_vm_create_20260601T045853Z_vm_instance_manifest` | `sha256:16fb8b2ac24fabd9d78a5b270828939a9946cd00b08a0b61b2b141141519f3d8` |
| `planned_git_diff` | `artifact_planned_git_diff_job_drs_test_vm_create_20260601T045853Z_planned_git_diff` | `sha256:b28de73d7685187e73ee2e785b775b96eba23ab62bea78e62abafc9a03330e27` |
| `plan` | `artifact_plan_job_drs_test_vm_create_20260601T045853Z_plan` | `sha256:4bcceac34106fb6794b98857c944aaa2378fea561382162839bc4d491827ef95` |
| `review_summary` | `artifact_review_summary_job_drs_test_vm_create_20260601T045853Z_review_summary` | `sha256:f26a9784f0a3cf983dad0e33d2f82ebc481ec6062bffaf0be5883ab516c2aff4` |
| `approval` | `artifact_approval_job_drs_test_vm_create_20260601T045853Z_approval` | `sha256:2af93f04e6b5e24f23fb371e42a1068f21e0e39cc0acea59d1e8b08adac2e37a` |
| `proxmox_create_preview` | `artifact_proxmox_create_preview_job_drs_test_vm_create_20260601T045853Z_proxmox_create_preview` | `sha256:4656449b6c0e3eacab8f87cb90b7213c97da13e2474f06f8dd50b672c85f24dd` |
| `observed_after` | `artifact_observed_after_job_drs_test_vm_create_20260601T045853Z_observed_after` | `sha256:2ea6280203041eed45367a458cbf1b15f5d9f98215e060efc869c14d7f66bb65` |

Recorded side effects:

```text
proxmox_clone_invoked
proxmox_task_polled
proxmox_disk_resize_not_needed
proxmox_config_updated
proxmox_post_check_observed
proxmox_start_invoked
proxmox_start_task_polled
proxmox_boot_post_check_observed
proxmox_guest_agent_observed
proxmox_cloud_init_status_checked
```

## Notes And Remaining Risk

- VMID `140` was intentionally left `running`; shutdown/delete/cleanup was not
  approved or executed in this run.
- This run created a candidate VM for later DRS testing only. It is not DRS
  migration evidence and does not close the live DRS smoke gap.
- Any live DRS migration still requires separate active-session approval with
  exact `drs_live_migration_acknowledged=true`.
- The command observed one transient guest-agent `exec-status` HTTP 500 for an
  invalid `pid` during cloud-init polling, then retried successfully; final
  cloud-init status was `done`.
