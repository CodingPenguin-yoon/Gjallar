# Gjallar

**English** · [한국어](README.ko.md)

**Manage Proxmox VMs, templates, monitoring, and recovery from one web interface.**

Gjallar is a web operations tool for Proxmox VE. It connects resource discovery, change review, execution, and result verification. Proxmox remains the execution engine and the source of truth; Gjallar keeps accounts, approvals, operation history, and recovery records.

> **Under active development.** The features below are implemented in the current code. Live validation varies by feature and environment; implementation does not mean every workflow is production-validated. See the validation status below and the [roadmap](project-docs/roadmap.md).

## Implemented features

The web interface has six main areas: overview, VM management, templates, monitoring, infrastructure, and operation history. Account and session management are available from the account menu.

| Area | Current implementation |
|---|---|
| Installation and connection | Managed Docker Compose bootstrap, service start/status/stop, and image upgrades with an unchanged DB schema. Web-based Proxmox registration through dedicated token issuance or existing-token import, verification, and activation |
| Overview and inventory | Cluster overview, node comparison and detail, and VM/template/storage/network observations. New connections discover current and future resources without entering individual resource IDs; mutation capabilities are selected separately |
| VM creation and power | Clone an existing Proxmox template using direct specifications or an optional preset; review and approve the plan; optionally boot and verify guest agent, IP, and cloud-init. Start and graceful shutdown with result checks |
| VM configuration | Change CPU cores and memory on supported stopped VMs; expand NFS `scsi0` disks; change an existing NIC's bridge/VLAN; full clone and explicit deletion with source/preserved-resource checks |
| Web console | Authenticated noVNC screen console for running QEMU VMs, with explicit connection and disconnection |
| Templates | Convert a prepared stopped VM to a template; build from the fixed AlmaLinux 9.8 GenericCloud x86_64 catalog; explicitly clean up owned templates/uploaded sources; inspect test deployments and record operator-confirmed access results |
| Monitoring | Current node/VM/storage metrics, PVE history for hour/day/week/month/year, threshold exceedance/clearance intervals, operation failure/recovery history, and risk/readiness/capacity/placement insights |
| Backup and restore | List backups and explicitly back up supported stopped VMs to NFS; restore an archive to a separate VMID with its NIC disconnected; inspect preservation, configuration, and subsequent boot/guest-agent observations |
| Maintenance and host settings | Manually move supported stopped VMs between nodes using shared NFS; inspect node maintenance readiness; register/update existing directory storage; create/update limited VM Linux bridges and apply node-wide network changes |
| Operations and accounts | Operation status, events, evidence, creation history, and supported recovery observations; externally executed Guided `qm unlock`; local login, sessions, and `viewer`/`operator`/`admin` roles |

Detailed support conditions and execution procedures are maintained in the [architecture](project-docs/architecture.md) and [operations runbook](project-docs/development.md).

## Validation status and limits

Recorded live checks include managed installation on macOS, existing-token import, full-cluster inventory, template-based creation with boot/DHCP/guest-agent/cloud-init checks, power operations, CPU/memory changes, disk expansion, NIC changes, full clone, deletion, and console connection/disconnection. Monitoring has been compared with actual PVE metrics and history. These checks cover specific environments and targets, not every supported combination.

