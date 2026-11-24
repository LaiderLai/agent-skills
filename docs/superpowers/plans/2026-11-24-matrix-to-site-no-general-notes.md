# matrix-to-site no General notes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the `general` notes section from both templates: feature notes per platform, requirement notes per Discovery/EA/FC/GA/QA.

**Architecture:** Note-key rules live in `assets/web/template.js` (`noteOrder`, `noteKeyFor`, `validateMeta`) and `model.js` (`validateComponent`, `applyBatch`); converters in `scripts/convert_csv.py` (feature) and `scripts/requirement_matrix.py`; UI in `assets/web/app.js`.

**Tech Stack:** Python 3 + PyYAML (unittest), Node ES modules (`node --test`), vanilla JS app, headless Chrome browser tests.

**Spec:** `docs/superpowers/specs/2026-11-24-matrix-to-site-no-general-notes-design.md`.

## Global Constraints

- Work in `matrix-to-site/` and `docs/`; commit locally; **never push**.
- Feature output changes **only** by the removal of General notes parts. Golden files may be regenerated only in Task 3, and the regeneration diff (`git diff tests/golden`) must contain nothing else — paste it into the report.
- No company/customer/project names or personal paths in committed files or messages; synthetic fixtures only.
- Python `ruff format` + `ruff check` clean; no new npm deps; `~/Downloads` must not gain files.
- Full suite after every task, from `matrix-to-site/`: `timeout 900 python3 -m unittest discover -s tests` → `OK`.

## Review Focus

1. A feature CSV with two platforms, an unmarked note and no `notes_default_platform` stops with an error naming `notes_default_platform` — Task 2.
2. A feature mapping with one platform and no head/default keys puts unmarked and head text on that platform — Task 2.
3. Batch on a feature status column without platform: no note box, the commit adds no note anywhere — Task 3.
4. Requirement 2.03's Discovery note ends with `\n\nJira: PROJ-12` — Task 2.
5. `general` notes in hand-edited data fail `check` in both templates with a re-import hint — Task 1.

---

### Task 1: Note-key rules and validation

**Files:** Modify `matrix-to-site/assets/web/template.js`, `matrix-to-site/assets/web/model.js`. Test: `matrix-to-site/tests/template.test.mjs`, `matrix-to-site/tests/validate.test.mjs`, `matrix-to-site/tests/batch.test.mjs`.

**Interfaces (produced):**
- `noteOrder(meta)` → feature: platform ids; requirement: `note_keys` ids. No `general`.
- `noteKeyFor(column, meta)` (existing argument order, callers unchanged) → requirement: `column.note_key`; feature: `column.platform ?? null`. `null` means "no note"; app.js callers must treat `null` as no note box / no note.
- `applyBatch(..., { noteKey })` with `noteKey: null` never writes a note (even if `note` is non-empty).
- `validateMeta`: requirement column without `note_key`, or with one not in `note_keys` → error.
- `validateComponent`: a `general` note key (or any key outside `noteOrder`) → error text containing `re-import`. `GENERAL` export may stay for compatibility of imports but no rule uses it.

- [ ] **Step 1: Failing tests:** noteOrder feature `["p1","p2"]`, requirement `["discovery","ea","fc","ga","qa"]`; noteKeyFor feature platform column → platform, feature column without platform → `null`, requirement column → its note_key; applyBatch with `noteKey: null` and note `agreed` changes status but adds no note; validateMeta error for a requirement column missing note_key and for an unknown note_key; validateComponent errors for `notes: {general: "x"}` on a feature item, a feature component, and a requirement item, each message containing `re-import`.
- [ ] **Step 2: Run** `node --test tests/` → FAIL. **Step 3: Implement.** Update existing tests that expect `general`.
- [ ] **Step 4: Run** node tests → PASS; full suite → may fail in browser/golden tests that still show General — allowed until Task 3 only for DOM goldens and the requirement browser suite (skip them with reason "updated in Task 3"); converter goldens must still pass.
- [ ] **Step 5: Commit** `matrix-to-site: notes belong to a platform or a phase, never general`.

### Task 2: Converters and inspector

**Files:** Modify `matrix-to-site/scripts/convert_csv.py`, `matrix-to-site/scripts/inspect_csv.py`, `matrix-to-site/scripts/requirement_matrix.py`, `matrix-to-site/tests/fixtures/requirement-mapping.yaml`, `matrix-to-site/references/mapping.md`. Test: `matrix-to-site/tests/test_matrix_to_site.py`, `matrix-to-site/tests/test_requirement_matrix.py`.

**Interfaces:**
- Feature `Converter`: head text → `notes_head_platform`, unmarked → `notes_default_platform`; with one platform both default to it; otherwise a needed-but-unset key exits with `error: notes need a platform: set notes_default_platform (or notes_head_platform) in the mapping` (exact text up to the builder, must name the key).
- `inspect_csv.py` feature draft writes `notes_default_platform` and `notes_head_platform` set to the first platform with a `# CONFIRM` comment.
- Requirement converter: Jira line appended to `discovery`; no `general` anywhere; `notes_head_key`/`notes_default_key` default to `discovery`.

- [ ] **Step 1: Failing tests:** feature: existing fixture converts unchanged (golden raw/formatted/data.json unchanged); a two-platform mapping without `notes_default_platform` and an unmarked note fails with an error naming `notes_default_platform`; a one-platform mapping without head/default keys puts unmarked and head text on that platform; the feature inspector draft contains both keys with `# CONFIRM`. Requirement: 2.03 notes `== {"discovery": "PROJ-12: needs workaround\n\n[x01]\nworks with component\n\nJira: PROJ-12"}`; no item has a `general` note; mixed-token and duplicate tests now check the Discovery note.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; update the feature golden `inspect.yaml` only if the draft change requires it (diff must be only the two notes keys + comments) and document it. **Step 4: Run** → PASS; full suite (Task 1 skips allowed).
- [ ] **Step 5: Commit** `matrix-to-site: converters never write general notes`.

### Task 3: UI, goldens, docs

**Files:** Modify `matrix-to-site/assets/web/app.js`, `matrix-to-site/tests/browser/requirement.e2e.mjs`, `matrix-to-site/tests/browser/feature.e2e.mjs` (if needed), `matrix-to-site/tests/golden/feature/dom/*`, `matrix-to-site/SKILL.md`, `matrix-to-site/assets/README.md`.

- [ ] **Step 1: Assertions:** requirement drawer 2.03 has no "General" card/block and its Discovery note links PROJ-12; requirement editor has no `notes.general` field; requirement CSV has no `General notes`; feature: a scenario that batches the column without platform (fixture's group column) shows no note box and its commit adds no note; feature editor/drawer/CSV show no General.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Regenerate the feature DOM goldens** with `node tests/browser/run.mjs --update feature`, then `git diff tests/golden` must show only General-notes removal (paste it into the report); run without `--update` twice → PASS; requirement suite PASS; remove Task 1 skips; full suite OK.
- [ ] **Step 5: Docs:** SKILL.md step 3 (feature: unmarked notes and text before the first marker must go to a platform, no general option; requirement: note sections Discovery/EA/FC/GA/QA, Jira keys to Discovery), pitfalls table rows that mention `general`, step 5 re-import note covers both templates; README notes descriptions; mapping.md.
- [ ] **Step 6: Commit** `matrix-to-site: UI and docs without general notes`.
