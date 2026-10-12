#!/usr/bin/env python3
"""Security findings for Loams Postgres: issues, severities and response targets.

    sla.py file --repo <owner/repo> --kind cargo-deny --input <deny.jsonl>
    sla.py file --repo <owner/repo> --kind trivy --input <report.json>...
    sla.py file --repo <owner/repo> --kind ghsa --watch <advisory-watch.txt>
                [--manifest compute/loams-extensions.toml] [--since-days 30]
    sla.py file --repo <owner/repo> --kind findings --input <findings.json>
    sla.py file --repo <owner/repo> --kind fuzz --target <name> --artifact <crash file> --log <fuzzer log>
    sla.py sweep --repo <owner/repo> [--codeowners CODEOWNERS]
    sla.py pinned-images --pins <loams-postgres-images.toml>

`file` turns a scanner's output into findings and opens one issue per new
finding, labelled `loams-sla` and `sev:<severity>`, with its due date. A
finding has a stable key (`rustsec:<id>`, `cve:<id>`, `ghsa:<id>`,
`pg-release:<date>`, `fuzz:<target>:<signature>`), kept in a marker in the
issue body. An issue with the same key, open or closed, means the finding is
known: it is not filed again and a closed issue is not reopened.
`file` options: --now <ISO time>, --dry-run, --max-new <n> (default 50; the
most severe findings are filed first, the rest on the next run).

`sweep` walks the open issues. One with a `sev:` label and no due date (filed
by hand) gets one; one whose severity label changed gets a new due date from
the same start; one past its due date gets the `overdue` label and a comment
that mentions @ostrium-labs/security and the owners of /SECURITY.md in
CODEOWNERS, once.

Response targets (design §51 §3.7, D805; Q724's defaults) run from the
finding's start: the upstream release for a Postgres security minor, the
publication for a GitHub advisory, and the day we first see it otherwise.

  sev:critical   CVSS >= 9.0, or a fuzzer memory error   72 hours
  sev:high       CVSS 7.0-8.9, a vulnerability without
                 a CVSS 3 score, or a fuzzer crash         7 days
  sev:pg-minor   a Postgres security minor                 7 days after the release
  sev:other      everything else                           30 days (the monthly roll-up)

A finding marked private (a fuzzer crash: an undisclosed bug) is only filed
into a private repository; `file` exits 2 otherwise.

GitHub is reached with the token in GH_TOKEN or GITHUB_TOKEN. Exit 0 on
success, 1 on a GitHub or input error, 2 on bad usage or a refusal.
Standard library only.
"""

import argparse
import base64
import dataclasses
import datetime as dt
import hashlib
import json
import math
import os
import re
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UTC = dt.timezone.utc

TARGETS = {
    "critical": dt.timedelta(hours=72),
    "high": dt.timedelta(days=7),
    "pg-minor": dt.timedelta(days=7),
    "other": dt.timedelta(days=30),
}
TARGET_TEXT = {
    "critical": "72 hours",
    "high": "7 days",
    "pg-minor": "7 days after the upstream release",
    "other": "30 days",
}
SEVERITIES = tuple(TARGETS)  # most severe first
SLA_LABEL = "loams-sla"
OVERDUE_LABEL = "overdue"
SECURITY_TEAM = "@ostrium-labs/security"
SIGNAL_REPOS = ("neondatabase/neon",)  # watched, but no fix is expected from it (D820)
LABELS = {
    SLA_LABEL: ("5319e7", "Tracked by scripts/loams/sla.py"),
    OVERDUE_LABEL: ("b60205", "Past its response target"),
    "sev:critical": ("b60205", "Target: 72 hours"),
    "sev:high": ("d93f0b", "Target: 7 days"),
    "sev:pg-minor": ("fbca04", "Target: 7 days after the Postgres release"),
    "sev:other": ("c5def5", "Target: 30 days"),
    "fuzz": ("1d76db", "Found by the nightly fuzzer"),
    "upstream-signal": ("ededed", "Advisory upstream; no fix is expected from it"),
}
MARKER = re.compile(r"<!-- loams-sla (\{.*?\}) -->")
FOOTER = re.compile(r"\n*<!-- loams-sla-start -->.*?<!-- loams-sla \{.*?\} -->", re.S)
INLINE_REPRODUCER_MAX = 16 * 1024
LOG_TAIL_LINES = 80
LOG_TAIL_CHARS = 20_000


