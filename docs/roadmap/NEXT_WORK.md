# Next Work

This document lists the next work after the current environment-contract slice.

## 1. Add capacity-aware pool scheduling

The current scheduler only proves that a ready host and free port exist.

Needed work:

- rank hosts by real capacity, not just port availability
- track CPU, memory, disk, and app-density signals
- avoid repeatedly placing everything on the first ready host
- define saturation thresholds clearly

## 2. Add host-pool operations

The registry exists, but pool lifecycle is still minimal.

Needed work:

- edit `environment` and `pool_key` after registration
- operator controls for `enabled` and `drain_mode`
- sync registry state with VM lifecycle automatically
- expose bootstrap / inspection failures more clearly

## 3. Add automatic host creation for saturated pools

The intended operating model is:

- create a shared staging host
- deploy multiple apps with Docker
- add another host when the pool is saturated

Needed work:

- define when a pool is considered full
- trigger new VM creation from that signal
- attach new VMs to the correct pool automatically
- keep host sizing standardized

## 4. Add DB automation

Required to support `database_required=true` projects.

Needed work:

- Postgres resource provisioning
- `DATABASE_URL` injection
- migration command execution rules
- resource state tracking

## 5. Add redeploy automation

Only for already-prepared staging environments.

Needed work:

- webhook or merge trigger rules
- redeploy-only flow for existing targets
- separation between first deploy and redeploy

## 6. Add snapshot and rollback

Current releases stay on disk, but rollback is still manual.

Needed work:

- release retention policy
- snapshot strategy
- rollback trigger
- rollback API or operator action
- failure recovery behavior

## 7. Add production execution flow

Production should not inherit staging rules by default.

Needed work:

- separate approval rules
- separate host pools and port policy
- separate deployment safety model
- production-specific rollback and validation
