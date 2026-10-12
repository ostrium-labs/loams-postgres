#!/usr/bin/env bash
# Tests for scripts/loams/check-dco.sh (NF1 Task 5; dco_rejects_unsigned).
# Copied from ostrium-labs/loams scripts/ci/test-dco.sh, plus the fork's
# cases: Neon's history before neon-fork-point and the commits listed in
# LOAMS_PATCHES.md's "Commits without a trailer" table (read from a trusted
# revision, EXEMPT_FROM) are exempt.
set -euo pipefail
checker="$(cd "$(dirname "$0")/.." && pwd)/check-dco.sh"
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
git init -q "$fixture"
cd "$fixture"
git config user.name 'DCO fixture'
git config user.email fixture@example.com
git commit -q --allow-empty -m 'neon: unsigned upstream history'
git tag neon-fork-point
base=$(git rev-parse HEAD)

run() {
  # run <expected> [VAR=value ...]: runs the checker with the given environment.
  local expected=$1 result=0
  shift
  env "$@" "$checker" > "$fixture/.result" 2>&1 || result=$?
  if [[ $expected == pass && $result != 0 || $expected == fail && $result == 0 ]]; then
    cat "$fixture/.result"
    echo "unexpected DCO result: expected $expected ($*)" >&2
    exit 1
  fi
}

check() {
  local name=$1 email=$2 signoff=$3 expected=$4
  git commit -q --allow-empty --author "$name <$email>" -m fixture ${signoff:+-m "$signoff"}
  local head
  head=$(git rev-parse HEAD)
  run "$expected" BASE="$base" HEAD="$head"
  base=$head
}

check 'Human' human@example.com 'Signed-off-by: Human <human@example.com>' pass
check 'Human' human@example.com '' fail
check 'dependabot[bot]' '49699333+dependabot[bot]@users.noreply.github.com' 'Signed-off-by: dependabot[bot] <support@github.com>' pass
check 'dependabot[bot]' '49699333+dependabot[bot]@users.noreply.github.com' '' fail
check 'Human' human@example.com 'Signed-off-by: dependabot[bot] <support@github.com>' fail
check 'dependabot[bot]' impostor@example.com 'Signed-off-by: dependabot[bot] <support@github.com>' fail

# The fork's cases, on a fresh history: by default the check starts at
# neon-fork-point, so the unsigned upstream commit is never checked.
git checkout -q --detach neon-fork-point
git commit -q --allow-empty -m 'ours: signed' -m 'Signed-off-by: DCO fixture <fixture@example.com>'
run pass
git commit -q --allow-empty -m 'ours: unsigned, before the rule'
unsigned=$(git rev-parse HEAD)
run fail
table() { # table <sha> <section>: commits a LOAMS_PATCHES.md listing <sha> under <section>.
  cat > LOAMS_PATCHES.md <<EOF
## Patches

| Id | Title | Area | Owner | Since | Origin | Drop when |
|---|---|---|---|---|---|---|
| LP-0001 | A patch | build | @o | 2026-10-12 | loams-only | never |

## $2

| Commit | Id | Why |
|---|---|---|
| $1 | LP-0001 | predates the rules |
EOF
  git add LOAMS_PATCHES.md
  git commit -q -m "table: $2" -m 'Signed-off-by: DCO fixture <fixture@example.com>'
}
before_table=$unsigned
table "$unsigned" 'Commits without a trailer'
# The table at a trusted revision (here HEAD, as on main) exempts the commit.
run pass
# A pull request cannot exempt its own unsigned commit: the table is read from
# the base revision, which does not list it.
run fail EXEMPT_FROM="$before_table"
# A sha in another section of the file does not exempt anything.
table "$unsigned" 'Something else'
run fail
# A missing base is an error, not an empty range.
run fail BASE=no-such-ref
echo 'DCO: signed humans/bot accepted; unsigned, mismatched and non-exempt commits rejected; Neon history exempt'
