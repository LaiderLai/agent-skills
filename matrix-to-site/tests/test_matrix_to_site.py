import csv
import io
import json
import os
import re
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
    "repository": {"name": "example-org/example-repo", "branch": "matrix-table-demo"},
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
    "notes_default_platform": "board-a",
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

    def test_two_platforms_need_default_platform(self):
        mapping = {k: v for k, v in MAPPING.items() if not k.startswith("notes_head")}
        mapping.pop("notes_default_platform", None)
        with self.assertRaises(SystemExit) as cm:
            self.convert(mapping)
        self.assertIn("notes_default_platform", str(cm.exception))

    def test_one_platform_is_the_notes_default(self):
        mapping = {
            k: v
            for k, v in MAPPING.items()
            if k not in ("notes_head_platform", "notes_default_platform")
        }
        mapping["platforms"] = MAPPING["platforms"][:1]
        mapping["status_columns"] = [
            c
            for c in MAPPING["status_columns"]
            if c.get("platform", MAPPING["platforms"][0]["id"])
            == MAPPING["platforms"][0]["id"]
        ]
        mapping["notes_markers"] = {}
        conv = self.convert(mapping)
        only = MAPPING["platforms"][0]["id"]
        for f in self.features(conv).values():
            self.assertLessEqual(set(f.get("notes", {})), {only})

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
        self.assertEqual(f["A.1.3"]["notes"], {"board-a": "untagged note"})
        self.assertEqual(
            f["A.2.1"]["notes"], {"board-a": "[build] log line"}
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

    def test_draft_notes_platform_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "features.csv")
            write_csv(path)
            out = run(os.path.join(SCRIPTS, "inspect_csv.py"), path).stdout
        draft = yaml.safe_load(out)
        first = draft["platforms"][0]["id"]
        self.assertEqual(draft["notes_default_platform"], first)
        self.assertEqual(draft["notes_head_platform"], first)
        for key in ("notes_default_platform", "notes_head_platform"):
            line = next(ln for ln in out.splitlines() if ln.startswith(key))
            self.assertIn("# CONFIRM", line)

    def test_draft_notes_platform_keys_without_markers(self):
        rows = [[re.sub(r"\[\w+\]", "", c) for c in r] for r in ROWS]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "features.csv")
            write_csv(path, rows)
            out = run(os.path.join(SCRIPTS, "inspect_csv.py"), path).stdout
        draft = yaml.safe_load(out)
        self.assertNotIn("notes_markers", draft)
        for key in ("notes_default_platform", "notes_head_platform"):
            self.assertEqual(draft[key], draft["platforms"][0]["id"])
            line = next(ln for ln in out.splitlines() if ln.startswith(key))
            self.assertIn("# CONFIRM", line)

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
            self.scaffold("--deploy-branch", "matrix-table-demo").returncode, 0
        )
        with open(
            os.path.join(self.repo, ".github", "workflows", "matrix-site.yml")
        ) as f:
            workflow = f.read()
        self.assertTrue(workflow.startswith("name: Matrix Site"))
        self.assertNotIn("__DEPLOY_BRANCH__", workflow)
        self.assertIn("refs/heads/matrix-table-demo", workflow)
        self.assertTrue(
            os.path.exists(
                os.path.join(self.repo, "matrix-table", "tools", "convert_csv.py")
            )
        )
        self.assertEqual(
            self.scaffold("--deploy-branch", "matrix-table-demo").returncode, 1
        )  # already installed

    def test_force_without_mapping_keeps_the_mapping(self):
        mapping = os.path.join(self.tmp, "mapping.yaml")
        with open(mapping, "w") as f:
            f.write("title: Demo Matrix table\n")
        self.assertEqual(
            self.scaffold(
                "--deploy-branch", "matrix-table-demo", "--mapping", mapping
            ).returncode,
            0,
        )
        saved = os.path.join(self.repo, "matrix-table", "tools", "mapping.yaml")
        # "Update the site code only": --force without --mapping
        out = self.scaffold("--deploy-branch", "matrix-table-demo", "--force")
        self.assertEqual(out.returncode, 0, out.stderr)
        with open(saved) as f:
            self.assertEqual(f.read(), "title: Demo Matrix table\n")

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_end_to_end_build(self):
        self.assertEqual(
            self.scaffold("--deploy-branch", "matrix-table-demo").returncode, 0
        )
        csv_path = os.path.join(self.tmp, "features.csv")
        write_csv(csv_path)
        mapping = os.path.join(self.tmp, "mapping.yaml")
        with open(mapping, "w") as f:
            yaml.safe_dump(MAPPING, f)
        data = os.path.join(self.repo, "matrix-table", "data")
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
        build = os.path.join(self.repo, "matrix-table", "tools", "build.mjs")
        for args in (["format"], ["check"], ["build", os.path.join(self.tmp, "dist")]):
            res = subprocess.run(
                ["node", build, *args], check=False, capture_output=True, text=True
            )
            self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "dist", "data.json")))

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_end_to_end_build_requirement(self):
        fixtures = os.path.join(HERE, "fixtures")
        mapping = os.path.join(fixtures, "requirement-mapping.yaml")
        self.assertEqual(
            self.scaffold("--deploy-branch", "matrix-table-demo").returncode, 0
        )
        data = os.path.join(self.repo, "matrix-table", "data")
        out = run(
            os.path.join(SCRIPTS, "convert_csv.py"),
            "--mapping",
            mapping,
            "--csv",
            os.path.join(fixtures, "requirement.csv"),
            "--out",
            data,
        )
        self.assertEqual(out.returncode, 0, out.stdout)
        build = os.path.join(self.repo, "matrix-table", "tools", "build.mjs")
        for args in (["format"], ["check"], ["build", os.path.join(self.tmp, "dist")]):
            res = subprocess.run(
                ["node", build, *args], check=False, capture_output=True, text=True
            )
            self.assertEqual(res.returncode, 0, res.stderr)
            if args == ["check"]:
                self.assertNotIn("warning:", res.stdout + res.stderr)
            if args[0] == "build":
                self.assertIn("9 requirements", res.stdout)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "dist", "data.json")))

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_feature_meta_errors_are_reported_without_stack_trace(self):
        self.assertEqual(
            self.scaffold("--deploy-branch", "matrix-table-demo").returncode, 0
        )
        data = os.path.join(self.repo, "matrix-table", "data")
        os.makedirs(data, exist_ok=True)
        meta = {
            "title": "Demo",
            "repository": {"path": "matrix-table/data"},
            "sections": [{"id": "A", "name": "S"}],
            "platforms": [{"id": "p1", "name": "P1"}],
            "columns": [{"id": "c1", "name": "C", "platform": "p1"}],
            "some_unknown_key": True,
        }
        build = os.path.join(self.repo, "matrix-table", "tools", "build.mjs")
        meta_path = os.path.join(data, "_meta.yaml")

        def check():
            with open(meta_path, "w") as f:
                yaml.safe_dump(meta, f)
            return subprocess.run(
                ["node", build, "check"], check=False, capture_output=True, text=True
            )

        self.assertEqual(check().returncode, 0)
        meta["columns"] = [None]
        res = check()
        self.assertEqual(res.returncode, 1, res.stdout)
        self.assertIn("error: _meta.yaml: column 1 must be a mapping", res.stderr)
        self.assertNotIn("    at ", res.stderr)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_unquoted_numeric_id_fails_check(self):
        self.assertEqual(
            self.scaffold("--deploy-branch", "matrix-table-demo").returncode, 0
        )
        data = os.path.join(self.repo, "matrix-table", "data")
        os.makedirs(data, exist_ok=True)
        meta = {
            "title": "Demo",
            "repository": {"path": "matrix-table/data"},
            "template": "requirement-matrix",
            "noun": ["requirement", "requirements"],
            "sections": [{"id": "A", "name": "Requirements"}],
            "platforms": [{"id": "platform-1", "name": "Platform 1"}],
            "status_sets": {
                "requirement": [
                    {
                        "id": "supported",
                        "label": "Supported",
                        "resolved": True,
                        "tone": "yes",
                    },
                    {"id": "tbd", "label": "TBD", "resolved": False, "tone": "open"},
                ]
            },
            "fields": [
                {
                    "id": "scope",
                    "name": "Scope",
                    "type": "enum",
                    "values": [{"id": "in-scope", "label": "In Scope"}],
                }
            ],
            "note_keys": [{"id": "x01", "name": "x01"}],
            "columns": [
                {
                    "id": "p1-x01",
                    "name": "x01",
                    "platform": "platform-1",
                    "status_set": "requirement",
                    "note_key": "x01",
                }
            ],
        }
        with open(os.path.join(data, "_meta.yaml"), "w") as f:
            yaml.safe_dump(meta, f)
        with open(os.path.join(data, "A.01-demo.yaml"), "w") as f:
            f.write("id: A.1\nname: Demo\nfeatures:\n  - id: 2.10\n    name: GPU\n")
        build = os.path.join(self.repo, "matrix-table", "tools", "build.mjs")
        res = subprocess.run(
            ["node", build, "check"], check=False, capture_output=True, text=True
        )
        self.assertEqual(res.returncode, 1, res.stdout)
        self.assertIn("A.01-demo.yaml", res.stderr)
        self.assertIn("quoted string", res.stderr)


