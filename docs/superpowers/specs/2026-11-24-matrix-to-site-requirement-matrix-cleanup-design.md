# matrix-to-site: requirement matrix — remove label, Jira ID field, platform notes

Small change on top of `2026-11-24-matrix-to-site-requirement-matrix-revision-design.md`
(that document and the base design still hold where not changed here).

## Why

The user found three things in the requirement template that carry no meaning for
requirement sheets: the "Short label", a separate Jira ID field (Jira references are kept
in notes), and a notes section per platform (notes belong to Discovery and the three
release phases).

## Decided with the user (2026-11-24)

1. **No label for requirement matrices.** Requirement items have no `label`: not written by
   the converter, not accepted by validation (unknown key), not shown (table sub-line,
   drawer tag, editor "Short label" input), not exported (no "Label" CSV column).
2. **No Jira ID field.** The template's bug / JIRA ID column is still read for non-excluded
   rows, but its Jira keys go into the item's **`general` note** as one line
   `Jira: KEY-1, KEY-2` (in column order, duplicates removed). Non-Jira tokens stay
   template placeholders: dropped and counted as today. Excluded rows: not read. No
   `jira` field in `_meta.yaml`; the drawer's Project execution block shows only the
   phase statuses; no "Jira ID" CSV column. Jira keys in notes are linked as today.
3. **No platform notes section for requirement matrices.** Note sections are `general`
   plus `note_keys` (Discovery, EA, FC, GA, QA). `noteOrder` for requirement matrices
   leaves out platform ids; validation rejects a platform-keyed note; the editor, drawer
   and CSV export show no "<platform> notes".

Feature matrices: no change (goldens unchanged).

## Approach

Change the requirement template in place on the unmerged branch, as before. No option to
keep the old behaviour (nobody uses it). The trial site converted with the previous
template is re-converted afterwards, pushed only with the user's consent.

## Left to the builder

Where the Jira line sits inside an existing `general` note (the converter writes nothing
else there today), wording of any new validation message.
