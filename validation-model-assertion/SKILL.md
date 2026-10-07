---
name: validation-model-assertion
description: Validate an Ubuntu Core / snapd model assertion JSON before signing or building an image — read-only by design, it never edits the file you give it. Checks structure, snap-ids, channels, grade, architecture, and base/track coherence, surfaces the values only a human can confirm, then explains exactly what to fix and leaves the decision to you. Use this whenever the user mentions a model assertion, model.json, snap sign, ubuntu-image, snap prepare-image, remodeling, Ubuntu Core image building, or shows you a JSON/assertion file containing brand-id, grade, or a snaps list — even if they only say "does this look right?" or paste the file without asking a question.
---

# Validating a model assertion

A model assertion is the contract that defines an Ubuntu Core device: which
kernel, gadget, base and snaps it ships, who signs it, and how locked-down it
is. Mistakes in it are expensive, because the feedback loop is long — you sign
it, feed it to `ubuntu-image`, wait for a multi-gigabyte build, and only then
find out that a snap-id was copied from the wrong snap. The point of this skill
is to collapse that loop to a few seconds.

## The one rule above all others: never modify the model being validated

This is a read-only job. The file you were handed is the evidence, and the
moment you edit it you have destroyed the thing you were asked to assess — the
user can no longer tell what the original said, a diff appears in a repository
other people build from, and if the file was already signed, the signature no
longer matches its content.

That stays true when the fix is obvious, when it is a single character, and
when you are certain. Being right is not the same as being asked. A validator
that silently corrects its input is a tool nobody can audit, and the whole
value of this skill is that its output can be trusted.

So: report, show the corrected JSON in your reply, or write a copy to a scratch
path and say where it is. Let the user apply it. The *only* exception is
`--update-timestamp`, and only after the user has seen the report and
explicitly said yes to that specific question (Step 7). Nothing else — not a
snap-id the store disagrees with, not a malformed architecture, not a stale
channel — gets written back on your initiative.

## Before you start: four constraints that apply to the whole run

These cost you more than quality if you get them wrong, so they come first
rather than buried in the workflow. They matter most when nobody is watching
the run.

### When you cannot ask

Sometimes there is nobody to ask: a CI job, a batch run over a directory, a
subagent with no channel back to the user. The failure mode to avoid is
answering the questions yourself. A confirmation you invented is strictly worse
than an open question, because it looks settled — the engineer skims the
report, sees no question, and ships a model whose architecture nobody actually
checked.

So carry the questions forward instead. Put them in the report as one explicit,
consolidated list headed something like "Only you can confirm these", keep the
model's current value next to each one, and say plainly that the run could not
verify them. A report that ends with five honest questions is a useful
artefact. One that ends with five silent assumptions is a liability.

The same applies to anything requiring credentials: say which checks were
skipped and why, rather than letting a clean report imply they passed.

### Nothing you produce should land in their working tree

This is the top rule applied to the surrounding mess: scratch files, converted
assertions, downloaded reference models. Model assertions usually live in a git
repository someone else builds from, so write your working files to `/tmp` or
somewhere clearly disposable, and clean up after yourself. An unexplained
`model.json.new` next to their assertions is nearly as unwelcome as editing the
original. When reviewing a directory, treat every file in it as read-only.

### Customer identifiers belong in the report and nowhere else

A model assertion is commercially identifying. `brand-id`, `model`, the brand
`store` id and brand-scoped snap names together name a customer, a product and
a private store, and a brand store id in particular is an access-relevant
secret that is not meant to circulate.

Those values are fine in the report you hand back — that is the whole point of
the confirm table, and the user already has them. What must not happen is them
coming to rest anywhere else: not in a scratch file you forget to delete, not
in a commit message or a PR description, not in a bug report, and above all not
written back into this skill, its examples, its evals or its reference. A skill
file is permanent and travels to every future session and every other user, so
a customer name pasted into an example as a convenience becomes a disclosure
that nobody notices.

