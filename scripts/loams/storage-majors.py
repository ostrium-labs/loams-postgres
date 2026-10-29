#!/usr/bin/env python3
"""Check the Postgres majors in a storage image (LP-0055, NF2 Task 8).

    storage-majors.py <image ref> "<v18 v17 ...>"

For each major the build was given (the Makefile's POSTGRES_VERSIONS, or the
workflow's `postgres-versions` input), /usr/local/v<N>/bin/postgres --version
must report N.x, and /usr/share/doc/loams-postgres/POSTGRES_VERSIONS must list
exactly those majors. The tests named in the plan:
storage_image_has_majors, and storage_image_has_v18 when v18 is built.
Uses $DOCKER (default docker). Exit 1 on a finding, 2 on usage.
"""

import os
import re
import subprocess
import sys

LIST = "/usr/share/doc/loams-postgres/POSTGRES_VERSIONS"


def run(docker, image, entrypoint, *args):
    return subprocess.run([docker, "run", "--rm", "--entrypoint", entrypoint, image, *args],
                          capture_output=True, text=True, timeout=300)


def main(argv):
    if len(argv) != 3:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    image, versions = argv[1], argv[2].split()
    if not versions or not all(re.fullmatch(r"v[0-9]+", v) for v in versions):
        print(f"storage-majors: versions must be v<N> words, got {argv[2]!r}", file=sys.stderr)
        return 2
    docker = os.environ.get("DOCKER", "docker")
    problems = []
    r = run(docker, image, "cat", LIST)
    listed = r.stdout.split() if r.returncode == 0 else None
    if listed is None:
        problems.append(f"{LIST} is missing: {r.stderr.strip()}")
    elif sorted(listed) != sorted(versions):
        problems.append(f"{LIST} lists {' '.join(listed)}, the build was given {' '.join(versions)}")
    for v in versions:
        n = v[1:]
        r = run(docker, image, f"/usr/local/{v}/bin/postgres", "--version")
        out = r.stdout.strip()
        m = re.fullmatch(r"postgres \(PostgreSQL\) ([0-9]+)(\.[0-9]+|beta[0-9]+|rc[0-9]+)\b.*", out)
        if r.returncode != 0 or not m:
            problems.append(f"{v}: /usr/local/{v}/bin/postgres --version failed: {(r.stderr or out).strip()}")
        elif m.group(1) != n:
            problems.append(f"{v}: /usr/local/{v}/bin/postgres is {out!r}, not {n}.x")
        else:
            print(f"{v}: {out}")
    for p in problems:
        print(f"storage-majors: {p}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
