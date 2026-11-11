import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(__file__)
SCRIPT = os.path.join(HERE, "..", "scripts", "build_report.py")
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import build_report as br  # noqa: E402

SITE = "https://example.atlassian.net"
ME = "acc-me"


def url(key):
    return f"{SITE}/browse/{key}"


def issue(key, status="Triaged", type="Task", parent=None, summary=None, assignee=None, category=None):
    return {"key": key, "summary": summary if summary is not None else f"title {key}", "status": status,
            "category": category, "type": type, "parent": parent, "assignee": assignee}


def epic(key, status, *child_statuses):
    """Resolved Epic, as consumed by the alert / progress / render code."""
    return {
        "key": key,
        "summary": f"title {key}",
        "status": status,
        "children": [{"key": f"{key}-c{i}", "status": s} for i, s in enumerate(child_statuses)],
    }


def resolved(cards=(), epics=(), project="DEMO"):
    return {
        "site": SITE,
        "start": "2026-11-06 18:00",
        "end": "2026-11-11 10:35",
        "timezone": "Asia/Taipei",
        "projects": [{"key": project, "cards": list(cards), "epics": list(epics)}],
    }


def raw(touched=(), epics=(), children=(), project="DEMO", extra_projects=()):
    return {
        "site": SITE,
        "start": "2026-11-06 18:00",
        "end": "2026-11-11 10:35",
        "timezone": "Asia/Taipei",
        "me": ME,
        "projects": [{"key": project, "touched": list(touched), "epics": list(epics), "children": list(children)}]
        + list(extra_projects),
    }


