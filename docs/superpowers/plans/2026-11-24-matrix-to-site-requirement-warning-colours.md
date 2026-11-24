# matrix-to-site requirement warning colours Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Warning colours on the requirement overview for Not supported, Risk and Test coverage.

**Architecture:** Pure level helpers in `assets/web/template.js`; `requirementCards` and the requirement stat cards in `assets/web/app.js` add a level class; CSS in `assets/web/style.css`.

**Tech Stack:** Node ES modules (`node --test`), vanilla JS app, headless Chrome browser tests.

**Spec:** `docs/superpowers/specs/2026-11-24-matrix-to-site-requirement-warning-colours-design.md`.

## Global Constraints

- Work in `matrix-to-site/` and `docs/`; commit locally; **never push**.
- Feature output byte-identical: feature goldens pass; never run `--update`.
- No company/customer/project names or personal paths in committed files; `~/Downloads` must not gain files.
- Full suite from `matrix-to-site/`: `timeout 900 python3 -m unittest discover -s tests` → `OK`.
- Levels exactly: coverage `pct` 0–49 `red`, 50–79 `orange`, 80–99 `yellow`, 100 `green`, total 0 → none; risk 0% `red`, 1–99% `orange`, 100% `green`, total 0 → `green`; Not supported count > 0 → `red`. Warning labels start with `⚠ ` for red/orange/yellow.

## Review Focus

1. Boundaries 49/50, 79/80, 99/100 for coverage, and 0/1, 99/100 for risk — Task 1.
2. Switching the focused phase recolours the Risk and Not supported cards — Task 1.
3. No warning class or "⚠" appears on a feature-matrix page — Task 1.

---

### Task 1: Level helpers, cards, CSS, docs

**Files:** Modify `matrix-to-site/assets/web/template.js`, `matrix-to-site/assets/web/app.js`, `matrix-to-site/assets/web/style.css`, `matrix-to-site/SKILL.md`, `matrix-to-site/assets/README.md`. Test: `matrix-to-site/tests/template.test.mjs`, `matrix-to-site/tests/browser/requirement.e2e.mjs`.

**Interfaces:** `coverageLevel(cov) -> "red"|"orange"|"yellow"|"green"|null` (from `coverage()` result), `riskLevel(rd) -> "red"|"orange"|"green"` (from `riskDone()` result), `notSupportedLevel(n) -> "red"|null`. Cards get class `level-<level>`.

- [ ] **Step 1: Failing tests.** Node: coverageLevel for pct 0, 49 → red; 50, 79 → orange; 80, 99 → yellow; 100 → green; total 0 → null. riskLevel for done/total 0/3 → red, 1/3 and 2/3 → orange, 3/3 → green, 0/0 → green. notSupportedLevel 0 → null, 1 → red. Browser (requirement fixture, default focus FC): Not supported card has no level (0 on FC); Risk card `level-red` with label starting `⚠`; coverage card `level-red` (0%); after clicking the EA donut: Not supported card `level-red` with `⚠` (1 on EA), Risk card `level-orange` (2/3). Feature suite unchanged; a requirement-only check that the feature pages contain no `level-` class is covered by the feature goldens.
- [ ] **Step 2: Run** `node --test tests/` and `node tests/browser/run.mjs requirement` → FAIL.
- [ ] **Step 3: Implement** (gate on `isReq()`); CSS for `.stat.level-red|orange|yellow|green` in light and dark mode.
- [ ] **Step 4: Run** node tests, both browser suites, full suite → PASS/OK.
- [ ] **Step 5: Docs.** SKILL.md report template risk line: "Risk: <done>/<risky> on <phase> (risky = not Out-of-Scope and Risk not None; empty Risk counts)"; one line that the overview flags Not supported > 0, risk < 100 % and coverage < 100 % in colour. README requirement section one line on the warning colours.
- [ ] **Step 6: Commit** `matrix-to-site: warning colours on the requirement overview`.
