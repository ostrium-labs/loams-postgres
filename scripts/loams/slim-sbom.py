#!/usr/bin/env python3
"""Shrink an SPDX JSON SBOM to its packages, for actions/attest-sbom (LP-0012).

    slim-sbom.py <in.spdx.json> <out.spdx.json>

attest-sbom refuses an SBOM over 16 MiB, and Syft's SBOM of a build or storage
image is larger: most of it is CPE guesses (externalRefs of type cpe23Type),
the image's files and the relationships to them. What Loams verifies
(scripts/nf1/verify_pins.py) is each package's name, version, licences and
purl, so this keeps every package with its purls and licences and drops the
CPEs, the files and every relationship that names a file. It fails when the
result is still over the limit.
"""

import json
import sys

LIMIT = 16 * 1024 * 1024


def slim(doc):
    files = {f.get("SPDXID") for f in doc.get("files", [])}
    for pkg in doc.get("packages", []):
        refs = [r for r in pkg.get("externalRefs", []) if r.get("referenceType") != "cpe23Type"]
        if refs:
            pkg["externalRefs"] = refs
        else:
            pkg.pop("externalRefs", None)
        pkg.pop("hasFiles", None)
    doc.pop("files", None)
    doc["relationships"] = [r for r in doc.get("relationships", [])
                            if r.get("spdxElementId") not in files and r.get("relatedSpdxElement") not in files]
    return doc


def main(argv):
    if len(argv) != 3:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    with open(argv[1]) as fh:
        doc = slim(json.load(fh))
    data = json.dumps(doc, separators=(",", ":"))
    if len(data) > LIMIT:
        print(f"slim-sbom: still {len(data)} bytes, over {LIMIT}", file=sys.stderr)
        return 1
    with open(argv[2], "w") as fh:
        fh.write(data)
    print(f"slim-sbom: {len(doc.get('packages', []))} packages, {len(data)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