class Resolve(unittest.TestCase):
    def project(self, r, i=0):
        return br.resolve(r)["projects"][i]

    def card_keys(self, r, i=0):
        return [c["key"] for c in self.project(r, i)["cards"]]

    def epic_keys(self, r, i=0):
        return [e["key"] for e in self.project(r, i)["epics"]]

    def test_only_work_item_types_become_cards(self):
        r = raw(touched=[
            issue("DEMO-1", type="Task"), issue("DEMO-2", type="Bug"), issue("DEMO-3", type="Story"),
            issue("DEMO-4", type="Spike"), issue("DEMO-5", type="Sub-task"), issue("DEMO-6", type="Subtask"),
            issue("DEMO-7", type="Epic"), issue("DEMO-8", type="Initiative"),
        ])
        self.assertEqual(sorted(self.card_keys(r)), ["DEMO-1", "DEMO-2", "DEMO-3", "DEMO-4", "DEMO-5", "DEMO-6"])

    def test_card_keeps_summary_status_category(self):
        r = raw(touched=[issue("DEMO-1", status="Blocked", category="In Progress", summary="Fix it")])
        self.assertEqual(self.project(r)["cards"],
                         [{"key": "DEMO-1", "summary": "Fix it", "status": "Blocked", "category": "In Progress"}])

    def test_epic_assigned_to_me_is_included_even_if_untouched(self):
        r = raw(epics=[issue("DEMO-20", type="Epic", assignee=ME), issue("DEMO-21", type="Epic", assignee="other")])
        self.assertEqual(self.epic_keys(r), ["DEMO-20"])

    def test_parent_epic_of_a_card_is_included(self):
        r = raw(touched=[issue("DEMO-1", parent="DEMO-20")],
                epics=[issue("DEMO-20", type="Epic", assignee="other")])
        self.assertEqual(self.epic_keys(r), ["DEMO-20"])

    def test_subtask_grandparent_epic_resolved_through_children(self):
        r = raw(touched=[issue("DEMO-2", type="Sub-task", parent="DEMO-10")],
                epics=[issue("DEMO-20", type="Epic")],
                children=[issue("DEMO-10", type="Story", parent="DEMO-20")])
        self.assertEqual(self.epic_keys(r), ["DEMO-20"])

    def test_subtask_grandparent_epic_resolved_through_touched(self):
        r = raw(touched=[issue("DEMO-2", type="Sub-task", parent="DEMO-10"),
                         issue("DEMO-10", type="Story", parent="DEMO-20")],
                epics=[issue("DEMO-20", type="Epic")])
        self.assertEqual(self.epic_keys(r), ["DEMO-20"])

    def test_no_higher_than_two_levels(self):
        r = raw(touched=[issue("DEMO-3", type="Sub-task", parent="DEMO-2")],
                epics=[issue("DEMO-20", type="Epic")],
                children=[issue("DEMO-2", type="Sub-task", parent="DEMO-10"),
                          issue("DEMO-10", type="Story", parent="DEMO-20")])
        self.assertEqual(self.epic_keys(r), [])

    def test_touched_epic_is_included_regardless_of_assignee(self):
        r = raw(touched=[issue("DEMO-20", type="Epic", assignee="other")],
                epics=[issue("DEMO-20", type="Epic", assignee="other")])
        self.assertEqual(self.epic_keys(r), ["DEMO-20"])
        self.assertEqual(self.card_keys(r), [])

    def test_unrelated_epics_are_dropped(self):
        r = raw(touched=[issue("DEMO-1", parent="DEMO-20")],
                epics=[issue("DEMO-20", type="Epic"), issue("DEMO-30", type="Epic")])
        self.assertEqual(self.epic_keys(r), ["DEMO-20"])

    def test_parent_not_in_epic_list_is_ignored(self):
        # Epic closed before the range (filtered out by the JQL) or a non-Epic parent.
        r = raw(touched=[issue("DEMO-1", parent="DEMO-99")])
        self.assertEqual(self.epic_keys(r), [])

    def test_non_epic_rows_in_epic_list_are_ignored(self):
        r = raw(epics=[issue("DEMO-20", type="Story", assignee=ME)])
        self.assertEqual(self.epic_keys(r), [])

    def test_epic_children_are_direct_children_of_any_type(self):
        r = raw(epics=[issue("DEMO-20", type="Epic", assignee=ME, summary="Big thing")],
                children=[issue("DEMO-10", status="Done", type="Story", parent="DEMO-20"),
                          issue("DEMO-11", status="In Progress", type="Bug", parent="DEMO-20"),
                          issue("DEMO-12", type="Sub-task", parent="DEMO-10"),
                          issue("DEMO-13", type="Task", parent="DEMO-30")])
        e = self.project(r)["epics"][0]
        self.assertEqual(e["summary"], "Big thing")
        self.assertEqual(sorted((c["key"], c["status"]) for c in e["children"]),
                         [("DEMO-10", "Done"), ("DEMO-11", "In Progress")])

    def test_slim_children_rows_are_enough(self):
        r = raw(touched=[issue("DEMO-2", type="Sub-task", parent="DEMO-10")],
                epics=[issue("DEMO-20", type="Epic")],
                children=[{"key": "DEMO-10", "status": "Done", "parent": "DEMO-20"}])
        e = self.project(r)["epics"][0]
        self.assertEqual(e["children"], [{"key": "DEMO-10", "status": "Done"}])

    def test_duplicate_rows_count_once(self):
        r = raw(touched=[issue("DEMO-1", parent="DEMO-20"), issue("DEMO-1", parent="DEMO-20")],
                epics=[issue("DEMO-20", type="Epic"), issue("DEMO-20", type="Epic")],
                children=[issue("DEMO-1", parent="DEMO-20"), issue("DEMO-1", parent="DEMO-20")])
        p = self.project(r)
        self.assertEqual(len(p["cards"]), 1)
        self.assertEqual(len(p["epics"]), 1)
        self.assertEqual(len(p["epics"][0]["children"]), 1)

    def test_epic_in_another_listed_project_shows_under_its_own_project(self):
        other = {"key": "OTHER", "touched": [], "epics": [issue("OTHER-5", type="Epic")], "children": []}
        r = raw(touched=[issue("DEMO-1", parent="OTHER-5")], extra_projects=[other])
        self.assertEqual(self.epic_keys(r, 0), [])
        self.assertEqual(self.epic_keys(r, 1), ["OTHER-5"])

    def test_keeps_header_fields_and_project_order(self):
        r = raw(extra_projects=[{"key": "OTHER", "touched": [], "epics": [], "children": []}])
        out = br.resolve(r)
        self.assertEqual([p["key"] for p in out["projects"]], ["DEMO", "OTHER"])
        self.assertEqual((out["site"], out["start"], out["end"], out["timezone"]),
                         (SITE, "2026-11-06 18:00", "2026-11-11 10:35", "Asia/Taipei"))


