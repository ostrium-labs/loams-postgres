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


PINS = """
schema = 1
[majors]
supported = [17]
beta = [18]
maintenance = [16]
default = 17
"""
REVISIONS = {"v18": ["18.6", "a" * 40], "v17": ["17.11", "b" * 40], "v16": ["16.15", "c" * 40],
             "v15": ["15.13", "d" * 40], "v14": ["14.18", "e" * 40]}


class Legs(unittest.TestCase):
    """G2's legs and the upgrade job from Loams' pin file (NF2 Task 7, D1118)."""

    def plan(self, pins=PINS, revisions=REVISIONS, own=()):
        return gate.legs(pins, revisions, own)

    def test_gate_legs_follow_pins(self):
        p = self.plan()
        self.assertEqual([(l["major"], l["status"]) for l in p["legs"]],
                         [("16", "maintenance"), ("17", "supported"), ("18", "beta")])
        # 14 and 15 are vendored but no longer pinned: no leg.
        two = self.plan(pins=PINS.replace("beta = [18]", "beta = []"), revisions={k: REVISIONS[k] for k in ("v16", "v17")})
        self.assertEqual([l["major"] for l in two["legs"]], ["16", "17"])
        promoted = self.plan(pins=PINS.replace("supported = [17]", "supported = [17, 18]").replace("beta = [18]", "beta = []"))
        self.assertEqual([(l["major"], l["advisory"]) for l in promoted["legs"]],
                         [("16", False), ("17", False), ("18", False)])

    def test_a_pinned_major_that_is_not_built_is_an_error(self):
        with self.assertRaisesRegex(gate.Finding, "Postgres 18 is in Loams' pin file but not in vendor/revisions.json"):
            self.plan(revisions={k: REVISIONS[k] for k in ("v16", "v17")})

    def test_a_built_major_newer_than_every_pin_gets_an_advisory_leg(self):
        p = self.plan(pins=PINS.replace("beta = [18]", "beta = []"))
        self.assertEqual(p["legs"][-1], {"major": "18", "status": "unpinned", "advisory": True})

    def test_beta_leg_advisory_for_other_majors(self):
        legs = {l["major"]: l for l in self.plan()["legs"]}
        self.assertTrue(legs["18"]["advisory"])
        self.assertFalse(legs["17"]["advisory"])
        self.assertFalse(legs["16"]["advisory"])
        # ... and required for its own images.
        own = {l["major"]: l for l in self.plan(own=["18"])["legs"]}
        self.assertFalse(own["18"]["advisory"])
        # The workflow lets an advisory leg fail without failing its job, so a
        # red beta leg leaves `g2` green and the gate passes ...
        wf = (REPO_ROOT / ".github" / "workflows" / "loams-gate.yml").read_text()
        for job in ("g2", "g2-upgrade"):
            block = wf.split(f"\n  {job}:\n", 1)[1].split("\n\n  ", 1)[0]
            self.assertIn("continue-on-error: ${{ matrix.leg.advisory }}", block, job)
        self.assertEqual(gate.verdict(["g2"], needs(g2_build="success", g2="success", g2_upgrade="skipped"),
                                      may_skip=["g2-upgrade"]), [])
        # ... while a red required leg fails it.
        self.assertEqual(gate.verdict(["g2"], needs(g2_build="success", g2="failure", g2_upgrade="skipped"),
                                      may_skip=["g2-upgrade"]), ["g2 (g2): failure"])

    def test_own_major_must_have_a_leg(self):
        with self.assertRaisesRegex(gate.Finding, "own major 19 has no leg"):
            self.plan(own=["19"])

    def test_upgrade_from_each_supported_major_to_the_next(self):
        p = self.plan()
        self.assertEqual(p["upgrade"], [{"from": "17", "to": "18", "advisory": True}])
        self.assertEqual(p["upgrade_skipped"], [])
        self.assertEqual(self.plan(own=["18"])["upgrade"], [{"from": "17", "to": "18", "advisory": False}])

    def test_upgrade_to_a_major_not_built_is_skipped_with_a_reason(self):
        p = self.plan(pins=PINS.replace("beta = [18]", "beta = []"), revisions={k: REVISIONS[k] for k in ("v16", "v17")})
        self.assertEqual(p["upgrade"], [])
        self.assertEqual(p["upgrade_skipped"], [{"from": "17", "to": "18",
                                                 "reason": "Postgres 18 is not built in this commit (no v18 in vendor/revisions.json)"}])
        self.assertEqual(p["may_skip"], ["g2-upgrade"])

    def test_skipped_job_is_red_unless_the_plan_allows_it(self):
        self.assertEqual(gate.verdict(["g2"], needs(g2_build="success", g2="success", g2_upgrade="skipped")),
                         ["g2-upgrade (g2): skipped"])
        # may_skip never excuses a failure.
        self.assertTrue(gate.verdict(["g2"], needs(g2_build="success", g2="success", g2_upgrade="failure"),
                                     may_skip=["g2-upgrade"]))

    def test_cli_legs(self):
        with tempfile.TemporaryDirectory() as d:
            pins, revs = Path(d) / "pins.toml", Path(d) / "revisions.json"
            pins.write_text(PINS)
            revs.write_text(json.dumps(REVISIONS))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(gate.main(["legs", "--pins", str(pins), "--revisions", str(revs), "--own-majors", ""]), 0)
            lines = dict(l.split("=", 1) for l in out.getvalue().splitlines())
            self.assertEqual([l["major"] for l in json.loads(lines["legs"])], ["16", "17", "18"])
            self.assertEqual(json.loads(lines["upgrade"]), [{"from": "17", "to": "18", "advisory": True}])
            self.assertEqual(json.loads(lines["may-skip"]), [])
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(gate.main(["legs", "--pins", str(pins), "--revisions", str(revs), "--own-majors", "x"]), 2)

    def test_the_gate_never_runs_on_pull_requests_or_a_schedule(self):
        wf = (REPO_ROOT / ".github" / "workflows" / "loams-gate.yml").read_text()
        on = wf.split("\non:\n", 1)[1].split("\n\n", 1)[0]
        triggers = [l.strip().rstrip(":") for l in on.splitlines() if l.startswith("  ") and not l.startswith("   ")]
        self.assertEqual(triggers, ["workflow_dispatch", "workflow_call"])


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
