#!/usr/bin/env python3
"""Tests for scripts/loams/check-postgres-branches.py (LP-0014, NF1 Task 15;
loams/pg18 from REL_18_6 in LP-0035, NF2 Task 2).

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
        ours = cpb.q(f"loams/pg{n}")
        api[f"/repos/{REPO}/branches/{ours}"] = {"name": f"loams/pg{n}"}
        api[f"/repos/{REPO}/compare/{cpb.BASES[n]}...{ours}"] = {"status": "ahead", "ahead_by": 2, "behind_by": 0}
        for f in cpb.REQUIRED_FILES:
            api[f"/repos/{REPO}/contents/{f}?ref={ours}"] = {"name": f}
        api[f"/repos/{REPO}/rules/branches/{ours}"] = PROTECTED
    for n in cpb.RETIRED:
        old, neon = cpb.q(f"loams/REL_{n}_STABLE"), cpb.q(f"REL_{n}_STABLE_neon")
        api[f"/repos/{REPO}/branches/{old}"] = {"name": f"loams/REL_{n}_STABLE"}
        api[f"/repos/{REPO}/rules/branches/{old}"] = PROTECTED
        api[f"/repos/{REPO}/rules/branches/{neon}"] = FROZEN
    return api


def run(api, majors=(16, 17, 18)):
    return cpb.check_branches(api.get, REPO, list(majors))


class BranchesExistAndProtected(unittest.TestCase):
    def test_correct_layout_passes(self):
        self.assertEqual(run(layout()), [])

    def test_missing_branch_fails(self):
        api = layout()
        del api[f"/repos/{REPO}/branches/{cpb.q('loams/pg17')}"]
        self.assertEqual(run(api), [f"loams/pg17: missing in {REPO}"])

    def test_branch_not_on_the_pinned_base_fails(self):
        api = layout()
        api[f"/repos/{REPO}/compare/{cpb.BASES[16]}...{cpb.q('loams/pg16')}"]["behind_by"] = 3
        self.assertIn("does not descend from a42351fc", "\n".join(run(api)))

    def test_major_without_a_base_fails(self):
        self.assertEqual(run(layout(), majors=(19,)), ["loams/pg19: no pinned base revision for Postgres 19"])

    def test_pg18_starts_at_rel_18_6(self):
        self.assertEqual(cpb.BASES[18], "724edf9bde9d356724ad384a2e196edc3c9f80f7")
        api = layout()
        api[f"/repos/{REPO}/compare/{cpb.BASES[18]}...{cpb.q('loams/pg18')}"]["behind_by"] = 1
        self.assertEqual(run(api), ["loams/pg18: does not descend from 724edf9b (1 commits behind)"])

    def test_pg18_missing_fails(self):
        api = layout()
        del api[f"/repos/{REPO}/branches/{cpb.q('loams/pg18')}"]
        self.assertEqual(run(api), [f"loams/pg18: missing in {REPO}"])

    def test_pg18_unprotected_fails(self):
        api = layout()
        api[f"/repos/{REPO}/rules/branches/{cpb.q('loams/pg18')}"] = []
        self.assertEqual(run(api), ["loams/pg18: not protected against deletion, non_fast_forward"])

    def test_missing_security_file_fails(self):
        api = layout()
        del api[f"/repos/{REPO}/contents/SECURITY.md?ref={cpb.q('loams/pg17')}"]
        self.assertEqual(run(api), ["loams/pg17: no SECURITY.md"])

    def test_force_push_allowed_fails(self):
        api = layout()
        api[f"/repos/{REPO}/rules/branches/{cpb.q('loams/pg17')}"] = [{"type": "deletion"}]
        self.assertEqual(run(api), ["loams/pg17: not protected against non_fast_forward"])

    def test_unprotected_branch_fails(self):
        api = layout()
        del api[f"/repos/{REPO}/rules/branches/{cpb.q('loams/pg16')}"]
        self.assertEqual(run(api), ["loams/pg16: not protected against deletion, non_fast_forward"])

    def test_retired_branch_is_kept(self):
        api = layout()
        del api[f"/repos/{REPO}/branches/{cpb.q('loams/REL_17_STABLE')}"]
        self.assertEqual(run(api), ["loams/REL_17_STABLE: retired branches are kept, but it is missing"])

    def test_neon_branch_not_frozen_fails(self):
        api = layout()
        api[f"/repos/{REPO}/rules/branches/{cpb.q('REL_18_STABLE_neon')}"] = PROTECTED
        self.assertEqual(run(api), ["REL_18_STABLE_neon: not frozen (update allowed)"])


class SubmoduleUrlRelative(unittest.TestCase):
    def test_repository_gitmodules_pass(self):
        self.assertEqual(cpb.check_gitmodules((REPO_ROOT / ".gitmodules").read_text()), [])

    def test_absolute_url_fails(self):
        text = '[submodule "vendor/postgres-v17"]\n\tpath = vendor/postgres-v17\n' \
               '\turl = https://github.com/neondatabase/postgres.git\n\tbranch = loams/pg17\n'
        self.assertEqual(len(cpb.check_gitmodules(text)), 1)

    def test_maintained_major_tracks_its_branch(self):
        text = '[submodule "vendor/postgres-v16"]\n\tpath = vendor/postgres-v16\n' \
               '\turl = ../postgres.git\n\tbranch = loams/REL_16_STABLE\n'
        self.assertEqual(cpb.check_gitmodules(text),
                         [".gitmodules: submodule \"vendor/postgres-v16\" tracks 'loams/REL_16_STABLE', not 'loams/pg16'"])

    def test_pg18_submodule_tracks_loams_pg18(self):
        text = '[submodule "vendor/postgres-v18"]\n\tpath = vendor/postgres-v18\n' \
               '\turl = ../postgres.git\n\tbranch = REL_18_STABLE_neon\n'
        self.assertEqual(cpb.check_gitmodules(text),
                         [".gitmodules: submodule \"vendor/postgres-v18\" tracks 'REL_18_STABLE_neon', not 'loams/pg18'"])

    def test_tracked_majors_come_from_gitmodules(self):
        text = ''.join(f'[submodule "vendor/postgres-v{n}"]\n\tpath = vendor/postgres-v{n}\n\turl = ../postgres.git\n'
                       f'\tbranch = {b}\n' for n, b in ((14, "REL_14_STABLE_neon"), (17, "loams/pg17"), (18, "loams/pg18")))
        self.assertEqual(cpb.tracked_majors(text), [17, 18])

    def test_no_submodules_fails(self):
        self.assertEqual(cpb.check_gitmodules(""), [".gitmodules: no submodules"])


class Cli(unittest.TestCase):
    def test_offline_checks_gitmodules_only(self):
        self.assertEqual(cpb.main(["--offline", "--gitmodules", str(REPO_ROOT / ".gitmodules")]), 0)

    def test_bad_majors_is_usage(self):
        self.assertEqual(cpb.main(["--offline", "--majors", "x"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
