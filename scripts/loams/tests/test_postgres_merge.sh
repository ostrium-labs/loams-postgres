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
# The port mode (NF2 Task 2, D1109): the 17 series cherry-picked onto REL_18_6.
#   port_mode_applies_series          every commit lands in order with "(ported from <sha>)" and the
#                                     trailer; the first --push creates loams/pg18 at the base tag
#   port_mode_stops_on_conflict       the first conflict stops the port: files, diff, the 17 commit,
#                                     the file versions and the remaining list are written; progress
#                                     goes to loams/port-pg18 and loams/pg18 stays at the base
#   port_map_patch_resumes            a map entry `patch` resolves it; the next run resumes from
#                                     loams/port-pg18 without re-applying, and --promote moves loams/pg18
#   port_map_neon_and_skip            `neon <sha>` takes Neon's 18 commit, `skip` leaves one out
#   port_map_extra_commits            `before <file>` and `end <file>` add our own commits (mbox) at
#                                     their place, once: a resumed run does not apply them again
#   port_keep_going_lists_all         --keep-going (no push) surveys every conflict
#   port_promote_needs_complete       --promote never moves loams/pg18 to an incomplete series
#   port_bad_args_refused
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

# --- port mode -------------------------------------------------------------
# up:   REL_17_STABLE (REL_17_11) and REL_18_STABLE (REL_18_6), both from one root.
# fork: loams/pg17 = REL_17_11 + c0 (new file), c1 (smgr hook), a merge of an
#       upstream-like side commit (left out: --no-merges), c2 (governance, already
#       carrying LP-0000); REL_18_STABLE_neon = an 18 base + Neon's own n1.
port_setup() { # $1: conflict | clean
  rm -rf "$tmp/up" "$tmp/fork" "$tmp/out" "$tmp/work" "$tmp/w"
  git init -q -b master "$tmp/up"
  ( cd "$tmp/up"
    printf 'a\nb\nc\n' > smgr.c; echo root > version; echo old > zz_gone.c; git add .; git commit -q -m root
    git checkout -q -b REL_17_STABLE; echo 17.11 > version; git commit -q -am 17.11; git tag REL_17_11
    git checkout -q -b REL_18_STABLE master
    if [ "$1" = conflict ]; then printf 'a\nREADV\nc\n' > smgr.c; git rm -q zz_gone.c; fi
    echo 18.2 > version; git commit -q -am 18.2; git tag REL_18_2
    echo 18.6 > version; git commit -q -am 18.6; git tag REL_18_6 )
  git -C "$tmp/up" config uploadpack.allowFilter true
  git init -q --bare "$tmp/fork"
  git -C "$tmp/fork" config uploadpack.allowFilter true
  git -C "$tmp/fork" config uploadpack.allowAnySHA1InWant true
  git clone -q "$tmp/fork" "$tmp/w" 2> /dev/null
  ( cd "$tmp/w"
    git fetch -q "$tmp/up" REL_17_STABLE REL_18_2
    git checkout -q -b loams/pg17 FETCH_HEAD 2> /dev/null || true
    git checkout -q -B loams/pg17 "$(git -C "$tmp/up" rev-parse REL_17_11)"
    echo feature > feature.c; git add feature.c; git commit -q -m "c0: neon feature" -m "Body of c0."
    printf 'a\nNEON\nc\n' > smgr.c; echo neon > zz_gone.c; git commit -q -am "c1: neon smgr hook"
    git checkout -q -b side HEAD~1; echo side > side.c; git add side.c; git commit -q -m "side"
    git checkout -q loams/pg17; git merge -q --no-ff -m "merge side" side
    echo sec > SECURITY.md; git add SECURITY.md; git commit -q -m "c2: governance" -m "Loams-Patch: LP-0000"
    git push -q origin loams/pg17
    git checkout -q -b REL_18_STABLE_neon "$(git -C "$tmp/up" rev-parse REL_18_2)"
    printf 'a\nNEON18\nc\n' > smgr.c; git commit -q -am "n1: neon smgr hook at 18"
    git push -q origin REL_18_STABLE_neon )
  rm -rf "$tmp/w"
}
port() { FORK_POSTGRES_URL="file://$tmp/fork" UPSTREAM_POSTGRES="file://$tmp/up" OUT="$tmp/out" WORK="$tmp/work" \
  "$script" port 18 REL_18_6 --from loams/pg17 --since REL_17_11 --patch-id LP-0099 "$@" > "$tmp/log" 2>&1; }
