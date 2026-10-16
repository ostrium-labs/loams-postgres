# The Postgres fork's branches

Loams Postgres builds Postgres from `ostrium-labs/postgres`, through the submodules
`vendor/postgres-v<N>` (`.gitmodules` uses `../postgres.git`, so a checkout of this
repository resolves to `ostrium-labs/postgres`). Design: §51 §3 and D821 in
`ostrium-labs/loams`; NF1 Task 15 (LP-0014).

## Layout

| Branch | What it is |
|---|---|
| `loams/REL_<N>_STABLE` | **Ours**, one per major (16, 17, 18). Postgres minors from `postgres/postgres` are merged into it (merge commits with `Loams-Sync: <tag>`, NF1 Tasks 17 and 18). Our changes go in by pull request. |
| `REL_<N>_STABLE_neon` | Neon's branch, **frozen history**. Nothing updates it, and nothing mirrors `neondatabase/postgres` any more (D821). |
| `REL_<N>_<m>_neon`, other Neon branches | Neon's leftovers, kept as they are. |
| `loams/meta` | Where the governance files (`SECURITY.md`, `CODEOWNERS`) were first reviewed (NF1 Task 5). |

Each `loams/REL_<N>_STABLE` starts at the head of `REL_<N>_STABLE_neon`, plus one commit adding
`SECURITY.md` and `CODEOWNERS` (`Loams-Patch: LP-0000`):

| Major | `REL_<N>_STABLE_neon` head | `loams/REL_<N>_STABLE` start |
|---|---|---|
| 16 | `59027122` | its own copy of the governance commit |
| 17 | `56692dfb` | `loams/meta`'s tip `efecf23b` (the NF1 Task 5 merge) |
| 18 | `a616eefe` | its own copy of the governance commit |

The submodules here still pin Neon's revisions (17.5 `1e01fcea`, 16.9 `a42351fc`), which are
ancestors of those heads. NF1 Task 17 moves them onto `loams/REL_<N>_STABLE` with the 17.11 and
16.15 merges. Postgres 18 has no submodule until NF1 Task 24.

## Protection

Rulesets on `ostrium-labs/postgres`, with no bypass actors:

- `loams/*: no force-push, no deletion`: `non_fast_forward` and `deletion` on `refs/heads/loams/**`;
- `REL_*_STABLE_neon: frozen history`: `update`, `non_fast_forward` and `deletion`;
- `loams: pinned tags are immutable`, on the tags.

The branches are created through the REST API (`gh api repos/ostrium-labs/postgres/git/refs`),
because no maintainer needs a local clone of the fork.

## The check

`scripts/loams/check-postgres-branches.py` checks this layout in `loams-hygiene.yml`. For each
major, `loams/REL_<N>_STABLE` must exist, descend from `REL_<N>_STABLE_neon`, carry
`SECURITY.md` and `CODEOWNERS`, and refuse force-pushes and deletion. `REL_<N>_STABLE_neon` must
refuse updates. Every submodule URL must be `../postgres.git`. The tests are
`scripts/loams/tests/test_postgres_branches.py`.

## Taking an upstream minor

Postgres minors come in by merge, never by rebase (D821). `loams-postgres-merge.yml` does the merge in CI, in a blobless clone inside the job:

```
gh workflow run loams-postgres-merge.yml --repo ostrium-labs/loams-postgres -f major=17 -f tag=REL_17_11            # try only
gh workflow run loams-postgres-merge.yml --repo ostrium-labs/loams-postgres -f major=17 -f tag=REL_17_11 -f push=true
```

1. The merge commit is `Merge REL_<N>_<m> into loams/REL_<N>_STABLE`, with the trailer `Loams-Sync: REL_<N>_<m>`.
2. With `push`, it goes to `loams/minor-<N>-REL_<N>_<m>`. `vendor/postgres-v<N>` and `vendor/revisions.json` move to it in a pull request here, and the gate (`loams-gate.yml`) runs on that pull request's branch.
3. Once the gate is green, `promote` fast-forwards `loams/REL_<N>_STABLE` to the merge.

A conflict fails the job and uploads the conflicted files and diff as an artifact. A maintainer then resolves it on `loams/minor-<N>-REL_<N>_<m>` by hand and records each resolution in the merge commit's message. Neon's patched areas are listed in `docs/core_changes.md`.
