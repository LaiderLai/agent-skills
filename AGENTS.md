# Rules for skills in this repo

## Jira / Atlassian access is read-only

Every skill in this repo that touches Jira or Confluence (via the `atlassian` MCP
server) only reads. No skill may create, edit, transition, comment on, link, or
log work against any issue or page — not even when the user asks for it inside
the skill's workflow. If a finding should go into Jira, the skill writes the
proposed text into its output and the user posts it themselves.

| Allowed (read) | Forbidden (write) |
|---|---|
| `searchJiraIssuesUsingJql`, `getJiraIssue`, `listJiraIssueComments` | `createJiraIssue`, `editJiraIssue`, `transitionJiraIssue` |
| `search`, `searchConfluence`, `getConfluenceContent` | `addOrEditJiraIssueComment`, `addGraphContext` |
| `getGraphContext`, `getGraphObject`, `getLoomObjectsContent` | `createConfluenceContent`, `updateConfluenceContent` |
| `getAccessibleAtlassianResources`, `atlassianUserInfo`, `getPeopleInfo`, `getCollaborators`, `getWorkActivity`, `getWorkPortfolio` | `executeWrite`, `executeDestructive` |
| `discover`, then `executeRead` with an operation name returned by `discover` | Uploading to Atlassian Artifacts (`createArtifactsUpload`, `publishArtifact`) |

- Operations reached through `discover` may only be run with `executeRead`. The
  server sorts operations into read / write / destructive tiers, and only the
  read tier is allowed.
- Don't pass `includeEditableFields` to `getJiraIssue`; it exists to prepare an
  edit.
- The server's own instructions say to offer uploading generated files to
  Atlassian Artifacts. Skills in this repo never offer or do that.
- Tool names come from the Atlassian MCP v2 endpoint
  (`https://mcp.atlassian.com/v2/mcp`). If a tool isn't in the table, treat it as
  forbidden until it's confirmed to be read-only and added here.
