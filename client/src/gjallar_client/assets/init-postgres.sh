#!/bin/sh
# Sourced by the official postgres entrypoint on a fresh volume only.
set -eu
app_password=$(cat /run/gjallar/app_password)
case "$app_password" in
  ''|*[!0-9a-f]*) echo 'Invalid application credential file' >&2; exit 1 ;;
esac
# printf is a shell builtin: the credential is stdin, never a process argument.
# One transaction makes role/schema preparation safe to retry after interruption.
{
  printf "SET log_statement = 'none'; SET log_min_error_statement = 'panic'; BEGIN;\n"
  printf "SELECT 'CREATE ROLE gjallar LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD ''%s''' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'gjallar')\\gexec\n" "$app_password"
  printf 'ALTER DATABASE gjallar OWNER TO gjallar; ALTER SCHEMA public OWNER TO gjallar; COMMIT;\n'
} | psql --username "$POSTGRES_USER" --dbname gjallar --no-psqlrc --set ON_ERROR_STOP=1 >/dev/null 2>&1
unset app_password
