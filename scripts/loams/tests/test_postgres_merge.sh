#!/usr/bin/env bash
# Tests for scripts/loams/postgres-merge.sh (LP-0016, NF1 Task 17), on local
# repositories built here: a "fork" with loams/pg17 (an upstream
# history plus one Loams commit) and an "upstream" with a new minor tag.
#   clean_merge_pushes_minor_branch   the merge carries Loams-Sync and goes to loams/minor-17-<tag>
#   already_merged_is_a_no_op
#   conflict_lists_files              a conflicting minor fails and lists the file
#   promote_fast_forwards             --promote moves loams/pg17 to the merge already on the minor branch
#   hand_resolution_is_reused         a minor branch resolved by hand is promoted as is, not re-merged
#   bad_tag_refused
# Run: scripts/loams/tests/test_postgres_merge.sh
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
script=$here/../postgres-merge.sh
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.com GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.com
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
fails=0
fail() { echo "FAIL $1: $2"; fails=$((fails + 1)); }
ok() { echo "ok   $1"; }

setup() { # $1: whether upstream's new minor conflicts with the Loams commit
  rm -rf "$tmp/up" "$tmp/fork" "$tmp/out" "$tmp/work"
  git init -q -b REL_17_STABLE "$tmp/up"
  ( cd "$tmp/up"
    printf 'a\nb\nc\n' > smgr.c; echo 17.8 > version; git add .; git commit -q -m "17.8"; git tag REL_17_8 )
  git clone -q --bare "$tmp/up" "$tmp/fork"
  git -C "$tmp/fork" config uploadpack.allowFilter true
  git -C "$tmp/fork" branch loams/pg17 REL_17_STABLE
  git clone -q -b loams/pg17 "$tmp/fork" "$tmp/w"
  ( cd "$tmp/w"; printf 'a\nNEON\nc\n' > smgr.c; git commit -q -am "neon: smgr hook"; git push -q origin loams/pg17 )
  rm -rf "$tmp/w"
  ( cd "$tmp/up"
    echo 17.11 > version
    if [ "$1" = conflict ]; then printf 'a\nUPSTREAM\nc\n' > smgr.c; fi
    git commit -q -am "17.11"; git tag REL_17_11 )
  git -C "$tmp/up" config uploadpack.allowFilter true
}
run() { FORK_POSTGRES_URL="file://$tmp/fork" UPSTREAM_POSTGRES="file://$tmp/up" OUT="$tmp/out" WORK="$tmp/work" \
  "$script" "$@" > "$tmp/log" 2>&1; }

setup clean
if run 17 REL_17_11 --push; then
  msg=$(git -C "$tmp/fork" log -1 --format=%B loams/minor-pg17-REL_17_11 2>/dev/null || true)
  if [[ $msg == *"Merge REL_17_11 into loams/pg17"* && $msg == *"Loams-Sync: REL_17_11"* ]] &&
     [ "$(git -C "$tmp/fork" rev-parse loams/minor-pg17-REL_17_11)" = "$(cat "$tmp/out/sha")" ] &&
     [ "$(git -C "$tmp/fork" show loams/minor-pg17-REL_17_11:smgr.c | sed -n 2p)" = NEON ] &&
     [ "$(git -C "$tmp/fork" show loams/minor-pg17-REL_17_11:version)" = 17.11 ]; then
    ok clean_merge_pushes_minor_branch
  else fail clean_merge_pushes_minor_branch "$msg"; fi
  stable_before=$(git -C "$tmp/fork" rev-parse loams/pg17)
  [ "$stable_before" != "$(cat "$tmp/out/sha")" ] || fail clean_merge_pushes_minor_branch "pushed the stable branch without --promote"
else fail clean_merge_pushes_minor_branch "$(cat "$tmp/log")"; fi

if run 17 REL_17_11 --promote && [ "$(git -C "$tmp/fork" rev-parse loams/pg17)" = "$(cat "$tmp/out/sha")" ]; then
  ok promote_fast_forwards
else fail promote_fast_forwards "$(cat "$tmp/log")"; fi

if run 17 REL_17_11 && grep -q 'already' "$tmp/log"; then ok already_merged_is_a_no_op
else fail already_merged_is_a_no_op "$(cat "$tmp/log")"; fi

setup conflict
if run 17 REL_17_11 --push; then fail conflict_lists_files "merged a conflict"
elif grep -qx smgr.c "$tmp/out/conflicts.txt" && ! git -C "$tmp/fork" rev-parse -q --verify loams/minor-pg17-REL_17_11 > /dev/null; then
  ok conflict_lists_files
else fail conflict_lists_files "$(cat "$tmp/log")"; fi

# A conflicting minor resolved by hand on loams/minor-pg17-REL_17_11 is reused by --promote.
setup conflict
git clone -q -b loams/pg17 "$tmp/fork" "$tmp/w"
( cd "$tmp/w"; git fetch -q "$tmp/up" refs/tags/REL_17_11:refs/tags/REL_17_11
  git merge -q REL_17_11 > /dev/null 2>&1 || true
  printf 'a\nRESOLVED\nc\n' > smgr.c; git add smgr.c; git commit -q -m "Merge REL_17_11 (resolved by hand)"
  git push -q origin HEAD:refs/heads/loams/minor-pg17-REL_17_11 )
hand=$(git -C "$tmp/w" rev-parse HEAD); rm -rf "$tmp/w"
if run 17 REL_17_11 --promote && [ "$(git -C "$tmp/fork" rev-parse loams/pg17)" = "$hand" ]; then
  ok hand_resolution_is_reused
else fail hand_resolution_is_reused "$(cat "$tmp/log")"; fi

if run 17 REL_16_15; then fail bad_tag_refused "accepted REL_16_15 for 17"; else ok bad_tag_refused; fi

[ "$fails" -eq 0 ] || { echo "$fails failure(s)"; exit 1; }
echo "all passed"
