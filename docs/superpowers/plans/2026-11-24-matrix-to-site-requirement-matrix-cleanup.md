# matrix-to-site requirement matrix cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Requirement matrices have no `label`, no Jira ID field (Jira keys go to the `general` note) and no per-platform notes section.

**Architecture:** Data-model rules in `assets/web/template.js` / `model.js` (noteOrder, item keys), converter and inspector in `scripts/requirement_matrix.py`, UI in `assets/web/app.js`. Feature matrices untouched (goldens guard).

**Tech Stack:** Python 3 + PyYAML (unittest), Node ES modules (`node --test`), vanilla JS app, headless Chrome browser tests.

**Spec:** `docs/superpowers/specs/2026-11-24-matrix-to-site-requirement-matrix-cleanup-design.md` (on top of the revision and base designs).

## Global Constraints

- Work in `matrix-to-site/` and `docs/`; commit locally; **never push**.
- Feature-matrix output byte-identical: feature golden files and feature DOM goldens pass after every task; never run `--update` on existing goldens.
- No company/customer/project names or personal paths in committed files or messages; fixtures stay synthetic (`PROJ`, `example.atlassian.net`, `Board X`).
- Python `ruff format` + `ruff check` clean; no new npm dependencies.
- Full suite after every task, from `matrix-to-site/`: `timeout 900 python3 -m unittest discover -s tests` → `OK`; `~/Downloads` must not gain files.
- Jira note line format exactly `Jira: KEY-1, KEY-2` (column order, duplicates removed) in note key `general`.

## Review Focus

1. A Jira cell holding both placeholders and keys (`LP#001, PROJ-12`) gives `general: "Jira: PROJ-12"` and counts `LP#001` as dropped — Task 1.
2. An excluded row's Jira cell is not read (no general note, nothing dropped) — Task 1.
3. A hand-edited requirement item with `label` or a platform-keyed note fails `check` with a clear message — Task 1.
4. The batch note for a phase column still goes to that phase's note (never a platform note) — Task 2.
5. The requirement drawer and CSV export show no "Label", "Jira ID" or "<platform> notes" — Task 2.

---

### Task 1: Data model, converter, inspector, fixture

**Files:**
- Modify: `matrix-to-site/assets/web/template.js` (`noteOrder`), `matrix-to-site/assets/web/model.js` (requirement item keys without `label`)
- Modify: `matrix-to-site/scripts/requirement_matrix.py`, `matrix-to-site/tests/fixtures/requirement-mapping.yaml`, `matrix-to-site/references/mapping.md`
- Test: `matrix-to-site/tests/test_requirement_matrix.py`, `matrix-to-site/tests/template.test.mjs`, `matrix-to-site/tests/validate.test.mjs`

**Interfaces:**
- `noteOrder(meta)` → `["general", ...note_keys]` for requirement matrices; unchanged for feature matrices.
- Requirement item keys: `id, name, comment, status, fields, notes` (no `label`).
- Mapping: the Jira column moves from `fields` to `columns: {..., jira: <index>}`; `RequirementConverter` writes `notes.general = "Jira: …"` when the column holds Jira keys; `dropped_bug_tokens` counting unchanged; `draft_mapping` drafts `columns.jira` and no `jira` field.

- [ ] **Step 1: Failing tests.** Python: 2.03 `notes == {"general": "Jira: PROJ-12", "discovery": "PROJ-12: needs workaround\n\n[x01]\nworks with component"}` (general first, per noteOrder); no item has `fields.jira`; `meta()["fields"]` has no `jira`; 1.01 (`LP#001, LP#002`) has no general note and dropped tokens stay 3; a variant where 1.01's cell is `LP#001, PROJ-30, PROJ-30` gives `general: "Jira: PROJ-30"`; 2.08.01 has no notes; `draft_mapping` round-trip still reproduces the fixture output; written YAML passes `check`, unchanged by `format`. Node: `noteOrder` for a requirement meta with a platform `p1` and note_keys discovery/ea returns `["general","discovery","ea"]`, for a feature meta returns `["general","p1"]`; `validateComponent` on a requirement item with `label: x` reports `unknown key "label"`, with `notes: {p1: "x"}` reports the notes-key error; feature items with `label` still pass.
- [ ] **Step 2: Run** `node --test tests/` and `timeout 300 python3 -m unittest tests.test_requirement_matrix` → FAIL.
- [ ] **Step 3: Implement**; update the fixture mapping and the "Requirement matrix" part of `references/mapping.md`.
- [ ] **Step 4: Run** both → PASS; full suite → OK (if the requirement browser suite fails only on the Jira ID / Label assertions Task 2 rewrites, skip `BrowserTest.test_requirement_ui` with reason "updated in Task 2"; feature suite must pass).
- [ ] **Step 5: Commit** `matrix-to-site: requirement items without label, Jira keys to general notes`.

### Task 2: UI, browser tests, docs

**Files:**
- Modify: `matrix-to-site/assets/web/app.js`
- Modify: `matrix-to-site/tests/browser/requirement.e2e.mjs`
- Modify: `matrix-to-site/SKILL.md`, `matrix-to-site/assets/README.md`

**Interfaces:**
- Consumes: Task 1's `noteOrder` and data shape.

- [ ] **Step 1: Rewrite assertions:** 2.03 drawer has a General note card containing a link to `https://example.atlassian.net/browse/PROJ-12`, no "Jira ID" text in the execution block, no "Board X" notes card; the requirement editor has no `[data-field="label"]` and no notes textarea for `platform-1`; CSV export header has no `Label`, `Jira ID` or `Board X notes`, keeps `General notes`, `Discovery notes`, `EA notes`, `FC notes`, `GA notes`, `QA notes`; the excluded-row CSV check uses the kept columns `ID, Section, Component, Requirement, Comment, Scope, Source`; the batch scenario's note still lands in `ea`; feature DOM goldens unchanged; no page errors. Remove any skip added in Task 1.
- [ ] **Step 2: Run** `node tests/browser/run.mjs requirement` → FAIL. **Step 3: Implement** (gate on `isReq()`). **Step 4: Run** requirement + feature → PASS; full suite → OK.
- [ ] **Step 5: Docs:** SKILL.md requirement variant: Jira keys from the Jira column go to the General note; no Short label; note sections General / Discovery / EA / FC / GA / QA. README requirement section and YAML example to match (no `jira` field; `notes: {general: "Jira: PROJ-12", discovery: …}`).
- [ ] **Step 6: Commit** `matrix-to-site: requirement UI without label, Jira field and platform notes`.
