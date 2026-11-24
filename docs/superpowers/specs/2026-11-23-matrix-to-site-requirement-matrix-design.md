# matrix-to-site: requirement matrix template

## Why

Some projects track their scope in a different spreadsheet template — a *requirement
matrix* (template v1.2: Requirements / Risk assessment / Project Execution per platform /
Test Plan) — instead of the *feature matrix* the skill handles today. The team wants the
same site (browse, in-browser editing, batch status changes, versions, HTML export,
GitHub Pages) for those sheets, plus a view of how well the in-scope requirements are
covered by tests. QA reviews each requirement and records a test conclusion.

## Goals

- One skill handles both templates; the template is declared in the data, never guessed
  at runtime.
- Requirement matrices keep their own IDs, status words, scope, risk, Jira references
  and test plan, and add a QA test conclusion (YES / NO / TBD) per in-scope requirement.
- Overview shows test coverage of in-scope requirements and how many in-scope
  requirements are Critical risk.

## Non-goals

- Links to bug trackers other than Jira.
- Batch editing of Scope or Risk (status columns only; may come later).
- Using the CSV's "Checkbox test status" as the test conclusion (it holds template
  defaults; it is kept as plain information).
- Keying browser `localStorage` per site (existing behaviour, unchanged).

## Anti-goals (would make this a failure even if it works)

- Any change to how feature matrices convert, validate, render or behave.
- Customer or project data from a real requirement CSV ending up in the skill repo.
- Two diverging copies of the web UI.

## Constraints

- Existing feature-matrix data (no `template` key) must keep working unchanged.
- Generated YAML stays lint-clean (repo yamllint) and canonically formatted.
- SKILL.md and docs in English, no project/company/customer names.
- Nothing is pushed to any remote branch without the user's explicit consent.

## Approaches

- **A. One skill, template-aware data model (chosen).** Shared converter, UI and tools;
  template-specific behaviour driven by `_meta.yaml`. One code base; isolation via data
  declaration + tests.
- B. A second skill with a copied site. Zero risk to feature matrices, but every fix
  twice and the copies drift.
- C. Two skills sharing a core via a sync script. Skills must be self-contained
  directories, so this is B with extra machinery.

## Data model

### `_meta.yaml` additions (all optional; feature matrices need none)

```yaml
template: requirement-matrix        # absent => feature-matrix
template_version: v1.2              # informational, from the CSV's first row
noun: [requirement, requirements]   # absent => [feature, features]
status_sets:                        # "default" is reserved = built-in YES/NO/TBD
  requirement:
    - {id: supported,     label: Supported,     resolved: true,  tone: yes,     title: Works with the standard image}
    - {id: enabled,       label: Enabled,       resolved: true,  tone: info,    title: Works after project enablement (custom driver, kernel component or workaround)}
    - {id: not-supported, label: Not supported, resolved: true,  tone: no,      title: In scope but cannot be supported}
    - {id: out-of-scope,  label: Out-of-Scope,  resolved: true,  tone: neutral, title: Not in project scope}
    - {id: tbd,           label: TBD,           resolved: false, tone: open,    title: Not decided yet}
fields:                             # order = display order
  - {id: scope, name: Scope, type: enum, show: table, filter: true,
     values: [{id: in-scope, label: In Scope}, {id: out-of-scope, label: Out-of-Scope, tone: neutral}]}
  - {id: risk, name: Risk, type: enum, show: table, filter: true,
     values: [{id: none, label: None}, {id: critical, label: Critical, tone: no}]}
  - {id: source, name: Source, type: text, show: detail}
  - {id: discovery_check, name: Discovery check, type: text, show: detail}
  - {id: bugs, name: Bugs, type: list, show: detail, link: jira}
  - {id: test_ids, name: Test IDs, type: list, show: detail, block: test-plan}
  - {id: test_name, name: Test name, type: text, show: detail, block: test-plan}
  - {id: test_description, name: Test description, type: text, show: detail, block: test-plan}
  - {id: test_expected, name: Expected outcome, type: text, show: detail, block: test-plan}
  - {id: test_type, name: Checkbox test type, type: text, show: detail, block: test-plan}
  - {id: test_status, name: Checkbox test status, type: text, show: detail, block: test-plan}
note_keys:                          # extra notes sections, in display order
  - {id: discovery, name: Discovery}
  - {id: x01, name: x01}
  - {id: x02, name: x02}
  - {id: future, name: future MS}
  - {id: qa, name: QA}
columns:
  - {id: p1-x01, name: x01, platform: platform-1, status_set: requirement, note_key: x01}
  - {id: p1-x02, name: x02, platform: platform-1, status_set: requirement, note_key: x02}
  - {id: p1-future, name: future MS, platform: platform-1, status_set: requirement, note_key: future}
  - {id: test, name: Test, group: Test plan, role: test, note_key: qa,
     applies_when: {field: scope, equals: in-scope}}
```

