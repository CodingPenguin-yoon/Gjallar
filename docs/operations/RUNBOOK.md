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
