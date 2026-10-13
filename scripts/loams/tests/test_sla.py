#!/usr/bin/env python3
"""NF1 Task 6: tests for scripts/loams/sla.py and scripts/loams/pg-security-feed.py.

GitHub is replaced by FakeGitHub, an in-memory issue tracker with the same
methods as sla.GitHub. The inputs are fixtures under fixtures/sla/: trimmed
real `cargo deny --format json check advisories` output, postgresql.org's
versions.rss, Trivy reports, GitHub repository advisories and libFuzzer logs.

Run: python3 -I scripts/loams/tests/test_sla.py
"""

import contextlib
import copy
import datetime as dt
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
FIX = HERE / "fixtures" / "sla"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sla = load("sla", "sla.py")
pgfeed = load("pg_security_feed", "pg-security-feed.py")

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
REPO = "ostrium-labs/loams-postgres-security"


class FakeGitHub:
    """In-memory stand-in for sla.GitHub (one repository is enough here)."""

    def __init__(self, private=True, advisories=None):
        self.private = private
        self.issues = []
        self.labels = {}
        self.advisories = advisories or {}
        self.writes = 0

    def repo_is_private(self, repo):
        return self.private

    def ensure_label(self, repo, name, color, description):
        self.labels.setdefault(name, (color, description))

    def list_issues(self, repo, state="all"):
        return [
            copy.deepcopy(i) for i in self.issues if state == "all" or i["state"] == state
        ]

    def create_issue(self, repo, title, body, labels):
        self.writes += 1
        issue = {
            "number": len(self.issues) + 1,
            "title": title,
            "body": body,
            "labels": [{"name": n} for n in labels],
            "state": "open",
            "created_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "html_url": f"https://github.com/{repo}/issues/{len(self.issues) + 1}",
            "comments": [],
        }
        self.issues.append(issue)
        return copy.deepcopy(issue)

    def update_issue(self, repo, number, body):
        self.writes += 1
        self.issue(number)["body"] = body

    def add_labels(self, repo, number, labels):
        self.writes += 1
        issue = self.issue(number)
        for name in labels:
            if name not in self.label_names(issue):
                issue["labels"].append({"name": name})

    def comment(self, repo, number, body):
        self.writes += 1
        self.issue(number)["comments"].append(body)

    def list_repo_advisories(self, repo):
        return copy.deepcopy(self.advisories.get(repo, []))

    # helpers for the tests
    def issue(self, number):
        return next(i for i in self.issues if i["number"] == number)

    @staticmethod
    def label_names(issue):
        return [lab["name"] for lab in issue["labels"]]

    def add_manual_issue(self, title, labels, created_at, body="Reported by hand."):
        issue = self.create_issue(REPO, title, body, labels)
        self.issue(issue["number"])["created_at"] = created_at
        return issue["number"]


def finding(key="test:1", severity="high", found=NOW, private=False):
    return sla.Finding(
        key=key, title=f"Finding {key}", severity=severity, found=found, body="Details.", private=private
    )


