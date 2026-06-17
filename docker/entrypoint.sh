#!/usr/bin/env sh
set -eu

if [ "${GJALLAR_SKIP_STARTUP_INIT:-}" = "1" ]; then
  echo "Skipping Gjallar startup database initialization."
else
  echo "Running Gjallar database migrations..."
  alembic -c /app/backend/alembic.ini upgrade head

  echo "Seeding Gjallar Create VM profiles..."
  python -m app.db.seed_create_vm_profiles

  echo "Bootstrapping Gjallar admin account if configured..."
  python -m app.auth.users bootstrap-admin-from-env
fi

exec "$@"
