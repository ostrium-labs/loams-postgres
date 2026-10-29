# The Postgres fork's branches

Loams Postgres builds Postgres from `ostrium-labs/postgres`, through the submodules `vendor/postgres-v<N>`. `.gitmodules` uses `../postgres.git`, so a checkout of this repository resolves to `ostrium-labs/postgres`.

Design: §51 §3 and D821 in `ostrium-labs/loams`; NF1 Task 15 (LP-0014), recut in NF1 Task 17 (LP-0016). Postgres 18: §62 §3 and D1109, NF2 Task 2 (LP-0035).

## Layout

| Branch | What it is |
|---|---|
| `loams/pg<N>` | **Ours**, one per major we maintain (16, 17, and 18 in beta). Postgres minors from `postgres/postgres` are merged into it, as merge commits carrying `Loams-Sync: <tag>` (NF1 Tasks 17 and 18). Our changes go in by pull request. |
| `loams/minor-pg<N>-REL_<N>_<m>` | One upstream minor's merge, gated before `loams/pg<N>` is fast-forwarded to it. |
| `loams/port-pg<N>` | The port of the previous major's series onto a new major's base, while it is in progress (18: onto `REL_18_6`). Fast-forward only; `loams/pg<N>` is fast-forwarded to it once the whole series applies and the checks pass. Kept afterwards, like every `loams/*` branch. |
| `loams/REL_<N>_STABLE` | **Retired** (16, 17, 18). Superseded on 2026-10-17; kept, never deleted. See below. |
| `REL_<N>_STABLE_neon` | Neon's branch, **frozen history**. Nothing updates it, and nothing mirrors `neondatabase/postgres` any more (D821). |
| `REL_<N>_<m>_neon`, other Neon branches | Neon's leftovers, kept as they are. |
| `loams/meta` | Where the governance files (`SECURITY.md`, `CODEOWNERS`) were first reviewed (NF1 Task 5). |

Each `loams/pg<N>` starts at the revision `main`'s `vendor/revisions.json` pinned before the recut, plus one commit adding `SECURITY.md` and `CODEOWNERS` (`Loams-Patch: LP-0000`):

