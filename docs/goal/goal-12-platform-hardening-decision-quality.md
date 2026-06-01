# Goal 12: Platform Hardening And Decision Quality

Status: candidate follow-on goal; not started. Start only if the user
explicitly selects this goal.

## Objective

Improve the quality of DRS decisions and the reliability of operations-console
platform behavior without adding new live mutation authority.

Goal 12 is a hardening and evidence-quality candidate. It should make stale
data, DRS blockers, audit history, error contracts, retention, and redaction
clearer before larger operational expansion.

## Starting Point

- Current DRS recommendation uses current CPU/memory pressure, bridge/storage
  evidence, red-risk exclusion, identity/policy blockers, operation-lock
  evidence, config-lock evidence, and final pre-check readiness.
- The 15-minute average/peak metrics substrate is not implemented.
- Deeper read-only advisor task/HA/quorum collection remains a gap. Current
  execution collects live pre-mutation evidence separately.
- Risks/Alerts is job-derived and is not yet a full DRS blocker/risk taxonomy.
- Goal 9 records sanitized account/session audit metadata on implemented
  mutation responses, but audit browsing API/UI is not implemented.
- API error envelope normalization, audit atomicity, and retention/redaction
  review remain hardening candidates.

## Controlling References

- `docs/goal/README.md`
- `docs/current/README.md`
- `docs/current/top-tabs/05-placement-drs-advisor.md`
- `docs/current/top-tabs/06-jobs-runs.md`
- `docs/current/top-tabs/07-risks-alerts.md`
- `docs/goal/goal-09-account-session-operations-polish.md`
- `docs/product/drs-advisor/04_DRS_RECOMMENDATION_AND_EXECUTION.md`
- `docs/architecture/api/current-api-v1.md`

## Decision Quality Scope

1. 15-minute average/peak metrics.
   - Add backend-owned resource history sufficient to show recent average and
     peak CPU/memory pressure for DRS decisions.
   - Keep current values distinct from historical averages and peaks.
2. Deeper read-only active task/HA/quorum collection.
   - Collect and expose read-only evidence for active tasks, HA resource state,
     and cluster quorum where safe and available.
   - Unknown, unavailable, stale, or ambiguous collection must remain visible
     and must not be inferred as safe.
3. Stale evidence warnings.
   - Surface age, source, and freshness of decision evidence.
   - Warn when recommendation/check evidence is too old for operator trust.
4. DRS blocker/risk taxonomy.
   - Normalize blockers and risks such as identity mismatch, unclassified VM,
     metadata incomplete, policy unknown/restricted/blocked, route unknown,
     route blocked, stale lock, active task conflict, HA/quorum uncertainty,
     migration timeout, and needs reconciliation.
   - Keep taxonomy backend-owned so frontend displays, rather than invents,
     blocker meaning.

## Platform Hardening Scope

1. Account/session audit browsing API/UI.
   - Add admin-facing browsing of sanitized audit events if selected for this
     goal.
   - Do not expose password values, password hashes, session tokens, token
     hashes, raw user-agent/IP, raw secrets, or credential material.
2. CLI audit decision.
   - Decide whether CLI account operations should write the same sanitized
     audit event model as API/UI operations.
   - Document any explicit reason if CLI audit remains out of scope.
3. Audit atomicity.
   - Ensure mutation state changes and audit records are transactionally
     consistent where the codebase supports it.
4. API error envelope normalization.
   - Normalize operator-facing API errors for auth, RBAC, DRS blockers,
     validation, stale evidence, and conflict cases.
   - Preserve safe detail without echoing secrets or untrusted raw input.
5. Retention/redaction review.
   - Review retention expectations for jobs, artifacts, account/session audit,
     DRS evidence, and post-create readiness evidence.
   - Confirm redaction rules for tokens, hashes, SSH keys, raw IP/user-agent
     values, credentials, and large raw Proxmox payloads.

## Out Of Scope

- Live Proxmox mutation, live DRS smoke, cleanup, live readiness, corrective
  action, or reconciliation mutation unless separately and explicitly approved
  for a specific run.
- Automatic DRS or scheduled balancing.
- Broad execute UI or corrective reconcile UI.
- External IdP, OAuth, SSO, 2FA, API tokens, or public signup unless separately
  requested.
- Create VM success-condition changes.
- SSH/Ansible/app bootstrap checks unless separately requested and approved.

## Acceptance Criteria

- Goal 12 remains candidate/not started until explicitly selected.
- Decision evidence distinguishes current values, 15-minute averages, and peaks
  if metrics are implemented.
- Stale, unknown, unavailable, or ambiguous evidence is visible and does not
  silently become executable.
- DRS blockers use a backend-owned taxonomy exposed consistently to DRS,
  Jobs/Runs, and Risks/Alerts surfaces selected for the slice.
- Account/session audit browsing, if implemented, returns sanitized metadata
  only.
- CLI audit behavior is either implemented or explicitly documented as a
  decision.
- Audit writes are transactionally consistent with the mutations selected for
  the slice.
- API errors use a normalized safe envelope for the selected surfaces.
- Retention and redaction expectations are documented for affected records.

## Suggested Validation

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests/drs backend/tests/contracts backend/tests/jobs backend/tests/db backend/tests/auth
node --test frontend/tests/*.mjs
pnpm --dir frontend lint
pnpm --dir frontend build
git diff --check
```

For a docs-only Goal 12 planning update, run the requested document checks and
`git diff --check`.