class EpicAlerts(unittest.TestCase):
    def kinds(self, e):
        return [a["kind"] for a in br.epic_alerts(e)]

    def test_empty_open_epic_is_a_warning(self):
        self.assertEqual(self.kinds(epic("DEMO-1", "Untriaged")), ["empty"])

    def test_empty_closed_epic_is_silent(self):
        self.assertEqual(self.kinds(epic("DEMO-1", "Done")), [])
        self.assertEqual(self.kinds(epic("DEMO-1", "Rejected")), [])

    def test_child_in_progress_but_epic_behind(self):
        a = br.epic_alerts(epic("DEMO-1", "Untriaged", "In Progress", "Triaged"))
        self.assertEqual([x["kind"] for x in a], ["to_in_progress"])
        self.assertEqual(a[0]["children"], ["DEMO-1-c0"])

    def test_child_in_progress_epic_already_in_progress_or_later(self):
        for s in ("In Progress", "In Review"):
            self.assertEqual(self.kinds(epic("DEMO-1", s, "In Progress")), [])

    def test_all_children_in_review(self):
        self.assertEqual(self.kinds(epic("DEMO-1", "In Progress", "In Review", "In Review")), ["to_in_review"])

    def test_in_review_rule_ignores_deployed_merged_and_closed(self):
        e = epic("DEMO-1", "Triaged", "In Review", "To Be Deployed", "Merged", "Done", "Rejected")
        self.assertEqual(self.kinds(e), ["to_in_review"])

    def test_in_review_rule_needs_every_remaining_child_in_review(self):
        self.assertEqual(self.kinds(epic("DEMO-1", "Triaged", "In Review", "Triaged")), [])

    def test_in_review_rule_silent_when_epic_already_in_review(self):
        self.assertEqual(self.kinds(epic("DEMO-1", "In Review", "In Review")), [])

    def test_only_deployed_or_merged_children_trigger_nothing(self):
        self.assertEqual(self.kinds(epic("DEMO-1", "Triaged", "To Be Deployed", "Merged")), [])

    def test_all_children_closed_epic_open(self):
        self.assertEqual(self.kinds(epic("DEMO-1", "In Review", "Done", "Rejected")), ["closable"])

    def test_deployed_child_blocks_closable(self):
        self.assertEqual(self.kinds(epic("DEMO-1", "In Review", "Done", "To Be Deployed")), [])

    def test_closed_epic_never_alerts(self):
        self.assertEqual(self.kinds(epic("DEMO-1", "Done", "Done")), [])
        self.assertEqual(self.kinds(epic("DEMO-1", "Rejected", "In Progress")), [])


class Progress(unittest.TestCase):
    def test_counts_closed_over_total(self):
        e = epic("DEMO-1", "In Review", "Done", "Rejected", "To Be Deployed", "Merged", "Triaged")
        self.assertEqual(br.progress(e), (2, 5))

    def test_empty(self):
        self.assertEqual(br.progress(epic("DEMO-1", "Untriaged")), (0, 0))


class Ordering(unittest.TestCase):
    def test_keys_sort_numerically(self):
        keys = ["DEMO-100", "DEMO-9", "DEMO-27"]
        self.assertEqual(sorted(keys, key=br.key_sort), ["DEMO-9", "DEMO-27", "DEMO-100"])

    def test_known_statuses_follow_workflow(self):
        names = ["Rejected", "Done", "Merged", "To Be Deployed", "In Review", "In Progress", "Triaged", "Untriaged"]
        self.assertEqual(sorted(names, key=lambda n: br.status_rank(n)), list(reversed(names)))

    def test_unknown_status_placed_by_category(self):
        self.assertLess(br.status_rank("Blocked", "In Progress"), br.status_rank("To Be Deployed"))
        self.assertGreater(br.status_rank("Blocked", "In Progress"), br.status_rank("In Review"))
        self.assertLess(br.status_rank("Backlog", "To Do"), br.status_rank("In Progress"))
        self.assertGreater(br.status_rank("Won't Do", "Done"), br.status_rank("Rejected"))


