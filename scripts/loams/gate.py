#!/usr/bin/env python3
"""The test gate's bookkeeping (LP-0015, NF1 Task 16; design §51 §6.4).

    gate.py subset-check [--subset scripts/loams/gate-subset.txt] [--root .]
    gate.py subset-args  [--subset scripts/loams/gate-subset.txt] [--root .]
    gate.py tiers   --tiers g0,g1,g2
    gate.py legs    --pins <loams-postgres-images.toml> [--revisions vendor/revisions.json] [--own-majors 18]
    gate.py verdict --tiers g0,g1,g2 --needs '<the needs context as JSON>' [--may-skip '["g2-upgrade"]']
    gate.py required-checks [--repo ostrium-labs/loams-postgres] [--branch main]
    gate.py exec-check [--root .]

subset-check: every test in G2's subset exists. A line names a test function,
`test_runner/regress/<file>.py::<function>`; the file must define it at module
level (read with `ast`, nothing is imported). A `deselect <node id> <issue URL>`
line skips one known flake: its node id must start with a listed test, and the
URL must be a GitHub issue. Duplicates are refused.

subset-args: the pytest arguments for the subset, one per line (the tests, then
`--deselect <node id>` pairs), after the same checks.

tiers: the requested tiers, validated (g0, g1, g2, g3), as JSON booleans for
the workflow's `if:`s, e.g. {"g0": true, "g1": false, ...}.

legs (NF2 Task 7, design §62 §8, D1118): G2's legs and its `upgrade` job,
printed as `legs=`, `upgrade=`, `upgrade-skipped=` and `may-skip=` lines of
JSON for $GITHUB_OUTPUT. The majors are Loams' pin file's (supported,
maintenance and beta; the same file the release and loams-build-compute.yml
read), each of which must be built here (in vendor/revisions.json), plus any
major built here that is newer than every pinned one (`unpinned`: a major on
its way to its first beta, e.g. 18 before Task 14). A beta or unpinned leg is
advisory (its job may fail without failing the gate: a broken beta never
blocks another major's release) unless --own-majors names it: a release of a
major's own images needs its legs green. `upgrade` is Path 1 from each
supported major N to N+1, advisory or not as N+1's leg; when N+1 is not built
here the pair is skipped with a reason, never run as a pass. `may-skip` names
the jobs the plan leaves with nothing to run (g2-upgrade with no pair).

verdict: the gate's final job. `needs` maps each tier's jobs to their results;
a job belongs to the tier its name starts with (`g2-build` is G2). The gate
passes only when every job of every requested tier succeeded: a failure, a
cancellation, or a requested tier whose job was skipped fails it
(gate_fails_on_red_tier), except a job the plan listed in --may-skip (one
with nothing to run). Jobs of tiers not requested may be skipped.

required-checks (required_checks_configured): the rules in force on `main`
require the status checks of the pull-request tier, `hygiene`, `patches` and
`dco` (the jobs of loams-hygiene.yml, loams-patches.yml and loams-dco.yml).
G0 to G3 are not among them: they do not run on pull requests (owner,
2026-10-16), and gate releases instead. It reads the public rules endpoint,
with GH_TOKEN or GITHUB_TOKEN when set.

exec-check (workflow_scripts_executable): every repository script a workflow's
`run:` executes by path (a command line starting with `scripts/` or
`./scripts/`) exists and has its executable bit. Without it the step fails
with exit code 126; G3 did, in the lp-2026.11.0 release, after a later commit
dropped gate-g3.sh's mode.

Exit codes: 0 ok, 1 a finding (or a red gate), 2 usage. Stdlib only.
"""

import argparse
import ast
import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TIERS = ("g0", "g1", "g2", "g3")
REQUIRED_CHECKS = ("hygiene", "patches", "dco")
API = "https://api.github.com"
TEST_RE = re.compile(r"^(test_runner/regress/[A-Za-z0-9_]+\.py)::(test_[A-Za-z0-9_]+)$")
RUN_RE = re.compile(r"^(\s*)(?:-\s+)?run:\s*(.*)$")
SCRIPT_RE = re.compile(r"^(?:\./)?(scripts/[A-Za-z0-9_./-]+)")
ISSUE_RE = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/[0-9]+$")


class Finding(Exception):
    pass


