# Staging Architecture

This document describes the staging architecture that exists in code today.

## Goal

Heimdall is finishing a usable staging path before adding production.

## Main components

### 1. Create Instance path

`Create Instance` is still the VM provisioning entrypoint.

- Terraform clones the VM from the selected template
- post-clone adjustments can apply CPU or memory changes
- Ansible bootstraps the host
- `Create as staging host` is a preset on top of this existing flow
- that preset auto-adds `base` and `docker` roles
- when the bootstrap finishes successfully, the backend auto-registers the host into `staging_hosts`
- the current preset writes `environment=staging`, `pool_key=default`, `role=shared`

Main code:

- `frontend/src/components/CreateInstanceWizard.jsx`
- `frontend/src/App.jsx`
- `backend/app/domains/deploy/router.py`
- `backend/app/domains/deploy/service.py`

### 2. Staging host registry

Successfully bootstrapped staging hosts are persisted in `staging_hosts`, then exposed as host pools.

- registration happens only after VM IP resolution
- registration happens only after Ansible bootstrap succeeds
- the registry stores `environment`, `node`, `vmid`, `host_ip`, `host_user`, `pool_key`, `role`, and runtime flags
- `Instance List` reads the registry and shows membership on matching VMs
- the staging service can group hosts by `environment + pool_key`
- the staging service can preview a pool live by:
  - SSHing into each ready host
  - collecting listening ports
  - calculating available port candidates within the configured range
  - selecting a host candidate for the requested port

Main code:

- `backend/app/domains/staging/router.py`
- `backend/app/domains/staging/service.py`
- `backend/app/shared/platform_models.py`
- `frontend/src/components/InstanceList.jsx`

### 3. GitLab environment contract

GitLab project deploy now runs through a platform-side environment contract.

- `Project Setup` now includes:
  - a manifest step for repo-side `.heimdall/project.yaml`
  - a deployment-contract step for platform-side settings
- each project stores:
  - `deployment_environment`
  - `deployment_pool_key`
  - `requested_app_port`
  - `database_required`
  - workflow metadata such as `deploy_branch`
- `GitLab Workspace` previews pool state and available ports before save
- current runtime execution only accepts `deployment_environment=staging`
- `Deploy Staging` resolves the selected pool, picks a ready host, and skips Terraform
- deploy reads `.heimdall/project.yaml` and runs app rollout through Ansible

Main code:

- `backend/app/domains/gitlab/service.py`
- `frontend/src/components/GitLabWorkspace.jsx`

## Current runtime flows

### Flow A: create a staging host

1. Open `Create Instance`.
2. Select server, template, storage, and optional static IP.
3. Enable `Create as staging host`.
4. Terraform provisions the VM.
5. Ansible bootstraps the VM.
6. If IP resolution and bootstrap both succeed, the backend registers the VM into `staging_hosts`.
7. `Instance List` shows the VM as `Staging Host`.

### Flow B: save an environment contract

Before saving the environment contract, the repo-side manifest is prepared in the first step of `Project Setup`.

### Flow B-1: prepare `.heimdall/project.yaml`

1. Open `GitLab Workspace > Project Setup`.
2. Check whether `.heimdall/project.yaml` exists on the target branch.
3. If the file is missing, use the generated draft.
4. If the file exists, load the current repo content.
5. Create or update the file through GitLab.

### Flow B-2: save an environment contract

1. Open `GitLab Workspace > Project Setup`.
2. Select `Environment` (`staging` or `production`).
3. Review the current pool state for that environment:
   - no registered pools
   - at least one available pool
   - pools exist but are currently blocked or full
4. Select a pool.
5. Choose `Requested port`, or rely on manifest `deploy.app_port` as a fallback.
6. Set `Database required` if needed.
7. Save settings.

### Flow C: deploy a GitLab project

1. Save project settings in `GitLab Workspace`.
2. Ensure `.heimdall/project.yaml` is valid on `deploy_branch`.
3. Request `Deploy Staging`.
4. The GitLab domain rebuilds the environment contract preview.
5. The selected staging pool is inspected again and a host candidate is chosen.
6. The deploy domain skips Terraform and prepares an app-deploy request for that host.
7. The backend downloads the GitLab source archive.
8. The release is extracted on the target host.
9. Docker port collision is checked on that host.
10. `docker compose up -d --build` runs.
11. the typed healthcheck contract is verified:
    - `http` -> `GET http://127.0.0.1:<port><path>`
    - `tcp` -> open port check
    - `command` -> command retry until exit code `0`
    - `none` -> skip

## Data boundary

The platform DB currently stores:

- GitLab project inventory
- project-level environment contracts
- staging host registry entries
- task metadata and logs
- future Postgres resource metadata

If `database_required=true`, the current staging deploy is blocked.

## Not implemented

- capacity-aware host scheduling
- automatic host creation when a pool is saturated
- drain-first pool balancing
- Postgres provisioning
- `DATABASE_URL` injection
- webhook or merge driven redeploy
- snapshot automation
- rollback automation
- production execution flow
