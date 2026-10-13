#!/usr/bin/env python3
"""The storage image's build context holds the whole Cargo workspace (LP-0010).

.dockerignore is an allowlist (`*`, then `!<path>`). The Dockerfile runs
`cargo chef prepare` and `cargo auditable build` on what it lets through, so
every workspace member and every file the Dockerfile copies by name must be in
it: a member left out (as `fuzz/` was) breaks the image build, not the local one.

    docker_context_has_workspace   cargo metadata --locked --offline succeeds on the context
    docker_context_has_doc_files   LICENSE, NOTICE, LOAMS_PATCHES.md, about.toml, about.hbs

Run: python3 -I scripts/loams/tests/test_docker_context.py
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parents[3]
DOC_FILES = ["LICENSE", "NOTICE", "LOAMS_PATCHES.md", "about.toml", "about.hbs"]


def allowlist():
    """The `!` patterns of .dockerignore, which must start with `*`."""
    lines = [l.strip() for l in (REPO / ".dockerignore").read_text().splitlines()]
    lines = [l for l in lines if l and not l.startswith("#")]
    if lines[0] != "*" or not all(l.startswith("!") for l in lines[1:]):
        raise AssertionError(f".dockerignore is not `*` plus `!` lines: {lines}")
    return [l[1:] for l in lines[1:]]


def allowed(path, patterns):
    p = PurePosixPath(path)
    for pat in patterns:
        if pat.endswith("/"):
            # A directory pattern (possibly with a glob in its last part).
            parts = PurePosixPath(pat.rstrip("/")).parts
            if len(p.parts) > len(parts) and all(
                PurePosixPath(a).match(b) for a, b in zip(p.parts, parts)
            ):
                return True
        elif p.match(pat) and len(p.parts) == len(PurePosixPath(pat).parts):
            return True
        elif path.startswith(pat + "/"):
            return True
    return False


def context(dest):
    patterns = allowlist()
    files = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True,
                           check=True).stdout.decode().split("\0")
    for f in files:
        if f and allowed(f, patterns) and (REPO / f).is_file():
            target = dest / f
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / f, target)


class DockerContext(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="loams-docker-context-"))
        context(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_docker_context_has_workspace(self):
        r = subprocess.run(["cargo", "metadata", "--locked", "--offline", "--no-deps",
                            "--format-version", "1"], cwd=self.tmp, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])

    def test_docker_context_has_doc_files(self):
        for f in DOC_FILES:
            self.assertTrue((self.tmp / f).is_file(), f"{f} is not in the build context")

    def test_allowlist_matching(self):
        pats = ["Cargo.toml", "libs/", "vendor/postgres-*/", "build-tools/patches"]
        self.assertTrue(allowed("Cargo.toml", pats))
        self.assertFalse(allowed("proxy/Cargo.toml", pats))
        self.assertTrue(allowed("libs/utils/src/lib.rs", pats))
        self.assertTrue(allowed("vendor/postgres-v17/configure", pats))
        self.assertFalse(allowed("vendor/revisions.json", pats))
        self.assertTrue(allowed("build-tools/patches/x.patch", pats))
        self.assertFalse(allowed("build-tools/Dockerfile", pats))


if __name__ == "__main__":
    unittest.main()