def defined_tests(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def parse_subset(text, root):
    """(tests, deselects) or Finding listing every problem."""
    tests, deselects, problems = [], [], []
    cache = {}
    for no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        where = f"line {no}"
        if line.startswith("deselect "):
            parts = line.split()
            if len(parts) != 3:
                problems.append(f"{where}: deselect needs a node id and an issue URL")
                continue
            _, node, issue = parts
            if not ISSUE_RE.match(issue):
                problems.append(f"{where}: {issue} is not a GitHub issue URL")
            deselects.append((no, node))
            continue
        m = TEST_RE.match(line)
        if not m:
            problems.append(f"{where}: {line!r} is not test_runner/regress/<file>.py::<test function>")
            continue
        if line in tests:
            problems.append(f"{where}: {line} is listed twice")
            continue
        rel, func = m.groups()
        path = root / rel
        if rel not in cache:
            cache[rel] = defined_tests(path) if path.is_file() else None
        if cache[rel] is None:
            problems.append(f"{where}: {rel} does not exist")
        elif func not in cache[rel]:
            problems.append(f"{where}: {rel} defines no {func}")
        tests.append(line)
    for no, node in deselects:
        if not any(node == t or node.startswith(t + "[") for t in tests):
            problems.append(f"line {no}: deselect {node} is not a parameter of a listed test")
    if not tests:
        problems.append("the subset lists no test")
    if problems:
        raise Finding("\n".join(problems))
    return tests, [n for _, n in deselects]


def pytest_args(tests, deselects):
    out = list(tests)
    for d in deselects:
        out += ["--deselect", d]
    return out


def parse_tiers(spec):
    tiers = [t.strip() for t in spec.split(",") if t.strip()]
    bad = [t for t in tiers if t not in TIERS]
    if bad or not tiers:
        raise ValueError(f"tiers must be a comma-separated subset of {','.join(TIERS)}, not {spec!r}")
    return tiers


LEG_STATUSES = ("supported", "maintenance", "beta")


def legs(pins_text, revisions, own=()):
    """G2's legs and the upgrade job's pairs (NF2 Task 7, D1118); Finding on a bad plan."""
    try:
        m = tomllib.loads(pins_text)["majors"]
    except (tomllib.TOMLDecodeError, KeyError) as e:
        raise Finding(f"Loams' pin file has no [majors]: {e}") from None
    status = {}
    for s in reversed(LEG_STATUSES):  # supported wins over beta if both list it
        for v in m.get(s, []):
            status[int(v)] = s
    if not status:
        raise Finding("Loams' pin file lists no majors")
    problems = [f"Postgres {n} is in Loams' pin file but not in vendor/revisions.json"
                for n in sorted(status) if f"v{n}" not in revisions]
    built = sorted(int(k[1:]) for k in revisions if re.fullmatch(r"v[0-9]+", k))
    for n in built:
        if n > max(status):
            status[n] = "unpinned"
    own = {int(o) for o in own}
    problems += [f"own major {o} has no leg" for o in sorted(own - set(status))]
    if problems:
        raise Finding("\n".join(problems))

    def advisory(n):
        return status[n] in ("beta", "unpinned") and n not in own

    out = [{"major": str(n), "status": status[n], "advisory": advisory(n)} for n in sorted(status)]
    upgrade, skipped = [], []
    for n in sorted(k for k, s in status.items() if s == "supported"):
        if f"v{n + 1}" not in revisions:
            skipped.append({"from": str(n), "to": str(n + 1),
                            "reason": f"Postgres {n + 1} is not built in this commit (no v{n + 1} in vendor/revisions.json)"})
        else:
            upgrade.append({"from": str(n), "to": str(n + 1), "advisory": advisory(n + 1)})
    return {"legs": out, "upgrade": upgrade, "upgrade_skipped": skipped,
            "may_skip": [] if upgrade else ["g2-upgrade"]}


def parse_own(spec):
    own = [o.strip() for o in spec.split(",") if o.strip()]
    bad = [o for o in own if not o.isdigit()]
    if bad:
        raise ValueError(f"--own-majors must be comma-separated major numbers, not {spec!r}")
    return own


def verdict(tiers, needs, may_skip=()):
    """A list of problems; empty means the gate is green."""
    problems = []
    seen = set()
    for job, info in sorted(needs.items()):
        tier = job.split("-", 1)[0]
        result = (info or {}).get("result")
        if tier not in TIERS:
            problems.append(f"{job}: belongs to no tier")
            continue
        if tier not in tiers:
            if result not in ("skipped", "success"):
                problems.append(f"{job}: {result} (tier {tier} was not requested)")
            continue
        seen.add(tier)
        if result == "skipped" and job in may_skip:
            continue
        if result != "success":
            problems.append(f"{job} ({tier}): {result}")
    for t in tiers:
        if t not in seen:
            problems.append(f"{t}: requested, but no job of it ran")
    return problems


def direct_scripts(text):
    """(line number, path) of each repository script a workflow's `run:` executes by path.

    A `run:` value is either inline or a block scalar (`|`, `>`): the lines
    indented deeper than the key. Each of its lines that starts with
    `scripts/` or `./scripts/` runs that file directly, so needs its mode bit.
    """
    found = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = RUN_RE.match(lines[i])
        i += 1
        if not m:
            continue
        indent, value = len(m.group(1)), m.group(2).strip()
        if value and value[0] not in "|>":
            body = [(i, value)]
        else:
            body = []
            while i < len(lines) and (not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip()) > indent):
                body.append((i + 1, lines[i].strip()))
                i += 1
        for no, cmd in body:
            s = SCRIPT_RE.match(cmd)
            if s:
                found.append((no, s.group(1)))
    return found


