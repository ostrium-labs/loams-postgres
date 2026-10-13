#!/usr/bin/env python3
"""Tests for scripts/loams/compute-sources.py (LP-0012, NF1 Task 12).

Run: python3 -I scripts/loams/tests/test_compute_sources.py
"""

import importlib.util
import re
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "compute-sources.py"
DOCKERFILE = HERE.parents[2] / "compute" / "compute-node.Dockerfile"
spec = importlib.util.spec_from_file_location("compute_sources", SCRIPT)
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)


class Sources(unittest.TestCase):
    def setUp(self):
        self.text = DOCKERFILE.read_text()
        self.out = subprocess.run([sys.executable, "-I", str(SCRIPT), str(DOCKERFILE)],
                                  capture_output=True, text=True, check=True).stdout

    def test_every_src_stage_is_collected(self):
        stages = cs.src_stages(self.text)
        self.assertGreater(len(stages), 30)
        for s in ("postgis-src", "pgrouting-src", "postgresql-unit-src", "pg_session_jwt-src"):
            self.assertIn(s, stages)
        for s in stages:
            self.assertIn(f"--mount=type=bind,from={s},source=/ext-src,target=/in/{s}", self.out)

    def test_original_dockerfile_is_kept_whole(self):
        self.assertTrue(self.out.startswith(self.text))

    def test_output_stages(self):
        appended = self.out[len(self.text):]
        self.assertRegex(appended, r"(?m)^FROM build-deps AS loams-sources$")
        self.assertRegex(appended, r"(?m)^FROM scratch AS loams-sources-out$")
        self.assertIn('postgres-${PG_VERSION}.tar.gz', appended)
        self.assertIn("SHA256SUMS", appended)
        # A stage name never appears twice (the build would refuse it).
        names = re.findall(r"(?m)^FROM \S+ AS (\S+)$", self.out)
        self.assertEqual(len(names), len(set(names)))

    def test_git_sources_listed(self):
        git = cs.git_sources(self.text)
        self.assertTrue(any("github.com/plv8/plv8" in g for g in git), git)
        self.assertTrue(any("github.com/pgbouncer/pgbouncer" in g for g in git), git)

    def test_no_src_stage_is_an_error(self):
        with self.assertRaises(SystemExit):
            cs.stages("FROM debian AS build\n")


if __name__ == "__main__":
    unittest.main()