Template conversion/image building/cleanup, backup creation/restore, stopped-VM node migration, and host storage/bridge changes still need live mutation validation. New Proxmox login/token issuance and the remaining installation/authentication combinations also need validation. Console connection checks do not establish guest login success; actual SSH login and some alert transition/recovery scenarios remain unverified. The [roadmap](project-docs/roadmap.md#진행-상태) tracks the evidence and remaining work.

- Product operations are web-only. The local `gjallar` tool retains `bootstrap`, `service start/status/stop`, and `upgrade`; user CLI/TUI operations have been removed.
- VM creation requires an existing Proxmox template. ISO installation and empty-VM creation are not supported.
- Configuration, clone, backup, restore, and migration support specific VM/storage/network combinations. Disk shrinking, running-VM hotplug, live migration, and automatic DRS are outside the current scope.
- Monitoring reads PVE observations/history on request. There is no separate telemetry store, continuous collector, or external alert delivery.
- Restore preserves the original VM and backup and initially leaves the new VM stopped with its NIC disconnected. Boot and access checks are separate steps.
- Host settings are limited to existing directory storage and VM Linux bridges. Management IP/gateway changes, physical NIC rearrangement, disk formatting, and Ceph management are not supported.

### Honest state and explicit outcomes

- Missing or failed Proxmox connections are reported as such; production does not substitute fake inventory.
- Partial observations remain visible with their limitations. Create input and review can use a partial base snapshot; execution has additional source and action-specific checks.
- Recovery observation rechecks Proxmox and reconciles local records. It does not blindly replay the original change. The background recovery observer is disabled by default.
- Monitoring uses Proxmox observations and available history; it does not run a separate telemetry store. A running VM does not by itself prove that its applications are healthy.

## Run the current application

For the managed bootstrap installer and manual setup, follow the [operations runbook](project-docs/development.md) for dependency installation, environment configuration, PostgreSQL initialization, and account creation.

### Managed installation

The Python installation tool runs the application and PostgreSQL through Docker Compose. It requires Python **3.13+**, Docker, Compose **2.20+**, and an application image built from this repository. A public release registry and signed release manifest are not yet provided.

Follow the runbook's [installer preparation](project-docs/development.md#설치-도구-준비와-웹-접속) and [new installation](project-docs/development.md#새-로컬-설치-별도-실행-승인검증-대상) procedures. The default web binding is loopback; new installations can explicitly use `--bind-address 0.0.0.0` for access from other machines. Database ports are not published, and TLS proxy setup is separate.

Managed initialization is explicit: normal service startup does not run migrations or recreate the administrator. `upgrade` only switches between images with the same DB schema. Existing-database migration follows a separate runbook procedure.

After installation, sign in through the browser and register or import a connection under **Infrastructure → Proxmox connection**. Select the permitted operations, verify and activate the connection, then restart all Gjallar server processes as instructed in the runbook. Existing environment-based Proxmox configuration is also supported.

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

Follow the runbook's container instructions. The legacy manual container entrypoint runs migrations, preset seeding, and optional administrator bootstrap on startup; it differs from managed service startup. Review the existing-database procedure before pointing it at an existing installation.

## Development and verification

The repository contains a React frontend, FastAPI backend, PostgreSQL/Alembic persistence, and a Proxmox API adapter.

| Location | Responsibility |
|---|---|
| `frontend/` | Web interface |
| `backend/app/` | API, observations, operations, and Proxmox integration |
| `backend/alembic/` | Database migrations |
| `backend/tests/` | Backend, contract, and integration tests |
| `client/` | Local installation/service tool only; historical package path retained |
| `project-docs/` | Shared product and engineering documentation |

With the installer, backend, and frontend development dependencies installed:

```bash
pnpm run verify
```

This runs installer and backend tests, frontend tests, ESLint, and the frontend production build. PostgreSQL integration tests require a separate disposable test database configured as described in the runbook.

For container-based verification with Docker available:

```bash
pnpm run verify:container
```

Container verification builds the installer/backend test images and production image; it does not start the application or run live Proxmox mutations.

## Documentation

Detailed project documentation is currently maintained in Korean.

- [Documentation home](project-docs/README.md)
- [Product direction and scope](project-docs/prd.md)
- [Current architecture](project-docs/architecture.md)
- [Setup, operations, and troubleshooting](project-docs/development.md)
- [Roadmap](project-docs/roadmap.md) · [Work log](project-docs/work/README.md)
- [Backend guide](backend/README.md) · [Frontend guide](frontend/README.md)
