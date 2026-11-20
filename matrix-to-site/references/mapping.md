# Mapping file format

`scripts/convert_csv.py` is driven by a YAML mapping that says which CSV
column holds what. Draft one with `scripts/inspect_csv.py`, then fix it.
Column indexes are **0-based**.

```yaml
title: "Example Matrix table"          # always "<Project name> Matrix table"
header_rows: 2                         # rows to skip before data
# encoding: "cp950"                   # only when the CSV is not UTF-8 (inspect_csv.py fills it in)
jira_url: "https://example.atlassian.net/browse/"   # fixed: links Jira keys in notes
jira_projects: ["PROJ"]                               # the project's Jira key(s), e.g. ["PROJ", "PROJHW"]
repository:                            # written to _meta.yaml; the web editor commits here
  name: "example-org/example-repo"     # owner/name from `git remote get-url origin`
  branch: "feature-matrix-example"     # deploy branch: never main, master or the default branch
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
notes_head_platform: "board-a"   # text before the first marker; omit -> "general"
notes_default_platform: "board-a"  # cells with no marker at all; omit -> "general"
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
  `notes_head_platform`. A cell with no marker goes to `notes_default_platform` (default
  `general`), except when its first line contains an inline marker (e.g.
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
