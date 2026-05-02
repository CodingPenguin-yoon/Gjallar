# Gjallar Next Work

## 1. Finish legacy cleanup

- remove or archive old Heimdall staging/GitLab documents
- finish replacing user-facing `deploy` wording with `provision` / `VM operation`
- keep `/api/deploy` only as a compatibility endpoint until a migration is planned

## 2. Improve VM provisioning UX

- clarify each wizard step
- show selected node/template/storage/network summary before launch
- improve validation errors for static IP and missing fields
- rename Launch/Deploy copy to Provision/Create VM where appropriate

## 3. Strengthen lifecycle safety

- add confirmation for destructive actions
- add clearer task logs for start/shutdown/stop/reboot/delete
- verify final VM state after each lifecycle operation

## 4. Improve inventory performance model

Current state:

- blocking Proxmox inventory handlers run as sync `def`
- VM inventory uses a short TTL cache

Next steps:

- add singleflight-style request coalescing for duplicate refreshes
- add background inventory collection
- serve UI from cached inventory snapshots
- add per-node concurrency/rate limits

## 5. Monitoring and risk baseline

After the VM operations baseline is stable, add first risk views:

- backup missing/failed signals
- old snapshot detection
- guest agent missing/not responding
- storage usage risk
- stopped/unused VM candidates

## 6. Later integrations

Only after the core VM operations product is stable:

- backup/report exports
- policy checks
- approval-based remediation
- Ansible/Terraform/OpenTofu integration where it supports VM operations directly
