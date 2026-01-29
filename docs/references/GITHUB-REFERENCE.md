# GitHub API & CLI Reference

This document provides a comprehensive reference for GitHub features accessible via the `gh` CLI and REST/GraphQL APIs. This serves as a planning reference for potential NEXUS3 GitHub tool integration.

---

## Overview

GitHub provides two primary programmatic interfaces:
- **`gh` CLI** - Official command-line tool with 30+ command groups and 200+ subcommands
- **REST API** - Traditional HTTP endpoints for most operations
- **GraphQL API** - Required for Projects v2, Discussions, and some advanced features

**Authentication:**
- Personal Access Tokens (classic or fine-grained)
- GitHub Apps (installation tokens)
- OAuth Apps
- CLI: `gh auth login` with scopes like `repo`, `project`, `read:org`

---

## Code Collaboration

### Pull Requests

Full lifecycle management for code review workflows.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List PRs | `gh pr list` | `GET /repos/{owner}/{repo}/pulls` |
| View PR | `gh pr view {number}` | `GET /repos/{owner}/{repo}/pulls/{pull_number}` |
| Create PR | `gh pr create` | `POST /repos/{owner}/{repo}/pulls` |
| Edit PR | `gh pr edit {number}` | `PATCH /repos/{owner}/{repo}/pulls/{pull_number}` |
| Close PR | `gh pr close {number}` | `PATCH /repos/{owner}/{repo}/pulls/{pull_number}` |
| Reopen PR | `gh pr reopen {number}` | `PATCH /repos/{owner}/{repo}/pulls/{pull_number}` |
| Merge PR | `gh pr merge {number}` | `PUT /repos/{owner}/{repo}/pulls/{pull_number}/merge` |
| Checkout PR | `gh pr checkout {number}` | N/A (local git operation) |
| View diff | `gh pr diff {number}` | `GET /repos/{owner}/{repo}/pulls/{pull_number}` with `Accept: application/vnd.github.v3.diff` |
| View checks | `gh pr checks {number}` | `GET /repos/{owner}/{repo}/commits/{ref}/check-runs` |
| Mark ready | `gh pr ready {number}` | GraphQL: `markPullRequestReadyForReview` |
| Convert to draft | N/A | GraphQL: `convertPullRequestToDraft` |
| Update branch | `gh pr update-branch` | `PUT /repos/{owner}/{repo}/pulls/{pull_number}/update-branch` |
| Revert PR | `gh pr revert {number}` | Creates new PR reverting changes |
| Lock/Unlock | `gh pr lock/unlock` | `PUT /repos/{owner}/{repo}/issues/{issue_number}/lock` |

**PR Comments:**
| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| Add comment | `gh pr comment {number}` | `POST /repos/{owner}/{repo}/issues/{issue_number}/comments` |
| List comments | N/A | `GET /repos/{owner}/{repo}/issues/{issue_number}/comments` |

### Pull Request Reviews

Code review with approval workflow.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| Submit review | `gh pr review {number}` | `POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews` |
| List reviews | N/A | `GET /repos/{owner}/{repo}/pulls/{pull_number}/reviews` |
| Get review | N/A | `GET /repos/{owner}/{repo}/pulls/{pull_number}/reviews/{review_id}` |
| Dismiss review | N/A | `PUT /repos/{owner}/{repo}/pulls/{pull_number}/reviews/{review_id}/dismissals` |
| List review comments | N/A | `GET /repos/{owner}/{repo}/pulls/{pull_number}/comments` |
| Create review comment | N/A | `POST /repos/{owner}/{repo}/pulls/{pull_number}/comments` |
| Reply to comment | N/A | `POST /repos/{owner}/{repo}/pulls/{pull_number}/comments/{comment_id}/replies` |

**Review states:** `APPROVE`, `REQUEST_CHANGES`, `COMMENT`, `PENDING`

**Inline suggestions:** Use markdown code blocks with `suggestion` language tag in review comments.

### Issues

