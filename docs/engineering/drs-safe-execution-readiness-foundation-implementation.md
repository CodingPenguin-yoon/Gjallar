# DRS Safe Execution Readiness Foundation Implementation Note

Date: 2026-05-28

Scope for this slice:

- Add compact DB-backed VM identity observations and migration policy memory.
- Resolve VM identity from curated read-only Proxmox inventory evidence only:
  SMBIOS UUID, VM generation ID, MAC addresses, disk volume IDs, and separate
  locator fields such as cluster, node, VMID, and name.
- Feed identity and policy evidence into DRS recommendations and final
  pre-check blockers while preserving existing route, local-storage,
  passthrough, threshold, and read-only execution blockers.
- Keep `/api/v1/drs/recommendations/{recommendation_id}/check` as the
  read-only final pre-check model. It rereads inventory, recomputes the
  recommendation, and always returns `executable: false`.

Non-goals:

- No live migration execution.
- No DRS use of Proxmox mutation APIs.
- No broad policy UI or rule engine.
- No large raw Proxmox inventory blobs in the DB.
- Create VM `observed_after` fingerprints remain supporting evidence, not the
  DRS success line.
