# Create VM Live Smoke Result - 2026-05-28

Status: complete.

This records the approved live Create VM smoke run for Goal 1. The run used the
active `/api/v1/vm-create/{draft_id}/proxmox-create` path and did not use legacy
Terraform execute/archive routes.

## Approved Target

| Field | Value |
| --- | --- |
| Code revision under test | `ba1e554 feat: add create vm evidence helper` |
| Proxmox API / cluster | `.env` `PROXMOX_API_URL`; value redacted |
| Target node | `yoonserver3` |
| Template | `yoonmanserver / VMID 118 / ubuntu-templte` |
| Storage | `nas-server` |
| Bridge | `vmbr0` |
| Static network | `192.168.2.140-150/24`, gateway `192.168.2.1` |
| SSH/cloud-init user | `yoon` |
| Operator | `yoon / admin` |
| Cleanup policy | Do not delete smoke VMs; leave final state `stopped` |

Preflight inventory confirmed `nas-server` is visible on `yoonserver3`,
`vmbr0` is active on `192.168.2.0/24`, and the selected Ubuntu template has
cloud-init and guest-agent readiness evidence.

## Non-Live Gates

Validation before live mutation:

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests/contracts backend/tests/vm_create backend/tests/proxmox
node --test frontend/tests/createVmFlow.test.mjs
git diff --check
```

Result: backend `170 passed, 33 warnings, 26 subtests passed`; frontend
`createVmFlow` passed; `git diff --check` passed.

Negative gate:

| Field | Value |
| --- | --- |
| Job id | `gjallar-smoke-negative-auth-20260528T030003Z` |
| Request | Same target as above, invalid bridge `vmbr-does-not-exist`, `192.168.2.143/24` |
| Endpoints | `preflight` HTTP 200, `plan` HTTP 200 |
| Result | job `blocked`, risk `red`, code `bridge_missing_or_inactive` |
| Mutation | No approve/create mutation sent; `side_effects=[]` |
| Request/VM rows | None expected for blocked pre-mutation gate |

## Live Matrix

| Case | Job id | VMID / name | Requested network | Power policy | HTTP result | Risk | Observed result | Cleanup |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Default stopped | `gjallar-smoke-stopped-20260528T020426Z` | `137 / gjallar-vm-gjallar-smoke-stopped-20260528t020426z` | `192.168.2.140/24`, gateway `192.168.2.1` | `stopped` | preflight 200, plan 200, approve 200, create 200 | `green`, no codes | VM exists on `yoonserver3`, status `stopped`, post-check `completed`, fingerprint `sha256:4ca4ce6975ebc6b1d37c8245e9dae784f560f6bd9593bcf5e91492b6c3a7518f` | Left stopped |
| Boot and verify | `gjallar-smoke-boot-verify-20260528T021815Z` | `138 / gjallar-vm-gjallar-smoke-boot-verify-20260528t021815z` | `192.168.2.141/24`, gateway `192.168.2.1` | `boot_and_verify` | preflight 200, plan 200, approve 200, create 200 | `green`, no codes | VM reached `running`; guest-agent observed `192.168.2.141`; cloud-init `done`; boot checks passed | Shutdown after verification; final Proxmox status `stopped`; fallback stop not used |
| Static IP stopped | `gjallar-smoke-static-20260528T024539Z` | `139 / gjallar-vm-gjallar-smoke-static-20260528t024539z` | `192.168.2.142/24`, gateway `192.168.2.1` | `stopped` | preflight 200, plan 200, approve 200, create 200 | `green`, no codes | VM exists on `yoonserver3`, status `stopped`, post-check `completed`, fingerprint `sha256:fbe2f3e6f8e9f951a4e0a9ca34f01fbbfcadf8b5ac2dba62540a4137840ed62e` | Left stopped |

Config spot-checks from observed create evidence:

| VMID | `ipconfig0` | `net0` bridge | `ciuser` |
| --- | --- | --- | --- |
| `137` | `ip=192.168.2.140/24,gw=192.168.2.1` | `vmbr0` | `yoon` |
| `138` | `ip=192.168.2.141/24,gw=192.168.2.1` | `vmbr0` | `yoon` |
| `139` | `ip=192.168.2.142/24,gw=192.168.2.1` | `vmbr0` | `yoon` |

Actor evidence for successful Create VM request rows recorded
`actor_username=yoon` and `actor_role=admin`. Internal actor user ids are
present in the DB evidence and intentionally omitted from this document.

## Artifact Evidence

Artifact paths use `db://job-artifacts/<artifact_id>`. The raw artifact content
remains in the DB; this document records safe ids and checksums only.