Issue tracking with full metadata support.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List issues | `gh issue list` | `GET /repos/{owner}/{repo}/issues` |
| View issue | `gh issue view {number}` | `GET /repos/{owner}/{repo}/issues/{issue_number}` |
| Create issue | `gh issue create` | `POST /repos/{owner}/{repo}/issues` |
| Edit issue | `gh issue edit {number}` | `PATCH /repos/{owner}/{repo}/issues/{issue_number}` |
| Close issue | `gh issue close {number}` | `PATCH /repos/{owner}/{repo}/issues/{issue_number}` |
| Reopen issue | `gh issue reopen {number}` | `PATCH /repos/{owner}/{repo}/issues/{issue_number}` |
| Delete issue | `gh issue delete {number}` | `DELETE /repos/{owner}/{repo}/issues/{issue_number}` |
| Transfer issue | `gh issue transfer {number} {repo}` | `POST /repos/{owner}/{repo}/issues/{issue_number}/transfer` |
| Pin/Unpin | `gh issue pin/unpin {number}` | GraphQL mutations |
| Lock/Unlock | `gh issue lock/unlock {number}` | `PUT /repos/{owner}/{repo}/issues/{issue_number}/lock` |
| Comment | `gh issue comment {number}` | `POST /repos/{owner}/{repo}/issues/{issue_number}/comments` |
| Develop (create branch) | `gh issue develop {number}` | Creates linked branch |
| View status | `gh issue status` | Shows issues assigned/mentioned/created by you |

**Issue metadata:**
- Assignees: `PATCH /repos/{owner}/{repo}/issues/{issue_number}` with `assignees` array
- Labels: `POST /repos/{owner}/{repo}/issues/{issue_number}/labels`
- Milestone: `PATCH /repos/{owner}/{repo}/issues/{issue_number}` with `milestone`
- Projects: GraphQL API

### Sub-Issues (Beta)

Hierarchical issue relationships.

| Operation | API Endpoint |
|-----------|--------------|
| List sub-issues | `GET /repos/{owner}/{repo}/issues/{issue_number}/sub_issues` |
| Add sub-issue | `POST /repos/{owner}/{repo}/issues/{issue_number}/sub_issues` |
| Remove sub-issue | `DELETE /repos/{owner}/{repo}/issues/{issue_number}/sub_issues/{sub_issue_id}` |
| Reprioritize | `PATCH /repos/{owner}/{repo}/issues/{issue_number}/sub_issues/priority` |

### Labels

Organize issues and PRs with labels.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List labels | `gh label list` | `GET /repos/{owner}/{repo}/labels` |
| Create label | `gh label create {name}` | `POST /repos/{owner}/{repo}/labels` |
| Edit label | `gh label edit {name}` | `PATCH /repos/{owner}/{repo}/labels/{name}` |
| Delete label | `gh label delete {name}` | `DELETE /repos/{owner}/{repo}/labels/{name}` |
| Clone labels | `gh label clone {repo}` | Copies labels from another repo |

### Milestones

Time-based issue grouping.

| Operation | API Endpoint |
|-----------|--------------|
| List milestones | `GET /repos/{owner}/{repo}/milestones` |
| Get milestone | `GET /repos/{owner}/{repo}/milestones/{milestone_number}` |
| Create milestone | `POST /repos/{owner}/{repo}/milestones` |
| Update milestone | `PATCH /repos/{owner}/{repo}/milestones/{milestone_number}` |
| Delete milestone | `DELETE /repos/{owner}/{repo}/milestones/{milestone_number}` |
| List milestone labels | `GET /repos/{owner}/{repo}/milestones/{milestone_number}/labels` |

### Discussions (GraphQL Only)

Community forum feature for Q&A and announcements.

| Operation | GraphQL |
|-----------|---------|
| List discussions | `repository.discussions` query |
| Get discussion | `repository.discussion(number)` query |
| Create discussion | `createDiscussion` mutation |
| Update discussion | `updateDiscussion` mutation |
| Delete discussion | `deleteDiscussion` mutation |
| Add comment | `addDiscussionComment` mutation |
| Mark as answer | `markDiscussionCommentAsAnswer` mutation |
| Upvote | `addUpvote` mutation |
| List categories | `repository.discussionCategories` query |