When you need an example, invent one: `mybrand`, `acme-robotics`,
`my-brand-store-id`. When you are tempted to record a real run as a worked
example, don't — paraphrase the shape of the problem instead. The same applies
in reverse: if you notice a real brand-id, store id or customer snap name
already sitting in a skill, a template or a committed example, say so, because
it is a leak rather than a style issue.

### Never run a command that waits on a terminal

This is the one that costs you the entire run rather than a bit of quality.
`snap create-key` prompts for a passphrase, and `snap sign` with a real key
does too. In a session with no TTY they do not fail — they block, silently,
until something gives up. No output, no error, no partial result.

Signing is the only place in this workflow that wants a terminal, and the
validator already has a non-interactive path for it (`--create-key`, below).
If a signing round-trip needs the user's real key, hand them the command to run
themselves rather than attempting it. Everything else here — validation, store
lookups, `snap known --remote` — is safe.

## Step 1: Get the model assertion

**Always start from a concrete model file.** Do not write advice about a
hypothetical model, and do not invent one to validate. If the user has not
already given you the JSON, ask for it and offer the ways they might have it:

- a path to a `.json` file they are editing (most common)
- pasted JSON in the conversation — write it to a file first, because the
  validator works on files and you want a stable artefact to iterate on
- an already-signed `.model` or `.assertion` file — this is the signed
  YAML-ish form, not JSON. Convert it back with
  `scripts/assertion_to_json.py model.model > model.json`
- a running or built device: `snap model --assertion > model.model`, or from
  `/var/lib/snapd/assertions/asserts-v0/model/`

If they give you a signed assertion, say clearly that you are validating the
*content*, not the signature — re-signing is a separate step, and editing a
signed assertion always invalidates its signature.

## Step 2: Run the validator

Set this once and the rest of the commands work from any directory, which
matters because the model file is usually somewhere else entirely:

```bash
SKILL_DIR=~/.agents/skills/validation-model-assertion
python3 $SKILL_DIR/scripts/validate_model.py MODEL.json --online
```

The remaining examples write `scripts/validate_model.py` for brevity; they all
mean `$SKILL_DIR/scripts/validate_model.py`.

**Validating a set.** The script also accepts several paths, or a directory:

```bash
python3 scripts/validate_model.py assertions/amd64/26/ --online
```

Reach for this whenever the user has a folder of variants, because some of the
most expensive mistakes are invisible one file at a time. Nine files that each
validate perfectly can still be nine assertions competing for one device
identity (see "Across the set" below). A batch run also merges identical
findings — one shared kernel problem reported once with "(all files)" instead
of nine times — and asks each confirmation question once rather than per file,
which is the difference between five questions a person will answer and
forty-five they will skip. Store lookups are cached across the set, so a
directory is barely slower than a single file.

The script layers three independent kinds of checking, and the layering is the
whole idea:

| Layer | What it catches | Why it exists |
|---|---|---|
| structural | missing/mistyped headers, illegal grade, essential snap with `presence`, an incomplete boot chain, an end-of-life model format | these are mostly the rules snapd itself enforces; the script reports them per-field instead of as one opaque error |
| semantic (`--online`) | snap-id belongs to a different snap, wrong snap `type`, track that does not exist, no build for this architecture | **`snap sign` does not check any of this.** `"architecture": "x86_64"` signs perfectly and then fails at image build |
| advisory | stale timestamp, a channel that silently falls back to a more stable risk | not errors, but each one has burned somebody |
| confirm | architecture, brand-id, model name, store id, grade, track-vs-base, unresolvable snaps | legal values that only a human can judge — see Step 3 |

**Scope: UC20 and later.** Ubuntu Core 16 and 18 are end-of-life, and the
validator rejects that format with a migration path instead of checking it.
A UC16/18 model is recognisable by top-level `gadget` / `kernel` /
`required-snaps` headers where a UC20+ model has a `snaps` list. If the user
brings one, the useful answer is how to move it to a supported base — not a
list of things to fix in a format that has no snap-ids, no grade and no
supported kernel. See §4 of the reference.