class Targets(unittest.TestCase):
    def test_due_dates_follow_targets(self):
        """§51 §3.7 (Q724 defaults): 72 h, 7 days, 7 days after the release, 30 days."""
        found = dt.datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
        self.assertEqual(sla.due_date("critical", found), dt.datetime(2026, 10, 4, 12, 0, tzinfo=UTC))
        self.assertEqual(sla.due_date("high", found), dt.datetime(2026, 10, 8, 12, 0, tzinfo=UTC))
        self.assertEqual(sla.due_date("pg-minor", found), dt.datetime(2026, 10, 8, 12, 0, tzinfo=UTC))
        self.assertEqual(sla.due_date("other", found), dt.datetime(2026, 10, 31, 12, 0, tzinfo=UTC))
        with self.assertRaises(KeyError):
            sla.due_date("medium", found)

        gh = FakeGitHub()
        sla.file_findings(gh, REPO, [finding("k:crit", "critical", found)], NOW)
        issue = gh.issues[0]
        self.assertIn("sev:critical", gh.label_names(issue))
        self.assertIn("loams-sla", gh.label_names(issue))
        self.assertIn("Due: 2026-10-04 12:00 UTC", issue["body"])
        self.assertEqual(sla.marker(issue["body"])["due"], "2026-10-04T12:00:00Z")

    def test_cvss_scores(self):
        cases = {
            "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H": 9.8,
            "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H": 7.5,
            "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N": 5.3,
            "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H": 10.0,
            "CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N": 6.1,
            "CVSS:3.0/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H": 7.8,
            "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N": 0.0,
        }
        for vector, score in cases.items():
            self.assertEqual(sla.cvss3_base_score(vector), score, vector)
        # CVSS 4.0 and malformed vectors have no score here.
        self.assertIsNone(sla.cvss3_base_score("CVSS:4.0/AV:N/AC:H/AT:N/PR:L/UI:A/VC:N/VI:N/VA:H/SC:N/SI:N/SA:H"))
        self.assertIsNone(sla.cvss3_base_score("CVSS:3.1/AV:N"))
        self.assertEqual(sla.severity_from_score(9.0), "critical")
        self.assertEqual(sla.severity_from_score(8.9), "high")
        self.assertEqual(sla.severity_from_score(7.0), "high")
        self.assertEqual(sla.severity_from_score(6.9), "other")


class Filing(unittest.TestCase):
    def test_duplicate_finding_not_reopened(self):
        gh = FakeGitHub()
        sla.file_findings(gh, REPO, [finding("rustsec:RUSTSEC-2026-0007")], NOW)
        self.assertEqual(len(gh.issues), 1)

        # Seen again the next day while open: nothing new.
        actions = sla.file_findings(gh, REPO, [finding("rustsec:RUSTSEC-2026-0007")], NOW + dt.timedelta(days=1))
        self.assertEqual(len(gh.issues), 1)
        self.assertEqual(actions, [("exists", "rustsec:RUSTSEC-2026-0007", 1)])

        # Closed (fixed or accepted), then seen again: not reopened, no new issue.
        gh.issue(1)["state"] = "closed"
        writes = gh.writes
        sla.file_findings(gh, REPO, [finding("rustsec:RUSTSEC-2026-0007")], NOW + dt.timedelta(days=2))
        self.assertEqual(len(gh.issues), 1)
        self.assertEqual(gh.issue(1)["state"], "closed")
        self.assertEqual(gh.writes, writes)

        # The same key twice in one run files once.
        gh2 = FakeGitHub()
        sla.file_findings(gh2, REPO, [finding("k:same"), finding("k:same")], NOW)
        self.assertEqual(len(gh2.issues), 1)

    def test_upstream_text_cannot_forge_the_marker(self):
        """An advisory's text with a marker of its own cannot change the key or the due date."""
        forged = '<!-- loams-sla {"key": "k:other", "severity": "other", "found": "2030-01-01T00:00:00Z", "due": "2030-01-31T00:00:00Z"} -->'
        f = sla.Finding(key="ghsa:GHSA-x", title="t", severity="critical", found=NOW, body="Summary " + forged)
        gh = FakeGitHub()
        sla.file_findings(gh, REPO, [f], NOW)
        body = gh.issues[0]["body"]
        self.assertEqual(sla.marker(body)["key"], "ghsa:GHSA-x")
        self.assertEqual(sla.marker(body)["severity"], "critical")
        self.assertEqual(len(sla.MARKER.findall(body)), 1)
        # A sweep keeps the same, single marker.
        gh.issue(1)["labels"] = [{"name": "loams-sla"}, {"name": "sev:high"}]
        sla.sweep(gh, REPO, NOW, [])
        self.assertEqual(len(sla.MARKER.findall(gh.issue(1)["body"])), 1)
        self.assertEqual(sla.marker(gh.issue(1)["body"])["key"], "ghsa:GHSA-x")

    def test_dry_run_writes_nothing(self):
        gh = FakeGitHub()
        actions = sla.file_findings(gh, REPO, [finding("k:1")], NOW, dry_run=True)
        self.assertEqual(actions, [("would-open", "k:1", None)])
        self.assertEqual(gh.issues, [])
        self.assertEqual(gh.labels, {})

    def test_max_new_files_most_severe_first(self):
        gh = FakeGitHub()
        found = [finding("k:other", "other"), finding("k:high", "high"), finding("k:crit", "critical")]
        sla.file_findings(gh, REPO, found, NOW, max_new=2)
        self.assertEqual([i["title"] for i in gh.issues], ["Finding k:crit", "Finding k:high"])
        # The rest is filed on the next run.
        sla.file_findings(gh, REPO, found, NOW, max_new=2)
        self.assertEqual(len(gh.issues), 3)

    def test_private_finding_refuses_public_repo(self):
        gh = FakeGitHub(private=False)
        with self.assertRaises(sla.Refused):
            sla.file_findings(gh, "ostrium-labs/loams-postgres", [finding("fuzz:x", private=True)], NOW)
        self.assertEqual(gh.issues, [])

    def test_pull_requests_are_not_issues(self):
        gh = FakeGitHub()
        sla.file_findings(gh, REPO, [finding("k:1")], NOW)
        gh.issues[0]["pull_request"] = {"url": "x"}
        sla.file_findings(gh, REPO, [finding("k:1")], NOW)
        self.assertEqual(len(gh.issues), 2)


