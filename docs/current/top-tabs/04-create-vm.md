# Create VM

평가일: 2026-05-16

검증 기준: 2026-05-16에 backend `PYTHONPATH=backend backend/venv/bin/pytest -q backend/tests` -> 148 passed, 1 warning, 29 subtests passed, frontend `for test_file in frontend/tests/*.mjs; do node "$test_file"; done` -> passed, `pnpm --dir frontend lint` -> passed, `pnpm --dir frontend build` -> passed, `git diff --check` -> passed를 기록했다.

## 구현 수준

Create VM은 현재 가장 강한 supporting capability다. draft/preflight/plan/review/approval과 Proxmox API native create gate가 구현되어 있지만, DRS Advisor의 success line은 아니다. Terraform plan/apply legacy executor route surface는 제거됐다.

## 구현 API/endpoints

- `GET /api/v1/profiles`
- `GET /api/v1/vm-create/readiness`
- `POST /api/v1/vm-create/drafts`
- `POST /api/v1/vm-create/{draft_id}/preflight`
- `POST /api/v1/vm-create/{draft_id}/plan`
- `POST /api/v1/vm-create/{draft_id}/approve`
- `POST /api/v1/vm-create/{draft_id}/proxmox-preview`
- `POST /api/v1/vm-create/{draft_id}/proxmox-create`

## 관련 파일

- Frontend: [frontend/src/components/CreateInstanceWizard.jsx](../../../frontend/src/components/CreateInstanceWizard.jsx), [frontend/src/utils/createVmFlow.js](../../../frontend/src/utils/createVmFlow.js), [frontend/src/utils/createVmDefaults.js](../../../frontend/src/utils/createVmDefaults.js), [frontend/src/services/apiV1.js](../../../frontend/src/services/apiV1.js)
- Backend: [backend/app/api/v1/router.py](../../../backend/app/api/v1/router.py), [backend/app/vm_create/drafts.py](../../../backend/app/vm_create/drafts.py), [backend/app/vm_create/preflight.py](../../../backend/app/vm_create/preflight.py), [backend/app/vm_create/planner.py](../../../backend/app/vm_create/planner.py), [backend/app/vm_create/approval.py](../../../backend/app/vm_create/approval.py), [backend/app/vm_create/proxmox_runner.py](../../../backend/app/vm_create/proxmox_runner.py), [backend/app/proxmox/client.py](../../../backend/app/proxmox/client.py), [backend/app/vm_create/manifest.py](../../../backend/app/vm_create/manifest.py), [backend/app/vm_create/iac_readiness.py](../../../backend/app/vm_create/iac_readiness.py)
- Shared substrate: [backend/app/jobs/runs.py](../../../backend/app/jobs/runs.py), [backend/app/jobs/artifacts.py](../../../backend/app/jobs/artifacts.py), [backend/app/jobs/models.py](../../../backend/app/jobs/models.py)
- Tests: [frontend/tests/createVmFlow.test.mjs](../../../frontend/tests/createVmFlow.test.mjs), [frontend/tests/createVmDefaults.test.mjs](../../../frontend/tests/createVmDefaults.test.mjs), [backend/tests/contracts/test_api_v1_vm_create.py](../../../backend/tests/contracts/test_api_v1_vm_create.py), [backend/tests/contracts/test_api_v1_vm_create_approval_execute.py](../../../backend/tests/contracts/test_api_v1_vm_create_approval_execute.py), [backend/tests/vm_create/test_preflight_plan_contract.py](../../../backend/tests/vm_create/test_preflight_plan_contract.py)

## 현재 구현

primary UI flow는 default draft 생성, read-only preflight, artifact-backed dry-run plan, review checksum, approval validation, final acknowledgement, Proxmox native create gate로 이어진다. 별도 "생성 요청 저장" 단계는 current UI에서 제거됐고, `proxmox-create`는 manifest commit SHA를 요구하지 않는다.

Access/SSH는 현재 구현되어 있다. Wizard는 cloud-init user와 SSH public key
입력을 보낸다. Backend는 request key 또는 backend env/file default key를
사용하고, profile이 SSH key를 요구할 때 missing/malformed/private-key-looking
값을 red preflight로 차단한다. Review/plan/manifest/preview/observed evidence는
username, password-login disabled, key presence/source/fingerprint만 포함하고
raw public key는 반환하거나 artifact에 쓰지 않는다.

`proxmox-preview`는 승인 뒤에도 mutation하지 않고 clone/config/post-check payload와 artifact만 만든다. 현재 UI는 별도 preview 버튼을 노출하지 않으며, `proxmox-create`가 mutation 직전에 preview artifact를 내부 생성한다. `proxmox-create`는 `proxmox_mutation_acknowledged=true`를 요구하고, mutation 직전에 preflight/plan을 다시 만든 뒤 red risk면 차단한다.

Native create는 `/nodes/{template_node}/qemu/{template_vmid}/clone` full clone, task polling, cloned config 기반 boot disk resize 필요 여부 판단, `/nodes/{node}/qemu/{vmid}/config`, `/status/current` + `/config` post-check 순서다. 요청 `disk_gb`가 cloned boot disk보다 크면 config 전 `/resize`를 호출하고, unknown/resize failure는 `needs_reconciliation`이다. 기본 `stopped` 정책은 VM exists + target node + `stopped`가 확인되고 `observed_after`/fingerprint artifact가 있어야 applied다. 선택 `boot_and_verify` 정책은 VM을 시작한 뒤 guest-agent IP와 `cloud-init status --wait` 완료까지 확인해야 applied다.

Removed Terraform plan/apply URLs are absent from the route table and return FastAPI 404.