**The four essential snaps.** A UC20+ model should pin `gadget`, `kernel`,
`base` and `snapd` — all four. `snap sign` only insists on kernel and gadget,
so a model missing the other two signs cleanly and looks fine. The cost shows
up later: nothing pins the base and snapd revisions, so the image builder takes
whatever the store serves that day and two builds of the "same" model ship
different software. The script treats all four as errors for that reason, and
the summary prints the boot chain in fixed order so a gap is visible rather
than merely absent. Classic hybrid models are the exception — kernel and gadget
come from the host install there, so only base and snapd are expected.

The report ends with a plain-English summary of what the model describes; that
is Step 6 and it is not optional.

The report is ordered ERROR → WARN → CONFIRM → INFO, and the verdict counts
all four. Exit code is 1 only if there are errors, so `CONFIRM` items never
block a script.

**The store-lookup ledger.** After the findings, the report lists every snap it
looked up and what happened — `snap-id verified`, `NOT FOUND`, `local snapd`,
`MISMATCH`. Show this to the user; do not summarise it away. Silence is
ambiguous in exactly the place it matters most: a brand-store gadget that was
checked and matched produces no finding, and so does one that was never checked
at all. The reader cannot tell those apart from a clean report, and "the
validator didn't complain" is how an unverified snap-id reaches a device. Any
snap without a verified id is something only the user can vouch for, and the
ledger is what makes that list visible.

Offline runs print the ledger too, saying plainly that nothing was checked
against reality. An offline PASS means "well-formed", not "correct" — say so.

`--online` only talks to `https://api.snapcraft.io` and needs no credentials.
Use it unless the user is offline or the snaps are private — then say which
checks you skipped rather than silently dropping them.

**Brand stores.** The validator reads the model's own `store` header
automatically, so you rarely need to pass anything. `--store ID` exists for the
case where the model has no `store` header but the snaps live in a brand store
anyway — a model being drafted, or one that relies on the device's store
assignment:

```bash
python3 scripts/validate_model.py MODEL.json --online --store my-brand-store-id
```

It also falls back to asking the local snapd (`snap info --verbose`) for snaps
the public API cannot see. A snap it still cannot resolve is reported as a
**warning**, not an error, because in a brand-store workflow that is the
expected answer — do not tell the user their snap name is wrong when all you
know is that you cannot see it. Instead point them at `snapcraft status <snap>`
or a machine attached to that store. Truly private snaps need credentials; be
explicit that the check was skipped rather than implying it passed.

The ledger distinguishes a snap that genuinely needed the brand store from one
that resolved identically without it, and that distinction is worth repeating
to the user. Most snaps in a brand-store model — `core26`, `snapd`, a public
kernel — come from the global store and the brand header changes nothing; only
the gadget is usually brand-scoped. Saying "verified in <brand store>" for all
of them overstates what was checked. It also hides a real risk: a brand store
can shadow a public snap of the same name, so if the public namespace answers
with a *different* snap-id, the ledger says so explicitly. That is worth
reading carefully, because the model's declared id is what decides which one
the device actually gets.

For the authoritative structural verdict, add a signing round-trip:

```bash
python3 scripts/validate_model.py MODEL.json --online --sign-check -k KEYNAME
```

This pipes the JSON through `snap sign`, which runs snapd's own assembler. If
it assembles, the structure is definitively valid. It needs a key; check with
`snap keys` first — if there is none, see "Creating a throwaway validation key"
below. Be aware that `--create-key` leaves a real key behind in snapd's GnuPG
keyring, so plan on removing it afterwards; the cleanup commands are in that
section. Skip the round-trip if no key is available — the structural layer
already covers the same rules.

A round-trip on its own is not a verdict, either. `snap sign` never goes
online, so `--sign-check` without `--online` can print PASS for a model whose
snap-ids point at entirely different snaps. Pair the two whenever you can.

**Across the set.** A batch run adds one check that no single file can
support, and it has caught a real problem:

*Shared device identity.* A model is identified by `series` + `brand-id` +
`model`, with `revision` as the tiebreaker — filenames are irrelevant. If a
folder holds `dangerous-edge.json`, `signed-next.json` and `secured-stable.json`
with the same brand-id and model name and no `revision` header, they all
default to revision 0. Each one validates. Each one signs. But a device accepts
the highest revision and treats it as superseding the rest, so those are not
three variants — they are three mutually exclusive assertions for one identity,
and you cannot remodel between them because a remodel requires the revision to
increase. When you report this, be clear it is a product decision rather than a
syntax fix: separate `model` names if the variants are meant to coexist in the
field, or increasing `revision` values if they are a hardening progression of
one product.

