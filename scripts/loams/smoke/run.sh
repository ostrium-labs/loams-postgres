#!/usr/bin/env bash
# Smoke test of a storage image and a compute image together (LP-0010, NF1
# Tasks 10 and 11): starts compose.yaml beside this script, creates a tenant and
# a timeline of the given Postgres major through the pageserver API, starts a
# compute on it and runs `SELECT 1` through the compute, then any SQL files given.
#
# Usage: run.sh <storage image> <compute image> <pg major> [file.sql ...]
#
# Environment:
#   COMPOSE          the compose command (default: `docker compose`)
#   EXPECT_COMMIT    if set, `pageserver --version` must name this commit
#   SMOKE_KEEP=1     leave the stack running (default: `down -v`, which removes
#                    only this run's containers, network and volumes)
# The compose project is loams-smoke-<random>, and nothing is published on the
# host, so runs never collide.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
[[ $# -ge 3 ]] || { echo "usage: $0 <storage image> <compute image> <pg major> [file.sql ...]" >&2; exit 2; }
export STORAGE_IMAGE=$1 COMPUTE_IMAGE=$2
major=$3
shift 3
[[ $major =~ ^[0-9]+$ ]] || { echo "pg major must be a number, got: $major" >&2; exit 2; }
read -r -a compose <<<"${COMPOSE:-docker compose}"
export COMPOSE_PROJECT_NAME=loams-smoke-$(od -An -N4 -tx4 /dev/urandom | tr -d ' ')
dc() { "${compose[@]}" -f "$here/compose.yaml" "$@"; }

cleanup() {
  local status=$?
  if ((status != 0)); then
    echo "--- smoke failed; the last logs:" >&2
    dc logs --tail 80 >&2 || true
  fi
  if [[ ${SMOKE_KEEP:-} != 1 ]]; then
    dc down -v --remove-orphans > /dev/null 2>&1 || true
  fi
  exit "$status"
}
trap cleanup EXIT

wait_for() {
  # wait_for <seconds> <description> <command ...>
  local deadline=$((SECONDS + $1)) what=$2
  shift 2
  until "$@" > /dev/null 2>&1; do
    ((SECONDS < deadline)) || { echo "timed out waiting for $what" >&2; return 1; }
    sleep 2
  done
}

echo "smoke: project $COMPOSE_PROJECT_NAME, storage $STORAGE_IMAGE, compute $COMPUTE_IMAGE, Postgres $major"

version=$(dc run --rm --no-deps --entrypoint pageserver pageserver --version)
echo "smoke: $version"
if [[ -n ${EXPECT_COMMIT:-} && $version != *"$EXPECT_COMMIT"* ]]; then
  echo "pageserver --version does not name $EXPECT_COMMIT" >&2
  exit 1
fi

dc up -d rustfs create-bucket storage_broker pageserver safekeeper1
api() { dc exec -T pageserver curl -sf "$@"; }
wait_for 120 "the pageserver API" api http://localhost:9898/v1/status

tenant=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')
timeline=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')
api -X PUT -H 'Content-Type: application/json' \
  -d '{"mode":"AttachedSingle","generation":1,"tenant_conf":{}}' \
  "http://localhost:9898/v1/tenant/$tenant/location_config" > /dev/null
api -X POST -H 'Content-Type: application/json' \
  -d "{\"new_timeline_id\":\"$timeline\",\"pg_version\":$major}" \
  "http://localhost:9898/v1/tenant/$tenant/timeline/" > /dev/null
echo "smoke: tenant $tenant, timeline $timeline"

TENANT_ID=$tenant TIMELINE_ID=$timeline dc up -d compute1
psql() { dc exec -T compute1 /usr/local/bin/psql -X -v ON_ERROR_STOP=1 -h localhost -p 55433 -U cloud_admin -d postgres "$@"; }
wait_for 180 "the compute" psql -c 'SELECT 1'

got=$(psql -At -c 'SELECT 1')
[[ $got == 1 ]] || { echo "SELECT 1 answered: $got" >&2; exit 1; }
server=$(psql -At -c 'SHOW server_version_num')
[[ ${server:0:${#major}} == "$major" ]] || { echo "the compute runs Postgres $server, not $major" >&2; exit 1; }
echo "smoke: SELECT 1 ok on Postgres $server"

for sql in "$@"; do
  echo "smoke: $sql"
  psql < "$sql"
done
echo "smoke: ok"
