# Gjallar Frontend

The frontend is a React + Vite operator UI for Gjallar.

## Main screens

- `Overview`: Proxmox and instance summary
- `Create Instance`: VM provisioning from template
- `Instance List`: VM/LXC inventory and lifecycle actions
- `Task Board`: long-running operation progress/logs
- `Monitoring`: operational visibility
- `LLM Assistant`: operational assistant UI

Removed legacy screen:

- GitLab Workspace

## Run

```bash
cd frontend
npm run dev -- --host 0.0.0.0 --port 5174
```

## Validate

```bash
cd frontend
npm run lint
npm run build
```

The frontend talks to the backend through `/api`. The current VM provisioning client still calls `/api/deploy` for compatibility, but UI copy should describe the action as VM provisioning or VM creation.