**Discussion features:**
- Categories (Announcements, Q&A, Ideas, etc.)
- Pinned discussions
- Polls
- Upvoting
- Answer marking (Q&A category)

### Gists

Share code snippets and notes.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List gists | `gh gist list` | `GET /gists` |
| View gist | `gh gist view {id}` | `GET /gists/{gist_id}` |
| Create gist | `gh gist create {files}` | `POST /gists` |
| Edit gist | `gh gist edit {id}` | `PATCH /gists/{gist_id}` |
| Delete gist | `gh gist delete {id}` | `DELETE /gists/{gist_id}` |
| Clone gist | `gh gist clone {id}` | N/A (git clone) |
| Rename gist | `gh gist rename {id} {old} {new}` | `PATCH /gists/{gist_id}` |

---

## Project Management

### Projects v2 (GraphQL Only)

Flexible project boards with custom fields, views, and automation.

| Operation | CLI Command | GraphQL |
|-----------|-------------|---------|
| List projects | `gh project list` | `user.projectsV2` or `organization.projectsV2` |
| View project | `gh project view {number}` | `node(id)` query |
| Create project | `gh project create` | `createProjectV2` mutation |
| Edit project | `gh project edit` | `updateProjectV2` mutation |
| Delete project | `gh project delete` | `deleteProjectV2` mutation |
| Close project | `gh project close` | `updateProjectV2` with `closed: true` |
| Copy project | `gh project copy` | `copyProjectV2` mutation |
| Mark as template | `gh project mark-template` | `updateProjectV2` mutation |
| Link to repo | `gh project link` | `linkProjectV2ToRepository` mutation |
| Unlink from repo | `gh project unlink` | `unlinkProjectV2FromRepository` mutation |

**Project Items:**
| Operation | CLI Command | GraphQL |
|-----------|-------------|---------|
| List items | `gh project item-list` | `projectV2.items` query |
| Add item | `gh project item-add` | `addProjectV2ItemById` mutation |
| Create draft | `gh project item-create` | `addProjectV2DraftIssue` mutation |
| Edit item | `gh project item-edit` | `updateProjectV2ItemFieldValue` mutation |
| Archive item | `gh project item-archive` | `archiveProjectV2Item` mutation |
| Delete item | `gh project item-delete` | `deleteProjectV2Item` mutation |

**Project Fields:**
| Operation | CLI Command | GraphQL |
|-----------|-------------|---------|
| List fields | `gh project field-list` | `projectV2.fields` query |
| Create field | `gh project field-create` | `createProjectV2Field` mutation |
| Delete field | `gh project field-delete` | `deleteProjectV2Field` mutation |

**Field types:** Text, Number, Date, Single select, Iteration, Tracks/Tracked by

**Views:** TABLE, BOARD, ROADMAP (created via `createProjectV2View` mutation)

**Note:** Status field (board columns) cannot be managed via API - must be configured in UI.

---

## CI/CD & Automation

### GitHub Actions - Workflow Runs

Monitor and control workflow executions.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List runs | `gh run list` | `GET /repos/{owner}/{repo}/actions/runs` |
| View run | `gh run view {run_id}` | `GET /repos/{owner}/{repo}/actions/runs/{run_id}` |
| Watch run | `gh run watch {run_id}` | Polls run status |
| Rerun run | `gh run rerun {run_id}` | `POST /repos/{owner}/{repo}/actions/runs/{run_id}/rerun` |
| Rerun failed | `gh run rerun {run_id} --failed` | `POST /repos/{owner}/{repo}/actions/runs/{run_id}/rerun-failed-jobs` |
| Cancel run | `gh run cancel {run_id}` | `POST /repos/{owner}/{repo}/actions/runs/{run_id}/cancel` |
| Delete run | `gh run delete {run_id}` | `DELETE /repos/{owner}/{repo}/actions/runs/{run_id}` |
| Download artifacts | `gh run download {run_id}` | `GET /repos/{owner}/{repo}/actions/runs/{run_id}/artifacts` |
| View logs | `gh run view {run_id} --log` | `GET /repos/{owner}/{repo}/actions/runs/{run_id}/logs` |

### GitHub Actions - Workflows

