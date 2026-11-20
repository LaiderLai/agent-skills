#!/usr/bin/env python3
"""Profile a feature-list CSV and print a draft mapping for convert_csv.py.

    python3 inspect_csv.py features.csv > /tmp/opencode/mapping.draft.yaml

The draft is a starting point: every guess is marked "# guess". Review it
against the column profile printed to stderr, fix it, and confirm the
platform / milestone / marker choices with the user before converting.
"""

import argparse
import collections
import csv
import io
import re
import sys
from pathlib import Path

# Spreadsheet exports are not always UTF-8 (Excel on Traditional Chinese Windows
# writes Big5/CP950, Western Windows CP1252). Try them in order and say which won.
ENCODINGS = ("utf-8-sig", "cp950", "cp1252")


def read_csv(path, encoding=None):
    """Return (rows, encoding) for a CSV file, trying common spreadsheet encodings."""
    data = Path(path).read_bytes()
    for enc in [encoding] if encoding else ENCODINGS:
        try:
            text = data.decode(enc)
        except UnicodeDecodeError:
            continue
        return list(csv.reader(io.StringIO(text, newline=""))), enc
    sys.exit(
        f"error: cannot decode {path} as {encoding or ', '.join(ENCODINGS)}; re-export as UTF-8 or pass --encoding"
    )


STATUS_WORDS = {
    "YES",
    "NO",
    "TBD",
    "Y",
    "N",
    "PENDING",
    "N/A",
    "NA",
    "DONE",
    "PASS",
    "FAIL",
    "WIP",
    "TODO",
    "PARTIAL",
}


def profile(rows, header_rows):
    body = rows[header_rows:]
    width = max(len(r) for r in rows)
    cols = []
    for i in range(width):
        values = [r[i].strip() if i < len(r) else "" for r in body]
        filled = [v for v in values if v]
        counter = collections.Counter(filled)
        header = " / ".join(
            " ".join(r[i].split())
            for r in rows[:header_rows]
            if i < len(r) and r[i].strip()
        )
        avg = sum(map(len, filled)) / len(filled) if filled else 0
        multiline = sum("\n" in v for v in filled)
        kind = "empty"
        if filled:
            upper = {v.upper() for v in counter}
            if (
                len(counter) <= 6
                and all(len(v) <= 12 for v in counter)
                and (upper & STATUS_WORDS)
            ):
                kind = "status"
            elif sum(
                bool(re.match(r"^[A-Z]{1,3}\.?\d+(\.\d+)*$", v)) for v in filled
            ) >= 0.8 * len(filled):
                kind = "id"
            elif multiline or avg > 60:
                kind = "long-text"
            elif len(counter) <= 12 and len(filled) > 3 * len(counter):
                kind = "category"
            else:
                kind = "text"
        markers = collections.Counter()
        for v in filled:
            markers.update(
                re.findall(r"^[ \t]*\[([A-Za-z][\w .-]{0,30})\]", v, re.MULTILINE)
            )
        cols.append(
            {
                "index": i,
                "header": header,
                "fill": len(filled) / max(1, len(body)),
                "distinct": len(counter),
                "top": counter.most_common(5),
                "kind": kind,
                "markers": markers,
            }
        )
    return cols