class Sweep(unittest.TestCase):
    def test_overdue_issue_escalates(self):
        gh = FakeGitHub()
        found = dt.datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
        sla.file_findings(gh, REPO, [finding("k:late", "critical", found), finding("k:fine", "other", found)], NOW)
        mentions = ["@ostrium-labs/security", "@dina-kar"]

        sla.sweep(gh, REPO, dt.datetime(2026, 10, 3, 0, 0, tzinfo=UTC), mentions)
        self.assertNotIn("overdue", gh.label_names(gh.issue(1)))

        actions = sla.sweep(gh, REPO, NOW, mentions)  # 2026-10-12: past 10-04 (72 h)
        self.assertEqual(actions, [("escalated", 1)])
        late = gh.issue(1)
        self.assertIn("overdue", gh.label_names(late))
        self.assertEqual(len(late["comments"]), 1)
        self.assertIn("@ostrium-labs/security", late["comments"][0])
        self.assertIn("@dina-kar", late["comments"][0])
        self.assertIn("2026-10-04", late["comments"][0])
        self.assertNotIn("overdue", gh.label_names(gh.issue(2)))  # due 10-31

        # Escalation happens once.
        self.assertEqual(sla.sweep(gh, REPO, NOW + dt.timedelta(days=1), mentions), [])
        self.assertEqual(len(late["comments"]), 1)

        # Closed issues are left alone.
        gh.issue(2)["state"] = "closed"
        self.assertEqual(sla.sweep(gh, REPO, dt.datetime(2026, 12, 1, tzinfo=UTC), mentions), [])

    def test_manual_issue_gets_due_date(self):
        """A maintainer opens an issue and labels it; the sweep sets its due date."""
        gh = FakeGitHub()
        number = gh.add_manual_issue("Crash in walredo", ["sev:high"], "2026-10-10T09:30:00Z")
        actions = sla.sweep(gh, REPO, NOW, ["@ostrium-labs/security"])
        self.assertEqual(actions, [("dated", number)])
        issue = gh.issue(number)
        self.assertTrue(issue["body"].startswith("Reported by hand."))
        self.assertEqual(sla.marker(issue["body"])["due"], "2026-10-17T09:30:00Z")
        self.assertIn("loams-sla", gh.label_names(issue))
        # An unlabelled issue is not ours.
        other = gh.add_manual_issue("A question", [], "2026-10-10T09:30:00Z")
        sla.sweep(gh, REPO, NOW, [])
        self.assertIsNone(sla.marker(gh.issue(other)["body"]))

    def test_relabel_moves_due_date(self):
        gh = FakeGitHub()
        found = dt.datetime(2026, 10, 10, 0, 0, tzinfo=UTC)
        sla.file_findings(gh, REPO, [finding("k:1", "high", found)], NOW)
        issue = gh.issue(1)
        issue["labels"] = [{"name": "loams-sla"}, {"name": "sev:other"}]  # triaged down
        actions = sla.sweep(gh, REPO, NOW, [])
        self.assertEqual(actions, [("redated", 1)])
        mark = sla.marker(issue["body"])
        self.assertEqual((mark["severity"], mark["due"]), ("other", "2026-11-09T00:00:00Z"))
        self.assertIn("Due: 2026-11-09 00:00 UTC", issue["body"])
        # Two severity labels: the most severe wins.
        issue["labels"].append({"name": "sev:critical"})
        sla.sweep(gh, REPO, NOW, [])
        self.assertEqual(sla.marker(issue["body"])["severity"], "critical")

    def test_security_mentions_from_codeowners(self):
        text = "* @a\n# security\n/SECURITY.md @dina-kar @Kesh3805\n/NOTICE @x\n"
        self.assertEqual(
            sla.security_mentions(text), ["@ostrium-labs/security", "@dina-kar", "@Kesh3805"]
        )
        self.assertEqual(sla.security_mentions(""), ["@ostrium-labs/security"])