@unittest.skipUnless(shutil.which("node"), "node is required")
class GoldenFeatureTest(unittest.TestCase):
    CSV = os.path.join(HERE, "fixtures", "feature.csv")
    MAPPING = os.path.join(HERE, "fixtures", "feature-mapping.yaml")

    def test_matches_golden(self):
        res = run(
            os.path.join(HERE, "golden_tool.py"),
            "--csv",
            self.CSV,
            "--mapping",
            self.MAPPING,
            "--golden",
            os.path.join(HERE, "golden", "feature"),
        )
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_fixture_covers_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = run(
                os.path.join(SCRIPTS, "convert_csv.py"),
                "--mapping",
                self.MAPPING,
                "--csv",
                self.CSV,
                "--out",
                tmp,
            )
            self.assertEqual(res.returncode, 0, res.stdout)
            comps = []
            meta = None
            for name in sorted(os.listdir(tmp)):
                with open(os.path.join(tmp, name), encoding="utf-8") as f:
                    doc = yaml.safe_load(f)
                if name == "_meta.yaml":
                    meta = doc
                else:
                    comps.append(doc)
        feats = [f for c in comps for f in c["features"]]
        notes = [n for f in feats for n in (f.get("notes") or {}).items()]
        self.assertTrue(any(s.get("notes") for s in meta["sections"]))
        self.assertTrue(any(c.get("description") for c in comps))
        self.assertTrue(any(f.get("label") for f in feats))
        inline = [
            v for k, v in notes if k == "board-y" and v.startswith("PROJ-3: [BoardY]")
        ]
        self.assertTrue(inline)
        self.assertTrue(any("[build]" in v for _, v in notes))
        self.assertTrue(any("PROJ-7" in v for _, v in notes))
        used = {k for f in feats for k in f.get("status", {})}
        self.assertIn("board-y-ga", {c["id"] for c in meta["columns"]})
        self.assertNotIn("board-y-ga", used)


