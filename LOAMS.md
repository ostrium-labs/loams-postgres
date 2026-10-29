# Loams Postgres

Loams Postgres is Ostrium Labs' hard fork of Neon's serverless Postgres
(storage, compute and their tools). It is the Postgres storage plane of
[Loams](https://github.com/ostrium-labs/loams).

## Independence

- **Hard fork.** This repository was forked from `neondatabase/neon`. Neon's
  last public commit, `fa504217` (2026-08-31), is tagged `neon-fork-point`.
  Everything after it is ours. Nothing is merged from `neondatabase/*`. An
  upstream commit, if one ever appears, may be cherry-picked by hand as a patch
  with its own `LP-` id and a `(cherry picked from neondatabase/neon <sha>)`
  line.
- **Not Neon.** Loams Postgres is independent of, and not endorsed by, Neon Inc.
  or Databricks. "Neon" appears here only in the attribution (`LICENSE`,
  `NOTICE`) and in compatibility names that users' data depends on: the `neon`
  extension, `neon.*` GUCs, the `neon_superuser` role, `NEON_*` variables,
  `neon_local`, and the wire protocols and on-disk formats. Those are not
  renamed in place.
- **Licence.** Apache-2.0, as Neon's. Our changes against Neon are listed,
  commit by commit, in `LOAMS_PATCHES.md` (each commit after `neon-fork-point`
  carries a `Loams-Patch: LP-<nnnn>` trailer).

## Branches and tags

| Ref | Rule |
|---|---|
| `main` | The default branch and trunk. Pull requests only, one code-owner approval; no force-push, no deletion. Releases are cut from it |
| `neon-fork-point` (tag) | `fa504217`, Neon's last public commit; the base of the patch and DCO checks |
| `loams/<topic>` | Work branches. No force-push, no deletion: merge, never rebase |
| `loams/decoder-trim` | Historical (the WAL decoder trim, `1218fb7a`, now on `main`); kept |
| `loams-<YYYYMMDD>-<n>` (tags) | Every revision Loams pins outside a release |
| `lp-YYYY.MM.N` (tags) | Releases |

Tags `neon-fork-point`, `loams-*` and `lp-*` cannot be moved or deleted.
Neon's other branches and tags are kept as history and are not maintained.

## Pull requests

This repository is still in `neondatabase/neon`'s fork network until GitHub
detaches it, so GitHub offers `neondatabase/neon` as the default base of a new
pull request. **Every pull request must target `ostrium-labs/loams-postgres`,
branch `main`:**

```
gh pr create --repo ostrium-labs/loams-postgres --base main
```

Commits are signed off (`git commit -s`, DCO; `scripts/loams/check-dco.sh`)
and carry a `Loams-Patch` trailer. Code owners are in `CODEOWNERS`; report
vulnerabilities privately as `SECURITY.md` says, never in a public issue.
Daily advisory checks (`loams-advisories.yml`) and nightly fuzzing
(`loams-fuzz.yml`, targets in `fuzz/`) file findings in a private tracker
with a severity and a due date from `SECURITY.md`'s response targets
(`scripts/loams/sla.py`).

## Releases and images

| What | Where |
|---|---|
| Releases | Tags `lp-YYYY.MM.N` on `main` |
| Storage image | `ghcr.io/ostrium-labs/loams-postgres-storage` |
| Compute images | `ghcr.io/ostrium-labs/loams-postgres-compute-v<N>` |
| Build tools | `ghcr.io/ostrium-labs/loams-postgres-build-tools` |
| Postgres with Neon's patches | `ostrium-labs/postgres`, branches `loams/REL_<N>_STABLE` |

Loams pins each image by digest in
[`deploy/pins/loams-postgres-images.toml`](https://github.com/ostrium-labs/loams/blob/dev/deploy/pins/loams-postgres-images.toml).
Until our first release, Loams runs Neon's last public images (build
`77e22e4b`).

## The other forks

| Fork | Branch we keep | State |
|---|---|---|
| `ostrium-labs/postgres` | `loams/REL_<N>_STABLE`; `REL_<N>_STABLE_neon` frozen | Maintained |
| `ostrium-labs/rust-postgres` | `loams/neon` | Frozen unless an advisory needs a fix |
| `ostrium-labs/azure-sdk-for-rust` | `loams/neon` | Frozen |
| `ostrium-labs/tokio-epoll-uring` | `loams/main` | Maintained (licence texts) |
| `ostrium-labs/pg_session_jwt` | `loams/main` | Maintained |
| `ostrium-labs/framed-websockets` | `loams/main` | Archived |
| `ostrium-labs/autoscaling` | `loams/main` | Archived |