*Drift from the signed sibling.* This one runs for a single file too. If a
`.assert` / `.model` file sits next to the JSON, the script converts it back
and compares. People edit the JSON and forget to re-sign, and then the file
under review stops describing the artefact that actually ships. A match is
reported too, because knowing the pair is in sync is worth as much as knowing
it is not.

**When the user names one file but it has siblings.** Validate what they asked
for. If the directory holds other model JSONs, mention in a line at the end
that the set has not been checked for shared-identity collisions and offer the
directory run — do not silently widen the scope, because a report that answers
a question nobody asked buries the one they did ask.

## Step 3: Confirm what the machine cannot know

The `CONFIRM` block is the part of the report that is **not** a finding — it is
a short list of things that are perfectly legal, that no tool can check, and
that are wrong often enough to be worth one question. Typically:

- **architecture** — an amd64 model produces a flawless image that no arm64
  board will ever boot. Nothing downstream complains, so ask.
- **brand-id / authority-id** — a free-form string that only has to be
  self-consistent. The validator resolves it against the store's account
  assertions, so you can say "`canonical` resolves to Canonical (certified)" or
  "no account exists for `acme-rootics`" rather than just repeating it back.
  A model signed under a brand-id whose key you do not hold signs fine and is
  then rejected by the device.
- **model name** — part of the device's permanent identity. Renaming it later
  means re-serialising devices, not just rebuilding an image, so a typo or a
  stale revision suffix is expensive.
- **store id** — a wrong brand store id is invisible at signing time and shows
  up as fleets that cannot refresh. It is the store's ID from the dashboard,
  not its display name.
- **grade** — `dangerous` in something headed for production, or `signed` in
  something the user is still iterating on locally.
- **kernel/gadget track vs base** — a `core26` model with a `24/stable` kernel
  might be a leftover, or might be a deliberate hwe/rt/vendor track.
- **snaps that cannot be resolved** — brand-store and private snaps are
  invisible from an unauthenticated session, so the snap-id can only come from
  the user.

Ask these as **one grouped question**, not seven separate ones, and make each
answerable without research — state what the model currently says and what the
alternative would be. Interactive confirmation is worth it here because each of
these failures costs an image build or a field deployment to discover, but
pestering the user about things the validator already decided costs you their
attention. If the user has already made it clear in the conversation (e.g.
"our pi fleet"), do not ask again — state the assumption you are carrying
forward instead.

For an unresolvable snap, ask for the snap-id directly and tell them where to
get it:

```
rover-control is not visible from here — if it's in your brand store, what's
its snap-id? (`snapcraft status rover-control`, or `snap info --verbose
rover-control` on a machine attached to that store)
```

Then put the answer in the model and re-validate, so the final state is
verified rather than assumed.

If there is nobody to answer — a CI job, a directory sweep, a subagent — go
back to "When you cannot ask" above and carry the questions into the report
instead of resolving them yourself.

## Step 4: Report findings the way an engineer wants them

The report answers three questions in this order, because that is the order the
reader needs them in: *is anything broken?*, *do these values look like mine?*,
and *anything else I should know?*

```
## Verdict

FAIL — signs cleanly, but the image build cannot resolve what this model asks
for. One error.

1. snaps "acme-kernel": track 24 does not exist for arm64. Published tracks are
   20 (5.4.0-1068), 22 (5.15.0-1045) and latest (5.4.0-1017), and none of them
   belongs to core24 — so this needs a kernel build, not a different channel.

## Please read these values

| Field | Current value | Check |
|---|---|---|
| architecture | `arm64` | the board you are building for? |
| grade | `signed` | store-asserted snaps only |
| brand-id | `acme-robotics` | resolves to "Acme Robotics Ltd" — is that you? |
| model | `acme-rover-v3` | right product and revision? |
| store | `my-brand-store-id` | the store id from the dashboard, not its name |

## Worth knowing

- Only the gadget actually needed the brand store. acme-kernel, core24, snapd
  and console-conf resolved from the public store, so the brand store header
  changed nothing for them.
- signed-stable.assert matches this JSON, so the signed artefact is in sync.
```

