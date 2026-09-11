#!/bin/sh
set -eu

# The reference task declares PostgreSQL in its verification manifest and its
# public lifecycle commands use the local PostgreSQL endpoint. Start the
# disposable database before dropping privileges for the verifier process.
if [ "$(id -u)" -eq 0 ]; then
  if [ "${ASTRA_EXTERNAL_LIFECYCLE:-}" != "1" ]; then
    version="$(pg_lsclusters --no-header | awk 'NR == 1 {print $1}')"
    cluster="$(pg_lsclusters --no-header | awk 'NR == 1 {print $2}')"
    if [ -z "$version" ] || [ -z "$cluster" ]; then
      echo "no PostgreSQL cluster is available" >&2
      exit 2
    fi
    pg_ctlcluster --skip-systemctl-redirect "$version" "$cluster" start >/dev/null 2>&1 || true
    runuser -u postgres -- psql --dbname postgres --set ON_ERROR_STOP=1 \
      --command "ALTER USER postgres WITH PASSWORD 'postgres'" >/dev/null
    # Candidate manifests from the reference task use the task-owned `arena`
    # role/database. Create them once when the disposable verifier starts so
    # reset scripts can use the same connection contract as the sample task.
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
  exec runuser -u verifier -- "$0" "$@"
fi

if [ ! -d /input/verifier ]; then
  echo "missing /input/verifier" >&2
  exit 2
fi
if [ -z "${VERIFIER_COMMAND:-}" ]; then
  echo "VERIFIER_COMMAND is required" >&2
  exit 2
fi

# The verifier is a separate filesystem namespace from the candidate runtime.
# It may read a candidate snapshot for contracts/artifacts, but it never runs
# candidate-provided commands.  Candidate lifecycle commands run only in the
# candidate-runtime container, which never receives /input/verifier.
cd /input/verifier
set +e
sh -c "$VERIFIER_COMMAND"
verifier_status=$?
set -e

exit "$verifier_status"
