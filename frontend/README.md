# Frontend

The frontend is the React + Vite operator UI for Heimdall.

## Main screens

- `Create Instance`
- `Instance List`
- `Task Board`
- `Monitoring`
- `GitLab Workspace`
- `LLM Assistant`

## Current screen behavior

### Create Instance

- provisions a VM from the current wizard inputs
- supports `Create as staging host`
- that preset keeps the current server/template/storage/network flow
- the preset auto-includes `base` and `docker` roles

### Instance List

- loads Proxmox VM inventory
- loads staging host registry entries
- marks matching VMs as `Staging Host`
- shows resolved VM IPs when they can be discovered

### GitLab Workspace

- supports inventory sync
- supports GitLab project creation
- supports `.heimdall/project.yaml` read/create/update inside `Project Setup`
- generates manifest YAML from guided setup fields before save
- supports project environment-contract editing in the same setup flow
- shows manifest validation state
- previews environment pool state and port availability
- supports manual `Deploy Staging`

Current limitation:

- only `staging` contracts are executable today
- `production` can be selected and saved, but not deployed yet

## Run

From repo root:

```bash
pnpm frontend
```

Directly:

```bash
cd frontend
pnpm dev
pnpm build
```

The frontend talks to the backend through `/api`.
