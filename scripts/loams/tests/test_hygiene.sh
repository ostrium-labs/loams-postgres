#!/usr/bin/env bash
# Tests for NF1 Task 7, the build hygiene patches (LP-0002 to LP-0006).
#
#   upstream_ci_absent       no workflow without the loams- prefix; strip-upstream-ci.sh is idempotent
#   deny_rejects_cddl        `cargo deny check licenses` passes here and fails on a CDDL-1.0 fixture crate
#   no_inferno               `cargo tree -e features -i inferno` finds nothing, on any target
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

deny_rejects_cddl() {
  (cd "$repo" && cargo deny --log-level error check licenses) || fail "cargo deny check licenses failed"

  # A scratch workspace with this repository's deny.toml and one CDDL crate.
  local fx="$scratch/cddl"
  mkdir -p "$fx/src"
  cp "$repo/deny.toml" "$fx/deny.toml"
  : > "$fx/src/lib.rs"
  cat > "$fx/Cargo.toml" <<'TOML'
[package]
name = "cddl-fixture"
version = "0.1.0"
edition = "2021"
license = "CDDL-1.0"
TOML
  if (cd "$fx" && cargo deny --log-level error check licenses) > "$fx/out" 2>&1; then
    fail "cargo deny accepted a CDDL-1.0 crate"
  elif ! grep -q 'CDDL-1.0' "$fx/out"; then
    fail "cargo deny failed, but not on CDDL-1.0: $(cat "$fx/out")"
  fi
}

no_inferno() {
  local out
  if out=$(cd "$repo" && cargo tree --locked --target all -e features -i inferno 2>&1); then
    fail "inferno is in the graph: $out"
  elif ! grep -q 'did not match any packages' <<<"$out"; then
    fail "cargo tree failed: $out"
  fi
}

all=(upstream_ci_absent deny_rejects_cddl no_inferno)
for current in "${@:-${all[@]}}"; do
  echo "--- $current"
  "$current"
done
if ((failures)); then
  echo "test_hygiene: $failures failure(s)" >&2
  exit 1
fi
echo "test_hygiene: ok (${*:-${all[*]}})"
