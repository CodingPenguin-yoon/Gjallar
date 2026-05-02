# Gjallar

Gjallar is a Proxmox operations console for small teams and homelab-to-business environments.

It is **not** a GitLab CI/CD or staging deployment tool. The current direction is a focused Proxmox control and visibility layer:

```text
VM create/manage + instance inventory + monitoring
```

## Product direction

Gjallar helps operators see and manage their Proxmox environment without jumping between scattered scripts, dashboards, and manual checks.

Primary goals:

- show Proxmox nodes, VMs/LXCs, templates, storage, and networks
- create VMs from known templates
- perform basic VM lifecycle actions safely
- monitor instance status and resource usage
- keep long-running operations visible through task/log tracking

Out of scope for the current product direction:

- GitLab project inventory
- CI/CD pipeline management
- staging host pools
- application deployment from source repositories
- webhook-driven auto deploy
- production release automation

## Current cleanup status

This repository started as a copy of Heimdall, which was a staging-first GitLab deployment control plane.

The repo is being realigned into Gjallar. During this cleanup, some old files may still exist, but they are considered legacy unless they support the Proxmox VM/inventory/monitoring direction.

Keep:

- Proxmox inventory and VM operations
- instance list and monitoring UI
- task board / task logs for long-running operations
- minimal VM creation flow, after removing staging-specific behavior

Remove or ignore:

- GitLab workspace and GitLab API integration
- GitLab webhooks
- staging host registry / staging pool concepts
- Deploy Staging and application deployment flow
- CI/CD-oriented documentation

## Working scope

### 1. Proxmox inventory

Gjallar should show the current Proxmox environment:

- nodes
- VM/LXC instances
- templates
- storage
- networks / bridges
- IP and guest-agent-derived information when available

### 2. VM creation

Gjallar should support controlled VM creation from Proxmox templates.

The first useful flow is:

```text
select node/template/storage/network
→ choose CPU/RAM/disk/name
→ create VM
→ track progress as a task
→ show the VM in the instance list
```

This is infrastructure management, not app deployment.

### 3. Instance management

Gjallar should support basic VM operations:

- start
- shutdown
- stop when needed
- reboot
- delete/terminate with safeguards
- resource adjustment where safe

### 4. Monitoring

Gjallar should provide operational visibility:

- node status
- instance status
- CPU/RAM/disk usage
- uptime and power state
- storage usage
- task history and logs

## Near-term plan

1. Rewrite project documentation around Gjallar.
2. Remove GitLab and staging deployment entrypoints.
3. Keep Proxmox inventory, instance management, monitoring, and task tracking.
4. Rename/refactor remaining Heimdall deployment concepts into Proxmox VM operations.
5. Add risk/reporting features later, after the VM management baseline is clean.

## Repository layout

```text
backend/       FastAPI backend
frontend/      React/Vite frontend
infra/         Legacy Terraform/Ansible assets; review before reuse
backend/app/domains/proxmox/  Proxmox API integration
backend/app/domains/task/     Task status/log APIs
```

## Documentation source of truth

Project planning and operating notes are kept in shared storage:

```text
/mnt/hermes_data/프로젝트/Gjallar
```

Start there before making product or architecture changes.

## Development note

Until the cleanup is complete, treat GitLab/staging/deploy references as legacy Heimdall residue. Do not extend those paths for new Gjallar work.
