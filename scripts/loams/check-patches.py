#!/usr/bin/env python3
"""Check that every change since the fork point is a listed Loams patch.

    check-patches.py [--base neon-fork-point] [--head HEAD] [--repo .]
                     [--patches LOAMS_PATCHES.md] [--allow-sync-merges] [--parse-only]

It lists the non-merge commits in <base>..<head> and fails (exit 1) when:
  - a commit has no `Loams-Patch: LP-<nnnn>` trailer (and is not listed under
    "Commits without a trailer"), or has more than one;
  - a trailer's id has no row under "## Patches";
  - a row has no commit;
  - a row whose origin is `cherry-pick` has a commit without the line
    `(cherry picked from neondatabase/neon <40 hex>)`, or a commit with that
    line belongs to a row of another origin.

Merge commits are not patches; the commits they bring in are checked.
`--allow-sync-merges` (for ostrium-labs/postgres) exempts the commits a merge
brings in when the merge carries a `Loams-Sync:` trailer: those are upstream
Postgres's own commits.

A malformed LOAMS_PATCHES.md, or a ref git cannot resolve, exits 2.
Standard library only.
"""

import argparse
import datetime
import re
import subprocess
import sys
from pathlib import Path

ID = re.compile(r"LP-\d{4}")
SHA = re.compile(r"[0-9a-f]{40}")
ORIGINS = ("loams-only", "upstreamable", "cherry-pick")
COLUMNS = ["id", "title", "area", "owner", "since", "origin", "drop when"]
EXCEPTION_COLUMNS = ["commit", "id", "why"]
CHERRY_LINE = re.compile(r"^\(cherry picked from neondatabase/neon [0-9a-f]{40}\)$", re.M)


class Malformed(Exception):
    """LOAMS_PATCHES.md or the arguments cannot be used (exit 2)."""


def cells(line):
    """The cells of a Markdown table row; `\\|` is a literal bar."""
    inner = line.strip()
    if not (inner.startswith("|") and inner.endswith("|")):
        return None
    parts = re.split(r"(?<!\\)\|", inner[1:-1])
    return [p.strip().replace("\\|", "|") for p in parts]


def table(lines, section, columns, where):
    """The rows of the first table under `## <section>`, checked for its columns."""
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == f"## {section}")
    except StopIteration:
        return None
    rows = []
    header = None
    for n, line in enumerate(lines[start + 1 :], start + 2):
        if line.startswith("## "):
            break
        row = cells(line)
        if row is None:
            if header is not None and rows and line.strip() == "":
                break
            continue
        if header is None:
            header = [c.lower() for c in row]
            if header != columns:
                raise Malformed(f"{where}:{n}: '## {section}' needs the columns {' | '.join(columns)}")
            continue
        if set("".join(row)) <= set("-: "):
            continue  # the separator row
        if len(row) != len(columns):
            raise Malformed(f"{where}:{n}: a row needs {len(columns)} columns, found {len(row)}")
        rows.append((n, row))
    return rows


