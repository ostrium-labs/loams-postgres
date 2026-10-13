#!/usr/bin/env python3
"""Tests for scripts/loams/release-notes.py (LP-0013, NF1 Task 13).

    release_tag_immutable        an existing or malformed lp- tag is refused
    notes_list_digests_and_patches  the notes name every digest, the Postgres minors,
                                 and the patches added and dropped since the last release
    pin_pr_matches_release       the pin document carries exactly the release's digests,
                                 in the schema Loams' pins.py reads

Run: python3 -I scripts/loams/tests/test_release.py
"""

import importlib.util
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "release-notes.py"
spec = importlib.util.spec_from_file_location("release_notes", SCRIPT)
rn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rn)

SHA = "0123456789abcdef0123456789abcdef01234567"
D = {n: "sha256:" + c * 64 for n, c in (("storage", "1"), ("16", "2"), ("17", "3"))}
REVISIONS = {"v17": ["17.5", "1e01fcea"], "v16": ["16.9", "a42351fc"], "v15": ["15.13", "x"], "v14": ["14.18", "y"]}
LOAMS_PINS = """# Written by scripts/nf1/pins.py (set); checked by pins.py (check). Do not edit by hand.
schema = 1
fork_release = "mirror-77e22e4b"
fork_commit = "77e22e4bf09d88b70b4a83a38c2f6de6301816b4"

[majors]
supported = [17]
beta = []
maintenance = [16]
default = 17

[images.storage]
repository = "ghcr.io/neondatabase/neon"
digest = "sha256:7a4f124917bb929964b2d696d710f19584f80bb9bd51b2af4a6e2425434c761f"
source = "mirror:ghcr.io/neondatabase/neon@sha256:7a4f124917bb929964b2d696d710f19584f80bb9bd51b2af4a6e2425434c761f"
pg_minors = { "16" = "16.9", "17" = "17.5" }

[images.compute-v16]
repository = "ghcr.io/neondatabase/compute-node-v16"
digest = "sha256:b3e151661bd2ee11eb2843c8926001966cb23969227e9673c5f42fc3fbe14249"
source = "mirror:ghcr.io/neondatabase/compute-node-v16@sha256:b3e151661bd2ee11eb2843c8926001966cb23969227e9673c5f42fc3fbe14249"
pg_minor = "16.9"

[images.compute-v17]
repository = "ghcr.io/neondatabase/compute-node-v17"
digest = "sha256:13ab146d3e7bbabb25a8532f315ac443e7512351d1ede0bab586def5c70e26c3"
source = "mirror:ghcr.io/neondatabase/compute-node-v17@sha256:13ab146d3e7bbabb25a8532f315ac443e7512351d1ede0bab586def5c70e26c3"
pg_minor = "17.5"
"""
PATCHES_PREV = """## Patches

| Id | Title | Area | Owner | Since | Origin | Drop when |
|---|---|---|---|---|---|---|
| LP-0000 | Governance | ci | @a | 2026-10-11 | loams-only | never |
| LP-0004 | No private Data API | build | @a | 2026-10-13 | loams-only | never |
| LP-0099 | An old workaround | build | @a | 2026-10-01 | upstreamable | fixed |

## Commits without a trailer
"""
PATCHES_NOW = """## Patches

| Id | Title | Area | Owner | Since | Origin | Drop when |
|---|---|---|---|---|---|---|
| LP-0000 | Governance | ci | @a | 2026-10-11 | loams-only | never |
| LP-0004 | No private Data API | build | @a | 2026-10-13 | loams-only | never |
| LP-0032 | Least privilege for spec roles | compute | @a | 2026-10-12 | loams-only | never |

## Commits without a trailer
"""


class Tag(unittest.TestCase):
    def test_release_tag_immutable(self):
        rn.check_tag("lp-2026.10.0", ["lp-2026.09.3", "loams-20261013-1"])
        with self.assertRaises(rn.Refused):
            rn.check_tag("lp-2026.10.0", ["lp-2026.10.0"])
        for bad in ("lp-2026.10", "v2026.10.0", "lp-2026.1.0", "lp-2026.10.0-rc1", "lp-26.10.0"):
            with self.assertRaises(rn.Refused):
                rn.check_tag(bad, [])

    def test_previous_release(self):
        tags = ["lp-2026.10.0", "lp-2026.10.10", "lp-2026.10.2", "lp-2026.11.0", "loams-20261013-1"]
        self.assertEqual(rn.previous_release("lp-2026.11.1", tags), "lp-2026.11.0")
        self.assertEqual(rn.previous_release("lp-2026.11.0", tags), "lp-2026.10.10")
        self.assertIsNone(rn.previous_release("lp-2026.10.0", tags))


