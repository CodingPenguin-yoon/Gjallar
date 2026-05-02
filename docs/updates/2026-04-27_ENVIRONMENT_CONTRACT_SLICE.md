# 2026-04-27 Environment Contract Slice

This document records the work completed in the 2026-04-27 slice.

## Summary

Today the GitLab deployment setup moved from staging-specific flags to an environment-contract model.

The important shift is:

- before: user-facing settings were closer to workflow flags
- now: user-facing settings define where and how the app should run

The current contract is centered on:

- `Environment`
- `Host pool`
- `Requested app port`
- `Database required`

The GitLab Workspace flow is now:

- `Overview`
- `Project Setup`

## What changed

### 1. Project settings schema

Added project-level contract fields:

- `deployment_environment`
- `deployment_pool_key`
- `requested_app_port`

Added host-registry fields used by pool execution:

- `staging_hosts.environment`
- `staging_hosts.host_user`

Migration:

- `backend/alembic/versions/20260426_0010_environment_contract_fields.py`

### 2. Staging pool preview

The staging registry is no longer just a list.

New capabilities:

- list pools by `environment + pool_key`
- preview a specific pool live
- compute host availability
- compute allowed port candidates
- select a host candidate for the requested port

Main code:

- `backend/app/domains/staging/service.py`
- `backend/app/domains/staging/router.py`

### 3. GitLab Workspace redesign

The project setup UI now behaves like an environment-contract editor.

What the UI shows now:

- environment selection
- pool-state summary:
  - no registered pool
  - available pool exists
  - pools exist but are currently blocked / full
- pool selection
- allowed port range
- available port suggestions
- DB requirement

Main code:

- `frontend/src/components/GitLabWorkspace.jsx`
- `frontend/src/services/api.js`

### 3-1. Manifest step inside Project Setup

Added a dedicated manifest-editing step inside `Project Setup` for `.heimdall/project.yaml`.
The current flow intentionally starts with deployment settings, then generates the manifest preview from those choices.

Supported cases:

- repo created from Heimdall
  - use an existing seed or generated draft
- existing external repo
  - check whether `.heimdall/project.yaml` exists
  - create it when missing
  - update it when present
- fill guided inputs first:
  - `name`
  - `runtime`
  - `deploy.compose_file`
  - `deploy.healthcheck`
- reflect platform-side port / DB choices into the generated manifest preview
- validate the generated YAML before saving

Backend support:

- read current manifest file from GitLab
- return raw content plus generated draft
- create or update the file on the selected branch
- recalculate `manifest_status` immediately after save

### 4. Deploy Staging path

`Deploy Staging` now uses the selected staging pool.

Execution path:

1. rebuild contract preview
2. validate manifest and contract
3. preview selected pool again
4. choose a ready host
5. skip Terraform for the app deploy path
6. deploy source archive with Docker Compose
7. run the typed healthcheck contract

Main code:

- `backend/app/domains/gitlab/service.py`

### 5. Manifest rule change

`.heimdall/project.yaml` still requires:

- `runtime`
- `deploy.compose_file`
- `deploy.healthcheck`
- `environments.staging.enabled`

But `deploy.app_port` is no longer mandatory.

Current behavior:

- if project settings store `requested_app_port`, that value wins
- otherwise manifest `deploy.app_port` is used as a fallback

## Validation completed

- `python3 -m compileall backend/app`
- `pnpm --dir frontend build`
- `cd backend && ./venv/bin/alembic upgrade head`

Database state after the work:

- Alembic head: `20260426_0010`

## Known limits after this slice

- production contract storage exists, but production execution does not
- host scheduling is still capacity-unaware
- new VM creation on pool saturation is not automated yet
- `database_required=true` still blocks deploy
- snapshot and rollback are still not implemented
