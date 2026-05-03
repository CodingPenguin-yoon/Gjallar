# Gjallar Runbook

## 1. Local development on Codex VM

```bash
ssh codex-vm
cd /home/yoon/projects/Gjallar
```

Current dev ports:

```text
frontend: 5174
backend: 8001
```

## 2. Backend

```bash
cd backend
. .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

Runtime import smoke test:

```bash
cd backend
.venv/bin/python -c 'from app.main import app; print(app.title)'
```

Expected title:

```text
Gjallar VM Operations API
```

Redis may be unavailable in local development. The backend can still import and run, but chat/session history may not persist.

## 3. Frontend

```bash
cd frontend
npm run dev -- --host 0.0.0.0 --port 5174
```

Validation:

```bash
cd frontend
npm run lint
npm run build
```

## 4. Common verification

From repo root:

```bash
python3 -m compileall backend
git diff --check
```

## 5. VM provisioning smoke path

1. Open frontend.
2. Go to `Create Instance`.
3. Select node, template, storage, and network.
4. Choose CPU/RAM/name and optional static IP.
5. Start VM provisioning.
6. Track progress in `Task Board`.
7. Confirm the VM appears in `Instance List`.

## 6. Safety notes

- Do not commit `.env`, `data/`, tokens, keys/secrets, or local runtime artifacts.
- Use `/api/provision` for new VM provisioning calls. Treat `/api/deploy` as a compatibility endpoint only.
- Proxmox inventory calls are cached briefly; use manual refresh or wait for TTL expiry when checking recent changes.


## Provisioning runtime prerequisites

VM provisioning runs Terraform and Ansible from the backend process environment.
The host running the backend must have these executables on `PATH`:

```bash
command -v terraform && terraform version
command -v ansible-playbook && ansible-playbook --version
terraform -chdir=infra/terraform init -input=false
terraform -chdir=infra/terraform validate
```

Current Codex VM runtime verification:

```text
Terraform: v1.15.1
Ansible: 2.10.8
ansible-playbook: 2.10.8
terraform init/validate: pass
```

If missing on Ubuntu 22.04:

```bash
sudo apt-get update
sudo apt-get install -y gnupg software-properties-common curl ca-certificates lsb-release
wget -O- https://apt.releases.hashicorp.com/gpg | gpg --dearmor | sudo tee /usr/share/keyrings/hashicorp-archive-keyring.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(. /etc/os-release && echo "$VERSION_CODENAME") main" | sudo tee /etc/apt/sources.list.d/hashicorp.list >/dev/null
sudo apt-get update
sudo apt-get install -y terraform ansible
```

Note: Terraform/Ansible being installed only clears the local runtime prerequisite.
Provisioning can still fail later if Proxmox API credentials, template IDs, storage IDs,
cloud-init, or guest SSH readiness are wrong.

## 7. Provisioning readiness check

Before using `Create Instance`, verify the backend can see the required provisioning runtime/config:

```bash
curl http://127.0.0.1:8001/api/provision/readiness
```

Expected healthy result:

```text
HTTP 200
status: ready
```

The readiness endpoint checks Terraform, ansible-playbook, Terraform config, Ansible playbook,
required Proxmox API environment key presence, and `terraform validate`.
Credential values are intentionally hidden and must not be logged or committed.

If the endpoint reports `error`, fix the listed blocker before attempting VM provisioning.
If it reports `warning`, provisioning may still run, but review the shown next actions first.

## Provisioning resource preflight smoke

Use this after backend route changes or before Create VM smoke tests.

```bash
curl -sS -X POST http://127.0.0.1:8001/api/provision/preflight \
  -H 'Content-Type: application/json' \
  -d '{"server_id":"yoonmanserver","template_id":"yoonmanserver/118","storage_id":"machine-mainnode","network_ids":["vmbr0"],"server_name":"gjallar-smoke-preflight","disk_size_gb":50}'
```

Expected result for the current local environment:

```text
HTTP 200
status: warning
```

Known current warnings:

```text
template_readiness: cloud-init not detected on yoonmanserver/118
storage_capacity: storage free space unknown for machine-mainnode
```

If `storage_id`, `network_ids`, VM identity, or static IP/gateway values are invalid, the endpoint should return `status: error` with next actions instead of starting Terraform. The Create VM wizard blocks Launch on readiness/resource-preflight errors and allows warnings after operator review.

### Interpreting template readiness warnings

If `/api/provision/preflight` returns:

```text
template_readiness: warning
cloud_init=False
```

then the selected template may still clone successfully, but cloud-init/IP discovery/Ansible handoff can be unreliable. Check the Proxmox template config for cloud-init disk (`cloudinit`) and guest agent (`agent=1`).


## Template disk-size safety

Before running actual Create VM smoke, check `POST /api/provision/preflight`. If the selected template disk is larger than requested `disk_size_gb`, preflight returns `template_disk_size=error` because Proxmox/Terraform cannot shrink cloned disks.

The 2026-05-03 smoke verified this with `yoonmanserver2/107`:

```text
50GB request  -> failed shrink path, VM yoonmanserver2/122 left stopped
200GB request -> successful provisioning, VM yoonmanserver2/123 gracefully shut down
```

Do not use `/api/instances/terminate` for smoke cleanup unless explicitly approved. Stop/shutdown test VMs only.