class Refused(Exception):
    """A finding must not go where it was asked to go."""


class InputError(Exception):
    """A scanner's output is not what sla.py expects."""


@dataclasses.dataclass(frozen=True)
class Finding:
    key: str
    title: str
    severity: str
    found: dt.datetime
    body: str
    private: bool = False
    labels: tuple = ()

    def to_json(self):
        d = dataclasses.asdict(self)
        d["found"] = iso(self.found)
        d["labels"] = list(self.labels)
        return d


def iso(t):
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(text):
    t = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def human(t):
    return t.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def due_date(severity, found):
    return found + TARGETS[severity]


# --- CVSS ------------------------------------------------------------------

_CVSS3 = {
    "AV": {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2},
    "AC": {"L": 0.77, "H": 0.44},
    "UI": {"N": 0.85, "R": 0.62},
    "C": {"H": 0.56, "L": 0.22, "N": 0.0},
    "I": {"H": 0.56, "L": 0.22, "N": 0.0},
    "A": {"H": 0.56, "L": 0.22, "N": 0.0},
}
_PR = {"U": {"N": 0.85, "L": 0.62, "H": 0.27}, "C": {"N": 0.85, "L": 0.68, "H": 0.5}}


def _roundup(x):
    i = round(x * 100_000)
    return i / 100_000 if i % 10_000 == 0 else (math.floor(i / 10_000) + 1) / 10


def cvss3_base_score(vector):
    """The CVSS 3.0/3.1 base score of a vector, or None (CVSS 4.0, malformed)."""
    parts = vector.split("/")
    if not parts or parts[0] not in ("CVSS:3.0", "CVSS:3.1"):
        return None
    try:
        m = dict(p.split(":", 1) for p in parts[1:])
        scope = m["S"]
        av, ac, ui = (_CVSS3[k][m[k]] for k in ("AV", "AC", "UI"))
        c, i, a = (_CVSS3[k][m[k]] for k in ("C", "I", "A"))
        pr = _PR[scope][m["PR"]]
    except (KeyError, ValueError):
        return None
    iss = 1 - (1 - c) * (1 - i) * (1 - a)
    if scope == "U":
        impact = 6.42 * iss
    else:
        impact = 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15
    exploitability = 8.22 * av * ac * pr * ui
    if impact <= 0:
        return 0.0
    if scope == "U":
        return _roundup(min(impact + exploitability, 10))
    return _roundup(min(1.08 * (impact + exploitability), 10))


def severity_from_score(score):
    if score >= 9.0:
        return "critical"
    if score >= 7.0:
        return "high"
    return "other"


def most_severe(severities):
    return min(severities, key=SEVERITIES.index)


# --- Sources ---------------------------------------------------------------


def findings_from_cargo_deny(lines, now):
    """`cargo deny --format json check advisories` (stderr, one JSON object a line)."""
    advisories, finished = {}, False
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        d = json.loads(line)
        fields = d.get("fields") or {}
        adv = fields.get("advisory")
        finished = finished or d.get("type") == "summary"
        if d.get("type") != "diagnostic" or not adv:
            continue
        entry = advisories.setdefault(adv["id"], {"adv": adv, "code": fields.get("code"), "versions": set()})
        for graph in fields.get("graphs") or []:
            entry["versions"].add(graph["Krate"]["version"])
    if not finished:
        # cargo deny exits 1 both with findings and when it fails; only a run
        # that reached its summary has checked everything.
        raise InputError("cargo deny's output has no summary line: the check did not finish")
    out = []
    for aid, entry in sorted(advisories.items()):
        adv = entry["adv"]
        score = cvss3_base_score(adv["cvss"]) if adv.get("cvss") else None
        if score is not None:
            severity = severity_from_score(score)
        elif entry["code"] == "vulnerability":
            severity = "high"  # no CVSS 3 score: assume the worse case until triaged
        else:
            severity = "other"  # unmaintained, unsound, notice
        versions = ", ".join(sorted(entry["versions"]))
        description = (adv.get("description") or "").strip().split("\n\n")[0][:500]
        body = "\n".join(
            [
                f"`cargo deny check advisories` on `Cargo.lock` reports **{aid}** ({entry['code']}).",
                "",
                f"- Crate: `{adv['package']}` {versions}",
                f"- Title: {adv['title']}",
                f"- CVSS: {adv.get('cvss') or 'none'}" + (f" (base score {score})" if score is not None else ""),
                f"- Aliases: {', '.join(adv.get('aliases') or []) or 'none'}",
                f"- Advisory: https://rustsec.org/advisories/{aid}.html",
                "",
                description,
            ]
        )
        out.append(
            Finding(
                key=f"rustsec:{aid}",
                title=f"{aid}: {adv['package']} {versions}: {adv['title']}",
                severity=severity,
                found=now,
                body=body,
            )
        )
    return out