The validator produces the table for you — it keeps each value in its own field
precisely so the report can present them this way. Do not flatten it back into
prose. The values that land in that table (architecture, brand-id, store id)
are wrong *silently*: nothing downstream objects, and the first symptom is a
device that will not boot. Scanning one column is a different and much more
reliable act than reading five sentences.

Three habits that make the difference:

- **Say what happens if they ignore it.** "will not sign" vs "will sign but
  break at build" vs "will build but the device will not encrypt" are three
  very different levels of urgency, and the user cannot tell them apart from
  the error text alone. The verdict line already makes this distinction — carry
  it through rather than flattening everything to "invalid".
- **Give the corrected value, not just the rule.** If the store says the
  snap-id is `UqFziVZ...`, paste it. The user is going to paste it anyway. The
  exception is when there is no correct value to give: if a kernel has no track
  for this base, say that plainly instead of listing tracks, because a list of
  options reads as a menu and the nearest-looking option is usually the wrong
  generation.
- **Put the things that are not errors under "Worth knowing".** A channel that
  silently falls back to a more stable risk, a snap that did not need the brand
  store after all, a `.assert` sibling that matches or has drifted — none of
  these block anything, and all of them have surprised somebody. This section
  is also where an observation the tool cannot make belongs: if the file sits
  in a directory of sibling models that has not been checked as a set, say so
  here and offer the directory run.

Close every report the same way, PASS or FAIL: hand the decisions back. What to
change and whether to refresh the timestamp are both the user's calls, not
yours — that is Step 7, and it is the natural last section of the report rather
than a separate conversation.

## Step 5: Show the fix — do not apply it

Give them the concrete edit, not a description of it: the exact line, the exact
corrected value, pasteable. If several things change, show the corrected JSON
in your reply or write a copy to `/tmp` and say where it is.

Then stop. Applying it is their call, for the reasons at the top of this file —
and often they know something you do not. A channel that looks stale may be
pinned deliberately; a snap-id you cannot resolve may be a snap that has not
been published yet. Your evidence is the store and the schema; theirs is the
product.

If they explicitly ask you to make the change, make it — that is a different
request from the one you started with, and now you have the mandate. Re-run the
validator afterwards so the result is demonstrated rather than claimed, and if
the file was already signed, remind them the signature no longer matches.

When the model is clean, tell them the next command in their actual workflow:

```bash
snap sign -k KEYNAME model.json > model.model     # sign
ubuntu-image snap -O output/ model.model          # build an image
snap prepare-image --channel=stable model.model ./seed/   # or just seed it
```

Editing a signed assertion always invalidates its signature, so any change at
all means re-signing before it is good for anything.

## Step 6: Read the model back in plain English

The validator ends with a `What this model actually says` section — prose
describing the brand, the model name, the release, the architecture, the
security grade, the boot chain, the extra snaps and where they come from.
**Always show this to the user before you call the job done.**

This exists because every check above answers "is this well-formed?", and none
of them answers "is this the device you meant to build?" A model can pass every
layer and still pin last year's kernel track, name the wrong product, or ship
at `dangerous` because someone was debugging in March. Those are invisible in
JSON and obvious in a sentence — people read prose for meaning and JSON for
syntax, so the same mistake that hides in a `snaps` list jumps out of
"Security grade **dangerous** — no secure boot, no disk encryption".

Present it as something to read, not something to approve:

```
Here's what this model describes — have a read and tell me if anything is off:

Acme Robotics (brand-id "acme-robotics") ships a device model called
"acme-rover-v3", running Ubuntu Core 24 on arm64.
Security grade signed — store-asserted snaps only; secure boot and
full-disk encryption available.
...
```

If the user corrects something here, that is the skill working, not a failure —
fix the model and re-validate so the final state is verified end to end.

## Step 7: Hand the decisions back to the user

