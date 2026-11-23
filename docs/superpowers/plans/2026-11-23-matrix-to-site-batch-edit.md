# Batch Status Edit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a signed-in editor tick several rows, pick a status column and value, optionally add a meeting note, and save all of it as one commit.

**Architecture:** Pure batch logic goes in `model.js` (shared, testable with `node --test`). `app.js` gains a selection state, a sticky batch bar and confirm dialog, and `commitFiles()`, which writes several component files in one commit through the GitHub Git Data API, re-applying the batch on the latest copy of each file with the same per-feature conflict rule as single edits.

**Tech Stack:** vanilla ES modules in the browser (no build step), Node ≥ 18 `node:test`, Python `unittest` wrapper, GitHub REST (Git Data API).

**Spec:** `docs/superpowers/specs/2026-11-23-matrix-to-site-batch-edit-design.md`

## Global Constraints

- Skill lives in `matrix-to-site/`; SKILL.md and docs stay English with no project/company names.
- One batch = one commit; message `matrix-table: set <column title> to <VALUE> for N features` (VALUE = `YES`/`NO`/`TBD`/`—`).
- Note line format: `YYYY-MM-DD · <column name>: <OLD> → <NEW> — <note>`, appended after a blank line, under the column's platform key, or `general` for a column without `platform`. No note → no notes change.
- Features already at the target value are untouched (status and notes).
- Read-only states (not signed in, viewing a version, exported HTML) show no checkboxes or bar.
- Generated YAML must pass `node matrix-table/tools/build.mjs check` and the repo yamllint config.

## Review Focus

1. Target value "—" (unset) → status key removed; note line shows `→ —`.
2. Selection survives navigation between component page and search; rows hidden by a filter but still selected are counted and shown in the confirm summary.
3. A feature deleted by someone else since load → reported as a conflict, nothing saved.
4. Branch head moves between building the commit and updating the ref (422 non-fast-forward) → retried once from the new head.
5. Applying twice in a row (second time all skipped) → no commit, toast says nothing to change.

Each is pinned by a test in the owning task below.

---

### Task 1: Batch logic in `model.js`

**Files:**
- Modify: `matrix-to-site/assets/web/model.js`
- Create: `matrix-to-site/tests/batch.test.mjs`
- Modify: `matrix-to-site/tests/test_matrix_to_site.py` (add `NodeTestsTest` that runs `node --test tests/` and asserts exit 0; skip if no node)

**Interfaces:**
- Produces: `applyBatch(doc, ids, column, value, { noteKey, note, date, columnName }) -> { doc, changed: string[], skipped: string[], missing: string[] }`
  - `doc` is a component document (not mutated; returns a clone); `ids` feature ids (may include ids of other components — ignored); `column` status column id; `value` one of `supported|unsupported|tbd|unset`; `noteKey` `general` or a platform id; `note` string (trimmed, may be empty); `date` `YYYY-MM-DD`; `columnName` e.g. `Beta`.
- Produces: `batchNoteLine(date, columnName, oldValue, newValue, note) -> string` using labels from `STATUSES` (`unset` → `—`).
- Produces: `sameFeature(a, b, meta) -> boolean` (move from app.js; app.js imports it).

- [ ] **Step 1: Write failing tests** in `tests/batch.test.mjs` with `node:test` + `assert`, using a 3-feature component (`A.1.1` tbd, `A.1.2` unsupported, `A.1.3` supported on column `b-beta`; `A.1.1` has `notes: {b: "old"}`):
  - `applies value and skips already-set`: ids `[A.1.1, A.1.2, A.1.3]`, value `supported` → `changed = [A.1.1, A.1.2]`, `skipped = [A.1.3]`, statuses supported.
  - `appends note under platform key`: note `"agreed"`, noteKey `b`, date `2026-11-23`, columnName `Beta` → A.1.1 notes.b === `"old\n\n2026-11-23 · Beta: TBD → YES — agreed"`; A.1.2 notes.b === `"2026-11-23 · Beta: NO → YES — agreed"`; skipped A.1.3 notes unchanged.
  - `empty note leaves notes alone`.
  - `unset removes status key` (Review Focus 1): value `unset` on A.1.3 → `"b-beta" in status` false; line contains `YES → —`.
  - `ids of other components and unknown ids`: `B.2.1` ignored; `A.1.9` reported in `missing`.
  - `does not mutate input`.
