# Gjallar Codebase Rewrite Execution Plan

> Historical planning note: this execution plan preserves rewrite-era working assumptions and may mention legacy endpoint names or parked flows. Treat `doc/status/current.md` and `doc/operations/runbook.md` as the current repo-local state.

> 작성: 2026-05-09 00:04 KST  
> 기준 문서: `/mnt/hermes_data/프로젝트/Gjallar/PRD/`  
> 실행 원칙: PRD → contract/schema test → 구현 → fresh review

## 0. 결론

준비됐다. 다만 바로 대규모 삭제부터 하지 않는다.

이번 작업은 **기존 코드를 보존 전제로 리팩터링하는 작업이 아니라, PRD 기준 새 `/api/v1` + 새 화면/도메인 구조를 세우고 기존 구현에서 검증된 일부만 가져오는 재작성**으로 간다.

첫 구현 단위는 PRD의 `21_MVP_IMPLEMENTATION_HANDOFF.md` 기준으로 다음 흐름이다.

```text
repo/code inventory
→ contract/schema tests
→ minimum job/artifact substrate
→ read-only inventory API
→ create draft / preflight / plan
→ Review & Confirm
→ GitOps guard
→ Terraform/Proxmox apply powered-off
→ first power on + Stage A smoke
→ UI/artifact expansion
```

## 1. 확인한 기준

### 1.1 공용 PRD 핵심

- Gjallar = **Proxmox를 VMware처럼 쓰게 해주는 VM/인프라 운영 콘솔**.
- 제품 중심은 Terraform/Ansible 실행기가 아니라 **사람이 이해하고 승인하는 VM/노드/리스크/작업 화면**.
- MVP 실제 생성 profile은 `general-vm` 하나.
- 첫 생성 flow는 `draft → preflight → plan → Review & Confirm → commit/push guard → apply powered-off → first power on → smoke`.
- MVP 제외: VM 삭제, snapshot/rollback, hard stop/reset/kill, 기존 VM 독립 power action, Runtime Target write/active, 앱 deploy/DB migration/임의 shell.
- red risk는 승인으로도 우회 불가. yellow risk는 명시 ack 필요.
- secret 원문은 Git/DB/artifact/log/UI/API에 남기지 않는다.

### 1.2 현재 repo 상태 요약

대상 repo:

```text
codex VM: yoon@192.168.2.82:/home/yoon/projects/Gjallar
branch: main...origin/main
latest: 29412e8 feat: extend operational risk assurance controls
working tree: clean
tracked files: 144
backend tracked files: 69
frontend tracked files: 40
infra tracked files: 5
```

현재 구조는 PRD와 충돌하는 legacy가 많다.

- Backend route base가 `/api`이며 PRD 기준 `/api/v1`이 아님.
- 기존 route 예: `/provision`, `/deploy`, `/instances/terminate`, `/instances/action`, `/instances/resources`, `/llm/*`.
- Frontend도 `/provision`, instance lifecycle, LLM chat, old monitoring/risk 중심.
- Alembic migration에 GitLab/staging/project setup 계열 legacy가 남아 있음.
- 기존 Proxmox read-only inventory/risk/guest-agent/IP 조회 경험은 일부 Keep 후보.
- 기존 deploy/provision/destructive/LLM/app-staging 성격 코드는 Drop 또는 Park 후보.

### 1.3 확인된 실행 환경 이슈

- `frontend/tests/*.mjs`는 Node 22에서 통과.
- backend pytest는 현재 venv에 `pytest`가 없어 실행 불가.
- Codex VM에는 `/mnt/hermes_data`가 마운트되어 있지 않음.
- Hermes host에서 `/mnt/hermes_data/IaC`가 현재 보이지 않음.

따라서 초기 구현은 가능하지만, **Slice 6 GitOps guard 이후는 IaC repo 위치/마운트 정리가 선행되어야 한다.**

## 2. 비파괴 안전 원칙

1. `main`에 직접 작업하지 않는다. 새 branch에서 시작한다.
2. 대규모 삭제 전 반드시 백업 산출물을 만든다.
   - `git status --short --branch`
   - tracked diff/stat
   - untracked 목록/압축
   - 현재 route/test inventory
3. destructive endpoint는 새 API에 만들지 않는다.
4. 기존 destructive endpoint는 새 `/api/v1` cutover 전까지 사용하지 않고, 제거/비활성화는 테스트로 고정한 뒤 한다.
5. commit/push/delete/apply는 사용자 승인 대상이다.
6. 코드는 TDD로만 간다. production code 전에 실패 테스트가 먼저 있어야 한다.

