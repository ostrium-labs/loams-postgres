#!/usr/bin/env python3
"""NF2 Task 1: tests for scripts/loams/format-diff-check.py.

The check reads every `docs/loams/pg<N>-format-diff.md` (design §51 §8.3, §62
§4.1) and fails when a row of a classified table has no classification, or one
that is not exactly one of "decoder", "walingest", "redo", "compute only" or
"none". The fixtures are written to a scratch directory; the last test runs the
check on the repository's own documents.

Run: python3 -I scripts/loams/tests/test_format_diff.py
"""

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECK = HERE.parent / "format-diff-check.py"
REPO = HERE.parent.parent.parent

GOOD = """\
# Postgres 18 format diff

Intro text, with a table that is not classified:

| Constant | 17 | 18 |
|---|---|---|
| `XLOG_PAGE_MAGIC` | `0xD116` | `0xD118` |

## Items

| Id | Item | Change | Upstream | Classification | Where |
|---|---|---|---|---|---|
| F1 | `XLOG_PAGE_MAGIC` | 0xD116 to 0xD118 | `b14e9ce7d5` | decoder | `postgres_ffi` |
| F2 | `rmgrlist.h` | none | — | none | — |
| F3 | `xl_heap_inplace` | invals | `243e9b40f1` | **redo** | `neon_walredo` |
| F4 | `ControlFileData` | new bool | `44fe30fdab` | `walingest` | `controlfile_utils.rs` |
| F5 | `smgrstartreadv` | AIO | `50cb7505b3` | compute only | `pagestore_smgr.c` |
"""


def run(*paths):
    return subprocess.run(
        [sys.executable, "-I", str(CHECK), *map(str, paths)],
        capture_output=True,
        text=True,
    )


class FormatDiffCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def doc(self, text, name="pg18-format-diff.md"):
        path = self.dir / name
        path.write_text(textwrap.dedent(text), encoding="utf-8")
        return path

    def assertFails(self, text, *needles):
        out = run(self.doc(text))
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        for needle in needles:
            self.assertIn(needle, out.stderr)

    def test_good_document_passes(self):
        out = run(self.doc(GOOD))
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("5 items", out.stdout)

    def test_missing_classification_fails(self):
        self.assertFails(
            GOOD.replace("| `b14e9ce7d5` | decoder |", "| `b14e9ce7d5` |  |"),
            "F1",
            "no classification",
        )

    def test_unknown_classification_fails(self):
        self.assertFails(GOOD.replace("| — | none | — |", "| — | tbd | — |"), "F2", "'tbd'")

    def test_two_classifications_fail(self):
        self.assertFails(
            GOOD.replace("| **redo** |", "| decoder, redo |"), "F3", "'decoder, redo'"
        )

    def test_short_row_fails(self):
        self.assertFails(GOOD + "| F6 | `md.h` | AIO |\n", "F6")

    def test_duplicate_id_fails(self):
        self.assertFails(GOOD.replace("| F2 |", "| F1 |"), "F1", "twice")

    def test_document_without_classified_table_fails(self):
        self.assertFails("# Postgres 18 format diff\n\nNothing yet.\n", "no table")

    def test_name_must_name_a_major(self):
        out = run(self.doc(GOOD, name="format-diff.md"))
        self.assertEqual(out.returncode, 1)
        self.assertIn("pg<N>-format-diff.md", out.stderr)

    def test_no_argument_checks_every_major_in_the_repository(self):
        out = subprocess.run(
            [sys.executable, "-I", str(CHECK)], capture_output=True, text=True, cwd=REPO
        )
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("pg18-format-diff.md", out.stdout)

    def test_format_diff_has_no_unclassified_items(self):
        """The plan's named test: the repository's own diffs are fully classified."""
        docs = sorted((REPO / "docs" / "loams").glob("pg*-format-diff.md"))
        self.assertIn("pg18-format-diff.md", [d.name for d in docs])
        out = run(*docs)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
