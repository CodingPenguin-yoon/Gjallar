# Provisioning Resource Preflight

## Summary

Gjallar checks selected Proxmox resources before VM provisioning starts.

This complements runtime readiness:

```text
Provisioning Readiness = Terraform/Ansible/Proxmox env/runtime readiness
Resource Preflight = selected node/template/storage/network validity
```

## Endpoint

```text
POST /api/provision/preflight
```

Request:

```json
{
  "server_id": "yoonmanserver",
  "template_id": "yoonmanserver/118",
  "storage_id": "machine-mainnode",
  "network_ids": ["vmbr0"]
}
```

Response shape:

```json
{
  "status": "ready|warning|error",
  "summary": "...",
  "checks": [
    { "id": "target_node", "label": "Target node", "status": "ok|warning|error" },
    { "id": "template", "label": "Template", "status": "ok|warning|error" },
    { "id": "storage", "label": "Storage", "status": "ok|warning|error" },
    { "id": "networks", "label": "Networks", "status": "ok|warning|error" }
  ],
  "next_actions": [],
  "target": {
    "node": "...",
    "template_id": "...",
    "storage_id": "...",
    "network_ids": []
  }
}
```

## Checks

### Target node

- Selected node exists in Proxmox inventory.
- Node is online or unknown.
- Missing/offline node blocks provisioning.

### Template

- Selected `template_id` exists in Proxmox template inventory.
- Supports IDs such as `node/vmid` and raw `vmid` matching.

### Storage

- Selected storage exists on the selected target node.
- If storage content is known and does not include `images`, the check returns warning.

### Networks

- Selected bridge IDs exist on the selected target node.
- Missing bridge blocks provisioning.

## Timeout avoidance

If the selected node does not exist, Gjallar does not call node-scoped storage/network APIs.

This avoids slow Proxmox timeouts such as:

```text
/nodes/{missing-node}/storage
/nodes/{missing-node}/network
```

## Frontend

Create VM review now shows a `Resource Preflight` panel with:

- OK/warning/error counts
- per-resource checks
- next actions
- manual refresh button

Panel order:

```text
Provisioning Readiness
Resource Preflight
Provisioning Review
```

## Verification

Automated tests:

```bash
cd backend && PYTHONPATH=. .venv/bin/python -m unittest tests.test_resource_preflight -v
node frontend/tests/resourcePreflight.test.mjs
```

Full verification includes frontend lint/build, backend unittest discovery, Terraform validate, compileall, and `git diff --check`.

Real smoke:

```text
POST /api/provision/preflight
payload: yoonmanserver / yoonmanserver/118 / machine-mainnode / vmbr0
HTTP 200
status: ready
```

## Template readiness extension

Resource preflight also includes `template_readiness`.

It checks selected template config for qemu guest agent and cloud-init readiness signals. Missing signals return `warning`, not `error`, because template conventions differ by environment.

See: `docs/features/Template_Readiness_Preflight.md`.
