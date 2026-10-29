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
| LP-0000 | Fork governance: charter, patch queue and its check; CODEOWNERS, DCO check, SECURITY.md, NOTICE | ci | @dina-kar | 2026-10-11 | loams-only | never |
| LP-0001 | Decoder trim: `pageserver_api` and `postgres_ffi` let API-only consumers leave out the storage clients and pprof | build | @dina-kar | 2026-10-08 | upstreamable | never (Loams' WAL decoder builds on it) |
| LP-0002 | Upstream CI removed: Neon's 43 workflows and the scripts only they used (`.github/scripts/`, `.github/file-filters.yaml`); `scripts/loams/strip-upstream-ci.sh` | ci | @dina-kar | 2026-10-13 | loams-only | never (D820: no upstream sync) |
| LP-0003 | No CDDL: pprof and jemalloc_pprof without `flamegraph` (no `inferno`); `CDDL-1.0` out of `deny.toml`; `format=svg` on the profiling routes answers 400; benches and pagebench write pprof protobuf | licence | @dina-kar | 2026-10-13 | loams-only | never (no CDDL in what we publish) |
| LP-0004 | No private Data API: the `SUBZERO_ACCESS_TOKEN` steps and the `rest_broker` feature out of the `Dockerfile`; `prepare-for-subzero` action deleted; the REST broker documented as unsupported (Q720); the `subzero-core` stub kept | build | @dina-kar | 2026-10-13 | loams-only | never (`subzero` is Neon's private code) |
| LP-0005 | Git dependencies from `ostrium-labs` by rev: `rust-postgres` (four crates and the `[patch.crates-io]` entry), `azure-sdk-for-rust`, `tokio-epoll-uring`, `framed-websockets`; `deny.toml` allows git only from `ostrium-labs` | build | @dina-kar | 2026-10-13 | loams-only | never |
| LP-0006 | No `neondatabase` downloads: `pg_session_jwt` from our fork's tag; `pgrag` dropped (Q719); `lcov` removed from `build-tools`; `ARG REPOSITORY=ghcr.io/ostrium-labs`; `scripts/loams/check-no-private-sources.sh` | build | @dina-kar | 2026-10-13 | loams-only | never |
| LP-0007 | Licence texts for `tokio-epoll-uring`: our fork's `loams/main` adds `LICENSE-MIT`, `LICENSE-APACHE`, `uring-common/LICENSE-tokio-uring` and `LICENSING.md`, and the pin moves there; `docs/loams/LICENSING-tokio-epoll-uring.md` | licence | @dina-kar | 2026-10-13 | loams-only | upstream publishes licence files that match its manifests |
| LP-0008 | Advisories, fuzzing and response targets: daily advisory checks, nightly fuzz targets (`fuzz/`, the proxy's `fuzzing` feature), severity labels and due dates (`scripts/loams/sla.py`) | ci | @dina-kar | 2026-10-12 | loams-only | never |
| LP-0009 | Our build-tools image: `loams-build-tools.yml` builds `ghcr.io/ostrium-labs/loams-postgres-build-tools` (amd64, arm64) and opens the pin PR; the storage `Dockerfile` builds `FROM $BUILD_TOOLS`, pinned by digest (`scripts/loams/pin-build-tools.sh`) | build | @dina-kar | 2026-10-13 | loams-only | never |
| LP-0010 | The storage image workflow: `loams-build-storage.yml` (amd64, arm64; `<sha12>`, `edge`), the smoke stack (`scripts/loams/smoke/`), the image audit (`scripts/loams/audit-image.sh`, vendored from Loams), labels and `/usr/share/doc/loams-postgres/` (`THIRD_PARTY_LICENSES.html` from `cargo about`) | build | @dina-kar | 2026-10-13 | loams-only | never |
| LP-0011 | The compute image workflow: `loams-build-compute.yml` (the pin file's majors × amd64, arm64; heavy stages in their own cached jobs), `cargo auditable` and the licence files in the compute image, the core-extension smoke (`compute/tests/loams-smoke/`) | build | @dina-kar | 2026-10-13 | loams-only | never |
| LP-0012 | Sign, attest and attach sources: the reusable `loams-sign.yml` (cosign keyless, build provenance, SPDX SBOMs per platform, the compute sources artifact from `scripts/loams/compute-sources.py`), called by `loams-build-tools.yml` and the release | ci | @dina-kar | 2026-10-13 | loams-only | never |
| LP-0013 | Releases `lp-YYYY.MM.N`: `loams-release.yml` (gate, builds, image tags, signing, the GitHub Release with notes and the pin document, the pin PR on Loams, the cadence check), `scripts/loams/release-notes.py`, `docs/loams/release.md` | ci | @dina-kar | 2026-10-13 | loams-only | never |
| LP-0014 | The Postgres fork's branch layout: `loams/REL_<N>_STABLE` for 16, 17 and 18 in `ostrium-labs/postgres`, `REL_<N>_STABLE_neon` frozen; `docs/loams/postgres-branches.md`, `scripts/loams/check-postgres-branches.py` in `loams-hygiene.yml` | ci | @dina-kar | 2026-10-16 | loams-only | never |
| LP-0015 | The test gate G0 to G3: `loams-gate.yml` (nightly, on releases, by hand), `scripts/loams/gate.py`, `gate.sh`, `gate-docker.sh`, `gate-g3.sh`, `gate-subset.txt`, `docs/loams/gate.md`; the release runs it; rustfmt on `libs/remote_storage/src/gcs_bucket.rs` (G0) | ci | @dina-kar | 2026-10-16 | loams-only | never |
| LP-0016 | Postgres minors 16.15 and 17.11 on the recut branches `loams/pg16` (from 16.9 `a42351fc`) and `loams/pg17` (from 17.5 `1e01fcea`); `loams/REL_<N>_STABLE` retired, because Neon's branch heads need unpublished `pgxn/neon` changes (owner, 2026-10-17); `loams-postgres-merge.yml` and `postgres-merge.sh` (the merge in CI); 17.11 keeps the fork's heap WAL format without upstream's VM block references (`docs/loams/pg17-vm-clear.md`, `test_loams_vm_clear.py`) | ci, pg | @dina-kar | 2026-10-16 | loams-only | never |
| LP-0035 | Postgres 18: `loams/pg18` from upstream `REL_18_6` with our 17 series ported by cherry-pick (D1109); the port mode of `postgres-merge.sh` and `loams-postgres-merge.yml` (`loams/port-pg18`, the resolutions in `scripts/loams/port/pg18/`), `make check` and `installcheck-world` on the port; `check-postgres-branches.py` covers `loams/pg18`; `vendor/postgres-v18` (18.6, `loams/pg18` `735664df`) and `POSTGRES_CORE_VERSIONS` (Postgres builds for 18, the pgxn extensions and images not yet) | pg18 | @dina-kar | 2026-10-28 | loams-only | never |
| LP-0036 | Postgres 18: no invalidation processing in `heap_xlog_inplace` during WAL redo (`if (!am_wal_redo_postgres)`), because 18's in-place records carry invalidations and unlinking the relcache init file is outside `neon_walredo`'s seccomp filter (NF2 Task 1 F26). Taken from `neondatabase/postgres` `f368841ccf` (`REL_18_STABLE_neon`), whose commit in `loams/pg18` carries `(cherry picked from neondatabase/postgres <sha>)`; here, the mbox in `scripts/loams/port/pg18/` | pg18 | @dina-kar | 2026-10-29 | loams-only | upstream Postgres stops processing invalidations in a WAL-redo-only process |
| LP-0037 | Postgres 18: the fork's heap WAL format without visibility-map block references, reverting 18.6's `f581fa729d` (and `4d7feebfbd`'s test) in `loams/pg18` as 17.11 did (D1112 as amended 2026-10-29, owner: "Yes, revert at 18"; NF2 Task 1 F27); here, the mbox in `scripts/loams/port/pg18/` | pg18 | @dina-kar | 2026-10-29 | loams-only | never (D1112) |
| LP-0038 | Postgres 18: build fixes for call sites 18.6 added to the ported series (`smgropen()`'s relpersistence in `RelationCopyStorageUsingBuffer`, `_bt_get_endpoint()`'s parent argument, `getEventTriggers()` without a count); here, the mbox in `scripts/loams/port/pg18/` | pg18 | @dina-kar | 2026-10-29 | loams-only | never |
| LP-0032 | Least privilege for spec roles: a role gets what the spec asks for; `privileged` opts into Neon's admin attributes and `neon_superuser` | compute | @dina-kar | 2026-10-12 | loams-only | never (Loams' role model, PG2 R11.9) |
| LP-0033 | `postgres_ffi`'s build finds the server headers in `include/server` too: Postgres installs them there when the prefix names "postgres", as in a `loams-postgres` checkout | build | @dina-kar | 2026-10-14 | upstreamable | never |
| LP-0034 | The Postgres 18 format diff: `docs/loams/pg18-format-diff.md` (17.11 → 18.6, every item classified per §51 §8.3) and its check, `scripts/loams/format-diff-check.py` in `loams-hygiene.yml` (NF2 Task 1) | pg18 | @dina-kar | 2026-10-28 | loams-only | never |

## Commits without a trailer

Commits on `main` that predate the trailer and sign-off rules. History is
never rewritten, so they are mapped to their patch here, and
`scripts/loams/check-dco.sh` exempts them from the DCO check.

| Commit | Id | Why |
|---|---|---|
| 1218fb7a6a37e1b4c268bad5c2952c238d81d368 | LP-0001 | Fast-forwarded onto `main` before the patch queue existed (NF1 Task 3) |