def _trivy_severity(vuln):
    scores = [
        v["V3Score"]
        for v in (vuln.get("CVSS") or {}).values()
        if isinstance(v, dict) and isinstance(v.get("V3Score"), (int, float))
    ]
    if scores:
        return severity_from_score(max(scores))
    return {"CRITICAL": "critical", "HIGH": "high"}.get(vuln.get("Severity"), "other")


def findings_from_trivy(reports, now):
    """Trivy JSON reports (`trivy image --format json`), one CVE an issue."""
    vulns = {}
    for report in reports:
        image = report.get("ArtifactName", "?")
        for result in report.get("Results") or []:
            for v in result.get("Vulnerabilities") or []:
                entry = vulns.setdefault(v["VulnerabilityID"], {"title": v.get("Title") or "", "rows": [], "sev": []})
                entry["sev"].append(_trivy_severity(v))
                entry["url"] = v.get("PrimaryURL") or entry.get("url")
                entry["rows"].append(
                    f"| `{image}` | `{v.get('PkgName')}` | {v.get('InstalledVersion', '')} | {v.get('FixedVersion') or 'none yet'} |"
                )
    out = []
    for vid, entry in sorted(vulns.items()):
        packages = sorted({row.split("|")[2].strip(" `") for row in entry["rows"]})
        body = "\n".join(
            [
                f"Trivy finds **{vid}** in images Loams pins (`deploy/pins/loams-postgres-images.toml`).",
                "",
                entry["title"],
                "",
                "| Image | Package | Installed | Fixed in |",
                "|---|---|---|---|",
                *entry["rows"],
                "",
                f"Details: {entry.get('url') or 'https://nvd.nist.gov/vuln/detail/' + vid}",
            ]
        )
        out.append(
            Finding(
                key=f"cve:{vid}",
                title=f"{vid}: {', '.join(packages)} in pinned images",
                severity=most_severe(entry["sev"]),
                found=now,
                body=body,
            )
        )
    return out


def _ghsa_score(adv):
    v3 = ((adv.get("cvss_severities") or {}).get("cvss_v3") or {}).get("score")
    if isinstance(v3, (int, float)):
        return v3
    cvss = adv.get("cvss") or {}
    if isinstance(cvss.get("score"), (int, float)) and str(cvss.get("vector_string", "")).startswith("CVSS:3"):
        return cvss["score"]
    return None


def findings_from_ghsa(advisories_by_repo, now, since_days=30, signal=SIGNAL_REPOS):
    """Published GitHub repository advisories of the watched repositories."""
    since = now - dt.timedelta(days=since_days)
    out = []
    for repo, advisories in sorted(advisories_by_repo.items()):
        for adv in advisories:
            if adv.get("withdrawn_at") or not adv.get("published_at"):
                continue
            published = parse_time(adv["published_at"])
            if published < since:
                continue
            score = _ghsa_score(adv)
            if score is not None:
                severity = severity_from_score(score)
            else:
                severity = {"critical": "critical", "high": "high"}.get(adv.get("severity"), "other")
            is_signal = repo in signal
            body = "\n".join(
                [
                    f"`{repo}` published **{adv['ghsa_id']}**"
                    + (f" ({adv['cve_id']})" if adv.get("cve_id") else "")
                    + f" on {human(published)}.",
                    "",
                    f"- Summary: {adv.get('summary', '')}",
                    f"- Severity: {adv.get('severity')}" + (f", CVSS {score}" if score is not None else ""),
                    f"- Advisory: {adv.get('html_url')}",
                    "",
                    (
                        "A signal only: no fix is expected from this upstream (D820). Check whether the "
                        "same code is in Loams Postgres and fix it here."
                        if is_signal
                        else "Check whether the version we ship is affected, and update or patch it."
                    ),
                ]
            )
            out.append(
                Finding(
                    key=f"ghsa:{adv['ghsa_id']}",
                    title=f"{adv['ghsa_id']}: {repo}: {adv.get('summary', '')}",
                    severity=severity,
                    found=published,
                    body=body,
                    labels=("upstream-signal",) if is_signal else (),
                )
            )
    return out


