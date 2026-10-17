#!/usr/bin/env bash
# Merge an upstream Postgres minor into our branch (LP-0016, NF1 Task 17;
# design §51 §6.3, D821), run by loams-postgres-merge.yml:
#
#   postgres-merge.sh MAJOR TAG [--push] [--promote]
#
# 1. A blobless clone of ostrium-labs/postgres at loams/REL_<MAJOR>_STABLE (blobs
#    come on demand; nothing else is fetched).
# 2. The tag REL_<MAJOR>_<m> from postgres/postgres.
# 3. `git merge --no-ff` with the message "Merge <TAG> into loams/REL_<MAJOR>_STABLE"
#    and the trailer `Loams-Sync: <TAG>` (the plan's patch-trailer contract).
#    A conflict stops here: the files and the conflicted diff go to
#    $OUT (default ./postgres-merge), for a maintainer to resolve on the branch
#    by hand, with each resolution recorded in the merge commit's message.
# 4. --push: the merge goes to loams/minor-<MAJOR>-<TAG> (a new branch; never a
#    force-push). The submodule in vendor/postgres-v<MAJOR> can then move to it,
#    and the gate runs on that.
# 5. --promote: loams/REL_<MAJOR>_STABLE is fast-forwarded to that branch
#    (the rulesets refuse anything but a fast-forward).
# Pushes need GH_TOKEN with contents: write on ostrium-labs/postgres
# (LOAMS_BOT_TOKEN). Writes the merge commit's sha to $OUT/sha.
set -euo pipefail
major=${1:?usage: postgres-merge.sh MAJOR TAG [--push] [--promote]}
tag=${2:?usage: postgres-merge.sh MAJOR TAG [--push] [--promote]}
shift 2
push=false promote=false
for a in "$@"; do
  case "$a" in --push) push=true ;; --promote) push=true promote=true ;; *) echo "unknown option $a"; exit 2 ;; esac
done
[[ $major =~ ^[0-9]+$ && $tag =~ ^REL_${major}_[0-9]+$ ]] || { echo "TAG must be REL_${major}_<minor>, not $tag"; exit 2; }

fork=${FORK_POSTGRES:-ostrium-labs/postgres}
fork_url=${FORK_POSTGRES_URL:-https://github.com/$fork.git}
upstream=${UPSTREAM_POSTGRES:-https://github.com/postgres/postgres.git}
branch=loams/REL_${major}_STABLE
minor=loams/minor-${major}-${tag}
out=$(realpath -m "${OUT:-postgres-merge}")
work=${WORK:-${RUNNER_TEMP:-$PWD}/postgres-$major}
mkdir -p "$out"
rm -rf "$work"

auth=()
if [ -n "${GH_TOKEN:-}" ]; then
  auth=(-c "http.https://github.com/.extraheader=AUTHORIZATION: basic $(printf 'x-access-token:%s' "$GH_TOKEN" | base64 -w0)")
fi

git "${auth[@]}" clone -q --filter=blob:none --single-branch --branch "$branch" "$fork_url" "$work"
cd "$work"
git fetch -q --filter=blob:none --no-tags "$upstream" "refs/tags/$tag:refs/tags/$tag"
echo "$branch: $(git rev-parse --short HEAD); $tag: $(git rev-parse --short "$tag^{commit}")"

# A minor branch that already holds the tag (an earlier run, or a maintainer's
# hand resolution of a conflict) is the merge: reuse it, never re-merge, so a
# later --promote fast-forwards to exactly what the gate tested.
if git "${auth[@]}" fetch -q --filter=blob:none origin "+refs/heads/$minor:refs/remotes/origin/$minor" 2>/dev/null &&
   git merge-base --is-ancestor HEAD "origin/$minor" && git merge-base --is-ancestor "$tag" "origin/$minor"; then
  git reset -q --hard "origin/$minor"
  sha=$(git rev-parse HEAD)
  echo "$sha" > "$out/sha"
  echo "$minor already holds $tag: $sha"
  if $promote; then
    git "${auth[@]}" push -q origin "HEAD:refs/heads/$branch"
    echo "fast-forwarded $branch to $sha"
  fi
  exit 0
fi

if git merge-base --is-ancestor "$tag" HEAD; then
  echo "$tag is already in $branch"
  git rev-parse HEAD > "$out/sha"
  exit 0
fi

name=${GIT_NAME:-loams-postgres-bot}
email=${GIT_EMAIL:-loams-postgres-bot@users.noreply.github.com}
msg="Merge $tag into $branch

Upstream Postgres minor $tag from postgres/postgres (NF1 Task 17; D821).

Loams-Sync: $tag
Signed-off-by: $name <$email>"
if ! git -c user.name="$name" -c user.email="$email" merge -q --no-ff -m "$msg" "$tag"; then
  git diff --name-only --diff-filter=U > "$out/conflicts.txt"
  git diff > "$out/conflicts.diff" || true
  echo "::error::$tag does not merge cleanly into $branch: $(wc -l < "$out/conflicts.txt") file(s)"
  sed 's/^/  conflict: /' "$out/conflicts.txt"
  exit 1
fi
sha=$(git rev-parse HEAD)
echo "$sha" > "$out/sha"
echo "merged: $sha ($(git diff --shortstat HEAD^1 HEAD))"

if $push; then
  git "${auth[@]}" push -q origin "HEAD:refs/heads/$minor"
  echo "pushed $minor"
fi
if $promote; then
  git "${auth[@]}" push -q origin "HEAD:refs/heads/$branch"
  echo "fast-forwarded $branch to $sha"
fi
