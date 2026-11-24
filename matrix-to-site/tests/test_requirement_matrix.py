import collections
import contextlib
import copy
import csv
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path[:0] = [SCRIPTS, HERE]
import requirement_matrix as rm
import test_matrix_to_site as base

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CSV = FIXTURES / "requirement.csv"
MAPPING = yaml.safe_load((FIXTURES / "requirement-mapping.yaml").read_text())


def load(csv_path=CSV, mapping=MAPPING):
    conv = rm.RequirementConverter(copy.deepcopy(mapping))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        conv.run(csv_path)
    conv.stdout = out.getvalue()
    return conv


def items(conv):
    return {i["id"]: i for c in conv.components for i in c["features"]}


def rewrite(tmp, edit):
    with CSV.open(newline="") as f:
        rows = list(csv.reader(f))
    edit(rows)
    path = Path(tmp) / "r.csv"
    with path.open("w", newline="") as f:
        csv.writer(f).writerows(rows)
    return path


class RequirementConvertTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.conv = load()
        self.items = items(self.conv)

    def test_structure(self):
        self.assertEqual(
            [(c["id"], c["name"]) for c in self.conv.components],
            [
                ("A.1", "General"),
                ("A.2", "Hardware Configuration"),
                ("A.3", "Security"),
                ("A.4", "Process"),
            ],
        )
        self.assertEqual(
            list(self.items),
            ["1.01", "1.02", "2.01", "2.03", "2.08.01", "2.10", "2.16", "3.01", "4.01"],
        )
        self.assertEqual(self.conv.skipped_rows, [13])

    def test_excluded_items(self):
        self.assertEqual(self.conv.excluded_items, 2)
        self.assertEqual(
            self.items["2.08.01"],
            {
                "id": "2.08.01",
                "name": "Wi-Fi (2.4 GHz)",
                "fields": {"source": "Initial SoW", "scope": "out-of-scope"},
            },
        )
        self.assertEqual(
            self.items["4.01"],
            {
                "id": "4.01",
                "name": "Release Notes",
                "fields": {"source": "Initial SoW", "scope": "out-of-scope"},
            },
        )

    def test_status_counts(self):
        def count(col):
            return collections.Counter(
                i["status"][col]
                for i in self.items.values()
                if col in i.get("status", {})
            )

        self.assertEqual(
            count("ea"), {"supported": 3, "enabled": 2, "not-supported": 1}
        )
        self.assertEqual(count("fc"), {"enabled": 1})
        self.assertEqual(self.items["1.01"]["status"]["fc"], "enabled")
        self.assertNotIn("ea", self.items["3.01"].get("status", {}))
        self.assertEqual(count("ga"), {})

    def test_test_default(self):
        with_test = {i for i, v in self.items.items() if "test" in v.get("status", {})}
        self.assertEqual(
            with_test, {"1.01", "1.02", "2.01", "2.03", "2.10", "2.16", "3.01"}
        )
        self.assertEqual({self.items[i]["status"]["test"] for i in with_test}, {"tbd"})

    def test_jira_and_names(self):
        for item in self.items.values():
            self.assertNotIn("jira", item.get("fields", {}))
        self.assertNotIn("jira", [f["id"] for f in self.conv.meta()["fields"]])
        self.assertEqual(
            self.items["2.03"]["notes"],
            {
                "discovery": "PROJ-12: needs workaround\n\n[x01]\nworks with component\n\nJira: PROJ-12",
            },
        )
        for item in self.items.values():
            self.assertNotIn("general", item.get("notes", {}))
        self.assertNotIn("notes", self.items["2.08.01"])
        self.assertEqual(sum(self.conv.dropped_bug_tokens.values()), 3)
        self.assertEqual(self.items["2.10"]["fields"]["scope"], "tbd")
        self.assertNotIn("risk", self.items["2.10"]["fields"])
        self.assertEqual(self.items["2.01"]["fields"]["test_ids"], ["cpu-001"])

    def test_jira_cell_mixed_tokens(self):
        def edit(rows):
            rows[3][9] = "LP#001, PROJ-30, PROJ-30"

        conv = load(rewrite(self.tmp, edit))
        notes = items(conv)["1.01"]["notes"]
        self.assertTrue(notes["discovery"].endswith("\n\nJira: PROJ-30"))
        self.assertEqual(sum(conv.dropped_bug_tokens.values()), 2)

    def test_default_keys_fall_back_to_discovery(self):
        mapping = copy.deepcopy(MAPPING)
        mapping.pop("notes_default_key", None)
        mapping.pop("notes_head_key", None)
        notes = items(load(mapping=mapping))["2.03"]["notes"]
        self.assertEqual(set(notes), {"discovery"})
        self.assertTrue(notes["discovery"].endswith("\n\nJira: PROJ-12"))

    def test_notes_stay_in_discovery(self):
        self.assertEqual(
            self.items["1.01"]["notes"], {"discovery": "[x01]\nos-release"}
        )
        self.assertEqual(set(self.items["2.01"]["notes"]), {"discovery"})
        self.assertIn("[x01] the same", self.items["2.01"]["notes"]["discovery"])
        for item in self.items.values():
            for key in ("ea", "fc", "ga"):
                self.assertNotIn(key, item.get("notes", {}))

    def test_meta(self):
        meta = self.conv.meta()
        self.assertEqual(meta["template_version"], "v1.2")
        self.assertEqual(meta["template"], "requirement-matrix")
        self.assertEqual(meta["noun"], ["requirement", "requirements"])
        self.assertEqual(
            meta["exclude_when"], {"field": "scope", "equals": "out-of-scope"}
        )
        self.assertEqual(len(meta["platforms"]), 1)
        for f in meta["fields"]:
            self.assertNotIn("column", f)
            self.assertNotIn("raw_values", f)
        self.assertEqual([c["id"] for c in meta["columns"]], ["ea", "fc", "ga", "test"])
        self.assertEqual(
            set(meta["columns"][-1]), {"id", "name", "group", "role", "note_key"}
        )

    def test_verify(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertTrue(self.conv.verify())
        text = out.getvalue()
        self.assertIn("out-of-scope: 2 items, their other columns ignored", text)
        self.assertIn("test: 7 set by default (not from CSV)", text)
        self.assertIn("dropped 3 bug tokens", text)

    def test_tbd_status_fails_verify(self):
        def edit(rows):
            rows[10][10] = "TBD"

        conv = load(rewrite(self.tmp, edit))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertFalse(conv.verify())
        self.assertIn("ea: 'TBD'", out.getvalue())

    def test_excluded_row_other_columns_never_read(self):
        def edit(rows):
            rows[7][10] = "Maybe"
            rows[7][9] = "junk"

        conv = load(rewrite(self.tmp, edit))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertTrue(conv.verify())
        self.assertEqual(sum(conv.dropped_bug_tokens.values()), 3)

    def test_unknown_status_fails_verify(self):
        def edit(rows):
            rows[3][10] = "Maybe"

        conv = load(rewrite(self.tmp, edit))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(conv.verify())

    def test_category_reappearing_fails(self):
        def edit(rows):
            rows[11][2] = "General"

        with self.assertRaises(SystemExit) as cm:
            load(rewrite(self.tmp, edit))
        self.assertIn("General", str(cm.exception))

    def test_duplicate_id_fails(self):
        def edit(rows):
            rows[4][1] = "1.01"

        with self.assertRaises(SystemExit) as cm:
            load(rewrite(self.tmp, edit))
        self.assertIn("1.01", str(cm.exception))

    def test_header_names_normalised(self):
        def edit(rows):
            rows[2][3] = "Feature   (Component)\n"
            rows[2][1] = "Req \n ID"

        mapping = copy.deepcopy(MAPPING)
        mapping["id_column"] = "Req ID"
        mapping["columns"]["name"] = "Feature (Component)"
        conv = load(rewrite(self.tmp, edit), mapping)
        self.assertEqual(len(items(conv)), 9)

    def test_other_template_version_warns(self):
        def edit(rows):
            rows[0][1] = "v1.1"

        conv = load(rewrite(self.tmp, edit))
        self.assertIn("warning: template version v1.1", conv.stdout)
        self.assertEqual(len(items(conv)), 9)

    def test_main_dispatches(self):
        mapping = Path(self.tmp) / "m.yaml"
        mapping.write_text(yaml.safe_dump(MAPPING))
        out = Path(self.tmp) / "data"
        res = base.run(
            os.path.join(SCRIPTS, "convert_csv.py"),
            "--mapping", str(mapping), "--csv", str(CSV), "--out", str(out),
        )  # fmt: skip
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(len(list(out.glob("A.*.yaml"))), 4)
        self.assertIn(
            'id: "2.10"', (out / "A.02-hardware-configuration.yaml").read_text()
        )


@unittest.skipUnless(shutil.which("node"), "node not installed")
class RequirementBuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        subprocess.run(["git", "init", "-q", "-b", "main", self.repo], check=True)
        base.git(self.repo, "commit", "-q", "--allow-empty", "-m", "init")

    def scaffold(self, *args):
        return base.run(os.path.join(SCRIPTS, "scaffold.py"), self.repo, *args)

    def test_check_and_format_are_clean(self):
        self.assertEqual(
            self.scaffold("--deploy-branch", "matrix-table-demo").returncode, 0
        )
        data = Path(self.repo) / "matrix-table" / "data"
        conv = load(CSV)
        conv.write(data)
        before = {p.name: p.read_text() for p in data.glob("*.yaml")}
        build = os.path.join(self.repo, "matrix-table", "tools", "build.mjs")
        check = subprocess.run(
            ["node", build, "check"], check=False, capture_output=True, text=True
        )
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertNotIn("warning:", check.stdout + check.stderr)
        fmt = subprocess.run(
            ["node", build, "format"], check=False, capture_output=True, text=True
        )
        self.assertEqual(fmt.returncode, 0, fmt.stderr)
        after = {p.name: p.read_text() for p in data.glob("*.yaml")}
        self.assertEqual(before, after)
        self.assertIn('id: "2.10"', after["A.02-hardware-configuration.yaml"])


class RequirementInspectTest(unittest.TestCase):
    def rows(self, path=CSV):
        with path.open(newline="") as f:
            return list(csv.reader(f))

    def inspect(self, env=None):
        run_env = {
            k: v for k, v in os.environ.items() if k != "MATRIX_TO_SITE_JIRA_URL"
        }
        run_env.update(env or {})
        return subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "inspect_csv.py"), str(CSV)],
            capture_output=True,
            check=False,
            text=True,
            env=run_env,
        )

    def test_detect(self):
        self.assertEqual(rm.detect(self.rows()), "v1.2")
        self.assertIsNone(rm.detect(self.rows(FIXTURES / "feature.csv")))

    def test_printed_draft_has_string_tones(self):
        result = self.inspect()
        self.assertEqual(result.returncode, 0, result.stderr)
        draft = yaml.safe_load(result.stdout)
        tones = [s["tone"] for s in draft["status_sets"]["execution"]]
        self.assertTrue(all(isinstance(t, str) for t in tones), tones)
        self.assertIn("# CONFIRM", result.stdout)
        self.assertEqual(draft["template"], "requirement-matrix")

    def test_stderr_counts(self):
        err = self.inspect().stderr
        self.assertIn("1 row without Req ID", err)
        self.assertIn("3 bug tokens are not Jira keys", err)

    def test_draft_shape(self):
        draft = yaml.safe_load(self.inspect().stdout)
        self.assertEqual(
            draft["platforms"], [{"id": "platform-1", "name": "Platform 1"}]
        )
        self.assertEqual(
            [(c["id"], c["name"]) for c in draft["status_columns"]],
            [("ea", "EA"), ("fc", "FC"), ("ga", "GA"), ("test", "Test")],
        )
        self.assertEqual(
            draft["exclude_when"], {"field": "scope", "equals": "out-of-scope"}
        )
        self.assertNotIn("notes_markers", draft)
        scope = next(f for f in draft["fields"] if f["id"] == "scope")
        self.assertEqual(scope["raw_values"]["TBD"], "tbd")

    def test_jira_url_from_env(self):
        env = {"MATRIX_TO_SITE_JIRA_URL": "https://example.atlassian.net"}
        draft = yaml.safe_load(self.inspect(env).stdout)
        self.assertEqual(draft["jira_url"], "https://example.atlassian.net/browse/")
        self.assertEqual(draft["jira_projects"], ["PROJ"])
        self.assertNotIn("jira_url", yaml.safe_load(self.inspect().stdout))

    def test_draft_maps_jira_column(self):
        draft = yaml.safe_load(self.inspect().stdout)
        self.assertEqual(draft["columns"]["jira"], 9)
        self.assertNotIn("jira", [f["id"] for f in draft["fields"]])

    def variant(self, edit):
        rows = self.rows()
        edit(rows)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        path = Path(tmp) / "v.csv"
        with path.open("w", newline="") as f:
            csv.writer(f).writerows(rows)
        return path, subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "inspect_csv.py"), str(path)],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_extra_column_before_status_columns(self):
        def edit(rows):
            for n, row in enumerate(rows):
                row.insert(10, "extra" if n == 2 else "")

        path, result = self.variant(edit)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("CONFIRM column positions", result.stdout)
        draft = yaml.safe_load(result.stdout)
        cols = [c["column"] for c in draft["status_columns"] if "column" in c]
        self.assertEqual(cols, [11, 12, 13])
        for key in ("title", "jira_url", "repository", "platforms"):
            draft[key] = MAPPING[key]
        mapping = copy.deepcopy(MAPPING)
        for c in mapping["status_columns"]:
            if "column" in c:
                c["column"] += 1
        for f in mapping["fields"]:
            if f["column"] >= 10:
                f["column"] += 1
        mapping["columns"] = dict(MAPPING["columns"])
        self.assertEqual(
            {f["id"]: f["column"] for f in draft["fields"]},
            {f["id"]: f["column"] for f in mapping["fields"]},
        )
        a, b = load(path, draft), load(path, mapping)
        self.assertEqual(a.components, b.components)
        self.assertEqual(a.meta(), b.meta())

    def test_unrecognised_milestone_headers_fall_back(self):
        def edit(rows):
            for i in range(10, 16):
                rows[2][i] = f"M{i}"

        _, result = self.variant(edit)
        self.assertIn("milestone headers", result.stderr)
        self.assertIn("CONFIRM column positions", result.stdout)
        draft = yaml.safe_load(result.stdout)
        cols = [c["column"] for c in draft["status_columns"] if "column" in c]
        self.assertEqual(cols, [10, 11, 12])

    def test_other_version_returned_and_warned(self):
        def edit(rows):
            rows[0][1] = "v1.3"

        self.assertEqual(rm.detect(self.variant_rows(edit)), "v1.3")
        _, result = self.variant(edit)
        self.assertIn("template version v1.3", result.stderr)

    def variant_rows(self, edit):
        rows = self.rows()
        edit(rows)
        return rows

    def test_round_trip_reproduces_fixture(self):
        draft = yaml.safe_load(self.inspect().stdout)
        for key in ("title", "jira_url", "repository", "platforms"):
            draft[key] = MAPPING[key]
        a, b = load(mapping=draft), load()
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        a.write(Path(tmp) / "a")
        b.write(Path(tmp) / "b")
        names = sorted(p.name for p in (Path(tmp) / "b").iterdir())
        self.assertEqual(names, sorted(p.name for p in (Path(tmp) / "a").iterdir()))
        for name in names:
            self.assertEqual(
                (Path(tmp) / "a" / name).read_text(),
                (Path(tmp) / "b" / name).read_text(),
                name,
            )


if __name__ == "__main__":
    unittest.main()
