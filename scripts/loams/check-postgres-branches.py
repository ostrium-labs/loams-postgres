#!/usr/bin/env python3
"""Check the Postgres fork's branch layout (LP-0014, NF1 Task 15; recut in
LP-0016, NF1 Task 17).

    check-postgres-branches.py [--repo ostrium-labs/postgres] [--majors 16,17]
                               [--gitmodules .gitmodules] [--offline]

For each major N (docs/loams/postgres-branches.md):

- branches_exist_and_protected: `loams/pg<N>` exists in the fork, descends
  from the revision main pinned before the recut (BASES), carries SECURITY.md
  and CODEOWNERS, and the rulesets in force on it refuse force-pushes and
  deletion. The retired `loams/REL_<N>_STABLE` (16, 17, 18) are still there
  and undeletable, and `REL_<N>_STABLE_neon` refuses updates (frozen history,
  D821).
- submodule_url_relative: every submodule in `.gitmodules` uses
  `../postgres.git`, so a checkout of `ostrium-labs/loams-postgres` resolves
  to `ostrium-labs/postgres`; the maintained majors track `loams/pg<N>`.

`--offline` runs the `.gitmodules` check only. The GitHub API is read with
GH_TOKEN or GITHUB_TOKEN when set (the endpoints are public). Exit codes: 0
ok, 1 a finding, 2 usage or an API error. Stdlib only.
"""

import argparse
import configparser
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
SUBMODULE_URL = "../postgres.git"
REQUIRED_FILES = ("SECURITY.md", "CODEOWNERS")


class ApiError(Exception):
    pass


def github(path):
    """GET `path` on the GitHub API; None for a 404."""
    req = urllib.request.Request(API + path, headers={"Accept": "application/vnd.github+json",
                                                      "X-GitHub-Api-Version": "2022-11-28"})
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 (https only)
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise ApiError(f"GET {path}: HTTP {e.code}") from None
    except urllib.error.URLError as e:
        raise ApiError(f"GET {path}: {e.reason}") from None


def q(ref):
    return urllib.parse.quote(ref, safe="")


def rule_types(get, repo, branch):
    rules = get(f"/repos/{repo}/rules/branches/{q(branch)}") or []
    return {r.get("type") for r in rules}


# The revisions loams/pg<N> start from: the ones ostrium-labs/loams-postgres
# main pinned in vendor/revisions.json before the recut (NF1 Task 17, owner
# 2026-10-17), whose pgxn/neon matches them.
BASES = {
    16: "a42351fcd41ea01edede1daed65f651e838988fc",
    17: "1e01fcea2a6b38180021aa83e0051d95286d9096",
}
# Retired, never deleted: Task 15's branches from Neon's REL_<N>_STABLE_neon
# heads, which need pgxn/neon changes Neon never published.
RETIRED = (16, 17, 18)


def check_branches(get, repo, majors):
    """Findings for the branches of `majors` in `repo`, through `get(path)`."""
    out = []
    for n in majors:
        ours = f"loams/pg{n}"
        base = BASES.get(n)
        if base is None:
            out.append(f"{ours}: no pinned base revision for Postgres {n}")
            continue
        if get(f"/repos/{repo}/branches/{q(ours)}") is None:
            out.append(f"{ours}: missing in {repo}")
            continue
        cmp = get(f"/repos/{repo}/compare/{base}...{q(ours)}")
        if cmp is None:
            out.append(f"{ours}: cannot compare with {base[:8]}")
        elif cmp.get("behind_by", 0) != 0:
            out.append(f"{ours}: does not descend from {base[:8]} ({cmp.get('behind_by')} commits behind)")
        for name in REQUIRED_FILES:
            if get(f"/repos/{repo}/contents/{q(name)}?ref={q(ours)}") is None:
                out.append(f"{ours}: no {name}")
        missing = {"non_fast_forward", "deletion"} - rule_types(get, repo, ours)
        if missing:
            out.append(f"{ours}: not protected against {', '.join(sorted(missing))}")
    for n in RETIRED:
        old, neon = f"loams/REL_{n}_STABLE", f"REL_{n}_STABLE_neon"
        if get(f"/repos/{repo}/branches/{q(old)}") is None:
            out.append(f"{old}: retired branches are kept, but it is missing")
        elif "deletion" not in rule_types(get, repo, old):
            out.append(f"{old}: retired, but not protected against deletion")
        frozen = {"update", "non_fast_forward", "deletion"} - rule_types(get, repo, neon)
        if frozen:
            out.append(f"{neon}: not frozen ({', '.join(sorted(frozen))} allowed)")
    return out


def check_gitmodules(text):
    """Findings for `.gitmodules` text."""
    cp = configparser.ConfigParser()
    try:
        cp.read_string(text)
    except configparser.Error as e:
        return [f".gitmodules: {e}"]
    out = []
    sections = [s for s in cp.sections() if s.startswith("submodule ")]
    if not sections:
        out.append(".gitmodules: no submodules")
    for s in sections:
        url = cp[s].get("url", "").strip()
        if url != SUBMODULE_URL:
            out.append(f".gitmodules: {s} has url {url!r}, not {SUBMODULE_URL!r}")
        # The majors we maintain track their loams/pg<N> branch.
        major = s.rsplit("postgres-v", 1)[-1].strip('"')
        if major.isdigit() and int(major) in BASES:
            branch = cp[s].get("branch", "").strip()
            if branch != f"loams/pg{major}":
                out.append(f".gitmodules: {s} tracks {branch!r}, not 'loams/pg{major}'")
    return out


def main(argv):
    ap = argparse.ArgumentParser(prog="check-postgres-branches.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default="ostrium-labs/postgres")
    ap.add_argument("--majors", default="16,17")
    ap.add_argument("--gitmodules", default=".gitmodules")
    ap.add_argument("--offline", action="store_true", help="check .gitmodules only")
    a = ap.parse_args(argv)
    try:
        majors = [int(m) for m in a.majors.split(",") if m]
        text = open(a.gitmodules, encoding="utf-8").read()
    except (ValueError, OSError) as e:
        print(f"check-postgres-branches: {e}", file=sys.stderr)
        return 2
    findings = check_gitmodules(text)
    if not a.offline:
        try:
            findings += check_branches(github, a.repo, majors)
        except ApiError as e:
            print(f"check-postgres-branches: {e}", file=sys.stderr)
            return 2
    for f in findings:
        print(f"check-postgres-branches: {f}", file=sys.stderr)
    if findings:
        return 1
    what = ".gitmodules" if a.offline else f".gitmodules and {a.repo} loams/pg{{{a.majors}}}"
    print(f"check-postgres-branches: ok ({what})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