| Major | Base (Neon's pin) | Governance commit | Current minor |
|---|---|---|---|
| 16 | `a42351fc` (16.9) | `e0ebf572` | 16.15: `loams/minor-pg16-REL_16_15` `23f0d68a` |
| 17 | `1e01fcea` (17.5) | `45d227e0` | 17.11: `loams/minor-pg17-REL_17_11` `aef0fc52` |

`loams/pg18` is different (D1109): it starts at upstream's `REL_18_6` (`724edf9b`), not at a Neon revision, and our 17 series is ported onto it once (below). Neon's `REL_18_STABLE_neon` (18.2) is read as a reference for resolutions only: it comes from the later Neon tree whose `pgxn/neon` half was never published, as for 16 and 17.

| Major | Base | Series | Current minor |
|---|---|---|---|
| 18 | `724edf9b` (`REL_18_6`) | `REL_17_11..loams/pg17`, ported by `loams/port-pg18`; `loams/pg18` = `735664df` (2026-10-29) | 18.6 |

**The port as done (2026-10-29).** The series is 99 commits. 70 cherry-picked unchanged. 21 needed a resolution, each a `resolve` file next to the map; one is Neon's own 18 version (`a6f2a366`, index-scan prefetch only). 4 were left out: Neon's CI workflow, prefetch in autoprewarm and in heap vacuum (18 reads both through the read stream, which prefetches through the smgr), and the `strchrnul()` detection fix, which 18 has. 3 were empty because 18 already has them. Our own commits are the D1112 revert of 18.6's VM block references (LP-0037, owner ruling 2026-10-29), Neon's guard against invalidation processing in WAL redo (LP-0036) and two fixes for call sites 18.6 added (LP-0038). `make check` and `make installcheck-world` pass on `735664df` (run 40842834855; promoted by run 40843653183).

## Why the Task 15 branches were retired (owner, 2026-10-17)

NF1 Task 15 started `loams/REL_<N>_STABLE` at the heads of Neon's `REL_<N>_STABLE_neon` (16 `59027122`, 17 `56692dfb`, 18 `a616eefe`). Those heads are 387 (16) and 475 (17) commits past the revisions this repository's `main` pins.

That range holds upstream minors, and also Neon's own Postgres-side changes: "Remove unnecessary set_lwlsn_block_* hooks", "Move LastWrittenLsnLock to neon extension", the moved `neon_storage_token` GUC, and `f_smgr` without `smgr_read_slru_segment`. Those changes need `pgxn/neon` changes that Neon never published. Our `pgxn/neon` does not build against them, which is how the first 16.15 gate found the problem.

`REL_18_STABLE_neon` has the same changes (no `set_lwlsn_block_*` hooks), so `loams/REL_18_STABLE` is retired too.

The recut keeps Neon's matching pair: the pinned Postgres revision and this repository's `pgxn/neon`. Postgres minors are merged on top of it. The retired branches stay protected and are never deleted. Revisions pinned from them are still reachable.

## Protection

Rulesets on `ostrium-labs/postgres`, with no bypass actors:

- `loams/*: no force-push, no deletion`: `non_fast_forward` and `deletion` on `refs/heads/loams/**`, which covers `loams/pg<N>`, the minor branches and the retired branches;
- `REL_*_STABLE_neon: frozen history`: `update`, `non_fast_forward` and `deletion`;
- `loams: pinned tags are immutable`, on the tags.

Branches are created through the REST API (`gh api repos/ostrium-labs/postgres/git/refs`).

## The check

`scripts/loams/check-postgres-branches.py` checks this layout in `loams-hygiene.yml`, with its tests in `scripts/loams/tests/test_postgres_branches.py`:

- For each maintained major, `loams/pg<N>` must exist, descend from its base, carry `SECURITY.md` and `CODEOWNERS`, and refuse force-pushes and deletion. The majors checked are those whose submodule tracks `loams/pg<N>` in `.gitmodules` (or `--majors`), so 18 is checked from the commit that vendors it.
- The retired `loams/REL_<N>_STABLE` must still exist and refuse deletion.
- `REL_<N>_STABLE_neon` must refuse updates.
- Every submodule URL must be `../postgres.git`, and `vendor/postgres-v16`, `vendor/postgres-v17` and `vendor/postgres-v18` must track `loams/pg16`, `loams/pg17` and `loams/pg18`.

## Taking an upstream minor

Postgres minors come in by merge, never by rebase (D821). `loams-postgres-merge.yml` does the merge in CI, in a blobless clone inside the job:

```
gh workflow run loams-postgres-merge.yml --repo ostrium-labs/loams-postgres -f major=17 -f tag=REL_17_11            # try only
gh workflow run loams-postgres-merge.yml --repo ostrium-labs/loams-postgres -f major=17 -f tag=REL_17_11 -f push=true
```

1. **The merge.** The commit is `Merge REL_<N>_<m> into loams/pg<N>`, with the trailer `Loams-Sync: REL_<N>_<m>`.
2. **`push`.** The merge goes to `loams/minor-pg<N>-REL_<N>_<m>`. `vendor/postgres-v<N>` and `vendor/revisions.json` move to it in a pull request here, and the gate (`loams-gate.yml`) runs on that pull request's branch.
3. **`promote`.** Once the gate is green, `promote` fast-forwards `loams/pg<N>` to the minor branch. It reuses the minor branch as it is and never re-merges, so `loams/pg<N>` gets exactly what the gate tested.

**A conflict** fails the job and uploads the conflicted files and the diff as an artifact.
- A maintainer resolves it by hand, in a blobless clone, and pushes the result to `loams/minor-pg<N>-REL_<N>_<m>`.
- Each resolution is recorded in the merge commit's message. Neon's patched areas are listed in `docs/core_changes.md`.
- Some changes merge without a textual conflict but still need a fix. The 16.15 and 17.11 merges each had one: a new upstream `_bt_get_endpoint()` call needs Neon's extra argument. The build in G1 finds these.

## Porting the series to a new major

A new major gets our series once, by cherry-pick; after that its minors come in by merge as above (§62 §3.2). `loams-postgres-merge.yml` does it in CI with `mode=port`:

```
gh workflow run loams-postgres-merge.yml --repo ostrium-labs/loams-postgres \
  -f mode=port -f major=18 -f tag=REL_18_6 -f since=REL_17_11 -f patch_id=LP-0035 -f keep_going=true   # survey every conflict
gh workflow run loams-postgres-merge.yml --repo ostrium-labs/loams-postgres \
  -f mode=port -f major=18 -f tag=REL_18_6 -f since=REL_17_11 -f patch_id=LP-0035 -f push=true        # apply, push progress
gh workflow run loams-postgres-merge.yml --repo ostrium-labs/loams-postgres \
  -f mode=port -f major=18 -f tag=REL_18_6 -f since=REL_17_11 -f patch_id=LP-0035 -f promote=true     # complete: check, then promote
```

1. **The series** is `git rev-list --reverse --topo-order --no-merges REL_17_11..loams/pg17`. Topological order is the only order in which every commit's parent state exists. `docs/core_changes.md` groups the series by area and is not an apply order. Merge commits (Neon's merges of 17.1 to 17.5, our 17.11 merge) are left out. Fixes made inside a merge, like 17.11's `_bt_get_endpoint()` argument, are not carried; G1's build finds what 18 needs.
2. **Each commit** is cherry-picked. Its message gets `(ported from <17 sha>)`, `Loams-Patch: LP-0035` and the bot's sign-off, and its author is kept. A commit that already carries a `Loams-Patch` trailer (the governance commit, LP-0000) keeps it. A commit whose change `REL_18_6` already has is left out as "empty".
3. **The map**, `scripts/loams/port/pg18/map`, decides a commit that does not cherry-pick as it is:
   - `resolve <file>`: cherry-pick the commit as usual, put the files `<file>` names back to the port's version, and apply `<file>`, a diff from that version, to them. `#keep-ours <path>` keeps the port's version of a conflicted file, and `#keep-deleted <path>` accepts the port's deletion of one. This is the form to use: the commit's clean files apply by 3-way merge, as unmapped commits do. The commit records `Resolved for 18 by scripts/loams/port/pg18/<file>`.
   - `patch <file>`: apply a whole `git diff` against the port at that point instead of the commit. In a blobless clone the 17-side blob ids of a cherry-picked diff cannot be fetched, so `git apply` has no 3-way fallback; prefer `resolve`.
   - `neon <sha>`: take Neon's own 18 version of the change from `REL_18_STABLE_neon`, with `(cherry picked from neondatabase/postgres <sha>)`. It is a reference for a resolution, never a base.
   - `skip <reason>`: leave it out.
   - `before <mbox>` and `end <mbox>`: our own commit (`git format-patch` output, with its own message and `Loams-Patch` id), applied before a series commit or after the series, once (a resumed run recognises it by patch-id).
   GitHub sometimes answers a batched lazy fetch of missing blobs with "not our ref", although it serves the same blobs one at a time; the port then fetches them one by one and tries the cherry-pick again.
