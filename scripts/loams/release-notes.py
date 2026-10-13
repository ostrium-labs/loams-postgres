#!/usr/bin/env python3
"""Release documents for loams-release.yml (LP-0013, NF1 Task 13).

    release-notes.py check-tag --version lp-YYYY.MM.N [--tag <existing tag> ...]
    release-notes.py previous  --version lp-YYYY.MM.N [--tag <existing tag> ...]
    release-notes.py pin-doc   --version V --commit SHA --loams-pins <Loams' pin file>
                               [--revisions vendor/revisions.json] [--storage DIGEST]
                               [--compute <major>=DIGEST ...]
    release-notes.py notes     --version V --commit SHA --pin-doc <file> --patches-now LOAMS_PATCHES.md
                               [--patches-prev <file>] [--previous lp-...] [--extensions compute/loams-extensions.toml]

check-tag   refuses (exit 1) a version that is not lp-YYYY.MM.N or whose tag exists:
            a release tag is immutable (the repository's tag ruleset enforces it too).
previous    prints the latest existing lp- tag before the version, if any.
pin-doc     prints the release's pin document: Loams' pin file
            (deploy/pins/loams-postgres-images.toml, NF1 Task 2's schema) with the
            images this release built replaced by ghcr.io/ostrium-labs/loams-postgres-*
            at their digests and `source = "ostrium-labs/loams-postgres@<commit>"`,
            and the Postgres minors from vendor/revisions.json. Images the release
            did not build keep Loams' current pins; a release that would leave a
            major's storage and compute minors apart is refused (kind=full then).
            It is attached to the GitHub Release, and the pin pull request on
            ostrium-labs/loams runs `pins.py set --from-release <its URL>`.
notes       prints the release notes (Markdown): the digests, the Postgres minors,
            the extension versions (compute/loams-extensions.toml, NF1 Task 20),
            and the patches added or dropped since the previous release
            (LOAMS_PATCHES.md then and now).

Exit 0 ok, 1 refused, 2 usage. Stdlib only.
"""

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION = re.compile(r"lp-(\d{4})\.(\d{2})\.(\d+)")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
REPO = "ghcr.io/ostrium-labs/loams-postgres-"
ROW = re.compile(r"^\| (LP-\d{4}) \| (.*?) \|", re.M)


class Refused(Exception):
    pass


def _key(tag):
    m = VERSION.fullmatch(tag)
    return tuple(int(x) for x in m.groups()) if m else None


def check_tag(version, existing):
    if not VERSION.fullmatch(version):
        raise Refused(f"{version!r} is not lp-YYYY.MM.N")
    if version in existing:
        raise Refused(f"the tag {version} exists; a release tag is never moved or reused")


def previous_release(version, existing):
    mine = _key(version)
    older = [t for t in existing if _key(t) and _key(t) < mine]
    return max(older, key=_key) if older else None


# ----------------------------------------------------------- the pin document

