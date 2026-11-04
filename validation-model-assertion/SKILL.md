---
name: validation-model-assertion
description: Use when an Ubuntu Core or snapd model assertion is involved — a model.json, .model or .assert file, a JSON with brand-id, grade, base or a snaps list, a folder of model variants — before snap sign, ubuntu-image or snap prepare-image, during a remodel, when snap sign rejects a model, or when the user just pastes one and asks "does this look right?".
---

# Validating a model assertion

A model assertion defines an Ubuntu Core device: brand, model name, boot chain
(gadget, kernel, base, snapd), extra snaps, grade. Mistakes surface late — after
signing and a multi-gigabyte image build — so this skill collapses that loop to
seconds. Official field reference:
https://documentation.ubuntu.com/core/reference/assertions/model/

**Core principle: this is a read-only job.** The file you were handed is the
evidence. Report, show the fix, let the user apply it.

## Hard rules for every run

| Rule | What it means in practice |
|---|---|
| **Never modify the model** | Not for a one-character fix, not when you are certain. Show the corrected value or write a copy to `/tmp`. Two exceptions only: the user explicitly asks you to make a change, or explicitly answers yes to the timestamp question (Step 6). If the file was signed, any edit invalidates the signature — say so. |
| **No one to ask → carry the questions forward** | In CI, batch or subagent runs, never answer a confirm question yourself. End the report with a list headed "Only you can confirm these", current value next to each, and state which checks were skipped (offline, no credentials) and why. |
| **Nothing lands in their working tree** | Scratch files go to `/tmp` and are deleted afterwards. Every file in a reviewed directory is read-only. |
| **Customer identifiers stay in the report** | Real `brand-id`, `model`, store id and brand snap names appear only in your reply — never in commits, bug reports, or this skill's examples/evals/reference. Invent examples (`mybrand`, `my-brand-store-id`). If you spot a real one committed in a skill or example, report it as a leak. |
| **Never run a command that waits on a terminal** | `snap create-key` and `snap sign` with a real key block silently on a passphrase. Use `--create-key` (throwaway key) or hand the command to the user. |
| **Delete the throwaway key before you finish** | If `snap keys` lists `model-validation-throwaway` after your run, remove it (commands in `references/validator-behaviour.md`) and confirm with `snap keys`. Do not leave it for the user. |

## Step 1: Get a concrete model file

Never validate a hypothetical or invented model. Accept:

- a path to a `.json` file (most common)
- pasted JSON — write it to `/tmp` first
- a signed `.model` / `.assert` — convert with
  `python3 $SKILL_DIR/scripts/assertion_to_json.py model.model > /tmp/model.json`
  and say you are validating the content, not the signature
- a device: `snap model --assertion > /tmp/model.model`

## Step 2: Run the validator

`$SKILL_DIR` is the directory containing this SKILL.md.

```bash
python3 $SKILL_DIR/scripts/validate_model.py MODEL.json --online
python3 $SKILL_DIR/scripts/validate_model.py some/dir/ --online      # a set of variants
python3 $SKILL_DIR/scripts/validate_model.py MODEL.json --online --sign-check --create-key
```

| Layer | Catches |
|---|---|
| structural | what snapd itself enforces: types, headers, grade, missing essential snaps, `presence` on essential snaps, end-of-life UC16/18 format |
| semantic (`--online`) | wrong snap-id, wrong `type`, missing track, no build for the architecture, components not published on the channel — **`snap sign` checks none of this** |
| advisory | stale or future timestamp, channel risk fallback, signed sibling drift |
| confirm | legal values only a human can judge (Step 3) |

- Use `--online` unless offline or the snaps are private; then say which checks
  were skipped. An offline PASS means "well-formed", not "correct".
- Pair `--sign-check` with `--online`: `snap sign` never goes online.
- The report includes a **store-lookup ledger** (`snap-id verified`,
  `NOT FOUND`, `local snapd`, `MISMATCH`). Show it — silence cannot distinguish
  "checked and fine" from "never checked".
- An unresolvable brand-store snap is a warning, not a typo: ask for its snap-id
  (`snapcraft status <snap>`, or `snap info --verbose <snap>` on an attached
  machine) and re-validate after.
- UC20+ only. A UC16/18 model (top-level `gadget`/`kernel`/`required-snaps`)
  gets a migration path, not a fix list — reference §4.
- The validator checks `storage-safety` whenever it is present (it is optional
  and valid at any grade): the value must be `prefer-unencrypted`,
  `prefer-encrypted` or `encrypted`, and a `secured` model accepts only
  `encrypted`. It also checks snap `components`: bare component names (not
  `<snap>+<component>`), `presence` required/optional, component modes within
  the snap's modes. It does **not** check `validation-sets`; if present, review
  them by hand against the official reference and say they were hand-checked.
- If the user names one file and the directory holds sibling models, validate
  only what they asked, then offer a directory run: siblings sharing
  `series`+`brand-id`+`model`+`revision` are mutually exclusive identities
  (reference §3).
- **Stage × grade convention.** Files named `<grade>-<stage>.json`
  (`dangerous|signed|secured` × `edge|next|stable`) are checked against
  their name: `grade` must match, and every snap's risk must match the stage
  (edge→`edge`, next→`beta`, stable→`stable`). The variants are reflashed,
  never remodelled, so a full set sharing one identity is reported as
  expected, not as a collision.