FAKE_GH = r'''#!/usr/bin/env python3
"""Stand-in for `gh`: answers `gh api <path>` from responses.json (a list per path, consumed in order)."""
import json, os, sys
state = os.path.join(os.path.dirname(os.path.abspath(__file__)), "responses.json")
if sys.argv[1:2] == ["auth"]:
    sys.exit(0)
path = sys.argv[-1]
data = json.load(open(state))
queue = data.get(path)
if not queue:
    sys.stderr.write("gh: Not Found (HTTP 404)\n")
    sys.exit(1)
answer = queue.pop(0) if len(queue) > 1 else queue[0]
json.dump(data, open(state, "w"))
if answer == 404:
    sys.stderr.write("gh: Not Found (HTTP 404)\n")
    sys.exit(1)
print(json.dumps(answer))
'''


class GithubStatusTest(unittest.TestCase):
    """github_status.py against a fake `gh`, so no network is needed."""

    REPO, BRANCH = "org/repo", "matrix-table-demo"
    SHA = "abc1234def5678abc1234def5678abc1234def56"  # full sha of the pushed commit
    SHORT = SHA[:7]

    def run_status(self, responses, *extra):
        with tempfile.TemporaryDirectory() as tmp:
            gh = os.path.join(tmp, "gh")
            with open(gh, "w") as f:
                f.write(FAKE_GH)
            os.chmod(gh, 0o755)
            with open(os.path.join(tmp, "responses.json"), "w") as f:
                json.dump(responses, f)
            env = {**os.environ, "PATH": tmp + os.pathsep + os.environ["PATH"]}
            return run(
                os.path.join(SCRIPTS, "github_status.py"),
                self.REPO,
                self.BRANCH,
                *extra,
                env=env,
            )

    def base(self, deployed_ref):
        r = f"repos/{self.REPO}"
        return {
            f"{r}/pages": [
                {"build_type": "workflow", "html_url": "https://x.pages.github.io/"}
            ],
            f"{r}/environments/github-pages": [
                {"name": "github-pages", "deployment_branch_policy": None}
            ],
            f"{r}/environments/github-pages/deployment-branch-policies": [
                {"branch_policies": []}
            ],
            f"{r}/deployments?environment=github-pages&per_page=20": [
                [
                    {
                        "id": 7,
                        "ref": deployed_ref,
                        "sha": self.SHA,
                        "created_at": "2026-11-23T06:00:12Z",
                    }
                ]
            ],
            f"{r}/deployments/7/statuses": [[{"state": "success"}]],
        }

    def runs_path(self):
        return f"repos/{self.REPO}/actions/runs?branch={self.BRANCH}&per_page=20"

    def test_waits_for_the_push_run_before_reporting(self):
        responses = self.base(self.BRANCH)
        run_obj = {
            "id": 42,
            "name": "Matrix Site",
            "html_url": "https://github.com/run/42",
            "head_sha": self.SHA,
        }
        older = {
            "id": 41,
            "name": "Matrix Site",
            "status": "completed",
            "conclusion": "failure",
            "head_sha": "f" * 40,
        }
        responses[self.runs_path()] = [
            {"workflow_runs": [older]},
            {
                "workflow_runs": [
                    {**run_obj, "status": "in_progress", "conclusion": None}
                ]
            },
            {
                "workflow_runs": [
                    {**run_obj, "status": "completed", "conclusion": "success"}
                ]
            },
        ]
        # a short sha must work too (GitHub's head_sha filter needs the full one)
        out = self.run_status(
            responses, "--wait-for", self.SHORT, "--interval", "0", "--timeout", "5"
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("workflow run: Matrix Site success", out.stdout)
        self.assertIn(f"live site: deployed from {self.BRANCH}", out.stdout)
        self.assertNotIn(
            "3 run the first deployment", out.stdout
        )  # already deployed by the push run

    def test_reports_the_failed_job(self):
        responses = self.base("other-branch")
        responses[self.runs_path()] = [
            {
                "workflow_runs": [
                    {
                        "id": 43,
                        "name": "Matrix Site",
                        "status": "completed",
                        "conclusion": "failure",
                        "html_url": "https://github.com/run/43",
                        "head_sha": self.SHA,
                    }
                ]
            }
        ]
        responses[f"repos/{self.REPO}/actions/runs/43/jobs"] = [
            {
                "jobs": [
                    {"name": "Validate and build", "conclusion": "success"},
                    {"name": "Deploy to GitHub Pages", "conclusion": "failure"},
                ]
            }
        ]
        out = self.run_status(
            responses, "--wait-for", self.SHA, "--interval", "0", "--timeout", "5"
        )
        self.assertIn("workflow run: Matrix Site failure", out.stdout)
        self.assertIn("failed job: Deploy to GitHub Pages", out.stdout)
        self.assertIn("3 run the first deployment", out.stdout)

    def test_gives_up_when_no_run_appears(self):
        responses = self.base(self.BRANCH)
        responses[self.runs_path()] = [{"workflow_runs": []}]
        out = self.run_status(
            responses, "--wait-for", self.SHA, "--interval", "0", "--timeout", "0"
        )
        self.assertIn("no finished workflow run for abc1234", out.stdout)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class NodeTestsTest(unittest.TestCase):
    """Runs the web model's JavaScript tests (tests/*.test.mjs) under node --test."""

    def test_node_suite(self):
        res = subprocess.run(
            ["node", "--test", HERE], check=False, capture_output=True, text=True
        )
        self.assertEqual(res.returncode, 0, res.stdout[-2000:] + res.stderr[-2000:])


@unittest.skipUnless(shutil.which("node"), "node not installed")
@unittest.skipUnless(shutil.which("google-chrome"), "google-chrome not installed")
class BrowserTest(unittest.TestCase):
    """Drives the built site in headless Chrome against a fake GitHub and compares DOM snapshots."""

    def test_feature_dom(self):
        res = subprocess.run(
            ["node", os.path.join(HERE, "browser", "run.mjs"), "feature"],
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
        self.assertEqual(res.returncode, 0, res.stdout[-3000:] + res.stderr[-2000:])

    def test_requirement_ui(self):
        res = subprocess.run(
            ["node", os.path.join(HERE, "browser", "run.mjs"), "requirement"],
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
        self.assertEqual(res.returncode, 0, res.stdout[-3000:] + res.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
