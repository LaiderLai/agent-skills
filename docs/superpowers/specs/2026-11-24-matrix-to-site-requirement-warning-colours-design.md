# matrix-to-site: requirement matrix warning colours

Small change on top of the requirement-matrix designs (2026-11-23/24).

## Why

On the overview of a requirement matrix, three numbers need attention when they are not
fine, and today they look the same as healthy numbers: requirements that are Not supported,
test coverage, and risky requirements not yet done.

## Decided with the user (2026-11-24)

Requirement matrices only; the overview follows the focused phase. Every warning adds a
"⚠" to the card's label so it does not rely on colour alone.

| Card | Rule | Level |
|---|---|---|
| Not supported (stat card of the focused phase) | count > 0 | red |
| Risk | done ÷ risky on the focused phase: 0% red, 1–99% orange, 100% green; no risky items → green | as listed |
| Test coverage | YES ÷ non-excluded: 0–49% red, 50–79% orange, 80–99% yellow, 100% green; no items → no level | as listed |

A level shows as a strong background tint, border and number colour (light and dark
mode). Feature matrices: no change (feature goldens unchanged).

SKILL.md report template: the risk line says risky = not Out-of-Scope and Risk not None
(empty counts), so a report matches the site (e.g. 3/7, not "4 Critical").

## Left to the builder

Exact colours, pure helper names, where the level helpers live (template.js preferred).