def watch_list(watch_file, manifest=None):
    """The repositories whose advisories we watch: the file, plus each extension's GitHub source."""
    repos = []
    for line in Path(watch_file).read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            repos.append(line)
    if manifest and Path(manifest).exists():
        data = tomllib.loads(Path(manifest).read_text())
        for ext in data.get("extension", []):
            m = re.match(r"https://github\.com/([\w.-]+/[\w.-]+?)(?:\.git)?/", ext.get("source", ""))
            if m:
                repos.append(m.group(1))
    return list(dict.fromkeys(repos))


def _source_path(path):
    """A source path without the machine's prefixes, so one bug keys the same everywhere."""
    path = re.sub(r"^.*/registry/src/[^/]+/", "", path)  # crates.io: <crate>-<version>/...
    path = re.sub(r"^.*/git/checkouts/[^/]+/[^/]+/", "", path)  # git dependencies
    path = re.sub(r"^/rustc/[0-9a-f]+/", "rustc/", path)  # the standard library
    return path.removeprefix("./")


def _ours(path):
    return not path.startswith("/")  # cargo names our own sources relative to the workspace


def _crash_signature(log, data):
    m = re.search(r"panicked at ([^\s:]+):(\d+):\d+", log)
    if m:
        signature = f"panic@{_source_path(m.group(1))}:{m.group(2)}"
        if not _ours(m.group(1)):
            # In std or a dependency: name the first frame of our own code, if
            # the fuzzer ran with RUST_BACKTRACE=1.
            for path, line in re.findall(r"^\s+at ([^\s:]+):(\d+):\d+", log, re.M):
                if _ours(path):
                    return f"{signature}<-{_source_path(path)}:{line}"
        return signature
    m = re.search(r"SUMMARY: (?:Address|Memory|Thread|UndefinedBehavior)Sanitizer: (\S+)(?: (\S+?):(\d+)(?::\d+)?)?", log)
    if m:
        where = f"@{m.group(2)}:{m.group(3)}" if m.group(2) else ""
        return f"asan-{m.group(1)}{where}"
    for needle, sig in (
        ("ERROR: libFuzzer: timeout", "timeout"),
        ("ERROR: libFuzzer: out-of-memory", "oom"),
        ("LeakSanitizer", "leak"),
    ):
        if needle in log:
            return sig
    return "input-" + hashlib.sha1(data).hexdigest()


def finding_from_fuzz(target, artifact_name, data, log, now):
    """A libFuzzer crash: private, keyed on where it crashed rather than on the input."""
    signature = _crash_signature(log, data)
    # The sanitizer's own report, not libFuzzer's hint that names it.
    memory_error = re.search(r"ERROR: (?:Address|Memory)Sanitizer: (?!DEADLYSIGNAL)", log) is not None
    severity = "critical" if memory_error else "high"
    tail = "\n".join(log.splitlines()[-LOG_TAIL_LINES:])[-LOG_TAIL_CHARS:]
    if len(data) <= INLINE_REPRODUCER_MAX:
        encoded = base64.b64encode(data).decode()
        reproducer = [
            f"Reproducer (`{artifact_name}`, {len(data)} bytes, base64):",
            "",
            "~~~",
            encoded,
            "~~~",
            "",
            "To reproduce, from the repository root with the nightly toolchain the fuzz workflow uses:",
            "",
            "~~~sh",
            f"base64 -d > {artifact_name} <<'EOF'",
            encoded,
            "EOF",
            f"cargo fuzz run {target} {artifact_name}",
            "~~~",
        ]
    else:
        reproducer = [
            f"The reproducer `{artifact_name}` is {len(data)} bytes, too big to inline "
            f"(sha256 `{hashlib.sha256(data).hexdigest()}`). Re-run `cargo fuzz run {target}` "
            "from the cached corpus, or attach it by hand.",
        ]
    body = "\n".join(
        [
            f"The nightly fuzzer (`loams-fuzz.yml`) crashed in target **`{target}`**: `{signature}`.",
            "",
            "This is an undisclosed bug in code we own (D820): keep it in this private tracker, "
            "fix it on a private branch, and publish an advisory when the fix ships.",
            "",
            *reproducer,
            "",
            "Fuzzer output (tail):",
            "",
            "~~~",
            tail,
            "~~~",
        ]
    )
    return Finding(
        key=f"fuzz:{target}:{signature}",
        title=f"Fuzz crash in {target}: {signature}",
        severity=severity,
        found=now,
        body=body,
        private=True,
        labels=("fuzz",),
    )


