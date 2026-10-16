#!/usr/bin/env bash
# G3, Loams' integration on a release candidate (LP-0015, NF1 Task 16; design
# §51 §6.4), run by loams-gate.yml:
#
#   gate-g3.sh KEY
#
# Dispatches ostrium-labs/loams nf1-candidate.yml on dev with the candidate's
# pin document ($CANDIDATE_PINS), this commit ($GITHUB_SHA) and KEY, which the
# run carries in its name so this job can find it. That workflow overrides
# Loams' pin file with the document, runs the Postgres e2e jobs, the WAL
# decoder's golden tests and the extension smoke, and sets the commit status
# `loams-gate / g3` on this commit. This job waits for it and fails with it.
#
# Needs GH_TOKEN: the LOAMS_BOT_TOKEN secret (actions: write on
# ostrium-labs/loams; GITHUB_TOKEN cannot dispatch another repository's
# workflows).
set -euo pipefail
key=${1:?usage: gate-g3.sh KEY}
loams=${LOAMS_REPO:-ostrium-labs/loams}
: "${CANDIDATE_PINS:?G3 needs the candidate pin document (input candidate-pins)}"
: "${GITHUB_SHA:?}"
if [ -z "${GH_TOKEN:-}" ]; then
  echo "::error::G3 needs the secret LOAMS_BOT_TOKEN to dispatch $loams nf1-candidate.yml"
  exit 1
fi

gh workflow run nf1-candidate.yml -R "$loams" --ref dev \
  -f pins="$CANDIDATE_PINS" -f fork_commit="$GITHUB_SHA" -f key="$key"

# The dispatch API returns no run id: find the run by the key in its name.
run=""
for _ in $(seq 1 30); do
  sleep 10
  run=$(gh run list -R "$loams" --workflow nf1-candidate.yml --event workflow_dispatch --limit 30 \
    --json databaseId,displayTitle -q ".[] | select(.displayTitle | endswith(\" $key\")) | .databaseId" | head -n1)
  [ -n "$run" ] && break
done
[ -n "$run" ] || { echo "::error::no nf1-candidate run named $key appeared on $loams"; exit 1; }
url="https://github.com/$loams/actions/runs/$run"
echo "G3: $url"
echo "G3: [$loams nf1-candidate run $run]($url)" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
gh run watch "$run" -R "$loams" --interval 60 > /dev/null || true
conclusion=$(gh run view "$run" -R "$loams" --json conclusion -q .conclusion)
echo "G3: $conclusion"
[ "$conclusion" = success ]
