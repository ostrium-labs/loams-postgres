#!/usr/bin/env bash
# No build-time fetch from Neon (LP-0006, NF1 Task 7): fails when a file that
# decides what a build or CI run downloads names the neondatabase GitHub
# organisations or registries (`neondatabase`, which also catches
# `neondatabase-labs` and `ghcr.io/neondatabase`) or Neon's build cache
# (`cache.neon.build`).
#
# Files checked: Cargo.lock, every Cargo.toml, .gitmodules, every Dockerfile
# (`Dockerfile`, `*.Dockerfile`, `Dockerfile.*`) and every workflow in
# .github/workflows. vendor/ (the Postgres submodules) is not checked.
# Matching ignores case. A line whose first non-blank character is `#` is a
# comment and is allowed.
# A file listed in scripts/loams/private-sources-allowlist.txt is skipped.
#
# One exception by source, not by file (Loams D2450, LP-0005): in Cargo.toml and
# Cargo.lock, a git dependency on one of Neon's three frozen library forks
# (rust-postgres, azure-sdk-for-rust, framed-websockets) pinned by a full
# 40-hex rev is allowed, because the rev we pin is on the official repository.
# The same repositories by branch or tag, and every other neondatabase source,
# still fail.
#
# Usage: check-no-private-sources.sh [root]   (default: the current repository)
# Test: scripts/loams/tests/test_hygiene.sh (no_private_sources).
set -euo pipefail
root=${1:-$(git rev-parse --show-toplevel)}
allowlist="$root/scripts/loams/private-sources-allowlist.txt"
pattern='neondatabase|cache\.neon\.build'
# Cargo.toml: `git = "<url>", rev = "<sha>"`; Cargo.lock: `"git+<url>?rev=<sha>#<sha>"`.
pinned_neon_git='https://github\.com/neondatabase/(rust-postgres\.git|azure-sdk-for-rust\.git|framed-websockets)(", rev = "[0-9a-f]{40}"|\?rev=[0-9a-f]{40}#[0-9a-f]{40}")'

allowed=""
if [[ -f $allowlist ]]; then
  # One path per line, relative to the root; `#` starts a comment.
  allowed=$(sed -e 's/#.*//' -e 's/[[:space:]]*$//' -e '/^$/d' "$allowlist")
fi

found=0
while IFS= read -r -d '' file; do
  rel=${file#"$root"/}
  if [[ -n $allowed ]] && grep -Fxq -- "$rel" <<<"$allowed"; then
    continue
  fi
  # -n: line numbers; -i: any case. Full-line comments are dropped.
  hits=$(grep -niE -- "$pattern" "$file" | grep -vE '^[0-9]+:[[:space:]]*#' || true)
  if [[ -n $hits && ( $rel == Cargo.lock || $rel == */Cargo.lock || $rel == Cargo.toml || $rel == */Cargo.toml ) ]]; then
    # Keep a line only if something still matches once the pinned sources are cut out.
    hits=$(while IFS= read -r hit; do
      grep -qiE -- "$pattern" < <(sed -E "s~$pinned_neon_git~~g" <<<"$hit") && printf '%s\n' "$hit"
    done <<<"$hits" || true)
  fi
  if [[ -n $hits ]]; then
    sed "s|^|$rel:|" <<<"$hits"
    found=$((found + 1))
  fi
done < <(find "$root" \
  \( -name .git -o -path "$root/vendor" -o -path "$root/target" -o -path "$root/pg_install" -o -name node_modules \) -prune -o \
  -type f \( -name Cargo.lock -o -name Cargo.toml -o -name .gitmodules -o -name Dockerfile -o -name '*.Dockerfile' -o -name 'Dockerfile.*' \
    -o -path "$root/.github/workflows/*.yml" -o -path "$root/.github/workflows/*.yaml" \) -print0 | sort -z)

if ((found)); then
  echo "check-no-private-sources: $found file(s) name neondatabase or cache.neon.build (LP-0006)" >&2
  exit 1
fi
echo "check-no-private-sources: ok"
