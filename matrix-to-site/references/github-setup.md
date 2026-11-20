# GitHub setup the user does by hand

The skill never changes repository settings. After pushing, run
`python3 scripts/github_status.py OWNER/REPO BRANCH` (read-only) and give the user
only the steps it reports as still needed, filled in with their repo (`OWNER/REPO`)
and deploy branch (`BRANCH`). All of them need **admin** on the repo.

**One Pages site per repo.** If the repo already serves a site from another branch,
deploying `BRANCH` replaces it at the same URL; whichever branch deploys last wins.

## 1. Enable GitHub Pages

Settings → Pages → Build and deployment → **Source: GitHub Actions**.
For a private repo also set visibility to **Private** (only people with read
access can open the site). Pages for private repos needs a paid plan (Pro/Team/
Enterprise), but **only GitHub Enterprise Cloud can make the site itself private**.
On Pro/Team the site is public to anyone with the URL even though the repo is
private — if the "Private" visibility option is missing, stop and check with the
team before publishing internal feature data. The site URL appears on the same page after the
first deployment.

## 2. Allow the deploy branch and version tags

Enabling Pages creates the `github-pages` environment, which by default only
deploys from the default branch. If the environment does not exist (e.g. it was
deleted), there is nothing to add rules to yet: do step 3 first — that run creates
the environment — then come back and add the rules.

Settings → Environments → **github-pages** → Deployment branches and tags → add:

- branch rule `BRANCH` (always needed: the site never deploys from the default branch)
- tag rule `matrix-table/*` (so creating a version redeploys the snapshot)

## 3. Run the first deployment

The **Run workflow** button only appears for workflows that exist on the default
branch, and this workflow lives only on `BRANCH`, so use one of these instead:

- **Re-run**: Actions → **Matrix Site** → open the latest run on `BRANCH` (the push
  already triggered one; it fails at "Deploy" until steps 1–2 are done) →
  **Re-run all jobs**.
- **CLI**: `gh workflow run matrix-site.yml -R OWNER/REPO --ref BRANCH` (works once
  the workflow has run at least once, which the push did).
- **Push** any commit to `BRANCH`; every push runs the workflow.

If the `github-pages` environment did not exist, this first run creates it with no
restrictions — do step 2's rules right after it.

## 4. Token for editing (each editor, once)

GitHub → Settings → Developer settings → **Fine-grained tokens** → Generate:

- Resource owner: `OWNER`; Repository access: only `REPO`
- Permissions → Repository → **Contents: Read and write**
- Organisations may require admin approval or SSO authorisation for the token.

Open the site → **Sign in to edit** → paste the token (stored only in that browser).

## Equivalent gh commands (for users who prefer the CLI)

```sh
gh api -X POST repos/OWNER/REPO/pages -f build_type=workflow
gh api -X POST repos/OWNER/REPO/environments/github-pages/deployment-branch-policies -f name=BRANCH -f type=branch
gh api -X POST repos/OWNER/REPO/environments/github-pages/deployment-branch-policies -f name='matrix-table/*' -f type=tag
gh workflow run matrix-site.yml -R OWNER/REPO --ref BRANCH
```

## Keeping main clean

The site lives on its own branch so web edits never commit to `main`. If the team
later wants the files on `main` too, merge `BRANCH` through a normal PR; the site
keeps deploying from `BRANCH`, and edits keep landing there.
