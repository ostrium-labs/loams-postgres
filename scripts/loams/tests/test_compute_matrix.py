#!/usr/bin/env python3
"""Tests for scripts/loams/compute-matrix.py (LP-0011, NF1 Task 11; LP-0055, NF2 Task 8).

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
V18 = {"v18": ["18.6", "724edf9b"]}
BUILT = {14, 15, 16, 17}
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
        self.assertEqual(v16, {"pg": "16", "pg_version": "v16", "debian": "bookworm", "minor": "16.9",
                               "beta": False, "tags": ["16.9-0123456789ab", "edge"], "extensions": "all"})
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
        self.assertEqual(v19["debian"], "trixie")

    # NF2 Task 8: 18 is opt-in until vendor/postgres-v18 and pgxn/neon at 18 land.
    def test_beta_18_skipped_until_vendored(self):
        out = cm.plan(PINS.replace("beta = []", "beta = [18]"), REVISIONS, ["plv8-build"], SHA, BUILT)
        self.assertEqual([m["pg"] for m in out["majors"]], ["16", "17"])
        self.assertEqual([s["pg"] for s in out["skipped"]], ["18"])
        self.assertIn("vendor/revisions.json", out["skipped"][0]["reason"])
        self.assertNotIn("v18", {h["pg_version"] for h in out["heavy"]})

    def test_beta_18_skipped_until_the_fork_builds_it(self):
        out = cm.plan(PINS.replace("beta = []", "beta = [18]"), {**REVISIONS, **V18}, [], SHA, BUILT)
        self.assertEqual([m["pg"] for m in out["majors"]], ["16", "17"])
        self.assertIn("POSTGRES_VERSIONS", out["skipped"][0]["reason"])

    def test_beta_18_built_on_trixie(self):
        out = cm.plan(PINS.replace("beta = []", "beta = [18]"), {**REVISIONS, **V18}, ["plv8-build"], SHA,
                      BUILT | {18})
        v18 = out["majors"][-1]
        self.assertEqual(v18, {"pg": "18", "pg_version": "v18", "debian": "trixie", "minor": "18.6",
                               "beta": True, "tags": ["18.6-beta-0123456789ab", "beta"], "extensions": "all"})
        self.assertIn({"pg": "18", "pg_version": "v18", "debian": "trixie", "stage": "plv8-build"}, out["heavy"])
        self.assertEqual(out["skipped"], [])
        # 16 and 17 stay on bookworm: their collations must not change under existing databases.
        self.assertEqual({m["debian"] for m in out["majors"][:2]}, {"bookworm"})

    def test_extra_major_is_opt_in_and_beta(self):
        out = cm.plan(PINS, {**REVISIONS, **V18}, [], SHA, BUILT, extra={18})
        v18 = out["majors"][-1]
        self.assertEqual((v18["pg"], v18["beta"], v18["tags"][-1]), ("18", True, "beta"))

    def test_extra_major_without_a_tree_fails(self):
        with self.assertRaises(LookupError):
            cm.plan(PINS, REVISIONS, [], SHA, BUILT, extra={18})

    def test_supported_major_the_fork_does_not_build_fails(self):
        with self.assertRaises(LookupError):
            cm.plan(PINS, REVISIONS, [], SHA, {16})

    def test_supported_18_is_not_beta(self):
        pins = PINS.replace("supported = [17]", "supported = [17, 18]")
        out = cm.plan(pins, {**REVISIONS, **V18}, [], SHA, BUILT | {18})
        self.assertEqual(out["majors"][-1]["tags"], ["18.6-0123456789ab", "edge"])

    # NF2 Task 8: a new major builds the extensions ported to it so far
    # (`extensions-v<N>` in the Dockerfile), and only their heavy stages.
    def test_extension_subset_per_major(self):
        subsets = {18: {"postgis-build", "pgvector-build"}}
        out = cm.plan(PINS.replace("beta = []", "beta = [18]"), {**REVISIONS, **V18},
                      ["plv8-build", "postgis-build"], SHA, BUILT | {18}, subsets=subsets)
        self.assertEqual([m["extensions"] for m in out["majors"]], ["all", "all", "v18"])
        self.assertEqual([h["stage"] for h in out["heavy"] if h["pg"] == "18"], ["postgis-build"])
        self.assertEqual([h["stage"] for h in out["heavy"] if h["pg"] == "17"], ["plv8-build", "postgis-build"])

    def test_extension_subsets_from_the_dockerfile(self):
        text = """FROM build-deps AS extensions-all
COPY --from=plv8-build /usr/local/pgsql/ /usr/local/pgsql/
FROM build-deps AS extensions-v18