- [ ] **Step 2: Run** `node --test matrix-to-site/tests/` → FAIL (`applyBatch` not exported).
- [ ] **Step 3: Implement** `applyBatch`, `batchNoteLine`, `sameFeature` in `model.js`; notes appended with `cleanText`-compatible text (no trailing spaces).
- [ ] **Step 4: Run** `node --test matrix-to-site/tests/` and `python3 -m unittest discover -s matrix-to-site/tests` → all pass.
- [ ] **Step 5: Commit** `matrix-to-site: add batch apply logic`.

### Task 2: Multi-file commit in `app.js`

**Files:**
- Modify: `matrix-to-site/assets/web/app.js`

**Interfaces:**
- Consumes: `applyBatch`, `sameFeature` (Task 1); existing `gh`, `repo`, `encodePath`, `validateComponent`, `dumpComponent`, `parseYaml`, `decodeBase64`, `utf8ToBase64`, `rebuildIndex`, `ConflictError`.
- Produces: `async commitFiles(changes: Array<{ entry, apply: (latestDoc) => doc }>, message: string) -> { sha, html_url }`; updates each `entry.sha/doc/base` on success; throws `ConflictError` (message lists conflicting feature ids) or `Error` with `.errors` for validation.

- [ ] **Step 1: Implement `commitFiles`**: `GET git/ref/heads/<branch>` → head; `GET git/commits/<head>` → tree; per entry `GET contents/<path>?ref=<head>`, `parseYaml`, run `apply` (which throws `ConflictError`), validate, dump; `POST git/blobs` (base64) per file; `POST git/trees` with `base_tree`, mode `100644`; `POST git/commits` with `parents: [head]`; `PATCH git/refs/heads/<branch>` `{ sha, force: false }`. On 422 from the PATCH, redo everything once from the new head (Review Focus 4). Return the commit.
- [ ] **Step 2: Refactor** single-feature `sameFeature` use in `saveDraft` to the model.js export; `node --check assets/web/app.js` passes.
- [ ] **Step 3: Commit** `matrix-to-site: add multi-file commit via Git Data API` (behaviour verified end-to-end in Task 4).

### Task 3: Selection UI and batch bar

**Files:**
- Modify: `matrix-to-site/assets/web/app.js`, `matrix-to-site/assets/web/style.css`

**Interfaces:**
- Consumes: `applyBatch`, `batchNoteLine` (Task 1), `commitFiles` (Task 2), `canEdit()`.
- Produces: `state.selection: Set<string>` (feature ids); DOM hooks used by Task 4: row checkbox `input[data-select="<id>"]`, header `input[data-select-all]`, bar `#batch-bar` with `select#batch-column`, buttons `[data-batch-value="supported|unsupported|tbd|unset"]`, `textarea#batch-note`, `[data-action="batch-apply"]`, `[data-action="batch-clear"]`; confirm dialog `#batch-confirm` with `[data-action="batch-confirm"]`.

- [ ] **Step 1:** When `canEdit()`, add a checkbox column to the matrix (component and search views) and a header "select all visible" checkbox; clicking a checkbox must not open the drawer; selection persists across hash navigation and clears after a successful apply or Cancel (Review Focus 2).
- [ ] **Step 2:** Sticky `#batch-bar` shown when `selection.size ≥ 1`: "N selected", column select (default `state.focus`, options from `meta.columns` with `columnTitle`), value buttons, note textarea, Cancel, "Apply & save" (disabled until a value is picked).
- [ ] **Step 3:** "Apply & save" builds per-component previews with `applyBatch` on loaded docs and opens `#batch-confirm`: counts changed / skipped, components touched, ids not found (Review Focus 3 surfaces at save time). If nothing changes → toast "Nothing to change" and no commit (Review Focus 5).
- [ ] **Step 4:** Confirm → `commitFiles` with apply re-running `applyBatch` on the latest doc and throwing `ConflictError` when a selected feature differs from `entry.base` per `sameFeature`, or is missing; commit message per Global Constraints; noteKey = column's `platform` or `general`; date = local `YYYY-MM-DD`. Success → toast with commit link, clear selection, re-render. Conflict → toast/dialog listing ids, nothing saved.
- [ ] **Step 5:** Hidden when `!canEdit()` (version view, export, signed out). `node --check` passes; build with `node assets/tools/build.mjs` on a converted fixture still passes.
- [ ] **Step 6: Commit** `matrix-to-site: add batch selection UI`.

