#!/usr/bin/env python3
"""Tests for scripts/loams/compute-matrix.py (LP-0011, NF1 Task 11).

Run: python3 -I scripts/loams/tests/test_compute_matrix.py
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "compute-matrix.py"
spec = importlib.util.spec_from_file_location("compute_matrix", SCRIPT)
cm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cm)

SHA = "0123456789abcdef0123456789abcdef01234567"
REVISIONS = {"v17": ["17.5", "1e01fcea"], "v16": ["16.9", "a42351fc"], "v15": ["15.13", "2aaab3bb"]}
PINS = """schema = 1
[majors]
supported = [17]
beta = []
maintenance = [16]
default = 17
"""


class Plan(unittest.TestCase):
    def test_today_builds_16_and_17(self):
        out = cm.plan(PINS, REVISIONS, ["plv8-build", "postgis-build"], SHA)
        self.assertEqual([m["pg"] for m in out["majors"]], ["16", "17"])
        v16, v17 = out["majors"]
        self.assertEqual(v16, {"pg": "16", "pg_version": "v16", "debian": "bullseye", "minor": "16.9",
                               "beta": False, "tags": ["16.9-0123456789ab", "edge"]})
        self.assertEqual(v17["debian"], "bookworm")
        self.assertEqual(v17["tags"], ["17.5-0123456789ab", "edge"])
        self.assertEqual(len(out["heavy"]), 4)
        self.assertIn({"pg": "17", "pg_version": "v17", "debian": "bookworm", "stage": "postgis-build"},
                      out["heavy"])

    def test_beta_major_is_tagged_beta(self):
        pins = PINS.replace("beta = []", "beta = [19]")
        out = cm.plan(pins, {**REVISIONS, "v19": ["19.0", "deadbeef"]}, [], SHA)
        v19 = out["majors"][-1]
        self.assertTrue(v19["beta"])
        self.assertEqual(v19["tags"], ["19.0-beta-0123456789ab", "beta"])
        self.assertEqual(v19["debian"], "bookworm")

    def test_major_without_a_tree_fails(self):
        with self.assertRaises(LookupError):
            cm.plan(PINS.replace("supported = [17]", "supported = [17, 18]"), REVISIONS, [], SHA)

    def test_short_sha_refused(self):
        with self.assertRaises(ValueError):
            cm.plan(PINS, REVISIONS, [], "0123456")

    def test_heavy_stage_file(self):
        self.assertEqual(cm.heavy_stages("# comment\nplv8-build\n\n  rdkit-build \n"), ["plv8-build", "rdkit-build"])

    def test_listed_heavy_stages_exist(self):
        dockerfile = (HERE.parents[2] / "compute" / "compute-node.Dockerfile").read_text()
        stages = cm.heavy_stages((HERE.parent / "compute-heavy-stages.txt").read_text())
        self.assertTrue(stages)
        for s in stages:
            self.assertRegex(dockerfile, rf"(?m)^FROM \S+ AS {s}$")

    def test_cli_prints_github_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            pins, rev = Path(tmp) / "pins.toml", Path(tmp) / "revisions.json"
            pins.write_text(PINS)
            rev.write_text(json.dumps(REVISIONS))
            r = subprocess.run([sys.executable, "-I", str(SCRIPT), "--pins", str(pins), "--revisions", str(rev),
                                "--sha", SHA], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = dict(l.split("=", 1) for l in r.stdout.splitlines())
        self.assertEqual([m["pg"] for m in json.loads(lines["majors"])], ["16", "17"])
        self.assertTrue(json.loads(lines["heavy"]))


if __name__ == "__main__":
    unittest.main()
