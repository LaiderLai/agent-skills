# matrix-to-site requirement matrix revision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Switch the requirement-matrix template to the revised definitions: Out-of-Scope items ignored, execution statuses Supported/Enabled/Not supported with "done", automatic EA/FC/GA phases on one platform, whole notes to Discovery, a risk dashboard.

**Architecture:** One new meta key `exclude_when` drives "ignored" everywhere through a single helper `excluded(meta, item)` in `assets/web/template.js`; counts, cards, filters, batch and export call it. The converter (`scripts/requirement_matrix.py`) stops reading non-Requirements columns for excluded rows and no longer splits notes. Feature matrices are untouched; their goldens guard that.

**Tech Stack:** Python 3 + PyYAML (unittest), Node ES modules (`node --test`), vanilla JS web app, headless Chrome browser tests (`tests/browser/run.mjs`).

**Spec:** `docs/superpowers/specs/2026-11-24-matrix-to-site-requirement-matrix-revision-design.md` (revises `docs/superpowers/specs/2026-11-23-matrix-to-site-requirement-matrix-design.md`; read both, the revision wins).

## Global Constraints

- Work in `matrix-to-site/` and `docs/`; commit locally; **never push**.
- Feature-matrix output byte-identical: `tests/golden/feature/**` and the feature DOM goldens must pass after every task; never run `--update` on existing golden files.
- No company/customer/project names or personal paths in committed files or messages (fixtures use `PROJ`, `example.atlassian.net`, `Board X`).
- Never read a real CSV in tests; fixtures are synthetic.
- Python `ruff format` + `ruff check` clean; no new npm dependencies.
- Full suite after every task, from `matrix-to-site/`: `timeout 900 python3 -m unittest discover -s tests` → `OK`.
- Requirement statuses: ids `supported`, `enabled`, `not-supported` only; done = `supported` or `enabled`. Scope ids `in-scope`, `out-of-scope`, `tbd`. Phase column ids `ea`, `fc`, `ga`; note keys `discovery`, `ea`, `fc`, `ga`, `qa`.

## Review Focus

1. An item whose Scope is **empty** must count as not excluded in every denominator (phase done %, risk, coverage) — tests in Tasks 1 and 3.
2. A requirement with Risk **empty** counts as risky; Risk `none` does not — tests in Tasks 1 and 3.
3. Toggling Scope to Out-of-Scope in the editor and back must restore the hidden statuses/fields/notes unchanged in the saved YAML — test in Task 4.
4. An excluded item carrying a status/fields/notes (hand-edited YAML) passes `check` but appears in no count, card, filter chip count or batch — tests in Tasks 1 and 3.
5. `[x01]` text inside Notes must stay inside the Discovery note, not create an EA note — test in Task 2.

---

### Task 1: Data model — exclusion, done, risk helpers, validation

**Files:**
- Modify: `matrix-to-site/assets/web/template.js`, `matrix-to-site/assets/web/model.js`, `matrix-to-site/assets/tools/build.mjs`
- Test: `matrix-to-site/tests/template.test.mjs`, `matrix-to-site/tests/validate.test.mjs`, `matrix-to-site/tests/batch.test.mjs`

**Interfaces (produced, used by Tasks 3–4):**
- `excluded(meta, item) -> boolean` — true iff `meta.exclude_when` is set and `item.fields?.[field] === equals`.
- `included(features, meta) -> feature[]` — the non-excluded ones.
- `tally(features, meta, column)` unchanged signature; callers pass `included(...)` for requirement matrices.
- `done(features, meta, column) -> {done, total, pct}` over `included` features: done = statuses with `resolved: true`; `pct = Math.round(done / total * 100)`, 0 when total is 0.
- `risky(features, meta) -> feature[]` — included items whose `fields.risk !== "none"` (empty/absent counts).
- `riskDone(features, meta, column) -> {done, total, pct, items}` — `risky` items, done on `column`.
- `coverage(features, meta)` — same return shape, keys renamed: `{total, yes, no, tbd, unset, pct}` over `included` features (replaces `inScope`).
- Removed: `criticalInScope`, `consistencyWarnings` (and its call in `build.mjs`), `applies`, column `applies_when`. `applyBatch`'s `applies` option stays (callers pass `(f) => !excluded(meta, f)`).
- `validateMeta`: accepts `exclude_when: {field, equals}` (must name an enum field and one of its values; must be a mapping); rejects it for feature matrices like other requirement-only keys. The `applies_when` checks are removed; for feature matrices `applies_when` stays in the requirement-only column key list, so a feature column carrying it is still rejected.
- `validateComponent`: no "does not apply" error; values on excluded items are type-checked as usual.

