#!/usr/bin/env python3
"""Turn collected Jira data into the weekly progress report.

Input is a JSON file the agent assembles from three read-only Jira queries per
project, every issue flattened to the same record:

{
  "site": "https://example.atlassian.net",
  "start": "2026-11-06 18:00", "end": "2026-11-11 10:35", "timezone": "Asia/Taipei",
  "me": "<accountId>",
  "projects": [
    {"key": "DEMO",
     "touched":  [<issue>, ...],   # updatedBy(me) in the range
     "epics":    [<issue>, ...],   # project Epics open, or closed in the range
     "children": [<issue>, ...]}   # parent in (those Epics)
  ]
}

<issue> = {"key": "DEMO-12", "summary": "...", "status": "Triaged", "category": "To Do",
           "type": "Task", "parent": "DEMO-20" | null, "assignee": "<accountId>" | null}
children rows only need {"key", "status", "parent"}.

The script decides which touched issues are report cards and which Epics are
reported. "category" (Jira status category name) only places statuses missing
from WORKFLOW.

  build_report.py range --tz Asia/Taipei
      -> {"start": "...", "end": "...", "timezone": "..."}
  build_report.py render data.json --html weekly-report-2026-11-11.html --copy
      -> plain-text report on stdout, HTML file written, HTML on the clipboard
"""
import argparse
import datetime
import html
import json
import os
import shutil
import subprocess
import sys

WORKFLOW = ["Untriaged", "Triaged", "In Progress", "In Review", "To Be Deployed", "Merged", "Done", "Rejected"]
CATEGORY_SLOT = {"To Do": 1.5, "In Progress": 3.5, "Done": 7.5}
CLOSED = {"Done", "Rejected"}
IGNORED = {"To Be Deployed", "Merged"}
CARD_TYPES = {"Spike", "Task", "Bug", "Story", "Sub-task", "Subtask"}


def _unique(issues):
    seen = {}
    for i in issues:
        seen.setdefault(i["key"], i)
    return list(seen.values())


def _brief(issue):
    return {f: issue.get(f) for f in ("key", "summary", "status", "category")}


def resolve(report):
    """Pick report cards and reported Epics out of the raw per-project rows.

    Cards: touched issues of a work-item type. Epics (from the projects' Epic
    lists only): assigned to me, touched themselves, or the parent / parent's
    parent of a card.
    """
    me = report.get("me")
    projects = report["projects"]
    epic_home = {}
    for n, p in enumerate(projects):
        for e in _unique(p.get("epics", [])):
            if e.get("type") == "Epic":
                epic_home.setdefault(e["key"], (n, e))
    known = {}
    for p in projects:
        for i in p.get("touched", []) + p.get("children", []):
            known.setdefault(i["key"], i)

    wanted = {k for k, (_, e) in epic_home.items() if me and e.get("assignee") == me}
    cards = []
    for p in projects:
        mine = []
        for i in _unique(p.get("touched", [])):
            if i.get("type") == "Epic":
                if i["key"] in epic_home:
                    wanted.add(i["key"])
                continue
            if i.get("type") not in CARD_TYPES:
                continue
            mine.append(_brief(i))
            parent = i.get("parent")
            grandparent = known.get(parent, {}).get("parent")
            if parent in epic_home:
                wanted.add(parent)
            elif grandparent in epic_home:
                wanted.add(grandparent)
        cards.append(mine)

    children = {}
    for c in _unique([c for p in projects for c in p.get("children", [])]):
        children.setdefault(c.get("parent"), []).append({"key": c["key"], "status": c["status"]})

    out = []
    for n, p in enumerate(projects):
        epics = [dict(_brief(e), children=children.get(k, []))
                 for k, (home, e) in epic_home.items() if home == n and k in wanted]
        out.append({"key": p["key"], "cards": cards[n], "epics": epics})
    return {**{k: report[k] for k in ("site", "start", "end", "timezone")}, "projects": out}


