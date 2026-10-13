#!/usr/bin/env bash
# Tests for NF1 Task 7, the build hygiene patches (LP-0002 to LP-0006).
#
#   upstream_ci_absent       no workflow without the loams- prefix; strip-upstream-ci.sh is idempotent
#   deny_rejects_cddl        `cargo deny check licenses` passes here and fails on a CDDL-1.0 fixture crate
#   no_inferno               `cargo tree -e features -i inferno` finds nothing, on any target
#   no_private_sources       check-no-private-sources.sh passes here, fails on neon-fork-point and on fixtures
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

no_private_sources() {
  "$scripts/check-no-private-sources.sh" "$repo" > /dev/null || fail "fails on this tree"

  # Neon's last public commit fetches from neondatabase in Cargo.lock, the
  # Dockerfiles and the workflows.
  local fp="$scratch/fork-point" files
  mkdir -p "$fp"
  files=$(git -C "$repo" ls-tree -r --name-only neon-fork-point |
    grep -E '(^|/)(Cargo\.lock|Cargo\.toml|\.gitmodules|Dockerfile|[^/]*\.Dockerfile|Dockerfile\.[^/]*)$|^\.github/workflows/' || true)
  [[ -n $files ]] || { fail "no files at neon-fork-point (fetch the tag)"; return; }
  # shellcheck disable=SC2086
  git -C "$repo" archive neon-fork-point $files | tar -x -C "$fp"
  local out
  if out=$("$scripts/check-no-private-sources.sh" "$fp" 2>&1); then
    fail "passes on neon-fork-point"
  fi
  for want in 'Cargo.lock:' 'Dockerfile:' 'compute/compute-node.Dockerfile:' '.github/workflows/'; do
    grep -qF -- "$want" <<<"$out" || fail "neon-fork-point: no finding in $want"
  done

  # Fixtures: comments pass; a registry without a slash, Neon's labs
  # organisation and the build cache fail; the allowlist skips a file.
  local fx="$scratch/sources"
  mkdir -p "$fx/scripts/loams" "$fx/.github/workflows" "$fx/docker"
  printf '# built from neondatabase/neon once\nFROM debian\n' > "$fx/Dockerfile"
  printf 'name: x\n  # see neondatabase/neon#1\n' > "$fx/.github/workflows/ci.yml"
  "$scripts/check-no-private-sources.sh" "$fx" > /dev/null || fail "a comment was refused"
  for line in 'ARG REPOSITORY=ghcr.io/neondatabase' \
              'RUN wget https://github.com/neondatabase-labs/pgrag/archive/v1.tar.gz' \
              'ENV RUSTC_WRAPPER_CACHE=https://cache.neon.build/x' \
              'RUN git clone https://github.com/NeonDatabase/pgrag'; do
    printf 'FROM debian\n%s\n' "$line" > "$fx/docker/Dockerfile.ext"
    "$scripts/check-no-private-sources.sh" "$fx" > /dev/null 2>&1 && fail "accepted: $line"
  done
  echo 'docker/Dockerfile.ext   # fixture' > "$fx/scripts/loams/private-sources-allowlist.txt"
  "$scripts/check-no-private-sources.sh" "$fx" > /dev/null || fail "the allowlist did not skip the file"
}

all=(upstream_ci_absent deny_rejects_cddl no_inferno no_private_sources)
for current in "${@:-${all[@]}}"; do
  echo "--- $current"
  "$current"
done
if ((failures)); then
  echo "test_hygiene: $failures failure(s)" >&2
  exit 1
fi
echo "test_hygiene: ok (${*:-${all[*]}})"
