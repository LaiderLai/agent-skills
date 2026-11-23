#!/usr/bin/env python3
"""Read-only check of a repo's GitHub Pages setup, to tailor the manual steps.

    python3 github_status.py <owner/name> <deploy-branch> [--wait-for <commit sha>]

With --wait-for, first waits for the workflow run that the push of that commit
started (the first deployment usually happens there) and reports its result and
any failed job, so the status below reflects the finished deployment.

Uses `gh api` GET requests only - it never changes settings. Prints what is
already in place (Pages enabled? deploy rules for the branch and version tags?
which branch the live site currently comes from) and which of the manual steps
in references/github-setup.md are still needed. If `gh` is missing or not
authenticated, says so; then hand the user all steps.
"""

import argparse
import json
import shutil
import subprocess
import time

TAG_RULE = "matrix-table/*"


def gh(path):
    out = subprocess.run(
        ["gh", "api", path], check=False, capture_output=True, text=True
    )
    if out.returncode:
        return None, (out.stderr or out.stdout).strip()
    return json.loads(out.stdout or "null"), None


def wait_for_run(repo, branch, sha, timeout, interval):
    """Wait for the workflow run started by pushing `sha` and print its outcome."""
    deadline = time.monotonic() + timeout
    # head_sha= only matches full SHAs, so list the branch's latest runs and match by prefix.
    path = f"repos/{repo}/actions/runs?branch={branch}&per_page=20"
    while True:
        runs, _ = gh(path)
        run = next(
            (
                r
                for r in (runs or {}).get("workflow_runs", [])
                if r.get("head_sha", "").startswith(sha)
            ),
            None,
        )
        if run and run.get("status") == "completed":
            print(
                f"workflow run: {run['name']} {run['conclusion']} {run.get('html_url', '')}"
            )
            if run["conclusion"] != "success":
                jobs, _ = gh(f"repos/{repo}/actions/runs/{run['id']}/jobs")
                for job in (jobs or {}).get("jobs", []):
                    if job.get("conclusion") not in ("success", "skipped", None):
                        print(f"failed job: {job['name']}")
            return
        if time.monotonic() >= deadline:
            state = run["status"] if run else "not started"
            print(
                f"no finished workflow run for {sha[:7]} after {timeout}s ({state}) -> check Actions"
            )
            return
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("repo")
    parser.add_argument("branch")
    parser.add_argument(
        "--wait-for",
        metavar="SHA",
        help="commit just pushed; wait for its workflow run first",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="seconds to wait for the run (default 600)",
    )
    parser.add_argument(
        "--interval", type=float, default=10, help="seconds between polls (default 10)"
    )
    args = parser.parse_args()
    repo, branch = args.repo, args.branch
    if not shutil.which("gh"):
        print("gh: not installed -> cannot check; give the user all manual steps")
        return
    if subprocess.run(
        ["gh", "auth", "status"], check=False, capture_output=True
    ).returncode:
        print("gh: not authenticated -> cannot check; give the user all manual steps")
        return
    if args.wait_for:
        wait_for_run(repo, branch, args.wait_for, args.timeout, args.interval)

    steps = []
    pages, err = gh(f"repos/{repo}/pages")
    if pages is None:
        if "404" in (err or ""):
            print("Pages: not enabled")
            steps.append("1 enable Pages (Source: GitHub Actions)")
        else:
            print(f"Pages: unknown ({err[:120]}) -> give the user all manual steps")
            return
    else:
        print(
            f"Pages: enabled, source={pages.get('build_type')}, url={pages.get('html_url')}"
        )
        if pages.get("build_type") != "workflow":
            steps.append("1 switch Pages Source to GitHub Actions")

    env, env_err = gh(f"repos/{repo}/environments/github-pages")
    env_missing = env is None and "404" in (env_err or "")
    policies, _ = gh(
        f"repos/{repo}/environments/github-pages/deployment-branch-policies"
    )
    rules = {
        (p["type"], p["name"]) for p in (policies or {}).get("branch_policies", [])
    }
    if env_missing:
        print("deploy rules: github-pages environment does not exist yet")
    else:
        print(
            "deploy rules:", ", ".join(f"{t}:{n}" for t, n in sorted(rules)) or "none"
        )
    missing = [
        f"{t} rule {n}"
        for t, n in (("branch", branch), ("tag", TAG_RULE))
        if (t, n) not in rules
    ]

    live = None
    # Deployment records outlive a deleted Pages site, so only trust them while Pages is enabled.
    deployments, _ = (
        gh(f"repos/{repo}/deployments?environment=github-pages&per_page=20")
        if pages
        else (None, None)
    )
    for d in deployments or []:
        statuses, _ = gh(f"repos/{repo}/deployments/{d['id']}/statuses")
        if statuses and statuses[0].get("state") == "success":
            live = d
            break
    if live:
        print(
            f"live site: deployed from {live['ref']} @ {live['sha'][:7]} on {live['created_at']}"
        )
        if live["ref"] not in (branch, f"refs/heads/{branch}"):
            print(
                f"WARNING: a repo has ONE Pages site. Deploying {branch} will REPLACE the site now "
                f"served from {live['ref']} (same URL; whichever branch deploys last wins). "
                "Tell the user before they run step 3."
            )
    else:
        print("live site: none deployed yet")
    deploy = (
        "3 run the first deployment (Re-run the push's run, or gh workflow run --ref BRANCH; "
        "there is no Run workflow button off the default branch)"
    )
    if env_missing and pages:
        # Pages is on but its environment is gone: the first deployment recreates it
        # (unrestricted), and rules can only be added afterwards.
        steps.append(deploy + " - it creates the github-pages environment")
        steps.append("2 THEN restrict it: add " + " and ".join(missing))
    else:
        if missing:
            steps.append("2 add " + " and ".join(missing))
        if not (live and live["ref"] in (branch, f"refs/heads/{branch}")):
            steps.append(deploy)
        if env is not None and not env.get("deployment_branch_policy"):
            print(
                "WARNING: github-pages has no branch restriction - any branch can deploy until step 2 is done"
            )
    steps.append("4 editors create tokens")
    print("still needed:", "; ".join(steps))


if __name__ == "__main__":
    main()