def findings_from_json(data):
    return [
        Finding(
            key=d["key"],
            title=d["title"],
            severity=d["severity"],
            found=parse_time(d["found"]),
            body=d["body"],
            private=bool(d.get("private", False)),
            labels=tuple(d.get("labels", ())),
        )
        for d in data
    ]


def pinned_images(pins_text):
    """Every image in Loams' pin file, as repository@digest."""
    pins = tomllib.loads(pins_text)
    return [f"{img['repository']}@{img['digest']}" for img in pins.get("images", {}).values()]


def security_mentions(codeowners_text):
    """@ostrium-labs/security plus the owners of /SECURITY.md (who stand in until the team exists)."""
    mentions = [SECURITY_TEAM]
    for line in codeowners_text.splitlines():
        parts = line.split("#", 1)[0].split()
        if parts and parts[0] == "/SECURITY.md":
            mentions.extend(o for o in parts[1:] if o.startswith("@"))
    return list(dict.fromkeys(mentions))


# --- Issues ----------------------------------------------------------------


def marker(body):
    """The footer's marker: the last one, which sla.py writes after any other text."""
    found = MARKER.findall(body or "")
    return json.loads(found[-1]) if found else None


def _footer(key, severity, found):
    due = due_date(severity, found)
    data = json.dumps({"key": key, "severity": severity, "found": iso(found), "due": iso(due)}, sort_keys=True)
    data = data.replace("--", "-\\u002d")  # never end the HTML comment early
    return "\n".join(
        [
            "",
            "<!-- loams-sla-start -->",
            "---",
            f"Severity: `sev:{severity}` (target: {TARGET_TEXT[severity]}). "
            f"Found: {human(found)}. Due: {human(due)}.",
            "Targets: design §51 §3.7 (Q724). Change the `sev:` label to re-target; "
            "`scripts/loams/sla.py sweep` moves the due date.",
            f"<!-- loams-sla {data} -->",
        ]
    )


def with_footer(body, key, severity, found):
    base = FOOTER.sub("", body or "").rstrip()
    # Text from upstream (an advisory's summary, a fuzzer's output) must not
    # carry a marker of its own: escape every HTML comment in it.
    base = base.replace("<!--", "&lt;!--")
    return base + "\n" + _footer(key, severity, found)


def label_names(issue):
    return [lab["name"] if isinstance(lab, dict) else lab for lab in issue.get("labels", [])]


def issue_severity(issue):
    sevs = [n[4:] for n in label_names(issue) if n.startswith("sev:") and n[4:] in TARGETS]
    return most_severe(sevs) if sevs else None


def _real_issues(gh, repo, state):
    return [i for i in gh.list_issues(repo, state=state) if "pull_request" not in i]


def ensure_labels(gh, repo, names):
    for name in names:
        color, description = LABELS.get(name, ("ededed", ""))
        gh.ensure_label(repo, name, color, description)


