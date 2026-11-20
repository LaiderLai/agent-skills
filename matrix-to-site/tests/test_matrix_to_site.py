import csv
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(HERE, "..")
SCRIPTS = os.path.join(SKILL, "scripts")
sys.path.insert(0, SCRIPTS)
import convert_csv as cc

# A small two-header-row export: section rows, component header rows (A.1.0), features,
# one empty milestone column, and remarks tagged with a line-leading [BoardB] marker.
HEADER = [
    [
        "Item",
        "ID",
        "Component",
        "Feature",
        "Feature",
        "Comment",
        "SoC",
        "Board A EA",
        "Board A GA",
        "Board B Beta",
        "Board B GA",
        "Remarks",
    ],
    [
        "",
        "",
        "",
        "",
        "",
        "",
        "Silicon",
        "Reference board",
        "Reference board",
        "Partner board",
        "Partner board",
        "",
    ],
]
ROWS = [
    [
        "Kernel",
        "",
        "",
        "",
        "",
        "Kernel features",
        "",
        "",
        "",
        "",
        "",
        "BIOS 1.0\n\n[BoardB] BIOS 2.0",
    ],
    ["Kernel", "A.1.0", "System", "", "", "CPU and memory", "", "", "", "", "", ""],
    [
        "Kernel",
        "",
        "System",
        "Boot",
        "Boot to shell",
        "",
        "YES",
        "YES",
        "YES",
        "YES",
        "",
        "Booted\n\n[BoardB] Booted too",
    ],
    [
        "Kernel",
        "",
        "System",
        "",
        "Reboot",
        "",
        "YES",
        "NO",
        "YES",
        "TBD",
        "",
        "PROJ-7: [BoardB] still open?",
    ],
    [
        "Kernel",
        "",
        "System",
        "",
        "Suspend",
        "",
        "NO",
        "NO",
        "NO",
        "NO",
        "",
        "untagged note",
    ],
    ["", "", "", "", "", "", "", "", "", "", "", ""],
    ["Kernel", "A.2.0", "Storage", "", "", "Disks", "", "", "", "", "", ""],
    [
        "Kernel",
        "",
        "Storage",
        "NVMe",
        "NVMe read/write",
        "",
        "YES",
        "YES",
        "YES",
        "TBD",
        "",
        "[build] log line",
    ],
    ["Userspace", "", "", "", "", "Userspace features", "", "", "", "", "", ""],
    ["Userspace", "B.1.0", "Video", "", "", "Playback", "", "", "", "", "", ""],
    [
        "Userspace",
        "",
        "Video",
        "",
        "Hardware decode",
        "",
        "TBD",
        "NO",
        "NO",
        "TBD",
        "",
        "",
    ],
]
MAPPING = {
    "title": "DEMO Matrix table",
    "header_rows": 2,
    "jira_url": "https://example.atlassian.net/browse/",
    "jira_projects": ["PROJ"],
    "repository": {"name": "example-org/example-repo", "branch": "feature-matrix-demo"},
    "columns": {
        "section": 0,
        "component_id": 1,
        "component": 2,
        "label": 3,
        "feature": 4,
        "comment": 5,
        "notes": 11,
    },
    "status_values": {"YES": "supported", "NO": "unsupported", "TBD": "tbd"},
    "platforms": [
        {"id": "board-a", "name": "Board A", "hardware": "Reference board"},
        {"id": "board-b", "name": "Board B", "hardware": ""},
    ],
    "status_columns": [
        {"column": 6, "id": "soc", "name": "SoC", "group": "Supported by HW/FW"},
        {"column": 7, "id": "board-a-ea", "platform": "board-a", "name": "EA"},
        {"column": 8, "id": "board-a-ga", "platform": "board-a", "name": "GA"},
        {"column": 9, "id": "board-b-beta", "platform": "board-b", "name": "Beta"},
        {"column": 10, "id": "board-b-ga", "platform": "board-b", "name": "GA"},
    ],
    "notes_markers": {"BoardB": "board-b"},
    "notes_head_platform": "board-a",
}


def write_csv(path, rows=None, encoding="utf-8"):
    buf = io.StringIO()
    csv.writer(buf).writerows(HEADER + (ROWS if rows is None else rows))
    with open(path, "w", encoding=encoding, newline="") as f:
        f.write(buf.getvalue())


def run(*args, cwd=None, env=None):
    return subprocess.run(
        [sys.executable, *args],
        check=False,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )


def git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


class ConvertTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.csv = os.path.join(self.tmp, "features.csv")
        write_csv(self.csv)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def convert(self, mapping=MAPPING):
        conv = cc.Converter(mapping)
        conv.run(cc.Path(self.csv))
        return conv

    def features(self, conv):
        return {f["id"]: f for c in conv.components for f in c["features"]}

    def test_structure_and_ids(self):
        conv = self.convert()
        self.assertEqual([c["id"] for c in conv.components], ["A.1", "A.2", "B.1"])
        self.assertEqual(
            list(self.features(conv)), ["A.1.1", "A.1.2", "A.1.3", "A.2.1", "B.1.1"]
        )
        boot = self.features(conv)["A.1.1"]
        self.assertEqual((boot["name"], boot["label"]), ("Boot to shell", "Boot"))
        self.assertEqual(conv.meta()["sections"][0]["description"], "Kernel features")

    def test_status_counts_match_csv(self):
        conv = self.convert()
        self.assertTrue(conv.verify())
        self.assertEqual(
            dict(conv.csv_counts["board-b-beta"]),
            {"supported": 1, "tbd": 3, "unsupported": 1},
        )
        self.assertNotIn(
            "board-b-ga", self.features(conv)["A.1.1"]["status"]
        )  # empty milestone = not set

    def test_notes_split_by_marker(self):
        f = self.features(self.convert())
        self.assertEqual(
            f["A.1.1"]["notes"], {"board-a": "Booted", "board-b": "Booted too"}
        )
        self.assertEqual(
            f["A.1.2"]["notes"], {"board-b": "PROJ-7: [BoardB] still open?"}
        )  # inline marker
        self.assertEqual(f["A.1.3"]["notes"], {"general": "untagged note"})
        self.assertEqual(
            f["A.2.1"]["notes"], {"general": "[build] log line"}
        )  # not a mapped marker

    def test_notes_default_platform(self):
        f = self.features(
            self.convert({**MAPPING, "notes_default_platform": "board-a"})
        )
        self.assertEqual(f["A.1.3"]["notes"], {"board-a": "untagged note"})

    def test_unknown_status_value_fails(self):
        rows = [r[:] for r in ROWS]
        rows[2][7] = "Partial"
        write_csv(self.csv, rows)
        conv = self.convert()
        self.assertFalse(conv.verify())
        self.assertIn(("board-a-ea", "Partial"), conv.unknown_values)

    def test_empty_csv_fails(self):
        write_csv(self.csv, rows=[])
        self.assertFalse(self.convert().verify())

    def test_cp950_export_is_detected(self):
        rows = [r[:] for r in ROWS]
        rows[2][4] = "開機到 shell"
        write_csv(self.csv, rows, encoding="cp950")
        conv = self.convert()
        self.assertEqual(conv.encoding, "cp950")
        self.assertEqual(self.features(conv)["A.1.1"]["name"], "開機到 shell")

    def test_meta_has_no_empty_strings(self):
        out = os.path.join(self.tmp, "data")
        conv = self.convert()
        conv.write(cc.Path(out))
        with open(os.path.join(out, "_meta.yaml"), encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("''", text)  # yamllint double-quote rules reject ''
        meta = yaml.safe_load(text)
        self.assertEqual(meta["title"], "DEMO Matrix table")
        self.assertEqual(meta["repository"]["tag_prefix"], "matrix-table/")
        self.assertNotIn("hardware", meta["platforms"][1])


class InspectTest(unittest.TestCase):
    def test_draft_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "features.csv")
            write_csv(path)
            out = run(os.path.join(SCRIPTS, "inspect_csv.py"), path)
            self.assertEqual(out.returncode, 0, out.stderr)
            draft = yaml.safe_load(out.stdout)
            self.assertEqual(draft["header_rows"], 2)
            self.assertEqual(
                [c["column"] for c in draft["status_columns"]], [6, 7, 8, 9]
            )
            self.assertEqual(draft["columns"]["notes"], 11)
            self.assertIn("BoardB", draft["notes_markers"])
            self.assertIn(
                "empty column 10", out.stdout
            )  # empty milestone is pointed out

    def draft(self, jira_env):
        env = {k: v for k, v in os.environ.items() if k != "MATRIX_TO_SITE_JIRA_URL"}
        if jira_env is not None:
            env["MATRIX_TO_SITE_JIRA_URL"] = jira_env
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "features.csv")
            write_csv(path)
            out = run(os.path.join(SCRIPTS, "inspect_csv.py"), path, env=env)
            self.assertEqual(out.returncode, 0, out.stderr)
            return yaml.safe_load(out.stdout)

    def test_jira_url_from_env(self):
        self.assertEqual(
            self.draft("https://jira.example.com")["jira_url"],
            "https://jira.example.com/browse/",
        )

    def test_jira_url_unset_is_left_for_the_agent_to_ask(self):
        self.assertNotIn("jira_url", self.draft(None))  # emitted as a commented TODO

    def test_jira_url_normalisation(self):
        import inspect_csv

        for given in (
            "https://x.atlassian.net",
            "https://x.atlassian.net/",
            "https://x.atlassian.net/browse/",
        ):
            self.assertEqual(
                inspect_csv.jira_browse_url(given),
                "https://x.atlassian.net/browse/",
                given,
            )
        self.assertEqual(inspect_csv.jira_browse_url("  "), "")

    def test_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "empty.csv")
            open(path, "w").close()
            self.assertEqual(
                run(os.path.join(SCRIPTS, "inspect_csv.py"), path).returncode, 1
            )


class ScaffoldTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.remote = os.path.join(self.tmp, "remote.git")
        self.repo = os.path.join(self.tmp, "repo")
        subprocess.run(
            ["git", "init", "-q", "--bare", "-b", "main", self.remote], check=True
        )
        subprocess.run(
            ["git", "clone", "-q", self.remote, self.repo],
            check=True,
            capture_output=True,
        )
        git(self.repo, "checkout", "-q", "-b", "main")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "init")
        git(self.repo, "push", "-q", "origin", "main")
        git(self.repo, "remote", "set-head", "origin", "main")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def scaffold(self, *args):
        return run(os.path.join(SCRIPTS, "scaffold.py"), self.repo, *args)

    def test_refuses_default_branches(self):
        for branch in ("main", "master"):
            self.assertEqual(
                self.scaffold("--deploy-branch", branch).returncode, 1, branch
            )

    def test_install_and_reinstall(self):
        self.assertEqual(
            self.scaffold("--deploy-branch", "feature-matrix-demo").returncode, 0
        )
        with open(
            os.path.join(self.repo, ".github", "workflows", "matrix-site.yml")
        ) as f:
            workflow = f.read()
        self.assertTrue(workflow.startswith("name: Matrix Site"))
        self.assertNotIn("__DEPLOY_BRANCH__", workflow)
        self.assertIn("refs/heads/feature-matrix-demo", workflow)
        self.assertTrue(
            os.path.exists(
                os.path.join(self.repo, "feature-matrix", "tools", "convert_csv.py")
            )
        )
        self.assertEqual(
            self.scaffold("--deploy-branch", "feature-matrix-demo").returncode, 1
        )  # already installed

    def test_legacy_workflow_replaced_on_force(self):
        legacy = os.path.join(self.repo, ".github", "workflows", "feature-matrix.yml")
        os.makedirs(os.path.dirname(legacy))
        with open(legacy, "w") as f:
            f.write("name: Feature Matrix\n")
        self.assertEqual(
            self.scaffold("--deploy-branch", "feature-matrix-demo").returncode, 1
        )
        self.assertEqual(
            self.scaffold(
                "--deploy-branch", "feature-matrix-demo", "--force"
            ).returncode,
            0,
        )
        self.assertFalse(os.path.exists(legacy))

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_end_to_end_build(self):
        self.assertEqual(
            self.scaffold("--deploy-branch", "feature-matrix-demo").returncode, 0
        )
        csv_path = os.path.join(self.tmp, "features.csv")
        write_csv(csv_path)
        mapping = os.path.join(self.tmp, "mapping.yaml")
        with open(mapping, "w") as f:
            yaml.safe_dump(MAPPING, f)
        data = os.path.join(self.repo, "feature-matrix", "data")
        out = run(
            os.path.join(SCRIPTS, "convert_csv.py"),
            "--mapping",
            mapping,
            "--csv",
            csv_path,
            "--out",
            data,
        )
        self.assertEqual(out.returncode, 0, out.stdout)
        build = os.path.join(self.repo, "feature-matrix", "tools", "build.mjs")
        for args in (["format"], ["check"], ["build", os.path.join(self.tmp, "dist")]):
            res = subprocess.run(
                ["node", build, *args], check=False, capture_output=True, text=True
            )
            self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "dist", "data.json")))


if __name__ == "__main__":
    unittest.main()