class Sources(unittest.TestCase):
    def test_cargo_deny_findings(self):
        with open(FIX / "cargo-deny.jsonl") as fh:
            found = {f.key: f for f in sla.findings_from_cargo_deny(fh, NOW)}
        self.assertEqual(
            sorted(found),
            [
                "rustsec:RUSTSEC-2025-0056",
                "rustsec:RUSTSEC-2026-0007",
                "rustsec:RUSTSEC-2026-0009",
                "rustsec:RUSTSEC-2026-0194",
                "rustsec:RUSTSEC-2026-0285",
            ],
        )
        # CVSS 3.1 A:H -> 7.5; one issue for three versions of quick-xml.
        xml = found["rustsec:RUSTSEC-2026-0194"]
        self.assertEqual(xml.severity, "high")
        for version in ("0.26.0", "0.31.0", "0.37.1"):
            self.assertIn(version, xml.body)
        self.assertEqual(found["rustsec:RUSTSEC-2026-0285"].severity, "other")  # 5.3
        # A vulnerability without a CVSS 3 score is treated as high.
        self.assertEqual(found["rustsec:RUSTSEC-2026-0007"].severity, "high")
        self.assertEqual(found["rustsec:RUSTSEC-2026-0009"].severity, "high")  # CVSS 4.0 only
        # Unmaintained is informational.
        self.assertEqual(found["rustsec:RUSTSEC-2025-0056"].severity, "other")
        self.assertTrue(all(f.found == NOW and not f.private for f in found.values()))

    def test_cargo_deny_that_did_not_finish_is_an_error(self):
        lines = (FIX / "cargo-deny.jsonl").read_text().splitlines()
        with self.assertRaises(sla.InputError):
            sla.findings_from_cargo_deny([l for l in lines if '"summary"' not in l], NOW)
        with self.assertRaises(sla.InputError):
            sla.findings_from_cargo_deny(["error: failed to fetch advisory database"], NOW)

    def test_trivy_findings(self):
        reports = [json.loads((FIX / n).read_text()) for n in ("trivy-storage.json", "trivy-compute.json")]
        found = {f.key: f for f in sla.findings_from_trivy(reports, NOW)}
        self.assertEqual(sorted(found), ["cve:CVE-2026-0101", "cve:CVE-2026-0202", "cve:CVE-2026-0303"])
        ssl = found["cve:CVE-2026-0101"]
        self.assertEqual(ssl.severity, "critical")
        self.assertIn("ghcr.io/neondatabase/neon@sha256:7a4f1249", ssl.body)
        self.assertIn("ghcr.io/neondatabase/compute-node-v17@sha256:13ab146d", ssl.body)
        self.assertEqual(found["cve:CVE-2026-0202"].severity, "high")  # no score: Trivy's HIGH
        self.assertEqual(found["cve:CVE-2026-0303"].severity, "high")  # best score 8.1

    def test_ghsa_findings(self):
        advisories = json.loads((FIX / "ghsa.json").read_text())
        found = {f.key: f for f in sla.findings_from_ghsa(advisories, NOW, since_days=30)}
        self.assertEqual(sorted(found), ["ghsa:GHSA-aaaa-bbbb-cccc", "ghsa:GHSA-neon-sign-al00"])
        pgdog = found["ghsa:GHSA-aaaa-bbbb-cccc"]
        self.assertEqual(pgdog.severity, "critical")
        self.assertEqual(pgdog.found, dt.datetime(2026, 10, 10, 8, 0, tzinfo=UTC))
        neon = found["ghsa:GHSA-neon-sign-al00"]
        self.assertEqual(neon.severity, "other")
        self.assertIn("upstream-signal", neon.labels)
        self.assertNotIn("upstream-signal", pgdog.labels)

    def test_watch_list(self):
        repos = sla.watch_list(SCRIPTS / "advisory-watch.txt", None)
        self.assertIn("pgdogdev/pgdog", repos)
        self.assertIn("neondatabase/neon", repos)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        manifest = Path(tmp.name) / "loams-extensions.toml"
        manifest.write_text(
            'schema = 1\n[[extension]]\nname = "pgvector"\n'
            'source = "https://github.com/pgvector/pgvector/archive/refs/tags/v0.8.1.tar.gz"\n'
            '[[extension]]\nname = "postgis"\nsource = "https://download.osgeo.org/postgis/source/postgis-3.5.2.tar.gz"\n'
        )
        repos = sla.watch_list(SCRIPTS / "advisory-watch.txt", manifest)
        self.assertIn("pgvector/pgvector", repos)
        self.assertEqual(len(repos), len(set(repos)))

    def test_pinned_images(self):
        images = sla.pinned_images((FIX / "pins.toml").read_text())
        self.assertEqual(len(images), 3)
        self.assertIn(
            "ghcr.io/neondatabase/neon@sha256:7a4f124917bb929964b2d696d710f19584f80bb9bd51b2af4a6e2425434c761f",
            images,
        )
        out = subprocess.run(
            [sys.executable, "-I", str(SCRIPTS / "sla.py"), "pinned-images", "--pins", str(FIX / "pins.toml")],
            capture_output=True, text=True, check=True,
        ).stdout.split()
        self.assertEqual(out, images)