def file_findings(gh, repo, findings, now, dry_run=False, max_new=50):
    """Open an issue for each finding not yet known. Returns (action, key, issue number) tuples."""
    if any(f.private for f in findings) and not gh.repo_is_private(repo):
        raise Refused(f"{repo} is not private; a private finding (a fuzzer crash) is never filed there")
    known = {}
    for issue in _real_issues(gh, repo, "all"):
        mark = marker(issue.get("body"))
        if mark:
            known.setdefault(mark["key"], issue["number"])
    ordered = sorted(findings, key=lambda f: (SEVERITIES.index(f.severity), f.key))
    actions, handled, opened, labelled = [], set(), 0, False
    for f in ordered:
        if f.key in handled:
            continue  # the same finding twice in one run
        handled.add(f.key)
        if f.key in known:
            actions.append(("exists", f.key, known[f.key]))
        elif opened >= max_new:
            actions.append(("deferred", f.key, None))
        elif dry_run:
            actions.append(("would-open", f.key, None))
            opened += 1
        else:
            if not labelled:
                ensure_labels(gh, repo, [SLA_LABEL, OVERDUE_LABEL, *(f"sev:{s}" for s in SEVERITIES)])
                labelled = True
            ensure_labels(gh, repo, f.labels)
            labels = [SLA_LABEL, f"sev:{f.severity}", *f.labels]
            issue = gh.create_issue(repo, f.title[:250], with_footer(f.body, f.key, f.severity, f.found), labels)
            actions.append(("opened", f.key, issue["number"]))
            opened += 1
    return actions


def sweep(gh, repo, now, mentions, dry_run=False):
    """Date the hand-filed issues, re-date relabelled ones, escalate overdue ones (once)."""
    actions = []
    labels_ready = False
    for issue in _real_issues(gh, repo, "open"):
        number, names = issue["number"], label_names(issue)
        severity = issue_severity(issue)
        mark = marker(issue.get("body"))
        if severity is None:
            if mark is None:
                continue  # not a security finding
            severity = mark["severity"]
        if mark is None or mark["severity"] != severity:
            found = parse_time(mark["found"]) if mark else parse_time(issue["created_at"])
            key = mark["key"] if mark else f"issue:{repo}#{number}"
            body = with_footer(issue.get("body") or "", key, severity, found)
            actions.append(("dated" if mark is None else "redated", number))
            if not dry_run:
                gh.update_issue(repo, number, body)
                if SLA_LABEL not in names:
                    if not labels_ready:
                        ensure_labels(gh, repo, [SLA_LABEL, OVERDUE_LABEL])
                        labels_ready = True
                    gh.add_labels(repo, number, [SLA_LABEL])
            mark = marker(body)
        due = parse_time(mark["due"])
        if now > due and OVERDUE_LABEL not in names:
            actions.append(("escalated", number))
            if not dry_run:
                if not labels_ready:
                    ensure_labels(gh, repo, [SLA_LABEL, OVERDUE_LABEL])
                    labels_ready = True
                gh.add_labels(repo, number, [OVERDUE_LABEL])
                gh.comment(
                    repo,
                    number,
                    f"Overdue: the `sev:{severity}` target ({TARGET_TEXT[severity]}) passed on "
                    f"{human(due)}. Ship the fix, or re-triage the severity with a reason. "
                    f"cc {' '.join(mentions)}",
                )
    return actions


# --- GitHub ----------------------------------------------------------------


class GitHub:
    """The few REST calls sla.py makes (https://api.github.com, token from the environment)."""

    API = "https://api.github.com"

    def __init__(self, token):
        self.token = token

    def _request(self, method, url, body=None):
        if not url.startswith(self.API + "/"):
            url = self.API + url
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        req.add_header("User-Agent", "loams-postgres-sla")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return (json.loads(raw) if raw else None), resp.headers.get("Link", "")

    def _paginate(self, path):
        items, url = [], path
        while url:
            page, link = self._request("GET", url)
            items.extend(page)
            m = re.search(r'<([^>]+)>;\s*rel="next"', link)
            url = m.group(1) if m else None
        return items

    def repo_is_private(self, repo):
        return bool(self._request("GET", f"/repos/{repo}")[0]["private"])

    def ensure_label(self, repo, name, color, description):
        try:
            self._request("GET", f"/repos/{repo}/labels/{urllib.parse.quote(name, safe='')}")
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            self._request("POST", f"/repos/{repo}/labels", {"name": name, "color": color, "description": description})

    def list_issues(self, repo, state="all"):
        return self._paginate(f"/repos/{repo}/issues?state={state}&per_page=100")

    def create_issue(self, repo, title, body, labels):
        return self._request("POST", f"/repos/{repo}/issues", {"title": title, "body": body, "labels": labels})[0]

    def update_issue(self, repo, number, body):
        self._request("PATCH", f"/repos/{repo}/issues/{number}", {"body": body})

    def add_labels(self, repo, number, labels):
        self._request("POST", f"/repos/{repo}/issues/{number}/labels", {"labels": labels})

    def comment(self, repo, number, body):
        self._request("POST", f"/repos/{repo}/issues/{number}/comments", {"body": body})

    def list_repo_advisories(self, repo):
        return self._paginate(f"/repos/{repo}/security-advisories?state=published&per_page=100")


