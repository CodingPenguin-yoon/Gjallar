# Gjallar VM Provisioning Contract

This document defines the active VM provisioning contract.

## Endpoint compatibility

The current API endpoint is still:

```text
POST /api/provision
```

This name is legacy from Heimdall. Semantically, the endpoint now represents VM provisioning.

## Required inputs

- `server_id`: target Proxmox node
- `template_id`: source template
- `storage_id`: target storage
- `network_ids`: one or more network/bridge IDs

## Optional inputs

- `server_name`: VM name
- `cpu_cores`: requested CPU cores
- `memory_gb`: requested memory
- `disk_size_gb`: requested disk size
- `vm_ip`: static VM IP in CIDR form, for example `192.168.2.120/24`
- `vm_gateway`: gateway IP used with static IP mode
- `ansible_packages`: optional bootstrap packages
- `ansible_roles`: optional bootstrap roles

## Static network rule

- `vm_ip` and `vm_gateway` must be provided together
- `vm_ip` must be an IPv4 CIDR
- `vm_gateway` must be a valid IPv4 address

## Task behavior

A successful request returns a task ID. Operators should track progress through the task board/log APIs.

Expected high-level task phases:

1. prepare Proxmox/Terraform variables
2. clone/provision VM from template
3. apply requested CPU/RAM/disk/network options where supported
4. resolve VM identity/IP metadata
5. optionaly run bootstrap packages/roles
6. record result and expose it in inventory

## Removed legacy behavior

The active contract no longer includes:

- `create_as_staging_host`
- staging registry registration
- GitLab environment contracts
- app deployment from source repositories
- Deploy Staging execution
