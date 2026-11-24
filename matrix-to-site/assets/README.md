# Matrix Table

What each platform and milestone supports, with notes and test evidence —
browsable, editable from the browser, versioned with git tags and exportable
as a standalone HTML report. Generated from a spreadsheet export.

## Layout

```
matrix-table/
├── data/
│   ├── _meta.yaml          # platforms, status columns (platform x milestone), sections, repo settings
│   └── A.01-<name>.yaml    # one file per component
├── web/                    # static web UI (viewer + editor), no build step
│   └── model.js            # shared by the UI and tools: validation + canonical YAML
└── tools/
    ├── build.mjs           # check | format | build <dir>
    ├── convert_csv.py      # spreadsheet import (re-run only to start over from a CSV)
    └── mapping.yaml        # how the CSV columns map onto the data
```

A component file looks like this:

```yaml
id: A.1
name: System
features:
  - id: A.1.9
    name: HW Watchdog Timer (WDT)
    label: Watchdog              # optional short name
    comment: ...                 # optional description / comment
    status:                      # column ids come from _meta.yaml
      silicon: supported         # supported | unsupported | tbd   (omit = not set)
      board-beta: tbd
    notes:                       # <platform id>
      board: |-
        $ sudo dmesg | grep -i watchdog
        ...
```

| Value | Shown as | Meaning |
|-------|----------|---------|
| `supported` | YES | **Resolved** – supported / in scope |
| `unsupported` | NO | **Resolved** – not supported / out of scope |
| `tbd` | TBD | **Open** – not yet verified, still under discussion |
| *(omitted)* | — | Not set for this milestone |

- Adding a milestone = add a column to `_meta.yaml`; adding a platform = add it to `platforms`.
- Jira keys listed in `jira_projects` and URLs in notes are linked automatically.

## Requirement matrix

With `template: requirement-matrix` in `_meta.yaml`, items are requirements (Req ID as
`id`) grouped by Category. Besides `name` / `comment`, the extra attributes defined in
`_meta.yaml` (`scope`, `risk`, ...) live under `fields:`, and each item has a
status per platform phase:

```yaml
  - id: "2.03"                   # numeric-looking ids must be quoted strings
    name: GPU
    status: {ea: enabled, test: tbd}
    fields: {scope: in-scope, risk: critical}
    notes: {discovery: "...\nJira: PROJ-12", qa: ...}
```

| Status | Meaning |
|--------|---------|
| Supported | **Done** – works with the standard image |
| Enabled | **Done** – works after project enablement |
| Not supported | **Not done** – in scope but cannot be supported |

- Scope is In Scope / Out-of-Scope / TBD. Out-of-Scope items are listed but keep only
  ID, name, description, Source and Scope; their other columns are ignored everywhere
  (counts, cards, filters), and the editor hides those fields but keeps their data.
- Phases EA / FC / GA come from the first platform's x01 / x02 / future MS columns.
- The **Test** column (YES / NO / TBD only) starts as TBD for every item that is not
  Out-of-Scope. Jira keys from the Jira column are appended to the Discovery note
  as its last line (`Jira: PROJ-12`); other tokens are dropped.
- Requirements have no Short label and no per-platform notes; note sections are
  Discovery / EA / FC / GA / QA (no General).
- All CSV notes go to the Discovery note.
- The overview shows a done % donut per phase, a Risk card (done / risky on the focused
  phase; risky = not Out-of-Scope and risk not None, empty counts), a Test coverage
  card (YES ÷ non-excluded items) and a "Not done" sidebar; filters cover scope and risk.
  Warning colours: Not supported > 0 is red; risk below 100 % is orange (red at 0 %);
  coverage is red < 50 %, orange < 80 %, yellow < 100 %, green at 100 %.

## Editing

**In the browser (anyone with repo access):** open the site, click **Sign in to edit**
and paste a fine-grained GitHub token (Repository access: only this repo;
Permissions → Contents: Read and write). Saving commits straight to the deploy
branch, live immediately for signed-in users; the read-only snapshot redeploys in
1–2 minutes. Concurrent edits to different features merge automatically; editing
the same feature concurrently is rejected.

**Batch status change (e.g. after a review meeting):** tick the rows (or the header
checkbox for all visible rows; works across components on the search / "Open items"
page), choose the column and YES / NO / TBD / —, optionally type a meeting note, then
**Apply & save**. Everything is saved as one commit. Items already at that value are
skipped; the note is appended to each changed item's notes for that column's platform
as `YYYY-MM-DD · <column>: <old> → <new> — <note>`.

**In git:** edit the YAML, then

```sh
node matrix-table/tools/build.mjs format   # normalise formatting
node matrix-table/tools/build.mjs check    # validate (also run by CI)
```

## Versions

A version is an annotated tag `matrix-table/<version>`. Create one from
**Version → ＋ Create version…** (signed in) or with git; view it from the menu or
`…/?v=<version>`. Versions are read-only. Deleting a tag does not redeploy:
run the workflow manually afterwards.

## Export

**⤓ Export HTML** downloads a single self-contained file of the viewed version that
opens offline (for customers). **Export CSV** on the overview gives a spreadsheet.

## Local preview

```sh
node matrix-table/tools/build.mjs build /tmp/fm && python3 -m http.server -d /tmp/fm 8000
```
