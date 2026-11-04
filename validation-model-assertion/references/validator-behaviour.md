# Validator behaviour in detail

Supporting detail for SKILL.md Step 2. Read it when a report section needs
explaining or a run behaves unexpectedly.

## The store-lookup ledger

After the findings, the report lists every snap it looked up and the outcome:
`snap-id verified`, `NOT FOUND`, `local snapd`, `MISMATCH`. Snap components get their own rows
(`<snap>+<component>`: `component published` / `component NOT PUBLISHED`,
with the channel the image will use). A missing required component is a
warning, like an unpublished channel; a missing optional one is INFO, since
`ubuntu-image` leaves it out unless asked. Show the ledger to the user
verbatim. A brand-store gadget that was checked and matched produces no
finding, and neither does one that was never checked; only the ledger tells
them apart. Any snap without a verified id is something only the user can
vouch for. Offline runs print the ledger too, saying nothing was checked.

## Brand stores

- The validator reads the model's `store` header automatically. `--store ID`
  is only for models without a `store` header whose snaps still live in a
  brand store (drafts, or models relying on device store assignment).
- Lookup order: public API with the brand store header, then the local snapd
  (`snap info --verbose`). A snap still unresolved is a **warning** — in a
  brand-store workflow "I cannot see it" is expected. Truly private snaps need
  credentials; say the check was skipped.
- The ledger separates snaps that needed the brand store from those that
  resolved identically without it. Usually only the gadget needs it; do not
  report "verified in <brand store>" for `core26`, `snapd` or a public kernel.
- A brand store can shadow a public snap of the same name. If the public
  namespace returns a different snap-id, the ledger says so; the model's
  declared id decides which one the device gets.

## Batch runs (directory or several paths)

- Identical findings merge into one line with "(all files)"; each confirm
  question is asked once for the set. Store lookups are cached.
- The store-lookup ledger is printed per file; files with identical lookups
  share one block. Each file also gets its own plain-English readback under
  "What each model actually says".
- **Shared device identity**: files with the same `series` + `brand-id` +
  `model` and the same `revision` (default 0) collide — a device keeps only
  the highest revision, and a remodel needs the revision to increase. This is
  a product decision: separate `model` names for coexisting products, or
  increasing `revision` values for a hardening progression. See
  `model-assertion-reference.md` §3.
- **Exception — stage × grade sets**: when every file sharing the identity is
  named `<grade>-<stage>.json` and no (grade, stage) pair repeats, the set is
  the reflash-only variant matrix. It is reported under "stage × grade
  matrix" as INFO and does not affect the exit code. Mixing in other file
  names, or repeating a pair, brings back the collision warning.
- `--update-timestamp` is refused for a batch.

## Signed sibling drift

If a `.assert` / `.model` file sits next to the JSON (single-file runs too),
the validator converts it back and compares. Drift means the JSON was edited
without re-signing. A match is reported as well — knowing the pair is in sync
is useful.

## Timestamps

Age is mentioned only past a year (INFO — models under version control are
expected to carry old timestamps). More than a day in the future is a WARN,
usually a clock problem or a hand-edited date. Neither is an error.

## `--sign-check` and the throwaway key

`--sign-check` pipes the JSON through `snap sign`, snapd's own assembler, so
an assembly success is the authoritative structural verdict. It never goes
online — pair it with `--online`.

`--create-key` reuses or creates `model-validation-throwaway` non-interactively
(`gpg --batch --quick-generate-key` in snapd's keyring). Without a key and
without `--create-key`, the check is skipped and says so. Tell the user the
key is unregistered, passphrase-less, trusted by no device, and unrelated to
their real signing key (`snap create-key` + `snapcraft register-key`, kept
with a passphrase).

Remove it afterwards — there is no `snap remove-key`:

```bash
snap keys
gpg --homedir ~/.snap/gnupg --list-secret-keys              # find the fingerprint
gpg --homedir ~/.snap/gnupg --batch --yes \
    --delete-secret-and-public-key <FINGERPRINT>
snap keys                                                   # verify it is gone
```

If `snap sign` with a real key hangs, it is waiting for a passphrase on a
terminal that does not exist. Hand the command to the user.

## Exit codes and ordering

Findings are ordered ERROR → WARN → CONFIRM → INFO. Exit code is 1 only when
there are errors; CONFIRM items never fail a script.
