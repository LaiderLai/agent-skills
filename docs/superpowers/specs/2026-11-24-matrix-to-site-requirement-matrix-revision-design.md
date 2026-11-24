# matrix-to-site: requirement matrix — revised definitions

Revises `2026-11-23-matrix-to-site-requirement-matrix-design.md` (the base design).
Everything in the base design still holds unless this document changes it. Nothing of
the requirement template has been merged or published yet, so the old definitions are
replaced, not kept alongside.

## Why

The first trial on a real requirement sheet showed the requirement template modelled the
sheet's groups wrongly. The user's view of the sheet:

- **Requirements** (Source, Req ID, Category, Feature, Description, Project Scope)
  decide whether the rest of the row matters at all.
- **Discovery** (the sheet's "Risk assessment" group: Discovery check, Risk, Notes) is
  its own phase, unrelated to the first release phase.
- **Project execution** is the Jira ID plus the target platform's three release phases,
  EA, FC and GA. Its status says whether the requirement is done.
- Two dashboards matter: how much is done per phase, and how much of the risky work is
  done.

## Goals

- Project scope has priority over everything else: an Out-of-Scope requirement is
  listed but otherwise ignored.
- Project execution statuses are only Supported, Enabled, Not supported; Supported and
  Enabled count as done.
- Converting a template sheet needs no phase questions: x01 / x02 / future MS become
  EA / FC / GA on one platform automatically.
- A risk dashboard: risky requirements done ÷ risky requirements.

## Non-goals

- Keeping the old definitions as an option (nobody uses them).
- A second platform. Platform #2 columns of the template are ignored.
- Splitting notes by `[x01]`-style markers.
- Any change for feature matrices.

## Anti-goals

- Out-of-Scope requirements showing up in any count, percentage or warning.
- Feature-matrix output changing in any way (golden files and DOM goldens stay
  byte-identical; existing `--update` is never run).
- Silently losing data the user typed in the web editor when they toggle Scope.

## Approaches

- **A. Change the requirement template in place (chosen).** The branch is unmerged, so
  data model, converter, inspector, UI, fixtures and tests switch to the new definitions.
  A trial site already converted with the old ones is re-converted afterwards (push only
  with the user's consent).
- B. Old and new definitions side by side, chosen by a setting — extra code and tests for
  definitions nobody needs.
- C. Configuration only — status words and scope values could be config, but "ignore
  Out-of-Scope everywhere", whole notes to Discovery and the new risk dashboard need code.

## Decided with the user (2026-11-24)

1. **Scope has priority.** Project Scope values: **In Scope, Out-of-Scope, TBD**. Only
   **Out-of-Scope** items are ignored: they stay listed (dimmed, labelled "Out of
   scope") with only the Requirements group shown — ID, name, description, Source,
   Scope. Their Discovery, Risk, notes, project-execution statuses, Jira IDs, Test and
   test plan are not imported, not shown and not counted. In Scope and TBD items are
   handled the same way.
2. **Project-execution statuses:** Supported, Enabled, Not supported; empty = not set.
   No TBD, no Out-of-Scope status, no "resolved" wording. **Done = Supported or
   Enabled.**
3. **Project execution = Jira ID + phases EA, FC, GA** of one target platform. The
   inspector maps the template's Platform #1 `x01 → EA`, `x02 → FC`, `future MS → GA`
   without asking; Platform #2 columns are dropped. The platform name is still asked.
4. **Discovery** = Discovery check, Risk and the whole Notes cell. Notes are not split by
   markers; the entire cell goes to the `discovery` note section. EA, FC, GA and QA keep
   their own (initially empty) note sections for the web editor and batch notes.
5. **Risk dashboard.** Denominator: items that are not Out-of-Scope and whose Risk is
   **not None** — Critical, any other value, and empty (not assessed) all count.
   Numerator: those of them whose status in the **focused phase** is Supported or
   Enabled.

## Data model (changes to the base design)

```yaml
template: requirement-matrix
exclude_when: {field: scope, equals: out-of-scope}   # NEW: item is listed, otherwise ignored
status_sets:
  execution:
    - {id: supported,     label: Supported,     resolved: true,  tone: yes,  title: Works with the standard image}
    - {id: enabled,       label: Enabled,       resolved: true,  tone: info, title: Works after project enablement (custom driver, kernel component or workaround)}
    - {id: not-supported, label: Not supported, resolved: false, tone: no,   title: In scope but cannot be supported}
fields:
  - {id: scope, name: Scope, type: enum, show: table, filter: true,
     values: [{id: in-scope, label: In Scope}, {id: out-of-scope, label: Out-of-Scope, tone: neutral}, {id: tbd, label: TBD, tone: open}]}
  - {id: risk, name: Risk, type: enum, show: table, filter: true, block: discovery,
     values: [{id: none, label: None}, {id: critical, label: Critical, tone: no}]}
  - {id: source, name: Source, type: text, show: detail}
  - {id: discovery_check, name: Discovery check, type: text, show: detail, block: discovery}
  - {id: jira, name: Jira ID, type: list, show: detail, link: jira, block: execution}
  - ... test-plan fields unchanged (block: test-plan)
note_keys: [{id: discovery, name: Discovery}, {id: ea, name: EA}, {id: fc, name: FC}, {id: ga, name: GA}, {id: qa, name: QA}]
platforms: [{id: <slug>, name: <asked>}]
columns:
  - {id: ea, name: EA, platform: <slug>, status_set: execution, note_key: ea}
  - {id: fc, name: FC, platform: <slug>, status_set: execution, note_key: fc}
  - {id: ga, name: GA, platform: <slug>, status_set: execution, note_key: ga}
  - {id: test, name: Test, group: Test plan, role: test, note_key: qa}
```

- **`exclude_when`** replaces the Test column's `applies_when`. An excluded item keeps
  `id, name, comment, fields.source, fields.scope`; any other status, field or note on it
  is ignored by every count, card, filter chip count, consistency check and batch, and is
  hidden in table and drawer. `validateMeta` checks it names an enum field and one of its
  values; it is rejected for feature matrices like the other requirement keys.
- **`resolved`** stays the internal key that drives "done"; for requirement matrices
  the UI says **done / complete**, never "resolved". `not-supported` is not done.
- **`bugs` → `jira`** ("Jira ID"), grouped with project execution.
- **`block`** groups detail fields in the drawer: `discovery`, `execution`, `test-plan`.
- The scope/status consistency warning is removed (there is no Out-of-Scope status any
  more).

## Converter and inspector (changes)

- Columns 0–5 are read for every row. For a row whose scope maps to `out-of-scope`,
  columns 6 onward are not read; verify reports `out-of-scope: N items, their other
  columns ignored`.
- Notes: the whole cell → `discovery`. No marker splitting for requirement matrices.
- Status raw values: `Supported`, `Enabled`, `Not supported` (case-insensitive). Any
  other non-empty value on a non-excluded row (e.g. `TBD`, `Out-of-Scope`) is an
  unknown value and fails the conversion as today.
- Scope raw values: `In Scope`, `Out-of-Scope`, `TBD`; empty scope = not set, not
  excluded.
- Test column default: `tbd` for every non-excluded item.
- Jira ID column: tokens matching `[A-Z][A-Z0-9]+-\d+` kept, others dropped and counted
  (unchanged rule).
- `inspect_csv.py` drafts the three phase columns from Platform #1 by header
  (`x01`/`x02`/`future MS`) as EA/FC/GA, drops Platform #2, and leaves only the platform
  name marked `# CONFIRM`.

## UI (changes)

- **Phase donuts** (EA, FC, GA): Supported, Enabled, Not supported, not set; centre
  shows **% done** = (Supported + Enabled) ÷ non-excluded items. Overview stat cards for
  the focused phase: Done %, Supported, Enabled, Not supported, Not set.
- **Risk card:** `<done> / <risky>` and % for the focused phase, where risky = not
  excluded and risk ≠ none (including empty). It links to a search listing exactly the
  risky items.
- **Test coverage card:** YES ÷ non-excluded items (In Scope + TBD).
- **Table:** excluded rows dimmed, showing ID, name, Scope and "Out of scope" across the
  other cells; no checkbox for batch on them.
- **Drawer:** blocks Requirements (description, Source, Scope), Discovery (Discovery
  check, Risk, Discovery notes), Project execution (EA/FC/GA pills with their notes,
  Jira ID), Test plan, QA notes. Excluded items show only the Requirements block.
- **Editing:** changing Scope to Out-of-Scope hides the other fields but **does not
  delete** them, so switching back restores them; a hint says they are ignored while
  Out-of-Scope. (Replaces "clears Test on save".)

## SKILL.md / docs (changes)

Step 3 requirement variant: no phase-marker question; show the automatic EA/FC/GA
mapping, ask the platform name, show scope values (In Scope / Out-of-Scope / TBD) and
that Out-of-Scope rows keep only their Requirements columns. Report template: statuses
Supported / Enabled / Not supported with done %, risk done/total, test coverage.
README and `references/mapping.md` follow the new model.

## Tests (changes)

- Feature goldens and DOM goldens unchanged and passing.
- Requirement fixture updated: a TBD-scope row, an Out-of-Scope row carrying a status,
  a risk and notes (all ignored), a row with empty risk, statuses only Supported /
  Enabled / Not supported, Notes with `[x01]` text that must stay in Discovery.
- Unit tests for exclusion, done %, risk dashboard numbers, coverage denominator.
- Browser tests for the new cards, dimmed excluded rows, drawer blocks, scope toggle
  keeping hidden data.

## Left to the builder

Exact card layout and colours, the URL form of the risky-items search link, wording of
the "ignored while Out-of-Scope" hint.

## Clarifications (builder check, 2026-11-24)

Answered from the conversation or the base design:

- **Excluded items that carry data** (typed in the editor, then Scope switched to
  Out-of-Scope): `check` accepts it. Values are still type-checked (status ids in the
  column's set, enum ids, list/text types) so the YAML stays valid, but their presence
  is never an error, including a `test` value. The base design's "value where
  `applies_when` does not hold is an error" rule goes away with `applies_when`.
- **Not excluded** means scope is In Scope, TBD **or empty**. Every "non-excluded"
  denominator above (phase % done, risk dashboard, test coverage) includes empty-scope
  items.
- **Columns are located by header name**, as in the base design. "Columns 0–5" above
  means the Requirements group (Source, Req ID, Category, Feature, Description, Project
  Scope); for an excluded row only those mapped fields are read.
- **Re-converting the trial site** made with the old definitions is a separate step after this work,
  done by a clean agent following SKILL.md and pushed only with the user's consent. It is
  not part of the implementation plan.

Controller's calls (minor, a sensible builder could settle them; listed for review):

- **Focus** keeps the base rule (default = last phase column with data, never Test;
  clicking a donut changes it). The stat cards and the risk card follow the focused
  phase. The risky-items link lists the same items whatever the phase; the phase only
  changes which status counts as done.
- **"Not none" filter:** the risk filter gains a value meaning "risky" (not None,
  including empty), used by the risk card link and offered as one extra Risk chip.
- **Open vs done:** for requirement matrices the sidebar's open-items link and badges
  count **not done** (Not supported + not set) on the focused phase and are labelled
  "Not done". Not set counts as not done everywhere.
- **CSV export:** excluded rows export their Requirements columns only; other cells are
  empty.