class PostgresFeed(unittest.TestCase):
    def fetch(self, url):
        name = url.rsplit("/", 1)[1]
        return (FIX / name).read_text()

    def test_pg_security_release_opens_issue(self):
        feed = (FIX / "versions.rss").read_text()
        pins = (FIX / "pins.toml").read_text()
        findings = pgfeed.findings(feed, pins, self.fetch)
        self.assertEqual(len(findings), 1)
        f = findings[0]
        self.assertEqual(f.key, "pg-release:2026-08-13")
        self.assertEqual(f.severity, "pg-minor")
        self.assertEqual(f.found, dt.datetime(2026, 8, 13, tzinfo=UTC))
        self.assertIn("17.11", f.title)
        self.assertIn("16.15", f.title)
        self.assertNotIn("18.6", f.title)  # not a supported or maintenance major
        self.assertNotIn("15.19", f.title)
        self.assertIn("CVE-2026-14662", f.body)
        self.assertIn("pinned 17.5", f.body)

        gh = FakeGitHub()
        sla.file_findings(gh, REPO, findings, NOW)
        self.assertEqual(len(gh.issues), 1)
        issue = gh.issues[0]
        self.assertIn("sev:pg-minor", gh.label_names(issue))
        self.assertIn("Due: 2026-08-20 00:00 UTC", issue["body"])  # 7 days after the release
        # The daily run sees the same release again: no second issue.
        sla.file_findings(gh, REPO, pgfeed.findings(feed, pins, self.fetch), NOW)
        self.assertEqual(len(gh.issues), 1)

    def test_release_without_cves_is_ignored(self):
        feed = (FIX / "versions.rss").read_text().replace("17.11", "17.12").replace("17-11", "17-12")
        pins = (FIX / "pins.toml").read_text().replace("maintenance = [16]", "maintenance = []")
        pins = pins.replace('[images.compute-v16]', '[images.unused]')
        self.assertEqual(pgfeed.findings(feed, pins, self.fetch), [])

    def test_beta_major_is_not_tracked(self):
        pins = (FIX / "pins.toml").read_text()
        self.assertEqual(pgfeed.tracked_majors(pins), {16: "16.9", 17: "17.5"})
        beta = pins.replace("beta = []", "beta = [19]")
        self.assertEqual(sorted(pgfeed.tracked_majors(beta)), [16, 17])

    def test_feed_cli_writes_findings_json(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name) / "findings.json"
        subprocess.run(
            [
                sys.executable, "-I", str(SCRIPTS / "pg-security-feed.py"),
                "--feed", str(FIX / "versions.rss"), "--pins", str(FIX / "pins.toml"),
                "--notes-dir", str(FIX), "--out", str(out),
            ],
            check=True, capture_output=True, text=True,
        )
        data = json.loads(out.read_text())
        self.assertEqual([d["key"] for d in data], ["pg-release:2026-08-13"])
        self.assertEqual(sla.findings_from_json(data)[0].severity, "pg-minor")

    def test_feed_cli_refuses_plain_http(self):
        run = subprocess.run(
            [sys.executable, "-I", str(SCRIPTS / "pg-security-feed.py"),
             "--feed", "http://www.postgresql.org/versions.rss", "--pins", str(FIX / "pins.toml")],
            capture_output=True, text=True,
        )
        self.assertEqual(run.returncode, 2)