# --- CLI -------------------------------------------------------------------


def _github():
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("sla: set GH_TOKEN or GITHUB_TOKEN")
    return GitHub(token)


def _collect(args, gh, now):
    if args.kind == "cargo-deny":
        with open(_one(args.input)) as fh:
            return findings_from_cargo_deny(fh, now), []
    if args.kind == "trivy":
        return findings_from_trivy([json.loads(Path(p).read_text()) for p in args.input], now), []
    if args.kind == "findings":
        return findings_from_json(json.loads(Path(_one(args.input)).read_text())), []
    if args.kind == "fuzz":
        if not (args.target and args.artifact and args.log):
            raise SystemExit(2)
        artifact = Path(args.artifact)
        log = Path(args.log).read_text(errors="replace")
        return [finding_from_fuzz(args.target, artifact.name, artifact.read_bytes(), log, now)], []
    # ghsa
    if not args.watch:
        raise SystemExit(2)
    advisories, errors = {}, []
    for repo in watch_list(args.watch, args.manifest):
        try:
            advisories[repo] = gh.list_repo_advisories(repo)
        except urllib.error.HTTPError as e:
            errors.append(f"{repo}: HTTP {e.code}")
    return findings_from_ghsa(advisories, now, args.since_days), errors


def _one(inputs):
    if not inputs or len(inputs) != 1:
        raise SystemExit(2)
    return inputs[0]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("file")
    f.add_argument("--repo", required=True)
    f.add_argument("--kind", required=True, choices=["cargo-deny", "trivy", "ghsa", "findings", "fuzz"])
    f.add_argument("--input", nargs="+")
    f.add_argument("--watch")
    f.add_argument("--manifest")
    f.add_argument("--since-days", type=int, default=30)
    f.add_argument("--target")
    f.add_argument("--artifact")
    f.add_argument("--log")
    f.add_argument("--max-new", type=int, default=50)
    s = sub.add_parser("sweep")
    s.add_argument("--repo", required=True)
    s.add_argument("--codeowners", default="CODEOWNERS")
    for q in (f, s):
        q.add_argument("--now")
        q.add_argument("--dry-run", action="store_true")
    i = sub.add_parser("pinned-images")
    i.add_argument("--pins", required=True)
    args = p.parse_args(argv)

    if args.cmd == "pinned-images":
        print("\n".join(pinned_images(Path(args.pins).read_text())))
        return 0

    now = parse_time(args.now) if args.now else dt.datetime.now(UTC)
    gh = _github()
    try:
        if args.cmd == "sweep":
            owners = Path(args.codeowners)
            mentions = security_mentions(owners.read_text() if owners.exists() else "")
            for action in sweep(gh, args.repo, now, mentions, args.dry_run):
                print(*action)
            return 0
        findings, errors = _collect(args, gh, now)
        for action in file_findings(gh, args.repo, findings, now, args.dry_run, args.max_new):
            print(*(a for a in action if a is not None))
    except Refused as e:
        print(f"sla: refused: {e}", file=sys.stderr)
        return 2
    except InputError as e:
        print(f"sla: {e}", file=sys.stderr)
        return 1
    except urllib.error.HTTPError as e:
        print(f"sla: GitHub: HTTP {e.code} {e.reason} ({e.url})", file=sys.stderr)
        return 1
    for err in errors:
        print(f"sla: {err}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