sha() { git -C "$tmp/fork" rev-parse -q --verify "$1^{commit}" 2> /dev/null || true; }
src() { git -C "$tmp/fork" log --format=%H --grep="^$1" loams/pg17; } # the 17 commit by subject prefix
subjects() { git -C "$tmp/fork" log --reverse --format=%s "$(git -C "$tmp/up" rev-parse REL_18_6)..$1" | tr '\n' '|'; }

port_setup clean
base18=$(git -C "$tmp/up" rev-parse REL_18_6)
if port --push; then
  head=$(sha loams/port-pg18) c1=$(src "c1:")
  msg1=$(git -C "$tmp/fork" log -1 --format=%B --grep='^c1:' loams/port-pg18)
  msg2=$(git -C "$tmp/fork" log -1 --format=%B --grep='^c2:' loams/port-pg18)
  if [ "$(subjects loams/port-pg18)" = "c0: neon feature|c1: neon smgr hook|side|c2: governance|" ] &&
     [ "$(sha loams/pg18)" = "$base18" ] && [ "$head" = "$(cat "$tmp/out/sha")" ] && [ -f "$tmp/out/complete" ] &&
     [[ $msg1 == *"(ported from $c1)"* && $msg1 == *"Loams-Patch: LP-0099"* ]] &&
     [[ $msg2 == *"Loams-Patch: LP-0000"* && $msg2 != *"LP-0099"* ]] &&
     [ "$(git -C "$tmp/fork" log -1 --format=%an --grep='^c1:' loams/port-pg18)" = t ] &&
     [ "$(git -C "$tmp/fork" show loams/port-pg18:smgr.c | sed -n 2p)" = NEON ] &&
     [ "$(git -C "$tmp/fork" show loams/port-pg18:version)" = 18.6 ] && ! grep -q 'fatal:' "$tmp/log"; then
    ok port_mode_applies_series
  else fail port_mode_applies_series "$(subjects loams/port-pg18) pg18=$(sha loams/pg18) $msg1 $(cat "$tmp/log")"; fi
else fail port_mode_applies_series "$(cat "$tmp/log")"; fi

port_setup conflict
base18=$(git -C "$tmp/up" rev-parse REL_18_6)
c1=$(src "c1:")
if port --push --promote; then fail port_mode_stops_on_conflict "ported a conflict"
elif grep -qx smgr.c "$tmp/out/conflicts.txt" 2> /dev/null && grep -q '<<<<<<<' "$tmp/out/conflicts.diff"; then
  if [ "$(head -1 "$tmp/out/remaining.txt" | cut -d' ' -f1)" = "$c1" ] && grep -q '^c2: governance' <(cut -d' ' -f2- "$tmp/out/remaining.txt") &&
     [ "$(cat "$tmp/out/commit")" = "$c1" ] && grep -q '^+NEON' "$tmp/out/commit.patch" &&
     [ "$(sed -n 2p "$tmp/out/files/ours/smgr.c")" = READV ] && [ "$(sed -n 2p "$tmp/out/files/theirs/smgr.c")" = NEON ] &&
     [ "$(sed -n 2p "$tmp/out/files/base/smgr.c")" = b ] && grep -q '<<<<<<<' "$tmp/out/files/merged/smgr.c" &&
     [ "$(subjects loams/port-pg18)" = "c0: neon feature|" ] && [ "$(sha loams/pg18)" = "$base18" ]; then
    ok port_mode_stops_on_conflict
  else fail port_mode_stops_on_conflict "remaining=$(cat "$tmp/out/remaining.txt") port=$(subjects loams/port-pg18) $(cat "$tmp/log")"; fi