def _q(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _render(doc):
    m = doc["majors"]
    out = [
        "# The pin document of a Loams Postgres release (scripts/loams/release-notes.py pin-doc);",
        "# ostrium-labs/loams' scripts/nf1/pins.py set --from-release reads it.",
        "schema = 1",
        f"fork_release = {_q(doc['fork_release'])}",
        f"fork_commit = {_q(doc['fork_commit'])}",
        "",
        "[majors]",
        *(f"{k} = [{', '.join(str(v) for v in m[k])}]" for k in ("supported", "beta", "maintenance")),
        f"default = {m['default']}",
    ]
    for key in sorted(doc["images"], key=lambda k: (k != "storage", k)):
        img = doc["images"][key]
        out += ["", f"[images.{key}]", f"repository = {_q(img['repository'])}", f"digest = {_q(img['digest'])}",
                f"source = {_q(img['source'])}"]
        if "pg_minors" in img:
            out.append("pg_minors = { " + ", ".join(f"{_q(k)} = {_q(v)}" for k, v in sorted(img["pg_minors"].items())) + " }")
        if "pg_minor" in img:
            out.append(f"pg_minor = {_q(img['pg_minor'])}")
    return "\n".join(out) + "\n"


def pin_document(version, commit, loams_pins, revisions, storage, compute):
    check_tag(version, [])
    if not COMMIT.fullmatch(commit):
        raise Refused(f"--commit must be 40 hex characters, got {commit!r}")
    for d in [storage, *compute.values()]:
        if d is not None and not DIGEST.fullmatch(d):
            raise Refused(f"not a digest: {d!r}")
    if storage is None and not compute:
        raise Refused("a release builds the storage image, the compute images, or both")
    current = tomllib.loads(loams_pins)
    majors = current["majors"]
    listed = sorted({int(v) for k in ("supported", "beta", "maintenance") for v in majors.get(k, [])})
    source = f"ostrium-labs/loams-postgres@{commit}"

    def minor(n):
        tree = revisions.get(f"v{n}")
        if not tree:
            raise Refused(f"Postgres {n} is pinned by Loams but has no tree in vendor/revisions.json")
        return tree[0]

    images = {k: dict(v) for k, v in current["images"].items()}
    if storage is not None:
        images["storage"] = {"repository": REPO + "storage", "digest": storage, "source": source,
                             "pg_minors": {str(n): minor(n) for n in listed}}
    if compute:
        missing = [n for n in listed if str(n) not in compute]
        if missing:
            raise Refused(f"no compute digest for Postgres {missing}; a compute release builds every pinned major")
        for n in listed:
            images[f"compute-v{n}"] = {"repository": f"{REPO}compute-v{n}", "digest": compute[str(n)],
                                       "source": source, "pg_minor": minor(n)}
    for n in listed:
        s = images["storage"].get("pg_minors", {}).get(str(n))
        c = images.get(f"compute-v{n}", {}).get("pg_minor")
        if s != c:
            raise Refused(f"Postgres {n}: the storage image has {s} and the compute image {c}; release kind=full")
    doc = {"fork_release": version, "fork_commit": commit,
           "majors": {k: majors.get(k, []) for k in ("supported", "beta", "maintenance")} | {"default": majors["default"]},
           "images": images}
    return _render(doc)


# ------------------------------------------------------------------ the notes

def patch_rows(text):
    """{id: title} of LOAMS_PATCHES.md's Patches table."""
    if not text:
        return {}
    section = text.split("## Patches", 1)[-1].split("\n## ", 1)[0]
    return dict(ROW.findall(section))


def notes(version, commit, pin_doc, previous, patches_prev, patches_now, extensions):
    images = pin_doc["images"]
    out = [f"# Loams Postgres {version}", "",
           f"Built from `ostrium-labs/loams-postgres@{commit}`. Every image below is a multi-arch "
           "index (amd64, arm64), signed with cosign (keyless) and attested (build provenance, "
           "SPDX SBOM); the compute images carry their sources "
           "(`application/vnd.loams.sources.v1`).", "", "## Images", "",
           "| Image | Digest | Source |", "|---|---|---|"]
    for key in sorted(images, key=lambda k: (k != "storage", k)):
        img = images[key]
        built = img["source"] == f"ostrium-labs/loams-postgres@{commit}"
        out.append(f"| `{key}` | `{img['repository']}@{img['digest']}` | "
                   f"{'this release' if built else 'unchanged: ' + img['source']} |")
    out += ["", "## Postgres", "", "| Major | Minor | Status |", "|---|---|---|"]
    m = pin_doc["majors"]
    status = {**{n: "maintenance" for n in m["maintenance"]}, **{n: "beta" for n in m["beta"]},
              **{n: "supported" for n in m["supported"]}}
    for n in sorted(status):
        mark = " (default)" if n == m["default"] else ""
        out.append(f"| {n} | {images['storage']['pg_minors'].get(str(n), '?')} | {status[n]}{mark} |")
    out += ["", "## Extensions", ""]
    if extensions:
        ext = [e for e in tomllib.loads(extensions).get("extension", []) if e.get("tier") != "dropped"]
        out += ["| Extension | Version | Tier | Licence | Majors |", "|---|---|---|---|---|"]
        for e in sorted(ext, key=lambda e: (e.get("tier") != "core", e["name"])):
            out.append(f"| {e['name']} | {e.get('version', '')} | {e.get('tier', '')} | {e.get('license', '')} | "
                       f"{', '.join(str(x) for x in e.get('majors', []))} |")
    else:
        out.append("The extension manifest (`compute/loams-extensions.toml`) arrives with NF1 Task 20; "
                   "until then the versions are those of `compute/compute-node.Dockerfile` at this commit.")
    prev, now = patch_rows(patches_prev), patch_rows(patches_now)
    added = {k: v for k, v in now.items() if k not in prev}
    dropped = {k: v for k, v in prev.items() if k not in now}
    out += ["", "## Patches", "",
            f"Changes from Neon are listed in `LOAMS_PATCHES.md` ({len(now)} patches); "
            + (f"since {previous}:" if previous else "this is the first release:"), "", "### Added", ""]
    out += [f"- {k}: {v}" for k, v in sorted(added.items())] or ["- none"]
    out += ["", "### Dropped", ""]
    out += [f"- {k}: {v}" for k, v in sorted(dropped.items())] or ["- none"]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------- CLI

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("check-tag", "previous"):
        s = sub.add_parser(name)
        s.add_argument("--version", required=True)
        s.add_argument("--tag", action="append", default=[])
    s = sub.add_parser("pin-doc")
    s.add_argument("--version", required=True)
    s.add_argument("--commit", required=True)
    s.add_argument("--loams-pins", required=True)
    s.add_argument("--revisions", default=str(ROOT / "vendor" / "revisions.json"))
    s.add_argument("--storage")
    s.add_argument("--compute", action="append", default=[])
    s = sub.add_parser("notes")
    s.add_argument("--version", required=True)
    s.add_argument("--commit", required=True)
    s.add_argument("--pin-doc", required=True)
    s.add_argument("--patches-now", required=True)
    s.add_argument("--patches-prev")
    s.add_argument("--previous")
    s.add_argument("--extensions")
    args = p.parse_args(argv)
    try:
        if args.cmd == "check-tag":
            check_tag(args.version, args.tag)
            print(f"{args.version}: free")
        elif args.cmd == "previous":
            print(previous_release(args.version, args.tag) or "")
        elif args.cmd == "pin-doc":
            compute = {}
            for c in args.compute:
                major, _, digest = c.partition("=")
                compute[major] = digest
            sys.stdout.write(pin_document(args.version, args.commit, Path(args.loams_pins).read_text(),
                                          json.loads(Path(args.revisions).read_text()), args.storage, compute))
        else:
            ext = Path(args.extensions).read_text() if args.extensions and Path(args.extensions).is_file() else None
            prev = Path(args.patches_prev).read_text() if args.patches_prev else ""
            sys.stdout.write(notes(args.version, args.commit, tomllib.loads(Path(args.pin_doc).read_text()),
                                   args.previous, prev, Path(args.patches_now).read_text(), ext))
    except Refused as e:
        print(f"release-notes: refused: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
