# Heimdall

Heimdall is a staging-first deployment control plane for GitLab projects on Proxmox.

## What works now

- `Create Instance` can provision a VM from a template through Terraform and Ansible.
- `Create as staging host` can auto-register a successfully bootstrapped VM into the staging host registry.
- `Instance List` reads the staging host registry, marks registered hosts, and shows VM IPs when they can be resolved.
- the staging host registry groups hosts by `environment` and `pool_key`
- `GitLab Workspace` now edits `.heimdall/project.yaml` inside the `Project Setup` flow
- `GitLab Workspace` stores a project-side environment contract:
  - `deployment_environment`
  - `deployment_pool_key`
  - `requested_app_port`
  - `database_required`
  - `deploy_branch`
- `Deploy Staging` re-validates that contract, picks a ready host from the selected staging pool, skips Terraform, and runs app deploy directly on that host.
- app deploy still uses the GitLab source archive, remote `docker compose up -d --build`, and typed healthcheck verification.
- task tracking exists for both wrapper tasks and linked deploy tasks.

## Current staging model

There are three connected layers right now.

### 1. Staging host provisioning

- operators create a VM in `Create Instance`
- enabling `Create as staging host` keeps the current server/template/storage/network flow, but auto-adds the `base` and `docker` Ansible roles
- the VM is registered into `staging_hosts` only when:
  - Terraform returns a VM IP
  - Ansible bootstrap actually runs
  - Ansible finishes successfully
- the current preset registers hosts into `environment=staging`, `pool_key=default`
- `Instance List` shows which VMs are already in the staging host registry

### 2. Staging pool preview

- the backend exposes pool inventory and per-pool live preview
- live preview inspects each ready host over SSH
- the preview reports:
  - ready vs blocked host counts
  - available ports in the configured environment range
  - requested-port availability
  - a selected host candidate

### 3. GitLab project deploy

- `Project Setup` now includes both:
  - a repo-side manifest step for `.heimdall/project.yaml`
  - a platform-side environment contract step
- if the file exists, it can be read and updated
- if the file is missing, a draft can be generated and committed
- project settings now store an environment contract instead of user-facing staging flags
- the main user choices are `Environment`, `Host pool`, `App port`, and `Database required`
- current execution is staging-only:
  - `deployment_environment=staging` is deployable
  - `deployment_environment=production` can be saved, but `Deploy Staging` will refuse to run
- GitLab deploy now schedules from the staging host registry and selected pool

## Repository contract

- the repo must contain `.heimdall/project.yaml`
- the code expects `.heimdall/project.yaml`, not `.heimdal`
- current deploy fields used from the manifest:
  - `deploy.compose_file`
  - `deploy.healthcheck`
  - optional fallback: `deploy.app_port`

## Not implemented yet

- Postgres provisioning and `DATABASE_URL` injection
- capacity-aware pool balancing
- automatic new host creation when pools are saturated
- webhook or merge driven auto redeploy
- release snapshot automation
- rollback automation
- production execution flow

## Documentation

Start at [docs/README.md](docs/README.md).

For the current implementation snapshot, read [docs/updates/2026-05-02_COMPLETED_WORK_SUMMARY.md](docs/updates/2026-05-02_COMPLETED_WORK_SUMMARY.md).