End every run the same way, whether the verdict was PASS or FAIL. You have
reported what is broken and shown them the values only they can vouch for; what
happens next is theirs to decide, and the report is not finished until you have
said so explicitly.

Ask two things, and ask both even when the model failed. A FAIL is not a reason
to withhold the timestamp question — they may be fixing the kernel channel this
afternoon and want the timestamp refreshed in the same edit, or they may
consider the finding a non-issue for their workflow. Deciding that on their
behalf is the same mistake as editing their file.

```
That's everything I found. Two things for you:

1. The acme-kernel channel is the only hard blocker — nothing I can fix from
   here, since it needs a 24 track to exist. Want to change anything based on
   the report, or is this expected for now?

2. The timestamp is currently 2026-09-22. Want me to refresh it to now? The
   file is in your repo, so this would show up as a diff — it's the only
   change I'd make to the file, and only if you say yes.
```

Make the second question explicitly about *writing to their file*, because it
is the one place this skill touches their working tree. If they say yes:

```bash
python3 scripts/validate_model.py MODEL.json --update-timestamp --online
```

That rewrites it in place (UTC, RFC3339) and re-validates. Confirm the new
value afterwards so nothing changed silently.

If they would rather leave the file alone, `snap sign --update-timestamp` does
the same thing to the signing output at signing time and never touches the
source — mention it, because it is usually the better answer for a model under
version control.

Two things to know about how the script judges a timestamp: it only mentions
age past a year (an INFO, since a model under version control is *expected* to
carry an old one), and it warns about a timestamp more than a day in the
future, which usually means a clock problem or a hand-edited date. Neither is
an error, and `--update-timestamp` is refused for a batch run — rewriting nine
of someone's files on the strength of one "yes" is not what they agreed to.

If there is nobody to ask, do not resolve either question yourself. Put them at
the end of the report as open items and leave the file untouched; see "When you
cannot ask".

## Creating a throwaway validation key

`--sign-check` needs a key. Never run `snap create-key` here — see "Never run a
command that waits on a terminal" above. The validator handles this for you:

```bash
python3 scripts/validate_model.py MODEL.json --sign-check --create-key
```

That reuses an existing `model-validation-throwaway` key or generates one
non-interactively (`gpg --batch --quick-generate-key` in snapd's own keyring).
Without `--create-key` and without a key present, the check is simply skipped
and says so — which is the right outcome, because the structural layer already
covers the same rules and a blocked session helps nobody.

Tell the user what the key is: unregistered, passphrase-less, trusted by no
device, and only useful for proving that snapd can assemble the assertion.
Their real signing key is a different thing entirely — created with
`snap create-key`, registered with `snapcraft register-key`, and it should
keep its passphrase.

The same hazard applies to signing with a real key: if `snap sign` hangs, it is
waiting for a passphrase on a terminal that does not exist. Hand the command to
the user to run themselves rather than retrying it.

Clean up when you are done, so you do not leave an unexplained key in someone's
snapd keyring. There is no `snap remove-key` — snapd only creates keys, so
removal goes through the GnuPG keyring it keeps under `~/.snap/gnupg`:

```bash
snap keys                                                   # confirm what is there
gpg --homedir ~/.snap/gnupg --list-secret-keys              # get the fingerprint
gpg --homedir ~/.snap/gnupg --batch --yes \
    --delete-secret-and-public-key <FINGERPRINT>
snap keys                                                   # verify it is gone
```

## Deeper reference

`references/model-assertion-reference.md` has the full header tables for each
model format, the real `snap sign` error messages mapped to their causes, and
complete worked examples (UC24 signed, UC26 brand-store, classic hybrid), and the
UC16/18 migration path. Read it when
the user asks *why* a rule exists, when you hit an error the validator did not
anticipate, or when you need to write a model from scratch rather than check
one.

## A note on scope

This skill validates; it does not design. If the user actually wants help
deciding what should be in the model — which grade, whether to pin tracks,
whether a snap belongs in the model or in a seed — answer that on its merits,
then validate the result. Running the validator on a model that does not yet
express what they want is just a fast way to confirm the wrong thing.
