# Mapping file format

`scripts/convert_csv.py` is driven by a YAML mapping that says which CSV
column holds what. Draft one with `scripts/inspect_csv.py`, then fix it.
Column indexes are **0-based**.

```yaml
title: "Example Matrix table"          # always "<Project name> Matrix table"
header_rows: 2                         # rows to skip before data
# encoding: "cp950"                   # only when the CSV is not UTF-8 (inspect_csv.py fills it in)
jira_url: "https://example.atlassian.net/browse/"   # $MATRIX_TO_SITE_JIRA_URL or asked; omit = no links
jira_projects: ["PROJ"]                               # the project's Jira key(s), e.g. ["PROJ", "PROJHW"]
repository:                            # written to _meta.yaml; the web editor commits here
  name: "example-org/example-repo"     # owner/name from `git remote get-url origin`
  branch: "matrix-table-example"     # deploy branch: never main, master or the default branch
  # tag_prefix: "matrix-table/"        # versions are tags <tag_prefix><version>

columns:
  section: 0          # top-level group, e.g. "Hardware / Linux Kernel" (carried down)
  component_id: 1     # optional: a value here (e.g. "A.1.0") marks a component header row
  component: 2        # component name ("System", "Storage", ...)
  label: 3            # optional short name
  feature: 4          # feature name (falls back to label when empty)
  comment: 5          # optional description / comment
  notes: 12           # optional remarks / evidence / logs

sections:             # optional: fix ids / names; unknown sections get A, B, C... in order
  "Hardware / Linux Kernel": {id: "A"}
  "Distro and Middleware": {id: "B"}
  "Firmware and Bootloader": {id: "C"}

status_values:        # EVERY non-empty value in a status column, matched case-insensitively
  "YES": supported    # resolved: supported / in scope
  "NO": unsupported   # resolved: not supported / out of scope
  "TBD": tbd          # open: not verified yet / under discussion

platforms:            # platforms that own status columns and notes
  - {id: "board-a", name: "Board A", hardware: "Reference board"}
  - {id: "board-b", name: "Board B", hardware: "Partner board"}

status_columns:       # one entry per platform x milestone column, in display order
  - {column: 6, id: "silicon", name: "Silicon", group: "Supported by HW/FW", hint: "Silicon (P1)"}
  - {column: 7, id: "board-a-ea", platform: "board-a", name: "EA"}
  - {column: 8, id: "board-a-beta", platform: "board-a", name: "Beta"}
  - {column: 9, id: "board-a-ga", platform: "board-a", name: "GA"}
  - {column: 10, id: "board-b-beta", platform: "board-b", name: "Beta"}
  - {column: 11, id: "board-b-ga", platform: "board-b", name: "GA"}   # empty column = future milestone

notes_markers:        # line-leading "[Marker]" in the notes column -> platform id
  "BoardB": "board-b"
  "Vendor": "board-a"     # a marker can be an alias of a platform
notes_head_platform: "board-a"   # text before the first marker; omit -> the default platform
notes_default_platform: "board-a"  # cells with no marker at all; required with 2+ platforms (one platform: implied)
```

## Rules the converter applies

- A row with `section` set switches the current section; blank cells carry the previous one down.
- A row with `component_id` set starts a component: its `component`, `comment` and
  `notes` become the component's name, description and notes. The number in the id
  (`A.1.0` → 1) becomes the component number. Without a `component_id` column, a new
  component starts whenever the `component` value changes.
- A row with no feature/label name (and no component id) is a section header: its
  comment and notes are stored on the section.
- Feature ids are generated: `<section>.<component>.<n>` in CSV order.
- Status cells: empty → not set. A value missing from `status_values` stops the
  conversion with a list of the unknown values; add them (e.g. `"N/A": unsupported`) or
  fix the column choice.
- Notes: text is split at line-leading `[Marker]`s; text before the first marker goes to
  `notes_head_platform`. A cell with no marker goes to `notes_default_platform` (required
  with two or more platforms; implied with one), except when its first line contains an inline marker (e.g.
  `PROJ-1: [BoardB] question`), which assigns the cell to that platform. Use
  `notes_default_platform` when one platform is the "unmarked" default, e.g. the user says
  "everything not tagged [BoardB] belongs to Board A".

## Choosing values

- `status_columns.id`: lowercase `<platform>-<milestone>`; it is the key stored in the YAML,
  so pick it once and keep it.
- A status column without `platform` (e.g. silicon support) needs `group` (card title).
- Drop columns that are completely empty and not a milestone; empty milestone columns
  (planned but no data yet) are worth keeping so the UI shows them.
- Markers that appear only once or twice are usually pasted log text (`[build]`), not platforms.

## Requirement matrix