Manage workflow definitions.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List workflows | `gh workflow list` | `GET /repos/{owner}/{repo}/actions/workflows` |
| View workflow | `gh workflow view {id}` | `GET /repos/{owner}/{repo}/actions/workflows/{workflow_id}` |
| Run workflow | `gh workflow run {id}` | `POST /repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches` |
| Enable workflow | `gh workflow enable {id}` | `PUT /repos/{owner}/{repo}/actions/workflows/{workflow_id}/enable` |
| Disable workflow | `gh workflow disable {id}` | `PUT /repos/{owner}/{repo}/actions/workflows/{workflow_id}/disable` |

### GitHub Actions - Jobs

Individual job management within runs.

| Operation | API Endpoint |
|-----------|--------------|
| List jobs for run | `GET /repos/{owner}/{repo}/actions/runs/{run_id}/jobs` |
| Get job | `GET /repos/{owner}/{repo}/actions/jobs/{job_id}` |
| Download job logs | `GET /repos/{owner}/{repo}/actions/jobs/{job_id}/logs` |
| Rerun job | `POST /repos/{owner}/{repo}/actions/jobs/{job_id}/rerun` |

### Secrets

Encrypted secrets for workflows.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List secrets | `gh secret list` | `GET /repos/{owner}/{repo}/actions/secrets` |
| Set secret | `gh secret set {name}` | `PUT /repos/{owner}/{repo}/actions/secrets/{secret_name}` |
| Delete secret | `gh secret delete {name}` | `DELETE /repos/{owner}/{repo}/actions/secrets/{secret_name}` |

**Scopes:** Repository, Environment, Organization (with `--org` flag)

### Variables

Plaintext configuration variables.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List variables | `gh variable list` | `GET /repos/{owner}/{repo}/actions/variables` |
| Get variable | `gh variable get {name}` | `GET /repos/{owner}/{repo}/actions/variables/{name}` |
| Set variable | `gh variable set {name}` | `POST /repos/{owner}/{repo}/actions/variables` |
| Delete variable | `gh variable delete {name}` | `DELETE /repos/{owner}/{repo}/actions/variables/{name}` |

### Cache

Actions cache management.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List caches | `gh cache list` | `GET /repos/{owner}/{repo}/actions/caches` |
| Delete cache | `gh cache delete {key}` | `DELETE /repos/{owner}/{repo}/actions/caches/{cache_id}` |
| Delete by key | `gh cache delete --all` | `DELETE /repos/{owner}/{repo}/actions/caches?key={key}` |

### Deployments

Track deployments to environments.

| Operation | API Endpoint |
|-----------|--------------|
| List deployments | `GET /repos/{owner}/{repo}/deployments` |
| Create deployment | `POST /repos/{owner}/{repo}/deployments` |
| Get deployment | `GET /repos/{owner}/{repo}/deployments/{deployment_id}` |
| Delete deployment | `DELETE /repos/{owner}/{repo}/deployments/{deployment_id}` |
| List statuses | `GET /repos/{owner}/{repo}/deployments/{deployment_id}/statuses` |
| Create status | `POST /repos/{owner}/{repo}/deployments/{deployment_id}/statuses` |

**Environments:**
| Operation | API Endpoint |
|-----------|--------------|
| List environments | `GET /repos/{owner}/{repo}/environments` |
| Get environment | `GET /repos/{owner}/{repo}/environments/{environment_name}` |
| Create/Update environment | `PUT /repos/{owner}/{repo}/environments/{environment_name}` |
| Delete environment | `DELETE /repos/{owner}/{repo}/environments/{environment_name}` |

### Checks

Status checks for commits (used by CI systems).

| Operation | API Endpoint |
|-----------|--------------|
| Create check run | `POST /repos/{owner}/{repo}/check-runs` |
| Update check run | `PATCH /repos/{owner}/{repo}/check-runs/{check_run_id}` |
| Get check run | `GET /repos/{owner}/{repo}/check-runs/{check_run_id}` |
| List check runs | `GET /repos/{owner}/{repo}/commits/{ref}/check-runs` |
| List check suites | `GET /repos/{owner}/{repo}/commits/{ref}/check-suites` |
| Rerequest check suite | `POST /repos/{owner}/{repo}/check-suites/{check_suite_id}/rerequest` |