## 3. 재작성 방식

### 방식: Clean-room core + selective salvage

기존 코드를 한 번에 `rm -rf`하지 않고 아래 방식으로 간다.

```text
1. 새 PRD 기준 package/route/test skeleton 생성
2. `/api/v1` contract/schema test 작성
3. 새 구현을 통과시킴
4. 기존 router/UI를 새 entrypoint에서 분리
5. Keep 후보만 테스트와 함께 이식
6. Drop/Park 항목은 백업 후 제거
```

이 방식이 좋은 이유:

- PRD/API 계약이 먼저 고정된다.
- 기존 코드가 새 제품 방향을 다시 끌고 가지 못한다.
- destructive/legacy endpoint를 테스트로 차단할 수 있다.
- 부분적으로 쓸 만한 Proxmox 조회 경험은 안전하게 재사용할 수 있다.

## 4. 목표 코드 구조 초안

### 4.1 Backend

예상 새 구조:

```text
backend/app/main.py
backend/app/api/v1/router.py
backend/app/api/v1/responses.py
backend/app/core/config.py
backend/app/core/redaction.py
backend/app/core/time.py
backend/app/manifests/models.py
backend/app/manifests/loader.py
backend/app/manifests/validation.py
backend/app/proxmox/client.py
backend/app/proxmox/inventory.py
backend/app/proxmox/readiness.py
backend/app/jobs/models.py
backend/app/jobs/store.py
backend/app/jobs/artifacts.py
backend/app/vm_create/drafts.py
backend/app/vm_create/preflight.py
backend/app/vm_create/planner.py
backend/app/vm_create/approval.py
backend/app/vm_create/gitops.py
backend/app/vm_create/executor.py
backend/app/smoke/stage_a.py
backend/app/smoke/models.py
```

Legacy 후보 처리:

```text
backend/app/domains/deploy/*       -> Drop, 단 preflight 아이디어만 재검증
backend/app/domains/llm/*          -> Drop/Park
backend/app/domains/proxmox/*      -> read-only inventory/risk 일부 Keep 후보
backend/app/integrations/terraform -> GitOps/apply slice에서 재검증 후 일부 Keep 후보
backend/alembic old GitLab/staging -> 새 DB 모델과 충돌 여부 검토 후 migration reset/새 baseline 결정
```

### 4.2 Frontend

예상 새 구조:

```text
frontend/src/app/App.jsx
frontend/src/api/client.js
frontend/src/api/v1.js
frontend/src/pages/DashboardPage.jsx
frontend/src/pages/InfraExplorerPage.jsx
frontend/src/pages/CreateVmPage.jsx
frontend/src/pages/JobsPage.jsx
frontend/src/pages/RisksPage.jsx
frontend/src/features/create-vm/*
frontend/src/features/inventory/*
frontend/src/features/jobs/*
frontend/src/features/risks/*
frontend/src/components/common/*
frontend/src/utils/reviewSummary.js
frontend/src/utils/riskPolicy.js
frontend/src/utils/secretRedaction.js
```

Legacy 후보 처리:

```text
CreateInstanceWizard.jsx        -> PRD wizard와 다르므로 대부분 Drop
InstanceList.jsx                -> VM list display idea만 Keep 후보
OperationalRiskDashboard.jsx    -> risk summary 표시 아이디어 일부 Keep 후보
LlmInfraChat.jsx                -> Drop/Park
old provisioning utils          -> static IP validation 등만 테스트 후 Keep 후보
```

### 4.3 IaC / manifests

PRD 기준 위치:

```text
/mnt/hermes_data/IaC
  manifests/profiles/general-vm.yaml
  manifests/templates/ubuntu-template.yaml
  manifests/networks/server-net.yaml
  manifests/vms/<manifest_id>.yaml
  generated/**
  terraform/**
  ansible/**

/var/lib/gjallar/runs/<job_id>/
  preflight_report.json
  plan.json
  review_summary.json
  approval.json
  planned_git_diff.txt
  terraform_plan.txt/json
  terraform_apply.log
  state_checksum.json
  observed_snapshot.json
  smoke_report.json
```

현재 `/mnt/hermes_data/IaC`가 확인되지 않으므로, Slice 6 전에는 IaC repo 생성/clone/mount 정책을 확정해야 한다.

## 5. 실행 세트

### Set 0 — 작업 준비 / 안전 백업

목표:

- 새 branch 생성.
- 현재 repo 상태와 legacy route/test inventory 백업.
- backend test dependency 확인.
- Codex VM에서 PRD 접근 방식 결정: NFS mount 또는 PRD snapshot copy.

