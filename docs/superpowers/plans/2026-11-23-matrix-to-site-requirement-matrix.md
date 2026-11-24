# matrix-to-site requirement matrix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the matrix-to-site skill turn a requirement-matrix CSV (template v1.2) into the same editable site, with per-template status words, extra fields, phase notes, a QA test column, test coverage and a risk card — without changing anything for feature matrices.

**Architecture:** The template is declared in `_meta.yaml`. Template logic lives in new focused files: `assets/web/template.js` (status sets, fields, coverage, meta validation; pure, Node-testable), `scripts/requirement_matrix.py` (converter + inspector for the requirement template). Existing files dispatch to them only when `template: requirement-matrix`. Before any behaviour change, golden files and DOM snapshots of a synthetic feature matrix are committed; every later task must keep them byte-identical.

**Tech Stack:** Python 3 + PyYAML (scripts, unittest), Node 20+ ES modules (web model, `node --test`), vanilla JS web app, headless Chrome via CDP (browser tests), vendored js-yaml.

**Spec:** `docs/superpowers/specs/2026-11-23-matrix-to-site-requirement-matrix-design.md` — read it first; this plan does not repeat its decisions.

## Global Constraints

- Work only in `matrix-to-site/` and `docs/`; commit locally; **never push** (the user consents to pushes separately).
- No project/company/customer names anywhere in the repo (fixtures, tests, docs, commit messages). Jira keys in fixtures use `PROJ`; Jira site `https://example.atlassian.net/browse/`; platforms `Board X` / `Board Y`.
- Never copy content from a real CSV into the repo. Real CSVs are used only by hand, from outside the repo.
- Feature-matrix output (YAML, `data.json`, DOM, CSV export, commit messages, error texts) must stay byte-identical: the golden tests from Tasks 1–2 must pass after every task.
- Python formatted with `ruff format`, clean under `ruff check` (ruff is a snap: copy files to `~/work/rufftmp` to lint anything under a hidden dir or `/tmp`).
- Full suite after every task: `cd matrix-to-site && timeout 300 python3 -m unittest discover -s tests` → `OK` (it also runs `node --test tests/` and, when `google-chrome` exists, the browser tests).
- Tones: exactly `yes`, `no`, `open`, `neutral`, `info`, `warn`. Reserved status set name: `default`.
- Requirement ID pattern `^[0-9A-Za-z][0-9A-Za-z._-]*$`; Jira key pattern `[A-Z][A-Z0-9]+-\d+`.

## Review Focus

1. A hand-edited unquoted `id: 2.10` (js-yaml reads 2.1) must fail `check` with a message naming the file and saying the id must be a quoted string — test in Task 4.
2. Multi-line or extra-spaced header cells and multi-line requirement names (`"Wi-Fi\n(2.4 GHz)"`) — header matching normalises whitespace, names are joined with one space — test in Task 5.
3. Log text in notes such as `[    0.258147]` or a marker in mid-line must stay text, not start a phase section — test in Task 5.
4. Switching the batch column from a platform column (requirement set) to Test (default set) while `enabled` is chosen must reset the chosen value, and Test batches must skip out-of-scope items — test in Task 9.
5. An out-of-scope item with `risk: critical` must not count in the Risk card, and an out-of-scope item must never count in coverage — test in Task 8.

---

### Task 1: Feature-matrix golden files (converter, inspector, build)

**Files:**
- Create: `matrix-to-site/tests/fixtures/feature.csv`, `matrix-to-site/tests/fixtures/feature-mapping.yaml`
- Create: `matrix-to-site/tests/golden_tool.py`
- Create: `matrix-to-site/tests/golden/feature/` (generated, committed)
- Modify: `matrix-to-site/tests/test_matrix_to_site.py` (add `GoldenFeatureTest`)

