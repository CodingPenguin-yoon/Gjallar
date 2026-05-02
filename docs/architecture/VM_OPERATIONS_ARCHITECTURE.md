# Gjallar VM Operations Architecture

Gjallar is a Proxmox VM operations and monitoring console.

## Active goal

```text
Proxmox inventory → VM provisioning → lifecycle action → task/log tracking → monitoring
```

Gjallar is not a GitLab, staging, CI/CD, or application deployment control plane.

## Main components

### 1. Frontend operator UI

Main screens:

- `OverviewDashboard`: high-level Proxmox and instance summary
- `CreateInstanceWizard`: VM provisioning from a Proxmox template
- `InstanceList`: VM/LXC inventory and lifecycle entrypoints
- `MonitoringDashboard`: node, instance, storage, and runtime visibility
- `TaskBoard`: long-running operation progress and logs
- `LlmInfraChat`: assistant UI for operational questions

### 2. Backend API

Main domains:

- `app/domains/proxmox`: Proxmox inventory and VM lifecycle APIs
- `app/domains/deploy`: legacy domain name currently used for VM provisioning endpoint
- `app/domains/task`: task persistence, progress, logs, and SSE
- `app/domains/llm`: assistant/chat support

The `deploy` domain name is legacy. New code and UI copy should describe this path as VM provisioning or VM operations. New UI calls `/api/provision`; `/api/deploy` remains only as a compatibility alias.

### 3. Proxmox integration

The backend reads Proxmox node, VM/LXC, template, storage, and network information through the Proxmox API.

Inventory calls can be slow. Current mitigation:

- blocking Proxmox route handlers are sync `def` so they run outside the FastAPI event loop
- VM inventory calls use a short TTL cache via `PROXMOX_VM_INVENTORY_CACHE_TTL_SECONDS`
- future high-load design should use a background inventory collector and cached snapshots

### 4. Long-running operations

VM provisioning and lifecycle actions should be task-backed.

The user-facing flow should be:

```text
request operation → create task → run backend work → stream/log progress → verify result in inventory
```

## Explicit non-goals

- GitLab project inventory
- GitLab webhook handling
- staging host pools
- Deploy Staging
- source repository application deployment
- CI/CD or production release automation