---

## Releases & Packages

### Releases

Version releases with assets.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List releases | `gh release list` | `GET /repos/{owner}/{repo}/releases` |
| View release | `gh release view {tag}` | `GET /repos/{owner}/{repo}/releases/tags/{tag}` |
| Create release | `gh release create {tag}` | `POST /repos/{owner}/{repo}/releases` |
| Edit release | `gh release edit {tag}` | `PATCH /repos/{owner}/{repo}/releases/{release_id}` |
| Delete release | `gh release delete {tag}` | `DELETE /repos/{owner}/{repo}/releases/{release_id}` |
| Download assets | `gh release download {tag}` | `GET /repos/{owner}/{repo}/releases/{release_id}/assets` |
| Upload asset | `gh release upload {tag} {files}` | `POST /repos/{owner}/{repo}/releases/{release_id}/assets` |
| Delete asset | `gh release delete-asset {tag} {asset}` | `DELETE /repos/{owner}/{repo}/releases/assets/{asset_id}` |
| Verify release | `gh release verify {tag}` | Verify release attestations |

### Attestations

Software supply chain security.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| Download attestation | `gh attestation download` | `GET /repos/{owner}/{repo}/attestations/{subject_digest}` |
| Verify attestation | `gh attestation verify` | Local verification |
| Get trusted root | `gh attestation trusted-root` | Get Sigstore trusted root |

### Packages

Package registry management (npm, Docker, Maven, NuGet, RubyGems, Gradle).

| Operation | API Endpoint |
|-----------|--------------|
| List packages | `GET /users/{username}/packages` or `GET /orgs/{org}/packages` |
| Get package | `GET /users/{username}/packages/{package_type}/{package_name}` |
| Delete package | `DELETE /users/{username}/packages/{package_type}/{package_name}` |
| Restore package | `POST /users/{username}/packages/{package_type}/{package_name}/restore` |
| List versions | `GET /users/{username}/packages/{package_type}/{package_name}/versions` |
| Get version | `GET /users/{username}/packages/{package_type}/{package_name}/versions/{package_version_id}` |
| Delete version | `DELETE /users/{username}/packages/{package_type}/{package_name}/versions/{package_version_id}` |

---

## Repository Management

### Repositories

Core repository operations.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List repos | `gh repo list` | `GET /users/{username}/repos` or `GET /orgs/{org}/repos` |
| View repo | `gh repo view` | `GET /repos/{owner}/{repo}` |
| Create repo | `gh repo create` | `POST /user/repos` or `POST /orgs/{org}/repos` |
| Edit repo | `gh repo edit` | `PATCH /repos/{owner}/{repo}` |
| Delete repo | `gh repo delete` | `DELETE /repos/{owner}/{repo}` |
| Clone repo | `gh repo clone {repo}` | N/A (git clone) |
| Fork repo | `gh repo fork` | `POST /repos/{owner}/{repo}/forks` |
| Sync fork | `gh repo sync` | `POST /repos/{owner}/{repo}/merge-upstream` |
| Archive repo | `gh repo archive` | `PATCH /repos/{owner}/{repo}` with `archived: true` |
| Unarchive repo | `gh repo unarchive` | `PATCH /repos/{owner}/{repo}` with `archived: false` |
| Rename repo | `gh repo rename {new-name}` | `PATCH /repos/{owner}/{repo}` with `name` |
| Set default | `gh repo set-default` | Sets default repo for current directory |

### Repository Contents

File and directory operations via API.

| Operation | API Endpoint |
|-----------|--------------|
| Get contents | `GET /repos/{owner}/{repo}/contents/{path}` |
| Create/Update file | `PUT /repos/{owner}/{repo}/contents/{path}` |
| Delete file | `DELETE /repos/{owner}/{repo}/contents/{path}` |
| Get README | `GET /repos/{owner}/{repo}/readme` |
| Download archive | `GET /repos/{owner}/{repo}/zipball/{ref}` or `tarball` |

### Branches

Branch management.