def default_range(now):
    """Previous Friday 18:00 (a Friday run goes back a full week) up to now."""
    back = (now.weekday() - 4) % 7 or 7
    start = (now - datetime.timedelta(days=back)).replace(hour=18, minute=0)
    return start.strftime("%Y-%m-%d %H:%M"), now.strftime("%Y-%m-%d %H:%M")


def status_rank(name, category=None):
    if name in WORKFLOW:
        return float(WORKFLOW.index(name))
    return CATEGORY_SLOT.get(category, 8.0)


def key_sort(key):
    prefix, _, num = key.rpartition("-")
    return (prefix, int(num) if num.isdigit() else 0)


def progress(epic):
    children = epic.get("children", [])
    return sum(1 for c in children if c["status"] in CLOSED), len(children)


def fingerprint(report):
    """Same value as the JS in SKILL.md: JSON.stringify, then a rolling hash over code points."""
    h = 0
    for ch in json.dumps(report, ensure_ascii=False, separators=(",", ":")):
        h = (h * 131 + ord(ch)) % 2147483647
    return h


def summary(report):
    counts = "; ".join(
        "{} touched={} epics={} children={}".format(
            p["key"], len(p.get("touched", [])), len(p.get("epics", [])), len(p.get("children", [])))
        for p in report["projects"])
    return f"{counts} | fp={fingerprint(report)}"


def epic_alerts(epic):
    status = epic["status"]
    if status in CLOSED:
        return []
    children = epic.get("children", [])
    if not children:
        return [{"kind": "empty", "epic": epic}]
    rank = status_rank(status, epic.get("category"))
    in_progress = sorted((c["key"] for c in children if c["status"] == "In Progress"), key=key_sort)
    if in_progress and rank < status_rank("In Progress"):
        return [{"kind": "to_in_progress", "epic": epic, "children": in_progress}]
    remaining = [c for c in children if c["status"] not in CLOSED | IGNORED]
    if remaining and all(c["status"] == "In Review" for c in remaining) and rank < status_rank("In Review"):
        return [{"kind": "to_in_review", "epic": epic}]
    if all(c["status"] in CLOSED for c in children):
        return [{"kind": "closable", "epic": epic}]
    return []


def node(text="", url=None, suffix="", children=None):
    return {"text": text, "url": url, "suffix": suffix, "children": children or []}


def _title(item):
    return f" — {item['summary']}" if item.get("summary") else ""


def group_by_status(items, site, with_progress):
    groups = {}
    for it in items:
        groups.setdefault((it["status"], it.get("category")), []).append(it)
    out = []
    for (status, category) in sorted(groups, key=lambda sc: (status_rank(*sc), sc[0])):
        leaves = []
        for it in sorted(groups[(status, category)], key=lambda i: key_sort(i["key"])):
            suffix = _title(it) + (" ({}/{})".format(*progress(it)) if with_progress else "")
            leaves.append(node(url=f"{site}/browse/{it['key']}", suffix=suffix))
        out.append(node(status, children=leaves))
    return out


def alert_line(alert, site):
    e = alert["epic"]
    link = f"{site}/browse/{e['key']}"
    lead = _title(e) + "："
    if alert["kind"] == "empty":
        return node(url=link, suffix=lead + "Epic 已開啟，但底下沒有任何卡片")
    if alert["kind"] == "to_in_progress":
        kids = "、".join(alert["children"])
        return node(url=link, suffix=lead + f"子卡已有 In Progress（{kids}），Epic 仍為 {e['status']}，應切 In Progress")
    if alert["kind"] == "to_in_review":
        return node(url=link, suffix=lead + f"子卡皆已 In Review，Epic 仍為 {e['status']}，應切 In Review")
    return node(url=link, suffix=lead + f"子卡已全部 Done/Rejected，Epic 仍為 {e['status']}，應可關閉")