**Interfaces:**
- Produces: `python3 tests/golden_tool.py --csv <csv> --mapping <yaml> --golden <dir> [--update]` → exit 0 when identical, 1 with a unified diff otherwise. Golden dir layout: `inspect.yaml` (inspect_csv.py stdout), `raw/*.yaml` (converter output), `formatted/*.yaml` (after `build.mjs format`), `data.json` (parsed, `generated` removed, `json.dumps(indent=1, ensure_ascii=False, sort_keys=False)`), `verify.txt` (converter stdout).
- `golden_tool.build_site(csv, mapping, workdir) -> Path` creates a fresh `git init` repo in `workdir` (no tags), runs `scaffold.py --deploy-branch matrix-table-golden --mapping`, `convert_csv.py`, `build.mjs format`, `build.mjs build dist`, returns the dist dir. Task 2 reuses it.

- [ ] **Step 1: Write the fixture.** `feature.csv` (2 header rows) must contain each of: section row with description and notes; `component_id` column with `A.1.0`-style rows; a `label` column; a notes cell whose first line has an inline `[BoardY]` marker; a cell with text before the first marker; a status column with `group` and no platform; an unmapped `[build]` marker inside pasted log text; multi-line notes containing `PROJ-7`; blank rows; an empty milestone column; YES, NO and TBD values; at least 2 sections, 4 components, 12 features. `feature-mapping.yaml` uses `notes_head_platform`, `notes_default_platform`, `notes_markers` (`BoardY`, plus an alias), `jira_projects: [PROJ]`, `jira_url: https://example.atlassian.net/browse/`.
- [ ] **Step 2: Write `GoldenFeatureTest.test_matches_golden`** — runs `golden_tool.py` without `--update` against `tests/golden/feature`, asserts exit 0. Add `test_fixture_covers_paths`: converts the fixture and asserts a section has notes, a component has description, a feature has `label`, a `board-y` note came from an inline marker, some note text still contains `[build]`, some note contains `PROJ-7`, one column has 0 values. Skip both when `node` is missing.
- [ ] **Step 3: Run** `python3 -m unittest tests.test_matrix_to_site.GoldenFeatureTest -v` → FAIL (golden tool / files missing).
- [ ] **Step 4: Implement `golden_tool.py`** (compare every file in the golden dir and the generated set both ways; `--update` rewrites the dir).
- [ ] **Step 5: Generate the golden files with the current, unmodified code:** `python3 tests/golden_tool.py --csv tests/fixtures/feature.csv --mapping tests/fixtures/feature-mapping.yaml --golden tests/golden/feature --update`. Open the outputs and confirm they look right (counts in `verify.txt` all `OK`).
- [ ] **Step 6: Run** the class again → PASS; full suite → OK.
- [ ] **Step 7: Local real-data baseline (not committed).** With the current code, run `golden_tool.py --update` on the real feature CSV and its mapping (paths given by the controller, outside the repo) into `~/work/golden-real-feature`. Never commit these paths or files.
- [ ] **Step 8: Commit** `matrix-to-site: golden files for feature-matrix output`.

### Task 2: Committed browser tests with DOM golden snapshots

**Files:**
- Create: `matrix-to-site/tests/browser/cdp.mjs` (from the CDP driver pattern: `launch(port)`, `goto`, `waitFor`, `evaluate`, `click`, `setField`, `close`; user-data-dir under `os.tmpdir()`)
- Create: `matrix-to-site/tests/browser/fake_github.mjs`
- Create: `matrix-to-site/tests/browser/feature.e2e.mjs`, `matrix-to-site/tests/browser/run.mjs`
- Create: `matrix-to-site/tests/golden/feature/dom/*.html`, `matrix-to-site/tests/golden/feature/dom/export.csv`, `matrix-to-site/tests/golden/feature/dom/batch-commit.txt`
- Modify: `matrix-to-site/tests/test_matrix_to_site.py` (add `BrowserTest`, skipped without `google-chrome`)

**Interfaces:**
- Consumes: `golden_tool.build_site` (Task 1).
- Produces: `fakeGithub(page, { repo, branch, files: Map<path,string> })` — enables CDP `Fetch` for `https://api.github.com/*` and answers the calls `app.js` makes (contents listing, blobs, matching-refs → `[]`, `user`, contents PUT, git data API: refs, commits, trees, blobs POST, ref PATCH), keeping files in memory; returns `{ files, commits: [{message, changes:{path:text}}] }`.
- Produces: `snapshot(page, name, goldenDir, update)` — stores `#content`, `#drawer`, `#batch-bar`, `#dialog` `outerHTML` with dates (`\d{4}-\d{2}-\d{2}`), ISO times and 7/40-hex shas replaced by placeholders.
- `node tests/browser/run.mjs [--update] <suite>` runs `feature` (Task 2) and later `requirement` (Tasks 8–9); exit 0/1.

