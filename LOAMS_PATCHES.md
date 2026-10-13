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
| LP-0032 | Least privilege for spec roles: a role gets what the spec asks for; `privileged` opts into Neon's admin attributes and `neon_superuser` | compute | @dina-kar | 2026-10-12 | loams-only | never (Loams' role model, PG2 R11.9) |

## Commits without a trailer

Commits on `main` that predate the trailer and sign-off rules. History is
never rewritten, so they are mapped to their patch here, and
`scripts/loams/check-dco.sh` exempts them from the DCO check.

| Commit | Id | Why |
|---|---|---|
| 1218fb7a6a37e1b4c268bad5c2952c238d81d368 | LP-0001 | Fast-forwarded onto `main` before the patch queue existed (NF1 Task 3) |
