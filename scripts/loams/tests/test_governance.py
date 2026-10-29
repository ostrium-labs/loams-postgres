#!/usr/bin/env python3
"""NF1 Task 5: tests for the fork's governance files.

- notice_retains_upstream: NOTICE keeps Neon's lines and names the fork.
- dco_rejects_unsigned: scripts/loams/tests/test-dco.sh, check-dco.sh's own test.
- codeowners_valid: GitHub reports no CODEOWNERS errors for this commit.
  It needs `gh` and GH_TOKEN, and the commit pushed to GitHub. Outside
  GitHub Actions it is skipped when either is missing; in Actions it runs.

Run: python3 -I scripts/loams/tests/test_governance.py
"""

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
REPO = "ostrium-labs/loams-postgres"
FORK_LINE = "Based on Neon by Databricks/Neon Inc."


def git(*args):
    return subprocess.run(
        ["git", "-C", str(ROOT), *args], check=True, capture_output=True, text=True
    ).stdout


class Governance(unittest.TestCase):
    def test_notice_retains_upstream(self):
        upstream = git("show", "neon-fork-point:NOTICE").splitlines()
        ours = (ROOT / "NOTICE").read_text().splitlines()
        self.assertEqual(ours[:3], upstream[:3])
        self.assertEqual(ours[: len(upstream)], upstream, "Neon's lines are kept whole")
        self.assertIn(FORK_LINE, "\n".join(ours))
        self.assertIn("LOAMS_PATCHES.md", "\n".join(ours))

    def test_dco_rejects_unsigned(self):
        result = subprocess.run(
            ["bash", str(HERE / "test-dco.sh")], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_codeowners_valid(self):
        in_actions = os.environ.get("GITHUB_ACTIONS") == "true"
        if not in_actions and (shutil.which("gh") is None or not os.environ.get("GH_TOKEN")):
            self.skipTest("needs gh and GH_TOKEN")
        self.assertTrue((ROOT / "CODEOWNERS").is_file())
        ref = os.environ.get("CODEOWNERS_REF") or git("rev-parse", "HEAD").strip()
        out = subprocess.run(
            ["gh", "api", f"repos/{REPO}/codeowners/errors?ref={ref}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertEqual(json.loads(out)["errors"], [])


if __name__ == "__main__":
    sys.exit(unittest.main())