class RenderText(unittest.TestCase):
    def setUp(self):
        self.r = resolved(
            cards=[
                {"key": "DEMO-12", "summary": "title DEMO-12", "status": "Triaged"},
                {"key": "DEMO-3", "summary": "title DEMO-3", "status": "Done"},
                {"key": "DEMO-10", "summary": "title DEMO-10", "status": "Triaged"},
            ],
            epics=[
                epic("DEMO-20", "Untriaged", "In Progress", "Triaged"),
                epic("DEMO-7", "Untriaged"),
                epic("DEMO-30", "In Review", "Done", "Done"),
            ],
        )
        self.text = br.render_text(self.r)

    def test_header_has_range(self):
        self.assertTrue(self.text.startswith("週進度報告：2026-11-06 18:00 – 2026-11-11 10:35 (Asia/Taipei)\n"))

    def test_detail_section_structure(self):
        expected = "\n".join([
            "細節進度",
            "- DEMO",
            "  - Triaged",
            f"    - {url('DEMO-10')} — title DEMO-10",
            f"    - {url('DEMO-12')} — title DEMO-12",
            "  - Done",
            f"    - {url('DEMO-3')} — title DEMO-3",
        ])
        self.assertIn(expected, self.text)

    def test_epic_section_structure(self):
        expected = "\n".join([
            "專案進度（已完成/總數）",
            "- DEMO",
            "  - Untriaged",
            f"    - {url('DEMO-7')} — title DEMO-7 (0/0)",
            f"    - {url('DEMO-20')} — title DEMO-20 (0/2)",
            "  - In Review",
            f"    - {url('DEMO-30')} — title DEMO-30 (2/2)",
        ])
        self.assertIn(expected, self.text)

    def test_warning_and_reminders(self):
        self.assertIn(f"警告\n- {url('DEMO-7')} — title DEMO-7：Epic 已開啟，但底下沒有任何卡片\n", self.text)
        self.assertIn(f"- {url('DEMO-20')} — title DEMO-20：子卡已有 In Progress（DEMO-20-c0），Epic 仍為 Untriaged，應切 In Progress",
                      self.text)
        self.assertIn(f"- {url('DEMO-30')} — title DEMO-30：子卡已全部 Done/Rejected，Epic 仍為 In Review，應可關閉", self.text)

    def test_missing_summary_shows_url_only(self):
        text = br.render_text(resolved(cards=[{"key": "DEMO-1", "status": "Done"}],
                                       epics=[{"key": "DEMO-2", "summary": "", "status": "Untriaged", "children": []}]))
        self.assertIn(f"    - {url('DEMO-1')}\n", text)
        self.assertIn(f"    - {url('DEMO-2')} (0/0)\n", text)
        self.assertIn(f"- {url('DEMO-2')}：Epic 已開啟，但底下沒有任何卡片", text)

    def test_no_alerts_says_none(self):
        text = br.render_text(resolved(epics=[epic("DEMO-1", "Done", "Done")]))
        self.assertIn("警告\n- 無\n", text)
        self.assertIn("提醒\n- 無", text)

    def test_project_without_cards_still_listed(self):
        text = br.render_text(resolved(epics=[epic("DEMO-1", "Done", "Done")]))
        self.assertIn("細節進度\n- DEMO\n  - 無\n", text)

    def test_multiple_projects_each_get_level_one(self):
        r = resolved(cards=[{"key": "DEMO-1", "status": "Done"}])
        r["projects"].append({"key": "OTHER", "cards": [{"key": "OTHER-5", "status": "Triaged"}], "epics": []})
        text = br.render_text(r)
        detail = text.split("專案進度")[0]
        self.assertLess(detail.index("- DEMO\n"), detail.index("- OTHER\n"))


class RenderHtml(unittest.TestCase):
    def test_link_text_is_the_url_and_title_follows(self):
        html = br.render_html(resolved(cards=[{"key": "DEMO-1", "summary": "Fix it", "status": "Done"}]))
        self.assertIn(f'<a href="{url("DEMO-1")}">{url("DEMO-1")}</a> — Fix it', html)

    def test_nesting_is_balanced(self):
        html = br.render_html(resolved(
            cards=[{"key": "DEMO-1", "status": "Done"}],
            epics=[epic("DEMO-2", "Untriaged", "In Progress"), epic("DEMO-3", "Untriaged")],
        ))
        self.assertEqual(html.count("<ul>"), html.count("</ul>"))
        self.assertEqual(html.count("<li>"), html.count("</li>"))

    def test_text_is_escaped(self):
        r = resolved(cards=[{"key": "DEMO-1", "summary": "a <b> & c", "status": "A<B"}])
        html = br.render_html(r)
        self.assertIn("A&lt;B", html)
        self.assertIn("a &lt;b&gt; &amp; c", html)


