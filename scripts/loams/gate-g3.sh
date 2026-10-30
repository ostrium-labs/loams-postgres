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
# `loams-gate / g3` on this commit. This job waits for it and fails with that
# status. Loams runs the e2e jobs once per candidate major (NF2 Task 7, D1118);
# a beta major's legs are advisory there, so the run may fail on a beta leg
# while the status is green: the status, not the run's conclusion, decides.
# OWN_MAJORS (the gate's own-majors input) makes those majors' legs required.
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

own=()
# Only when set: a Loams dev without the own_majors input still takes the dispatch.
[ -n "${OWN_MAJORS:-}" ] && own=(-f own_majors="$OWN_MAJORS")
gh workflow run nf1-candidate.yml -R "$loams" --ref dev \
  -f pins="$CANDIDATE_PINS" -f fork_commit="$GITHUB_SHA" -f key="$key" "${own[@]}"

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
fork=${GITHUB_REPOSITORY:-ostrium-labs/loams-postgres}
# Only this run's status counts, not an older run's on the same commit.
jq_status="[.[] | select(.context == \"loams-gate / g3\" and (.target_url // \"\" | endswith(\"/runs/$run\")))][0]"
state=$(gh api "repos/$fork/commits/$GITHUB_SHA/statuses?per_page=100" -q "$jq_status | \"\\(.state) \\(.description)\"")
echo "G3: run $conclusion; status loams-gate / g3: $state"
[ "$conclusion" = success ] || [ "${state%% *}" != success ] ||
  echo "::warning title=G3::advisory (beta) legs failed in $url; the required legs passed"
[ "${state%% *}" = success ]
