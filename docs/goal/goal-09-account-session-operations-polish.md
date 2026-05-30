# Goal 9: Account/Session Operations Polish

Status: deferred.

## Objective

Improve operational convenience without changing the auth model.

## Starting Point

Current local user management includes:

- CLI: `create-admin`, `create-user`, `list-users`, `set-role`,
  `disable-user`, `reset-password`
- UI: `/admin/users`
- API: `/api/v1/admin/users*`
- Last enabled admin protection in shared service logic

## Candidate Work

1. Re-enable disabled users.
2. Session list and force logout for admins.
3. Self password change.
4. Account operation audit log.
5. Better admin UI affordances for last-admin protection and disabled users.

## Out Of Scope Unless Explicitly Requested

- Public signup.
- Email password reset.
- OAuth/SSO/2FA.
- API tokens.

## Definition Of Done

- Account/session operations remain admin-gated where appropriate.
- Password hashes, session token hashes, raw secrets, and plaintext passwords
  are never returned in API responses.
- Last enabled admin protection remains intact.
- Existing auth/RBAC behavior is preserved unless explicitly changed by the
  goal.