class PinDocument(unittest.TestCase):
    def doc(self, kind="full", **kw):
        args = dict(version="lp-2026.10.0", commit=SHA, loams_pins=LOAMS_PINS, revisions=REVISIONS,
                    storage=D["storage"], compute={"16": D["16"], "17": D["17"]})
        if kind == "storage":
            args["compute"] = {}
        if kind == "compute":
            args["storage"] = None
        args.update(kw)
        return tomllib.loads(rn.pin_document(**args))

    def test_pin_pr_matches_release(self):
        doc = self.doc()
        self.assertEqual(doc["schema"], 1)
        self.assertEqual(doc["fork_release"], "lp-2026.10.0")
        self.assertEqual(doc["fork_commit"], SHA)
        self.assertEqual(doc["majors"], {"supported": [17], "beta": [], "maintenance": [16], "default": 17})
        img = doc["images"]
        self.assertEqual(img["storage"], {
            "repository": "ghcr.io/ostrium-labs/loams-postgres-storage", "digest": D["storage"],
            "source": f"ostrium-labs/loams-postgres@{SHA}", "pg_minors": {"16": "16.9", "17": "17.5"}})
        self.assertEqual(img["compute-v17"]["repository"], "ghcr.io/ostrium-labs/loams-postgres-compute-v17")
        self.assertEqual(img["compute-v17"]["digest"], D["17"])
        self.assertEqual(img["compute-v16"]["pg_minor"], "16.9")
        notes = rn.notes(version="lp-2026.10.0", commit=SHA, pin_doc=doc, previous=None,
                         patches_prev="", patches_now=PATCHES_NOW, extensions=None)
        for d in D.values():
            self.assertIn(d, notes)  # the PR (generated from the doc) and the notes agree

    def test_partial_release_keeps_the_other_pins(self):
        doc = self.doc("storage")
        self.assertEqual(doc["images"]["storage"]["digest"], D["storage"])
        self.assertEqual(doc["images"]["compute-v17"]["repository"], "ghcr.io/neondatabase/compute-node-v17")
        doc = self.doc("compute")
        self.assertEqual(doc["images"]["storage"]["repository"], "ghcr.io/neondatabase/neon")
        self.assertEqual(doc["images"]["compute-v16"]["digest"], D["16"])

    def test_partial_release_with_a_new_minor_is_refused(self):
        with self.assertRaises(rn.Refused):
            self.doc("compute", revisions={**REVISIONS, "v17": ["17.6", "abc"]})

    def test_a_major_without_its_compute_digest_is_refused(self):
        with self.assertRaises(rn.Refused):
            self.doc(compute={"17": D["17"]})


class Notes(unittest.TestCase):
    def test_notes_list_digests_and_patches(self):
        doc = tomllib.loads(rn.pin_document(version="lp-2026.11.0", commit=SHA, loams_pins=LOAMS_PINS,
                                            revisions=REVISIONS, storage=D["storage"],
                                            compute={"16": D["16"], "17": D["17"]}))
        text = rn.notes(version="lp-2026.11.0", commit=SHA, pin_doc=doc, previous="lp-2026.10.0",
                        patches_prev=PATCHES_PREV, patches_now=PATCHES_NOW, extensions=None)
        self.assertIn("# Loams Postgres lp-2026.11.0", text)
        self.assertIn(f"ghcr.io/ostrium-labs/loams-postgres-storage@{D['storage']}", text)
        self.assertIn(f"ghcr.io/ostrium-labs/loams-postgres-compute-v16@{D['16']}", text)
        self.assertIn("| 17 | 17.5 |", text)
        self.assertIn("LP-0032", text.split("### Added")[1].split("###")[0])
        self.assertIn("LP-0099", text.split("### Dropped")[1])
        self.assertNotIn("LP-0004", text.split("## Patches")[1])
        self.assertIn("since lp-2026.10.0", text)
        self.assertIn("NF1 Task 20", text)  # no manifest yet: said so, not left blank

    def test_extension_versions_from_the_manifest(self):
        manifest = """schema = 1
[[extension]]
name = "pgvector"
provides = ["vector"]
version = "0.8.1"
license = "PostgreSQL"
tier = "core"
majors = [16, 17]
[[extension]]
name = "pg_duckdb"
version = "0.3.1"
license = "MIT"
tier = "dropped"
majors = [16, 17]
"""
        doc = tomllib.loads(rn.pin_document(version="lp-2026.11.0", commit=SHA, loams_pins=LOAMS_PINS,
                                            revisions=REVISIONS, storage=D["storage"],
                                            compute={"16": D["16"], "17": D["17"]}))
        text = rn.notes(version="lp-2026.11.0", commit=SHA, pin_doc=doc, previous=None,
                        patches_prev="", patches_now=PATCHES_NOW, extensions=manifest)
        self.assertIn("| pgvector | 0.8.1 | core | PostgreSQL | 16, 17 |", text)
        self.assertNotIn("pg_duckdb", text)

    def test_cli_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "pins.toml").write_text(LOAMS_PINS)
            (t / "rev.json").write_text('{"v16": ["16.9", "a"], "v17": ["17.5", "b"]}')
            (t / "now.md").write_text(PATCHES_NOW)
            r = subprocess.run([sys.executable, "-I", str(SCRIPT), "pin-doc", "--version", "lp-2026.10.0",
                                "--commit", SHA, "--loams-pins", str(t / "pins.toml"), "--revisions",
                                str(t / "rev.json"), "--storage", D["storage"], "--compute", f"16={D['16']}",
                                "--compute", f"17={D['17']}"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            (t / "doc.toml").write_text(r.stdout)
            r = subprocess.run([sys.executable, "-I", str(SCRIPT), "notes", "--version", "lp-2026.10.0",
                                "--commit", SHA, "--pin-doc", str(t / "doc.toml"), "--patches-now",
                                str(t / "now.md")], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(D["17"], r.stdout)
            r = subprocess.run([sys.executable, "-I", str(SCRIPT), "check-tag", "--version", "lp-2026.10.0",
                                "--tag", "lp-2026.10.0"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
