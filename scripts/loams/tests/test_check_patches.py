#!/usr/bin/env python3
"""NF1 Task 4: tests for scripts/loams/check-patches.py.

Each test builds a scratch git repository: a "Neon" history, a fork point tag,
then our commits and a LOAMS_PATCHES.md, and runs the script on it.

Run: python3 -I scripts/loams/tests/test_check_patches.py
"""

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECK = HERE.parent / "check-patches.py"

HEADER = """\
# Loams Postgres patches

## Patches

| Id | Title | Area | Owner | Since | Origin | Drop when |
|---|---|---|---|---|---|---|
"""

UPSTREAM_SHA = "0123456789abcdef0123456789abcdef01234567"


def row(pid, origin="loams-only", title="A patch", area="compute"):
    return f"| {pid} | {title} | {area} | @owner | 2026-10-12 | {origin} | never |\n"


class Repo(unittest.TestCase):
    """A scratch repository with Neon's history and the fork point."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.env = dict(
            os.environ,
            GIT_AUTHOR_NAME="t",
            GIT_AUTHOR_EMAIL="t@example.com",
            GIT_COMMITTER_NAME="t",
            GIT_COMMITTER_EMAIL="t@example.com",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
        )
        self.git("init", "-q", "-b", "main")
        self.commit("neon: first", "a.txt")
        self.commit("neon: second, no trailer", "b.txt")
        self.git("tag", "neon-fork-point")
        self.rows = ""
        self.exceptions = ""

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        out = subprocess.run(
            ["git", *args], cwd=self.dir, env=self.env, capture_output=True, text=True
        )
        if out.returncode != 0:
            raise AssertionError(f"git {args}: {out.stderr}")
        return out.stdout.strip()

    def commit(self, message, path=None):
        path = path or f"f{len(self.git('rev-list', '--all').split())}.txt"
        f = self.dir / path
        f.write_text(f.read_text() + "x\n" if f.exists() else "x\n")
        self.git("add", path)
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def patch(self, pid, subject="compute: a change", body=""):
        msg = subject + "\n\n" + (body + "\n\n" if body else "")
        return self.commit(msg + f"Loams-Patch: {pid}\nSigned-off-by: t <t@example.com>")

    def write_queue(self):
        text = HEADER + self.rows
        if self.exceptions:
            text += (
                "\n## Commits without a trailer\n\n"
                "| Commit | Id | Why |\n|---|---|---|\n" + self.exceptions
            )
        (self.dir / "LOAMS_PATCHES.md").write_text(text)

    def run_check(self, *extra):
        self.write_queue()
        return subprocess.run(
            [sys.executable, "-I", str(CHECK), "--repo", str(self.dir), *extra],
            capture_output=True,
            text=True,
        )

    def assertPasses(self, *extra):
        out = self.run_check(*extra)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        return out

    def assertFindings(self, needle, *extra):
        out = self.run_check(*extra)
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn(needle, out.stdout)
        return out


class Queue(Repo):
    def test_listed_patches_pass(self):
        self.patch("LP-0000", "loams-ci: charter")
        self.patch("LP-0000", "loams-ci: patch queue")
        self.patch("LP-0032", "compute_ctl: least privilege")
        self.rows = row("LP-0000", area="ci") + row("LP-0032")
        out = self.assertPasses()
        self.assertIn("3 commits, 2 patches", out.stdout)

    def test_unlisted_patch_fails(self):
        self.patch("LP-0000")
        sha = self.commit("compute: no trailer at all")
        self.rows = row("LP-0000")
        self.assertFindings(f"{sha[:12]} compute: no trailer at all: no Loams-Patch trailer")

    def test_trailer_without_row_fails(self):
        self.patch("LP-0000")
        sha = self.patch("LP-0007", "licence: texts")
        self.rows = row("LP-0000")
        self.assertFindings(f"{sha[:12]} licence: texts: LP-0007 has no row")

    def test_row_without_commit_fails(self):
        self.patch("LP-0000")
        self.rows = row("LP-0000") + row("LP-0005")
        self.assertFindings("LP-0005: row has no commit")

    def test_neon_history_exempt(self):
        # The two commits before neon-fork-point carry no trailer.
        self.patch("LP-0000")
        self.rows = row("LP-0000")
        out = self.assertPasses()
        self.assertIn("1 commits, 1 patches", out.stdout)

    def test_merge_commits_are_not_patches(self):
        self.git("checkout", "-q", "-b", "loams/topic")
        self.patch("LP-0000")
        self.git("checkout", "-q", "main")
        self.git("merge", "-q", "--no-ff", "-m", "Merge pull request #1", "loams/topic")
        self.rows = row("LP-0000")
        self.assertPasses()

    def test_two_ids_on_one_commit_fail(self):
        sha = self.commit("compute: two\n\nLoams-Patch: LP-0000\nLoams-Patch: LP-0001")
        self.rows = row("LP-0000") + row("LP-0001")
        self.assertFindings(f"{sha[:12]} compute: two: more than one Loams-Patch trailer")

    def test_malformed_trailer_fails(self):
        sha = self.patch("LP-7")
        self.rows = row("LP-0000")
        self.assertFindings(f"{sha[:12]} compute: a change: malformed Loams-Patch trailer 'LP-7'")


class Exceptions(Repo):
    def test_commit_without_trailer_listed_passes(self):
        sha = self.commit("pageserver_api: trim")
        self.patch("LP-0000")
        self.rows = row("LP-0000") + row("LP-0001", origin="upstreamable")
        self.exceptions = f"| {sha} | LP-0001 | before the trailer rule |\n"
        self.assertPasses()

    def test_exception_outside_range_fails(self):
        self.patch("LP-0000")
        neon = self.git("rev-parse", "neon-fork-point")
        self.rows = row("LP-0000")
        self.exceptions = f"| {neon} | LP-0000 | stale |\n"
        self.assertFindings(f"{neon[:12]}: listed without a trailer but not in")

    def test_exception_needs_full_sha(self):
        sha = self.commit("pageserver_api: trim")
        self.rows = row("LP-0001")
        self.exceptions = f"| {sha[:8]} | LP-0001 | short |\n"
        out = self.run_check()
        self.assertEqual(out.returncode, 2, out.stdout + out.stderr)
        self.assertIn("40 hex", out.stderr)


class SyncMerges(Repo):
    def upstream_merge(self, message):
        base = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "-b", "upstream", "neon-fork-point")
        self.commit("Fix a bug in the planner (Postgres)")
        self.commit("Stamp 17.11 (Postgres)")
        self.git("checkout", "-q", "main")
        self.git("merge", "-q", "--no-ff", "-m", message, "upstream")
        return base

    def test_postgres_sync_merge_exempt(self):
        self.patch("LP-0014")
        self.upstream_merge("Merge REL_17_11\n\nLoams-Sync: REL_17_11")
        self.rows = row("LP-0014")
        self.assertPasses("--allow-sync-merges")

    def test_sync_merge_not_exempt_without_flag(self):
        self.patch("LP-0014")
        self.upstream_merge("Merge REL_17_11\n\nLoams-Sync: REL_17_11")
        self.rows = row("LP-0014")
        self.assertFindings("Stamp 17.11 (Postgres): no Loams-Patch trailer")

    def test_merge_without_sync_trailer_not_exempt(self):
        self.patch("LP-0014")
        self.upstream_merge("Merge upstream")
        self.rows = row("LP-0014")
        self.assertFindings("Stamp 17.11 (Postgres): no Loams-Patch trailer", "--allow-sync-merges")


class CherryPicks(Repo):
    def test_cherry_pick_needs_origin_line(self):
        sha = self.patch("LP-0040", "proxy: a fix from Neon")
        self.rows = row("LP-0040", origin="cherry-pick")
        self.assertFindings(f"{sha[:12]} proxy: a fix from Neon: LP-0040 is a cherry-pick")

    def test_cherry_pick_with_origin_line_passes(self):
        self.patch(
            "LP-0040",
            "proxy: a fix from Neon",
            f"(cherry picked from neondatabase/neon {UPSTREAM_SHA})",
        )
        self.rows = row("LP-0040", origin="cherry-pick")
        self.assertPasses()

    def test_origin_line_needs_cherry_pick_row(self):
        sha = self.patch(
            "LP-0040",
            "proxy: a fix from Neon",
            f"(cherry picked from neondatabase/neon {UPSTREAM_SHA})",
        )
        self.rows = row("LP-0040", origin="loams-only")
        self.assertFindings(f"{sha[:12]} proxy: a fix from Neon: cherry-picked, but LP-0040's origin")


class File(Repo):
    def run_bad(self, needle):
        self.patch("LP-0000")
        out = self.run_check()
        self.assertEqual(out.returncode, 2, out.stdout + out.stderr)
        self.assertIn(needle, out.stderr)

    def test_duplicate_row_is_an_error(self):
        self.rows = row("LP-0000") + row("LP-0000")
        self.run_bad("LP-0000 is listed twice")

    def test_unknown_origin_is_an_error(self):
        self.rows = row("LP-0000", origin="upstream")
        self.run_bad("origin 'upstream'")

    def test_bad_date_is_an_error(self):
        self.rows = "| LP-0000 | T | ci | @owner | 2026-13-01 | loams-only | never |\n"
        self.run_bad("since '2026-13-01'")

    def test_owner_needs_at(self):
        self.rows = "| LP-0000 | T | ci | owner | 2026-10-12 | loams-only | never |\n"
        self.run_bad("owner 'owner'")

    def test_wrong_columns_are_an_error(self):
        self.rows = "| LP-0000 | T | ci | @owner | 2026-10-12 | loams-only |\n"
        self.run_bad("7 columns")

    def test_missing_patches_section_is_an_error(self):
        self.patch("LP-0000")
        (self.dir / "LOAMS_PATCHES.md").write_text("# Patches\n")
        out = subprocess.run(
            [sys.executable, "-I", str(CHECK), "--repo", str(self.dir), "--patches", "LOAMS_PATCHES.md"],
            capture_output=True,
            text=True,
        )
        # run_check rewrites the file; call the script directly.
        self.assertEqual(out.returncode, 2, out.stdout + out.stderr)
        self.assertIn("## Patches", out.stderr)

    def test_unknown_base_is_an_error(self):
        self.rows = row("LP-0000")
        out = self.run_check("--base", "no-such-tag")
        self.assertEqual(out.returncode, 2, out.stdout + out.stderr)
        self.assertIn("no-such-tag", out.stderr)


class RealQueue(unittest.TestCase):
    """The repository's own LOAMS_PATCHES.md parses (history is checked in CI)."""

    def test_repository_queue_parses(self):
        root = HERE.parent.parent.parent
        if not (root / "LOAMS_PATCHES.md").exists():
            self.skipTest("no LOAMS_PATCHES.md")
        out = subprocess.run(
            [sys.executable, "-I", str(CHECK), "--repo", str(root), "--parse-only"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)


if __name__ == "__main__":
    unittest.main()
