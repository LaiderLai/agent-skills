"""Requirement-matrix template (v1.2) converter for convert_csv.py.

Selected by ``template: requirement-matrix`` in the mapping file; see
references/mapping.md for the format. The feature-matrix ``Converter`` in
convert_csv.py is not involved.
"""

import collections
import os
import re
import sys

import yaml
from convert_csv import META_HEADER, IndentDumper, clean, prune, read_csv, slug

SUPPORTED_VERSION = "v1.2"
JIRA_KEY = re.compile(r"[A-Z][A-Z0-9]+-\d+")
META_COLUMN_KEYS = (
    "id",
    "name",
    "platform",
    "group",
    "status_set",
    "note_key",
    "role",
)
MAPPING_ONLY_FIELD_KEYS = ("column", "raw_values")


class RequirementDumper(IndentDumper):
    """Write YAML exactly as `build.mjs format` does: plain scalars where safe,
    double quotes otherwise (so "2.10" stays a string) and `|-` for multi-line text."""

    def choose_scalar_style(self):
        style = super().choose_scalar_style()
        return '"' if style == "'" else style


RequirementDumper.add_representer(
    str,
    lambda d, v: d.represent_scalar(
        "tag:yaml.org,2002:str", v, style="|" if "\n" in v else None
    ),
)