산출물:

```text
artifacts/rewrite-baseline/<timestamp>/status.txt
artifacts/rewrite-baseline/<timestamp>/tracked-files.txt
artifacts/rewrite-baseline/<timestamp>/route-inventory.txt
artifacts/rewrite-baseline/<timestamp>/test-inventory.txt
```

검증:

- `git status --short --branch` clean.
- frontend current tests pass.
- backend test command이 실행 가능한 상태가 되거나, 설치 필요성이 명시됨.

### Set 1 — Fresh code inventory / Keep-Drop-Park

목표:

- PRD 기준으로 기존 코드를 `Keep / Drop / Park` 분류.
- 공용 PRD `10_CODE_INVENTORY.md`, `11_KEEP_DROP_PARK.md`에 구현 직전 결과 반영.

분류 기준:

- Keep: Proxmox/VM 계층, 테스트 가능, secret/state 안전, PRD API와 맞음.
- Drop: deploy/app/DB migration/LLM/staging/destructive/느린 backend/불명확 state.
- Park: 삭제/snapshot/resource resize/template management/console/RBAC 등 2차 기능.

검증:

- 모든 top-level backend/frontend/infra 모듈이 분류됨.
- Drop 전 백업 경로가 기록됨.

### Set 2 — Contract/schema tests 먼저 작성

목표:

- `/api/v1` 공통 response/error shape 테스트.
- manifest schema 테스트.
- profile/network/template 기본값 테스트.
- forbidden API 테스트.
- secret serialization 테스트.

필수 테스트 후보:

```text
backend/tests/contracts/test_api_v1_shape.py
backend/tests/contracts/test_forbidden_mvp_endpoints.py
backend/tests/manifests/test_profile_schema.py
backend/tests/manifests/test_network_profile.py
backend/tests/manifests/test_secret_redaction.py
backend/tests/vm_create/test_draft_contract.py
backend/tests/vm_create/test_preflight_policy.py
frontend/tests/reviewSummary.test.mjs
frontend/tests/riskPolicy.test.mjs
frontend/tests/createVmDefaults.test.mjs
```

검증:

- 첫 실행은 실패해야 한다.
- 실패 이유가 “아직 구현 없음/계약 불일치”여야 한다.

### Set 3 — Backend `/api/v1` skeleton + manifest loader

목표:

- `FastAPI`에 `/api/v1` router 추가.
- 공통 response wrapper 추가.
- manifest model/loader/validator 추가.
- `general-vm`, `server-net`, `ubuntu-template` fixture 로드.

초기 API:

```text
GET /api/v1/cluster/summary
GET /api/v1/nodes
GET /api/v1/vms
GET /api/v1/vms/{vmid}
GET /api/v1/profiles
GET /api/v1/templates
GET /api/v1/networks
```

검증:

- Set 2 contract/schema 테스트 중 skeleton 관련 테스트 GREEN.
- legacy `/api/deploy`, `/api/provision`에 의존하지 않음.

### Set 4 — Minimum job/artifact substrate

목표:

- approval/preflight/plan보다 먼저 artifact 참조가 실제 파일을 가리키게 함.
- fake checksum이 아닌 실제 SHA-256 checksum 사용.

최소 모델:

```text
jobs: job_id, job_type, status, target_id, risk_level, started_at, finished_at
approvals: job_id, plan_artifact_id, review_summary_checksum, yellow_risk_acknowledged, decision
job_artifacts: artifact_id, job_id, type, path, checksum, created_at
```

초기 저장소:

```text
/var/lib/gjallar/runs/<job_id>/
```

검증:

- artifact 없이 approval checksum만 만드는 구현 금지 테스트 통과.
- secret 원문 저장 금지 테스트 통과.

### Set 5 — Read-only Proxmox inventory adapter

목표:

- Proxmox nodes/VMs/templates/storage/network/guest-agent/IP read-only 조회.
- live inventory snapshot 저장.
- Codex/dev 환경에서는 fake adapter로 contract test 가능하게 함.

Keep 후보:

- 기존 `ProxmoxService`의 read-only inventory, qemu-guest-agent, IP merge/caching 경험.

주의:

- create/apply/delete/power action 없음.
- Heimdall write 없음.

검증:

- nodes/vms/detail API shape 테스트 GREEN.
- secret/log redaction 테스트 GREEN.

### Set 6 — Create draft / preflight / plan

목표:

- `POST /api/v1/vm-create/drafts`
- `POST /api/v1/vm-create/{draft_id}/preflight`
- `POST /api/v1/vm-create/{draft_id}/plan`

Preflight 필수 checks:

