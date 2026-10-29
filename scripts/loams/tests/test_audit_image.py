#!/usr/bin/env python3
"""Tests for scripts/loams/audit-image.sh and audit_image.py (LP-0010).

Vendored from ostrium-labs/loams scripts/nf1/tests/test_mirror.py (NF1 Task 1):
the audit tests, unchanged. They need `rust-audit-info` and `objcopy`.

Run: python3 -I scripts/loams/tests/test_audit_image.py
"""

import gzip
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOAMS = HERE.parent
AUDIT = LOAMS / "audit-image.sh"
AUDIT_PY = LOAMS / "audit_image.py"


def run(*args, env=None, **kw):
    full_env = dict(os.environ)
    full_env.update(env or {})
    return subprocess.run(
        [str(a) for a in args], capture_output=True, text=True, env=full_env, **kw
    )


def sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class Usage(unittest.TestCase):
    def test_audit_refuses_unpinned_source(self):
        r = run(AUDIT, "ghcr.io/neondatabase/neon:latest", env={"SKOPEO": "false"})
        self.assertEqual(r.returncode, 2, r.stderr)



def dep_v0(packages) -> bytes:
    return zlib.compress(json.dumps({"packages": packages}).encode())


def pkg(name, version, source="crates.io", root=False):
    p = {"name": name, "version": version, "source": source, "kind": "runtime"}
    if root:
        p["root"] = True
    return p


@unittest.skipUnless(shutil.which("rust-audit-info") and shutil.which("objcopy"),
                     "needs rust-audit-info and objcopy")
class Audit(unittest.TestCase):
    """audit_flags_cddl, audit_flags_subzero: fixture `.dep-v0` payloads in a
    skopeo `dir:` image, scanned by audit_image.py."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nf1-audit-"))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def elf(self, name, packages) -> bytes:
        payload = self.tmp / f"{name}.dep-v0"
        payload.write_bytes(dep_v0(packages))
        out = self.tmp / name
        shutil.copy(shutil.which("true"), out)
        r = run("objcopy", "--add-section", f".dep-v0={payload}", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        return out.read_bytes()

    def image_dir(self, files: dict, arch="amd64") -> Path:
        d = self.tmp / f"img-{arch}"
        d.mkdir()
        layers = []
        for path, data in files.items():
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as tar:
                info = tarfile.TarInfo(path)
                info.size = len(data)
                info.mode = 0o755
                tar.addfile(info, io.BytesIO(data))
            gz = gzip.compress(buf.getvalue(), mtime=0)
            digest = sha256(gz)
            (d / digest.split(":")[1]).write_bytes(gz)
            layers.append({"mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                           "digest": digest, "size": len(gz)})
        (d / "manifest.json").write_text(json.dumps({"schemaVersion": 2, "layers": layers}))
        return d

    def audit(self, d: Path, licences=None, arch="amd64"):
        lic = self.tmp / "licences.json"
        lic.write_text(json.dumps(licences or {}))
        r = run(sys.executable, "-I", AUDIT_PY, "--offline", "--licences", lic,
                f"linux/{arch}={d}")
        out = json.loads(r.stdout) if r.stdout.strip() else None
        return r, out

    def test_clean_image_passes(self):
        d = self.image_dir({
            "usr/local/bin/pageserver": self.elf("pageserver", [pkg("pageserver", "0.1.0", "local", True),
                                                                pkg("anyhow", "1.0.98")]),
            "etc/motd": b"not an elf\n",
        })
        r, out = self.audit(d, {"anyhow@1.0.98": "MIT OR Apache-2.0"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(list(out), ["linux/amd64:/usr/local/bin/pageserver"])
        self.assertIn({"name": "anyhow", "version": "1.0.98", "source": "crates.io"},
                      out["linux/amd64:/usr/local/bin/pageserver"])

    def test_audit_flags_cddl(self):
        # inferno by name, even without a licence lookup ...
        d = self.image_dir({"usr/local/bin/pageserver": self.elf(
            "pageserver", [pkg("pageserver", "0.1.0", "local", True), pkg("inferno", "0.11.21")])})
        r, out = self.audit(d)
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("inferno 0.11.21", r.stderr)
        self.assertIn("linux/amd64:/usr/local/bin/pageserver", out)

    def test_audit_flags_cddl_by_licence(self):
        # ... and any crate whose crates.io licence is CDDL.
        d = self.image_dir({"usr/local/bin/proxy": self.elf(
            "proxy", [pkg("proxy", "0.1.0", "local", True), pkg("somecrate", "1.2.3")])})
        r, _ = self.audit(d, {"somecrate@1.2.3": "CDDL-1.0 OR MIT"})
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("somecrate 1.2.3", r.stderr)
        self.assertIn("CDDL", r.stderr)

    def test_audit_flags_subzero(self):
        d = self.image_dir({"usr/local/bin/proxy": self.elf(
            "proxy", [pkg("proxy", "0.1.0", "local", True), pkg("subzero-core", "3.0.1", "git")])})
        r, _ = self.audit(d)
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("subzero-core", r.stderr)

    def test_subzero_stub_is_not_a_finding(self):
        # Neon's public build links a path stub of subzero-core, not the private crate.
        d = self.image_dir({"usr/local/bin/proxy": self.elf(
            "proxy", [pkg("proxy", "0.1.0", "local", True), pkg("subzero-core", "3.0.1", "local")])})
        r, _ = self.audit(d)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_audit_flags_cddl_without_dep_v0(self):
        # Neon's compute image builds local_proxy with plain `cargo build`: no .dep-v0.
        # The crate source paths left in the binary still name inferno.
        path = (b"\0/root/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/"
                b"inferno-0.11.21/src/flamegraph/mod.rs\0"
                b"/root/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/anyhow-1.0.98/src/lib.rs\0")
        elf = Path(shutil.which("true")).read_bytes() + path
        d = self.image_dir({"usr/local/bin/local_proxy": elf})
        r, out = self.audit(d)
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("inferno 0.11.21", r.stderr)
        self.assertIn({"name": "inferno", "version": "0.11.21", "source": "crates.io",
                       "evidence": "strings"}, out["linux/amd64:/usr/local/bin/local_proxy"])

    def test_audit_flags_subzero_checkout_without_dep_v0(self):
        elf = Path(shutil.which("true")).read_bytes() + (
            b"\0/root/.cargo/git/checkouts/subzero-0123456789abcdef/3962646/core/src/lib.rs\0")
        d = self.image_dir({"usr/local/bin/proxy": elf})
        r, _ = self.audit(d)
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("subzero", r.stderr)

    def test_whiteout_removes_a_binary(self):
        bad = self.elf("old", [pkg("old", "0.1.0", "local", True), pkg("inferno", "0.11.21")])
        d = self.image_dir({"usr/bin/old": bad, "usr/bin/.wh.old": b""})
        r, out = self.audit(d)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(out, {})



if __name__ == "__main__":
    unittest.main()
