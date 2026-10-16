# The test gate

`.github/workflows/loams-gate.yml` (LP-0015, NF1 Task 16; design §51 §6.4) has four tiers.

| Tier | What runs | Where |
|---|---|---|
| G0 | rustfmt; clippy on G1's crates; `cargo deny check bans licenses sources`; actionlint; `loams-hygiene`, `loams-patches`, `loams-dco` | standard runner |
| G1 | `cargo nextest` on `postgres_ffi`, `wal_decoder`, `pageserver_api`, `compute_api`, `compute_tools` and `pageserver`. The pageserver's tests run once with `NEON_PAGESERVER_UNIT_TEST_VIRTUAL_FILE_IOENGINE=std-fs` and once with `tokio-epoll-uring`. Postgres and Neon's extensions are built for every major the code supports first | the build-tools image |
| G2 | Neon's `test_runner` with `neon_local` on [`scripts/loams/gate-subset.txt`](../../scripts/loams/gate-subset.txt), once per Postgres major Loams pins, from one release build | the build-tools image |
| G3 | Loams' integration on a release candidate: `ostrium-labs/loams` `nf1-candidate.yml` runs Loams' Postgres e2e jobs, the WAL decoder's golden tests and an extension smoke on the candidate's images. It sets the status `loams-gate / g3` on the candidate's commit | Loams' CI |

## When it runs

- **Nightly** at 21:07 UTC: G0 to G2 on `main`.
- **On every release.** `loams-release.yml` runs G0 to G2 before it builds. Once the images are built, it runs G3 on the candidate's pin document, and tags nothing unless G3 passes.
- **By hand**, with any set of tiers:

  ```
  gh workflow run loams-gate.yml --repo ostrium-labs/loams-postgres --ref main -f tiers=g0,g1,g2
  # G3 on a pin document, e.g. the one Loams pins today (a dry run of a candidate):
  gh workflow run loams-gate.yml --repo ostrium-labs/loams-postgres --ref main -f tiers=g3 \
    -f candidate-pins="$(curl -fsSL https://raw.githubusercontent.com/ostrium-labs/loams/dev/deploy/pins/loams-postgres-images.toml)"
  ```

The gate does not run on pull requests (owner, 2026-10-16). A pull request into `main` runs the light checks `hygiene`, `patches` and `dco`, and those are its required checks (`gate.py required-checks` verifies the ruleset).

## Rules

- **A failing tier fails the job `gate`.** `gate.py verdict` fails the gate when a job of a requested tier failed, was cancelled, or was skipped.
- **A known flake is skipped only with an issue.** Add `deselect <node id> <issue URL>` to `gate-subset.txt`. Never delete a test.
- **Every name in the subset must exist.** `gate.py subset-check` runs on every pull request, in `loams-hygiene`.
- **Runners.** Every job runs on a standard GitHub-hosted runner, or on `vars.RUNNER_HEAVY` for G1 and G2.
  - At most two heavy jobs run at once: G1 beside G2's build, then the G2 majors two at a time.
  - The organisation's concurrent-job limit is shared with Loams' CI.
- **Advisories** are not part of G0. `loams-advisories.yml` gives each one a tracked issue with a due date.

## What G3 needs

- The organisation secret `LOAMS_BOT_TOKEN`. It must be allowed to dispatch workflows on `ostrium-labs/loams` and to set commit statuses on this repository.
- `nf1-candidate.yml` on Loams' `dev`.
