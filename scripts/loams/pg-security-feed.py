#!/usr/bin/env python3
"""Find Postgres security minors for the majors Loams Postgres supports or maintains.

    pg-security-feed.py --pins <loams-postgres-images.toml> [--feed <url|path>]
                        [--notes-dir <dir>] [--out <findings.json>]

It reads postgresql.org's release feed (default
https://www.postgresql.org/versions.rss: the latest minor of every major, with
its release date), keeps the majors listed as `supported` or `maintenance` in
Loams' pin file (beta majors are not tracked), and reads each release's notes.
A release whose notes name a CVE is a security minor. Releases of one day make
one finding, keyed `pg-release:<date>`, severity `pg-minor`, starting at the
release date: images must be published within 7 days of it (design §51 §3.7).

The findings are written as JSON for `sla.py file --kind findings` (stdout
without --out). --notes-dir reads release notes from <dir>/<file name of the
notes URL> instead of the network (tests, offline runs). Only https URLs are
fetched; anything else exits 2. Standard library only.
"""

import argparse
import datetime as dt
import email.utils
import json
import re
import sys
import tomllib
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sla  # noqa: E402

FEED = "https://www.postgresql.org/versions.rss"
NOTES_PREFIX = "https://www.postgresql.org/docs/"
CVE = re.compile(r"CVE-\d{4}-\d{4,}")
VERSION = re.compile(r"^(\d{2,})\.(\d+)$")


class Usage(Exception):
    pass


def tracked_majors(pins_text):
    """{major: pinned minor} for the supported and maintenance majors of the pin file."""
    pins = tomllib.loads(pins_text)
    majors = pins.get("majors", {})
    images = pins.get("images", {})
    minors = images.get("storage", {}).get("pg_minors", {})
    out = {}
    for major in [*majors.get("supported", []), *majors.get("maintenance", [])]:
        compute = images.get(f"compute-v{major}", {})
        out[major] = minors.get(str(major)) or compute.get("pg_minor") or "unknown"
    return out


def releases(feed_xml):
    """The feed's items whose title is a version of a major from 10 on."""
    out = []
    for item in ET.fromstring(feed_xml).iter("item"):
        version = (item.findtext("title") or "").strip()
        m = VERSION.match(version)
        if not m:
            continue
        out.append(
            {
                "version": version,
                "major": int(m.group(1)),
                "date": email.utils.parsedate_to_datetime(item.findtext("pubDate")).astimezone(dt.timezone.utc),
                "link": (item.findtext("link") or "").strip(),
            }
        )
    return out


def findings(feed_xml, pins_text, fetch):
    tracked = tracked_majors(pins_text)
    by_day = {}
    for rel in releases(feed_xml):
        if rel["major"] not in tracked:
            continue
        if not rel["link"].startswith(NOTES_PREFIX):
            raise Usage(f"unexpected release-notes link {rel['link']!r}")
        cves = sorted(set(CVE.findall(fetch(rel["link"]))))
        if cves:
            by_day.setdefault(rel["date"], []).append((rel, cves))
    out = []
    for day, rels in sorted(by_day.items()):
        rels.sort(key=lambda r: -r[0]["major"])
        versions = ", ".join(r["version"] for r, _ in rels)
        rows = [
            f"| [{r['version']}]({r['link']}) | pinned {tracked[r['major']]} | {', '.join(cves)} |"
            for r, cves in rels
        ]
        body = "\n".join(
            [
                f"postgresql.org released Postgres security minors on {day:%Y-%m-%d} for majors Loams "
                "Postgres supports or maintains (Loams' `deploy/pins/loams-postgres-images.toml`).",
                "",
                "| Release | Loams Postgres | CVEs named in the release notes |",
                "|---|---|---|",
                *rows,
                "",
                "Target: images with these minors published within 7 days of the release "
                "(design §51 §3.7): merge the minors into `loams/REL_<N>_STABLE` behind the gate, "
                "release, and update the pins.",
            ]
        )
        out.append(
            sla.Finding(
                key=f"pg-release:{day:%Y-%m-%d}",
                title=f"Postgres security minors {day:%Y-%m-%d}: {versions}",
                severity="pg-minor",
                found=day,
                body=body,
            )
        )
    return out


def read(source, notes_dir=None):
    if notes_dir is not None and source.startswith(NOTES_PREFIX):
        return (Path(notes_dir) / source.rsplit("/", 1)[1]).read_text()
    if "://" not in source:
        return Path(source).read_text()
    if not source.startswith("https://"):
        raise Usage(f"only https URLs are fetched, not {source!r}")
    req = urllib.request.Request(source, headers={"User-Agent": "loams-postgres-advisories"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--pins", required=True)
    p.add_argument("--feed", default=FEED)
    p.add_argument("--notes-dir")
    p.add_argument("--out")
    args = p.parse_args(argv)
    try:
        found = findings(read(args.feed), Path(args.pins).read_text(), lambda url: read(url, args.notes_dir))
    except Usage as e:
        print(f"pg-security-feed: {e}", file=sys.stderr)
        return 2
    text = json.dumps([f.to_json() for f in found], indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text)
    else:
        sys.stdout.write(text)
    for f in found:
        print(f"pg-security-feed: {f.key}: {f.title}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