4. **A conflict** stops the port. The artifact `postgres-port-<major>-<tag>-<attempt>` holds what a resolution needs, so no clone is needed: `conflicts.txt`, `conflicts.diff`, `commit.patch`, `remaining.txt`, `series.txt` (every commit's state), and `files/{ours,base,theirs,merged,upstream}/<path>` for every file the commit touches. Here `ours` is the port so far, `base` and `theirs` are the 17 commit's parent and the commit, and `upstream` is `REL_18_6`. Write the resolved files, make the diff against `ours`, add it to the map and run again. `keep_going` surveys the whole series (each conflict is recorded under `conflicts/<n>-<sha>/` and left out), and never pushes.
5. **`push`** creates `loams/pg18` at `REL_18_6` if it is missing (the fork lacked 18.6's objects, so the REST API could not create it), and pushes the progress to `loams/port-pg18`. A later run starts there and does not apply a commit whose `(ported from <sha>)` is already on it.
6. **`check`** builds the complete series on its own and runs `make check` and `make installcheck-world`. **`promote`** runs the checks and then fast-forwards `loams/pg18` to exactly the commit they built. `vendor/postgres-v18` then points at it.
7. **A change to what a WAL record carries** is never decided in a resolution (§62's rule). It goes to the owner as a ruling first.
