# Releasing Loams Postgres

Releases are `lp-YYYY.MM.N` tags on `main`, cut by `.github/workflows/loams-release.yml`
(LP-0013). Design: §51 §5.6 (D810) in `ostrium-labs/loams`.

## Cadence

| Train | When | `kind` |
|---|---|---|
| Storage | When `main` has changed and the gate is green, at most weekly | `storage` |
| Compute, minor | Within 7 days of a Postgres release day (the second Thursday of Feb, May, Aug and Nov; next 2026-11-12) and of an out-of-cycle release | `full` (the storage image carries the WAL-redo Postgres) |
| Compute, roll-up | Monthly, first Tuesday: extension and Debian updates | `full` |
| Security | Within the targets in `SECURITY.md` | whatever is affected |

`N` counts from 0 within the month: `lp-2026.10.0`, `lp-2026.10.1`, … A tag is never
moved or reused (the tag ruleset refuses it, and the workflow checks first). The
support window is the two latest releases. Every Tuesday the workflow checks the
cadence: in a month's first week, if the month has no release yet, it opens an issue
on `ostrium-labs/loams`.

## Cutting a release

1. Check that `main` is green and that `LOAMS_PATCHES.md` lists every patch since the
   last release (`scripts/loams/check-patches.py`).
2. Run the workflow on `main`:

   ```
   gh workflow run loams-release.yml --repo ostrium-labs/loams-postgres --ref main \
     -f kind=full -f version=lp-2026.10.0
   ```

3. The workflow:
   - refuses a version that is malformed or already tagged;
   - runs the gate (until NF1 Task 16: `loams-hygiene`, `loams-patches`, `loams-dco`);
   - builds the images for the commit (`loams-build-storage.yml`, `loams-build-compute.yml`);
   - tags them `lp-YYYY.MM.N` (storage) and `<pgminor>-lp-YYYY.MM.N` (compute;
     `<pgminor>-beta-lp-YYYY.MM.N` for a beta major);
   - signs and attests each index and attaches the compute images' sources
     (`loams-sign.yml`);
   - creates the git tag and the GitHub Release, with the notes
     (`scripts/loams/release-notes.py notes`: digests, Postgres minors, extension
     versions, patches added and dropped) and the pin document
     `loams-postgres-images.toml` (`release-notes.py pin-doc`) as an asset;
   - opens the pin pull request on `ostrium-labs/loams` (`scripts/nf1/pins.py set
     --from-release <the asset's URL>`, into `dev`).
4. Review and merge the pin pull request on `ostrium-labs/loams`. Its body repeats the
   pin document; the digests must equal the release's.

A partial release (`storage` or `compute`) keeps Loams' other pins. One that would leave
a major's storage and compute minors apart is refused: release `full`.

## What the release needs

- Actions enabled on this repository, and package write access for `GITHUB_TOKEN`.
- The secret `LOAMS_BOT_TOKEN` (the `loams-postgres-bot` App's token, Q733) for the pin
  pull request and the cadence issue. Without it the workflow prints the `pins.py`
  command to run by hand.

## Verifying a release

In `ostrium-labs/loams`, `scripts/nf1/verify-pins.sh` checks every pinned image Loams
Postgres built: the cosign signature from `loams-release.yml` or `loams-sign.yml` at
`refs/heads/main`, the build provenance and SBOM attestations, the SBOM's licences, and
the compute images' sources artifact.
