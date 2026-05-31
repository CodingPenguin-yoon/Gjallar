# Goal 9: Account/Session Operations Polish

Status: completed for the local account/session polish slice.

## Objective

Polish the existing local auth/session model for operational use without
redesigning authentication or expanding into public identity features.

## Starting Point

Current local user management includes:

- CLI: `create-admin`, `create-user`, `list-users`, `set-role`,
  `disable-user`, `reset-password`
- UI: `/admin/users`
- API: `/api/v1/admin/users*`
- Last enabled admin protection in shared service logic
- Admin API/UI operations: list users, create user, change role, disable user,
  and reset password.
- Disable and reset-password revoke the target user's sessions.
- Role change does not revoke target sessions.
- Last enabled admin cannot be disabled or demoted; disabled admin rows do not
  count toward that protection.

Implemented in the Goal 9 polish slice:

- Admin-visible session inventory and session revocation UI.
- Self password change under the authenticated local session model.
- Expanded sanitized audit metadata for account/session mutations.

## Scope

1. Admin-gated local account operations.
   - Preserve implemented list, create, role change, disable, and password
     reset flows as admin-only operations.
   - Preserve last enabled admin protection for any operation that could remove
     the final usable admin account.
   - Preserve the current session behavior: disable/reset-password revoke target
     sessions, while role change does not.
2. Session operations, if implemented.
   - Add admin-visible session inventory and revocation only within the current
     local session model.
   - Avoid exposing raw session tokens or token hashes.
   - Make revoked, expired, current, and target sessions distinguishable in
     operator-facing metadata.
3. Self password change, if scoped.
   - Allow an authenticated user to change their own password only with the
     current-password verification and password policy expected by the existing
     local auth model.
   - Do not turn this into public reset or email-based recovery.
4. Audit metadata.
   - Record who performed account/session operations, what changed, when it
     changed, and which target account/session was affected.
   - Keep audit records sanitized and free of password values, password hashes,
     session tokens, token hashes, and raw secrets.
5. UI affordances.
   - Make disabled users, role changes, last-admin protection, password reset,
     session revocation, and current-session risk states clear in the admin UI
     when those operations exist.
   - Keep UI controls aligned with backend authorization and disabled states.

## Out Of Scope Unless Explicitly Requested

- Public signup.
- Email password reset.
- OAuth/SSO/2FA.
- API tokens.
- External identity providers.
- Auth model redesign.

## Definition Of Done

- Account/session operations remain admin-gated where appropriate.
- Password hashes, session token hashes, raw secrets, and plaintext passwords
  are never returned in API responses.
- Last enabled admin protection remains intact.
- Existing auth/RBAC behavior is preserved unless explicitly changed by the
  goal.
- Any new account/session audit metadata is sanitized and operator-readable.
- UI affordances reflect backend permissions and safety blockers instead of
  relying on frontend-only enforcement.

## Implemented Behavior

- `GET /api/v1/admin/sessions` lists local sessions for admins with safe
  metadata only: session id, user id/username, role, enabled state, created,
  expiry, revoked timestamp, derived `active`/`expired`/`revoked` status, and
  `is_current_session`.
- `POST /api/v1/admin/sessions/{session_id}/revoke` is admin-only and
  idempotent for already revoked or expired sessions. Revoking the current
  admin session clears the browser cookie in the response and returns
  `current_session_revoked=true` so the frontend refreshes auth state.
- `POST /api/v1/auth/change-password` requires an authenticated session,
  verifies `current_password`, validates and stores the new password using the
  existing local password hashing path, revokes other active sessions for that
  user, and preserves the current session.
- Admin create, role change, disable, reset-password, session revoke, and self
  password change now record a compact `account_audit_events` row and return
  `audit_event_id` plus operator-readable `audit_event` metadata in mutation
  responses.
- Audit details intentionally omit password values, password hashes, session
  tokens, session token hashes, user-agent/IP hashes, raw user-agent/IP, and raw
  secrets. The audit response includes trusted actor fields, target account or
  session identifiers, changed fields, status transitions, and revoked session
  counts where relevant.
- Invalid admin role errors now use a generic invalid-role response and do not
  echo the supplied role text.

## Validation

- Focused backend auth/admin contracts:
  `PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests/contracts/test_api_v1_auth.py backend/tests/contracts/test_api_v1_admin_users.py`
  passed with `34 passed`.
- Focused frontend account/session contracts:
  `node --test frontend/tests/apiV1Client.test.mjs frontend/tests/authFlow.test.mjs frontend/tests/adminUsersScreen.test.mjs`
  passed with `3 passed`.
- Broad backend validation:
  `PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend/tests`
  passed with `281 passed, 47 warnings, 29 subtests passed`.
- Broad frontend validation:
  `node --test frontend/tests/*.mjs` passed with `13 passed`;
  `pnpm --dir frontend lint` passed; `pnpm --dir frontend build` passed.
- Final whitespace validation: `git diff --check` passed.

## Remaining Gaps And Risks

- There is no audit event browsing UI/API yet; audit metadata is recorded and
  returned on the relevant mutation responses.
- No public signup, public reset, OAuth/SSO/2FA, API token, external IdP, or
  auth redesign work was added.
- No live Proxmox, DRS, readiness, SSH, Ansible, guest-agent, shell, or network
  smoke was run for this local-only auth/session slice.