- [ ] **Step 1: Write `feature.e2e.mjs`** scenarios, each ending in `snapshot`: `overview`, `overview-focus-<other column>` (click a donut), `component` (`#/c/A.1`), `search-tbd` (`#/search?status=tbd`), `drawer-feature` (`?open=A.1.1`), `drawer-component`, `editor` (signed in via `localStorage matrixTable.settings` token `test`, click Edit), `batch-bar` (tick 2 rows, pick column + YES), `batch-confirm` (Apply, with note `agreed`), then confirm and write the fake commit's message + changed file texts to `batch-commit.txt`; CSV export captured by overriding `URL.createObjectURL` to stash the Blob text → `export.csv`. Also assert `page.errors` is empty.
- [ ] **Step 2: Run** `node tests/browser/run.mjs feature` → FAIL (no golden files).
- [ ] **Step 3: Implement** `cdp.mjs`, `fake_github.mjs`, `run.mjs`; serve the built dist with a Node `http` static server on a free port.
- [ ] **Step 4: Generate golden** with current code: `node tests/browser/run.mjs --update feature`; read the snapshots, confirm they show the expected page states.
- [ ] **Step 5: Run** without `--update` twice → PASS both times (proves snapshots are stable). Add `BrowserTest.test_feature_dom` calling it; full suite → OK.
- [ ] **Step 6: Commit** `matrix-to-site: committed browser tests with feature-matrix DOM golden`.

### Task 3: `template.js` status sets and template helpers; model batch helpers

**Files:**
- Create: `matrix-to-site/assets/web/template.js`
- Modify: `matrix-to-site/assets/web/model.js:171-216`
- Test: `matrix-to-site/tests/template.test.mjs`, `matrix-to-site/tests/batch.test.mjs` (existing tests unchanged, new ones added)