else fail port_mode_stops_on_conflict "$(cat "$tmp/log")"; fi

# Resolve c1 with a patch made from the stop's files, as a maintainer would without a clone.
mkdir -p "$tmp/map/pg18"
rm -rf "$tmp/res"; git init -q "$tmp/res"
( cd "$tmp/res"; cp "$tmp/out/files/ours/smgr.c" smgr.c 2> /dev/null || true; git add -A; git commit -q -m ours --allow-empty
  printf 'a\nREADV\nNEON\nc\n' > smgr.c; git add -A; git diff --cached > "$tmp/map/pg18/$c1.patch" )
printf '# test map\n%s patch %s.patch  smgr hook beside 18 readv\n' "$c1" "$c1" > "$tmp/map/pg18/map"
port0=$(sha loams/port-pg18)
if port --map "$tmp/map/pg18/map" --push --promote; then
  msg1=$(git -C "$tmp/fork" log -1 --format=%B --grep='^c1:' loams/port-pg18)
  if [ "$(subjects loams/port-pg18)" = "c0: neon feature|c1: neon smgr hook|side|c2: governance|" ] &&
     git -C "$tmp/fork" merge-base --is-ancestor "$port0" loams/port-pg18 &&
     [ "$(sha loams/pg18)" = "$(sha loams/port-pg18)" ] &&
     [[ $msg1 == *"(ported from $c1)"* && $msg1 == *"Loams-Patch: LP-0099"* ]] &&
     [ "$(git -C "$tmp/fork" show loams/pg18:smgr.c | tr '\n' ' ')" = "a READV NEON c " ]; then
    ok port_map_patch_resumes
  else fail port_map_patch_resumes "$(subjects loams/port-pg18) $(cat "$tmp/log")"; fi
else fail port_map_patch_resumes "$(cat "$tmp/log")"; fi

port_setup conflict
c1=$(src "c1:") c0=$(src "c0:")
n1=$(git -C "$tmp/fork" rev-parse REL_18_STABLE_neon)
printf '%s neon %s\n%s skip upstream 18 already has it\n' "$c1" "$n1" "$c0" > "$tmp/map/pg18/map"
if port --map "$tmp/map/pg18/map"; then
  wk=$tmp/work
  msg1=$(git -C "$wk" log -1 --format=%B --grep='^n1:' HEAD)
  if [ "$(git -C "$wk" log --reverse --format=%s "$(git -C "$tmp/up" rev-parse REL_18_6)..HEAD" | tr '\n' '|')" = "n1: neon smgr hook at 18|side|c2: governance|" ] &&
     [[ $msg1 == *"(cherry picked from neondatabase/postgres $n1)"* && $msg1 == *"(ported from $c1)"* && $msg1 == *"Loams-Patch: LP-0099"* ]] &&
     grep -q "skip.*$c0" "$tmp/log" && [ -z "$(sha loams/port-pg18)" ] && [ -z "$(sha loams/pg18)" ]; then
    ok port_map_neon_and_skip
  else fail port_map_neon_and_skip "$(git -C "$wk" log --format=%s -5) $(cat "$tmp/log")"; fi
else fail port_map_neon_and_skip "$(cat "$tmp/log")"; fi

# Our own commits, as mboxes: one before c0, one after the series.
port_setup clean
c0=$(src "c0:")
rm -rf "$tmp/res"; git init -q "$tmp/res"
( cd "$tmp/res"; git fetch -q "$tmp/up" REL_18_6 && git checkout -q FETCH_HEAD
  echo pre > pre.c; git add pre.c; git commit -q -m "pre: before the series" -m "Loams-Patch: LP-0098"
  git format-patch -q -1 --stdout > "$tmp/map/pg18/pre.mbox"
  echo post > post.c; git add post.c; git commit -q -m "post: after the series" -m "Loams-Patch: LP-0097"
  git format-patch -q -1 --stdout > "$tmp/map/pg18/post.mbox" )
