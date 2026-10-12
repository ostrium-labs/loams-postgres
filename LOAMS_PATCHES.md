# Loams Postgres patches

Every change Loams Postgres makes to Neon after `neon-fork-point` (`fa504217`)
is a patch with an id `LP-<nnnn>` and a row below. Each commit of a patch
carries the trailer `Loams-Patch: LP-<nnnn>` (with `Signed-off-by`, DCO).
`scripts/loams/check-patches.py` checks the history against this file in
`.github/workflows/loams-patches.yml`: a commit without a trailer, a trailer
without a row and a row without a commit all fail.

How to add a patch:

1. Take the next free id. Ids the NF1 plan has already given to its tasks
   (LP-0002 to LP-0031) are kept for them; LP-0018 is retired.
2. Add the row in the same pull request as the patch's first commit.
3. Put `Loams-Patch: LP-<nnnn>` in every commit message of the patch
   (`git commit -s` adds the sign-off below it).
4. Merge with a merge commit, so the trailers reach `main` unchanged.

Columns:

- **Origin**: `loams-only` (Loams' own behaviour, not meant for another
  fork), `upstreamable` (a general fix another Neon fork could take as is;
  nothing is sent upstream, D820), or `cherry-pick` (taken by hand from
  `neondatabase/neon`; each commit carries
  `(cherry picked from neondatabase/neon <40 hex sha>)`).
- **Drop when**: the condition under which the patch can be reverted, or
  `never`.

## Patches

| Id | Title | Area | Owner | Since | Origin | Drop when |
|---|---|---|---|---|---|---|
| LP-0000 | Fork governance: charter, patch queue and its check | ci | @dina-kar | 2026-10-11 | loams-only | never |
| LP-0001 | Decoder trim: `pageserver_api` and `postgres_ffi` let API-only consumers leave out the storage clients and pprof | build | @dina-kar | 2026-10-08 | upstreamable | never (Loams' WAL decoder builds on it) |

## Commits without a trailer

Commits on `main` that predate the trailer rule. History is never rewritten,
so they are mapped to their patch here.

| Commit | Id | Why |
|---|---|---|
| 1218fb7a6a37e1b4c268bad5c2952c238d81d368 | LP-0001 | Fast-forwarded onto `main` before the patch queue existed (NF1 Task 3) |