| Operation | API Endpoint |
|-----------|--------------|
| List branches | `GET /repos/{owner}/{repo}/branches` |
| Get branch | `GET /repos/{owner}/{repo}/branches/{branch}` |
| Rename branch | `POST /repos/{owner}/{repo}/branches/{branch}/rename` |
| Sync branch with upstream | `POST /repos/{owner}/{repo}/merge-upstream` |

### Branch Protection

Protect branches with rules.

| Operation | API Endpoint |
|-----------|--------------|
| Get protection | `GET /repos/{owner}/{repo}/branches/{branch}/protection` |
| Update protection | `PUT /repos/{owner}/{repo}/branches/{branch}/protection` |
| Delete protection | `DELETE /repos/{owner}/{repo}/branches/{branch}/protection` |
| Get status checks | `GET /repos/{owner}/{repo}/branches/{branch}/protection/required_status_checks` |
| Get PR reviews | `GET /repos/{owner}/{repo}/branches/{branch}/protection/required_pull_request_reviews` |

### Rulesets

Repository rules (newer, more flexible than branch protection).

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List rulesets | `gh ruleset list` | `GET /repos/{owner}/{repo}/rulesets` |
| View ruleset | `gh ruleset view {id}` | `GET /repos/{owner}/{repo}/rulesets/{ruleset_id}` |
| Check rules | `gh ruleset check` | `GET /repos/{owner}/{repo}/rules/branches/{branch}` |

### Deploy Keys

Read-only or read-write SSH keys for CI/CD.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List keys | `gh repo deploy-key list` | `GET /repos/{owner}/{repo}/keys` |
| Add key | `gh repo deploy-key add` | `POST /repos/{owner}/{repo}/keys` |
| Delete key | `gh repo deploy-key delete` | `DELETE /repos/{owner}/{repo}/keys/{key_id}` |

### Webhooks

Repository event notifications.

| Operation | API Endpoint |
|-----------|--------------|
| List webhooks | `GET /repos/{owner}/{repo}/hooks` |
| Create webhook | `POST /repos/{owner}/{repo}/hooks` |
| Get webhook | `GET /repos/{owner}/{repo}/hooks/{hook_id}` |
| Update webhook | `PATCH /repos/{owner}/{repo}/hooks/{hook_id}` |
| Delete webhook | `DELETE /repos/{owner}/{repo}/hooks/{hook_id}` |
| Ping webhook | `POST /repos/{owner}/{repo}/hooks/{hook_id}/pings` |
| Test webhook | `POST /repos/{owner}/{repo}/hooks/{hook_id}/tests` |
| List deliveries | `GET /repos/{owner}/{repo}/hooks/{hook_id}/deliveries` |
| Redeliver | `POST /repos/{owner}/{repo}/hooks/{hook_id}/deliveries/{delivery_id}/attempts` |

### Autolinks

Automatic linking of external references.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List autolinks | `gh repo autolink list` | `GET /repos/{owner}/{repo}/autolinks` |
| Create autolink | `gh repo autolink create` | `POST /repos/{owner}/{repo}/autolinks` |
| Get autolink | N/A | `GET /repos/{owner}/{repo}/autolinks/{autolink_id}` |
| Delete autolink | `gh repo autolink delete` | `DELETE /repos/{owner}/{repo}/autolinks/{autolink_id}` |

---

## Security

### Code Scanning

Static analysis alerts.

| Operation | API Endpoint |
|-----------|--------------|
| List alerts | `GET /repos/{owner}/{repo}/code-scanning/alerts` |
| Get alert | `GET /repos/{owner}/{repo}/code-scanning/alerts/{alert_number}` |
| Update alert | `PATCH /repos/{owner}/{repo}/code-scanning/alerts/{alert_number}` |
| List analyses | `GET /repos/{owner}/{repo}/code-scanning/analyses` |
| Get analysis | `GET /repos/{owner}/{repo}/code-scanning/analyses/{analysis_id}` |
| Delete analysis | `DELETE /repos/{owner}/{repo}/code-scanning/analyses/{analysis_id}` |
| Upload SARIF | `POST /repos/{owner}/{repo}/code-scanning/sarifs` |

### Secret Scanning

Detect exposed secrets.

