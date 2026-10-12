#!/usr/bin/env bash
# DCO: every non-merge commit in BASE..HEAD has a Signed-off-by for its author.
# Copied from ostrium-labs/loams scripts/ci/check-dco.sh (NF1 Task 5). In the
# fork, BASE defaults to neon-fork-point, so Neon's history is exempt, and the
# commits in LOAMS_PATCHES.md's "Commits without a trailer" table are exempt
# too: they reached main before the rules, and history is never rewritten.
# The table is read from EXEMPT_FROM (default HEAD), a trusted revision: on a
# pull request the workflow passes the base commit, so a PR cannot exempt its
# own commits by editing the table.
# Test: scripts/loams/tests/test-dco.sh.
set -euo pipefail
BASE=${BASE:-neon-fork-point}
HEAD=${HEAD:-HEAD}
EXEMPT_FROM=${EXEMPT_FROM:-HEAD}
exempt=""
if patches=$(git show "$EXEMPT_FROM:LOAMS_PATCHES.md" 2>/dev/null); then
  exempt=$(awk '/^## /{f = ($0 == "## Commits without a trailer"); next} f' <<<"$patches" |
    grep -oE '\b[0-9a-f]{40}\b' || true)
fi
# An assignment, so a bad ref fails here instead of giving an empty range.
shas=$(git rev-list --no-merges "$BASE..$HEAD")
status=0
for sha in $shas; do
  if grep -Fxq "$sha" <<<"$exempt"; then
    continue
  fi
  name=$(git log -1 --format='%an' "$sha")
  email=$(git log -1 --format='%ae' "$sha")
  # GitHub's Dependabot commits use its support address in DCO.
  if [[ "$name" == 'dependabot[bot]' && "$email" == '49699333+dependabot[bot]@users.noreply.github.com' ]] &&
      git log -1 --format='%(trailers:key=Signed-off-by,valueonly)' "$sha" |
      grep -Fxq 'dependabot[bot] <support@github.com>'; then
    continue
  fi
  if ! git log -1 --format='%(trailers:key=Signed-off-by,valueonly)' "$sha" \
      | grep -qiF "<$email>"; then
    echo "::error::commit $sha is missing 'Signed-off-by: ... <$email>' (use git commit -s)"
    status=1
  fi
done
exit $status
