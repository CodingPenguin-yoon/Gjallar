# Create VM End-to-End Smoke — 2026-05-03

See also shared source-of-truth note:

```text
/mnt/hermes_data/프로젝트/Gjallar/05_기능설명/Create_VM_End_to_End_Smoke_2026-05-03.md
```

## Result

Actual Proxmox VM provisioning was tested on `yoonmanserver2` using the user-approved smoke range `192.168.2.140~150`.

No test VMs were deleted. They were stopped only.

Final smoke VMs:

```text
yoonmanserver2/122 gjallar-smoke-ip140 192.168.2.140 stopped
yoonmanserver2/123 gjallar-smoke-ip141 192.168.2.141 stopped
```

## Failed-path smoke

Task id:

```text
7c224629-d2b4-4439-8dd4-50a2996bce4d
```

Payload used `disk_size_gb=50` with template `yoonmanserver2/107`.

Terraform/Proxmox cloned the VM, but the task failed because the template disk was 200GB and the request attempted to shrink it to 50GB:

```text
Error: disk resize failure: requested size (50G) is lower than current size (200G)
```

VM left stopped:

```text
yoonmanserver2/122 gjallar-smoke-ip140 192.168.2.140 stopped
```

## Fix from smoke finding

Resource preflight now includes `template_disk_size`:

- Parses selected template disk sizes from config, e.g. `scsi0=...,size=200G`.
- Ignores cloud-init/cdrom-style devices.
- Blocks if `disk_size_gb` is lower than the template disk size.

Validation:

```text
disk_size_gb=50  -> preflight error
disk_size_gb=200 -> no template_disk_size error
```

## Success-path smoke

Task id:

```text
bd68b9fb-5985-47bc-9012-efd145bf48a9
```

Payload used:

```json
{
  "server_id": "yoonmanserver2",
  "template_id": "yoonmanserver2/107",
  "storage_id": "vm-storage",
  "network_ids": ["vmbr0"],
  "server_name": "gjallar-smoke-ip141",
  "cpu_cores": 2,
  "memory_gb": 4,
  "disk_size_gb": 200,
  "vm_ip": "192.168.2.141/24",
  "vm_gateway": "192.168.2.1",
  "skip_ansible": true
}
```

Result:

```text
Apply complete! Resources: 1 added, 0 changed, 0 destroyed.
vm_id = 123
vm_ip = "192.168.2.141"
vm_name = "gjallar-smoke-ip141"
```

The VM was then gracefully shut down via Gjallar lifecycle action:

```text
POST /api/instances/action
node: yoonmanserver2
vmid: 123
action: shutdown
```

Final status:

```text
yoonmanserver2/123 gjallar-smoke-ip141 stopped
```

## Verification

```text
backend unittest discover: 31 tests passed
python3 -m compileall backend/app backend/tests: passed
terraform -chdir=infra/terraform validate: passed
git diff --check: passed
```

## Follow-ups

- Improve storage free-space parsing; current smoke still reports storage free as unknown.
- Treat Proxmox thin-pool overcommit warnings as an operational risk signal.
- Decide whether the UI should auto-raise disk size to template minimum or force the user to edit it manually.
- User should manually delete stopped smoke VMs when ready.
