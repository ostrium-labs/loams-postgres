#!/usr/bin/env python3
"""Tests for scripts/loams/gate.py (LP-0015, NF1 Task 16).

Scratch test trees are built in a temporary directory; the real subset is
checked against this repository's test_runner as well.

Run: python3 -I scripts/loams/tests/test_gate.py
"""

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent
SCRIPT = HERE.parent / "gate.py"
spec = importlib.util.spec_from_file_location("gate", SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

ISSUE = "https://github.com/ostrium-labs/loams/issues/1"


class Subset(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        regress = self.root / "test_runner" / "regress"
        regress.mkdir(parents=True)
        (regress / "test_a.py").write_text(
            "import pytest\n\n"
            "def test_one(x):\n    pass\n\n"
            "async def test_two():\n    pass\n\n"
            "class TestNested:\n    def test_three(self):\n        pass\n"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def parse(self, text):
        return gate.parse_subset(text, self.root)

    def test_the_repository_subset_names_existing_tests(self):
        text = (REPO_ROOT / "scripts" / "loams" / "gate-subset.txt").read_text()
        tests, _ = gate.parse_subset(text, REPO_ROOT)
        self.assertIn("test_runner/regress/test_pg_regress.py::test_pg_regress", tests)

    def test_listed_tests_and_comments(self):
        tests, deselects = self.parse(
            "# comment\n\ntest_runner/regress/test_a.py::test_one\ntest_runner/regress/test_a.py::test_two\n"
        )
        self.assertEqual(tests, ["test_runner/regress/test_a.py::test_one", "test_runner/regress/test_a.py::test_two"])
        self.assertEqual(deselects, [])

    def test_missing_function_fails(self):
        with self.assertRaisesRegex(gate.Finding, "defines no test_gone"):
            self.parse("test_runner/regress/test_a.py::test_gone\n")

    def test_method_of_a_class_is_not_a_module_test(self):
        with self.assertRaisesRegex(gate.Finding, "defines no test_three"):
            self.parse("test_runner/regress/test_a.py::test_three\n")

    def test_missing_file_fails(self):
        with self.assertRaisesRegex(gate.Finding, "test_b.py does not exist"):
            self.parse("test_runner/regress/test_b.py::test_one\n")

    def test_malformed_line_fails(self):
        with self.assertRaisesRegex(gate.Finding, "is not test_runner/regress"):
            self.parse("test_runner/regress/test_a.py -k one\n")

    def test_duplicate_fails(self):
        with self.assertRaisesRegex(gate.Finding, "listed twice"):
            self.parse("test_runner/regress/test_a.py::test_one\ntest_runner/regress/test_a.py::test_one\n")

    def test_empty_subset_fails(self):
        with self.assertRaisesRegex(gate.Finding, "lists no test"):
            self.parse("# nothing\n")

    def test_deselect_needs_an_issue(self):
        with self.assertRaisesRegex(gate.Finding, "not a GitHub issue URL"):
            self.parse(
                "test_runner/regress/test_a.py::test_one\n"
                "deselect test_runner/regress/test_a.py::test_one[release-pg17] flaky\n"
            )

    def test_deselect_must_be_a_listed_test(self):
        with self.assertRaisesRegex(gate.Finding, "not a parameter of a listed test"):
            self.parse(
                "test_runner/regress/test_a.py::test_one\n"
                f"deselect test_runner/regress/test_a.py::test_two[release-pg17] {ISSUE}\n"
            )

    def test_pytest_args_carry_the_deselects(self):
        tests, deselects = self.parse(
            "test_runner/regress/test_a.py::test_one\n"
            f"deselect test_runner/regress/test_a.py::test_one[release-pg17] {ISSUE}\n"
        )
        self.assertEqual(
            gate.pytest_args(tests, deselects),
            ["test_runner/regress/test_a.py::test_one", "--deselect", "test_runner/regress/test_a.py::test_one[release-pg17]"],
        )


def needs(**results):
    return {job.replace("_", "-"): {"result": r, "outputs": {}} for job, r in results.items()}


class Verdict(unittest.TestCase):
    def test_all_green(self):
        self.assertEqual(gate.verdict(["g0", "g1", "g2"], needs(g0="success", g1="success", g2_build="success", g2="success")), [])

    def test_gate_fails_on_red_tier(self):
        problems = gate.verdict(["g0", "g1", "g2"], needs(g0="success", g1="failure", g2_build="success", g2="success"))
        self.assertEqual(problems, ["g1 (g1): failure"])

    def test_cancelled_is_red(self):
        self.assertTrue(gate.verdict(["g1"], needs(g1="cancelled")))

    def test_requested_but_skipped_is_red(self):
        # e.g. g2 skipped because g2-build failed
        problems = gate.verdict(["g2"], needs(g2_build="failure", g2="skipped"))
        self.assertIn("g2-build (g2): failure", problems)
        self.assertIn("g2 (g2): skipped", problems)

    def test_requested_tier_with_no_job_is_red(self):
        self.assertEqual(gate.verdict(["g3"], needs(g0="skipped")), ["g3: requested, but no job of it ran"])

    def test_unrequested_tiers_may_be_skipped(self):
        self.assertEqual(gate.verdict(["g3"], needs(g0="skipped", g1="skipped", g2="skipped", g3="success")), [])

    def test_unrequested_tier_that_failed_is_red(self):
        self.assertTrue(gate.verdict(["g3"], needs(g1="failure", g3="success")))

    def test_tiers(self):
        self.assertEqual(gate.parse_tiers("g0, g2"), ["g0", "g2"])
        with self.assertRaises(ValueError):
            gate.parse_tiers("g0,g4")
        with self.assertRaises(ValueError):
            gate.parse_tiers("")

    def test_cli_verdict_exit_codes(self):
        ok = json.dumps(needs(g1="success"))
        red = json.dumps(needs(g1="failure"))
        def run(*argv):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                return gate.main(list(argv))

        self.assertEqual(run("verdict", "--tiers", "g1", "--needs", ok), 0)
        self.assertEqual(run("verdict", "--tiers", "g1", "--needs", red), 1)
        self.assertEqual(run("verdict", "--tiers", "g9", "--needs", ok), 2)


class ExecCheck(unittest.TestCase):
    WORKFLOW = (
        "jobs:\n"
        "  a:\n"
        "    steps:\n"
        "      - name: inline\n"
        "        run: scripts/inline.sh \"$KEY\"\n"
        "      - run: |\n"
        "          set -euo pipefail\n"
        "          ./scripts/block.sh x\n"
        "          python3 -I scripts/interpreted.py\n"
        "      - uses: actions/cache@v4\n"
        "        with:\n"
        "          key: ${{ hashFiles('scripts/not-run.sh') }}\n"
        "on:\n"
        "  pull_request:\n"
        "    paths:\n"
        "      - scripts/also-not-run.sh\n"
    )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".github" / "workflows").mkdir(parents=True)
        (self.root / ".github" / "workflows" / "w.yml").write_text(self.WORKFLOW)
        (self.root / "scripts").mkdir()
        for name in ("inline.sh", "block.sh"):
            f = self.root / "scripts" / name
            f.write_text("#!/bin/sh\n")
            f.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_scripts_run_by_path(self):
        self.assertEqual(
            [p for _, p in gate.direct_scripts(self.WORKFLOW)],
            ["scripts/inline.sh", "scripts/block.sh"],
        )

    def test_workflow_scripts_executable(self):
        self.assertEqual(gate.exec_problems(self.root), [])

    def test_a_script_without_its_mode_bit_fails(self):
        # lp-2026.11.0: gate-g3.sh lost its mode and G3 exited 126.
        (self.root / "scripts" / "block.sh").chmod(0o644)
        problems = gate.exec_problems(self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn("w.yml:8: scripts/block.sh is not executable", problems[0])

    def test_a_missing_script_fails(self):
        (self.root / "scripts" / "inline.sh").unlink()
        self.assertEqual(gate.exec_problems(self.root), [".github/workflows/w.yml:5: scripts/inline.sh does not exist"])

    def test_the_repository_workflows(self):
        self.assertEqual(gate.exec_problems(REPO_ROOT), [])


class RequiredChecks(unittest.TestCase):
    def rules(self, *contexts):
        return [
            {"type": "deletion"},
            {"type": "required_status_checks",
             "parameters": {"required_status_checks": [{"context": c, "integration_id": 15368} for c in contexts]}},
        ]

    def test_required_checks_configured(self):
        self.assertEqual(gate.missing_required_checks(self.rules("hygiene", "patches", "dco")), [])

    def test_a_missing_check_is_reported(self):
        self.assertEqual(gate.missing_required_checks(self.rules("hygiene", "dco")), ["patches"])

    def test_no_rule_at_all(self):
        self.assertEqual(gate.missing_required_checks([{"type": "deletion"}]), list(gate.REQUIRED_CHECKS))
        self.assertEqual(gate.missing_required_checks(None), list(gate.REQUIRED_CHECKS))


if __name__ == "__main__":
    unittest.main(verbosity=1)