| Operation | API Endpoint |
|-----------|--------------|
| List alerts | `GET /repos/{owner}/{repo}/secret-scanning/alerts` |
| Get alert | `GET /repos/{owner}/{repo}/secret-scanning/alerts/{alert_number}` |
| Update alert | `PATCH /repos/{owner}/{repo}/secret-scanning/alerts/{alert_number}` |
| List locations | `GET /repos/{owner}/{repo}/secret-scanning/alerts/{alert_number}/locations` |

### Dependabot

Dependency vulnerability alerts and updates.

| Operation | API Endpoint |
|-----------|--------------|
| List alerts | `GET /repos/{owner}/{repo}/dependabot/alerts` |
| Get alert | `GET /repos/{owner}/{repo}/dependabot/alerts/{alert_number}` |
| Update alert | `PATCH /repos/{owner}/{repo}/dependabot/alerts/{alert_number}` |
| List secrets | `GET /repos/{owner}/{repo}/dependabot/secrets` |
| Set secret | `PUT /repos/{owner}/{repo}/dependabot/secrets/{secret_name}` |

### Security Advisories

CVE and vulnerability management.

| Operation | API Endpoint |
|-----------|--------------|
| List global advisories | `GET /advisories` |
| Get global advisory | `GET /advisories/{ghsa_id}` |
| List repo advisories | `GET /repos/{owner}/{repo}/security-advisories` |
| Create repo advisory | `POST /repos/{owner}/{repo}/security-advisories` |
| Update repo advisory | `PATCH /repos/{owner}/{repo}/security-advisories/{ghsa_id}` |
| Request CVE | `POST /repos/{owner}/{repo}/security-advisories/{ghsa_id}/cve` |

### Dependency Graph

Software Bill of Materials (SBOM) and dependency review.

| Operation | API Endpoint |
|-----------|--------------|
| Get SBOM | `GET /repos/{owner}/{repo}/dependency-graph/sbom` |
| Create snapshot | `POST /repos/{owner}/{repo}/dependency-graph/snapshots` |
| Get diff | `GET /repos/{owner}/{repo}/dependency-graph/compare/{basehead}` |

---

## Organizations & Teams

### Organizations

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List orgs | `gh org list` | `GET /user/orgs` |
| Get org | N/A | `GET /orgs/{org}` |
| Update org | N/A | `PATCH /orgs/{org}` |
| List members | N/A | `GET /orgs/{org}/members` |
| Check membership | N/A | `GET /orgs/{org}/members/{username}` |
| Remove member | N/A | `DELETE /orgs/{org}/members/{username}` |
| List outside collaborators | N/A | `GET /orgs/{org}/outside_collaborators` |

### Teams

| Operation | API Endpoint |
|-----------|--------------|
| List teams | `GET /orgs/{org}/teams` |
| Create team | `POST /orgs/{org}/teams` |
| Get team | `GET /orgs/{org}/teams/{team_slug}` |
| Update team | `PATCH /orgs/{org}/teams/{team_slug}` |
| Delete team | `DELETE /orgs/{org}/teams/{team_slug}` |
| List members | `GET /orgs/{org}/teams/{team_slug}/members` |
| Add member | `PUT /orgs/{org}/teams/{team_slug}/memberships/{username}` |
| Remove member | `DELETE /orgs/{org}/teams/{team_slug}/memberships/{username}` |
| List repos | `GET /orgs/{org}/teams/{team_slug}/repos` |
| Add repo | `PUT /orgs/{org}/teams/{team_slug}/repos/{owner}/{repo}` |

---

## Search

### Search API

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| Search code | `gh search code {query}` | `GET /search/code` |
| Search commits | `gh search commits {query}` | `GET /search/commits` |
| Search issues | `gh search issues {query}` | `GET /search/issues` |
| Search PRs | `gh search prs {query}` | `GET /search/issues` with `is:pr` |
| Search repos | `gh search repos {query}` | `GET /search/repositories` |
| Search users | N/A | `GET /search/users` |
| Search topics | N/A | `GET /search/topics` |

**Query qualifiers:** `repo:`, `user:`, `org:`, `language:`, `path:`, `filename:`, `extension:`, `is:`, `in:`, `created:`, `updated:`, etc.

