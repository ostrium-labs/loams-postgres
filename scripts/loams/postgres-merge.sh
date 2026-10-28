#!/usr/bin/env bash
# Merge an upstream Postgres minor into our branch (LP-0016, NF1 Task 17;
# design §51 §6.3, D821), run by loams-postgres-merge.yml:
#
#   postgres-merge.sh MAJOR TAG [--push] [--promote]
#
# 1. A blobless clone of ostrium-labs/postgres at loams/pg<MAJOR> (blobs
#    come on demand; nothing else is fetched).
# 2. The tag REL_<MAJOR>_<m> from postgres/postgres.
# 3. `git merge --no-ff` with the message "Merge <TAG> into loams/pg<MAJOR>"
#    and the trailer `Loams-Sync: <TAG>` (the plan's patch-trailer contract).
#    A conflict stops here: the files and the conflicted diff go to
#    $OUT (default ./postgres-merge), for a maintainer to resolve on the branch
#    by hand, with each resolution recorded in the merge commit's message.
# 4. --push: the merge goes to loams/minor-pg<MAJOR>-<TAG> (a new branch; never a
#    force-push). The submodule in vendor/postgres-v<MAJOR> can then move to it,
#    and the gate runs on that.
# 5. --promote: loams/pg<MAJOR> is fast-forwarded to that branch
#    (the rulesets refuse anything but a fast-forward).
# Pushes need GH_TOKEN with contents: write on ostrium-labs/postgres
# (LOAMS_BOT_TOKEN). Writes the merge commit's sha to $OUT/sha.
#
# Port mode (NF2 Task 2, D1109; LP-0035): our series for the previous major,
# cherry-picked onto a new major's first base tag, once per major:
#
#   postgres-merge.sh port MAJOR BASE_TAG --from loams/pg<P> --since REL_<P>_<m>
#                     --patch-id LP-<nnnn> [--map FILE] [--push] [--promote] [--keep-going]
#
# 1. A blobless clone of ostrium-labs/postgres at <from>; BASE_TAG and <since>
#    from postgres/postgres. BASE_TAG is fetched with its blobs (only those the
#    fork lacks, since REL_<MAJOR>_STABLE_neon is fetched first as a "have"), so
#    the first --push can create loams/pg<MAJOR> in a fork that lacks them.
# 2. The series is `git rev-list --reverse --topo-order --no-merges <since>..<from>`:
#    topological order, the only order every commit's parent state exists in
#    (docs/core_changes.md groups the series by area; it is not an apply order).
# 3. The run starts at loams/port-pg<MAJOR> (earlier runs' progress) or
#    loams/pg<MAJOR>, else BASE_TAG. A commit whose `(ported from <sha>)` line is
#    already there is not applied again.
# 4. Each commit is cherry-picked; its message gets `(ported from <sha>)` and
#    `Loams-Patch: <patch-id>` (unless it already carries a Loams-Patch trailer)
#    and the bot's sign-off; the author is kept. A commit whose change BASE_TAG
#    already has (an empty result) is left out and listed as "empty".
#    The map (FILE) decides a commit instead, one line each:
#      <sha> patch <file> [note]   apply <file> (relative to the map; a `git diff`
#                                  against the port at that point) instead
#      <sha> neon <neon-sha> [note]  cherry-pick Neon's own version of the change
#                                  from REL_<MAJOR>_STABLE_neon, with
#                                  `(cherry picked from neondatabase/postgres <sha>)`
#      <sha> skip <reason>         leave it out (e.g. upstream already has it)
# 5. The first conflict stops the port. $OUT gets conflicts.txt, conflicts.diff,
#    commit (the series commit), how, commit.patch, files/{ours,base,theirs,merged,
#    upstream}/<path> for every file the commit touches (ours = the port so far,
#    base/theirs = the commit's parent and the commit, upstream = BASE_TAG), and
#    remaining.txt; series.txt has every commit's state. That is enough to write
#    a `patch` resolution without a clone. --keep-going (no --push) instead
#    records each conflict under $OUT/conflicts/<n>-<sha>/, leaves it out and
#    goes on: a survey of the whole series.
# 6. --push: loams/pg<MAJOR> is created at BASE_TAG if missing, and the progress
#    goes to loams/port-pg<MAJOR> (fast-forward only), conflict or not.
#    --promote: when the whole series applied, loams/pg<MAJOR> is fast-forwarded
#    to it. $OUT/sha and $OUT/complete are written then.
set -euo pipefail