A mapping with `template: "requirement-matrix"` is handled by
`scripts/requirement_matrix.py` instead of the feature-matrix converter. The CSV has
three header rows (template info, groups, column names); items are requirements keyed by
the CSV's Req ID, one component per Category. Every `column` / `id_column` value is a
0-based index or a header name (matched ignoring case and whitespace differences).

```yaml
template: "requirement-matrix"
title: "Example Matrix table"
noun: ["requirement", "requirements"]
header_rows: 3
jira_url: "https://example.atlassian.net/browse/"   # Jira keys in the notes are linked
jira_projects: ["PROJ"]
repository: {name: "example-org/example-repo", branch: "matrix-table-demo"}
id_column: 1                      # Req ID; rows without one are skipped and reported
columns: {category: 2, name: 3, comment: 4, notes: 8, jira: 9}   # jira: the Jira ID column -> Discovery note
platforms:
  - {id: "platform-1", name: "Board X"}   # one platform; other platforms' columns are not mapped
exclude_when: {field: scope, equals: out-of-scope}   # copied to _meta.yaml
status_sets:                      # copied to _meta.yaml; quote yes/no tones ("yes")
  execution:
    - {id: supported, label: Supported, resolved: true, tone: "yes", title: "Works with the standard image"}
    - {id: enabled, label: Enabled, resolved: true, tone: info, title: "Works after project enablement"}
    - {id: not-supported, label: Not supported, resolved: false, tone: "no", title: "In scope but cannot be supported"}
status_values:                    # per set: raw CSV word (case-insensitive) -> status id
  execution: {"Supported": supported, "Enabled": enabled, "Not supported": not-supported}
fields:                           # the _meta field definition plus `column`
  - id: scope
    name: Scope
    type: enum
    show: table
    filter: true
    column: 5
    values:                       # copied to _meta.yaml
      - {id: in-scope, label: In Scope}
      - {id: out-of-scope, label: Out-of-Scope, tone: neutral}
      - {id: tbd, label: TBD, tone: open}
    raw_values: {"In Scope": in-scope, "Out-of-Scope": out-of-scope, "TBD": tbd}   # raw CSV word -> value id
  - {id: source, name: Source, type: text, show: detail, column: 0}
  - {id: discovery_check, name: Discovery check, type: text, show: detail, block: discovery, column: 6}
note_keys:                        # notes sections, in display order
  - {id: discovery, name: Discovery}
  - {id: ea, name: EA}
  - {id: fc, name: FC}
  - {id: ga, name: GA}
  - {id: qa, name: QA}
status_columns:
  - {column: 10, id: ea, name: EA, platform: platform-1, status_set: execution, note_key: ea}
  - {column: 11, id: fc, name: FC, platform: platform-1, status_set: execution, note_key: fc}
  - {column: 12, id: ga, name: GA, platform: platform-1, status_set: execution, note_key: ga}
  - id: test                      # no CSV column: filled only by `default`
    name: Test
    group: Test plan
    role: test
    note_key: qa
    default: {value: tbd}         # every non-excluded item
notes_default_key: discovery      # the whole Notes cell goes to this note
```

- Components are the Categories in CSV order (`A.1`, `A.2`, …). A Category that comes
  back after another one stops the conversion.
- Item ids are the Req IDs; duplicates stop the conversion. The written YAML is already
  in `build.mjs format`'s canonical form.
- `name` is the name cell with whitespace collapsed to single spaces.
- Enum values missing from `raw_values` and status words missing from `status_values`
  are listed and make verification fail. Empty cells are "not set".
- `columns.jira` (the Jira ID column) is split on commas/whitespace; only Jira keys
  (`ABC-123`) are kept, de-duplicated in column order, and written as the item's
  Discovery note as `Jira: KEY-1, KEY-2` (appended after any other Discovery text). Other
  tokens are dropped and counted ("dropped N bug tokens"). Excluded items' Jira cells
  are not read. There is no `jira` field and items have no `label`.
- `list` fields split on commas/whitespace.
- A status column with `default` and no `column` gets `value` on every non-excluded item
  (or, with an optional `when: {field, equals}`, only where that field matches);
  verification reports those separately.
- `exclude_when` marks items (here Scope = Out-of-Scope) that are only listed: the
  converter reads just their name, description, `source` and scope, never their other
  columns, and verification prints `out-of-scope: N items, their other columns ignored`.
  Any other non-empty status word on a non-excluded row (`TBD`, `Out-of-Scope`, ...) is
  unknown and fails verification.
- Notes are not split by markers: a `[x01]` line stays inside the Discovery note.
- Only `id, name, platform, group, status_set, note_key, role` of a status
  column, and the field definition without `column` / `raw_values`, go into `_meta.yaml`.
- A first row starting with "Based on template" supplies `template_version`; a version
  other than `v1.2` prints a warning and conversion continues.