def parse_queue(path):
    """({id: row dict}, {sha: id}) from LOAMS_PATCHES.md."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        raise Malformed(f"{path}: {e.strerror}") from e
    where = path.name
    patch_rows = table(lines, "Patches", COLUMNS, where)
    if patch_rows is None:
        raise Malformed(f"{where}: no '## Patches' section")
    patches = {}
    for n, (pid, title, area, owner, since, origin, drop) in patch_rows:
        at = f"{where}:{n}"
        if not ID.fullmatch(pid):
            raise Malformed(f"{at}: id '{pid}' is not LP-<4 digits>")
        if pid in patches:
            raise Malformed(f"{at}: {pid} is listed twice")
        for name, value in (("title", title), ("area", area), ("drop when", drop)):
            if not value:
                raise Malformed(f"{at}: {pid} has an empty {name}")
        if not re.fullmatch(r"@[A-Za-z0-9][A-Za-z0-9-]*(/[A-Za-z0-9._-]+)?", owner):
            raise Malformed(f"{at}: {pid} owner '{owner}' is not a GitHub @handle or @org/team")
        try:
            datetime.date.fromisoformat(since)
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", since):
                raise ValueError
        except ValueError:
            raise Malformed(f"{at}: {pid} since '{since}' is not a YYYY-MM-DD date") from None
        if origin not in ORIGINS:
            raise Malformed(f"{at}: {pid} origin '{origin}' is not one of {', '.join(ORIGINS)}")
        patches[pid] = {"origin": origin, "title": title}
    exceptions = {}
    for n, (sha, pid, why) in table(lines, "Commits without a trailer", EXCEPTION_COLUMNS, where) or []:
        at = f"{where}:{n}"
        if not SHA.fullmatch(sha):
            raise Malformed(f"{at}: commit '{sha}' must be the full 40 hex sha")
        if not ID.fullmatch(pid):
            raise Malformed(f"{at}: id '{pid}' is not LP-<4 digits>")
        if not why:
            raise Malformed(f"{at}: {sha[:12]} needs a reason")
        if sha in exceptions:
            raise Malformed(f"{at}: {sha[:12]} is listed twice")
        exceptions[sha] = pid
    return patches, exceptions


def git(repo, *args):
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise Malformed(f"git {' '.join(args)}: {out.stderr.strip()}")
    return out.stdout


def resolve(repo, ref):
    return git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").strip()


def commits(repo, base, head, allow_sync_merges):
    """[(sha, subject, [Loams-Patch values], body)] for the non-merge commits to check."""
    exclude = [f"^{base}"]
    if allow_sync_merges:
        fmt = "%H%x00%(trailers:key=Loams-Sync,valueonly,separator=%x2C)%x1e"
        for rec in git(repo, "log", "--merges", f"--format={fmt}", head, *exclude).split("\x1e"):
            sha, _, sync = rec.strip().partition("\x00")
            if sha and sync.strip():
                parents = git(repo, "rev-list", "--parents", "-n", "1", sha).split()[2:]
                exclude += [f"^{p}" for p in parents]
    fmt = "%H%x00%s%x00%(trailers:key=Loams-Patch,valueonly,separator=%x1f)%x00%B%x1e"
    out = []
    for rec in git(repo, "log", "--no-merges", f"--format={fmt}", head, *exclude).split("\x1e"):
        rec = rec.lstrip("\n")
        if not rec:
            continue
        sha, subject, trailers, body = rec.split("\x00", 3)
        values = [v.strip() for v in trailers.split("\x1f") if v.strip()]
        out.append((sha, subject, values, body))
    return out


def check(repo, base, head, patches, exceptions, allow_sync_merges, span):
    """(findings, commits checked); `span` names the range in messages."""
    found = []
    seen = set()
    listed = commits(repo, base, head, allow_sync_merges)
    in_range = {sha for sha, *_ in listed}
    for sha, subject, values, body in listed:
        name = f"{sha[:12]} {subject}"
        if not values:
            if sha not in exceptions:
                found.append(f"{name}: no Loams-Patch trailer")
                continue
            pid = exceptions[sha]
        elif len(set(values)) > 1:
            found.append(f"{name}: more than one Loams-Patch trailer ({', '.join(values)})")
            continue
        else:
            pid = values[0]
            if not ID.fullmatch(pid):
                found.append(f"{name}: malformed Loams-Patch trailer '{pid}'")
                continue
        if pid not in patches:
            found.append(f"{name}: {pid} has no row in LOAMS_PATCHES.md")
            continue
        seen.add(pid)
        picked = CHERRY_LINE.search(body) is not None
        if patches[pid]["origin"] == "cherry-pick" and not picked:
            found.append(
                f"{name}: {pid} is a cherry-pick; the commit needs "
                "'(cherry picked from neondatabase/neon <sha>)'"
            )
        elif picked and patches[pid]["origin"] != "cherry-pick":
            found.append(f"{name}: cherry-picked, but {pid}'s origin is {patches[pid]['origin']}")
    for sha, pid in exceptions.items():
        if sha not in in_range:
            found.append(f"{sha[:12]}: listed without a trailer but not in {span}")
    for pid in patches:
        if pid not in seen:
            found.append(f"{pid}: row has no commit in {span}")
    return found, len(listed)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--base", default="neon-fork-point")
    p.add_argument("--head", default="HEAD")
    p.add_argument("--repo", default=".", type=Path)
    p.add_argument("--patches", default="LOAMS_PATCHES.md", help="relative to --repo")
    p.add_argument("--allow-sync-merges", action="store_true")
    p.add_argument("--parse-only", action="store_true", help="check the file's format only")
    args = p.parse_args(argv)
    try:
        patches, exceptions = parse_queue(args.repo / args.patches)
        if args.parse_only:
            print(f"ok: {len(patches)} patches listed")
            return 0
        base, head = resolve(args.repo, args.base), resolve(args.repo, args.head)
        span = f"{args.base}..{args.head}"
        found, n = check(args.repo, base, head, patches, exceptions, args.allow_sync_merges, span)
    except Malformed as e:
        print(f"check-patches: {e}", file=sys.stderr)
        return 2
    for f in found:
        print(f)
    if found:
        print(f"check-patches: {len(found)} finding(s) in {args.base}..{args.head}", file=sys.stderr)
        return 1
    print(f"ok: {n} commits, {len(patches)} patches in {args.base}..{args.head}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
