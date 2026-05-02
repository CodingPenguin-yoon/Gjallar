# Staging Runbook

This runbook is the shortest path to validate the current staging slice.

## 1. Local prerequisites

- `python3`
- `pnpm`
- `terraform`
- `ansible-playbook`

Main env groups in repo root `.env`:

- `PROXMOX_*`
- `ANSIBLE_SSH_*`
- `BACKEND_PORT`
- `FRONTEND_PORT`
- `GITLAB_*`
- `PLATFORM_PUBLIC_BASE_URL`
- optional environment port ranges:
  - `DEPLOYMENT_PORT_RANGE_STAGING`
  - `DEPLOYMENT_PORT_RANGE_PRODUCTION`

Backend setup:

```bash
cd backend
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
```

Run from repo root:

```bash
pnpm backend
pnpm frontend
```

## 2. Create a staging host

Use `Create Instance`.

1. Select server, template, storage, and network.
2. Optional: choose a static IP and gateway.
3. Enable `Create as staging host`.
4. Launch the VM.

Expected behavior:

- Terraform provisions the VM
- Ansible bootstraps the VM
- the VM is registered into `staging_hosts` only if VM IP resolution and Ansible bootstrap both succeed
- the current preset registers the host into `staging/default`

Check result:

- open `Instance List`
- confirm the VM shows the `Staging Host` badge and host IP

## 3. Prepare a GitLab project

In `GitLab Workspace`:

- open `Project Setup`
- in `1. 배포 설정`, choose `deployment_environment`
- confirm the pool-state card for that environment
- choose `deployment_pool_key`
- choose `requested_app_port` or use manifest fallback
- choose `deploy_branch`
- keep `database_required = false`
- in `2. Manifest 생성`, fill `name`, `runtime`, `compose file`, and the healthcheck contract
- choose a healthcheck type:
  - `http`
  - `tcp`
  - `command`
  - `none`
- use `Validate preview` when you want to check the generated YAML before saving
- create or update `.heimdall/project.yaml`

Important:

- `production` can be stored, but current execution still supports staging only
- if the environment card says pools are full or blocked, fix the pool before deploying
- manifest save and environment-contract save are still separate actions, but they now live in one `Project Setup` screen
- the manifest preview reflects the deployment settings selected above it

## 4. Prepare `.heimdall/project.yaml`

The repository must include a valid `.heimdall/project.yaml` with:

- `deploy.strategy: docker-compose`
- `deploy.compose_file`
- `deploy.healthcheck`
- `environments.staging.enabled: true`
- optional fallback: `deploy.app_port`

## 5. Run staging deploy

Use `Deploy Staging` from `GitLab Workspace`.

Current execution path:

1. wrapper task is created
2. the saved environment contract is rebuilt and validated
3. the selected pool is previewed live
4. a ready host candidate is chosen from that pool
5. a linked deploy task is created
6. Terraform is skipped for the app deploy path
7. SSH readiness checks run for the selected host
8. Ansible prepares the selected host for app rollout
9. the backend downloads the GitLab source archive
10. the release is extracted on the host
11. the effective app port is checked against other running Docker projects
12. `docker compose up -d --build` runs
13. the app healthcheck is verified

## 6. Success criteria

- create-host tasks succeed when provisioning a staging host
- the VM appears in `Instance List` as `Staging Host`
- wrapper task succeeds for GitLab deploy
- linked deploy task succeeds
- compose services are running
- the configured healthcheck succeeds

## 7. Common blockers

- `database_required=true`
- invalid or missing `.heimdall/project.yaml`
- invalid static IP and gateway pair
- no VM IP returned after Terraform
- Ansible bootstrap did not run or failed
- GitLab token cannot read the manifest archive or branch
- no host pool is registered for the selected environment
- selected pool has no ready host or no free port in the allowed range
- requested app port is already published by another Docker project on that host
- missing compose file after archive extraction
- failed configured healthcheck after compose startup

## 8. Still manual

- capacity-aware host selection
- automatic new host creation when a pool is saturated
- DB provisioning
- snapshot creation
- rollback
- production separation