printf '%s before pre.mbox\nend post.mbox\n' "$c0" > "$tmp/map/pg18/map"
if port --map "$tmp/map/pg18/map" --push && port --map "$tmp/map/pg18/map" --push; then
  if [ "$(subjects loams/port-pg18)" = "pre: before the series|c0: neon feature|c1: neon smgr hook|side|c2: governance|post: after the series|" ] &&
     [[ $(git -C "$tmp/fork" log -1 --format=%B --grep='^pre:' loams/port-pg18) == *"Loams-Patch: LP-0098"* ]] &&
     grep -q 'done  extra pre.mbox' "$tmp/log"; then
    ok port_map_extra_commits
  else fail port_map_extra_commits "$(subjects loams/port-pg18) $(cat "$tmp/log")"; fi
else fail port_map_extra_commits "$(cat "$tmp/log")"; fi

# Two conflicting commits: --keep-going lists both and still fails.
port_setup conflict
( cd "$tmp/up"; git checkout -q REL_18_STABLE; git tag -d REL_18_6 > /dev/null
  printf 'X\n' > SECURITY.md; git add SECURITY.md; git commit -q -m sec18; git tag REL_18_6 )
if port --keep-going; then fail port_keep_going_lists_all "no conflict reported"
elif [ "$(cut -d' ' -f1 "$tmp/out/conflicting.txt" | tr '\n' ' ')" = "$(src "c1:") $(src "c2:") " ] &&
     [ -f "$tmp/out/conflicts/1-$(src "c1:")/conflicts.txt" ] && [ -f "$tmp/out/summary.txt" ] &&
     [ -f "$tmp/out/conflicts/1-$(src "c1:")/files/theirs/zz_gone.c" ]; then
  ok port_keep_going_lists_all
else fail port_keep_going_lists_all "$(cat "$tmp/out/conflicting.txt" 2> /dev/null) $(cat "$tmp/log")"; fi
if port --keep-going --push; then fail port_bad_args_refused "--keep-going with --push"; fi

port_setup conflict
if ! port --promote && [ "$(sha loams/pg18)" = "$(git -C "$tmp/up" rev-parse REL_18_6)" ]; then
  ok port_promote_needs_complete
else fail port_promote_needs_complete "pg18=$(sha loams/pg18) $(cat "$tmp/log")"; fi

bad=0
for args in "port 18 REL_17_6 --from loams/pg17 --since REL_17_11 --patch-id LP-0099" \
            "port 18 REL_18_6 --since REL_17_11 --patch-id LP-0099" \
            "port 18 REL_18_6 --from loams/pg17 --patch-id LP-0099" \
            "port 18 REL_18_6 --from loams/pg17 --since REL_17_11" \
            "port 18 REL_18_6 --from loams/pg17 --since REL_17_11 --patch-id LP-99" \
            "port 18 REL_18_6 --from loams/pg17 --since REL_17_11 --patch-id LP-0099 --map /nonexistent"; do
  # shellcheck disable=SC2086
  if FORK_POSTGRES_URL="file://$tmp/fork" UPSTREAM_POSTGRES="file://$tmp/up" OUT="$tmp/out" WORK="$tmp/work" \
     "$script" $args > "$tmp/log" 2>&1; then bad=1; echo "  accepted: $args"; fi
done
printf 'deadbeef frobnicate x\n' > "$tmp/map/badmap"
if port --map "$tmp/map/badmap"; then bad=1; echo "  accepted an unknown map action"; fi
[ "$bad" -eq 0 ] && ok port_bad_args_refused || fail port_bad_args_refused "see above"

[ "$fails" -eq 0 ] || { echo "$fails failure(s)"; exit 1; }
echo "all passed"