- profile schema
- disabled/future profile reject
- template 존재/상태
- target node online
- storage 존재/여유
- selected node bridge mapping
- live bridge existence
- `proxmox_vmid`/name collision
- hardware limit
- static IP range/reserved/collision
- Terraform state lock
- destroy/delete plan blocker
- credential scope

검증:

- red/yellow/green risk result 테스트 GREEN.
- manual VMID input reject/hide 테스트 GREEN.
- state path 형식 테스트 GREEN.

### Set 7 — Review & Confirm / approval policy

목표:

- plan response에 `review_confirm`와 `review_summary_checksum` 포함.
- approve request가 `plan_artifact_id`, checksum, yellow ack를 검증.

Review & Confirm 필수 13항목:

1. VM name
2. VMID
3. target node
4. storage
5. template
6. CPU/RAM/Disk
7. network/IP
8. Terraform state path
9. first power on 포함 여부
10. smoke timeout summary
11. red/yellow risk summary
12. plan artifact link
13. planned Git diff summary

검증:

- red risk면 approve/execute disabled.
- yellow risk면 ack 없이는 approve 실패.
- typed confirmation은 VM 생성에 요구하지 않음.

### Set 8 — GitOps guard

목표:

- job workspace 생성.
- IaC repo checkout/pull.
- allowlist path만 변경.
- manifest/generated 생성.
- repo clean/stale/non-fast-forward/push failure guard.
- commit/push before apply.

선행 blocker:

- `/mnt/hermes_data/IaC` 생성/clone/mount 필요.
- Codex VM의 shared doc/IaC 접근 방식 필요.

검증:

- denylist(`terraform/modules/**`, `ansible/roles/**`, `scripts/**`) write 차단.
- commit/push 실패 시 apply 차단.
- secret이 diff/artifact/log에 없음.

### Set 9 — Terraform/Proxmox apply powered-off

목표:

- powered-off clone/config.
- hardware/cloud-init/network config.
- local backend state path 사용.
- apply/config 성공 전 first power on 금지.
- state checksum/backup metadata 저장.

실패 상태:

```yaml
readiness_state: provision_failed_not_booted
boot_skipped: true
failed_stage: terraform_apply | proxmox_config
```

검증:

- apply/config 실패 시 power on 호출 없음.
- state/manifest `proxmox_vmid` mismatch red block.
- Terraform destroy/delete plan block.

### Set 10 — First power on + Stage A smoke

목표:

- first power on.
- cloud-init wait.
- guest-agent wait.
- IP discovery.
- SSH check.
- smoke report 저장.

Timeout 기본값:

```text
first power on: 5m
cloud-init: 15m
guest-agent: 5m
IP discovery: 5m
SSH: 5m
```

실패 상태:

```yaml
readiness_state: created_but_not_ready
boot_skipped: false
failed_stage: first_power_on | cloud_init | guest_agent | ip | ssh
```

검증:

- 자동 삭제/reboot/rollback 없음.
- 실패 VM도 artifact로 원인 추적 가능.

### Set 11 — UI cutover

목표:

- 새 API client `/api/v1` 사용.
- Dashboard / Infra Explorer / Create VM / Review & Confirm / Jobs / Risks 화면 구성.
- old provisioning/deploy/LLM tabs 제거 또는 Park.

검증:

- Create VM wizard에서 `general-vm`만 노출.
- default static, DHCP 선택 가능.
- advanced hardware collapsed.
- red risk approve disabled.
- yellow risk ack checkbox.
- hard stop/reset/delete/snapshot UI 없음.

### Set 12 — Legacy removal / final hardening

목표:

- legacy router/module 제거 또는 격리.
- README/backend/frontend docs를 새 PRD 기준으로 정리.
- full test/build/smoke.

제거 후보:

```text
/api/deploy
/api/provision
/api/instances/terminate
/api/instances/action stop/reset 성격
/api/llm/*
GitLab/staging legacy migrations/domain docs
```

검증:

- forbidden endpoint tests GREEN.
- frontend build GREEN.
- backend tests GREEN.
- `git diff --check` GREEN.
- fresh review 통과.

## 6. 테스트/검증 명령 후보

실제 repo 정리 후 확정한다.

```bash
# backend
cd /home/yoon/projects/Gjallar
backend/.venv/bin/python -m pytest backend/tests -q

# frontend pure tests
for f in frontend/tests/*.mjs; do node "$f" || exit 1; done

# frontend build/lint
pnpm --dir frontend install
pnpm --dir frontend build
pnpm --dir frontend lint

# hygiene
git diff --check
git status --short --branch
```