| Case | Type | Artifact id | Checksum |
| --- | --- | --- | --- |
| Negative gate | `job_status` | `artifact_job_status_gjallar_smoke_negative_auth_20260528T030003Z_job_status` | `sha256:fc3ba1238442b1e38758d10105007542fa5d4aa8750f5a28d6b48467aef58cee` |
| Negative gate | `preflight_report` | `artifact_preflight_report_gjallar_smoke_negative_auth_20260528T030003Z_preflight_report` | `sha256:3f6df0a1704f44d2a2aabc515f91a1d736bf0eb6cb296d121421257631c1b9e5` |
| Negative gate | `vm_instance_manifest` | `artifact_vm_instance_manifest_gjallar_smoke_negative_auth_20260528T030003Z_vm_instance_manifest` | `sha256:2488365f9409882039510f1dd889c956d31d44dea3ea5739b8728e003d78870f` |
| Negative gate | `planned_git_diff` | `artifact_planned_git_diff_gjallar_smoke_negative_auth_20260528T030003Z_planned_git_diff` | `sha256:46527c134604eff071178f33e9845b77567ef16662a4f5c85b0ca1fc6837b83e` |
| Negative gate | `plan` | `artifact_plan_gjallar_smoke_negative_auth_20260528T030003Z_plan` | `sha256:9ec7d7d5cb85ac5fd5f324671231a9887424bed7f027acd044ddd176cd44ec6a` |
| Negative gate | `review_summary` | `artifact_review_summary_gjallar_smoke_negative_auth_20260528T030003Z_review_summary` | `sha256:0b522c756af191ca8bfa563328574fda97c55db5b109930b744a2d46cab7f37c` |
| Default stopped | `job_status` | `artifact_job_status_gjallar_smoke_stopped_20260528T020426Z_job_status` | `sha256:633d2197e793571b47ab771154ffe8fae091d0bfb3e830f8e15522a37260c174` |
| Default stopped | `preflight_report` | `artifact_preflight_report_gjallar_smoke_stopped_20260528T020426Z_preflight_report` | `sha256:1abdfa36d4a725d848fb9532d81f4160b707d0f61bae587c0fd4280b51ad0406` |
| Default stopped | `vm_instance_manifest` | `artifact_vm_instance_manifest_gjallar_smoke_stopped_20260528T020426Z_vm_instance_manifest` | `sha256:bac8198de2f58346b153f31f85fb716b80f34a5a470791408e2ad0b96e4be665` |
| Default stopped | `planned_git_diff` | `artifact_planned_git_diff_gjallar_smoke_stopped_20260528T020426Z_planned_git_diff` | `sha256:c6e65fc48e501f679b4802671de6744574bab7b91b212cacc9ec5aa2ed71b3ef` |
| Default stopped | `plan` | `artifact_plan_gjallar_smoke_stopped_20260528T020426Z_plan` | `sha256:39ef8f0cb7aee4fd89d40ffa57f2d09eec62a2f23fe8a82945fdfd6327e8cd4a` |
| Default stopped | `review_summary` | `artifact_review_summary_gjallar_smoke_stopped_20260528T020426Z_review_summary` | `sha256:4d6a356a30fda7a6117233c26ecd5004ba6109edb50809e1b7982c7f6c5329dc` |
| Default stopped | `approval` | `artifact_approval_gjallar_smoke_stopped_20260528T020426Z_approval` | `sha256:7fa41e73aba9fe2db23ffb5eb4870f94b07d0b02bc6fddc24098ea64dfc88070` |
| Default stopped | `proxmox_create_preview` | `artifact_proxmox_create_preview_gjallar_smoke_stopped_20260528T020426Z_proxmox_create_preview` | `sha256:e0669d167a11d309b9915237f20c414056c65fc03de6867699fa01d417db227d` |
| Default stopped | `observed_after` | `artifact_observed_after_gjallar_smoke_stopped_20260528T020426Z_observed_after` | `sha256:96ce12b3f79931e734d597f45211a31049f0e8a35cdc71d3e0d48622c06fecc7` |
| Boot and verify | `job_status` | `artifact_job_status_gjallar_smoke_boot_verify_20260528T021815Z_job_status` | `sha256:977a861affdaff11c54f183593ade3a611c49e41f803b017c88abaa3cb8dd641` |
| Boot and verify | `preflight_report` | `artifact_preflight_report_gjallar_smoke_boot_verify_20260528T021815Z_preflight_report` | `sha256:5f152b7e4b82e1c90ed75d3df9c251c141e2cd44db2cb43ae0b435f0bfe7d28e` |
| Boot and verify | `vm_instance_manifest` | `artifact_vm_instance_manifest_gjallar_smoke_boot_verify_20260528T021815Z_vm_instance_manifest` | `sha256:9df2241417850d753a4d7cc64ba1d26598b5a14dea1f6639f93afdc72af8f694` |
| Boot and verify | `planned_git_diff` | `artifact_planned_git_diff_gjallar_smoke_boot_verify_20260528T021815Z_planned_git_diff` | `sha256:dfcdb117b20fda2448df97d10a85e0807fefc724219f2cfe78cb373e50c1089a` |
| Boot and verify | `plan` | `artifact_plan_gjallar_smoke_boot_verify_20260528T021815Z_plan` | `sha256:d29b9c10664e0c15b1199e5e67de871378fcbd502307dbe38846a5d95a076e88` |
| Boot and verify | `review_summary` | `artifact_review_summary_gjallar_smoke_boot_verify_20260528T021815Z_review_summary` | `sha256:b7fe8d98cd6c6b3a85c138e50240a2b8ea6abe0a5955534432aa36a025fab5ba` |
| Boot and verify | `approval` | `artifact_approval_gjallar_smoke_boot_verify_20260528T021815Z_approval` | `sha256:e01742886e2cafd1c24ba71faac7b51e3a0552f943fb456fc620e169abbca92b` |
| Boot and verify | `proxmox_create_preview` | `artifact_proxmox_create_preview_gjallar_smoke_boot_verify_20260528T021815Z_proxmox_create_preview` | `sha256:b3b5a9046dc58c35bacded9633ceff36cff5f8c1910a2b40a9e026811798d616` |
| Boot and verify | `observed_after` | `artifact_observed_after_gjallar_smoke_boot_verify_20260528T021815Z_observed_after` | `sha256:648764c30a8ddd243e8887fef460f9d8f1c6d5a794705c95ed5a222db8d05b3d` |
| Static IP stopped | `job_status` | `artifact_job_status_gjallar_smoke_static_20260528T024539Z_job_status` | `sha256:b49a4a7d24431bc9f4e2de1e17f00756b84b6295f9cba53df38163e030458167` |
| Static IP stopped | `preflight_report` | `artifact_preflight_report_gjallar_smoke_static_20260528T024539Z_preflight_report` | `sha256:8df964c2da636df0f5ca13ebc116ac88846afcd502f8aaf1bfca1df31b17b0ae` |
| Static IP stopped | `vm_instance_manifest` | `artifact_vm_instance_manifest_gjallar_smoke_static_20260528T024539Z_vm_instance_manifest` | `sha256:308344f67213bbad9518722556e359457c8e05188ef3bbe8fc6d883073b07e3a` |
| Static IP stopped | `planned_git_diff` | `artifact_planned_git_diff_gjallar_smoke_static_20260528T024539Z_planned_git_diff` | `sha256:853e5e111219f9a28e6d4b91ace8a8857a9232bc09c244ad3d1a8987cbec92e2` |
| Static IP stopped | `plan` | `artifact_plan_gjallar_smoke_static_20260528T024539Z_plan` | `sha256:7cebc4cd56fd31ca7d89220edc943a345b222e62f12a67c5d045af5cbc0e98ff` |
| Static IP stopped | `review_summary` | `artifact_review_summary_gjallar_smoke_static_20260528T024539Z_review_summary` | `sha256:f6c25cb80ffc3a272029012a3c7e722a68b34f45ae8ae6e3b4fd2d570e7b3f32` |
| Static IP stopped | `approval` | `artifact_approval_gjallar_smoke_static_20260528T024539Z_approval` | `sha256:5cbce2263f068ec2c7cee209bc8093a37b28b0951ef5423f4fd94af12777398d` |
| Static IP stopped | `proxmox_create_preview` | `artifact_proxmox_create_preview_gjallar_smoke_static_20260528T024539Z_proxmox_create_preview` | `sha256:df22d77d386e9f0fe160a34bdce1c630f4c3ba98a94da3e13900deb4c909c2a4` |
| Static IP stopped | `observed_after` | `artifact_observed_after_gjallar_smoke_static_20260528T024539Z_observed_after` | `sha256:aacf61dd110b9ef2436c922488ad6c890f24120b7364dbfd00131590ec59df56` |

Proxmox task evidence is stored in the DB artifacts. In the sanitized summary,
each successful live case has clone task exitstatus `OK`, resize
`not_needed` because requested disk size matched the template, config update
side effects, and post-check observation. The `boot_and_verify` case also has
start task exitstatus `OK`, guest-agent observation, and cloud-init status
check evidence.

## Notes And Remaining Risk

- The smoke VMs were intentionally not deleted. Final Proxmox status is
  `stopped` for VMIDs `137`, `138`, and `139`.
- The `boot_and_verify` DB `vm_instances` row records the immediate create
  result as `running`; the approved cleanup then shut the VM down and verified
  final Proxmox status `stopped`.
- A helper-script retry, `gjallar-smoke-static-20260528T024413Z`, was blocked
  before mutation because the approve/create payload omitted the original VM
  request fields. It returned HTTP 409 with `side_effects=[]` and is not counted
  as a successful smoke case.
- SSH login, Ansible, app bootstrap, background reconciliation, and DRS
  identity registration remain out of scope for Create VM success.
- Networks readiness still does not act as the Create VM static range source of
  truth; the active gate is selected bridge presence plus explicit static IP,
  prefix, and gateway validation.