- A channel with nothing published yet (a standard risk with no release, a
  release-number track not created yet, no build for the architecture) is a
  **warning**, not
  an error: the assertion may be written before development reaches that
  channel. Tell the user the image build will fail until it is published.
  A misspelt channel name is an **error**, not an early release: the risk must
  be `stable`, `candidate`, `beta` or `edge` (`26/stble` — snapd refuses to
  sign it), and the track must be `latest` or an Ubuntu Core release number
  such as `22`, `24`, `26` (`2b/stable` signs, but is still wrong).
  Documented variants (`24-hwe`, `26-rt`, `22-oem`, `26.04`, `classic-24.04`)
  are a **warning**: legal, but ask whether they are deliberate.

Details on the ledger, brand stores, batch runs and throwaway keys:
`references/validator-behaviour.md`.

## Step 3: Confirm what no tool can know

Ask once, as one grouped question. The rows come from the validator's
CONFIRM list, and every row is a question the user answers: field, current
value, what to check. A value that already checks out (a kernel track that
matches the base, a grade the user already stated) is not a row — put it
under "Worth knowing" if it is worth saying at all. Typical rows:

- **architecture** — an amd64 image never boots an arm64 board, and nothing complains
- **brand-id** — the validator resolves it to an account display name; quote that
- **model name** — permanent device identity; renaming means re-serialising
- **store id** — the dashboard id, not the display name; a wrong one shows up as fleets that cannot refresh
- **grade** — `dangerous` headed for production, or `signed` while still iterating
- **kernel/gadget track vs base** — only when the validator flags it: a different release number than the base is usually a leftover; a variant track (`24-hwe`, `26-rt`) may be deliberate
- **unresolvable snaps** — only the user has the snap-id

If the conversation already answered one (e.g. "our pi fleet"), state the
assumption instead of asking. With nobody to ask, see the hard rules.

## Step 4: Report

Order: *is anything broken?* → *are these values yours?* → *anything else?*

```
## Verdict
FAIL — signs cleanly, but the image build cannot resolve one snap. One error.
1. snaps "my-gadget": snap-id mismatch — the store says XyZ… (paste the real id).

## Not published yet (warning)
- snaps "my-kernel": 24/stable has no release (track 24 only has edge).
  Expected for this stage; the image build fails until it is published.

## Please read these values
| Field | Current value | Check |
|---|---|---|
| architecture | `arm64` | the board you are building for? |
| brand-id | `mybrand` | resolves to "My Brand Ltd" — is that you? |

## Worth knowing
- Only the gadget needed the brand store; the rest resolved publicly.
```

- Keep the confirm values in a table; do not flatten them into prose. Every
  row ends in a question; nothing in the table is "for information only".
- Say what happens if ignored: "will not sign" vs "signs but breaks at build"
  vs "builds but will not encrypt".
- Give the exact corrected value (paste the snap-id). If no correct value
  exists, say so — do not offer a menu of tracks from the wrong generation.
- Non-blocking observations (risk fallback, brand-store usage, sibling
  `.assert` in sync or drifted, unchecked sibling set) go under "Worth knowing".

## Step 5: Show the fix, then the plain-English readback

Show the exact edit (line and value), or full corrected JSON written to `/tmp`.
Do not apply it. When clean, give the next commands in their workflow:

```bash
snap sign -k KEYNAME model.json > model.model
ubuntu-image snap -O output/ model.model
```

Always show the validator's `What this model actually says` section before
calling the job done, framed as "have a read and tell me if anything is off".
Every check answers "is this well-formed?"; only the readback answers "is this
the device you meant?". If the user corrects something, revise and re-validate.

## Step 6: Hand the decisions back

End every run, PASS or FAIL, with these questions:

1. Do you want to change anything based on the report?
2. Only if the timestamp's UTC date is not today: "The timestamp is currently
   `<value>` — refresh it in your file?" (This writes to their file, the only
   write this skill makes, and only on a yes.) In a batch, ask about the files
   whose date is not today and name them. When every timestamp is from today,
   say so in one line instead of asking.

On yes: `python3 $SKILL_DIR/scripts/validate_model.py MODEL.json --update-timestamp --online`,
then confirm the new value. Mention `snap sign --update-timestamp` as the
alternative that never touches the source. Never refresh timestamps for a batch
on one "yes" (the script refuses). With nobody to ask, list both as open items
and leave the file untouched.

If the user explicitly asks you to apply a fix, that is a new mandate: apply
it, re-run the validator, and remind them to re-sign. The mandate covers
errors that have exactly one correct value (a JSON type, `x86_64` → `amd64`,
a snap-id the store returned). It does not cover Step 3 items or guesses —
kernel/gadget track, grade, brand-id, and anything you would have to guess:
leave those values as they are and list them as questions.

## Common mistakes

| Mistake | Correct behaviour |
|---|---|
| "It's a one-character fix, I'll just apply it" | Show it; the user applies it |
| Filling in confirm answers in CI so the report looks complete | List them as open questions |
| Reporting "PASS" from an offline or sign-only run | Say what was not checked |
| Summarising the ledger as "all snaps verified" | Show the per-snap ledger |
| Calling an unresolvable brand-store snap a typo | Warning plus a snap-id request |
| Skipping the readback, or the timestamp question on FAIL | Readback always; timestamp question whenever the date is not today |
| Asking to refresh a timestamp written today | Say it is current; no question |
| Adding "no answer needed" rows to the confirm table | Only rows that need an answer; the rest goes under "Worth knowing" |
| Running `snap create-key` / real-key `snap sign` | `--create-key`, or hand the command over |

## Scope

This skill validates; it does not design. If the user wants help deciding what
belongs in the model (grade, pinned tracks, model vs seed), answer that first,
then validate the result.

`references/model-assertion-reference.md` holds header tables, snapd error
messages mapped to causes, the UC16/18 migration path and full examples. Read
it when asked *why* a rule exists, for an error the validator did not
anticipate, or when writing a model from scratch.