현재 확인 결과 backend venv에는 `pytest`가 없으므로 Set 0에서 test env를 먼저 복구한다.

## 7. 실행 운영 방식

- Hermes: 공용 PRD/계획/검증/리뷰/보고 담당.
- Codex: 실제 코드 작업 담당.
- 큰 Set마다 구현자와 reviewer를 분리한다.
- 각 Set 완료 조건:
  1. RED 테스트 확인
  2. GREEN 구현 확인
  3. 관련 full/narrow tests 통과
  4. forbidden scope 미포함 확인
  5. fresh review
  6. 공용 문서 CURRENT/TASKS 또는 PRD 관련 문서 갱신

## 8. 첫 시작 액션

사용자가 이 계획을 승인하면 바로 아래부터 시작한다.

1. Codex VM repo에서 새 branch 생성.
2. baseline artifact 생성.
3. backend test env 복구 계획 확정.
4. `10_CODE_INVENTORY.md` / `11_KEEP_DROP_PARK.md`에 실제 repo inventory 반영.
5. Set 2 contract/schema tests를 RED로 만든다.

## 9. 지금 막는 질문

없다.

PRD는 이미 구현 시작 가능한 수준이다. 남은 값은 질문이 아니라 live inventory로 확인할 항목이다.

단, Slice 6 전에 다음은 도구로 확인/정리해야 한다.

- `/mnt/hermes_data/IaC` 실제 repo 위치/생성 여부
- Codex VM에서 공용 docs/IaC 접근 방식
- Proxmox template/storage/IP availability
- Proxmox API Token 권한 범위


## 10. Cron readiness review addendum

> 추가 리뷰: 2026-05-09 00:42 KST

### 10.1 판정

- Set 설계 방향은 PRD/MVP와 맞다.
- 단, overnight autonomous cron은 전체 Set 0~12를 무제한 실행하지 않는다.
- 허용 범위는 **Set 0~7의 비파괴/TDD/code/docs/fake-read-only/dry-run 작업**이다.
- **Set 8+ live GitOps/commit/push/apply/power-on은 사용자 명시 승인 전 hard stop**이다.

### 10.2 Set / Handoff Slice 매핑

```text
Set 0  -> 실행 준비 / 안전 백업
Set 1  -> Handoff Slice 1 code inventory
Set 2  -> Handoff Slice 2 contract/schema tests
Set 3  -> /api/v1 skeleton + manifest loader
Set 4  -> Handoff Slice 2.5 job/artifact substrate
Set 5  -> Handoff Slice 3 read-only inventory API
Set 6  -> Handoff Slice 4 draft/preflight/plan
Set 7  -> Handoff Slice 5 Review & Confirm / approval policy
Set 8  -> Handoff Slice 6 GitOps guard; live side effect approval gate
Set 9  -> Handoff Slice 7 Terraform/Proxmox apply powered-off; live side effect approval gate
Set 10 -> Handoff Slice 8 first power on + Stage A smoke; live side effect approval gate
Set 11 -> UI cutover; execution buttons must preserve approval/risk gates
Set 12 -> legacy removal/final hardening; deletion approval gate
```

### 10.3 Hard stop gates for cron

Cron must stop and report `DECISION_REQUIRED` before:

- `git commit` / `git push`
- file/module deletion or large legacy removal
- writing live IaC repo or Terraform state
- Terraform apply
- Proxmox write / VM create / power-on
- red risk override attempt
- yellow risk execution without explicit ack

### 10.4 Set 2 test additions

Add/verify tests for:

- no Heimdall registry write endpoint in MVP
- no Runtime Target write/`active=true` in MVP
- no independent VM power action endpoints in first MVP
- no delete/snapshot/rollback/hard-stop/reset/raw-shell/app-deploy/db-migrate endpoints
- create draft/preflight/plan/approve/execute state transition
- Jobs/Risks read API shape
- GitOps allowlist/denylist:
  - allow: `manifests/vms/**`, `generated/**`
  - deny: `terraform/modules/**`, `terraform/providers/**`, `ansible/roles/**`, `ansible/playbooks/**`, `scripts/**`

### 10.5 Pre-apply recheck required

Before any future Set 9/10 live execution, re-run live checks for:

- `proxmox_vmid` collision
- VM name collision
- IP collision/reserved range
- storage/template/node availability
- state lock
- manifest/state mapping mismatch
- destroy/delete plan blocker

Any red risk blocks execution even if the user approves.

### 10.6 Set 12 clarification

Autonomous cron may Park/disable legacy routes after tests, but **actual deletion/removal requires explicit user approval and backup artifact**.
