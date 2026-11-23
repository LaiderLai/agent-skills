# matrix-to-site: batch status edit

## Why

In review meetings the team discusses open items and reaches decisions together. The
PjM then needs to set several features to YES/NO (or TBD) at once. Today the web UI
edits one feature at a time: one drawer, one save, one commit, one redeploy each.

## Goal

Select several rows, pick a status column and a value, optionally type a meeting note,
and apply it to all of them in **one save** (one commit, one redeploy).

Non-goals: editing names/comments in bulk, bulk delete, applying several columns in one
go, spreadsheet-style inline editing.

## Behaviour (agreed with the user)

- **Where:** checkboxes on rows in the component page and in search / "Open items (TBD)"
  — a selection can span components. A "select all visible" checkbox in the table header
  selects the rows currently shown by the filters.
- **Bar:** when ≥1 row is selected, a sticky bar shows: "N selected", target column
  (defaults to the focus column), value buttons YES / NO / TBD / — (not set), optional
  meeting note, **Cancel** and **Apply & save**.
- **Confirm:** before saving, a short summary: how many change, how many are skipped
  because they already have that value, which components/files are touched.
- **Meeting note:** when filled in, appended to each *changed* feature's notes under the
  column's platform (column without a platform → `general`), after a blank line, as
  `YYYY-MM-DD · <column name>: <old> → <new> — <note>` with each item's own old value.
  Empty note → status only. Existing note text is never modified.
- **Skipped items:** features already at the target value are not touched (status or notes).
- **Save:** one commit for the whole batch, message
  `matrix-table: set <column> to <VALUE> for N features`.
- **Conflicts:** same rule as single edits — if someone else changed one of the selected
  features since it was loaded, nothing is saved and the user is told which features
  conflicted; changes to *other* features in the same files are merged.
- Read-only states (not signed in, viewing a version, exported HTML) hide the checkboxes.

## How (the one sensible way)

Use the GitHub Git Data API so several files land in one commit:
get the branch ref → base commit + tree → for each touched component file, re-read the
file at that commit, re-apply the batch to it (checking each selected feature is still
equal to what was loaded) → create blobs → create tree on the base tree → create commit →
update the ref with `force: false`. If the ref moved meanwhile (non-fast-forward), retry
once from the new head; the per-feature equality check decides conflict vs merge.
Validation and canonical YAML dumping reuse `model.js`, exactly like single edits.

Rejected: one Contents-API commit per file — N commits/redeploys and a batch can end
half-saved.

## Done when

- Unit-level: batch apply logic (skip, note append, platform/general key, old→new text)
  tested; skill tests still pass.
- End-to-end against a real GitHub branch: select across 2 components, apply with a note
  → exactly one new commit touching 2 files, values and notes correct, YAML lint-clean;
  a concurrent edit to a selected feature is rejected; to an unselected one is merged.
- Exported HTML and version views show no selection UI.

## Left to the builder

Exact styling of the bar, keyboard shortcuts, wording of messages.

## Follow-up fixes (agreed after trying the deployed site)

- **Confirm lists items:** the confirm dialog has a collapsible list of the items that
  will change (`id name: OLD → NEW`) and of skipped ones.
- **Ticking keeps focus:** ticking a row updates only that row and the header checkbox
  (which shows an indeterminate state when some visible rows are ticked); the table is
  not re-rendered, so keyboard focus stays.
- **Distinct highlight:** ticked rows use a different highlight than the row whose
  drawer is open.
- **Stale ids dropped:** after data reloads, ids that no longer exist leave the selection.
- **Wording:** commit message uses `feature`/`features` by count; "already not set"
  instead of "already —"; a second non-fast-forward reads "Someone else saved at the
  same moment — press Save again."
- **CSS:** valid font for the note box; no duplicate rule; batch bar and checkbox column
  hidden when printing.
- **Large files:** component files over 1 MB (Contents API returns no content) are read
  through the Git blobs API, for batch and single saves alike.
- **Saving lock:** starting an edit while a batch is saving is refused.
- **Overview:** the batch bar is hidden on pages without a matrix table; the selection
  is kept and the bar returns on component/search pages.
