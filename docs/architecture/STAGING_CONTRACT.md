# Staging Contract

This document defines the current staging input contract in code.

## 1. Create Instance contract

`Create Instance` is still the source of truth for VM creation.

Required inputs:

- `server_id`
- `template_id`
- `storage_id`
- at least one `network_id`

Optional inputs:

- `cpu_cores`
- `memory_gb`
- `disk_size_gb`
- `vm_ip`
- `vm_gateway`
- `ansible_packages`
- `ansible_roles`

Preset flag:

- `create_as_staging_host`

When `create_as_staging_host=true`:

- the UI auto-adds `base` and `docker` roles
- the backend still requires normal VM provisioning success
- registry registration only happens after VM IP resolution and successful Ansible bootstrap
- the current preset registers the host as:
  - `environment=staging`
  - `pool_key=default`
  - `role=shared`

Static network rule:

- `vm_ip` and `vm_gateway` must be provided together
- `vm_ip` must be an IPv4 CIDR like `192.168.2.120/24`
- `vm_gateway` must be a valid IPv4 address

## 2. Staging host registry contract

The registry persists successful staging hosts in `staging_hosts`.

Stored fields:

- `environment`
- `node`
- `vmid`
- `name`
- `host_ip`
- `host_user`
- `pool_key`
- `role`
- `bootstrap_status`
- `enabled`
- `drain_mode`
- `source_task_id`

Identity rules:

- `node + vmid` is unique
- `host_ip` is unique

Pool rules:

- pools are grouped by `environment + pool_key`
- pool state is exposed as:
  - `available`
  - `full`
  - `empty` for preview requests against missing pools
- ready hosts are hosts where:
  - `bootstrap_status=ready`
  - `enabled=true`
  - `drain_mode=false`

Live preview rules:

- the backend inspects ready hosts over SSH
- it reads listening TCP ports through `ss` or `netstat`
- it calculates `available_port_options` inside the environment port range
- it returns:
  - `requested_port_available`
  - `suggested_app_port`
  - `selected_host`
  - host counts and preview summaries

## 3. GitLab environment contract

Required project settings for staging execution:

- `deployment_environment`
- `deployment_pool_key`
- either:
  - `requested_app_port`
  - or manifest fallback `deploy.app_port`
- `deploy_branch`

Related repo-side contract:

- `.heimdall/project.yaml` is stored separately from the environment contract, but edited in the same `Project Setup` flow
- the UI now supports:
  - read current file from GitLab
  - create the file when missing
  - update the file when present

Persisted project settings now include:

- `deployment_environment`
- `deployment_pool_key`
- `requested_app_port`
- `database_required`
- `database_engine`
- `database_mode`
- `migration_command`
- `deploy_branch`
- `bootstrap_strategy`
- `notes`

Current user-facing environment options:

- `staging`
- `production`

Execution rules:

- `staging` can be executed through `Deploy Staging`
- `production` can be saved, but `Deploy Staging` will block it

Preview fields returned to the UI:

- `deployment_pool_summary`
- `port_range_summary`
- `available_port_options`
- `effective_app_port`
- `app_port_source`
- `suggested_app_port`
- `requested_port_available`
- `readiness_summary`

Readiness rules for `Deploy Staging`:

- project must not be archived
- `deployment_environment` must be `staging`
- a pool must be selected
- the selected pool must be deployable
- an effective app port must exist
- the port must be available in the selected pool
- manifest must validate
- `database_required` must still be `false`

## 4. Database contract

- `database_required=false`
  - staging deploy is allowed
- `database_required=true`
  - staging deploy is blocked

Current limitation:

- Postgres provisioning does not exist yet
- `DATABASE_URL` injection does not exist yet
- if DB is required, `database.engine` must be `postgres`

## 5. Repository contract

The repo must contain `.heimdall/project.yaml`.
The code expects `.heimdall/project.yaml`, not `.heimdal`.

Current UI behavior:

- if the file is missing, the manifest step in `Project Setup` can generate a draft and create it
- if the file exists, the manifest step in `Project Setup` can load and update it
- the save path accepts parseable YAML objects even if the manifest is still contract-invalid
- after save, the backend immediately recalculates `manifest_status`

Minimum manifest rules:

- `name` must be a non-empty string
- `runtime` must be a non-empty string
- `deploy.strategy == docker-compose`
- `deploy.compose_file` must be a non-empty relative path
- `deploy.healthcheck` is required unless legacy `deploy.healthcheck_path` is used
- supported healthcheck types:
  - `http`
  - `tcp`
  - `command`
  - `none`
- `deploy.healthcheck.path` must start with `/` when `type=http`
- `deploy.healthcheck.command` must be non-empty when `type=command`
- `deploy.healthcheck.port` must be positive when provided
- `environments.staging.enabled == true`
- if `database.required == true`, `database.engine == postgres`

Runtime rule:

- `deploy.app_port` is optional and acts as a fallback when the project does not store `requested_app_port`
- the effective app port must not collide with another running Docker project on the selected host

## 6. Environment port ranges

Port ranges are environment-scoped.

- `DEPLOYMENT_PORT_RANGE_STAGING`
  - default: `3000-3499`
- `DEPLOYMENT_PORT_RANGE_PRODUCTION`
  - default: `4000-4499`

## Example manifest

```yaml
name: sample-app
runtime: node

deploy:
  strategy: docker-compose
  compose_file: deploy/docker-compose.yml
  healthcheck:
    type: http
    path: /health

database:
  required: false

environments:
  staging:
    enabled: true
```
