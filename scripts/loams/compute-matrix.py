#!/usr/bin/env python3
"""The build plan of loams-build-compute.yml (LP-0011, NF1 Task 11).

    compute-matrix.py --pins <loams-postgres-images.toml> [--revisions vendor/revisions.json]
                      [--heavy scripts/loams/compute-heavy-stages.txt] --sha <commit>

Reads the majors from Loams' pin file (supported, maintenance and beta; the
compute images Loams may run) and each major's Postgres minor from
vendor/revisions.json, and prints one JSON object for $GITHUB_OUTPUT:

    majors  [{"pg": "17", "pg_version": "v17", "debian": "bookworm", "minor": "17.5",
              "beta": false, "tags": ["17.5-<sha12>", "edge"]}, ...]
    heavy   [{"pg": "17", "pg_version": "v17", "debian": "bookworm", "stage": "plv8-build"}, ...]

Image tags follow the plan's shared contract: `<pgminor>-<sha12>` and `edge`;
a beta major gets `<pgminor>-beta-<sha12>` and `beta` instead.
Exit 1 when a major has no Postgres tree in vendor/revisions.json, 2 on usage.
"""

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Neon built 14 to 16 on bullseye and 17 on bookworm. Bullseye's LTS ended on
# 2026-08-31 and its security archive is gone from deb.debian.org (the first
# v16 build failed on 404s), so 16 is built on bookworm too (NF1 Task 14
# ruling: glibc 2.36 and ICU 72 instead of 2.31 and 67, so text indexes of a
# v16 database created on Neon's image need a REINDEX). 18 waits for Q727 (Task 28).
DEBIAN = {14: "bullseye", 15: "bullseye"}
DEFAULT_DEBIAN = "bookworm"


def heavy_stages(text):
    return [l.strip() for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]


def plan(pins_text, revisions, stages, sha):
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError(f"--sha must be a full commit sha, got {sha!r}")
    m = tomllib.loads(pins_text)["majors"]
    beta = {int(v) for v in m.get("beta", [])}
    wanted = sorted({int(v) for k in ("supported", "maintenance", "beta") for v in m.get(k, [])})
    if not wanted:
        raise ValueError("the pin file lists no majors")
    majors, heavy = [], []
    for n in wanted:
        tree = revisions.get(f"v{n}")
        if not tree:
            raise LookupError(f"Postgres {n} is in the pin file but not in vendor/revisions.json")
        minor = tree[0]
        tags = ([f"{minor}-beta-{sha[:12]}", "beta"] if n in beta else [f"{minor}-{sha[:12]}", "edge"])
        base = {"pg": str(n), "pg_version": f"v{n}", "debian": DEBIAN.get(n, DEFAULT_DEBIAN)}
        majors.append({**base, "minor": minor, "beta": n in beta, "tags": tags})
        heavy.extend({**base, "stage": s} for s in stages)
    return {"majors": majors, "heavy": heavy}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--pins", required=True)
    p.add_argument("--revisions", default=str(ROOT / "vendor" / "revisions.json"))
    p.add_argument("--heavy", default=str(ROOT / "scripts" / "loams" / "compute-heavy-stages.txt"))
    p.add_argument("--sha", required=True)
    args = p.parse_args(argv)
    try:
        out = plan(Path(args.pins).read_text(), json.loads(Path(args.revisions).read_text()),
                   heavy_stages(Path(args.heavy).read_text()), args.sha)
    except ValueError as e:
        print(f"compute-matrix: {e}", file=sys.stderr)
        return 2
    except LookupError as e:
        print(f"compute-matrix: {e}", file=sys.stderr)
        return 1
    print(f"majors={json.dumps(out['majors'])}")
    print(f"heavy={json.dumps(out['heavy'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