def guess_header_rows(rows):
    # Header rows are the leading rows whose would-be status cells hold text instead of status words.
    for n in (1, 2, 3):
        cols = profile(rows, n)
        if any(c["kind"] == "status" for c in cols):
            status_cols = [c["index"] for c in cols if c["kind"] == "status"]
            nxt = rows[n] if n < len(rows) else []
            words = sum(
                (nxt[i].strip().upper() in STATUS_WORDS) or not nxt[i].strip()
                for i in status_cols
                if i < len(nxt)
            )
            if words >= len(status_cols) / 2:
                return n
    return 1


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("csv")
    parser.add_argument(
        "--encoding",
        help="force a text encoding (default: try " + ", ".join(ENCODINGS) + ")",
    )
    args = parser.parse_args()
    rows, encoding = read_csv(args.csv, args.encoding)
    if not any(any(c.strip() for c in r) for r in rows):
        sys.exit(f"error: {args.csv} has no data")
    header_rows = guess_header_rows(rows)
    cols = profile(rows, header_rows)
    err = sys.stderr
    note = (
        ""
        if encoding == "utf-8-sig"
        else "  <- NOT UTF-8: check the names below are not garbled"
    )
    print(f"encoding: {encoding}{note}", file=err)
    print(f"rows: {len(rows)}  header rows (guess): {header_rows}\n", file=err)
    for c in cols:
        top = ", ".join(f"{v[:24]!r}x{n}" for v, n in c["top"])
        print(
            f"[{c['index']:2}] {c['kind']:9} fill {c['fill']:4.0%} distinct {c['distinct']:3}  {c['header'][:50]!r}",
            file=err,
        )
        if c["kind"] != "empty":
            print(f"      top: {top}", file=err)
        if c["markers"]:
            print(f"      line-leading markers: {dict(c['markers'])}", file=err)

    by_kind = collections.defaultdict(list)
    for c in cols:
        by_kind[c["kind"]].append(c)
    status_cols = by_kind["status"]
    long_text = sorted(
        by_kind["long-text"], key=lambda c: (-sum(c["markers"].values()), -c["fill"])
    )
    category = [
        c
        for c in by_kind["category"]
        if c["index"] < (status_cols[0]["index"] if status_cols else 99)
    ]
    text = [
        c
        for c in by_kind["text"]
        if c["index"] < (status_cols[0]["index"] if status_cols else 99)
    ]
    ids = by_kind["id"]
    values = collections.Counter()
    for c in status_cols:
        for v, n in c["top"]:
            values[v] += n

    def line(key, col, note="guess"):
        if col is None:
            return f"  # {key}: <column index>   # not found - set it or leave out"
        return f"  {key}: {col['index']}   # {note}: {col['header'][:40]!r}"

    print('title: "TODO <PROJECT NAME> Matrix table"   # project name in upper case')
    print(f"header_rows: {header_rows}   # guess")
    if encoding != "utf-8-sig":
        print(f'encoding: "{encoding}"   # detected; the CSV is not UTF-8')
    print('jira_url: "https://example.atlassian.net/browse/"   # fixed')
    keys = collections.Counter(
        k for r in rows for c in r for k in re.findall(r"\b([A-Z][A-Z0-9]+)-\d+\b", c)
    )
    seen = ", ".join(f"{k} x{n}" for k, n in keys.most_common(3)) or "none found"
    print(
        f'jira_projects: ["TODO"]   # the project\'s Jira key; keys seen in the CSV: {seen}'
    )
    print('repository:\n  name: "TODO owner/name"   # from `git remote get-url origin`')
    print(
        '  branch: "TODO"   # deploy branch; never main/master/default, e.g. feature-matrix-<project>'
    )
    print("columns:")
    print(line("section", category[0] if category else None))
    print(line("component_id", ids[0] if ids else None))
    print(
        line(
            "component",
            category[1] if len(category) > 1 else (text[0] if text else None),
        )
    )
    print(line("label", text[-2] if len(text) >= 2 else None, "guess short name"))
    print(line("feature", text[-1] if text else None, "guess feature name"))
    comment = next((c for c in long_text if not c["markers"]), None)
    notes = next(
        (c for c in long_text if c["markers"]), long_text[-1] if long_text else None
    )
    print(line("comment", comment))
    print(line("notes", notes))
    print("status_values:   # every non-empty value in a status column must be listed")
    canon = {
        "YES": "supported",
        "Y": "supported",
        "DONE": "supported",
        "PASS": "supported",
        "NO": "unsupported",
        "N": "unsupported",
        "N/A": "unsupported",
        "NA": "unsupported",
    }
    for v, n in values.most_common():
        print(f'  "{v}": {canon.get(v.upper(), "tbd")}   # x{n}')
    print(
        'platforms:   # TODO confirm names with the user\n  - id: "platform-a"\n    name: "Platform A"\n    hardware: ""'
    )
    print("status_columns:   # TODO set platform / name / group for each")
    for c in status_cols:
        print(
            f'  - column: {c["index"]}\n    id: "col-{c["index"]}"   # header {c["header"][:50]!r}\n    name: "{c["header"][:20]}"\n    platform: "platform-a"'
        )
    if status_cols:
        lo, hi = status_cols[0]["index"], status_cols[-1]["index"]
        for c in cols:
            if c["kind"] == "empty" and c["header"] and lo - 1 <= c["index"] <= hi + 1:
                print(
                    f"  # empty column {c['index']} {c['header'][:50]!r}: a milestone with no data yet? add it if so"
                )
    markers = notes["markers"] if notes else {}
    if markers:
        print("notes_markers:   # line-leading [Marker] -> platform id")
        for m, n in markers.most_common():
            hint = (
                "   # rare: probably pasted log text, drop unless it is a platform"
                if n <= 2
                else ""
            )
            print(f'  "{m}": "TODO"{hint}   # x{n}')
        print(
            'notes_head_platform: "TODO"   # platform for text before the first marker, or delete -> general'
        )
        print(
            '# notes_default_platform: "TODO"   # platform for cells with no marker (default: general)'
        )


if __name__ == "__main__":
    main()
