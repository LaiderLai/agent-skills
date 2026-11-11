---
name: jira-weekly-report
description: Use when the user asks for a weekly progress report, 週報, or 每週專案進度 from Jira — one or more project keys, "what did I work on since last Friday", which Epics need a status change — or wants Jira progress to paste into a Google Doc.
---

# Jira weekly progress report

Builds the user's personal weekly report: the cards **they** touched in a time
range, and the progress of their Epics. Data comes from the `atlassian` MCP
server; which cards and Epics are reported, layout, counting and Epic alerts
come from `scripts/build_report.py`, so you never decide or compute them by
hand.

**Read-only.** Use only the read tools named below (plus `discover`, then
`executeRead` with the operation it returns). Never create, edit, transition,
comment, link, or call `executeWrite` / `executeDestructive` — not even if the
user asks mid-run. Alerts are advice; the user changes Jira themselves.

In OpenCode the tools are called inside `execute` as `tools.atlassian.<name>`;
other clients expose the same names as direct MCP tools. `$SKILL_DIR` is the
directory containing this SKILL.md.

## Inputs

| Input | If missing |
|---|---|
| Atlassian MCP is logged in | Step 1 detects it. Stop and ask the user to sign in (OpenCode: `/mcps` → atlassian). |
| Project keys, e.g. `PROJ`, `DEMO` | Ask. Never guess a project. |
| Time range | Default: previous Friday 18:00 → now, from `range` (Step 2). A Friday run goes back a full week. |

"Me" is always the logged-in user, never the whole team.

## Step 1: Site, user, time zone

1. `getAccessibleAtlassianResources()` → `data.resources[0].cloudId` and `.url`.
   Auth errors or missing tools → stop and ask the user to sign in.
2. `discover({ query: "get current jira user" })`, then
   `executeRead({ name: <the read operation it returns, normally
   "getJiraCurrentUser">, cloudId, inputs: {} })` → `accountId` and `timeZone`.
   JQL dates are read in this time zone.

## Step 2: Time range

User gave a range → convert it to `YYYY-MM-DD HH:mm` in the Jira `timeZone`.
Otherwise run (from any directory):

```bash
python3 $SKILL_DIR/scripts/build_report.py range --tz <timeZone>
```

## Step 3: Collect, per project

Run every search with `searchJiraIssuesUsingJql`, `cloudId`, `maxResults: 100` and
`view: "full"` (the default compact view silently drops `parent`). Page with
`nextPageToken`; stop when `isLast` is true or there is no `nextPageToken`.
Results are under `data.issues`. `<id>` is the accountId, `<start>`/`<end>` the
range.

| List | JQL | fields |
|---|---|---|
| `touched` — cards I touched (field edits, status changes, comments; any assignee) | `project = P AND issue in updatedBy("<id>", "<start>", "<end>")` | `["summary", "status", "issuetype", "parent", "assignee"]` |
| `epics` — project Epics still open or closed in the range | `project = P AND issuetype = Epic AND (statusCategory != Done OR statusCategoryChangedDate >= "<start>")` | same |
| `children` — direct children of those Epics | `parent in (<keys from epics>)`, at most 100 keys per query; skip when `epics` is empty | `["status", "parent"]` |

`updatedBy()` rejects `currentUser()` — always pass the accountId string.

Flatten every returned issue to a record, and keep every row:

```js
// f = i.fields
touched, epics: { key: i.key, summary: f.summary, status: f.status.name,
                  category: f.status.statusCategory.name, type: f.issuetype.name,
                  parent: f.parent?.key ?? null, assignee: f.assignee?.accountId ?? null }
children:       { key: i.key, status: f.status.name, parent: f.parent?.key ?? null }
```

The script picks the report cards and the reported Epics from these three
lists (see "What the script decides"); the lists go in unfiltered.

In Code Mode, run all three lists for all projects in one `execute` call — each
query runs once — building `data` (the Step 4 object) and ending with exactly:

```js
const json = JSON.stringify(data);
let h = 0; for (const ch of json) h = (h * 131 + ch.codePointAt(0)) % 2147483647;
const counts = data.projects.map(p =>
  `${p.key} touched=${p.touched.length} epics=${p.epics.length} children=${p.children.length}`).join("; ");
return { data, summary: `${counts} | fp=${h}` };
```