def build(report):
    site = report["site"].rstrip("/")
    detail, epics, warnings, reminders = [], [], [], []
    for p in report["projects"]:
        cards = group_by_status(p.get("cards", []), site, False)
        detail.append(node(p["key"], children=cards or [node("無")]))
        ep = group_by_status(p.get("epics", []), site, True)
        epics.append(node(p["key"], children=ep or [node("無")]))
        for e in sorted(p.get("epics", []), key=lambda e: key_sort(e["key"])):
            for a in epic_alerts(e):
                (warnings if a["kind"] == "empty" else reminders).append(alert_line(a, site))
    title = f"週進度報告：{report['start']} – {report['end']} ({report['timezone']})"
    return title, [
        ("細節進度", detail),
        ("專案進度（已完成/總數）", epics),
        ("警告", warnings or [node("無")]),
        ("提醒", reminders or [node("無")]),
    ]


def _plain(n):
    return (n["url"] or n["text"]) + n["suffix"]


def render_text(report):
    title, sections = build(report)
    lines = [title]

    def walk(nodes, depth):
        for n in nodes:
            lines.append("  " * depth + "- " + _plain(n))
            walk(n["children"], depth + 1)

    for heading, nodes in sections:
        lines += ["", heading]
        walk(nodes, 0)
    return "\n".join(lines) + "\n"


def render_html(report):
    title, sections = build(report)
    esc = html.escape

    def item(n):
        body = f'<a href="{esc(n["url"])}">{esc(n["url"])}</a>' if n["url"] else esc(n["text"])
        body += esc(n["suffix"])
        if n["children"]:
            body += "<ul>" + "".join(item(c) for c in n["children"]) + "</ul>"
        return f"<li>{body}</li>"

    parts = [f"<p>{esc(title)}</p>"]
    for heading, nodes in sections:
        parts.append(f"<p>{esc(heading)}</p><ul>" + "".join(item(n) for n in nodes) + "</ul>")
    return '<html><head><meta charset="utf-8"></head><body>' + "".join(parts) + "</body></html>\n"


def copy_html(doc):
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
        cmd = ["wl-copy", "--type", "text/html"]
    elif os.environ.get("DISPLAY") and shutil.which("xclip"):
        cmd = ["xclip", "-selection", "clipboard", "-t", "text/html"]
    else:
        return "no clipboard tool (wl-copy or xclip) found; open the HTML file in a browser and copy from there"
    subprocess.run(cmd, input=doc.encode(), check=True)
    return f"HTML copied to clipboard with {cmd[0]}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    rg = sub.add_parser("range", help="print the default range: previous Friday 18:00 to now")
    rg.add_argument("--tz", required=True, help="IANA time zone of the user's Jira profile")
    rd = sub.add_parser("render", help="print the text report and write the HTML version")
    rd.add_argument("input", help="collected Jira data (JSON)")
    rd.add_argument("--html", required=True, help="where to write the HTML report")
    rd.add_argument("--copy", action="store_true", help="put the HTML on the clipboard")
    args = ap.parse_args()

    if args.cmd == "range":
        from zoneinfo import ZoneInfo
        start, end = default_range(datetime.datetime.now(ZoneInfo(args.tz)))
        print(json.dumps({"start": start, "end": end, "timezone": args.tz}))
        return

    with open(args.input, encoding="utf-8") as f:
        report = json.load(f)
    resolved = resolve(report)
    doc = render_html(resolved)
    with open(args.html, "w", encoding="utf-8") as f:
        f.write(doc)
    sys.stdout.write(render_text(resolved))
    print(f"[data: {summary(report)}]", file=sys.stderr)
    print(f"[HTML written to {os.path.abspath(args.html)}]", file=sys.stderr)
    if args.copy:
        print(f"[{copy_html(doc)}]", file=sys.stderr)


if __name__ == "__main__":
    main()