- [ ] **Step 1: Write failing tests** with this meta (subset of the spec example): `exclude_when: {field: scope, equals: out-of-scope}`, set `execution` = supported(resolved true), enabled(true), not-supported(false), scope enum in-scope/out-of-scope/tbd, risk enum none/critical, columns `ea`, `fc` (status_set execution) and `test` (role test, default set). Items: A in-scope risk none ea supported; B in-scope risk critical ea enabled; C scope tbd risk absent ea not-supported; D scope absent risk critical ea absent; E out-of-scope risk critical ea supported test supported. Assert: `included` = A,B,C,D; `done(..., ea)` = `{done: 2, total: 4, pct: 50}`; `risky` = B,C,D; `riskDone(..., ea)` = `{done: 1, total: 3, pct: 33}`; `coverage` with A test supported, B test tbd, others absent = `{total: 4, yes: 1, no: 0, tbd: 1, unset: 2, pct: 25}`; `validateMeta` errors for `exclude_when` on a text field, on an unknown value, as a non-mapping, and on a feature meta; `validateComponent` accepts E with all its data; `applyBatch` with `applies: f => !excluded(meta, f)` puts E in `notApplicable`.
- [ ] **Step 2: Run** `node --test tests/` → new tests FAIL.
- [ ] **Step 3: Implement.** Update existing tests that referenced removed helpers (`criticalInScope`, `consistencyWarnings`, `applies_when`) to the new model; do not touch feature-path tests.
- [ ] **Step 4: Run** `node --test tests/` → PASS; full suite → OK (requirement browser suite may fail until Task 3 — if so, mark that test `skip` with reason "revised in Task 3" and note it in the report; feature suites must pass).
- [ ] **Step 5: Commit** `matrix-to-site: requirement exclusion, done and risk helpers`.

### Task 2: Converter, inspector, fixture

**Files:**
- Modify: `matrix-to-site/scripts/requirement_matrix.py`, `matrix-to-site/references/mapping.md`
- Modify: `matrix-to-site/tests/fixtures/requirement.csv`, `matrix-to-site/tests/fixtures/requirement-mapping.yaml`
- Test: `matrix-to-site/tests/test_requirement_matrix.py`

**Interfaces:**
- Consumes: `_meta` shape from the spec (Task 1 validates it).
- Mapping: `exclude_when` (copied to `_meta`), one platform, `status_columns` `ea`/`fc`/`ga` (+ `test` with `default: {value: tbd}` and no `when`, meaning every non-excluded item), field `jira` (`link: jira`, `block: execution`), `risk` and `discovery_check` with `block: discovery`, scope `raw_values` incl. `"TBD": tbd`; no `notes_markers`; `notes_default_key: discovery`.
- `RequirementConverter`: for an excluded row reads only `name`, `comment`, `source`, `scope`; counts it in `excluded_items`; never reads its status/notes/other fields (so its raw values are never unknown and never counted).
- `verify()` prints `out-of-scope: N items, their other columns ignored` (always, also N = 0).
- `draft_mapping(rows)`: Platform #1 headers x01/x02/future MS → columns `ea`/`fc`/`ga` named EA/FC/GA; Platform #2 not drafted; platform `{id: platform-1, name: "Platform 1"}  # CONFIRM`; scope raw values from the data plus `TBD`.

**Fixture** (`requirement.csv`; template header as today; columns: Req ID | Category | Name | Scope | Risk | Notes | Bug/JIRA | P1 x01 | P1 x02):

