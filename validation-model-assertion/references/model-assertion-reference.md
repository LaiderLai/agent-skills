# Model assertion reference

Everything here was verified against snapd 2.77.1 by feeding JSON to
`snap sign` and recording what it accepts and rejects. Where snapd's behaviour
differs from the published docs, snapd wins — it is what actually runs.

Contents:
1. [The one rule that surprises everyone](#1-the-one-rule-that-surprises-everyone)
2. [Which format am I looking at?](#2-which-format-am-i-looking-at)
3. [Headers: UC20+ (extended snaps header)](#3-headers-uc20-extended-snaps-header)
4. [UC16/18 is end-of-life](#4-uc1618-is-end-of-life)
5. [Classic hybrid models](#5-classic-hybrid-models)
6. [The `snaps` list](#6-the-snaps-list)
7. [Grades](#7-grades)
8. [Error message → cause](#8-error-message--cause)
9. [What `snap sign` does NOT check](#9-what-snap-sign-does-not-check)
10. [Complete examples](#10-complete-examples)
11. [Signing and key workflow](#11-signing-and-key-workflow)
12. [Common pitfalls](#12-common-pitfalls)

---

## 1. The one rule that surprises everyone

**Every value in the JSON must be a string.** Assertion headers hold strings,
or lists/maps whose only scalars are strings. JSON booleans and numbers are
rejected at a level below the model validator, with an error that does not
mention your field in a helpful way:

```
"series": 16        → error: header "series": header values must be strings ...: 16
"classic": true     → error: header "classic": header values must be strings ...: true
"id": null          → error: header "snaps": header values must be strings ...: <nil>
```

Correct: `"series": "16"`, `"classic": "true"`. There is no `null` — omit the
field instead.

---

## 2. Which format am I looking at?

| Signal | Format |
|---|---|
| has a `snaps` list | UC20+ ("extended snaps header") — the only supported format |
| has `gadget` / `kernel` / `required-snaps` top-level headers | UC16/18 — end-of-life, see §4 |
| has `snaps` **and** `"classic": "true"` + `distribution` | classic hybrid |
| has both a `snaps` list and `gadget`/`kernel` headers | invalid — snapd rejects it |

The two formats are mutually exclusive, and the error says so:

```
cannot specify separate "gadget" header once using the extended snaps header
cannot specify a grade for model without the extended snaps header
```

---

## 3. Headers: UC20+ (extended snaps header)

| Header | Required | Value |
|---|---|---|
| `type` | yes | `"model"` |
| `series` | yes | `"16"` (string) |
| `authority-id` | yes | must equal `brand-id` |
| `brand-id` | yes | your store account id (`snapcraft whoami`) |
| `model` | yes | lowercase alphanumerics and single dashes |
| `revision` | no (defaults to `0`) | string integer. See the note below — this is the header people forget |
| `architecture` | yes | `amd64`, `arm64`, `armhf`, `i386`, `ppc64el`, `s390x`, `riscv64` — **not validated by snapd**, see §9 |
| `base` | yes | `core20`, `core22`, `core24`, `core26` … — the number also tells you which kernel/gadget track to expect. `core` and `core18` are end-of-life and rejected |
| `grade` | no (defaults to `signed`) | `dangerous` \| `signed` \| `secured` |
| `snaps` | yes | list of maps, see §6 |
| `classic` | no | `"true"` only for hybrid models, see §5 |
| `distribution` | only if classic | e.g. `"ubuntu"` (os-release ID) |
| `store` | no | brand store id |
| `serial-authority` | no | list of account ids allowed to sign serials, commonly `["generic"]` |
| `system-user-authority` | no | list of account ids, or `"*"` |
| `timestamp` | yes | RFC3339, e.g. `"2026-10-07T00:00:00+00:00"` — a bare date is rejected |
| `sign-key-sha3-384` | never write it | snapd fills it in when signing |

### The primary key, and why `revision` matters

A model assertion is uniquely identified by `series` + `brand-id` + `model` —
*not* by the filename, and not by `grade` or `base`. `revision` is the
tiebreaker: among assertions sharing that key, a device accepts the one with
the highest revision and treats it as superseding the rest.

This has a consequence that bites teams who keep a directory of variants.
Suppose you keep `dangerous-edge.json`, `signed-next.json` and
`secured-stable.json` side by side, all with the same `brand-id` and `model`,
and none of them declaring `revision`. Each validates. Each signs. But they all
default to revision 0, so they are nine names for one identity, and a device
can hold exactly one of them. Signing a second one does not give you a second
variant — it gives you a collision, and remodelling between them is impossible
because a remodel requires the revision to increase.

Two ways out, and the choice is a product decision rather than a syntax one:

- **Different products**: give each variant its own `model` name
  (`acme-rover-dev`, `acme-rover-prod`). They become separate device
  identities, serialised separately, and can coexist in the field.
- **A progression of one product**: keep the `model` name and give each
  successive version an increasing `revision`. This is what remodelling
  expects — `dangerous` → `signed` → `secured` as the product hardens.

Validating one file at a time cannot see this, because nothing is wrong with
any individual file. It only becomes visible when you look at the set.

---

## 4. UC16/18 is end-of-life

Ubuntu Core 16 and 18 have reached end of life, and the validator rejects
models in that format outright rather than checking them. A model that
validates is an invitation to keep shipping it, and for these there is nothing
worth validating: the base is out of support, and the format cannot express
`grade`, `presence`, `modes` or snap-ids at all. Snaps are pinned by name only,
so the model does not even constrain which publisher's snap ends up on the
device — which is precisely why UC20+ replaced it.

You can still recognise one by its top-level headers:

| Header | Meaning |
|---|---|
| `gadget` | snap name, optionally `name=track` e.g. `pc=18` |
| `kernel` | snap name, optionally `name=track` |
| `base` | `core` (implied) or `core18` |
| `required-snaps` | list of snap names |

### Migrating to UC20+

1. Pick a supported base: `core20`, `core22`, `core24` or `core26`.
2. Replace `gadget` / `kernel` / `required-snaps` with an extended `snaps`
   list. Every entry needs `name`, `type` and `default-channel`; `id` is
   mandatory once the grade is `signed` or `secured`.
3. Include all four essential snaps — gadget, kernel, base and snapd (§6).
4. Add a `grade`. Omitting it defaults to `signed`, which then requires ids.
5. Move the kernel and gadget onto the track matching the new base, e.g.
   `24/stable` for `core24`.
6. Refresh the `timestamp`.

The old `pc=18` syntax has no equivalent: the track moves into
`default-channel`, and the `=track` suffix is simply dropped from the name.

Run the validator on the migrated file with `--online` — the ids and channels
are the parts most likely to be wrong, and they are exactly what the old format
never let you state.

---

## 5. Classic hybrid models

A classic hybrid system is a normal Ubuntu rootfs managed by snapd's boot
chain. It uses the UC20+ format plus:

```json
"classic": "true",
"distribution": "ubuntu"
```

Verified behaviour:

- `distribution` is **mandatory** when `classic` is `"true"`
  (`"distribution" header is mandatory, see distribution ID in os-release spec`)
- `distribution` without `classic` is rejected
  (`cannot specify distribution for model unless it is classic and has an extended snaps header`)
- `classic` must be the string `"true"` or `"false"`; `"yes"` is rejected
- kernel and gadget snaps become **optional** — a classic hybrid model with
  neither signs fine
- essential snaps still cannot carry `presence`

### Verifying the identity headers

`brand-id`, `authority-id`, `model` and `store` are free-form strings that only
have to be self-consistent, so a typo signs cleanly and fails at the device.
The brand is the one you can actually check — account assertions are public:

```bash
snap known --remote account account-id=canonical
# type: account
# account-id: canonical
# display-name: Canonical
# username: canonical
# validation: certified
```

No output (and exit 0) means no such account. The validator does this lookup
during `--online` and reports the display name, so the user is confirming
"Canonical" rather than re-reading a string they just typed. A brand-store
account that has never published publicly may legitimately not resolve, so this
is a **confirm**, not an error.

`model` and `store` cannot be checked at all — the model name is part of the
device's permanent identity (changing it means re-serialising devices), and a
wrong store id surfaces only as fleets that cannot refresh. Both are worth one
explicit question.

---

## 6. The `snaps` list

Each entry is a map of strings:

| Field | Required | Notes |
|---|---|---|
| `name` | yes | snap name |
| `id` | yes for grade `signed`/`secured` | the 32-character snap-id. Optional only for `dangerous` |
| `type` | yes | `app`, `base`, `gadget`, `kernel`, `snapd`, `core` |
| `default-channel` | no (defaults `latest/stable`) | `track/risk`, e.g. `24/stable` |
| `presence` | no | `required` \| `optional`. **Not allowed on essential snaps** (snapd, kernel, gadget, base) |
| `modes` | no | subset of `run`, `ephemeral`, `recover`, `factory-reset` — snapd does **not** validate the values |

Structural rules snapd enforces:

- exactly one entry with `type: kernel` and one with `type: gadget`
  (non-classic): `one "snaps" header entry must specify the model kernel`
- `presence` on an essential snap:
  `essential snaps are always available, cannot specify presence for snap "pc"`
- missing id at signed grade: `"id" of snap "pc" is mandatory for signed grade model`
- malformed id: `"id" of snap "pc" contains invalid characters: "tooshort"`

### The four essential snaps

A complete UC20+ model pins four snaps: **gadget, kernel, base and snapd**.

snapd only *enforces* two of them. Omit the `snapd` entry, or leave the base
implicit because the top-level `base: core26` header already names it, and
`snap sign` produces a perfectly valid assertion. Every Canonical reference
model lists all four anyway, and the reason is reproducibility: the model is
supposed to describe one image, and an unpinned snap is resolved at build time
from whatever the store is serving. Two builds a week apart then ship different
snapd revisions from the same "identical" model — which is exactly the class of
difference that is impossible to debug from the field.

The base entry is also where a stale base hides. A model upgraded from core22
to core26 by editing the top-level header, but still listing `core22` in
`snaps`, signs without complaint and builds an image with both bases.

Classic hybrid models are the exception: kernel and gadget come from the host
installation, so only base and snapd are expected.

Finding a snap-id:

```bash
snap info --verbose pc-kernel | grep snap-id
curl -s -H 'Snap-Device-Series: 16' \
  'https://api.snapcraft.io/v2/snaps/info/pc-kernel?fields=snap-id' | jq -r '."snap-id"'
```

### Brand stores and private snaps

The public API only sees the global store, so a snap published to a brand store
looks identical to a typo. Three ways to resolve one, in order of convenience:

```bash
# 1. brand store namespace - works for snaps published to the brand store
#    without being public globally. No credentials needed.
curl -s -H 'Snap-Device-Series: 16' -H 'Snap-Device-Store: my-brand-store-id' \
  'https://api.snapcraft.io/v2/snaps/info/rover-control?fields=snap-id'
python3 scripts/validate_model.py model.json --online --store my-brand-store-id

# 2. a machine already attached to that store - snapd has the credentials
snap info --verbose rover-control | grep snap-id

# 3. the publishing account
snapcraft login
snapcraft status rover-control
```

The validator tries 1 and 2 automatically (it reads the model's own `store`
header if `--store` is not given, and falls back to the local snapd), and
reports an unresolvable snap as a **warning**, not an error — in a brand-store
workflow "I cannot see it from here" is the expected answer, and treating it as
a typo would be wrong. Genuinely private snaps need credentials and cannot be
checked from an unauthenticated session at all; say so rather than guessing.

Verified snap-ids for common snaps (amd64/arm64 are the same snap):

| snap | snap-id |
|---|---|
| `pc` | `UqFziVZDHLSyO3TqSWgNBoAdHbLI4dAH` |
| `pc-kernel` | `pYVQrBcKmBa0mZ4CCN7ExT6jH8rY1hza` |
| `core22` | `amcUKQILKXHHTlmSa7NMdnXSx02dNeeT` |
| `core24` | `dwTAh7MZZ01zyriOZErqd1JynQLiOGvM` |
| `core26` | `cUqM61hRuZAJYmIS898Ux66VY61gBbZf` |
| `snapd` | `PMrrV4ml8uWuEUDBT8dSGnKUYbevVhc4` |
| `pi` | `YbGa9O3dAXl88YLI6Y1bGG74pwBxZyKg` |
| `pi-kernel` | `jeIuP6tfFrvAdic8DMWqHmoaoukAPNbJ` |

Verify rather than trust this table — snap-ids are stable, but a table in a
document is not a source of truth. One `--online` run checks all of them.

### Bases and tracks

`core26` is current, alongside `core20`/`core22`/`core24`. The convention is
that `coreNN` pairs with the `NN` track of the kernel and gadget:

| base | kernel/gadget track | notes |
|---|---|---|
| `core20` | `20/stable` | |
| `core22` | `22/stable` | `22-hwe`, `22-rt`, `22-oem` variants exist |
| `core24` | `24/stable` | `24-hwe`, `24-rt`, `24.10` variants exist |
| `core26` | `26/stable` | `26-rt`, `26.04`, `26.10` variants exist |

The validator derives the expected track from the base number, so a new
`coreNN` works without any change to the tooling. A mismatch is reported as a
**confirm**, not an error, because hwe/rt/vendor tracks are legitimate.

### How the store resolves a channel

A channel is `track/risk`, and a bare word is ambiguous in a way that matters:
`edge` means `latest/edge`, but `26` means `26/stable`. snapd decides by asking
whether the word is one of the four risks (`stable`, `candidate`, `beta`,
`edge`); anything else is a track name.

The part that causes false alarms when writing tooling is **risk fallback**. If
a risk has no release of its own, the store serves the next *more stable* risk
in the same track. `snap info` shows this with a caret:

```
26.10/stable:     7.0.0-15.15   2026-06-12 (3419)
26.10/candidate:  ^
26.10/beta:       7.3.0-8.8     2026-10-06 (3815)
```

`26.10/candidate` is empty, so it serves the stable revision. The fallback only
runs towards stable — asking for `stable` never gets you an edge build.

Two consequences when checking a model:

- `26/edge` is **valid** even if the store's channel map only lists `26/stable`;
  it resolves to `26/stable`. Flagging it as an error is wrong. It is still
  worth mentioning, because the image will not contain what the channel name
  implies — somebody pinned `edge` expecting fresh builds and will get stable.
- `26/edge` is **broken** when the track `26` does not exist at all, or when the
  track exists with nothing more stable than the requested risk. That is a real
  build failure.

---

## 7. Grades

| Grade | Meaning | Use when |
|---|---|---|
| `dangerous` | no snap-ids needed, unasserted (`--snap local.snap`) snaps allowed, no secure boot chain, no full-disk encryption | bring-up and local iteration |
| `signed` | every snap must be asserted and identified by snap-id; secure boot + FDE available | the normal production choice |
| `secured` | as `signed`, plus recovery modes are restricted — no ephemeral/recover shell escape | devices where physical access is part of the threat model |

Going from `dangerous` to `signed` is where most models break, because the
missing snap-ids suddenly become errors. Validate before you flip the grade.

---

## 8. Error message → cause

All observed from `snap sign` on snapd 2.77.1.

| Message (after `cannot assemble assertion model:`) | Cause |
|---|---|
| `"timestamp" header is mandatory` | no timestamp |
| `"timestamp" header is not a RFC3339 date` | used `2026-10-07` instead of a full timestamp |
| `"base" header is mandatory` | UC20+ model with no base |
| `grade for model must be secured\|signed\|dangerous, not "secure"` | typo in grade |
| `cannot specify a grade for model without the extended snaps header` | grade in a UC16/18 model — migrate it, see §4 |
| `authority-id and brand-id must match ... model assertions are expected to be signed by the brand` | mismatched ids |
| `one "snaps" header entry must specify the model kernel` | no `type: kernel` entry |
| `cannot specify separate "gadget" header once using the extended snaps header` | mixed formats |
| `essential snaps are always available, cannot specify presence for snap "pc"` | `presence` on gadget/kernel/base/snapd |
| `"id" of snap "pc" is mandatory for signed grade model` | missing snap-id at signed/secured grade |
| `"id" of snap "pc" contains invalid characters` | snap-id is not 32 valid characters |
| `"distribution" header is mandatory, see distribution ID in os-release spec` | `classic: "true"` with no distribution |
| `cannot specify distribution for model unless it is classic and has an extended snaps header` | distribution without classic |
| `"classic" header must be 'true' or 'false'` | `"classic": "yes"` |
| `header values must be strings ...` | a JSON boolean, number or null — see §1 |
| `cannot sign using GPG: ... Bad passphrase` | not a model problem; the key needs a passphrase on a TTY |
| `cannot use "default" key: cannot find key pair in GPG keyring` | no key at all; `--sign-check --create-key` makes a throwaway one |
| *(hangs with no output)* | `snap create-key` or `snap sign` is waiting for a passphrase on a TTY that does not exist — never run these interactively from an agent session |

---

## 9. What `snap sign` does NOT check

This is the gap the validator's `--online` layer fills. All of the following
sign successfully and fail later:

- **`"architecture": "x86_64"`** — accepted. `ubuntu-image` then cannot resolve
  a single snap. Only `amd64`, `arm64`, `armhf`, `i386`, `ppc64el`, `s390x`,
  `riscv64` are real.
- **A valid-looking but wrong snap-id** — any 32 alphanumeric characters pass.
  A snap-id copied from the wrong snap builds an image with the wrong kernel.
- **A channel that does not exist** — `99/stable` signs fine.
- **A channel with no build for this architecture** — e.g. an arm64-only
  gadget track in an amd64 model.
- **Unknown `modes` values** — `"modes": ["run", "bogus"]` signs fine; the snap
  is then simply never installed.
- **kernel/gadget track vs base coherence** — a `core24` model with a
  `22/stable` kernel signs fine and usually boots into a mess.

---

## 10. Complete examples

### UC24, grade signed, amd64

```json
{
  "type": "model",
  "series": "16",
  "authority-id": "mybrand",
  "brand-id": "mybrand",
  "model": "my-core24-amd64",
  "architecture": "amd64",
  "base": "core24",
  "grade": "signed",
  "snaps": [
    {"name": "pc",        "id": "UqFziVZDHLSyO3TqSWgNBoAdHbLI4dAH", "type": "gadget", "default-channel": "24/stable"},
    {"name": "pc-kernel", "id": "pYVQrBcKmBa0mZ4CCN7ExT6jH8rY1hza", "type": "kernel", "default-channel": "24/stable"},
    {"name": "core24",    "id": "dwTAh7MZZ01zyriOZErqd1JynQLiOGvM", "type": "base",   "default-channel": "latest/stable"},
    {"name": "snapd",     "id": "PMrrV4ml8uWuEUDBT8dSGnKUYbevVhc4", "type": "snapd",  "default-channel": "latest/stable"},
    {"name": "my-app",    "id": "abcdefghijklmnopqrstuvwxyz123456", "type": "app",    "default-channel": "latest/stable",
     "presence": "required", "modes": ["run"]}
  ],
  "timestamp": "2026-10-07T00:00:00+00:00"
}
```

### UC26, grade dangerous, brand store, arm64

Bring-up configuration: `dangerous` while the board is still being brought up,
pinned to `edge`, resolved from a brand store.

```json
{
  "type": "model",
  "series": "16",
  "authority-id": "mybrand",
  "brand-id": "mybrand",
  "model": "my-core26-arm64",
  "architecture": "arm64",
  "base": "core26",
  "grade": "dangerous",
  "store": "my-brand-store-id",
  "snaps": [
    {"name": "my-gadget",  "id": "EE5h9IMeDSe1ZAMow1R4Ndnc3zbm75db", "type": "gadget", "default-channel": "26/edge"},
    {"name": "my-kernel",  "id": "MVMLcWCUw9e6mFDnb70IFqsWCmOvPpWu", "type": "kernel", "default-channel": "26/edge"},
    {"name": "core26",     "id": "cUqM61hRuZAJYmIS898Ux66VY61gBbZf", "type": "base",   "default-channel": "latest/edge"},
    {"name": "snapd",      "id": "PMrrV4ml8uWuEUDBT8dSGnKUYbevVhc4", "type": "snapd",  "default-channel": "latest/edge"}
  ],
  "timestamp": "2026-10-07T00:00:00+00:00"
}
```

`dangerous` makes the ids optional, but keeping them costs nothing and means
the model does not silently change meaning when the grade is promoted to
`signed` for production.

### Classic hybrid 24.04

```json
{
  "type": "model",
  "series": "16",
  "authority-id": "mybrand",
  "brand-id": "mybrand",
  "model": "my-classic-24-amd64",
  "architecture": "amd64",
  "base": "core24",
  "classic": "true",
  "distribution": "ubuntu",
  "grade": "signed",
  "snaps": [
    {"name": "pc",        "id": "UqFziVZDHLSyO3TqSWgNBoAdHbLI4dAH", "type": "gadget", "default-channel": "classic-24.04/stable"},
    {"name": "pc-kernel", "id": "pYVQrBcKmBa0mZ4CCN7ExT6jH8rY1hza", "type": "kernel", "default-channel": "24/stable"},
    {"name": "core24",    "id": "dwTAh7MZZ01zyriOZErqd1JynQLiOGvM", "type": "base",   "default-channel": "latest/stable"},
    {"name": "snapd",     "id": "PMrrV4ml8uWuEUDBT8dSGnKUYbevVhc4", "type": "snapd",  "default-channel": "latest/stable"}
  ],
  "timestamp": "2026-10-07T00:00:00+00:00"
}
```

---

## 11. Signing and key workflow

```bash
# real key, kept with a passphrase, registered with the store
snap create-key mykey
snapcraft register-key mykey
snapcraft list-keys

# refresh the timestamp first - it records when the assertion was signed
python3 scripts/validate_model.py model.json --update-timestamp --online

# sign
snap sign -k mykey model.json > model.model
snap sign -k mykey --update-timestamp model.json > model.model   # same, at signing time
snap sign -k mykey --chain model.json > model-chain.model        # bundle account + account-key

# inspect what a device or image is actually running
snap model --assertion
snap known model
snap known --remote model series=16 brand-id=canonical model=ubuntu-core-24-amd64

# build
ubuntu-image snap -O output/ model.model
snap prepare-image --channel=stable model.model ./seed/
```

`WARNING: could not fetch account-key to cross-check signed assertion with key
constraints.` on signing is normal when the key is not registered or the
machine is offline — it does not affect the assertion.

---

## 12. Common pitfalls

1. **JSON types.** `"series": 16` and `"classic": true` are the two most
   common first-run failures. Everything is a string (§1).
2. **`architecture` is unvalidated.** `x86_64` / `aarch64` / `arm64v8` all sign
   and all fail at build time.
3. **snap-ids are unvalidated.** Copy-pasting a row from the wrong snap's
   `snap info` output is silent until the image boots the wrong kernel.
4. **Grade flip breaks models.** `dangerous` → `signed` makes every missing
   snap-id an error at once.
5. **Mixed formats.** Starting from a UC18 model and adding a `snaps` list
   leaves `gadget`/`kernel` behind, which snapd rejects.
6. **Editing a signed `.model`.** The signature covers the headers; any edit
   invalidates it. Convert back to JSON, edit, re-sign.
7. **Track drift.** A `core24` base with a `22/stable` kernel is legal and
   wrong. Pin the track that matches the base unless you deliberately want an
   hwe or vendor track.
8. **`snap known --remote` exits 0 with no output** when the model does not
   exist, which silently produces an empty file.
