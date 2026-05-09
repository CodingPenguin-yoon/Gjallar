# Set 4 completion — Minimum job/artifact substrate

Completed: 2026-05-09 02:16 KST
Project: Gjallar
Repo: `codex-vm:/home/yoon/projects/Gjallar`
Branch: `rewrite/prd-v1-mvp`

## Goal

Preflight/plan/approval 이전에 job, approval, artifact 모델과 실제 파일/checksum 저장소를 최소 GREEN으로 만든다.

## TDD evidence

### RED

Command:

```bash
ssh codex-vm 'cd /home/yoon/projects/Gjallar && PYTHONPATH=backend backend/.venv/bin/python -m unittest backend/tests/jobs/test_artifact_store.py backend/tests/jobs/test_job_models.py'
```

Observed after fixing the test syntax draft:

```text
FAILED (failures=3)
No module named 'app.jobs'
```

The failures were expected because `app.jobs` did not exist yet.

### GREEN

Focused Set 4 command:

```bash
ssh codex-vm 'cd /home/yoon/projects/Gjallar && PYTHONPATH=backend backend/.venv/bin/python -m unittest backend/tests/jobs/test_artifact_store.py backend/tests/jobs/test_job_models.py'
```

Result:

```text
Ran 3 tests in 0.006s
OK
```

Set 3 + Set 4 focused regression command:

```bash
ssh codex-vm 'cd /home/yoon/projects/Gjallar && PYTHONPATH=backend backend/.venv/bin/python -m unittest backend/tests/contracts/test_api_v1_shape.py backend/tests/manifests/test_profile_schema.py backend/tests/manifests/test_network_profile.py backend/tests/manifests/test_secret_redaction.py backend/tests/jobs/test_artifact_store.py backend/tests/jobs/test_job_models.py'
```

Result:

```text
Ran 11 tests in 0.551s
OK
```

`git diff --check`: PASS.

Backend pytest command remains blocked as previously documented:

```text
/home/yoon/projects/Gjallar/backend/.venv/bin/python: No module named pytest
```

## Implemented

Remote files added:

```text
backend/app/jobs/__init__.py
backend/app/jobs/artifacts.py
backend/app/jobs/models.py
backend/tests/jobs/__init__.py
backend/tests/jobs/test_artifact_store.py
backend/tests/jobs/test_job_models.py
```

Remote shared-doc snapshot refreshed:

```text
artifacts/rewrite-baseline/20260509-004801-KST/shared-docs-set4/
```

Behavior now covered:

- `JobRecord`, `ArtifactRecord`, `ApprovalRecord` expose PRD Set 4 fields.
- JSON/text artifact writers write real files under a caller-provided run directory.
- Artifact checksums are real `sha256:<hex>` values computed from stored bytes.
- Artifact payload serialization calls `redact_secrets`; focused test verifies raw secret-like fixture values and credentialed URL password text are not persisted.
- Approval record carries `plan_artifact_id` and `review_summary_checksum` references.

## Repo status after Set 4

```text
## rewrite/prd-v1-mvp
 M backend/app/main.py
?? artifacts/
?? backend/app/api/
?? backend/app/core/
?? backend/app/jobs/
?? backend/app/manifests/
?? backend/tests/contracts/
?? backend/tests/jobs/
?? backend/tests/manifests/
?? backend/tests/vm_create/
?? frontend/tests/createVmDefaults.test.mjs
?? frontend/tests/reviewSummary.test.mjs
?? frontend/tests/riskPolicy.test.mjs
```

No commit, push, delete, Terraform apply, Proxmox write, VM create, or power action was run.

## Remaining intentional RED / deferred

- Backend pytest still unavailable until dependency recovery is performed.
- Existing Set 2 later-slice tests for forbidden legacy route cutover, `vm_create`, preflight policy, and frontend utilities remain deferred to later Sets.
- Set 5 should start read-only Proxmox inventory adapter work using fake/read-only fixtures only; no create/apply/delete/power action.
