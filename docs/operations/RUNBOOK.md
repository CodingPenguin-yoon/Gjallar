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

- Do not commit `.env`, `data/`, tokens, keysHsecrets, or local runtime artifacts.
- Treat `/api/deploy` as a compatibility endpoint for VM provisioning until renamed with a migration plan.
- Proxmox inventory calls are cached briefly; use manual refresh or wait for TTL expiry when checking recent changes.