### Task 4: End-to-end verification on a real branch

**Files:**
- Create (scratch, not committed): `batch-e2e.mjs` in a scratch directory, driving headless Chrome over CDP.

- [ ] **Step 1:** Create throwaway branch `<deploy-branch>-batch-e2e` from `origin/<deploy-branch>` in the target repo (no workflow runs on it); build the site from the updated assets with `_meta` branch overridden via Settings → Advanced branch.
- [ ] **Step 2:** Scenario A: select A.7.4 and A.11.4 (two components), column `<platform>-beta`, value YES, note `e2e batch` → exactly one new commit on the branch touching exactly those 2 files; both statuses `supported`; both `<platform>` notes end with `· Beta: TBD → YES — e2e batch`; `yamllint` + `build.mjs check` on the branch pass.
- [ ] **Step 3:** Scenario B: select A.7.5; out-of-band commit changes A.7.5 → apply → conflict reported, branch head unchanged by the UI.
- [ ] **Step 4:** Scenario C: select A.7.6; out-of-band commit changes A.7.7 (same file) → apply succeeds; both changes present.
- [ ] **Step 5:** Scenario D: apply the same batch again → "Nothing to change", no commit. Exported HTML and `?v=` view: no `input[data-select]`, no `#batch-bar`; no JS errors.
- [ ] **Step 6:** Delete `<deploy-branch>-batch-e2e`.

### Task 5: Ship

**Files:**
- Modify: `matrix-to-site/assets/README.md` (Editing section: batch edit), `matrix-to-site/SKILL.md` only if behaviour text changes (Overview feature list).

- [ ] **Step 1:** Docs updated; skill tests pass; sensitive-content scan clean.
- [ ] **Step 2:** Push `agent-skills` `main`; rsync to `~/.agents/skills/matrix-to-site`.
- [ ] **Step 3:** In the target repo on `<deploy-branch>`: copy mapping to a temp file, `scaffold.py . --deploy-branch <deploy-branch> --mapping <tmp> --force`, verify only `matrix-table/web`, `matrix-table/tools`, workflow/README changed, checks pass, commit, push; confirm the deploy run succeeds.

---

## Follow-up (spec section "Follow-up fixes")

### Task 6: Follow-up fixes

**Files:** `matrix-to-site/assets/web/app.js`, `style.css`, `model.js`; `tests/batch.test.mjs`; e2e `batch-followup-e2e.mjs` (scratch, not committed).

**Interfaces:**
- Produces (model.js): `batchCommitMessage(columnTitle: string, value: string, n: number) -> string` →
  `matrix-table: set <title> to <LABEL> for <n> feature(s)` (`1 feature`, `2 features`).
- Produces (app.js): `readFileAt(path, ref) -> { sha, text }` (Contents API, falls back to `git/blobs/<sha>` when `content` is empty); used by `commitFiles` and `commit()`.

- [ ] **Step 1 (RED):** unit tests for `batchCommitMessage` (1 → "feature", 2 → "features", unset → "—"); e2e checks:
  confirm dialog lists changed ids; focus stays on the ticked checkbox and no table re-render; header `indeterminate` when partial;
  ticked row background differs from drawer-open row; deleted feature leaves the count after refresh;
  all-skipped unset toast says "already not set"; print media hides `#batch-bar` and `td.sel`;
  overview hides the bar and the component page shows it again with the same count;
  Edit refused while `state.saving`; batch on a >1 MB component file succeeds.
- [ ] **Step 2:** watch them fail.
- [ ] **Step 3:** implement.
- [ ] **Step 4 (GREEN):** unit suite + follow-up e2e + regression e2e (A–D, fix pass) all pass.
- [ ] **Step 5: Commit** `matrix-to-site: batch edit follow-up fixes`.
