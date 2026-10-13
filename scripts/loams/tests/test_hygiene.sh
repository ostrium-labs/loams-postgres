#!/usr/bin/env bash
# Tests for NF1 Task 7, the build hygiene patches (LP-0002 to LP-0006).
#
#   upstream_ci_absent       no workflow without the loams- prefix; strip-upstream-ci.sh is idempotent
#
# Usage: test_hygiene.sh [test name ...]   (default: all)
set -euo pipefail
repo=$(cd "$(dirname "$0")/../../.." && pwd)
scripts="$repo/scripts/loams"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
failures=0

fail() { echo "FAIL $current: $*" >&2; failures=$((failures + 1)); }

upstream_ci_absent() {
  local left
  left=$(find "$repo/.github/workflows" -maxdepth 1 -type f ! -name 'loams-*' -printf '%f\n')
  [[ -z $left ]] || fail "upstream workflows left: $left"

  # The script removes only non-loams workflows, and a second run is a no-op.
  local fx="$scratch/strip"
  mkdir -p "$fx/.github/workflows"
  touch "$fx/.github/workflows/"{build_and_test.yml,_meta.yml,release.yaml,loams-gate.yml,loams-fuzz.yml}
  "$scripts/strip-upstream-ci.sh" "$fx" > /dev/null
  left=$(cd "$fx/.github/workflows" && ls | tr '\n' ' ')
  [[ $left == "loams-fuzz.yml loams-gate.yml " ]] || fail "after the first run: $left"
  "$scripts/strip-upstream-ci.sh" "$fx" | grep -q 'removed 0 workflow' || fail "second run removed something"
}

all=(upstream_ci_absent)
for current in "${@:-${all[@]}}"; do
  echo "--- $current"
  "$current"
done
if ((failures)); then
  echo "test_hygiene: $failures failure(s)" >&2
  exit 1
fi
echo "test_hygiene: ok (${*:-${all[*]}})"
