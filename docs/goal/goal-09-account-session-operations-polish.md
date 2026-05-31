# Goal 9: Account/Session Operations Polish

Status: polish deferred; admin local account operations are already implemented.

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

Not yet implemented:

- Admin-visible session inventory and session revocation UI.
- Self password change.
- Expanded sanitized audit metadata beyond the current operation responses.

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