class Fuzz(unittest.TestCase):
    def test_fuzz_crash_opens_issue(self):
        crash = (FIX / "crash-input.bin").read_bytes()
        log = (FIX / "fuzz-panic.log").read_text()
        f = sla.finding_from_fuzz("page_service_request", "crash-9b1f0c2d", crash, log, NOW)
        self.assertTrue(f.private)
        self.assertEqual(f.severity, "high")
        self.assertEqual(f.key, "fuzz:page_service_request:panic@libs/pageserver_api/src/pagestream_api.rs:331")
        self.assertIn("R0VUAP8Q", f.body)  # the reproducer, base64
        self.assertIn("cargo fuzz run page_service_request", f.body)
        self.assertIn("attempt to add with overflow", f.body)

        # Never into a public repository.
        with self.assertRaises(sla.Refused):
            sla.file_findings(FakeGitHub(private=False), "ostrium-labs/loams-postgres", [f], NOW)

        gh = FakeGitHub(private=True)
        sla.file_findings(gh, REPO, [f], NOW)
        issue = gh.issues[0]
        self.assertIn("sev:high", gh.label_names(issue))
        self.assertIn("fuzz", gh.label_names(issue))
        self.assertIn("Due: 2026-10-19 06:00 UTC", issue["body"])

        # Another input hitting the same panic is the same finding.
        again = sla.finding_from_fuzz("page_service_request", "crash-ffff", b"other", log, NOW)
        sla.file_findings(gh, REPO, [again], NOW)
        self.assertEqual(len(gh.issues), 1)

    def test_fuzz_cli_keeps_the_finding_out_of_the_log(self):
        # The run log of a public repository is public: `file --kind fuzz`
        # prints nothing that names the target's crash site or the issue.
        gh = FakeGitHub(private=True)
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "crash-9b1f0c2d"
            artifact.write_bytes((FIX / "crash-input.bin").read_bytes())
            argv = ["file", "--repo", REPO, "--kind", "fuzz", "--target", "page_service_request",
                    "--artifact", str(artifact), "--log", str(FIX / "fuzz-panic.log"),
                    "--now", "2026-10-12T06:00:00Z"]
            original = sla._github
            sla._github = lambda: gh
            try:
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    self.assertEqual(sla.main(argv), 0)
                    self.assertEqual(sla.main(argv), 0)  # a known finding: also silent
            finally:
                sla._github = original
        self.assertEqual(len(gh.issues), 1)
        logged = out.getvalue() + err.getvalue()
        for secret in ("pagestream_api", "panic@", "fuzz:", "page_service_request", "#1", " 1\n"):
            self.assertNotIn(secret, logged)

    def test_memory_error_is_critical(self):
        log = (FIX / "fuzz-asan.log").read_text()
        f = sla.finding_from_fuzz("wal_decoder_record", "crash-1", b"\x00", log, NOW)
        self.assertEqual(f.severity, "critical")
        self.assertEqual(
            f.key, "fuzz:wal_decoder_record:asan-heap-buffer-overflow@libs/postgres_ffi/src/walrecord.rs:300"
        )

    def test_panic_outside_our_code_keys_on_our_caller(self):
        """Machine paths are dropped, and a panic in a dependency or std names our frame."""
        log = (
            "thread '<unnamed>' panicked at /home/runner/.cargo/registry/src/"
            "index.crates.io-1949cf8c6b5b557f/bytes-1.9.0/src/bytes.rs:711:9:\n"
            "range end out of bounds\nstack backtrace:\n"
            "  12: bytes::bytes::Bytes::split_to\n"
            "             at /home/runner/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/bytes-1.9.0/src/bytes.rs:711:9\n"
            "  13: postgres_ffi::walrecord::decode_wal_record\n"
            "             at ./libs/postgres_ffi/src/walrecord.rs:412:22\n"
            "  14: wal_decoder::decoder::<impl>::from_bytes_filtered\n"
            "             at ./libs/wal_decoder/src/decoder.rs:30:9\n"
        )
        f = sla.finding_from_fuzz("wal_decoder_record", "crash-1", b"\x01", log, NOW)
        self.assertEqual(
            f.key,
            "fuzz:wal_decoder_record:panic@bytes-1.9.0/src/bytes.rs:711<-libs/postgres_ffi/src/walrecord.rs:412",
        )
        # Without a backtrace, the std location alone, without the toolchain's hash.
        log = (
            "thread '<unnamed>' panicked at /rustc/dcecb99176edf2eec51613730937d21cdd5c8f6e/"
            "library/core/src/str/mod.rs:818:21:\nbyte index 3 is out of bounds\n"
        )
        f = sla.finding_from_fuzz("proxy_scram", "crash-2", b"\x01", log, NOW)
        self.assertEqual(f.key, "fuzz:proxy_scram:panic@rustc/library/core/src/str/mod.rs:818")

    def test_libfuzzer_hint_is_not_a_memory_error(self):
        """libFuzzer's deadly-signal note names AddressSanitizer; that alone is a plain crash."""
        log = (FIX / "fuzz-panic.log").read_text() + (
            "NOTE: libFuzzer has rudimentary signal handlers.\n"
            "      Combine libFuzzer with AddressSanitizer or similar for better crash reports.\n"
        )
        f = sla.finding_from_fuzz("page_service_request", "crash-1", b"\x01", log, NOW)
        self.assertEqual(f.severity, "high")

    def test_unknown_crash_keys_on_the_input(self):
        f = sla.finding_from_fuzz("proxy_scram", "timeout-1", b"abc", "ERROR: libFuzzer: timeout after 30 seconds\n", NOW)
        self.assertEqual(f.key, "fuzz:proxy_scram:timeout")
        f = sla.finding_from_fuzz("proxy_scram", "crash-2", b"abc", "garbage\n", NOW)
        self.assertEqual(f.key, "fuzz:proxy_scram:input-a9993e364706816aba3e25717850c26c9cd0d89d")

    def test_big_reproducer_is_not_inlined(self):
        f = sla.finding_from_fuzz("proxy_startup", "crash-3", b"x" * 100_000, "", NOW)
        self.assertNotIn("x" * 1000, f.body)
        self.assertIn("100000 bytes", f.body)


if __name__ == "__main__":
    unittest.main()
