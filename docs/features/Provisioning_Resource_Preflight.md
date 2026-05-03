# Provisioning Resource Preflight

## Summary

Gjallar checks selected Proxmox resources before VM provisioning starts.

This complements runtime readiness:

```text
Provisioning Readiness = Terraform/Ansible/Proxmox env/runtime readiness
Resource Preflight = selected node/template/storage/network/identity/static-IP validity
Provisioning Review = user request summary before Launch
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
  "network_ids": ["vmbr0"],
  "server_name": "gjallar-smoke-preflight",
  "disk_size_gb": 50,
  "vm_ip": "192.168.2.50/24",
  "vm_gateway": "192.168.2.1"
}
```

Optional:

```json
{
  "vmid": 202
}
```

`vmid` is currently used for collision preflight only. Gjallar does not yet force Terraform to allocate that target VMID.

Response shape:

```json
{
  "status": "ready|warning|error",
  "summary": "...",
  "checks": [
    { "id": "target_node", "label": "Target node", "status": "ok|warning|error" },
    { "id": "template", "label": "Template", "status": "ok|warning|error" },
    { "id": "template_readiness", "label": "Template readiness", "status": "ok|warning|error" },
    { "id": "storage", "label": "Storage", "status": "ok|warning|error" },
    { "id": "storage_capacity", "label": "Storage capacity", "status": "ok|warning|error" },
    { "id": "networks", "label": "Networks", "status": "ok|warning|error" },
    { "id": "vm_identity", "label": "VM identity", "status": "ok|warning|error" },
    { "id": "static_network", "label": "Static network", "status": "ok|warning|error" }
  ],
  "next_actions": [],
  "target": {
    "node": "...",
    "template_id": "...",
    "storage_id": "...",
    "network_ids": [],
    "server_name": "...",
    "vmid": null,
    "disk_size_gb": 50,
    "vm_ip": null,
    "vm_gateway": null
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

### Template readiness

- Checks selected template config for qemu guest agent and cloud-init readiness signals.
- Missing signals return `warning`, not `error`, because template conventions differ by environment.

### Storage

- Selected storage exists on the selected target node.
- If storage content is known and does not include `images`, the check returns warning.

### Storage capacity

- Compares requested `disk_size_gb` with storage `available_gb` when available.
- If free space is unknown, returns warning.
- If requested disk size exceeds known free space, returns error.
- Frontend wizard sends the same default disk size as provisioning: `50GB`.

### Networks

- Selected bridge IDs exist on the selected target node.
- Missing bridge blocks provisioning.

### VM identity

- VM name collision is checked on the target node.
- VMID collision is checked cluster-wide because Proxmox VMIDs are cluster-unique.
- `vmid` is optional and currently only a preflight collision hint, not Terraform target VMID assignment.

### Static network

- Static IP mode requires both `vm_ip` and `vm_gateway`.
- `vm_ip` must be IPv4 CIDR, for example `192.168.2.50/24`.
- Gateway must be IPv4 and inside the VM IP subnet.
- VM IP must not equal gateway.
- VM IP must not be subnet network/broadcast address for normal subnets.

## Launch gating

The Create VM wizard blocks `Provision VM` when:

- provisioning readiness is `error` or unavailable,
- resource preflight is `error` or unavailable,
- readiness/preflight request failed,
- readiness/preflight is still loading.

Warnings are shown but allowed so the operator can intentionally proceed after review.

## Timeout avoidance

If the selected node does not exist, Gjallar does not call node-scoped storage/network APIs.

This avoids slow Proxmox timeouts such as:

```text
/nodes/{missing-node}/storage
/nodes/{missing-node}/network
```

## Frontend

Create VM review shows:

```text
Provisioning Readiness
Resource Preflight
Provisioning Review
```

The Resource Preflight panel displays:

- OK/warning/error counts
- per-resource checks
- next actions
- manual refresh button

## Verification

Automated tests:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m unittest tests.test_resource_preflight -v
PYTHONPATH=. .venv/bin/python -m unittest tests.test_provision_route tests.test_deployment_service_logs -v

cd ../frontend
node tests/resourcePreflight.test.mjs
node tests/provisioningPayload.test.mjs
```

Full verification includes frontend lint/build, backend unittest discovery, Terraform validate, compileall, and `git diff --check`.

Real smoke:

```text
GET /api/provision/readiness
HTTP 200
status: ready

POST /api/provision/preflight
payload: yoonmanserver / yoonmanserver/118 / machine-mainnode / vmbr0 / disk_size_gb=50
HTTP 200
status: warning
warnings: template cloud-init not detected, storage free space unknown

POST /api/provision/preflight with invalid static network address
status: error
static_network: vm_ip host address must not be the subnet network or broadcast address

POST /api/provision/preflight with invalid storage
status: error
storage: local-lvm is not available on node yoonmanserver
```