| 1.01 | General | OS Version | In Scope | None | `[x01]\nos-release` | `LP#001, LP#002` | Supported | Enabled |
| 1.02 | General | Kernel | In Scope | None | `uname desktop\n\n[x01]\nuname image` | | Supported | |
| 2.01 | Hardware Configuration | CPU | In Scope | None | `lscpu\n[    0.258147] boot log\n\n[x01] the same` | `bug#10` | Supported | |
| 2.03 | Hardware Configuration | GPU | In Scope | Critical | `PROJ-12: needs workaround\n\n[x01]\nworks with component` | `PROJ-12` | Enabled | |
| 2.08.01 | Hardware Configuration | `Wi-Fi\n(2.4 GHz)` | Out-of-Scope | Critical | `PROJ-20: ignored` | `PROJ-20` | Out-of-Scope | |
| 2.10 | Hardware Configuration | Display | TBD | *(empty)* | | | Enabled | |
| 2.16 | Hardware Configuration | Watchdog | In Scope | Critical | `PROJ-15: driver missing` | | Not supported | |
| 3.01 | Security | Secure Boot | In Scope | None | | | *(empty)* | |
| 4.01 | Process | Release Notes | Out-of-Scope | None | | | Out-of-Scope | |
| *(empty)* | | | | | | | | *(only Checkbox type/status)* |

2.01 keeps Test ID `cpu-001` and Test Short Name `- cpu/clocktest\n- cpu/maxfreq`; every row has Checkbox type `Automated`, status `Implemented`; Platform #2 columns empty.

