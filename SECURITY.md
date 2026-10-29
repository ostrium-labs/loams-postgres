# Security Policy

Loams Postgres is part of Loams and follows
[Loams' security policy](https://github.com/ostrium-labs/loams/security/policy).
This file says how that policy applies to this repository.

## Reporting a vulnerability

**Please do not report security vulnerabilities in public issues, pull
requests or discussions.**

Report them privately through GitHub's private vulnerability reporting:
open this repository's **Security** tab and choose **Report a vulnerability**
([direct link](https://github.com/ostrium-labs/loams-postgres/security/advisories/new)).
Only you and the maintainers can see the report.

If you cannot use GitHub, email **security@ostriumlabs.org**.

We acknowledge a report within **3 business days**, keep you updated while we
investigate, agree on a disclosure timeline with you, and credit you in the
advisory unless you ask us not to.

## This is a hard fork of Neon

Loams Postgres is a hard fork of Neon at `neon-fork-point` (`fa504217`). Neon
Inc. and Databricks do not maintain this code for us, and we take no fixes
from them, so report vulnerabilities in this repository's code to us, not to
Neon. A vulnerability in PostgreSQL itself (the trees under `vendor/`, which
come from `ostrium-labs/postgres`) can also be reported to the PostgreSQL
project at security@postgresql.org; we take its security releases.

## Response targets

Once a vulnerability is confirmed, whether reported to us or found by our own
checks (daily advisory scans of our dependencies and images, the PostgreSQL
release feed, and nightly fuzzing), we aim to publish fixed images within:

| Finding | Target |
|---|---|
| A PostgreSQL security release | 7 days after the release |
| CVSS 9.0 or higher, in a component we ship | 72 hours |
| CVSS 7.0 to 8.9 | 7 days |
| Others | 30 days (the monthly roll-up) |

These are targets, not guarantees. Each finding is tracked privately with its
severity and due date (`scripts/loams/sla.py`), and escalated when it is late.

## Supported versions

There is no release yet. Security fixes land on `main`. Once releases start
(tags `lp-YYYY.MM.N`), the latest release gets fixes, and the images Loams
pins in `deploy/pins/loams-postgres-images.toml` are rebuilt.
