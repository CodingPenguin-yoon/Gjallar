# Gjallar

**English** · [한국어](README.ko.md)

**Run your Proxmox environment from one place.**

Gjallar is building a simpler way to prepare templates, manage VMs, monitor infrastructure, and recover from problems. The goal is to finish everyday Proxmox operations through Gjallar's web interface, without switching back to the Proxmox management UI.

Proxmox remains the engine and the source of truth. Gjallar connects the steps: understand the current state, make a change, and verify the result.

> **Under active development.** Product operations are web-only. The local tool retains installation, service management, and same-schema image upgrades; the user CLI and TUI have been removed. See the architecture and roadmap for implemented features and remaining live validation.

## What matters

- **Easy to start.** Make installation and Proxmox connection straightforward.
- **Finish the job.** Keep preparation, management, monitoring, and recovery in one workflow.
- **Trust the result.** Show what changed, whether it worked, and what still needs attention. An accepted request is not proof of success.

The immediate focus is a solid everyday tool for individual operators and small teams. Enterprise features and AI assistance are later extensions of that foundation.

## The experience we are building

| Area | Goal |
|---|---|
| Setup | Simple bootstrap on macOS and Linux, connection checks, and clear configuration guidance |
| Templates | Register, prepare, validate, and manage reusable VM templates |
| VM management | Create, clone, remove, start, shut down, change resources, and access VM consoles |
| Monitoring | See node, VM, and storage health, resource usage, trends, and failed tasks |
| Recovery | Inspect failures, manage backups, restore VMs, and verify outcomes |
| Infrastructure | Inspect and manage the nodes, storage, and networks needed for everyday work |
| Web operations | Complete supported workflows through the web interface |

**The priority question: “What still makes an operator leave Gjallar and open Proxmox?”** Each supported workflow should be complete before adding more surface area. Proxmox's own emergency administration paths remain available.

These are product goals, not a list of shipped features. See the [product specification](project-docs/prd.md) for the agreed direction and current implementation boundary.

## Available today

| Capability | Current support |
|---|---|
| Inventory | Node, VM, template, storage, and network observations; VM details linked to recent operations |
| Insights | Risk, readiness, capacity, and placement findings with evidence and observation freshness |
| VM creation | Clone an existing Proxmox template, enter specifications directly or use an optional preset, review and approve the plan, and optionally boot and verify |
| Power operations | Start and graceful shutdown with pre-checks and result verification |
| Guided unlock | A restricted `qm unlock` procedure executed externally by the operator, followed by API verification |
| Operation history | Status, event timelines, evidence, job history, and supported recovery observations |
| Accounts | Local authentication, sessions, and `viewer`, `operator`, and `admin` roles |

### Honest state and explicit outcomes

- Missing or failed Proxmox connections are reported as such; production does not substitute fake inventory.
- Partial observations remain visible with their limitations. Create input and review can use a partial base snapshot; execution has additional source and action-specific checks.
- Recovery observation rechecks Proxmox and reconciles local records. It does not blindly replay the original change. The background recovery observer is disabled by default.
- Monitoring uses Proxmox observations and available history; it does not run a separate telemetry store. A running VM does not by itself prove that its applications are healthy.

The broader VM, template, monitoring, backup/restore, and infrastructure flows are implemented with varying live-validation coverage. See the roadmap for exact limits. VM creation requires an existing Proxmox template; ISO installation and empty-VM creation are not supported.

## Run the current application

For the managed bootstrap installer and manual setup, follow the [operations runbook](project-docs/development.md) for dependency installation, environment configuration, PostgreSQL initialization, and account creation.

### Local development

Requirements: Python **3.13**, Node.js **24**, pnpm **10.34.5**, PostgreSQL, and access to a Proxmox VE API for infrastructure features.

Once the runbook setup is complete, run from the repository root:

```bash
pnpm run dev
```

Default local addresses:

- Web UI: <http://127.0.0.1:5173>
- Backend: <http://127.0.0.1:8000>

### Docker

A Dockerfile is included. The production image serves the built web interface and FastAPI backend together; PostgreSQL is configured separately.

Follow the runbook's container instructions. Container startup applies database migrations, seeds optional creation presets, and can bootstrap an administrator. Review the existing-database procedure before pointing it at an existing installation.

## Development and verification

The repository contains a React frontend, FastAPI backend, PostgreSQL/Alembic persistence, and a Proxmox API adapter.

| Location | Responsibility |
|---|---|
| `frontend/` | Web interface |
| `backend/app/` | API, observations, operations, and Proxmox integration |
| `backend/tests/` | Backend and contract tests |
| `client/` | Local installation/service tool only; historical package path retained |
| `project-docs/` | Shared product and engineering documentation |

With the required development dependencies installed:

```bash
pnpm run verify
```

For container-based verification with Docker available:

```bash
pnpm run verify:container
```

## Documentation

Detailed project documentation is currently maintained in Korean.

- [Documentation home](project-docs/README.md)
- [Product direction and scope](project-docs/prd.md)
- [Current architecture](project-docs/architecture.md)
- [Setup, operations, and troubleshooting](project-docs/development.md)
- [Roadmap](project-docs/roadmap.md) · [Work log](project-docs/work/README.md)
- [Backend guide](backend/README.md) · [Frontend guide](frontend/README.md)
