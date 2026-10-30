#!/usr/bin/env python3
"""The build plan of loams-build-compute.yml (LP-0011, NF1 Task 11; LP-0055, NF2 Task 8).

    compute-matrix.py --pins <loams-postgres-images.toml> [--revisions vendor/revisions.json]
                      [--makefile Makefile] [--extra-majors "18"]
                      [--dockerfile compute/compute-node.Dockerfile]
                      [--heavy scripts/loams/compute-heavy-stages.txt] --sha <commit>

Reads the majors from Loams' pin file (supported, maintenance and beta; the
compute images Loams may run) and each major's Postgres minor from
vendor/revisions.json, and prints one JSON object per line for $GITHUB_OUTPUT:

    majors  [{"pg": "17", "pg_version": "v17", "debian": "bookworm", "minor": "17.5",
              "beta": false, "tags": ["17.5-<sha12>", "edge"], "extensions": "all"}, ...]
    heavy   [{"pg": "17", "pg_version": "v17", "debian": "bookworm", "stage": "plv8-build"}, ...]
    skipped [{"pg": "18", "reason": "..."}]

A major is built when this commit can build it: its Postgres tree is in
vendor/revisions.json and it is in the Makefile's POSTGRES_VERSIONS (the
storage image's list, which a major joins once pgxn/neon builds against it).
A supported or maintenance major that cannot be built is an error. A beta major
that cannot be built yet is skipped and listed in `skipped`, so Loams may list
18 as beta before the fork vendors it without turning this workflow red
(NF2 Task 8: 18 is opt-in until vendor/postgres-v18 and pgxn/neon at 18 land).

A major whose extensions are not all ported yet has its own layer in the
compute Dockerfile, `extensions-v<N>` (18 while NF2 Task 9 is open): it is
built with EXTENSIONS=v<N>, and only the heavy stages that layer copies from
are built for it.

--extra-majors (a workflow_dispatch input) builds a major the pin file does not
list yet, as beta; it must have a tree, and skips the Makefile check, so a
maintainer can try 18 by hand before it joins POSTGRES_VERSIONS.

Image tags follow the plan's shared contract: `<pgminor>-<sha12>` and `edge`;
a beta major gets `<pgminor>-beta-<sha12>` and `beta` instead.
Exit 1 when a major that must be built cannot be, 2 on usage.
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
# v16 database created on Neon's image need a REINDEX). 18 and later are built
# on Debian 13 trixie (Q727's default, design §62 §4.7); 16 and 17 stay on
# bookworm, so their collations do not change under existing databases.
DEBIAN = {14: "bullseye", 15: "bullseye"}
DEFAULT_DEBIAN = "bookworm"
TRIXIE_FROM = 18


def debian(n):
    return "trixie" if n >= TRIXIE_FROM else DEBIAN.get(n, DEFAULT_DEBIAN)


def heavy_stages(text):
    return [l.strip() for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]


def makefile_majors(text):
    """The majors in the Makefile's `POSTGRES_VERSIONS = v17 v16 ...` line."""
    m = re.search(r"(?m)^POSTGRES_VERSIONS\s*[:?]?=\s*(.*)$", text)
    if not m:
        raise ValueError("the Makefile has no POSTGRES_VERSIONS line")
    out = set()
    for word in m.group(1).split("#", 1)[0].split():
        if not re.fullmatch(r"v[0-9]+", word):
            raise ValueError(f"POSTGRES_VERSIONS has {word!r}, not v<N>")
        out.add(int(word[1:]))
    return out


def parse_majors(spec):
    out = set()
    for word in re.split(r"[\s,]+", spec or ""):
        if not word:
            continue
        if not re.fullmatch(r"v?[0-9]+", word):
            raise ValueError(f"not a Postgres major: {word!r}")
        out.add(int(word.lstrip("v")))
    return out


