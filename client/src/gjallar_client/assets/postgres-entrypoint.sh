#!/bin/sh
set -eu
# Host secret mounts stay 0600. Only container-local tmpfs copies are readable by postgres.
mkdir -p /run/gjallar
chmod 0700 /run/gjallar
for name in postgres_password app_password; do
  cp "/run/secrets/$name" "/run/gjallar/$name"
  chmod 0400 "/run/gjallar/$name"
  chown postgres:postgres "/run/gjallar/$name"
done
chown postgres:postgres /run/gjallar
exec /usr/local/bin/docker-entrypoint.sh "$@"
