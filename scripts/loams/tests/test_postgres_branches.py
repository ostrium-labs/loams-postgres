#!/usr/bin/env python3
"""Tests for scripts/loams/check-postgres-branches.py (LP-0014, NF1 Task 15).

The GitHub API is replaced by a fake built from a dict; nothing goes to the
network. The live check runs in loams-hygiene.yml.

Run: python3 -I scripts/loams/tests/test_postgres_branches.py
"""

import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent
SCRIPT = HERE.parent / "check-postgres-branches.py"
spec = importlib.util.spec_from_file_location("check_postgres_branches", SCRIPT)
cpb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cpb)

REPO = "ostrium-labs/postgres"
PROTECTED = [{"type": "non_fast_forward"}, {"type": "deletion"}]
FROZEN = [{"type": "update"}, {"type": "non_fast_forward"}, {"type": "deletion"}]


def layout(majors=(16, 17, 18)):
    """API answers for a correct layout."""
    api = {}
    for n in majors:
        ours, neon = cpb.q(f"loams/REL_{n}_STABLE"), cpb.q(f"REL_{n}_STABLE_neon")
        api[f"/repos/{REPO}/branches/{ours}"] = {"name": f"loams/REL_{n}_STABLE"}
        api[f"/repos/{REPO}/compare/{neon}...{ours}"] = {"status": "ahead", "ahead_by": 1, "behind_by": 0}
        for f in cpb.REQUIRED_FILES:
            api[f"/repos/{REPO}/contents/{f}?ref={ours}"] = {"name": f}
        api[f"/repos/{REPO}/rules/branches/{ours}"] = PROTECTED
        api[f"/repos/{REPO}/rules/branches/{neon}"] = FROZEN
    return api


def run(api, majors=(16, 17, 18)):
    return cpb.check_branches(api.get, REPO, list(majors))


class BranchesExistAndProtected(unittest.TestCase):
    def test_correct_layout_passes(self):
        self.assertEqual(run(layout()), [])

    def test_missing_branch_fails(self):
        api = layout()
        del api[f"/repos/{REPO}/branches/{cpb.q('loams/REL_18_STABLE')}"]
        self.assertEqual(run(api), [f"loams/REL_18_STABLE: missing in {REPO}"])

    def test_branch_that_drops_neon_history_fails(self):
        api = layout()
        api[f"/repos/{REPO}/compare/{cpb.q('REL_16_STABLE_neon')}...{cpb.q('loams/REL_16_STABLE')}"]["behind_by"] = 3
        self.assertIn("does not descend from REL_16_STABLE_neon", "\n".join(run(api)))

    def test_missing_security_file_fails(self):
        api = layout()
        del api[f"/repos/{REPO}/contents/SECURITY.md?ref={cpb.q('loams/REL_17_STABLE')}"]
        self.assertEqual(run(api), ["loams/REL_17_STABLE: no SECURITY.md"])

    def test_force_push_allowed_fails(self):
        api = layout()
        api[f"/repos/{REPO}/rules/branches/{cpb.q('loams/REL_17_STABLE')}"] = [{"type": "deletion"}]
        self.assertEqual(run(api), ["loams/REL_17_STABLE: not protected against non_fast_forward"])

    def test_unprotected_branch_fails(self):
        api = layout()
        del api[f"/repos/{REPO}/rules/branches/{cpb.q('loams/REL_16_STABLE')}"]
        self.assertEqual(run(api), ["loams/REL_16_STABLE: not protected against deletion, non_fast_forward"])

    def test_neon_branch_not_frozen_fails(self):
        api = layout()
        api[f"/repos/{REPO}/rules/branches/{cpb.q('REL_18_STABLE_neon')}"] = PROTECTED
        self.assertEqual(run(api), ["REL_18_STABLE_neon: not frozen (update allowed)"])


class SubmoduleUrlRelative(unittest.TestCase):
    def test_repository_gitmodules_pass(self):
        self.assertEqual(cpb.check_gitmodules((REPO_ROOT / ".gitmodules").read_text()), [])

    def test_absolute_url_fails(self):
        text = '[submodule "vendor/postgres-v17"]\n\tpath = vendor/postgres-v17\n' \
               '\turl = https://github.com/neondatabase/postgres.git\n'
        self.assertEqual(len(cpb.check_gitmodules(text)), 1)

    def test_no_submodules_fails(self):
        self.assertEqual(cpb.check_gitmodules(""), [".gitmodules: no submodules"])


class Cli(unittest.TestCase):
    def test_offline_checks_gitmodules_only(self):
        self.assertEqual(cpb.main(["--offline", "--gitmodules", str(REPO_ROOT / ".gitmodules")]), 0)

    def test_bad_majors_is_usage(self):
        self.assertEqual(cpb.main(["--offline", "--majors", "x"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