---

## Codespaces

Cloud development environments.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List codespaces | `gh codespace list` | `GET /user/codespaces` |
| Create codespace | `gh codespace create` | `POST /user/codespaces` |
| View codespace | `gh codespace view` | `GET /user/codespaces/{codespace_name}` |
| Delete codespace | `gh codespace delete` | `DELETE /user/codespaces/{codespace_name}` |
| Start codespace | N/A | `POST /user/codespaces/{codespace_name}/start` |
| Stop codespace | `gh codespace stop` | `POST /user/codespaces/{codespace_name}/stop` |
| SSH to codespace | `gh codespace ssh` | Opens SSH connection |
| Open in VS Code | `gh codespace code` | Opens in VS Code |
| Copy files | `gh codespace cp` | SCP to/from codespace |
| Forward ports | `gh codespace ports forward` | Port forwarding |
| View logs | `gh codespace logs` | Creation logs |
| Rebuild | `gh codespace rebuild` | Rebuild container |

---

## User Management

### Authentication

| Operation | CLI Command |
|-----------|-------------|
| Login | `gh auth login` |
| Logout | `gh auth logout` |
| Status | `gh auth status` |
| Token | `gh auth token` |
| Refresh | `gh auth refresh` |
| Switch account | `gh auth switch` |
| Setup git | `gh auth setup-git` |

### SSH Keys

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List keys | `gh ssh-key list` | `GET /user/keys` |
| Add key | `gh ssh-key add` | `POST /user/keys` |
| Delete key | `gh ssh-key delete` | `DELETE /user/keys/{key_id}` |

### GPG Keys

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List keys | `gh gpg-key list` | `GET /user/gpg_keys` |
| Add key | `gh gpg-key add` | `POST /user/gpg_keys` |
| Delete key | `gh gpg-key delete` | `DELETE /user/gpg_keys/{gpg_key_id}` |

---

## Utility Commands

### API Access

| Operation | CLI Command |
|-----------|-------------|
| Raw API call | `gh api {endpoint}` |
| GraphQL query | `gh api graphql -f query='{...}'` |
| Paginate | `gh api --paginate {endpoint}` |

### Extensions

| Operation | CLI Command |
|-----------|-------------|
| List extensions | `gh extension list` |
| Install extension | `gh extension install {repo}` |
| Upgrade extension | `gh extension upgrade {name}` |
| Remove extension | `gh extension remove {name}` |
| Create extension | `gh extension create {name}` |
| Search extensions | `gh extension search {query}` |
| Browse extensions | `gh extension browse` |

### Aliases

| Operation | CLI Command |
|-----------|-------------|
| List aliases | `gh alias list` |
| Set alias | `gh alias set {name} {command}` |
| Delete alias | `gh alias delete {name}` |
| Import aliases | `gh alias import {file}` |

### Configuration

| Operation | CLI Command |
|-----------|-------------|
| Get config | `gh config get {key}` |
| Set config | `gh config set {key} {value}` |
| List config | `gh config list` |
| Clear cache | `gh config clear-cache` |

### Other

| Operation | CLI Command |
|-----------|-------------|
| Open in browser | `gh browse` |
| View status | `gh status` |
| Completion | `gh completion` |

---

## Rate Limits

| Type | Limit |
|------|-------|
| Unauthenticated | 60 requests/hour |
| Authenticated (token) | 5,000 requests/hour |
| GitHub App installation | 5,000 requests/hour (or more with Enterprise) |
| Search API | 30 requests/minute (authenticated) |
| GraphQL | 5,000 points/hour |

Check rate limit: `GET /rate_limit` or `gh api /rate_limit`

---

## References

- [GitHub CLI Manual](https://cli.github.com/manual/)
- [GitHub REST API Documentation](https://docs.github.com/en/rest)
- [GitHub GraphQL API](https://docs.github.com/en/graphql)
- [GitHub Discussions GraphQL API](https://docs.github.com/en/graphql/guides/using-the-graphql-api-for-discussions)
- [Projects v2 API](https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/using-the-api-to-manage-projects)
