---
name: matrix-to-site
description: Use when someone has a feature list, support matrix or scope tracking spreadsheet (CSV export with platform/milestone YES/NO/TBD style columns, remarks or pasted logs) that is hard to maintain and wants it turned into YAML in git with a browsable, editable web page on GitHub Pages, version snapshots, or a standalone HTML report for customers — or asks to deploy such a matrix table site to a repo or branch, even if they only say "make this CSV a page like our other project's matrix table" or "turn our feature list CSV into a web page and deploy it".
---

# Matrix to Site

## Overview

`assets/` holds a finished, tested site: static web UI (overview, matrix, search,
detail drawer, in-browser editing and batch status changes that commit through the
GitHub API, version tags, HTML/CSV export), `build.mjs` validator/builder and a
GitHub Pages workflow.
Your job is the part that differs per spreadsheet: **get the column mapping right,
prove the conversion is lossless, push, and hand over the GitHub settings steps.**
Do not write your own UI, converter or workflow — the bundled ones already handle
YAML formatting, lint-clean output, concurrent edits and versions.

Needs `python3` with PyYAML, `node` ≥ 18, `git`, and push access to the target repo
(applying the GitHub settings afterwards needs repo **admin**). An authenticated `gh`
is optional: it lets step 9 tailor the GitHub steps (read-only). Paths below are
relative to this skill's directory; `$REPO` is the target repo, `$B` the deploy branch.

## Steps

1. **Collect inputs**:
   - **CSV path**. UTF-8 is best; Big5/CP950 and CP1252 exports are detected
     automatically (step 2 shows which encoding was used).
   - **Target repo** (`$REPO`), a local clone of a GitHub repo. If the user only has
     a GitHub URL, ask whether you may clone it and where, then `git clone` it.
   - **Project name** and its **Jira project key(s)** — ask in one question
     (e.g. "Project name and Jira key(s)? e.g. `Falcon` / `FALCON`"); a project may
     have several keys. The page title is always `<PROJECT NAME> Matrix table` —
     project name in upper case whatever the user typed (`falcon` → `FALCON`).
   - **Jira site** for linking those keys: use `$MATRIX_TO_SITE_JIRA_URL` if it is set
     (e.g. `https://<site>.atlassian.net`); otherwise ask for it in the same question.
     If the project has no Jira, leave `jira_url` out and keys stay plain text.
   - **Deploy branch** (`$B`), optional. It must never be `main`, `master` or the
     repo's default branch. If the user gives none — or asks for one of those —
     use `matrix-table-<project-slug>` (lowercase, hyphens) and say why; they can
     merge it later through a normal PR.
   - **GitHub repository** is derived, not asked: parse `owner/name` from
     `git -C $REPO remote get-url origin` (`git@github.com:owner/name.git` or
     `https://github.com/owner/name`). Only if origin is not on GitHub, ask for it,
     explaining it is the `owner/name` part of the repo's GitHub URL, which the web
     editor needs to commit changes.
   If you cannot ask, pick sensible values (e.g. the Jira keys that appear in the CSV
   notes) and report them.
2. **Draft the mapping** in a fresh scratch directory (`WORK=$(mktemp -d)`; note the
   path, shell variables may not survive between your commands):
   `python3 scripts/inspect_csv.py <csv> > $WORK/mapping.yaml`
   (column profile on stderr). If it reports `NOT UTF-8`, check the names in the
   profile are readable; if they are garbled, ask the user to re-export as UTF-8 or
   re-run with `--encoding <name>`. Edit every `TODO`/guess using
   [references/mapping.md](references/mapping.md). Set `title`, `jira_url`, `jira_projects`,
   `repository.name` and `repository.branch: $B`.
3. **Confirm the mapping with the user** before converting — show it as a short
   table: platforms, each status column (CSV header → platform · milestone), status
   value meanings, note markers → platform, where text before the first marker goes,
   where notes with **no marker** go (`general` or one platform — this differs per
   project, so always ask), columns dropped. Skip only if the user
   said not to ask; then list these as decisions in the report.
4. **Branch**: `$REPO` must be clean. Create `$B` from the up-to-date default branch
   (or check it out if it exists).
5. **Install**: `python3 scripts/scaffold.py $REPO --deploy-branch $B --mapping $WORK/mapping.yaml`
   It refuses `main`, `master` and the default branch; if it warns that the default
   branch could not be determined, confirm with the user that `$B` is not it.
   If it reports **already installed**, stop and ask the user which they want — never
   pick for them:
   - **Update the site code only**: re-run with `--force` (keeps `data/`) and skip step 6.
   - **Re-import the CSV**: replaces all of `data/`, losing edits made on the web since
     the last import. Suggest creating a version first so the old data stays viewable,
     then re-run with `--force` and continue with step 6.
6. **Convert**: `python3 scripts/convert_csv.py --mapping $WORK/mapping.yaml --csv <csv> --out $REPO/matrix-table/data`
   It must exit 0. A `MISMATCH`, "status values not in mapping" or "no features found"
   means the mapping is wrong — fix it and re-run; never edit the generated YAML to
   make numbers fit.
7. **Validate**: in `$REPO`, `node matrix-table/tools/build.mjs format`, then
   `node matrix-table/tools/build.mjs check` and
   `node matrix-table/tools/build.mjs build $WORK/preview`.
   Run the repo's own linters on the new files if it has any (e.g. `yamllint` with its `.yamllint`).
8. **Commit and push** one commit to `$B` only (`git push -u origin $B`). Never
   force-push, and never push to `main`, `master` or the default branch. If the push
   is rejected for permissions, tell the user rather than retrying another way.
9. **Check GitHub, read-only**: `python3 scripts/github_status.py <owner/name> $B`.
   It only reads (Pages enabled? deploy rules? which branch the live site comes
   from) and lists the manual steps still needed. A repo has **one** Pages site: if it
   warns that the live site comes from another branch, put that warning at the top
   of the report, because deploying `$B` replaces that site.
10. **Report** using the template below, with only the still-needed steps from
   [references/github-setup.md](references/github-setup.md) filled in (all steps if
   the check could not run). **Do not change repository settings yourself** (no
   write `gh api` calls for Pages or environments) — the user applies them.

## Mapping pitfalls

| Trap | Do instead |
|------|-----------|
| Empty column whose header names a milestone (e.g. "GA2 Scope") | Keep it as a status column; it shows as "not set" |
| Rare `[build]`-style markers from pasted logs | Leave them out of `notes_markers` |
| Text before the first `[Platform]` marker | Set `notes_head_platform` to the platform it describes, else it goes to `general` |
| Notes with no marker at all | Ask the user in step 3: keep them `general`, or set `notes_default_platform` to the platform they belong to |
| Status words like `Pending`, `N/A`, `Partial` | Map every one explicitly; YES/NO = resolved, anything still open = `tbd` |
| Two header rows (group + device) | `header_rows: 2`; use the device row for `platforms[].hardware` |

## Report template

```
## <PROJECT NAME> Matrix table pushed to <owner/repo>@<branch>
- Commit <sha> pushed to origin/<branch> (main / default branch untouched)
- <N> components, <M> features, <S> sections from <csv>; Jira key(s) <KEY, ...>

| Status column | YES | NO | TBD | CSV matches |
...

### Decisions to confirm
- <mapping choices you made: markers, dropped columns, notes defaults ...>

### What you need to do on GitHub
<warning from github_status.py, if any>
<only the steps still needed, from references/github-setup.md, with OWNER/REPO/BRANCH filled in>
```

The site is not live until the user finishes those steps; say so rather than
claiming it is deployed.