def extension_subsets(dockerfile):
    """{major: stages} for each `FROM ... AS extensions-v<N>` layer: the stages it copies from."""
    out, current = {}, None
    for line in dockerfile.splitlines():
        m = re.match(r"FROM\s+\S+\s+AS\s+(\S+)\s*$", line.strip(), re.I)
        if m:
            v = re.fullmatch(r"extensions-v([0-9]+)", m.group(1))
            current = int(v.group(1)) if v else None
            if current is not None:
                out[current] = set()
            continue
        m = re.match(r"COPY\s+(?:--\S+\s+)*--from=(\S+)", line.strip())
        if m and current is not None:
            out[current].add(m.group(1))
    return out


def plan(pins_text, revisions, stages, sha, build_majors=None, extra=(), subsets=None):
    """build_majors: the majors the fork builds (the Makefile's list); None means all with a tree.
    subsets: {major: stages} of the majors built with their own `extensions-v<N>` layer."""
    subsets = subsets or {}
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError(f"--sha must be a full commit sha, got {sha!r}")
    m = tomllib.loads(pins_text)["majors"]
    pinned = {k: {int(v) for v in m.get(k, [])} for k in ("supported", "maintenance", "beta")}
    required = pinned["supported"] | pinned["maintenance"]
    extra = set(extra)
    beta = (pinned["beta"] | extra) - required
    wanted = sorted(required | pinned["beta"] | extra)
    if not wanted:
        raise ValueError("the pin file lists no majors")
    majors, heavy, skipped = [], [], []
    for n in wanted:
        tree = revisions.get(f"v{n}")
        reason = None
        if not tree:
            reason = f"Postgres {n} has no tree in vendor/revisions.json"
        elif build_majors is not None and n not in build_majors and n not in extra:
            reason = f"Postgres {n} is not in the Makefile's POSTGRES_VERSIONS"
        if reason:
            if n in required or n in extra:
                raise LookupError(f"{reason}, but the pin file or --extra-majors needs it")
            skipped.append({"pg": str(n), "reason": reason})
            continue
        minor = tree[0]
        tags = ([f"{minor}-beta-{sha[:12]}", "beta"] if n in beta else [f"{minor}-{sha[:12]}", "edge"])
        base = {"pg": str(n), "pg_version": f"v{n}", "debian": debian(n)}
        subset = subsets.get(n)
        majors.append({**base, "minor": minor, "beta": n in beta, "tags": tags,
                       "extensions": f"v{n}" if subset is not None else "all"})
        heavy.extend({**base, "stage": s} for s in stages if subset is None or s in subset)
    if not majors:
        raise LookupError("no major can be built: " + "; ".join(s["reason"] for s in skipped))
    return {"majors": majors, "heavy": heavy, "skipped": skipped}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--pins", required=True)
    p.add_argument("--revisions", default=str(ROOT / "vendor" / "revisions.json"))
    p.add_argument("--makefile", default=str(ROOT / "Makefile"))
    p.add_argument("--extra-majors", default="", help='majors to build besides the pin file\'s, e.g. "18" (as beta)')
    p.add_argument("--heavy", default=str(ROOT / "scripts" / "loams" / "compute-heavy-stages.txt"))
    p.add_argument("--dockerfile", default=str(ROOT / "compute" / "compute-node.Dockerfile"))
    p.add_argument("--sha", required=True)
    args = p.parse_args(argv)
    try:
        out = plan(Path(args.pins).read_text(), json.loads(Path(args.revisions).read_text()),
                   heavy_stages(Path(args.heavy).read_text()), args.sha,
                   makefile_majors(Path(args.makefile).read_text()), parse_majors(args.extra_majors),
                   extension_subsets(Path(args.dockerfile).read_text()))
    except ValueError as e:
        print(f"compute-matrix: {e}", file=sys.stderr)
        return 2
    except LookupError as e:
        print(f"compute-matrix: {e}", file=sys.stderr)
        return 1
    for s in out["skipped"]:
        print(f"::notice title=compute-matrix::skipped beta Postgres {s['pg']}: {s['reason']}", file=sys.stderr)
    print(f"majors={json.dumps(out['majors'])}")
    print(f"heavy={json.dumps(out['heavy'])}")
    print(f"skipped={json.dumps(out['skipped'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
