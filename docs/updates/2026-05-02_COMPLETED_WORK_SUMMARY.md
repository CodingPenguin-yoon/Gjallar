# 2026-05-02 Completed Work Summary

This document summarizes the work that is implemented in the repository as of 2026-05-02.

## Outcome

Heimdall now has a usable staging-first path that connects:

- VM provisioning from `Create Instance`
- optional staging-host auto-registration
- staging host pool preview and port inspection
- GitLab project environment-contract setup
- repo-side `.heimdall/project.yaml` editing
- manual staging deploy onto a selected shared host

## Completed work

### 1. Staging host provisioning and registration

Operators can still provision a VM from `Create Instance`, but the flow now also supports `Create as staging host`.

Current behavior:

- the existing Terraform clone flow is preserved
- post-clone VM adjustment is still available
- Ansible bootstrap still runs as part of provisioning
- enabling `Create as staging host` auto-adds the `base` and `docker` roles
- a host is registered into `staging_hosts` only after:
  - VM IP resolution succeeds
  - bootstrap actually runs
  - bootstrap finishes successfully

Current registration defaults:

- `environment=staging`
- `pool_key=default`
- `role=shared`

### 2. Staging host registry and pool preview

The platform now persists shared staging hosts and exposes them as deployable pools.

Current capabilities:

- list registered staging hosts
- group hosts by `environment + pool_key`
- preview pool readiness
- inspect allowed ports on ready hosts over SSH
- report blocked hosts and inspection errors
- suggest an available app port
- choose a host candidate for deploy

### 3. GitLab project setup moved to an environment contract

GitLab project settings now store deployment intent instead of older staging-only flags.

Current contract fields:

- `deployment_environment`
- `deployment_pool_key`
- `requested_app_port`
- `database_required`
- `deploy_branch`

Current UI behavior:

- `GitLab Workspace` includes a `Project Setup` flow
- operators choose environment, pool, app port, and DB requirement
- the UI previews current pool availability before save
- `production` can be stored, but execution is still staging-only

### 4. Repo-side manifest management

The platform now manages `.heimdall/project.yaml` inside the same project setup flow.

Current capabilities:

- load the current manifest from GitLab
- generate a draft when the file is missing
- edit manifest content from guided fields
- validate YAML before save
- create or update the file on the selected branch

Current manifest deploy contract:

- required:
  - `runtime`
  - `deploy.compose_file`
  - `deploy.healthcheck`
- optional fallback:
  - `deploy.app_port`

If project settings already store `requested_app_port`, that value overrides the manifest fallback.

### 5. Shared-host staging deploy

`Deploy Staging` no longer needs to create a dedicated VM for the current staging path.

Current execution path:

1. reload project settings and manifest status
2. rebuild the environment-contract preview
3. preview the selected staging pool again
4. choose a ready host and app port
5. skip Terraform for app deploy
6. download the GitLab source archive
7. extract the release on the target host
8. run remote `docker compose up -d --build`
9. verify the typed healthcheck contract

Supported healthcheck modes:

- `http`
- `tcp`
- `command`
- `none`

### 6. Data model and API surface

The current slice added or expanded:

- `staging_hosts`
- environment-contract fields on `gitlab_project_settings`
- migration history through `20260426_0010`
- staging registry APIs
- manifest read/update/preview APIs
- staging deploy wrapper tracking

## Documentation restructure

The docs tree was reduced to the active staging slice and now centers on:

- `docs/architecture/STAGING_ARCHITECTURE.md`
- `docs/architecture/STAGING_CONTRACT.md`
- `docs/operations/STAGING_RUNBOOK.md`
- `docs/roadmap/NEXT_WORK.md`

Older broad planning documents were removed from the active set to keep the repo aligned with the code that exists today.

## Validation target

Recommended validation for this snapshot:

```bash
python3 -m compileall backend/app
pnpm --dir frontend build
cd backend && . venv/bin/activate && alembic upgrade head
```

## Remaining gaps

The following are still not finished:

- Postgres provisioning and `DATABASE_URL` injection
- capacity-aware host scheduling
- automatic host creation when a pool is saturated
- redeploy automation from webhook or merge events
- release snapshot automation
- rollback automation
- production execution flow
