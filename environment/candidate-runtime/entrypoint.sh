#!/bin/sh
set -eu

# This container owns only the untrusted candidate application and its
# disposable runtime dependencies.  It deliberately has no private verifier
# mount, Docker socket, report mount, or evaluator credentials.
if [ "$(id -u)" -eq 0 ]; then
  version="$(pg_lsclusters --no-header | awk 'NR == 1 {print $1}')"
  cluster="$(pg_lsclusters --no-header | awk 'NR == 1 {print $2}')"
  if [ -z "$version" ] || [ -z "$cluster" ]; then
    echo "no PostgreSQL cluster is available" >&2
    exit 2
  fi
  pg_ctlcluster --skip-systemctl-redirect "$version" "$cluster" start >/dev/null 2>&1 || true
  runuser -u postgres -- psql --dbname postgres --set ON_ERROR_STOP=1 \
    --command "ALTER USER postgres WITH PASSWORD 'postgres'" >/dev/null
  if ! runuser -u postgres -- psql --dbname postgres --tuples-only --no-align \
    --command "SELECT 1 FROM pg_roles WHERE rolname = 'arena'" | grep -qx '1'; then
    runuser -u postgres -- psql --dbname postgres --set ON_ERROR_STOP=1 \
      --command "CREATE ROLE arena LOGIN PASSWORD 'arena'" >/dev/null
  else
    runuser -u postgres -- psql --dbname postgres --set ON_ERROR_STOP=1 \
      --command "ALTER ROLE arena WITH LOGIN PASSWORD 'arena'" >/dev/null
  fi
  if ! runuser -u postgres -- psql --dbname postgres --tuples-only --no-align \
    --command "SELECT 1 FROM pg_database WHERE datname = 'arena'" | grep -qx '1'; then
    runuser -u postgres -- createdb --owner arena arena
  fi
fi

# Candidate workspaces are bind-mounted from the host and may not be writable
# by an image-local UID.  The container has no Docker socket, private mount,
# host network, or evaluator credentials, so root here is limited to the
# disposable candidate filesystem and runtime namespace.
if [ "$#" -gt 0 ]; then
  exec "$@"
fi
exec sleep infinity