auth=()
if [ -n "${GH_TOKEN:-}" ]; then
  auth=(-c "http.https://github.com/.extraheader=AUTHORIZATION: basic $(printf 'x-access-token:%s' "$GH_TOKEN" | base64 -w0)")
fi
fork=${FORK_POSTGRES:-ostrium-labs/postgres}
fork_url=${FORK_POSTGRES_URL:-https://github.com/$fork.git}
upstream=${UPSTREAM_POSTGRES:-https://github.com/postgres/postgres.git}
name=${GIT_NAME:-loams-postgres-bot}
email=${GIT_EMAIL:-loams-postgres-bot@users.noreply.github.com}

port_main() {
  local usage="usage: postgres-merge.sh port MAJOR BASE_TAG --from loams/pg<P> --since REL_<P>_<m> --patch-id LP-<nnnn> [--map FILE] [--push] [--promote] [--keep-going]"
  [ $# -ge 2 ] || { echo "$usage"; exit 2; }
  local major=$1 base=$2; shift 2
  local from="" since="" map="" pid="" push=false promote=false keep=false
  while [ $# -gt 0 ]; do
    case "$1" in
      --from|--since|--map|--patch-id)
        [ $# -ge 2 ] || { echo "$1 needs a value"; exit 2; }
        case "$1" in --from) from=$2 ;; --since) since=$2 ;; --map) map=$2 ;; --patch-id) pid=$2 ;; esac
        shift 2 ;;
      --push) push=true; shift ;;
      --promote) push=true promote=true; shift ;;
      --keep-going) keep=true; shift ;;
      *) echo "unknown option $1"; echo "$usage"; exit 2 ;;
    esac
  done
  [[ $major =~ ^[0-9]+$ && $base =~ ^REL_${major}_[0-9]+$ ]] || { echo "BASE_TAG must be REL_${major}_<minor>, not $base"; exit 2; }
  [[ $from =~ ^loams/pg([0-9]+)$ ]] || { echo "--from must be loams/pg<major>, not '$from'"; exit 2; }
  local prev=${BASH_REMATCH[1]}
  [ "$prev" -lt "$major" ] || { echo "--from $from is not an earlier major than $major"; exit 2; }
  [[ $since =~ ^REL_${prev}_[0-9]+$ ]] || { echo "--since must be REL_${prev}_<minor>, not '$since'"; exit 2; }
  [[ $pid =~ ^LP-[0-9]{4}$ ]] || { echo "--patch-id must be LP-<nnnn>, not '$pid'"; exit 2; }
  if $keep && $push; then echo "--keep-going is a survey: it cannot be combined with --push or --promote"; exit 2; fi

  # The map, read before anything is fetched so a typo fails fast.
  declare -A act=() arg=() note=()
  local mapdir="" mapprefix="" line msha a1 a2 a3
  if [ -n "$map" ]; then
    [ -f "$map" ] || { echo "no map file $map"; exit 2; }
    mapdir=$(cd "$(dirname "$map")" && pwd)
    mapprefix=$(git -C "$mapdir" rev-parse --show-prefix 2> /dev/null || true)
    while IFS= read -r line || [ -n "$line" ]; do
      [[ $line =~ ^[[:space:]]*(#|$) ]] && continue
      read -r msha a1 a2 a3 <<< "$line"
      [[ $msha =~ ^[0-9a-f]{7,40}$ ]] || { echo "map: bad commit '$msha' in: $line"; exit 2; }
      case "$a1" in
        patch) [ -n "$a2" ] && [ -f "$mapdir/$a2" ] || { echo "map: no patch file '$a2' for $msha"; exit 2; } ;;
        neon) [[ $a2 =~ ^[0-9a-f]{40}$ ]] || { echo "map: neon needs a full sha for $msha, not '$a2'"; exit 2; } ;;
        skip) [ -n "$a2" ] || { echo "map: skip needs a reason for $msha"; exit 2; }; a3="$a2${a3:+ $a3}"; a2="" ;;
        *) echo "map: unknown action '$a1' for $msha (patch, neon or skip)"; exit 2 ;;
      esac
      act[$msha]=$a1 arg[$msha]=$a2 note[$msha]=$a3
    done < "$map"
  fi

  local branch=loams/pg$major portb=loams/port-pg$major neonb=REL_${major}_STABLE_neon
  local out work
  out=$(realpath -m "${OUT:-postgres-merge}")
  work=${WORK:-${RUNNER_TEMP:-$PWD}/postgres-port-$major}
  mkdir -p "$out"
  rm -rf "$work"
  git "${auth[@]}" clone -q --filter=blob:none --no-checkout --single-branch --branch "$from" "$fork_url" "$work"
  cd "$work"
  git config user.name "$name"; git config user.email "$email"
  local r
  for r in "$neonb" "$branch" "$portb"; do
    git "${auth[@]}" fetch -q --filter=blob:none --no-tags origin "+refs/heads/$r:refs/remotes/origin/$r" 2> /dev/null || true
  done
  # Both tags with their blobs (--no-filter: a filtered fetch from a URL would
  # make it a promisor and filter every later fetch from it). The haves above
  # (<from> holds <since>; REL_<MAJOR>_STABLE_neon shares BASE_TAG's early
  # history) keep this to the objects the fork lacks, which a first --push needs.
  git fetch -q --no-filter --no-tags "$upstream" "refs/tags/$base:refs/tags/$base" "refs/tags/$since:refs/tags/$since"
  local base_sha; base_sha=$(git rev-parse "$base^{commit}")

  mapfile -t series < <(git rev-list --reverse --topo-order --no-merges "refs/tags/$since..refs/remotes/origin/$from")
  [ ${#series[@]} -gt 0 ] || { echo "no commits in $since..$from"; exit 2; }
  # Map entries name commits of the series by (abbreviated) sha; resolve them.
  declare -A cact=() carg=() cnote=()
  local c k hit
  for k in "${!act[@]}"; do
    hit=""
    for c in "${series[@]}"; do [[ $c == "$k"* ]] && hit+="$c "; done
    [ "$(wc -w <<< "$hit")" -eq 1 ] || { echo "map: $k matches ${hit:-no} commit(s) of $since..$from"; exit 2; }
    hit=${hit% }; cact[$hit]=${act[$k]} carg[$hit]=${arg[$k]} cnote[$hit]=${note[$k]}
  done

  local have_port=false have_branch=false start=$base_sha
  git rev-parse -q --verify "refs/remotes/origin/$portb" > /dev/null && have_port=true
  git rev-parse -q --verify "refs/remotes/origin/$branch" > /dev/null && have_branch=true
  if $have_port && { ! $have_branch || git merge-base --is-ancestor "origin/$branch" "origin/$portb"; }; then
    start=$(git rev-parse "origin/$portb")
  elif $have_branch; then
    start=$(git rev-parse "origin/$branch")
  fi
  git merge-base --is-ancestor "$base_sha" "$start" || { echo "$start does not descend from $base"; exit 2; }
  git checkout -q -B port "$start"
  echo "series: ${#series[@]} commits in $since..$from; base $base $(git rev-parse --short "$base_sha"); start $(git rev-parse --short "$start")"

  declare -A done_=()
  local s
  while read -r s; do [ -n "$s" ] && done_[$s]=1; done < <(git log --format=%B "$base_sha..HEAD" | sed -nE 's/^\(ported from ([0-9a-f]{40})\)$/\1/p')

  : > "$out/series.txt"; rm -rf "$out/conflicts" "$out/files"; rm -f "$out/conflicting.txt" "$out/sha" "$out/complete"
  local n_done=0 n_pick=0 n_neon=0 n_patch=0 n_skip=0 n_empty=0 n_conf=0 i=0 stopped=""
  local how src subj status body tmpmsg
  tmpmsg=$(mktemp)
  for c in "${series[@]}"; do
    i=$((i + 1))
    subj=$(git log -1 --format=%s "$c")
    if [ -n "${done_[$c]:-}" ]; then n_done=$((n_done + 1)); echo "$c done $subj" >> "$out/series.txt"; continue; fi
    how=${cact[$c]:-pick} src=$c status=ok
    case "$how" in
      skip)
        echo "skip  $c $subj: ${cnote[$c]}"
        echo "$c skip $subj (${cnote[$c]})" >> "$out/series.txt"; n_skip=$((n_skip + 1)); continue ;;
      pick) git cherry-pick --no-commit "$c" > /dev/null 2>&1 || status=conflict ;;
      neon) src=${carg[$c]}; git cherry-pick --no-commit "$src" > /dev/null 2>&1 || status=conflict ;;
      patch) git apply --index --3way "$mapdir/${carg[$c]}" > /dev/null 2>&1 || status=conflict ;;
    esac
    if [ "$status" = conflict ]; then
      n_conf=$((n_conf + 1))
      local d=$out
      if $keep; then d=$out/conflicts/$n_conf-$c; echo "$c $subj" >> "$out/conflicting.txt"; fi
      port_record "$d" "$c" "$src" "$how" "$base_sha" "${carg[$c]:-}"
      if $keep; then
        echo "conflict $c $subj ($how): $(tr '\n' ' ' < "$d/conflicts.txt")"
        echo "$c conflict $subj" >> "$out/series.txt"
        git reset -q --hard HEAD; rm -f .git/CHERRY_PICK_HEAD
        continue
      fi
      echo "::error::$c ($subj) does not apply on the port of $from to $major ($how): $(wc -l < "$d/conflicts.txt") file(s)"
      sed 's/^/  conflict: /' "$d/conflicts.txt"
      local j
      for ((j = i - 1; j < ${#series[@]}; j++)); do
        echo "${series[j]} $(git log -1 --format=%s "${series[j]}")" >> "$out/remaining.txt.new"
        [ "$j" -eq $((i - 1)) ] && echo "${series[j]} conflict $subj" >> "$out/series.txt" ||
          echo "${series[j]} pending $(git log -1 --format=%s "${series[j]}")" >> "$out/series.txt"
      done
      mv "$out/remaining.txt.new" "$out/remaining.txt"
      git reset -q --hard HEAD; rm -f .git/CHERRY_PICK_HEAD
      stopped=$c
      break
    fi
    if git diff --cached --quiet; then
      echo "empty $c $subj: $base already has it"
      echo "$c empty $subj" >> "$out/series.txt"; n_empty=$((n_empty + 1))
      git reset -q --hard HEAD; rm -f .git/CHERRY_PICK_HEAD
      continue
    fi
    body=$(git log -1 --format=%B "$src")
    {
      printf '%s\n\n' "$body"
      [ "$how" = neon ] && echo "(cherry picked from neondatabase/postgres $src)"
      echo "(ported from $c)"
      [ "$how" = patch ] && echo "Resolved for $major by ${mapprefix}${carg[$c]}${cnote[$c]:+: ${cnote[$c]}}"
      [ "$how" = neon ] && [ -n "${cnote[$c]}" ] && echo "Note: ${cnote[$c]}"
      echo
      grep -q '^Loams-Patch: ' <<< "$body" || echo "Loams-Patch: $pid"
      echo "Signed-off-by: $name <$email>"
    } > "$tmpmsg"
    GIT_AUTHOR_NAME=$(git log -1 --format=%an "$src") GIT_AUTHOR_EMAIL=$(git log -1 --format=%ae "$src") \
      GIT_AUTHOR_DATE=$(git log -1 --format=%aI "$src") git commit -q --no-verify --cleanup=verbatim -F "$tmpmsg"
    rm -f .git/CHERRY_PICK_HEAD
    case "$how" in pick) n_pick=$((n_pick + 1)) ;; neon) n_neon=$((n_neon + 1)) ;; patch) n_patch=$((n_patch + 1)) ;; esac
    echo "$c $how $subj" >> "$out/series.txt"
    echo "$how  $c $subj"
  done
  rm -f "$tmpmsg"
  local summary="port $from -> $branch: ${#series[@]} in series; $n_done ported before; applied $n_pick cleanly, $n_neon from Neon, $n_patch by patch; $n_skip skipped, $n_empty empty; $n_conf conflict(s)"
  echo "$summary" | tee "$out/summary.txt"
  git rev-parse HEAD > "$out/head"

  if $push; then
    if ! $have_branch; then
      git "${auth[@]}" push -q origin "$base_sha:refs/heads/$branch"
      echo "created $branch at $base ($base_sha)"
    fi
    git "${auth[@]}" push -q origin "HEAD:refs/heads/$portb"
    echo "pushed $portb at $(git rev-parse HEAD)"
  fi
  if [ -n "$stopped" ] || [ "$n_conf" -gt 0 ]; then
    $promote && echo "not promoting $branch: the series is not complete"
    exit 1
  fi
  git rev-parse HEAD > "$out/sha"
  touch "$out/complete"
  if $promote; then
    git "${auth[@]}" push -q origin "HEAD:refs/heads/$branch"
    echo "fast-forwarded $branch to $(git rev-parse HEAD)"
  fi
}

