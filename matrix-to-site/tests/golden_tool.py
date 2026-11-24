#!/usr/bin/env python3
"""Generate or compare golden files for a CSV + mapping.

    python3 golden_tool.py --csv X --mapping Y --golden DIR [--update]
    python3 golden_tool.py --csv X --mapping Y --site-out DIR   # build only, print dist path

Golden layout: inspect.yaml, raw/*.yaml, formatted/*.yaml, data.json, verify.txt.
dom/ (browser snapshots) is ignored.
Exit 0 when identical, 1 with a unified diff otherwise.
"""

import argparse
import difflib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL / "scripts"


def sh(*args, cwd=None, env=None, ok=(0,)):
    res = subprocess.run(
        list(args), check=False, cwd=cwd, env=env, capture_output=True, text=True
    )
    if res.returncode not in ok:
        sys.exit(f"command failed: {args}\n{res.stdout}\n{res.stderr}")
    return res


def build_site(csv, mapping, workdir, raw_copy=None):
    """Scaffold a fresh repo in workdir, convert, format and build; return the dist dir."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    sh("git", "init", "-q", str(workdir))
    sh(
        sys.executable,
        str(SCRIPTS / "scaffold.py"),
        str(workdir),
        "--deploy-branch",
        "matrix-table-golden",
        "--mapping",
        str(mapping),
    )
    data = workdir / "matrix-table" / "data"
    res = sh(
        sys.executable,
        str(SCRIPTS / "convert_csv.py"),
        "--mapping",
        str(mapping),
        "--csv",
        str(csv),
        "--out",
        str(data),
        ok=(0, 1),
    )
    (workdir / "verify.txt").write_text(
        res.stdout.replace(str(data), "<data>"), encoding="utf-8"
    )
    if raw_copy:
        shutil.copytree(data, raw_copy)
    build = workdir / "matrix-table" / "tools" / "build.mjs"
    sh("node", str(build), "format")
    dist = workdir / "dist"
    sh("node", str(build), "build", str(dist))
    return dist


def generate(csv, mapping, out):
    """Write the golden file set into out (must not exist)."""
    env = {k: v for k, v in os.environ.items() if k != "MATRIX_TO_SITE_JIRA_URL"}
    out = Path(out)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "repo"
        dist = build_site(csv, mapping, work, raw_copy=out / "raw")
        (out / "inspect.yaml").write_text(
            sh(
                sys.executable, str(SCRIPTS / "inspect_csv.py"), str(csv), env=env
            ).stdout,
            encoding="utf-8",
        )
        shutil.copytree(work / "matrix-table" / "data", out / "formatted")
        data = json.loads((dist / "data.json").read_text(encoding="utf-8"))
        data.pop("generated", None)
        (out / "data.json").write_text(
            json.dumps(data, indent=1, ensure_ascii=False, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        shutil.copy2(work / "verify.txt", out / "verify.txt")


def files(root):
    root = Path(root)
    return {
        str(p.relative_to(root)): p.read_text(encoding="utf-8")
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.relative_to(root).parts[0] != "dom"
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--mapping", required=True)
    ap.add_argument("--golden")
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--site-out", help="build only; print the dist path")
    args = ap.parse_args()
    if args.site_out:
        print(build_site(args.csv, args.mapping, args.site_out))
        return 0
    if not args.golden:
        ap.error("--golden is required")
    golden = Path(args.golden)
    if args.update:
        # dom/ belongs to the browser tests (tests/browser/run.mjs --update); keep it
        keep = Path(tempfile.mkdtemp()) / "dom"
        if (golden / "dom").exists():
            shutil.move(golden / "dom", keep)
        shutil.rmtree(golden, ignore_errors=True)
        golden.parent.mkdir(parents=True, exist_ok=True)
        generate(args.csv, args.mapping, golden)
        if keep.exists():
            shutil.move(keep, golden / "dom")
        shutil.rmtree(keep.parent, ignore_errors=True)
        print(f"updated {golden}")
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        generate(args.csv, args.mapping, Path(tmp) / "out")
        new = files(Path(tmp) / "out")
    old = files(golden) if golden.exists() else {}
    bad = False
    for name in sorted(set(old) | set(new)):
        if old.get(name) != new.get(name):
            bad = True
            sys.stdout.writelines(
                difflib.unified_diff(
                    (old.get(name) or "").splitlines(True),
                    (new.get(name) or "").splitlines(True),
                    f"golden/{name}",
                    f"generated/{name}",
                )
            )
            print()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