현재 생성 정책은 요청별로 명시된다. 기본값은 `stopped`이며 plan/review는 `first_power_on_included=false`, VMInstance manifest는 `desired_power_state: stopped`를 기록한다. 선택값 `boot_and_verify`는 `first_power_on_included=true`, `desired_power_state: running`을 기록하고 native create가 VM start, guest-agent IP discovery, cloud-init completion check까지 수행한다. SSH login, Ansible, app deploy, DRS identity registration은 아직 deferred다.

Profiles는 현재 `GJALLAR_DATABASE_URL`의 DB seed source로 구현되어 있다.
Alembic migration이 schema를 만들고, `python -m app.db.seed_create_vm_profiles`
manual seed command가 table이 비어 있을 때만 초기 profile을 insert한다.
`GET /api/v1/profiles`는 active `general-vm`, `runtime-server`,
`development-vm` 세 개를 `source: db_seed`로 반환하며, hardware `default/min/max`,
`template_requirements`, `access_recommendations`를 포함한다. Disabled/archived
profile은 Create VM selection에서 숨긴다. Profile API는
network/`network_id`, bridge, static IP, target node, storage, template
VMID/name, power policy, profile version을 반환하지 않는다. Wizard는 profile
목록을 API에서 로드한다. API 실패 또는 active profile empty일 때 local defaults는
표시 fallback으로만 쓰이고 review 진행은 차단된다.

Draft/API는 `profile_id`/`profileId`와 CPU/RAM/Disk override를 받는다. 기본값은
`general-vm`이고, profile 변경 시 UI는 CPU/RAM/Disk를 해당 profile default로
reset한 뒤 선택 template disk가 더 크면 disk만 올린다. Backend preflight는
선택 profile 존재/활성 여부와 CPU/RAM/Disk min/max를 authoritative red gate로
검증한다. Plan/review/review-summary checksum에는 `profile_id`와 resolved
profile hardware limits가 포함된다.

Template 선택은 `/api/v1/templates`의 read-only Proxmox inventory만 사용한다.
초기 세 profile은 모두 cloud-init과 qemu guest-agent capable template을
요구한다. Wizard는 live template을 모두 보여주되 선택 profile requirements를
통과하지 못하는 option을 disabled reason과 함께 비활성화하고, passing
template이 없으면 review 시작을 막는다. Backend preflight는 authoritative
gate로 selected template의 required cloud-init 또는 guest-agent readiness
부족을 red risk로 반환한다. Live inventory에서 Proxmox `agent` config가
없거나 unknown이면 guest-agent-ready로 보지 않는다.

## Profile / Template / Network target gap

Target design은
[`../../architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md`](../../architecture/CREATE_VM_PROFILE_TEMPLATE_NETWORK_DESIGN.md)를 따른다.
현재 구현 상태와 target의 차이는 명시적으로 남긴다.

- Profile source of truth는 Gjallar DB seed이며 초기 UI에서는 read-only다.
- Seeded enabled profiles는 `general-vm`, `runtime-server`, `development-vm`이다.
- Profile schema는 Alembic migration으로 관리하고 seed는 별도 manual command다.
- Template source of truth는 Proxmox live inventory이며, Gjallar template
  catalog/registration window는 active selection에 없다.
- Current UI는 선택 profile의 `require_cloud_init=true`,
  `require_qemu_guest_agent=true` 조건을 만족하지 못하는 live template을
  disabled로 보여주고, backend preflight가 red-block한다.
- Target network source of truth는 selected target node의 active live bridge다.
- Current code는 selected target node의 active live bridge를 source of truth로
  사용한다. `bridge_id`가 없거나 target node에서 missing/inactive이면 red
  preflight다.
- Incoming `network_id`/`networkId`는 transition compatibility로 ignore되며
  draft/plan/review/manifest/job active output에 echo하지 않는다.
- NetworkPolicy missing/range/out-of-range는 Create VM red blocker가 아니다.
  관찰된 static IP conflict는 계속 red blocker다.
- Static mode는 현재 `static_ip`, `prefix`, `gateway`를 모두 요구한다.
- Gateway와 prefix는 사용자가 입력한 값을 그대로 사용하며, native create는
  static IP에서 `.1` gateway 또는 `/24` prefix를 추론하지 않는다.
- Access section, SSH public key collection, missing-key red gate, safe
  fingerprint evidence, and fixed disabled password-login gate are current
  behavior.
- Profile에는 power policy가 없다. 운영자가 요청마다 `stopped` 또는 `boot_and_verify`를 선택한다. 기존 VM start는 여전히 별도 Infra Explorer row action과 Jobs/Runs audit 대상이다.

## DRS Advisor 기준 gaps

[DRS Advisor product direction](../../product/drs-advisor/01_PRODUCT_DIRECTION.md) 기준 Create VM은 보조 capability다. DRS final pre-check, operation lock, live migration, UPID tracking, post-check, needs_reconciliation은 Create VM의 native create 구현에서 배운 패턴을 재사용할 수 있지만, migration 실행 계약은 별도 구현이어야 한다.

Create VM의 approval/artifact/native acknowledgement/observed_after 패턴은 재사용할 수 있지만, DRS 실행 허가나 성공 기준으로 overclaim하면 안 된다.

## 리스크/메모

Legacy `execute/archive` manifest commit APIs are removed from the active route surface. 실제 Proxmox mutation은 `proxmox-create`에서만 gate 뒤에 일어난다.

## 다음 구현 slice

Create VM의 Terraform executor와 Terraform-named state metadata는 active
contract에서 제거됐다. DRS 작업에서는 approval checksum, artifact publication,
job status 기록 패턴만 참고하고, 별도 `/api/v1/drs/*` read model과 final
pre-check 계약을 먼저 만든다.