- [ ] **Step 1: Write failing tests** (replace the old expectations): 9 items, components `A.1 General, A.2 Hardware Configuration, A.3 Security, A.4 Process`; `excluded_items == 2`; 2.08.01 is exactly `{id, name: "Wi-Fi (2.4 GHz)", fields: {source, scope: out-of-scope}}` (no status, no risk, no notes, no jira, no test) and 4.01 likewise; `ea` values `{supported: 3, enabled: 2, not-supported: 1}` with 3.01 unset; `fc` `{enabled: 1}` (1.01); `test` is `tbd` on 1.01, 1.02, 2.01, 2.03, 2.10, 2.16, 3.01 only; 2.10 scope `tbd`, no risk; 2.03 `fields.jira == ["PROJ-12"]`; dropped tokens 3 (`LP#001`, `LP#002`, `bug#10`; 2.08.01's `PROJ-20` is not read); 1.01 notes `== {discovery: "[x01]\nos-release"}`, 2.01 notes has only `discovery` and contains `[x01] the same`; no item has an `ea`/`fc`/`ga` note; `verify()` true and prints `out-of-scope: 2 items, their other columns ignored`, `test: 7 set by default (not from CSV)` and `dropped 3 bug tokens`; a variant with `TBD` in 3.01's x01 cell fails verify listing `ea: 'TBD'`; `meta()` has `exclude_when`, columns `ea, fc, ga, test` and one platform; `draft_mapping(fixture)` with platform name/title/repository filled reproduces the fixture mapping's converter output (existing round-trip test, updated); output passes `build.mjs check` and is unchanged by `format` (existing test).
- [ ] **Step 2: Run** `timeout 300 python3 -m unittest tests.test_requirement_matrix -v` → FAIL.
- [ ] **Step 3: Implement**; update `references/mapping.md` "Requirement matrix" section to the new mapping (generic names).
- [ ] **Step 4: Run** → PASS; `GoldenFeatureTest` → PASS; full suite → OK (same Task 1 skip rule for the requirement browser test).
- [ ] **Step 5: Commit** `matrix-to-site: convert requirement matrices with exclusion and fixed phases`.

### Task 3: Requirement views

**Files:**
- Modify: `matrix-to-site/assets/web/app.js`, `matrix-to-site/assets/web/style.css`
- Modify: `matrix-to-site/tests/browser/requirement.e2e.mjs`

**Interfaces:**
- Consumes: `excluded`, `included`, `done`, `risky`, `riskDone`, `coverage` (Task 1); fixture site from Task 2 (`golden_tool.build_site`).
- Risk filter value `risky` for URL param `risk` (`#/search?risk=risky`) = `risky(...)`; one extra Risk chip "Risky".

- [ ] **Step 1: Rewrite the requirement suite's view assertions** for the Task 2 fixture: default focus `fc` (last phase column with data); overview phase donuts EA `71%` and FC `14%`, labelled done (no "resolved" text anywhere on a requirement page); stat cards for focus FC: Done `14%`, Supported `0`, Enabled `1`, Not supported `0`, Not set `6`; Risk card `0 / 3` and `0%` on FC, after clicking the EA donut `2 / 3` and `67%`; its link lists exactly 2.03, 2.10, 2.16; Test coverage `0%`, `YES 0 · NO 0 · TBD 7 · not set 0`, `of 7 requirements`; sidebar link labelled "Not done"; rows 2.08.01 and 4.01 have class `excluded`, show "Out of scope" and no checkbox; drawer 2.08.01 shows only the Requirements block; drawer 2.03 shows blocks Discovery (Discovery check, Risk Critical, Discovery note), Project execution (EA Enabled, FC not set, GA not set, Jira ID `PROJ-12` linked to `https://example.atlassian.net/browse/PROJ-12`), Test plan; scope chip counts and risk chip counts ignore excluded items (Risk "Critical" chip = 2); `#/search?scope=tbd` lists only 2.10; CSV export row 2.08.01 has empty cells after its Requirements columns; feature DOM goldens unchanged; no page errors.
- [ ] **Step 2: Run** `node tests/browser/run.mjs requirement` → FAIL. **Step 3: Implement** (gate everything on `isRequirement`). **Step 4: Run** requirement + feature → PASS; remove any skip added in Tasks 1–2; full suite → OK.
- [ ] **Step 5: Commit** `matrix-to-site: requirement views for done, risk and exclusion`.

### Task 4: Requirement editing and batch

**Files:**
- Modify: `matrix-to-site/assets/web/app.js`
- Modify: `matrix-to-site/tests/browser/requirement.e2e.mjs`

**Interfaces:**
- Consumes: `excluded` (Task 1); batch `applies` option.

- [ ] **Step 1: Extend the suite** (signed in, fake GitHub, in order): edit 1.02, set Scope Out-of-Scope → the other fields are hidden and the hint about being ignored is visible; save → committed YAML for 1.02 still has `status: {ea: supported, test: tbd}` and its notes; reopen, set Scope In Scope, save → item identical to the original; batch: tick 1.01, 2.08.01 is not tickable, tick 2.16 and 3.01, column EA, value Supported, note `agreed` → commit message `matrix-table: set Board X · EA to Supported for 2 requirements` (2.16 and 3.01; 1.01 already Supported is skipped), 2.16 notes `ea` ends with `· EA: Not supported → Supported — agreed`; overview EA donut then `100%` (all 7 non-excluded items Supported or Enabled); editor value buttons for EA show only Supported / Enabled / Not supported / —.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (remove the old "clear Test on scope change" path). **Step 4: Run** requirement + feature → PASS; full suite → OK.
- [ ] **Step 5: Commit** `matrix-to-site: edit and batch with exclusion`.

### Task 5: Docs and checks

**Files:**
- Modify: `matrix-to-site/SKILL.md`, `matrix-to-site/assets/README.md`
- Modify: `matrix-to-site/tests/test_matrix_to_site.py` (`test_end_to_end_build_requirement` keeps passing with the new fixture)

- [ ] **Step 1: Update SKILL.md** step 3 requirement variant per the spec ("SKILL.md / docs"): automatic EA/FC/GA from Platform #1, ask only the platform name, scope values In Scope / Out-of-Scope / TBD, Out-of-Scope rows keep only their Requirements columns, Notes go whole to Discovery, Jira ID keeps Jira keys only (keep the existing placeholder sentence); step 6 variant lists out-of-scope count; report template uses Supported / Enabled / Not supported, done %, risk done/total, test coverage; remove phase-marker wording. README requirement section to match. Keep every other rule.
- [ ] **Step 2: Run** full suite → OK; ruff clean; sensitive-name scan given by the controller → 0.
- [ ] **Step 3: Commit** `matrix-to-site: document revised requirement matrix`.
