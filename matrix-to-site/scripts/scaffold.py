#!/usr/bin/env python3
"""Install the feature-matrix site (web UI, tools, CI workflow) into a git repo.

    python3 scaffold.py <repo> --deploy-branch <branch> --mapping <mapping.yaml> [--force]

Copies the bundled assets into <repo>/feature-matrix/ and the GitHub Actions
workflow into <repo>/.github/workflows/matrix-site.yml, with the deploy
branch filled in. The data itself comes from convert_csv.py. Refuses to
overwrite an existing feature-matrix/ (or workflow) unless --force is given.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
ASSETS = SKILL / "assets"


def default_branch(repo):
    """The remote's default branch (origin/HEAD), or None when it cannot be determined."""
    for args in (
        ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
        ["remote", "show", "origin"],
    ):
        out = subprocess.run(
            ["git", "-C", str(repo), *args], check=False, capture_output=True, text=True
        )
        if out.returncode:
            continue
        if args[0] == "symbolic-ref":
            return out.stdout.strip().removeprefix("origin/")
        for line in out.stdout.splitlines():
            if "HEAD branch:" in line:
                return line.split(":", 1)[1].strip()
    return None


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("repo", type=Path)
    parser.add_argument(
        "--deploy-branch",
        required=True,
        help="branch the site is built and deployed from",
    )
    parser.add_argument(
        "--mapping",
        type=Path,
        help="mapping used for the import; saved as tools/mapping.yaml",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing installation (keeps data/)",
    )
    args = parser.parse_args()

    repo = args.repo.resolve()
    if not (repo / ".git").exists():
        sys.exit(f"error: {repo} is not a git repository")
    default = default_branch(repo)
    if default is None:
        print(
            "warning: could not determine the remote default branch; only main/master are blocked",
            file=sys.stderr,
        )
    protected = {"main", "master", default} - {None}
    if args.deploy_branch in protected:
        sys.exit(
            f"error: refusing to deploy from {args.deploy_branch!r} (main, master and the default branch "
            "are not allowed); use a dedicated branch such as feature-matrix-<project>"
        )
    target = repo / "feature-matrix"
    workflow = repo / ".github" / "workflows" / "matrix-site.yml"
    # Older installs used feature-matrix.yml; GitHub keys workflows by path, so keep only one.
    legacy = repo / ".github" / "workflows" / "feature-matrix.yml"
    existing = [
        p for p in (target / "web", target / "tools", workflow, legacy) if p.exists()
    ]
    if existing and not args.force:
        sys.exit(
            "error: already installed ("
            + ", ".join(str(p.relative_to(repo)) for p in existing)
            + "); use --force"
        )

    target.mkdir(parents=True, exist_ok=True)
    for name in ("web", "tools"):
        shutil.rmtree(target / name, ignore_errors=True)
        shutil.copytree(ASSETS / name, target / name)
    shutil.copy2(
        SKILL / "scripts" / "convert_csv.py", target / "tools" / "convert_csv.py"
    )
    if args.mapping:
        shutil.copy2(args.mapping, target / "tools" / "mapping.yaml")
    shutil.copy2(ASSETS / "package.json", target / "package.json")
    if not (target / "README.md").exists() or args.force:
        shutil.copy2(ASSETS / "README.md", target / "README.md")

    workflow.parent.mkdir(parents=True, exist_ok=True)
    if legacy.exists():
        legacy.unlink()
        print(
            f"removed old workflow {legacy.relative_to(repo)} (replaced by {workflow.name})"
        )
    text = (ASSETS / "matrix-site.workflow.yml").read_text(encoding="utf-8")
    workflow.write_text(
        text.replace("__DEPLOY_BRANCH__", args.deploy_branch), encoding="utf-8"
    )

    gitignore = repo / ".gitignore"
    line = "feature-matrix/dist/"
    current = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if line not in current.splitlines():
        sep = "" if not current or current.endswith("\n") else "\n"
        gitignore.write_text(
            f"{current}{sep}\n# Feature matrix build output\n{line}\n", encoding="utf-8"
        )

    print(f"installed feature-matrix into {target}")
    print(f"workflow: {workflow.relative_to(repo)} (deploys {args.deploy_branch})")
    if not (target / "data" / "_meta.yaml").exists():
        print("next: run convert_csv.py --out", target / "data")


if __name__ == "__main__":
    main()