class Summary(unittest.TestCase):
    def test_counts_raw_rows_per_project(self):
        r = raw(touched=[issue("DEMO-1"), issue("DEMO-2", type="Epic")],
                epics=[issue("DEMO-2", type="Epic")],
                children=[issue("DEMO-1", parent="DEMO-2"), issue("DEMO-3", parent="DEMO-2"), issue("DEMO-4")],
                extra_projects=[{"key": "OTHER", "touched": [], "epics": [], "children": []}])
        self.assertEqual(br.summary(r), "DEMO touched=2 epics=1 children=3; OTHER touched=0 epics=0 children=0"
                                        f" | fp={br.fingerprint(r)}")


class Fingerprint(unittest.TestCase):
    TRICKY = {"site": "https://x", "me": None, "projects": [{"key": "DEMO", "touched": [
        {"key": "DEMO-1", "summary": "中文 \"quote\" back\\slash 🚀 tab\there \u0001 \u2028 / end",
         "status": "Done", "parent": None}], "epics": [], "children": []}]}

    def test_matches_the_javascript_snippet_in_skill_md(self):
        # node: JSON.stringify(TRICKY), then h = (h * 131 + codePoint) % 2147483647 per character
        self.assertEqual(br.fingerprint(self.TRICKY), 60529013)

    def test_ignores_formatting(self):
        import json as j
        pretty = j.loads(j.dumps(self.TRICKY, indent=2))
        self.assertEqual(br.fingerprint(pretty), br.fingerprint(self.TRICKY))

    def test_one_character_typo_changes_it(self):
        r = raw(touched=[issue("DEMO-1", summary="Fix login")])
        typo = raw(touched=[issue("DEMO-1", summary="Fix logon")])
        self.assertNotEqual(br.fingerprint(r), br.fingerprint(typo))

    def test_swapped_characters_change_it(self):
        self.assertNotEqual(br.fingerprint(raw(touched=[issue("DEMO-12")])),
                            br.fingerprint(raw(touched=[issue("DEMO-21")])))


class RenderCommand(unittest.TestCase):
    def run_render(self, data, *extra, env=None):
        tmp = tempfile.mkdtemp()
        src, out = os.path.join(tmp, "data.json"), os.path.join(tmp, "report.html")
        with open(src, "w", encoding="utf-8") as f:
            json.dump(data, f)
        proc = subprocess.run([sys.executable, SCRIPT, "render", src, "--html", out, *extra],
                              capture_output=True, text=True, env=env)
        return proc, out

    def test_stdout_is_the_text_report_and_stderr_has_data_and_path(self):
        data = raw(touched=[issue("DEMO-1", parent="DEMO-20", summary="Fix it")],
                   epics=[issue("DEMO-20", type="Epic", summary="Big thing")],
                   children=[issue("DEMO-1", parent="DEMO-20")])
        proc, out = self.run_render(data)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, br.render_text(br.resolve(data)))
        self.assertIn(f"{url('DEMO-1')} — Fix it", proc.stdout)
        self.assertTrue(proc.stderr.startswith(f"[data: DEMO touched=1 epics=1 children=1 | fp={br.fingerprint(data)}]\n"),
                        proc.stderr)
        self.assertIn(f"[HTML written to {os.path.abspath(out)}]", proc.stderr)
        with open(out, encoding="utf-8") as f:
            self.assertEqual(f.read(), br.render_html(br.resolve(data)))

    def test_copy_without_clipboard_tool_says_so(self):
        env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
        proc, _ = self.run_render(raw(), "--copy", env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("no clipboard tool", proc.stderr)
        self.assertNotIn("HTML copied to clipboard", proc.stderr)


class DefaultRange(unittest.TestCase):
    def check(self, now, start):
        import datetime as dt
        s, e = br.default_range(dt.datetime.fromisoformat(now))
        self.assertEqual((s, e), (start, now[:16].replace("T", " ")))

    def test_midweek_goes_back_to_previous_friday(self):
        self.check("2026-11-11T10:35:12", "2026-11-06 18:00")

    def test_saturday_uses_yesterday(self):
        self.check("2026-11-07T09:00:00", "2026-11-06 18:00")

    def test_friday_uses_previous_week_even_after_six(self):
        self.check("2026-11-06T19:30:00", "2026-10-30 18:00")


if __name__ == "__main__":
    unittest.main()