def exec_problems(root):
    """Each direct script invocation in root's workflows whose file is missing or not executable."""
    problems = []
    for wf in sorted((root / ".github" / "workflows").glob("*.y*ml")):
        for no, rel in direct_scripts(wf.read_text(encoding="utf-8")):
            path = root / rel
            where = f"{wf.relative_to(root)}:{no}"
            if not path.is_file():
                problems.append(f"{where}: {rel} does not exist")
            elif not path.stat().st_mode & 0o111:
                problems.append(f"{where}: {rel} is not executable (git update-index --chmod=+x {rel})")
    return problems


def github(path):
    req = urllib.request.Request(API + path, headers={"Accept": "application/vnd.github+json",
                                                      "X-GitHub-Api-Version": "2022-11-28"})
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 (https only)
            return json.load(resp)
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        raise OSError(f"GET {path}: {e}") from None


def missing_required_checks(rules):
    """The checks of REQUIRED_CHECKS that no required_status_checks rule lists."""
    required = set()
    for rule in rules or []:
        if rule.get("type") == "required_status_checks":
            for c in (rule.get("parameters") or {}).get("required_status_checks", []):
                required.add(c.get("context"))
    return [c for c in REQUIRED_CHECKS if c not in required]


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("subset-check", "subset-args"):
        s = sub.add_parser(name)
        s.add_argument("--subset", default="scripts/loams/gate-subset.txt")
        s.add_argument("--root", default=".")
    s = sub.add_parser("tiers")
    s.add_argument("--tiers", required=True)
    s = sub.add_parser("verdict")
    s.add_argument("--tiers", required=True)
    s.add_argument("--needs", required=True)
    s.add_argument("--may-skip", default="[]", help="JSON list of jobs with nothing to run")
    s = sub.add_parser("legs")
    s.add_argument("--pins", required=True)
    s.add_argument("--revisions", default=str(Path(__file__).resolve().parents[2] / "vendor" / "revisions.json"))
    s.add_argument("--own-majors", default="")
    s = sub.add_parser("exec-check")
    s.add_argument("--root", default=".")
    s = sub.add_parser("required-checks")
    s.add_argument("--repo", default="ostrium-labs/loams-postgres")
    s.add_argument("--branch", default="main")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "required-checks":
            path = f"/repos/{a.repo}/rules/branches/{urllib.parse.quote(a.branch, safe='')}"
            missing = missing_required_checks(github(path))
            if missing:
                print(f"{a.repo} {a.branch}: not required: {', '.join(missing)}", file=sys.stderr)
                return 1
            print(f"required checks on {a.repo} {a.branch}: ok ({', '.join(REQUIRED_CHECKS)})")
            return 0
        if a.cmd == "exec-check":
            problems = exec_problems(Path(a.root))
            if problems:
                print("\n".join(problems), file=sys.stderr)
                return 1
            print("workflow scripts: ok (every script a run: executes by path is executable)")
            return 0
        if a.cmd in ("subset-check", "subset-args"):
            root = Path(a.root)
            tests, deselects = parse_subset(Path(a.subset).read_text(encoding="utf-8"), root)
            if a.cmd == "subset-args":
                print("\n".join(pytest_args(tests, deselects)))
            else:
                print(f"gate subset: ok ({len(tests)} tests, {len(deselects)} deselected)")
            return 0
        if a.cmd == "legs":
            own = parse_own(a.own_majors)
            p = legs(Path(a.pins).read_text(encoding="utf-8"),
                     json.loads(Path(a.revisions).read_text(encoding="utf-8")), own)
            print(f"legs={json.dumps(p['legs'])}")
            print(f"upgrade={json.dumps(p['upgrade'])}")
            print(f"upgrade-skipped={json.dumps(p['upgrade_skipped'])}")
            print(f"may-skip={json.dumps(p['may_skip'])}")
            return 0
        tiers = parse_tiers(a.tiers)
        if a.cmd == "tiers":
            print(json.dumps({t: t in tiers for t in TIERS}, sort_keys=True))
            return 0
        problems = verdict(tiers, json.loads(a.needs), json.loads(a.may_skip))
    except Finding as e:
        print(e, file=sys.stderr)
        return 1
    except (ValueError, OSError) as e:
        print(f"gate.py: {e}", file=sys.stderr)
        return 2
    if problems:
        print("the gate is red:\n" + "\n".join(f"  {p}" for p in problems), file=sys.stderr)
        return 1
    print(f"the gate is green ({','.join(tiers)})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