# What a maintainer needs to resolve a stop without a clone (see the header).
port_record() { # dir commit src how base_sha patch-file
  local d=$1 c=$2 src=$3 how=$4 base_sha=$5 pf=$6 p
  mkdir -p "$d"
  echo "$c" > "$d/commit"
  echo "$how${pf:+ $pf}${src:+ $src}" > "$d/how"
  git rev-parse HEAD > "$d/head"
  git diff --name-only --diff-filter=U > "$d/conflicts.txt"
  if [ "$how" = patch ] && [ ! -s "$d/conflicts.txt" ]; then
    git apply --numstat "$mapdir/$pf" 2> /dev/null | cut -f3 > "$d/conflicts.txt" || true
  fi
  git diff > "$d/conflicts.diff" || true
  git show --format=fuller "$src" > "$d/commit.patch" 2> /dev/null || true
  [ "$src" = "$c" ] || git show --format=fuller "$c" > "$d/series-commit.patch" 2> /dev/null || true
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    mkdir -p "$d/files/ours/$(dirname "$p")" "$d/files/base/$(dirname "$p")" "$d/files/theirs/$(dirname "$p")" \
      "$d/files/merged/$(dirname "$p")" "$d/files/upstream/$(dirname "$p")"
    git show "HEAD:$p" > "$d/files/ours/$p" 2> /dev/null || rm -f "$d/files/ours/$p"
    git show "$src^:$p" > "$d/files/base/$p" 2> /dev/null || rm -f "$d/files/base/$p"
    git show "$src:$p" > "$d/files/theirs/$p" 2> /dev/null || rm -f "$d/files/theirs/$p"
    git show "$base_sha:$p" > "$d/files/upstream/$p" 2> /dev/null || rm -f "$d/files/upstream/$p"
    [ -f "$p" ] && cp "$p" "$d/files/merged/$p"
  done < <({ git diff-tree --no-commit-id -r --name-only "$src"; cat "$d/conflicts.txt"; } | sort -u)
}

if [ "${1:-}" = port ]; then
  shift
  port_main "$@"
  exit 0
fi

major=${1:?usage: postgres-merge.sh MAJOR TAG [--push] [--promote]}
tag=${2:?usage: postgres-merge.sh MAJOR TAG [--push] [--promote]}
shift 2
push=false promote=false
for a in "$@"; do
  case "$a" in --push) push=true ;; --promote) push=true promote=true ;; *) echo "unknown option $a"; exit 2 ;; esac
done
[[ $major =~ ^[0-9]+$ && $tag =~ ^REL_${major}_[0-9]+$ ]] || { echo "TAG must be REL_${major}_<minor>, not $tag"; exit 2; }

branch=loams/pg${major}
minor=loams/minor-pg${major}-${tag}
out=$(realpath -m "${OUT:-postgres-merge}")
work=${WORK:-${RUNNER_TEMP:-$PWD}/postgres-$major}
mkdir -p "$out"
rm -rf "$work"

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
