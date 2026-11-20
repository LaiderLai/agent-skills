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
    notes:                       # general | <platform id>
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

## Editing

**In the browser (anyone with repo access):** open the site, click **Sign in to edit**
and paste a fine-grained GitHub token (Repository access: only this repo;
Permissions → Contents: Read and write). Saving commits straight to the deploy
branch, live immediately for signed-in users; the read-only snapshot redeploys in
1–2 minutes. Concurrent edits to different features merge automatically; editing
the same feature concurrently is rejected.

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
