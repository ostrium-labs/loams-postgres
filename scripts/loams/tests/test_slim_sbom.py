#!/usr/bin/env python3
"""Tests for scripts/loams/slim-sbom.py (LP-0012).

Run: python3 -I scripts/loams/tests/test_slim_sbom.py
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "slim-sbom.py"
spec = importlib.util.spec_from_file_location("slim_sbom", SCRIPT)
ss = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ss)

DOC = {
    "spdxVersion": "SPDX-2.3", "documentNamespace": "https://example.test/x",
    "packages": [
        {"SPDXID": "SPDXRef-p1", "name": "tokio", "versionInfo": "1.0", "licenseDeclared": "MIT",
         "hasFiles": ["SPDXRef-f1"],
         "externalRefs": [{"referenceType": "cpe23Type", "referenceLocator": "cpe:2.3:a:tokio:tokio:1.0"},
                          {"referenceType": "purl", "referenceLocator": "pkg:cargo/tokio@1.0"}]},
        {"SPDXID": "SPDXRef-p2", "name": "libc6", "licenseDeclared": "NOASSERTION",
         "externalRefs": [{"referenceType": "cpe23Type", "referenceLocator": "cpe:2.3:a:libc6"}]},
    ],
    "files": [{"SPDXID": "SPDXRef-f1", "fileName": "/usr/bin/x"}],
    "relationships": [
        {"spdxElementId": "SPDXRef-p1", "relationshipType": "CONTAINS", "relatedSpdxElement": "SPDXRef-f1"},
        {"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES", "relatedSpdxElement": "SPDXRef-p1"},
    ],
}


class Slim(unittest.TestCase):
    def test_keeps_packages_licences_and_purls(self):
        out = ss.slim(json.loads(json.dumps(DOC)))
        self.assertNotIn("files", out)
        self.assertEqual([p["name"] for p in out["packages"]], ["tokio", "libc6"])
        self.assertEqual(out["packages"][0]["externalRefs"],
                         [{"referenceType": "purl", "referenceLocator": "pkg:cargo/tokio@1.0"}])
        self.assertNotIn("externalRefs", out["packages"][1])
        self.assertNotIn("hasFiles", out["packages"][0])
        self.assertEqual(out["packages"][0]["licenseDeclared"], "MIT")
        self.assertEqual(out["relationships"], [DOC["relationships"][1]])
        self.assertEqual(out["documentNamespace"], DOC["documentNamespace"])

    def test_cli_and_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "in.json", Path(tmp) / "out.json"
            src.write_text(json.dumps(DOC))
            r = subprocess.run([sys.executable, "-I", str(SCRIPT), str(src), str(dst)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("2 packages", r.stdout)
            big = dict(DOC, packages=[{"name": "x" * 1024, "licenseDeclared": "MIT"}] * (17 * 1024))
            src.write_text(json.dumps(big))
            r = subprocess.run([sys.executable, "-I", str(SCRIPT), str(src), str(dst)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
