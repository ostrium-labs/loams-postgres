#!/usr/bin/env python3
"""Check that a Postgres major's format diff classifies every item.

Design §51 §8.3 and §62 §4.1 (NF2 Task 1, LP-0034): before a major is ported,
`docs/loams/pg<N>-format-diff.md` compares the previous major's last minor with
the new one, header by header. Every table in it with a "Classification" column
lists items; each row must carry exactly one of:

    decoder, walingest, redo, compute only, none

Tables without that column (constants, notes) are not checked. Bold or code
formatting around the value is ignored. If the table has an "Id" column, ids
must be unique.

Usage:
    format-diff-check.py                 # every docs/loams/pg*-format-diff.md
    format-diff-check.py DOC [DOC ...]

Exit status: 0 when every document passes, 1 otherwise (findings on stderr).
"""

import re
import sys
from collections import Counter
from pathlib import Path

CLASSES = ("decoder", "walingest", "redo", "compute only", "none")
NAME = re.compile(r"pg\d+-format-diff\.md")
REPO = Path(__file__).resolve().parent.parent.parent
SEPARATOR = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def cells(line):
    """The cells of a Markdown table row; `|` inside code spans or escaped stays."""
    out, cur, code = [], [], False
    i = 0
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            cur.append("|")
            i += 2
            continue
        if c == "`":
            code = not code
        if c == "|" and not code:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
        i += 1
    out.append("".join(cur).strip())
    return out


def tables(lines):
    """Yield (header cells, [(line number, row cells)]) for each table."""
    i = 0
    while i < len(lines) - 1:
        if lines[i].lstrip().startswith("|") and SEPARATOR.match(lines[i + 1].strip()):
            header = cells(lines[i])
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                rows.append((j + 1, cells(lines[j])))
                j += 1
            yield header, rows
            i = j
        else:
            i += 1


def normalise(value):
    return re.sub(r"\s+", " ", value.replace("*", "").replace("`", "")).strip().lower()


def check(path):
    """(number of items, Counter of classes, [errors]) for one document."""
    errors = []
    if not NAME.fullmatch(path.name):
        errors.append(f"{path}: the file must be named pg<N>-format-diff.md")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        return 0, Counter(), [f"{path}: {e.strerror}"]
    count, classes, seen = 0, Counter(), {}
    found = False
    for header, rows in tables(lines):
        names = [normalise(h) for h in header]
        if "classification" not in names:
            continue
        found = True
        col = names.index("classification")
        idcol = names.index("id") if "id" in names else None
        for n, row in rows:
            label = row[idcol] if idcol is not None and idcol < len(row) and row[idcol] else f"line {n}"
            at = f"{path.name}:{n} ({label})"
            if len(row) != len(header):
                errors.append(f"{at}: {len(row)} cells, the table has {len(header)}")
                continue
            if idcol is not None:
                if label in seen:
                    errors.append(f"{at}: id {label} is listed twice (first at line {seen[label]})")
                seen[label] = n
            value = normalise(row[col])
            if not value:
                errors.append(f"{at}: no classification")
            elif value not in CLASSES:
                errors.append(
                    f"{at}: classification '{row[col]}' is not exactly one of {', '.join(CLASSES)}"
                )
            else:
                classes[value] += 1
            count += 1
    if not found:
        errors.append(f"{path}: no table with a Classification column")
    return count, classes, errors


def main(argv):
    if argv:
        docs = [Path(a) for a in argv]
    else:
        docs = sorted((REPO / "docs" / "loams").glob("pg*-format-diff.md"))
        if not docs:
            print("format-diff-check: no docs/loams/pg*-format-diff.md found", file=sys.stderr)
            return 1
    failed = False
    for doc in docs:
        count, classes, errors = check(doc)
        for e in errors:
            print(e, file=sys.stderr)
        if errors:
            failed = True
            continue
        summary = ", ".join(f"{c} {classes[c]}" for c in CLASSES if classes[c])
        print(f"{doc.name}: {count} items classified ({summary})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
