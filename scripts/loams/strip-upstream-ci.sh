#!/usr/bin/env bash
# Deletes Neon's upstream CI: every workflow in .github/workflows whose name
# does not start with `loams-` (LP-0002, NF1 Task 7). Loams Postgres is a hard
# fork with no upstream sync (D820), so this ran once; nothing brings the files
# back, and scripts/loams/tests/test_hygiene.sh (`upstream_ci_absent`) keeps it
# so. Idempotent: a second run deletes nothing.
#
# Usage: strip-upstream-ci.sh [repository root]   (default: the current repository)
set -euo pipefail
root=${1:-$(git rev-parse --show-toplevel)}
dir="$root/.github/workflows"
[[ -d $dir ]] || { echo "no $dir" >&2; exit 2; }
shopt -s nullglob
removed=0
for f in "$dir"/*.yml "$dir"/*.yaml; do
  case $(basename "$f") in
    loams-*) ;;
    *) rm -- "$f"; echo "removed ${f#"$root"/}"; removed=$((removed + 1)) ;;
  esac
done
echo "strip-upstream-ci: removed $removed workflow(s)"