**Interfaces (all exported from `template.js`):**
- `TONES = ["yes","no","open","neutral","info","warn"]`
- `isRequirement(meta) -> boolean`
- `noun(meta, n) -> string` — `"feature"`/`"features"` by default, from `meta.noun` otherwise; `n === 1` singular.
- `statusSet(meta, column) -> [{id,label,resolved,tone,title}]` — `STATUSES` (with tones `yes`/`no`/`open` added) when `column.status_set` is absent or `default`.
- `statusInfo(meta, column, value) -> {label, title, cls}` — `cls` is the value id for the default set (keeps today's CSS classes) and `tone-<tone>` otherwise; `"unset"` → `{label:"—", title:"Not set", cls:"unset"}`.
- `tally(features, meta, column) -> {values:{<id>:n}, unset, resolved, open, total}` where `open` = unresolved ids, `total` includes unset.
- `noteKeyFor(column) -> column.note_key ?? column.platform ?? "general"`
- `noteOrder(meta) -> ["general", ...platform ids, ...note_keys ids]`
- `applies(column, item) -> boolean` — true without `applies_when`, else `item.fields?.[field] === equals`.
- `testColumn(meta) -> column|undefined` (`role: "test"`)
- `coverage(features, meta) -> {inScope, yes, no, tbd, unset, pct}` — only items where `applies(testColumn)`; `pct = Math.round(yes / inScope * 100)` (0 when `inScope` is 0).
- `criticalInScope(features, meta) -> feature[]` — `fields.scope === "in-scope" && fields.risk === "critical"`.
- model.js: `batchNoteLine(date, columnName, old, new, note, set = STATUSES)`, `batchCommitMessage(columnTitle, value, n, { set = STATUSES, nouns = ["feature","features"] } = {})`, `applyBatch(doc, ids, column, value, { ..., applies = () => true, own })` — items where `applies(item)` is false go to a new `notApplicable` list and are untouched; when `own` (a Set) is given, `missing = ids ∩ own − present`, else today's prefix rule.

- [ ] **Step 1: Write tests** in `template.test.mjs`: `statusSet` default equals the 3 built-in ids; requirement set from the spec's `_meta` example returns 5 ids; `statusInfo(..., "supported")` on default → `cls "supported"`, label `YES`; on requirement set `"enabled"` → `cls "tone-info"`, label `Enabled`; `tally` on `[supported, enabled, out-of-scope, tbd, unset]` with the requirement set → `resolved 3, open 1, unset 1, total 5`; `coverage` on 3 in-scope (yes, tbd, unset) + 1 out-of-scope with test absent → `{inScope:3, yes:1, no:0, tbd:1, unset:1, pct:33}`; `criticalInScope` ignores an out-of-scope critical item; `noun` default/plural/requirement. In `batch.test.mjs` add: requirement-set labels in `batchNoteLine` (`Enabled → Supported`), `batchCommitMessage` with `nouns: ["requirement","requirements"]`, `applyBatch` with `applies` returning false for one id → it lands in `notApplicable`, `own` set reports `2.99` as missing.
- [ ] **Step 2: Run** `node --test tests/` → new tests FAIL, existing PASS.
- [ ] **Step 3: Implement** `template.js` and the optional parameters in model.js (defaults reproduce today's outputs exactly).
- [ ] **Step 4: Run** `node --test tests/` → PASS; full suite (golden + DOM) → OK.
- [ ] **Step 5: Commit** `matrix-to-site: template helpers and status sets`.

### Task 4: Meta and requirement validation; `check` warnings

**Files:**
- Modify: `matrix-to-site/assets/web/template.js` (add `validateMeta`, `consistencyWarnings`)
- Modify: `matrix-to-site/assets/web/model.js` (`normalizeFeature`, `orderedNotes`, `validateComponent`)
- Modify: `matrix-to-site/assets/tools/build.mjs`
- Test: `matrix-to-site/tests/validate.test.mjs`, `matrix-to-site/tests/test_matrix_to_site.py` (build check cases)

**Interfaces:**
- `validateMeta(meta) -> string[]` — the rules in the spec's "Validation" section, messages prefixed `_meta.yaml: `.
- `consistencyWarnings(components, meta) -> string[]` — scope vs platform `out-of-scope` mismatch, one line per item: `<id>: scope is <scope label> but <column title> is <label>`.
- `normalizeFeature` adds `fields` after `status` (keys in `meta.fields` order, empty values dropped, lists as arrays of strings); `orderedNotes` uses `noteOrder(meta)`; FEATURE_KEYS gets `fields` only for requirement matrices.
- `validateComponent` for requirement matrices: component id `^[A-Z]\.\d+$` as today; item id must be a string matching the requirement pattern (non-string → `id must be a quoted string, e.g. "2.10"`); status values per column set; `applies_when` violations; fields by type and enum values; note keys from `noteOrder`. Feature path unchanged.
- `build.mjs`: runs `validateMeta` first; adds component-id vs item-id collision check; prints `warning: …` lines from `consistencyWarnings` (exit code unaffected); `check` summary uses `noun(meta, n)` (`OK: 4 components, 9 requirements`; feature text unchanged).

- [ ] **Step 1: Write tests** (`validate.test.mjs`): feature meta with an extra unknown key → `[]`; feature meta with `fields`, `note_keys` or a column `status_set` → error each; feature item with `fields` → `unknown key "fields"` (exact existing wording); requirement meta from the spec example → `[]`; unknown tone, undefined set, note key `general`, `applies_when` on a text field → errors; requirement item `id: 2.1` (number) → quoted-string error; `id: "2.08.01"` valid; enum value `maybe` → error naming allowed ids; test value on an out-of-scope item → error; scope out-of-scope + `p1-x01: supported` → one warning. In `test_matrix_to_site.py` add `test_unquoted_numeric_id_fails_check` (write a requirement data dir by hand, `id: 2.10` unquoted → `check` exit 1, stderr mentions the file and "quoted string").
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** node tests, unittest, golden + DOM → all PASS.
- [ ] **Step 5: Commit** `matrix-to-site: validate template metadata and requirement items`.

### Task 5: Requirement converter

**Files:**
- Create: `matrix-to-site/scripts/requirement_matrix.py`
- Modify: `matrix-to-site/scripts/convert_csv.py` (`main`: `RequirementConverter` when `mapping.get("template") == "requirement-matrix"`; nothing else)
- Create: `matrix-to-site/tests/fixtures/requirement.csv`, `matrix-to-site/tests/fixtures/requirement-mapping.yaml`
- Modify: `matrix-to-site/references/mapping.md` (requirement section with a full example)
- Test: `matrix-to-site/tests/test_requirement_matrix.py`

**Interfaces:**
- `RequirementConverter(mapping)` with `run(csv_path)`, `meta() -> dict`, `write(out_dir)`, `verify() -> bool`, attributes `components`, `skipped_rows: list[int]` (1-based CSV line numbers), `dropped_bug_tokens: Counter`.
- Mapping keys (document in `references/mapping.md`): `template`, `noun`, `header_rows: 3`, `id_column`, `columns: {category, name, comment, notes}`, `fields: [{id, column, ..., values: {raw: id}}]` (the `_meta` field definition plus `column` and raw map), `status_sets`, `status_values: {<set>: {raw: id}}`, `status_columns` entries with `status_set`, `note_key`, `role`, `applies_when`, `default: {value, when: {field, equals}}`, optional `column`; `note_keys`, `notes_markers: {x01: x01, ...}`, `notes_head_key: discovery`, `notes_default_key: discovery`.
- `_meta.yaml` gets `template`, `template_version`, `noun`, `status_sets`, `fields` (without `column`/raw maps), `note_keys`, and columns with only `id, name, platform, group, status_set, note_key, role, applies_when`.

**Fixture** (`requirement.csv`, columns as in the template; Bug column header `Bug#\nor JIRA ID#`; row 0 `Based on template: ,v1.2,,Last Updated:,2025-04-16`; row 1 groups incl. `"Project Execution\n[Platform#1]"` and `Test Plan`):

| Req ID | Category | Name | Scope | Risk | Notes | Bugs | P1 x01 |
|---|---|---|---|---|---|---|---|
| 1.01 | General | OS Version | In Scope | None | `[x01]\nos-release` | `LP#001, LP#002` | Supported |
| 1.02 | General | Kernel | In Scope | None | `uname desktop\n\n[x01]\nuname image` | | Supported |
| 2.01 | Hardware Configuration | CPU | In Scope | None | `lscpu\n[    0.258147] boot log\n\n[x01] the same` | `bug#10` | Supported |
| 2.03 | Hardware Configuration | GPU | In Scope | Critical | `PROJ-12: needs workaround\n\n[x01]\nworks with component` | `PROJ-12` | Enabled |
| 2.08.01 | Hardware Configuration | `Wi-Fi\n(2.4 GHz)` | Out-of-Scope | Critical | | | Out-of-Scope |
| 2.10 | Hardware Configuration | Display | In Scope | *(empty)* | | | Enabled |
| 2.16 | Hardware Configuration | Watchdog | In Scope | Critical | `PROJ-15: driver missing` | | Not supported |
| 3.01 | Security | Secure Boot | In Scope | None | | | *(empty)* |
| 4.01 | Process | Release Notes | Out-of-Scope | None | | | Out-of-Scope |
| *(empty)* | | | | | | | *(only Checkbox type/status filled)* |

2.01 also has Test ID `cpu-001`, Test Short Name `- cpu/clocktest\n- cpu/maxfreq`; every row has Checkbox type `Automated`, status `Implemented`. Platform #2 columns are empty. The mapping names platforms `Board X` (`platform-1`) and `Board Y` (`platform-2`), all six columns kept, note keys `discovery, x01, x02, future, p2-x01, p2-x02, p2-future, qa`.

- [ ] **Step 1: Write tests** (`test_requirement_matrix.py`): 9 items, components `A.1 General, A.2 Hardware Configuration, A.3 Security, A.4 Process`, item ids exactly the Req IDs; `skipped_rows` has the trailing row; `p1-x01` values `{supported:3, enabled:2, not-supported:1, out-of-scope:2}` and 3.01 has no `p1-x01`; `test` is `tbd` on the 7 in-scope items, absent on 2.08.01 and 4.01; 2.03 `fields.bugs == ["PROJ-12"]`, `dropped_bug_tokens` total 3; 2.08.01 name `Wi-Fi (2.4 GHz)`; 2.10 has no `risk`; notes: 1.01 `{x01}`, 1.02 `{discovery, x01}`, 2.01 discovery contains `[    0.258147] boot log`, 2.16 `{discovery}`; `meta()["template_version"] == "v1.2"`; `verify()` true and prints the defaults line `test: 7 set by default (not from CSV)` and `dropped 3 bug tokens`; a second CSV where Category `General` reappears after `Security` → `SystemExit` naming the category; header cells with doubled spaces/newlines still map; the written YAML passes `build.mjs check` with no warnings and is unchanged by `build.mjs format` (ids double-quoted); `template_version: v1.1` CSV prints `warning: template version v1.1` and still converts.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_requirement_matrix -v` → FAIL.
- [ ] **Step 3: Implement** `RequirementConverter` (own class, reusing `read_csv`, `clean`, `slug`, `prune`, `IndentDumper` from `convert_csv`; the feature `Converter` is not modified). Emit item ids as double-quoted scalars (custom representer for a `QuotedStr` subclass).
- [ ] **Step 4: Run** → PASS; full suite (golden + DOM) → OK.
- [ ] **Step 5: Commit** `matrix-to-site: convert requirement-matrix CSVs`.

### Task 6: Inspector detects the requirement template

**Files:**
- Modify: `matrix-to-site/scripts/requirement_matrix.py` (add `detect(rows) -> str | None`, `draft_mapping(rows) -> dict`)
- Modify: `matrix-to-site/scripts/inspect_csv.py` (`main`: if `detect(rows)` returns a version, print `requirement_matrix.draft_mapping(rows)` as YAML and return; feature path untouched)
- Test: `matrix-to-site/tests/test_requirement_matrix.py`

**Interfaces:**
- `detect(rows)` → `"v1.2"` (the version text) when row 0 col 0 starts with `Based on template` and row 1 contains `Project Execution` and `Test Plan` (whitespace-normalised); else `None`.
- `draft_mapping(rows)` locates columns by header name (whitespace-normalised, case-insensitive; the bug column by containing `JIRA ID`), fills the spec's status set, field definitions, raw value maps from the values present, six status columns with placeholder platform names `Platform 1` / `Platform 2` and a `# CONFIRM` comment, `test` column, note keys, markers found (`[x\d\d]`), and prints counts (values per column, empty columns, rows without Req ID, bug tokens that are not Jira keys) to stderr.

- [ ] **Step 1: Write tests**: `detect` on the fixture → `"v1.2"`, on `feature.csv` → `None`; `draft_mapping(fixture)` round-trips through `RequirementConverter` with only platform names changed and reproduces Task 5's YAML; stderr mentions `1 row without Req ID` and `3 bug tokens are not Jira keys`; the feature golden `inspect.yaml` still matches (Task 1 test).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS; full suite OK.
- [ ] **Step 5: Commit** `matrix-to-site: detect and draft requirement-matrix mappings`.

### Task 7: Web app reads statuses from the column's set (no visible change)

**Files:**
- Modify: `matrix-to-site/assets/web/app.js` (every use of `STATUSES`, `counts`, `resolvedOf`, `totalOf`, `statusLabel`, `statusTitle`, `pill`, `chipOrder`, `BATCH_VALUES`, `donut` colours, `openBadge`, `openLine`, sidebar "Open items", stat cards, legend, `exportCsv` labels, `batchPreview` note key, `platformName` for note keys)
- Modify: `matrix-to-site/assets/web/style.css` (add `.tone-*` classes for `pill`, `count`, `seg button.on`, `bar`, `stat`; existing rules untouched)

**Interfaces:**
- Consumes: `statusSet`, `statusInfo`, `tally`, `noteKeyFor`, `noteOrder`, `noun` (Task 3).
- `pill(column, value)`, `statusLabel(column, value)`, `statusTitle(column, value)` take the column; `counts(features, column)` returns `tally(...)`; overview/sidebar/list read `c.values[id]`, `c.resolved`, `c.open`, `c.unset`, `c.total`.
- Note headers use `note_keys[].name` via a `noteName(key)` helper; batch note key = `noteKeyFor(column)`.

- [ ] **Step 1:** Make the refactor with the feature DOM golden as the test: `node tests/browser/run.mjs feature` must stay PASS. Keep every string and class the default set produces identical.
- [ ] **Step 2: Run** full suite → OK (golden, DOM, node, unittest).
- [ ] **Step 3: Commit** `matrix-to-site: web UI reads statuses per column set`.

### Task 8: Requirement views (overview, table, filters, drawer, wording)

**Files:**
- Modify: `matrix-to-site/assets/web/app.js` (`viewOverview`, `viewComponent`, `viewSearch`, `renderList`, `matches`, `featureView`, `renderSidebar`, `load` focus, `route` params), `matrix-to-site/assets/web/style.css`
- Create: `matrix-to-site/tests/browser/requirement.e2e.mjs`

**Interfaces:**
- Consumes: `coverage`, `criticalInScope`, `testColumn`, `isRequirement`, `applies`, `noun` (Task 3); requirement fixture built with `golden_tool.build_site` (Task 1) from Task 5's fixture.
- Search/component pages read `scope` and `risk` params (`#/search?scope=in-scope&risk=critical`), ANDed with `status` and text; chips for each enum value of `filter: true` fields; links keep the params.
- Overview for requirement matrices: no donut for `role: test`; `Test coverage` card (`<pct>%`, `YES n · NO n · TBD n · not set n`, `of N in-scope requirements`); `Risk` card (`N critical in scope`, href `#/search?scope=in-scope&risk=critical`). Default focus excludes `role: test`.
- Table: `show: table` fields after the name column; `risk: critical` cell has class `risk-critical`; Test cell shows `n/a` when `!applies`. Drawer: comment, Source, Discovery check, Bugs (Jira links with `jira_url`), Test plan block (empty fields hidden), notes in `noteOrder`, each phase note card beside its column's pill.

- [ ] **Step 1: Write `requirement.e2e.mjs`** (assertions, no snapshots): overview shows `0%` coverage with `YES 0 · NO 0 · TBD 7 · not set 0` and `of 7 in-scope requirements`; Risk card says `2` and its link lists exactly 2.03 and 2.16; no Test donut; focus is `p1-x01`; `p1-x01` donut shows `89%` resolved (8 of 9: supported 3 + enabled 2 + not-supported 1 + out-of-scope 2; 3.01 not set); `#/search?risk=critical` lists 2.03, 2.08.01, 2.16, adding `scope=in-scope` drops 2.08.01; row 4.01 Test cell `n/a`; `?open=2.03` drawer shows `PROJ-12` linked to `https://example.atlassian.net/browse/PROJ-12`, Discovery and x01 note cards, no Test plan block; `?open=2.01` drawer shows the Test plan block with `cpu-001`; text search `clocktest` finds 2.01; headings say "requirements"; `page.errors` empty.
- [ ] **Step 2: Run** `node tests/browser/run.mjs requirement` → FAIL. **Step 3: Implement.** **Step 4: Run** requirement → PASS, feature DOM golden → PASS; add `BrowserTest.test_requirement_ui`; full suite OK.
- [ ] **Step 5: Commit** `matrix-to-site: requirement-matrix views`.

### Task 9: Requirement editing, batch and CSV export

**Files:**
- Modify: `matrix-to-site/assets/web/app.js` (`featureEditor`, `startEdit`, `saveDraft`, `renderDrawer` new-item path, `renderBatchBar`, batch-column change handler, `batchPreview`, `openBatchConfirm`, `saveBatch`, `exportCsv`)
- Modify: `matrix-to-site/tests/browser/requirement.e2e.mjs`

**Interfaces:**
- Consumes: `applyBatch` `applies`/`own` options, `batchCommitMessage` `set`/`nouns`, `batchNoteLine` `set` (Task 3); `validateComponent` (Task 4).
- Editor: enum fields as `<select data-field="<id>">` (plus empty option), text fields as `<textarea data-field>`, list fields as `<input data-field data-list>` (comma-separated, trimmed, empty dropped); Test segment disabled with `n/a` when `!applies`; when the draft's scope becomes not in-scope and the item has a Test value, show `.hint` "Test result will be cleared" and delete it on save.
- New requirement: form has `<input data-field-id>` (required); save refuses an id already in `state.index` or equal to a component id, with an inline error; `nextFeatureId` only for feature matrices.
- Batch: value buttons from `statusSet(batchColumn())`; changing the column clears `state.batch.value` when the new set lacks it; Test column → `applies` skip, confirmation line `skipped N out-of-scope`; note goes to `noteKeyFor(column)`; commit message via `batchCommitMessage(title, value, n, {set, nouns})`; `own` = ids mapped to that entry.
- CSV export (requirement only): extra columns after Comment in `meta.fields` order (lists joined with `, `), status labels from each column's set, notes columns in `noteOrder`.

- [ ] **Step 1: Extend `requirement.e2e.mjs`** with the fake GitHub: edit 2.10 risk → Critical, save → committed YAML has `risk: critical` and `id: "2.10"`; edit 1.02 scope → Out-of-Scope shows the hint, save → `test` removed; create requirement `5.01` in `Process` → saved, a second `5.01` → inline duplicate error, `A.1` → error; batch tick 2.03, 2.08.01, 3.01, pick `p1-x01` + `Enabled`, switch column to Test → no value selected, pick YES with note `reviewed` → confirm says `skipped 1 out-of-scope`, commit message `matrix-table: set Test to YES for 2 requirements`, 2.03 notes `qa` ends with `· Test: TBD → YES — reviewed`; overview coverage then `33%` and `of 6 in-scope requirements` (1.02 was moved out of scope above; the new 5.01 has no scope, so it is not counted); CSV export header contains `Scope`, `Risk`, `Test IDs` and a `Discovery notes` column, row 2.03 has `Enabled`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** requirement + feature DOM golden → PASS; full suite OK.
- [ ] **Step 5: Commit** `matrix-to-site: edit and batch requirement matrices`.

### Task 10: Skill docs, end-to-end check, real-data checks

**Files:**
- Modify: `matrix-to-site/SKILL.md` (description also covers requirement / scope tracking sheets; step 3 confirmation variant: platform names, phase markers, which Platform columns to keep; step 6 verification variant incl. dropped bug tokens and skipped rows; report template with the requirement status words and coverage; pitfalls: numeric ids)
- Modify: `matrix-to-site/assets/README.md` (requirement section: fields, status words, Test column, notes phases)
- Modify: `matrix-to-site/tests/test_matrix_to_site.py` (`test_end_to_end_build_requirement`: scaffold + convert requirement fixture + format/check/build)

- [ ] **Step 1: Write and run** `test_end_to_end_build_requirement` → PASS (it only exercises Tasks 4–6; if it fails, fix the code, not the test).
- [ ] **Step 2: Update docs.** Run the sensitive-name scan the controller provides (the pattern is not stored in the repo) over `matrix-to-site` and `docs` → no matches.
- [ ] **Step 3: Full verification:** full suite OK; `ruff format --check` + `ruff check` clean; `golden_tool.py` without `--update` on the same real feature CSV and mapping as Task 1 Step 7 against `~/work/golden-real-feature` → exit 0 (real feature data unchanged).
- [ ] **Step 4: Real requirement CSV, local only:** in a temp repo outside the skill repo, run `inspect_csv.py` on the real requirement CSV (path given by the controller), then convert, `check`, build and open the site headless; record counts (requirements, per-column values, dropped bug tokens, skipped rows, warnings) for the report. Nothing from it is committed.
- [ ] **Step 5: Sync the installed skill** (`rsync -a --delete --exclude=__pycache__ matrix-to-site/ ~/.agents/skills/matrix-to-site/`, then `diff -rq`).
- [ ] **Step 6: Commit** `matrix-to-site: document requirement matrices`. Do not push.
