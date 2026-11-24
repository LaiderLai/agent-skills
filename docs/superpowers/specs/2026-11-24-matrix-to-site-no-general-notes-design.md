# matrix-to-site: no General notes in either template

Change on top of the requirement-matrix designs of 2026-11-23/24 and the original feature
matrix. Everything else still holds.

## Why

The user found a design error: notes always belong to something concrete. In a feature
matrix that is a platform (e.g. two boards); in a requirement matrix it is a phase
(Discovery, EA, FC, GA) or QA. A shared "General" notes section has no owner and must go.

## Decided with the user (2026-11-24)

**Feature matrix**
1. Note keys are the platform ids only — for features, components and sections. `general`
   is no longer a valid note key (validation error naming the item and the key, with a
   hint to re-import).
2. Converter: text before the first marker goes to `notes_head_platform`; notes with no
   marker go to `notes_default_platform`. With exactly one platform both default to it.
   With several platforms and a note that needs one of them unset, the conversion stops
   with a clear error naming the mapping key (no silent `general`). SKILL.md step 3 keeps
   asking where unmarked notes go, without a "general" option.
3. Status columns without a platform (e.g. a silicon column): a batch change on them
   takes **no meeting note** (the note box is hidden for that column); single-item edits
   are unaffected.
4. UI: no "General" notes field, card or CSV column.

**Requirement matrix**
5. Note keys are `note_keys` only (Discovery, EA, FC, GA, QA). The Jira keys from the
   template's Jira column go to the **Discovery** note as a last line `Jira: KEY-1, KEY-2`
   (after the Notes text, separated by a blank line; duplicates removed; placeholders
   dropped and counted; excluded rows not read).
6. Every requirement status column must have a `note_key` from `note_keys`
   (`validateMeta` error otherwise); batch notes always go there.

**Both**
7. Feature-matrix output changes by design: golden files are regenerated, and the
   regeneration diff must contain only the removal of General notes parts.
8. Data with `general` notes made by earlier versions fails `check`; the fix is to
   re-import the CSV.

## Approach

Change both templates in place on the unmerged branch. No compatibility option.

## Left to the builder

Exact error wording; how the hidden batch note box is indicated.
