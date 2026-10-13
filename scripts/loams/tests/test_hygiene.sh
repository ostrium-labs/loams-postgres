#!/usr/bin/env bash
# Tests for NF1 Task 7, the build hygiene patches (LP-0002 to LP-0006).
#
#   upstream_ci_absent       no workflow without the loams- prefix; strip-upstream-ci.sh is idempotent
#   deny_rejects_cddl        `cargo deny check licenses sources` passes here; licenses fails on a CDDL-1.0 fixture crate
#   no_inferno               `cargo tree -e features -i inferno` finds nothing, on any target
#   no_private_sources       check-no-private-sources.sh passes here, fails on neon-fork-point and on fixtures
#   build_tools_pinned_by_digest  the storage Dockerfile builds FROM $BUILD_TOOLS, an ostrium-labs image by digest
#                            (LP-0009); pin-build-tools.sh rewrites it and refuses anything else
#   third_party_licences_include_tokio_epoll_uring  cargo about renders about.hbs with tokio-epoll-uring's
#                            MIT notice and uring-common's tokio-uring notice, and nothing CDDL (LP-0007, LP-0010);
#                            needs cargo-about 0.9.2 (CARGO_ABOUT, default `cargo-about` on PATH)
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
  # sources too: deny.toml refuses git sources outside ostrium-labs (LP-0005).
  (cd "$repo" && cargo deny --log-level error check licenses sources) || fail "cargo deny check licenses sources failed"

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

build_tools_pinned_by_digest() {
  local df="$repo/Dockerfile" digest_re='ghcr\.io/ostrium-labs/[a-z0-9/_-]+@sha256:[0-9a-f]{64}'
  grep -qE "^ARG BUILD_TOOLS=$digest_re\$" "$df" || fail "Dockerfile: no ARG BUILD_TOOLS=<ostrium-labs image>@sha256:<digest>"
  grep -qE '^FROM \$BUILD_TOOLS AS ' "$df" || fail "Dockerfile: no stage FROM \$BUILD_TOOLS"
  local stray
  stray=$(grep -nE '^FROM ' "$df" | grep -vE 'FROM (\$BUILD_TOOLS|\$BASE_IMAGE_SHA) AS |FROM \$BASE_IMAGE_SHA$' || true)
  [[ -z $stray ]] || fail "Dockerfile: FROM without a pinned base: $stray"

  # pin-build-tools.sh rewrites the ARG, and refuses a tag or another registry.
  local fx="$scratch/pin" d1 d2
  mkdir -p "$fx"
  cp "$df" "$fx/Dockerfile"
  d1=sha256:$(printf '1%.0s' {1..64}) d2=sha256:$(printf 'a%.0s' {1..64})
  "$scripts/pin-build-tools.sh" "ghcr.io/ostrium-labs/loams-postgres-build-tools@$d1" "$fx/Dockerfile" > /dev/null ||
    fail "pin-build-tools.sh failed"
  grep -qx "ARG BUILD_TOOLS=ghcr.io/ostrium-labs/loams-postgres-build-tools@$d1" "$fx/Dockerfile" || fail "the ARG was not rewritten"
  [[ $(diff "$df" "$fx/Dockerfile" | grep -c '^[<>]') == 2 ]] || fail "pin-build-tools.sh changed more than the ARG line"
  for bad in "ghcr.io/ostrium-labs/loams-postgres-build-tools:latest" "ghcr.io/neondatabase/build-tools@$d2" \
             "ghcr.io/ostrium-labs/loams-postgres-build-tools@sha256:abc"; do
    "$scripts/pin-build-tools.sh" "$bad" "$fx/Dockerfile" > /dev/null 2>&1 && fail "accepted $bad"
  done
  grep -qx "ARG BUILD_TOOLS=ghcr.io/ostrium-labs/loams-postgres-build-tools@$d1" "$fx/Dockerfile" || fail "a refused pin changed the file"
}

third_party_licences_include_tokio_epoll_uring() {
  local out="$scratch/THIRD_PARTY_LICENSES.html"
  (cd "$repo" && "${CARGO_ABOUT:-cargo-about}" generate --locked -o "$out" about.hbs) > "$scratch/about.log" 2>&1 ||
    { fail "cargo about failed: $(tail -5 "$scratch/about.log")"; return; }
  grep -qF 'Copyright (c) 2023-2026 the tokio-epoll-uring authors (Neon Inc.)' "$out" ||
    fail "no MIT notice of tokio-epoll-uring"
  grep -qF 'Copyright (c) 2021 Carl Lerche' "$out" || fail "no tokio-uring notice (uring-common)"
  ! grep -qiE 'CDDL|>inferno ' "$out" || fail "CDDL or inferno in the licence file"
}

all=(upstream_ci_absent deny_rejects_cddl no_inferno no_private_sources build_tools_pinned_by_digest
  third_party_licences_include_tokio_epoll_uring)
for current in "${@:-${all[@]}}"; do
  echo "--- $current"
  "$current"
done
if ((failures)); then
  echo "test_hygiene: $failures failure(s)" >&2
  exit 1
fi
echo "test_hygiene: ok (${*:-${all[*]}})"