def norm(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


class RequirementConverter:
    def __init__(self, mapping):
        self.m = mapping
        self.cols = mapping.get("columns") or {}
        self.fields = mapping.get("fields") or []
        self.status_columns = mapping["status_columns"]
        self.values = {
            name: {norm(k).upper(): v for k, v in raw.items()}
            for name, raw in (mapping.get("status_values") or {}).items()
        }
        self.markers = mapping.get("notes_markers") or {}
        self.head_key = mapping.get("notes_head_key") or "discovery"
        self.default_key = mapping.get("notes_default_key") or "discovery"
        if self.markers:
            names = "|".join(re.escape(k) for k in self.markers)
            self.marker_re = re.compile(rf"^[ \t]*\[({names})\][ \t]*", re.MULTILINE)
        self.note_order = [k["id"] for k in mapping.get("note_keys") or []]
        platforms = [p["id"] for p in mapping.get("platforms") or []]
        self.note_rank = {k: i for i, k in enumerate([*platforms, *self.note_order])}
        self.exclude = mapping.get("exclude_when")
        self.excluded_items = 0
        self.components = []
        self.skipped_rows = []
        self.template_version = None
        self.dropped_bug_tokens = collections.Counter()
        self.unknown_values = collections.Counter()
        self.csv_counts = collections.defaultdict(collections.Counter)
        self.default_counts = collections.defaultdict(collections.Counter)

    def index(self, ref, header):
        """Resolve a mapping column (0-based index or header name) to an index."""
        if isinstance(ref, int):
            return ref
        wanted = norm(ref).lower()
        for i, cell in enumerate(header):
            if norm(cell).lower() == wanted:
                return i
        sys.exit(f"error: no column with header {ref!r} in the CSV")

    def resolve_columns(self, header):
        ix = self.index
        self.id_index = ix(self.m["id_column"], header)
        self.col_index = {k: ix(v, header) for k, v in self.cols.items()}
        self.field_index = {f["id"]: ix(f["column"], header) for f in self.fields}
        self.status_index = {
            c["id"]: ix(c["column"], header)
            for c in self.status_columns
            if "column" in c
        }

    @staticmethod
    def get(row, index):
        return row[index] if index is not None and index < len(row) else ""

    def split_notes(self, text):
        text = clean(text)
        if not text:
            return {}
        found = list(self.marker_re.finditer(text)) if self.markers else []
        if not found:
            return {self.default_key: text}
        notes = {}
        head = clean(text[: found[0].start()])
        if head:
            notes[self.head_key] = head
        for i, match in enumerate(found):
            end = found[i + 1].start() if i + 1 < len(found) else len(text)
            body = clean(text[match.end() : end])
            if body:
                key = self.markers[match.group(1)]
                notes[key] = "\n\n".join(filter(None, [notes.get(key), body]))
        return dict(sorted(notes.items(), key=lambda kv: self.note_rank.get(kv[0], 99)))

    def field_value(self, field, raw):
        raw = clean(raw)
        if not raw:
            return None
        kind = field.get("type", "text")
        if kind == "enum":
            lookup = {norm(k).upper(): v for k, v in field["raw_values"].items()}
            value = lookup.get(norm(raw).upper())
            if value is None:
                self.unknown_values[(field["id"], raw)] += 1
            return value
        if kind == "list":
            tokens = [t for t in re.split(r"[,\s]+", raw) if t]
            if field.get("link") == "jira":
                kept = [t for t in tokens if JIRA_KEY.fullmatch(t)]
                self.dropped_bug_tokens.update(t for t in tokens if t not in kept)
                tokens = kept
            return tokens or None
        return raw

    def jira_keys(self, raw):
        tokens = [t for t in re.split(r"[,\s]+", clean(raw)) if t]
        self.dropped_bug_tokens.update(t for t in tokens if not JIRA_KEY.fullmatch(t))
        return list(dict.fromkeys(t for t in tokens if JIRA_KEY.fullmatch(t)))

    def run(self, csv_path):
        rows, self.encoding = read_csv(csv_path, self.m.get("encoding"))
        if self.encoding != "utf-8-sig":
            print(
                f"note: {csv_path} is not UTF-8; decoded as {self.encoding} (check names below look right)"
            )
        header_rows = self.m.get("header_rows", 3)
        if len(rows) < header_rows:
            sys.exit(f"error: {csv_path} has fewer than {header_rows} header rows")
        first = rows[0] if rows else []
        if len(first) > 1 and norm(first[0]).lower().startswith("based on template"):
            self.template_version = norm(first[1]) or None
        if self.template_version and self.template_version != SUPPORTED_VERSION:
            print(
                f"warning: template version {self.template_version} (expected {SUPPORTED_VERSION}); converting anyway"
            )
        self.resolve_columns(rows[header_rows - 1])
        seen_ids = set()
        closed = set()
        category = None
        component = None
        for number, row in enumerate(rows[header_rows:], start=header_rows + 1):
            if not any(c.strip() for c in row):
                continue
            raw_id = clean(self.get(row, self.id_index))
            if not raw_id:
                self.skipped_rows.append(number)
                continue
            if raw_id in seen_ids:
                sys.exit(f"error: duplicate requirement id {raw_id!r} (row {number})")
            seen_ids.add(raw_id)
            value = clean(self.get(row, self.col_index.get("category"))) or category
            value = value or "General"
            if value != category:
                if value in closed:
                    sys.exit(
                        f"error: category {value!r} reappears after another category (row {number}); group its rows together"
                    )
                if category is not None:
                    closed.add(category)
                category = value
                component = {
                    "_number": len(self.components) + 1,
                    "id": f"A.{len(self.components) + 1}",
                    "name": category,
                    "features": [],
                }
                self.components.append(component)
            component["features"].append(self.build_item(row, raw_id))

    def build_item(self, row, raw_id):
        get = self.get
        item = {
            "id": raw_id,
            "name": norm(get(row, self.col_index.get("name"))) or raw_id,
        }
        comment = clean(get(row, self.col_index.get("comment")))
        if comment:
            item["comment"] = comment
        values = {}

        def read(f):
            if f["id"] not in values:
                values[f["id"]] = self.field_value(
                    f, get(row, self.field_index[f["id"]])
                )
            return values[f["id"]]

        excluded = False
        keep = {"source"}
        if self.exclude:
            keep.add(self.exclude["field"])
            for f in self.fields:
                if f["id"] == self.exclude["field"]:
                    excluded = read(f) == self.exclude["equals"]
        if excluded:
            self.excluded_items += 1
            fields = {}
            for f in self.fields:
                if f["id"] in keep and read(f) is not None:
                    fields[f["id"]] = values[f["id"]]
            if fields:
                item["fields"] = fields
            return item
        fields = {}
        for f in self.fields:
            value = read(f)
            if value is not None:
                fields[f["id"]] = value
        status = {}
        for col in self.status_columns:
            if col["id"] in self.status_index:
                raw = get(row, self.status_index[col["id"]]).strip()
                if not raw:
                    continue
                values = self.values.get(col.get("status_set", "default")) or {}
                value = values.get(norm(raw).upper())
                if value is None:
                    self.unknown_values[(col["id"], raw)] += 1
                    continue
                status[col["id"]] = value
                self.csv_counts[col["id"]][value] += 1
            elif "default" in col:
                rule = col["default"]
                cond = rule.get("when")
                if not cond or fields.get(cond.get("field")) == cond.get("equals"):
                    status[col["id"]] = rule["value"]
                    self.default_counts[col["id"]][rule["value"]] += 1
        if status:
            item["status"] = status
        if fields:
            item["fields"] = fields
        notes = self.split_notes(get(row, self.col_index.get("notes")))
        keys = self.jira_keys(get(row, self.col_index.get("jira")))
        if keys:
            line = f"Jira: {', '.join(keys)}"
            notes["discovery"] = "\n\n".join(
                filter(None, [notes.get("discovery"), line])
            )
            notes = dict(
                sorted(notes.items(), key=lambda kv: self.note_rank.get(kv[0], 99))
            )
        if notes:
            item["notes"] = notes
        return item

    def meta(self):
        m = self.m
        meta = {"title": m["title"]}
        for key in ("jira_url", "jira_projects"):
            if m.get(key):
                meta[key] = m[key]
        repo = m.get("repository") or {}
        meta["repository"] = {
            "name": repo.get("name", ""),
            "branch": repo.get("branch", "main"),
            "path": "matrix-table/data",
            "tag_prefix": repo.get("tag_prefix", "matrix-table/"),
        }
        meta["template"] = "requirement-matrix"
        if self.template_version:
            meta["template_version"] = self.template_version
        meta["noun"] = m.get("noun") or ["requirement", "requirements"]
        if m.get("exclude_when"):
            meta["exclude_when"] = m["exclude_when"]
        meta["platforms"] = m.get("platforms") or []
        meta["status_sets"] = m.get("status_sets") or {}
        meta["fields"] = [
            {k: v for k, v in f.items() if k not in MAPPING_ONLY_FIELD_KEYS}
            for f in self.fields
        ]
        if m.get("note_keys"):
            meta["note_keys"] = m["note_keys"]
        meta["columns"] = [
            {k: col[k] for k in META_COLUMN_KEYS if k in col}
            for col in self.status_columns
        ]
        meta["sections"] = [{"id": "A", "name": m.get("section_name", "Requirements")}]
        return prune(meta)

    def write(self, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        for old in out_dir.glob("*.yaml"):
            old.unlink()

        def dump(data):
            return yaml.dump(
                data,
                Dumper=RequirementDumper,
                sort_keys=False,
                allow_unicode=True,
                width=1000,
            )

        (out_dir / "_meta.yaml").write_text(
            META_HEADER + dump(self.meta()), encoding="utf-8"
        )
        for c in self.components:
            doc = {"id": c["id"], "name": c["name"], "features": c["features"]}
            name = f"A.{c['_number']:02d}-{slug(c['name'])}.yaml"
            (out_dir / name).write_text(dump(doc), encoding="utf-8")

    def verify(self):
        """Compare status counts read from the CSV with counts in the generated items."""
        out_counts = collections.defaultdict(collections.Counter)
        total = 0
        for c in self.components:
            for item in c["features"]:
                total += 1
                for col, value in (item.get("status") or {}).items():
                    out_counts[col][value] += 1
        for col, counter in self.default_counts.items():
            out_counts[col].subtract(counter)
        ok = True
        print(f"\n{len(self.components)} components, {total} requirements")
        print(f"{'column':24} {'csv':>28} {'yaml':>28}")
        for col in self.status_columns:
            if col["id"] not in self.status_index:
                continue
            a = dict(self.csv_counts[col["id"]])
            b = {k: v for k, v in out_counts[col["id"]].items() if v}
            mark = "OK" if a == b else "MISMATCH"
            ok &= a == b
            print(f"{col['id']:24} {a!s:>28} {b!s:>28}  {mark}")
        for col, counter in self.default_counts.items():
            print(f"{col}: {sum(counter.values())} set by default (not from CSV)")
        if not total:
            ok = False
            print(
                "error: no requirements found - wrong header_rows / columns, or an empty CSV"
            )
        print(f"out-of-scope: {self.excluded_items} items, their other columns ignored")
        if self.skipped_rows:
            print(
                f"skipped {len(self.skipped_rows)} rows without a Req ID: {self.skipped_rows}"
            )
        dropped = sum(self.dropped_bug_tokens.values())
        if dropped:
            print(
                f"dropped {dropped} bug tokens (not Jira keys): {sorted(self.dropped_bug_tokens)}"
            )
        if self.unknown_values:
            ok = False
            print("\nerror: values not in the mapping (add them or fix the column):")
            for (col, raw), n in self.unknown_values.most_common():
                print(f"  {col}: {raw!r} x{n}")
        notes = collections.Counter(
            k
            for c in self.components
            for i in c["features"]
            for k in (i.get("notes") or {})
        )
        print(f"notes by key: {dict(notes)}")
        return ok


STATUS_SET = [
    {"id": "supported", "label": "Supported", "resolved": True, "tone": "yes"},
    {"id": "enabled", "label": "Enabled", "resolved": True, "tone": "info"},
    {"id": "not-supported", "label": "Not supported", "resolved": False, "tone": "no"},
]
STATUS_SET_TITLES = [
    "Works with the standard image",
    "Works after project enablement (custom driver, kernel component or workaround)",
    "In scope but cannot be supported",
]
STATUS_VALUES = {
    "Supported": "supported",
    "Enabled": "enabled",
    "Not supported": "not-supported",
}
ENUM_TONES = {"critical": "no", "out-of-scope": "neutral", "tbd": "open"}
PHASES = [("ea", "EA", "x01"), ("fc", "FC", "x02"), ("ga", "GA", "future MS")]


def detect(rows):
    """Return the template version ("v1.2") when rows look like the requirement matrix."""
    if len(rows) < 2 or not rows[0]:
        return None
    if not norm(rows[0][0]).lower().startswith("based on template"):
        return None
    group_row = norm(" ".join(rows[1]))
    if "Project Execution" not in group_row or "Test Plan" not in group_row:
        return None
    version = norm(rows[0][1]) if len(rows[0]) > 1 else ""
    return version or "unknown"


class DraftMapping(dict):
    positional_status = False


def milestone_columns(header):
    """Find phase id -> Platform #1 column index by header text, or None if a header is missing."""
    hits = {"x01": [], "x02": [], "future": []}
    for i, cell in enumerate(header):
        text = norm(cell).lower()
        if "future ms" in text:
            hits["future"].append(i)
        for key in ("x01", "x02"):
            if re.search(rf"\b{key}\b", text):
                hits[key].append(i)
    if any(not v for v in hits.values()):
        return None
    return {
        phase: hits[key][0]
        for phase, key in zip(("ea", "fc", "ga"), ("x01", "x02", "future"))
    }


def draft_mapping(rows, err=None):
    """Build a draft mapping dict for the requirement matrix; counts go to `err`."""
    from inspect_csv import jira_browse_url

    err = err or sys.stderr
    header_rows = 3
    header = rows[header_rows - 1]
    body = rows[header_rows:]
    names = [norm(h).lower() for h in header]

    def find(wanted, contains=False):
        for i, n in enumerate(names):
            if (wanted in n) if contains else (n == wanted):
                return i
        return None

    def cell(row, i):
        return clean(row[i]) if i is not None and i < len(row) else ""

    def column(i):
        return [cell(r, i) for r in body if any(c.strip() for c in r)]

    id_col = find("req id")
    if id_col is None:
        sys.exit("error: no 'Req ID' column in the header row")
    bug_col = find("jira id", contains=True)
    found = {
        key: find(wanted)
        for key, wanted in {
            "category": "category",
            "name": "feature (component)",
            "comment": "requirement description",
            "notes": "notes",
            "source": "source of req",
            "scope": "project scope (approved)",
            "discovery_check": "check items in discovery phase",
            "risk": "risk",
            "test_ids": "test id",
            "test_name": "test short name",
            "test_description": "test description",
            "test_expected": "test expected outcome",
            "test_type": "checkbox test type",
            "test_status": "checkbox test status",
        }.items()
    }

    def enum(field_id, name, key, extra=(), block=None):
        raw = list(dict.fromkeys([*(v for v in column(found[key]) if v), *extra]))
        ids = {v: slug(v) for v in raw}
        values = []
        for v in raw:
            entry = {"id": ids[v], "label": v}
            if ids[v] in ENUM_TONES:
                entry["tone"] = ENUM_TONES[ids[v]]
            values.append(entry)
        field = {
            "id": field_id,
            "name": name,
            "type": "enum",
            "show": "table",
            "filter": True,
        }
        if block:
            field["block"] = block
        field.update({"column": found[key], "values": values, "raw_values": ids})
        return field

    def text(field_id, name, key, block=None):
        field = {"id": field_id, "name": name, "type": "text", "show": "detail"}
        if block:
            field["block"] = block
        field["column"] = found[key]
        return field

    fields = []
    if found["scope"] is not None:
        fields.append(enum("scope", "Scope", "scope", extra=("TBD",)))
    if found["risk"] is not None:
        fields.append(enum("risk", "Risk", "risk", block="discovery"))
    if found["source"] is not None:
        fields.append(text("source", "Source", "source"))
    if found["discovery_check"] is not None:
        fields.append(
            text("discovery_check", "Discovery check", "discovery_check", "discovery")
        )
    plan = [
        ("test_ids", "Test IDs", "list"),
        ("test_name", "Test name", "text"),
        ("test_description", "Test description", "text"),
        ("test_expected", "Expected outcome", "text"),
        ("test_type", "Checkbox test type", "text"),
        ("test_status", "Checkbox test status", "text"),
    ]
    for key, label, kind in plan:
        if found[key] is None:
            continue
        field = text(key, label, key, "test-plan")
        field["type"] = kind
        fields.append(field)

    jira_keys = collections.Counter()
    for i in (found["notes"], bug_col):
        for value in column(i):
            jira_keys.update(k for k in re.findall(r"\b([A-Z][A-Z0-9]+)-\d+\b", value))

    note_keys = [{"id": "discovery", "name": "Discovery"}]
    note_keys += [{"id": pid, "name": label} for pid, label, _ in PHASES]
    note_keys.append({"id": "qa", "name": "QA"})

    status_columns = []
    located = milestone_columns(header)
    start = (bug_col if bug_col is not None else id_col) + 1
    if located is None:
        print(
            "warning: milestone headers x01 / x02 / future MS not found; "
            f"status columns assumed to be the 3 columns after column {start - 1} (CONFIRM)",
            file=err,
        )
    for j, (pid, label, _) in enumerate(PHASES):
        status_columns.append(
            {
                "column": located[pid] if located else start + j,
                "id": pid,
                "name": label,
                "platform": "platform-1",
                "status_set": "execution",
                "note_key": pid,
            }
        )
    status_columns.append(
        {
            "id": "test",
            "name": "Test",
            "group": "Test plan",
            "role": "test",
            "note_key": "qa",
            "default": {"value": "tbd"},
        }
    )

    mapping = DraftMapping(
        {
            "template": "requirement-matrix",
            "title": "TODO <PROJECT NAME> Matrix table",
            "noun": ["requirement", "requirements"],
            "header_rows": header_rows,
        }
    )
    mapping.positional_status = located is None
    jira = jira_browse_url(os.environ.get("MATRIX_TO_SITE_JIRA_URL", ""))
    if jira:
        mapping["jira_url"] = jira
    mapping["jira_projects"] = sorted(jira_keys) or ["TODO"]
    mapping["repository"] = {"name": "TODO owner/name", "branch": "TODO"}
    mapping["id_column"] = id_col
    found["jira"] = bug_col
    mapping["columns"] = {
        k: found[k]
        for k in ("category", "name", "comment", "notes", "jira")
        if found[k] is not None
    }
    if found["scope"] is not None:
        mapping["exclude_when"] = {"field": "scope", "equals": "out-of-scope"}
    mapping["platforms"] = [{"id": "platform-1", "name": "Platform 1"}]
    mapping["status_sets"] = {
        "execution": [{**s, "title": t} for s, t in zip(STATUS_SET, STATUS_SET_TITLES)]
    }
    mapping["status_values"] = {"execution": dict(STATUS_VALUES)}
    mapping["fields"] = fields
    mapping["note_keys"] = note_keys
    mapping["status_columns"] = status_columns
    mapping["notes_default_key"] = "discovery"

    ids = [cell(r, id_col) for r in body if any(c.strip() for c in r)]
    missing = sum(not i for i in ids)
    tokens = (
        [t for v in column(bug_col) for t in re.split(r"[,\s]+", v) if t]
        if bug_col is not None
        else []
    )
    bad = sum(not JIRA_KEY.fullmatch(t) for t in tokens)
    print("requirement matrix", detect(rows), file=err)
    print(f"{len(ids)} data rows", file=err)
    print(
        f"{missing} row{'s' * (missing != 1)} without Req ID (skipped by the converter)",
        file=err,
    )
    print(
        f"{bad} bug token{'s' * (bad != 1)} {'is' if bad == 1 else 'are'} not Jira keys (dropped by the converter)",
        file=err,
    )
    for i, h in enumerate(header):
        values = collections.Counter(v for v in column(i) if v)
        if not values:
            print(f"[{i:2}] empty        {norm(h)!r}", file=err)
        else:
            top = ", ".join(f"{v[:24]!r}x{n}" for v, n in values.most_common(4))
            print(f"[{i:2}] {len(values):3} values  {norm(h)!r}: {top}", file=err)
    return mapping


def render_draft(mapping):
    """Print-ready YAML for a draft mapping, with # CONFIRM / TODO comments."""
    text = yaml.dump(
        dict(mapping),
        Dumper=RequirementDumper,
        sort_keys=False,
        allow_unicode=True,
        width=1000,
    )
    out = []
    for line in text.splitlines():
        if re.search(r"name: Platform \d$", line):
            line += "   # CONFIRM platform name with the user"
        if line == "status_columns:" and getattr(mapping, "positional_status", False):
            line += "   # CONFIRM column positions: milestone headers not recognised"
        out.append(line)
        if line.startswith("jira_projects:") and "jira_url" not in mapping:
            out.insert(
                len(out) - 1,
                '# jira_url: "https://<site>.atlassian.net/browse/"   # TODO $MATRIX_TO_SITE_JIRA_URL unset: ask',
            )
    return "\n".join(out) + "\n"