COPY --from=postgis-build /usr/local/pgsql/ /usr/local/pgsql/
COPY --from=postgis-build /sfcgal/* /
COPY --from=pg_cron-build /usr/local/pgsql/ /usr/local/pgsql/

FROM extensions-${EXTENSIONS} AS neon-pg-ext-build
"""
        self.assertEqual(cm.extension_subsets(text), {18: {"postgis-build", "pg_cron-build"}})

    def test_this_dockerfile_builds_18_with_core_extensions(self):
        """The v18 subset carries what the smoke's compute preloads (pg_cron, timescaledb,
        pgaudit) and none of the heavy stages that are not ported yet."""
        text = (HERE.parents[2] / "compute" / "compute-node.Dockerfile").read_text()
        subsets = cm.extension_subsets(text)
        self.assertIn(18, subsets)
        for stage in ("pg_cron-build", "timescaledb-build", "pgaudit-build", "pgvector-build", "postgis-build"):
            self.assertIn(stage, subsets[18])
        self.assertNotIn("plv8-build", subsets[18])

    def test_makefile_majors(self):
        self.assertEqual(cm.makefile_majors("X = 1\nPOSTGRES_VERSIONS = v17 v16 v15 v14\n"), {14, 15, 16, 17})
        self.assertEqual(cm.makefile_majors("POSTGRES_VERSIONS ?= v18 v17 # beta first\n"), {17, 18})
        with self.assertRaises(ValueError):
            cm.makefile_majors("POSTGRES_VERSIONS = 17\n")
        with self.assertRaises(ValueError):
            cm.makefile_majors("nothing here\n")

    def test_parse_majors(self):
        self.assertEqual(cm.parse_majors("18, v19 "), {18, 19})
        self.assertEqual(cm.parse_majors(""), set())
        with self.assertRaises(ValueError):
            cm.parse_majors("eighteen")

    def test_this_commit_keeps_18_opt_in(self):
        """No red build on main: with Loams listing 18 as beta, this commit builds 18
        only if it has the tree and the Makefile lists it; otherwise 18 is skipped."""
        root = HERE.parents[2]
        revisions = json.loads((root / "vendor" / "revisions.json").read_text())
        built = cm.makefile_majors((root / "Makefile").read_text())
        out = cm.plan(PINS.replace("beta = []", "beta = [18]"), revisions, [], SHA, built)
        if "v18" in revisions and 18 in built:
            self.assertEqual(out["majors"][-1]["debian"], "trixie")
        else:
            self.assertEqual([s["pg"] for s in out["skipped"]], ["18"])

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
        self.assertEqual(json.loads(lines["skipped"]), [])

    def test_cli_skips_beta_18_and_builds_it_by_hand(self):
        with tempfile.TemporaryDirectory() as tmp:
            pins, rev, mk = Path(tmp) / "pins.toml", Path(tmp) / "revisions.json", Path(tmp) / "Makefile"
            pins.write_text(PINS.replace("beta = []", "beta = [18]"))
            rev.write_text(json.dumps({**REVISIONS, **V18}))
            mk.write_text("POSTGRES_VERSIONS = v17 v16 v15 v14\n")
            base = [sys.executable, "-I", str(SCRIPT), "--pins", str(pins), "--revisions", str(rev),
                    "--makefile", str(mk), "--sha", SHA]
            r = subprocess.run(base, capture_output=True, text=True)
            r2 = subprocess.run(base + ["--extra-majors", "18"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = dict(l.split("=", 1) for l in r.stdout.splitlines())
        self.assertEqual([m["pg"] for m in json.loads(lines["majors"])], ["16", "17"])
        self.assertEqual([s["pg"] for s in json.loads(lines["skipped"])], ["18"])
        self.assertIn("::notice", r.stderr)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        lines = dict(l.split("=", 1) for l in r2.stdout.splitlines())
        self.assertEqual([m["pg"] for m in json.loads(lines["majors"])], ["16", "17", "18"])

    def test_image_jobs_follow_the_matrix(self):
        """compute_image_audit_clean and the smoke run per matrix major, so they run at 18
        as soon as 18 is in the matrix; the release signs (and attaches the SBOM of)
        every matrix major. No compute job names a major by hand."""
        wf = HERE.parents[2] / ".github" / "workflows"
        build = (wf / "loams-build-compute.yml").read_text()
        self.assertEqual(build.count("major: ${{ fromJSON(needs.plan.outputs.majors) }}"), 4)
        self.assertIn("compute_image_audit_clean", build)
        self.assertNotRegex(build, r"compute-v1[0-9]|pg_version: v1[0-9]|PG_VERSION=v1[0-9]")
        release = (wf / "loams-release.yml").read_text()
        self.assertIn("scripts/loams/compute-matrix.py", release)


if __name__ == "__main__":
    unittest.main()
