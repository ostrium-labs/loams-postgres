#!/usr/bin/env python3
"""Tests for scripts/loams/storage-majors.py (LP-0055, NF2 Task 8), with a stub
`docker` that answers from a fixture image (no registry, no daemon).

    storage_image_has_v18   /usr/local/v18/bin/postgres --version is 18.x, and v18
                            is in /usr/share/doc/loams-postgres/POSTGRES_VERSIONS
    a major missing from the image, a binary of the wrong major, or a list that
    differs from the build's all fail

Run: python3 -I scripts/loams/tests/test_storage_majors.py
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "storage-majors.py"

# The stub reads $STUB_IMAGE: {"/path/to/file": "contents", "/usr/local/vN/bin/postgres": "<version line>"}
STUB = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
assert args[:2] == ["run", "--rm"], args
image = json.load(open(os.environ["STUB_IMAGE"]))
entry = args[args.index("--entrypoint") + 1]
rest = args[args.index("--entrypoint") + 3:]
if entry == "cat":
    for f in rest:
        if f not in image:
            print(f"cat: {f}: No such file or directory", file=sys.stderr); sys.exit(1)
        sys.stdout.write(image[f])
    sys.exit(0)
if entry not in image:
    print(f"exec: {entry}: no such file", file=sys.stderr); sys.exit(127)
assert rest == ["--version"], rest
print(image[entry]); sys.exit(0)
'''


def image(versions, binaries=None):
    files = {"/usr/share/doc/loams-postgres/POSTGRES_VERSIONS": " ".join(versions) + "\n"}
    for v in (binaries if binaries is not None else versions):
        n = v[1:]
        files[f"/usr/local/{v}/bin/postgres"] = f"postgres (PostgreSQL) {n}.{6 if n == '18' else 11}"
    return files


class StorageMajors(unittest.TestCase):
    def run_check(self, files, versions):
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "docker"
            stub.write_text(STUB)
            stub.chmod(0o755)
            fixture = Path(tmp) / "image.json"
            fixture.write_text(json.dumps(files))
            env = {**os.environ, "STUB_IMAGE": str(fixture), "DOCKER": str(stub)}
            return subprocess.run([sys.executable, "-I", str(SCRIPT), "registry.example/storage@sha256:" + "0" * 64,
                                   versions], capture_output=True, text=True, env=env)

    def test_storage_image_has_v18(self):
        r = self.run_check(image(["v18", "v17", "v16", "v15", "v14"]), "v18 v17 v16 v15 v14")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("v18: postgres (PostgreSQL) 18.6", r.stdout)

    def test_today_16_and_17(self):
        r = self.run_check(image(["v17", "v16", "v15", "v14"]), "v17 v16 v15 v14")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_missing_v18_fails(self):
        r = self.run_check(image(["v18", "v17"], binaries=["v17"]), "v18 v17")
        self.assertEqual(r.returncode, 1)
        self.assertIn("v18", r.stderr)

    def test_wrong_major_fails(self):
        files = image(["v18", "v17"])
        files["/usr/local/v18/bin/postgres"] = "postgres (PostgreSQL) 17.11"
        r = self.run_check(files, "v18 v17")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not 18", r.stderr)

    def test_list_differs_from_the_build_fails(self):
        r = self.run_check(image(["v17", "v16"]), "v18 v17 v16")
        self.assertEqual(r.returncode, 1)
        self.assertIn("POSTGRES_VERSIONS", r.stderr)

    def test_usage(self):
        r = subprocess.run([sys.executable, "-I", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        r = self.run_check(image(["v17"]), "17")
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