- **Tones** (fixed list, validated): `yes`, `no`, `open`, `neutral`, `info`, `warn`.
  The built-in `default` set is `supported`→`yes`, `unsupported`→`no`, `tbd`→`open`.
  Colours are the builder's choice; the built-in set keeps its current colours and CSS
  classes exactly.
- **`status_set`** absent => `default`. **`note_key`** absent => the column's platform,
  else `general` (today's behaviour).
- **`role: test`** marks the test-conclusion column: it gets no donut on the overview
  (the coverage card replaces it) and is never the default focus column.
- **`applies_when`**: the column only applies to items where the condition holds. A value
  on an item where it does not hold is a validation error; the drawer shows the column
  as "n/a" and read-only; batch skips such items.
- **Note sections for requirement matrices are per phase, not per platform**: Discovery,
  x01, x02, future MS, QA, plus `general`. With a single platform the section names are
  the milestone names; if a second platform gets data, its keys are `p2-x01`, … named
  "Platform #2 · x01" (step 3 confirms names).

### Item shape (requirement matrix)

```yaml
- id: "2.03"                 # string, always double-quoted; the CSV's Req ID
  name: GPU                  # Feature (Component); multi-line joined with a space
  comment: ...               # Requirement Description (optional)
  status: {p1-x01: enabled, test: tbd}
  fields: {scope: in-scope, risk: none, discovery_check: ..., test_name: ...}
  notes: {discovery: ..., x01: ..., qa: ...}
```

Canonical key order: `id, name, label, comment, status, fields, notes`; inside `fields`
the `_meta` field order; inside `notes`: `general`, platforms, then `note_keys` order.
Empty enum/text/list = key absent (not set).

### Validation

- New `validateMeta()`:
  - `template` is `feature-matrix` or `requirement-matrix`;
  - every `status_set` reference exists; `default` is not redefined; set IDs unique;
    tones from the fixed list;
  - field IDs unique, enum value IDs unique, `link` only `jira`;
  - `note_keys` IDs unique and not equal to `general` or a platform ID;
  - `applies_when` names an enum field and one of its values;
  - for `feature-matrix`: `fields`, `status_sets`, `note_keys`, `noun`, `status_set`,
    `note_key`, `role`, `applies_when` are rejected. **Any other unknown `_meta` key is
    still tolerated**, as today.
- Components: requirement IDs match `^[0-9A-Za-z][0-9A-Za-z._-]*$`, must be YAML
  strings (a numeric `id: 2.10` is an error with a clear message), unique across all
  files and distinct from component IDs. Feature-matrix ID rules are unchanged.
- Status values checked against the column's set; field values against their type.
- Item `fields` key is rejected in feature matrices (unknown key, as today).
- **Warning (exit 0)** from `check`: item with `scope: out-of-scope` but a platform
  status other than `out-of-scope`, or the reverse. No automatic sync.

## Requirement-matrix specifics

- **Header:** 3 rows (template info, groups, column names). Headers are matched by
  name with whitespace normalised; platform and milestone names never come from the
  group row (it is misleading) or from placeholder headers — step 3 asks the user.
- **Grouping:** one section "Requirements"; each *Category* is a component with IDs
  `A.1…A.n` in CSV order and files `A.01-<slug>.yaml` as today. A Category that
  reappears after another one is an error (no silent duplicate). Component numbers are
  never derived from Req IDs.
- **Rows without a Req ID** are skipped and reported by the converter.
- **Platform status columns:** Platform #1 and #2 × x01 / x02 / future MS. Columns with
  no data are kept as empty milestones (existing pitfall rule). Empty = not set.
- **Test column:** `test`, built-in YES/NO/TBD set, `applies_when: scope = in-scope`.
  Converter default: `tbd` for in-scope items, absent for others.
- **Fields mapping:** Feature (Component) → `name`; Requirement Description →
  `comment`; Source of Req → `source`; Project Scope → `scope`; Check items in Discovery
  phase → `discovery_check`; Risk → `risk`; the bug / JIRA ID column → `bugs`;
  Test ID, Test Short Name, Test Description, Test expected outcome, Checkbox test
  type, Checkbox test status → the test-plan fields. Unknown enum values fail like
  unknown status values do today.
- **Bugs:** split on commas/whitespace; only tokens matching `[A-Z][A-Z0-9]+-\d+` are
  kept; other tokens are template placeholders and are dropped, with the converter
  printing "dropped N bug tokens". Keys are linked with `jira_url` (any key, not only
  `jira_projects`); no link when `jira_url` is unset.
- **Notes:** text before the first marker → `discovery`; `[x01]` → `x01`, `[x02]` →
  `x02`, future-MS marker → `future`; bracketed text that is not a mapped marker (log
  output like `[    0.258147]`) stays as text. Jira keys in notes are linked as today.
- **Row 0:** template version stored as `template_version`; a version other than `v1.2`
  prints a warning and continues. The "Last Updated" date is dropped.

## UI

- **Statuses everywhere come from the column's set:** counts, resolved/open, donut
  colours, pills, chips, tooltips, editor segments, batch values, sidebar "open items",
  CSV export labels. With the `default` set the markup, classes and text are exactly
  today's.
- **Wording** uses `noun`: headings, "Add requirement", "Delete requirement", empty
  states, commit messages ("… for N requirements"), CSV header, verify output.
- **Overview (requirement matrix only):**
  - per-column donuts for platform columns (no donut for `role: test`);
    Out-of-Scope counts as resolved;
  - **Test coverage** card = YES ÷ in-scope items, with YES / NO / TBD / not-set counts
    among in-scope items;
  - **Risk** card = number of in-scope items with `risk: critical`, linking to
    `#/search?scope=in-scope&risk=critical`.
- **Default focus:** last column with data, excluding `role: test`.
- **Table:** ID, name, `show: table` fields (in `fields` order), status columns. Chip
  filters for Scope and Risk; URL params `scope=` and `risk=`, ANDed with `status=` and
  text, kept when navigating between component and search pages. Critical risk is
  highlighted. Search text also matches text and list fields.
- **Drawer:** comment, Source, Discovery check, Bugs (Jira links), Test plan block
  (fields hidden when empty), notes sections in order Discovery, x01, x02, future MS,
  QA, General — each shown next to its column's status where one exists.
- **Editing:** enums as selects; text fields and test-plan text as textareas; lists as
  comma-separated input normalised on save. The Test column is read-only "n/a" for
  out-of-scope items. Changing Scope from In Scope to Out-of-Scope clears the item's
  Test value on save, with a visible hint before saving.
- **New requirement:** the form asks for the Req ID (required, unique across the site);
  `nextFeatureId` is only used for feature matrices.
- **Batch:** unchanged mechanics on platform and Test columns; values come from the
  chosen column's set and the chosen value resets when the column changes to a set
  without it; out-of-scope items are skipped for the Test column and the confirmation
  says "skipped N out-of-scope"; the meeting note goes to the column's `note_key`
  (`qa` for Test). Missing-item detection looks IDs up per file, not by prefix.
- **CSV export** includes field columns for requirement matrices only.

## Converter / tools

- Mapping file (documented with a full example in `references/mapping.md`) gains
  `template`, `noun`, `id_column`, `header_rows: 3`, `fields` (each with `column` and,
  for enums, a raw→id `values` map), `status_sets`, per-column `status_set`,
  `note_key`, `role`, `applies_when`, `default`, `note_keys`, `notes_head_key`
  (generalises `notes_head_platform`), and marker → note-key maps. A status column may
  have no CSV `column` (filled only by `default`).
- Only `id, name, platform, group, status_set, note_key, role, applies_when` of a column
  are copied into `_meta.yaml`; `column` and `default` are not.
- `verify()` keeps comparing CSV values with YAML values per column; values created by
  `default` are reported on their own line and not counted as CSV values.
- Converter writes requirement IDs double-quoted so its output is already canonical.
- `inspect_csv.py` detects the template first (row 0 starts with "Based on template",
  row 1 contains "Project Execution" and "Test Plan") and drafts the requirement mapping
  by header names; otherwise the existing feature-matrix path runs unchanged.
- `scaffold.py` and the workflow are template-independent; `assets/README.md` gets a
  requirement-matrix section.
- SKILL.md: description also triggers on requirement/scope tracking sheets; step 3
  confirmation, step 6 verification and the report template get requirement variants.

## Isolation proof (tests, all committed)

- **Feature-matrix fixture:** a synthetic CSV in `tests/fixtures/` covering section
  rows with description and notes, a `component_id` column, a `label` column, inline
  first-line marker, `notes_head_platform`, a column with a group and no platform, an
  unmapped `[build]`-style marker, multi-line notes with Jira keys, blank rows, an empty
  milestone column, YES/NO/TBD.
- **Golden files**, created with the current code before any change: the
  `inspect_csv.py` draft, raw converter YAML, YAML after `build.mjs format`, and
  `data.json` built in a fresh temp git repo without tags, compared after parsing and
  removing `generated`. Every later run must match exactly.
- **Committed browser/DOM tests** on the fixture site: overview, component table,
  drawer, editor, batch bar and confirmation text, CSV export output; plus unit tests
  that `batchNoteLine`, `batchCommitMessage` and validation messages are unchanged.
- **Validation tolerance:** a feature `_meta.yaml` with an extra unknown key still
  passes; one with `fields`/`note_keys`/`status_set` fails; a feature item with
  `fields` fails.
- **Local real-data check (never committed):** the same golden comparison against a real
  feature-matrix CSV kept outside the repo, run by hand before and after the change.
- **Requirement matrix:** synthetic CSV in the same template (no customer platform,
  version or product names), unit + browser tests for IDs (incl. `2.10` and `2.08.01`),
  status sets, fields, filters, coverage, risk card, notes phases, Test n/a for
  out-of-scope, scope-change clearing, batch skip, CSV export, bug token dropping,
  scope/status mismatch warning, version warning.

## Decided with the user

Approach A; status words per template; Supported vs Enabled as in the table; Test
column YES/NO/TBD starting at TBD; coverage over in-scope items only; Out-of-Scope
counts as resolved; Test donut replaced by the coverage card; no test conclusion on
out-of-scope items; scope/status mismatch is a warning; bug column keeps Jira keys only;
notes by phase (Discovery, x01, x02, future MS) plus QA; "requirement" wording; other
template versions warn and continue; no batch edit for Scope/Risk.

## Left to the builder

Colours for the new tones, exact card layout, wording of tooltips beyond the table above.
