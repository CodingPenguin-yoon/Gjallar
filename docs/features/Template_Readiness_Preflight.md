# Template Readiness Preflight

## Summary

Gjallar Resource Preflight now checks whether the selected VM template exposes basic cloud-init and qemu guest agent readiness signals before provisioning starts.

This helps explain cases where:

```text
VM clone succeeds
IP discovery is delayed or missing
Ansible handoff fails
```

## Endpoint

Included in:

```text
POST /api/provision/preflight
```

Additional check ID:

```text
template_readiness
```

## Signals

### qemu guest agent

Considered ready when Proxmox template config has:

```text
agent=1
enabled=1
```

### cloud-init

Considered ready when template config has either:

```text
cloudinit/cloud-init disk reference
ipconfig* key
```

Examples:

```text
ide2: local-lvm:cloudinit,media=cdrom
ipconfig0: ip=dhcp
```

## Status policy

### ok

Template exists and both guest-agent and cloud-init readiness signals are detected.

### warning

Template exists but one or more readiness signals are missing or config cannot be loaded.

Gjallar keeps this as warning, not blocking error, because template conventions may differ across environments. Operators should review before relying on automatic IP discovery or Ansible handoff.

### error

Template does not exist.

## Real smoke

Request:

```json
{
  "server_id": "yoonmanserver",
  "template_id": "yoonmanserver/118",
  "storage_id": "machine-mainnode",
  "network_ids": ["vmbr0"]
}
```

Observed result:

```text
HTTP 200
status: warning

template_readiness: warning
Template exists but cloud-init readiness was not detected.
agent=1; cloud_init=False
```

Interpretation:

```text
The selected template has guest-agent enabled, but cloud-init readiness was not detected.
VM clone may still work, but automatic IP/cloud-init/Ansible handoff may be unreliable.
```

## Verification

```bash
cd backend && PYTHONPATH=. .venv/bin/python -m unittest tests.test_resource_preflight -v
cd backend && PYTHONPATH=. .venv/bin/python -m unittest discover -s tests
node frontend/tests/resourcePreflight.test.mjs
cd frontend && npm run lint && npm run build
terraform -chdir=infra/terraform validate
python3 -m compileall backend/app backend/tests
git diff --check
```