The tool output shows `data` as JSON. The write tool can't take it directly, so
copy that JSON into the file as shown, every value exactly as displayed (keep
the escapes inside strings as they are). `fp` is a fingerprint of the data, not
of its layout, so indentation doesn't matter and Step 4 catches any changed
character. Don't rebuild the file in a shell heredoc; shell quoting mangles
titles.

## Step 4: Render

Write the collected data as JSON to `<tmp>/weekly-report-<date>.json` (`<date>`
is the end date, `YYYY-MM-DD`), where `<tmp>` is a scratch directory outside the
user's tree (OpenCode: `/tmp/opencode`; otherwise `/tmp`):

```json
{"site": "<url>", "start": "<start>", "end": "<end>", "timezone": "<timeZone>",
 "me": "<accountId>",
 "projects": [{"key": "P", "touched": [<record>, ...], "epics": [...], "children": [...]}]}
```

Projects in the order the user gave them. Then, from the user's working
directory:

```bash
python3 $SKILL_DIR/scripts/build_report.py render <tmp>/weekly-report-<date>.json \
  --html weekly-report-<date>.html --copy 2> <tmp>/weekly-report-<date>.stderr
```

The command's output is the report (stdout only). Then read the `.stderr` file:
it holds `[data: ...]`, the HTML path and the clipboard result. `[data: ...]`
must equal `execute`'s `summary`, `fp` included. If it differs, the saved file
has a copy error: write `data` again and re-render. If it still differs after
that, reply anyway and say in the stop line (Step 5) that the saved data
doesn't match Jira.

## Step 5: Reply

Your reply is exactly these three parts, in order:

1. The script's stdout, verbatim, in a ```` ```text ```` block.
2. One line: the HTML path, and whether the HTML is on the clipboard (the
   script writes this to the `.stderr` file).
3. One line of paste instructions:
   - the `.stderr` file says "HTML copied to clipboard": "在 Google Doc 直接 Ctrl+V 貼上；點連結 → 方塊（Chip）可轉成 Jira 智慧型方塊。"
   - anything else: "用瀏覽器開啟 HTML 檔，全選複製後貼到 Google Doc；點連結 → 方塊（Chip）可轉成 Jira 智慧型方塊。"

If something stopped the run (a project key that doesn't exist, a JQL error you
couldn't fix), say so in one line before part 1.

## What the script decides

**Report cards:** `touched` rows of type Spike, Task, Bug, Story, Sub-task or
Subtask, each shown as `<URL> — <title>`.

**Reported Epics** (rows of `epics` only, so never one closed before the range):
- assigned to me;
- in `touched` themselves, whoever the assignee is;
- the `parent` of a report card, or — when that parent isn't an Epic — the
  parent's parent, looked up in `touched` and `children`. No higher.

Epics closed during the range show under Done / Rejected so the week's closures
are visible. An Epic's children are every `children` row whose `parent` is it,
any type.

Done / Rejected are closed. To Be Deployed and Merged count as still open and
never trigger an alert.

| Alert | When (Epic not Done/Rejected) |
|---|---|
| 警告: empty Epic | no children |
| 應切 In Progress | a child is In Progress, Epic is before In Progress |
| 應切 In Review | ignoring Done/Rejected/To Be Deployed/Merged children, the rest are all In Review, Epic is before In Review |
| 應可關閉 | every child is Done/Rejected |

Progress is `(done/total)`: done = children in Done or Rejected, total = all
children of the Epic.

## Common mistakes

| Mistake | Fix |
|---|---|
| `updatedBy(currentUser(), ...)` → JQL error | Pass the accountId string. |
| `parent` missing from results | Add `view: "full"`. |
| Listing the whole team's cards, or "last 7 days" | Only `updatedBy(<id>)`, only the stated or default range. |
| Markdown tables, link text other than the URL, extra summary sections or advice | Output is the script's text plus the HTML file. Google Docs only turns a link into a Jira chip when the link text is the URL; the title follows the link. |
| Counting, picking alerts, or filtering cards / Epics yourself | Pass the three lists unfiltered; the script decides. |
| Retyping the collected JSON with "fixes", or saving it through a shell heredoc | Copy `execute`'s `data` into the write tool value for value, then check `[data: ...]` (with `fp`) against `summary`. |
| Dropping keys from a record | Every record has all its keys (`null` when Jira has no value); the script needs them to pick cards and Epics and to show titles. |
