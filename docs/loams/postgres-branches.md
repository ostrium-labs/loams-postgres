# The Postgres fork's branches

Loams Postgres builds Postgres from `ostrium-labs/postgres`, through the submodules `vendor/postgres-v<N>`. `.gitmodules` uses `../postgres.git`, so a checkout of this repository resolves to `ostrium-labs/postgres`.

Design: §51 §3 and D821 in `ostrium-labs/loams`; NF1 Task 15 (LP-0014), recut in NF1 Task 17 (LP-0016).

## Layout

| Branch | What it is |
|---|---|
| `loams/pg<N>` | **Ours**, one per major we maintain (16, 17). Postgres minors from `postgres/postgres` are merged into it, as merge commits carrying `Loams-Sync: <tag>` (NF1 Tasks 17 and 18). Our changes go in by pull request. |
| `loams/minor-pg<N>-REL_<N>_<m>` | One upstream minor's merge, gated before `loams/pg<N>` is fast-forwarded to it. |
| `loams/REL_<N>_STABLE` | **Retired** (16, 17, 18). Superseded on 2026-10-17; kept, never deleted. See below. |
| `REL_<N>_STABLE_neon` | Neon's branch, **frozen history**. Nothing updates it, and nothing mirrors `neondatabase/postgres` any more (D821). |
| `REL_<N>_<m>_neon`, other Neon branches | Neon's leftovers, kept as they are. |
| `loams/meta` | Where the governance files (`SECURITY.md`, `CODEOWNERS`) were first reviewed (NF1 Task 5). |

Each `loams/pg<N>` starts at the revision `main`'s `vendor/revisions.json` pinned before the recut, plus one commit adding `SECURITY.md` and `CODEOWNERS` (`Loams-Patch: LP-0000`):

| Major | Base (Neon's pin) | Governance commit | Current minor |
|---|---|---|---|
| 16 | `a42351fc` (16.9) | `e0ebf572` | 16.15: `loams/minor-pg16-REL_16_15` `23f0d68a` |
| 17 | `1e01fcea` (17.5) | `45d227e0` | 17.11: `loams/minor-pg17-REL_17_11` `aef0fc52` |

Postgres 18 has no branch yet; NF1 Task 24 chooses its base.

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

- For each maintained major, `loams/pg<N>` must exist, descend from its base, carry `SECURITY.md` and `CODEOWNERS`, and refuse force-pushes and deletion.
- The retired `loams/REL_<N>_STABLE` must still exist and refuse deletion.
- `REL_<N>_STABLE_neon` must refuse updates.
- Every submodule URL must be `../postgres.git`, and `vendor/postgres-v16` and `vendor/postgres-v17` must track `loams/pg16` and `loams/pg17`.

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
