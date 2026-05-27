# Current Runbook

This is the current concise verification runbook for the implemented repo state. Prefer this file over the legacy [`../archive/operations/RUNBOOK.md`](../archive/operations/RUNBOOK.md).

## Backend validation

From repo root:

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests
```

Latest consolidated backend validation baseline is recorded in
[`../current/README.md`](../current/README.md). This runbook intentionally does
not carry a separate backend pass count.

## Frontend validation

Run the frontend `.mjs` tests directly with Node.

From repo root:

```bash
for test_file in frontend/tests/*.mjs; do
  node "$test_file"
done
```

Lint and build from `frontend/`:

```bash
pnpm lint
pnpm build
```

Current recorded frontend baseline:

- Frontend tests passed.
- Frontend build passed.

## Auth And First Admin

Run migrations before starting the backend so auth tables exist:

```bash
cd backend
set -a
. ../.env
set +a
venv/bin/alembic upgrade head
PYTHONPATH=. venv/bin/python -m app.db.seed_create_vm_profiles
PYTHONPATH=. venv/bin/python -m app.auth.users create-admin --username yoon
```

There is no public signup flow. Local accounts are managed with the backend CLI,
which prompts for passwords unless `--password-env` is supplied. For one-off
backend CLI commands, load the repo root `.env` in the backend shell first:

```bash
cd backend
set -a
. ../.env
set +a
```

Account operations:

```bash
PYTHONPATH=. venv/bin/python -m app.auth.users create-admin --username yoon
PYTHONPATH=. venv/bin/python -m app.auth.users create-user --username kim --role viewer
PYTHONPATH=. venv/bin/python -m app.auth.users create-user --username park --role operator
PYTHONPATH=. venv/bin/python -m app.auth.users list-users
PYTHONPATH=. venv/bin/python -m app.auth.users set-role --username kim --role operator
PYTHONPATH=. venv/bin/python -m app.auth.users disable-user --username kim
PYTHONPATH=. venv/bin/python -m app.auth.users reset-password --username park
```

`disable-user` and `reset-password` revoke existing sessions for the target user.
`set-role` does not revoke sessions; existing sessions pick up the role on their
next request. `disable-user` refuses to disable the last enabled admin, and
`set-role` refuses to demote the last enabled admin away from `admin`. Disabled
admin rows do not count toward that guard. `reset-password` is still allowed for
the last enabled admin and revokes that user's sessions.

The backend stores a PBKDF2 password hash and server-side session records; the
browser receives only an opaque `HttpOnly`, `SameSite=Lax` session cookie.

Login/logout flow:

- UI route: `/login`
- API login: `POST /api/v1/auth/login`
- API logout: `POST /api/v1/auth/logout`
- Session bootstrap: `GET /api/v1/auth/me`
- Admin UI: `/admin/users`

Admin user-management APIs:

```http
GET /api/v1/admin/users
POST /api/v1/admin/users
PATCH /api/v1/admin/users/{username}/role
POST /api/v1/admin/users/{username}/disable
POST /api/v1/admin/users/{username}/reset-password
```

All admin APIs require an `admin` session. Successful responses use the
standard `{ ok, data, meta }` envelope and return only safe user summaries plus
revoked session counts where relevant. They must not return password hashes,
session token hashes, raw secrets, or plaintext passwords. Operator errors use
structured `detail` objects; last-admin protection returns `409`, unknown users
return `404`, and validation errors return `400`.

Role behavior:

- `viewer`: can read protected inventory/jobs/risks/DRS surfaces.
- `operator`: viewer permissions plus Create VM workflow writes, Create VM live
  create, and VM Start.
- `admin`: operator permissions plus local user management.

Create VM draft/preflight/plan/approve/proxmox-preview all write Gjallar
job/artifact state, so they require `operator` or `admin`. Read-only GET APIs
require `viewer` or above. Public health, root health, login, logout, and
session status (`/api/v1/auth/me`, which returns `authenticated: false` when
anonymous) remain callable without a viewer role.

Unsafe browser requests with `Origin: null` or an unknown origin are rejected.
TestClient/curl-style requests without `Origin` are allowed.

## Diff hygiene

From repo root:

```bash
git diff --check
```

Use this to catch malformed whitespace or patch issues before any commit.

## Basic `/api/v1` smoke notes

The active frontend contract is `/api/v1`.

Current recorded smoke baseline:

- Frontend dev server convention is `http://127.0.0.1:5173`.
- Backend dev server convention is `http://127.0.0.1:8000`.
- Active API surface remains `/api/v1`.
- Browser access starts at `/login`; all frontend API fetches include session
  cookies.
- Jobs/Runs progress records are read from the DB configured by `GJALLAR_DATABASE_URL`.
- Create VM workflow and VM Start job evidence includes authenticated actor
  fields: `actor_user_id`, `actor_username`, and `actor_role`.
- Infra Explorer VM start uses `POST /api/v1/nodes/{node_id}/vms/{vmid}/actions/start` and records `vm_start` jobs/artifacts in the DB-backed Jobs/Runs tables.

Auth-focused validation from repo root:

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q \
  backend/tests/contracts/test_api_v1_auth.py \
  backend/tests/contracts/test_api_v1_vm_create.py \
  backend/tests/contracts/test_api_v1_vm_create_approval_execute.py
node --test frontend/tests/authFlow.test.mjs frontend/tests/apiV1Client.test.mjs frontend/tests/createVmFlow.test.mjs
```

## Safety notes

- Treat inventory as read-only.
- Create VM workflow writes and live actions require login with `operator` or
  `admin`, exact approval metadata, fresh red-risk checks, and explicit native
  Proxmox create acknowledgement.
- Create VM default `stopped` success remains powered-off after post-check and
  does not auto-start. The optional `boot_and_verify` request explicitly starts
  the new VM and verifies guest-agent IP plus cloud-init completion.
- Existing VM start requires an in-app acknowledgement, idempotency key, fresh inventory precheck, Proxmox task polling, and observed-after running evidence.
- Do not rely on destructive VM list controls; the current UI does not expose stop/reset/shutdown/reboot/delete/terminate.
- Live Proxmox Create VM smoke was not run during auth stabilization. Running
  the live smoke matrix still requires explicit approval.

## Live Create VM Smoke Checklist

Do not run this section without explicit user approval in the current session.
The checklist performs live Proxmox mutation through
`POST /api/v1/vm-create/{draft_id}/proxmox-create`.
Approval is one-time and session-bound; it is not standing approval for later
runs. The final mutation call still requires immediate explicit approval and
`proxmox_mutation_acknowledged=true`.

Before approval:

1. Confirm the target Proxmox cluster, node, storage, bridge, template, and VMID
   range with the operator.
2. Confirm the logged-in user has `operator` or `admin`.
3. Confirm `GJALLAR_DATABASE_URL`, Proxmox mutation credentials, and
   `GJALLAR_DEFAULT_SSH_PUBLIC_KEY` are loaded from the intended `.env`.
4. Run the non-live validations first:

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests/contracts backend/tests/vm_create backend/tests/proxmox
node --test frontend/tests/createVmFlow.test.mjs
git diff --check
```

Operator-confirmed target details:

| Field | Confirmed value |
| --- | --- |
| Redacted Proxmox API URL / cluster | `<redacted-api-url> / <cluster>` |
| Target node | `<node>` |
| Template node / VMID / name | `<template-node> / <template-vmid> / <template-name>` |
| Storage | `<storage-id>` |
| Bridge | `<bridge-name>` |
| VMID / name range convention | `<vmid-range> / <name-prefix-or-pattern>` |
| Profile / hardware | `<profile>; cpu=<n>; memory=<MiB>; disk=<GiB>; tags=<tags>` |
| IP mode / network values | `dhcp` or `static_ip=<ip>, prefix=<prefix>, gateway=<gateway>` |
| Operator username / role | `<username> / operator-or-admin` |
| Cleanup policy | `leave stopped`, `delete after separate approval`, or other operator-confirmed policy |
| Env/config names loaded | Record names/profile only, never values: `GJALLAR_DATABASE_URL`; `PROXMOX_API_URL`; `PROXMOX_API_TOKEN_ID`; `PROXMOX_API_TOKEN_SECRET`; `PROXMOX_TLS_INSECURE`; optional `PROXMOX_API_CONNECT_TIMEOUT_SECONDS` / `PROXMOX_API_READ_TIMEOUT_SECONDS` / `PROXMOX_TASK_POLL_INTERVAL_SECONDS` / `GJALLAR_PROXMOX_TASK_POLL_INTERVAL_SECONDS` / `PROXMOX_TASK_TIMEOUT_SECONDS` / `GJALLAR_PROXMOX_TASK_TIMEOUT_SECONDS`; `GJALLAR_DEFAULT_SSH_PUBLIC_KEY` or `GJALLAR_DEFAULT_SSH_PUBLIC_KEY_FILE`. |
| Explicit approval timestamp / session | `<YYYY-MM-DDTHH:MM:SSZ>; <session-or-ticket-id>` |

The VMID/name range is an operator convention only. The current API resolves
VMID from inventory and checks uniqueness; before final mutation
acknowledgement, the operator must manually compare the resolved review
VMID/name against the confirmed convention.

Before live mutation, run the negative preflight/gate case and record it in the
matrix below. It must prove the API returns a blocked status and
`side_effects=[]` before any mutation request is sent. Valid examples include
unavailable storage, missing or inactive bridge, unavailable template,
offline/missing node, invalid static network fields, or an IP collision.

After immediate explicit approval, run and record:

1. Default `stopped` creation with the selected live template, storage, bridge,
   and static IP or DHCP choice. Confirm the job completes, the DB
   `vm_create_requests`/`vm_instances` rows exist, and `observed_after` shows the
   VM on the target node with status `stopped`.
2. `boot_and_verify` creation. Confirm the job completes, Proxmox reports
   `running`, guest-agent IP evidence is present, and cloud-init completion is
   recorded.
3. Static IP creation with explicit `static_ip`, `prefix`, and `gateway`.
   Confirm the reviewed network values match the Proxmox config and job
   artifacts.

Live smoke results matrix:

| Case | Run timestamp | Code revision | Endpoint / HTTP / meta / status / message | Job id | Request id | VMID / name | Target node | Power policy | Actor fields | Risk level / codes | Approval evidence | Artifact ids / types / path / checksum | Proxmox UPID / task / resize / start side effects | `observed_after` summary | Guest-agent IP | `cloud_init` | `boot_verification` | DB `vm_create_request` / `vm_instance` evidence | Cleanup decision | Remaining risk |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Default stopped creation | `<timestamp>` | `<commit>` | `<endpoint>; <http>; meta=<meta>; status=<status>; message=<message>` | `<job-id>` | `<request-id>` | `<vmid> / <name>` | `<node>` | `stopped` | `<actor-id>; <username>; <role>` | `<level>; <codes>` | `<approval-timestamp>; <session>; proxmox_mutation_acknowledged=true` | `<ids>; <types>; <paths>; <checksums>` | `<upid>; task=<task>; resize=<none-or-detail>; start=<none>` | `<status stopped; node; config summary>` | `<none-or-ip>` | `<state>` | `<not-requested>` | `<request-row>; <instance-row>` | `<operator decision>` | `<risk>` |
| `boot_and_verify` | `<timestamp>` | `<commit>` | `<endpoint>; <http>; meta=<meta>; status=<status>; message=<message>` | `<job-id>` | `<request-id>` | `<vmid> / <name>` | `<node>` | `boot_and_verify` | `<actor-id>; <username>; <role>` | `<level>; <codes>` | `<approval-timestamp>; <session>; proxmox_mutation_acknowledged=true` | `<ids>; <types>; <paths>; <checksums>` | `<upid>; task=<task>; resize=<none-or-detail>; start=<upid-or-task>` | `<status running; node; config summary>` | `<ip>` | `<complete-or-evidence>` | `<passed-or-detail>` | `<request-row>; <instance-row>` | `<operator decision>` | `<risk>` |
| Static IP creation | `<timestamp>` | `<commit>` | `<endpoint>; <http>; meta=<meta>; status=<status>; message=<message>` | `<job-id>` | `<request-id>` | `<vmid> / <name>` | `<node>` | `<stopped-or-boot_and_verify>` | `<actor-id>; <username>; <role>` | `<level>; <codes>` | `<approval-timestamp>; <session>; proxmox_mutation_acknowledged=true` | `<ids>; <types>; <paths>; <checksums>` | `<upid>; task=<task>; resize=<none-or-detail>; start=<none-or-upid>` | `<status; node; static config summary>` | `<none-or-ip>` | `<state>` | `<not-requested-or-result>` | `<request-row>; <instance-row>` | `<operator decision>` | `<risk>` |
| Negative preflight/gate test | `<timestamp>` | `<commit>` | `<preflight-or-preview-endpoint>; <http>; meta=<meta>; status=blocked; message=<operator-facing-message>` | `<none>` | `<request-id-or-none>` | `<candidate-vmid> / <candidate-name>` | `<node-or-invalid-node>` | `<requested-policy>` | `<actor-id>; <username>; <role>` | `<level>; <codes>` | `<pre-mutation gate evidence; no mutation approval consumed>` | `<ids>; <types>; <paths>; <checksums>` | `side_effects=[]; upid=<none>; task=<none>; resize=<none>; start=<none>` | `<no VM created or changed>` | `<none>` | `<none>` | `<not-run>` | `<no success row; blocked/preflight evidence>` | `<none>` | `<risk>` |

Do not run stop/delete cleanup unless separately approved. Do not commit
secrets, tokens, raw Proxmox payloads, or unredacted live endpoint details.
