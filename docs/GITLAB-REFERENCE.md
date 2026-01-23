# GitLab API & CLI Reference

This document provides a comprehensive reference for GitLab features accessible via the `glab` CLI and REST API. This serves as a planning reference for potential NEXUS3 GitLab tool integration.

---

## Overview

GitLab provides two primary programmatic interfaces:
- **`glab` CLI** - Official command-line tool with 30+ command groups
- **REST API** - HTTP endpoints at `/api/v4/` for all operations
- **GraphQL API** - Available for some advanced queries

**Authentication:**
- Personal Access Tokens (PAT)
- Project/Group Access Tokens
- Deploy Tokens (limited scope)
- OAuth2 tokens
- CLI: `glab auth login`

**Base URL:** `https://gitlab.com/api/v4` (or self-hosted instance)

---

## Code Collaboration

### Merge Requests

Full lifecycle management for code review workflows.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List MRs | `glab mr list` | `GET /projects/:id/merge_requests` |
| View MR | `glab mr view {iid}` | `GET /projects/:id/merge_requests/:mr_iid` |
| Create MR | `glab mr create` | `POST /projects/:id/merge_requests` |
| Update MR | `glab mr update {iid}` | `PUT /projects/:id/merge_requests/:mr_iid` |
| Close MR | `glab mr close {iid}` | `PUT /projects/:id/merge_requests/:mr_iid` with `state_event=close` |
| Reopen MR | `glab mr reopen {iid}` | `PUT /projects/:id/merge_requests/:mr_iid` with `state_event=reopen` |
| Merge MR | `glab mr merge {iid}` | `PUT /projects/:id/merge_requests/:mr_iid/merge` |
| Checkout MR | `glab mr checkout {iid}` | N/A (local git operation) |
| View diff | `glab mr diff {iid}` | `GET /projects/:id/merge_requests/:mr_iid/changes` |
| Approve MR | `glab mr approve {iid}` | `POST /projects/:id/merge_requests/:mr_iid/approve` |
| Revoke approval | `glab mr revoke {iid}` | `POST /projects/:id/merge_requests/:mr_iid/unapprove` |
| Add note/comment | `glab mr note {iid}` | `POST /projects/:id/merge_requests/:mr_iid/notes` |
| Delete MR | `glab mr delete {iid}` | `DELETE /projects/:id/merge_requests/:mr_iid` |
| Subscribe | `glab mr subscribe {iid}` | `POST /projects/:id/merge_requests/:mr_iid/subscribe` |
| Unsubscribe | `glab mr unsubscribe {iid}` | `POST /projects/:id/merge_requests/:mr_iid/unsubscribe` |
| Rebase | N/A | `PUT /projects/:id/merge_requests/:mr_iid/rebase` |
| List commits | N/A | `GET /projects/:id/merge_requests/:mr_iid/commits` |
| List pipelines | N/A | `GET /projects/:id/merge_requests/:mr_iid/pipelines` |

**MR Participants:**
| Operation | API Endpoint |
|-----------|--------------|
| List participants | `GET /projects/:id/merge_requests/:mr_iid/participants` |
| List reviewers | `GET /projects/:id/merge_requests/:mr_iid/reviewers` |

### Merge Request Approvals (Premium)

Approval rules and requirements.

| Operation | API Endpoint |
|-----------|--------------|
| Get approval state | `GET /projects/:id/merge_requests/:mr_iid/approval_state` |
| Get approval rules | `GET /projects/:id/merge_requests/:mr_iid/approval_rules` |
| Create approval rule | `POST /projects/:id/merge_requests/:mr_iid/approval_rules` |
| Update approval rule | `PUT /projects/:id/merge_requests/:mr_iid/approval_rules/:rule_id` |
| Delete approval rule | `DELETE /projects/:id/merge_requests/:mr_iid/approval_rules/:rule_id` |
| Get project approval rules | `GET /projects/:id/approval_rules` |

### Merge Trains (Premium)

Automated merge queue management.

| Operation | API Endpoint |
|-----------|--------------|
| List merge trains | `GET /projects/:id/merge_trains` |
| Get merge train cars | `GET /projects/:id/merge_trains/:target_branch` |
| Get car status | `GET /projects/:id/merge_trains/merge_requests/:mr_iid` |
| Add to merge train | `POST /projects/:id/merge_trains/merge_requests/:mr_iid` |

### MR Discussions & Threads

Threaded conversations on merge requests.

| Operation | API Endpoint |
|-----------|--------------|
| List discussions | `GET /projects/:id/merge_requests/:mr_iid/discussions` |
| Get discussion | `GET /projects/:id/merge_requests/:mr_iid/discussions/:discussion_id` |
| Create discussion | `POST /projects/:id/merge_requests/:mr_iid/discussions` |
| Resolve discussion | `PUT /projects/:id/merge_requests/:mr_iid/discussions/:discussion_id` |
| Add note to discussion | `POST /projects/:id/merge_requests/:mr_iid/discussions/:discussion_id/notes` |

### Draft Notes

Pending review comments (batch submission).

| Operation | API Endpoint |
|-----------|--------------|
| List draft notes | `GET /projects/:id/merge_requests/:mr_iid/draft_notes` |
| Get draft note | `GET /projects/:id/merge_requests/:mr_iid/draft_notes/:draft_note_id` |
| Create draft note | `POST /projects/:id/merge_requests/:mr_iid/draft_notes` |
| Update draft note | `PUT /projects/:id/merge_requests/:mr_iid/draft_notes/:draft_note_id` |
| Delete draft note | `DELETE /projects/:id/merge_requests/:mr_iid/draft_notes/:draft_note_id` |
| Publish all drafts | `POST /projects/:id/merge_requests/:mr_iid/draft_notes/bulk_publish` |

### Issues

Issue tracking with full metadata support.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List issues | `glab issue list` | `GET /projects/:id/issues` |
| View issue | `glab issue view {iid}` | `GET /projects/:id/issues/:issue_iid` |
| Create issue | `glab issue create` | `POST /projects/:id/issues` |
| Update issue | `glab issue update {iid}` | `PUT /projects/:id/issues/:issue_iid` |
| Close issue | `glab issue close {iid}` | `PUT /projects/:id/issues/:issue_iid` with `state_event=close` |
| Reopen issue | `glab issue reopen {iid}` | `PUT /projects/:id/issues/:issue_iid` with `state_event=reopen` |
| Delete issue | `glab issue delete {iid}` | `DELETE /projects/:id/issues/:issue_iid` |
| Add note | `glab issue note {iid}` | `POST /projects/:id/issues/:issue_iid/notes` |
| Subscribe | `glab issue subscribe {iid}` | `POST /projects/:id/issues/:issue_iid/subscribe` |
| Move issue | N/A | `POST /projects/:id/issues/:issue_iid/move` |
| Clone issue | N/A | `POST /projects/:id/issues/:issue_iid/clone` |

**Issue metadata:**
- Assignees: `PUT /projects/:id/issues/:issue_iid` with `assignee_ids`
- Labels: `PUT /projects/:id/issues/:issue_iid` with `labels`
- Milestone: `PUT /projects/:id/issues/:issue_iid` with `milestone_id`
- Weight (Premium): `PUT /projects/:id/issues/:issue_iid` with `weight`
- Due date: `PUT /projects/:id/issues/:issue_iid` with `due_date`
- Time tracking: See Time Tracking section

### Issue Links

Related issue relationships.

| Operation | API Endpoint |
|-----------|--------------|
| List links | `GET /projects/:id/issues/:issue_iid/links` |
| Create link | `POST /projects/:id/issues/:issue_iid/links` |
| Delete link | `DELETE /projects/:id/issues/:issue_iid/links/:issue_link_id` |

**Link types:** `relates_to`, `blocks`, `is_blocked_by`

### Issue Boards

Kanban-style issue management.

| Operation | API Endpoint |
|-----------|--------------|
| List project boards | `GET /projects/:id/boards` |
| Get board | `GET /projects/:id/boards/:board_id` |
| Create board | `POST /projects/:id/boards` |
| Update board | `PUT /projects/:id/boards/:board_id` |
| Delete board | `DELETE /projects/:id/boards/:board_id` |
| List board lists | `GET /projects/:id/boards/:board_id/lists` |
| Create board list | `POST /projects/:id/boards/:board_id/lists` |
| Update board list | `PUT /projects/:id/boards/:board_id/lists/:list_id` |
| Delete board list | `DELETE /projects/:id/boards/:board_id/lists/:list_id` |

### Incidents (Premium)

On-call and incident management.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List incidents | `glab incident list` | `GET /projects/:id/issues?issue_type=incident` |
| View incident | `glab incident view {iid}` | `GET /projects/:id/issues/:issue_iid` |
| Create incident | `glab incident create` | `POST /projects/:id/issues` with `issue_type=incident` |

### Labels

Organize issues and MRs.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List labels | `glab label list` | `GET /projects/:id/labels` |
| Create label | `glab label create` | `POST /projects/:id/labels` |
| Update label | N/A | `PUT /projects/:id/labels/:label_id` |
| Delete label | N/A | `DELETE /projects/:id/labels/:label_id` |
| Promote to group | N/A | `PUT /projects/:id/labels/:label_id/promote` |
| Subscribe | N/A | `POST /projects/:id/labels/:label_id/subscribe` |

### Snippets

Code snippet sharing.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List snippets | `glab snippet list` | `GET /projects/:id/snippets` |
| Get snippet | `glab snippet view {id}` | `GET /projects/:id/snippets/:snippet_id` |
| Create snippet | `glab snippet create` | `POST /projects/:id/snippets` |
| Update snippet | N/A | `PUT /projects/:id/snippets/:snippet_id` |
| Delete snippet | `glab snippet delete {id}` | `DELETE /projects/:id/snippets/:snippet_id` |
| Get raw content | N/A | `GET /projects/:id/snippets/:snippet_id/raw` |

---

## Project Management (Premium/Ultimate)

### Epics

Large initiative tracking across issues.

| Operation | API Endpoint |
|-----------|--------------|
| List epics | `GET /groups/:id/epics` |
| Get epic | `GET /groups/:id/epics/:epic_iid` |
| Create epic | `POST /groups/:id/epics` |
| Update epic | `PUT /groups/:id/epics/:epic_iid` |
| Delete epic | `DELETE /groups/:id/epics/:epic_iid` |

**Epic attributes:**
- `title`, `description`, `labels`, `color`
- `start_date`, `start_date_fixed`, `start_date_is_fixed`
- `due_date`, `due_date_fixed`, `due_date_is_fixed`
- `confidential`, `state` (opened/closed)
- `parent_id` (for nested epics)

### Epic Issues

Link issues to epics.

| Operation | API Endpoint |
|-----------|--------------|
| List epic issues | `GET /groups/:id/epics/:epic_iid/issues` |
| Assign issue to epic | `POST /groups/:id/epics/:epic_iid/issues/:issue_id` |
| Remove issue from epic | `DELETE /groups/:id/epics/:epic_iid/issues/:epic_issue_id` |
| Update issue order | `PUT /groups/:id/epics/:epic_iid/issues/:epic_issue_id` |

### Child Epics (Ultimate)

Nested epic hierarchies.

| Operation | API Endpoint |
|-----------|--------------|
| List child epics | `GET /groups/:id/epics/:epic_iid/epics` |
| Create child epic | `POST /groups/:id/epics/:epic_iid/epics/:child_epic_id` |
| Reorder child epics | `PUT /groups/:id/epics/:epic_iid/epics/:child_epic_id` |
| Remove child epic | `DELETE /groups/:id/epics/:epic_iid/epics/:child_epic_id` |

### Linked Epics (Ultimate)

Cross-epic relationships.

| Operation | API Endpoint |
|-----------|--------------|
| List linked epics | `GET /groups/:id/epics/:epic_iid/related_epics` |
| Create link | `POST /groups/:id/epics/:epic_iid/related_epics` |
| Delete link | `DELETE /groups/:id/epics/:epic_iid/related_epics/:related_epic_link_id` |

**Link types:** `relates_to`, `blocks`, `is_blocked_by`

### Roadmap

Visual timeline of epics (UI feature, no direct API).

**API support:** Query epics with `start_date` and `due_date` to build roadmap views.

### Iterations (Premium)

Sprint/iteration management.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List iterations | `glab iteration list` | `GET /groups/:id/iterations` |
| Get iteration | N/A | `GET /groups/:id/iterations/:iteration_id` |
| Create iteration | N/A | `POST /groups/:id/iterations` |
| Update iteration | N/A | `PUT /groups/:id/iterations/:iteration_id` |
| Delete iteration | N/A | `DELETE /groups/:id/iterations/:iteration_id` |

**Iteration cadences (auto-scheduling):**
| Operation | API Endpoint |
|-----------|--------------|
| List cadences | `GET /groups/:id/iteration_cadences` |
| Create cadence | `POST /groups/:id/iteration_cadences` |
| Update cadence | `PUT /groups/:id/iteration_cadences/:cadence_id` |
| Delete cadence | `DELETE /groups/:id/iteration_cadences/:cadence_id` |

### Milestones

Time-based grouping of issues/MRs.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List milestones | `glab milestone list` | `GET /projects/:id/milestones` |
| Get milestone | N/A | `GET /projects/:id/milestones/:milestone_id` |
| Create milestone | `glab milestone create` | `POST /projects/:id/milestones` |
| Update milestone | N/A | `PUT /projects/:id/milestones/:milestone_id` |
| Delete milestone | N/A | `DELETE /projects/:id/milestones/:milestone_id` |
| Get issues | N/A | `GET /projects/:id/milestones/:milestone_id/issues` |
| Get MRs | N/A | `GET /projects/:id/milestones/:milestone_id/merge_requests` |
| Promote to group | N/A | `POST /projects/:id/milestones/:milestone_id/promote` |
| Get burndown (Premium) | N/A | `GET /projects/:id/milestones/:milestone_id/burndown_events` |

**Group milestones:** Replace `/projects/:id` with `/groups/:id`

### Time Tracking

Estimate and track time spent.

| Operation | API Endpoint |
|-----------|--------------|
| Set estimate | `POST /projects/:id/issues/:issue_iid/time_estimate` |
| Reset estimate | `POST /projects/:id/issues/:issue_iid/reset_time_estimate` |
| Add time spent | `POST /projects/:id/issues/:issue_iid/add_spent_time` |
| Reset time spent | `POST /projects/:id/issues/:issue_iid/reset_spent_time` |
| Get time stats | `GET /projects/:id/issues/:issue_iid/time_stats` |

**Time format:** `3h30m`, `1d`, `1w` (week = 5 days, day = 8 hours by default)

---

## CI/CD & Automation

### Pipelines

CI/CD pipeline management.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List pipelines | `glab ci list` | `GET /projects/:id/pipelines` |
| Get pipeline | `glab ci view {id}` | `GET /projects/:id/pipelines/:pipeline_id` |
| Create pipeline | `glab ci run` | `POST /projects/:id/pipeline` |
| Retry pipeline | `glab ci retry {id}` | `POST /projects/:id/pipelines/:pipeline_id/retry` |
| Cancel pipeline | `glab ci cancel {id}` | `POST /projects/:id/pipelines/:pipeline_id/cancel` |
| Delete pipeline | `glab ci delete {id}` | `DELETE /projects/:id/pipelines/:pipeline_id` |
| Get variables | N/A | `GET /projects/:id/pipelines/:pipeline_id/variables` |
| Get test report | N/A | `GET /projects/:id/pipelines/:pipeline_id/test_report` |
| Get test report summary | N/A | `GET /projects/:id/pipelines/:pipeline_id/test_report_summary` |

### Jobs

Individual job management.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List jobs | `glab ci status` | `GET /projects/:id/jobs` |
| List pipeline jobs | N/A | `GET /projects/:id/pipelines/:pipeline_id/jobs` |
| Get job | `glab job view {id}` | `GET /projects/:id/jobs/:job_id` |
| Get job log | `glab ci trace {id}` | `GET /projects/:id/jobs/:job_id/trace` |
| Retry job | `glab job retry {id}` | `POST /projects/:id/jobs/:job_id/retry` |
| Cancel job | N/A | `POST /projects/:id/jobs/:job_id/cancel` |
| Play manual job | `glab job play {id}` | `POST /projects/:id/jobs/:job_id/play` |
| Erase job | N/A | `POST /projects/:id/jobs/:job_id/erase` |

### Job Artifacts

Build output management.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| Download artifacts | `glab ci artifact {job_id}` | `GET /projects/:id/jobs/:job_id/artifacts` |
| Download single file | N/A | `GET /projects/:id/jobs/:job_id/artifacts/:artifact_path` |
| Download by ref | N/A | `GET /projects/:id/jobs/artifacts/:ref_name/download?job=:job_name` |
| Delete artifacts | N/A | `DELETE /projects/:id/jobs/:job_id/artifacts` |
| Keep artifacts | N/A | `POST /projects/:id/jobs/:job_id/artifacts/keep` |

### Pipeline Schedules

Automated pipeline triggers.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List schedules | `glab schedule list` | `GET /projects/:id/pipeline_schedules` |
| Get schedule | N/A | `GET /projects/:id/pipeline_schedules/:schedule_id` |
| Create schedule | `glab schedule create` | `POST /projects/:id/pipeline_schedules` |
| Update schedule | N/A | `PUT /projects/:id/pipeline_schedules/:schedule_id` |
| Delete schedule | `glab schedule delete {id}` | `DELETE /projects/:id/pipeline_schedules/:schedule_id` |
| Run schedule | `glab schedule run {id}` | `POST /projects/:id/pipeline_schedules/:schedule_id/play` |
| Take ownership | N/A | `POST /projects/:id/pipeline_schedules/:schedule_id/take_ownership` |

**Schedule variables:**
| Operation | API Endpoint |
|-----------|--------------|
| List variables | `GET /projects/:id/pipeline_schedules/:schedule_id/variables` |
| Create variable | `POST /projects/:id/pipeline_schedules/:schedule_id/variables` |
| Update variable | `PUT /projects/:id/pipeline_schedules/:schedule_id/variables/:key` |
| Delete variable | `DELETE /projects/:id/pipeline_schedules/:schedule_id/variables/:key` |

### Pipeline Triggers

External pipeline triggering.

| Operation | API Endpoint |
|-----------|--------------|
| List triggers | `GET /projects/:id/triggers` |
| Get trigger | `GET /projects/:id/triggers/:trigger_id` |
| Create trigger | `POST /projects/:id/triggers` |
| Update trigger | `PUT /projects/:id/triggers/:trigger_id` |
| Delete trigger | `DELETE /projects/:id/triggers/:trigger_id` |
| Trigger pipeline | `POST /projects/:id/trigger/pipeline` |

**Trigger pipeline parameters:**
- `token` (required): Trigger token
- `ref` (required): Branch or tag name
- `variables`: Key-value pairs for CI variables

### CI/CD Variables

Environment and configuration variables.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List variables | `glab variable list` | `GET /projects/:id/variables` |
| Get variable | `glab variable get {key}` | `GET /projects/:id/variables/:key` |
| Create variable | `glab variable set {key}` | `POST /projects/:id/variables` |
| Update variable | `glab variable update {key}` | `PUT /projects/:id/variables/:key` |
| Delete variable | `glab variable delete {key}` | `DELETE /projects/:id/variables/:key` |

**Variable attributes:**
- `key`, `value`, `variable_type` (env_var, file)
- `protected` (only available in protected branches/tags)
- `masked` (hidden in job logs)
- `environment_scope` (specific environments)

**Group variables:** Replace `/projects/:id` with `/groups/:id`

**Instance variables (admin):** `GET /admin/ci/variables`

### Secure Files (Premium)

Secure file storage for CI/CD.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List files | `glab securefile list` | `GET /projects/:id/secure_files` |
| Get file | N/A | `GET /projects/:id/secure_files/:secure_file_id` |
| Upload file | `glab securefile create` | `POST /projects/:id/secure_files` |
| Delete file | `glab securefile delete {id}` | `DELETE /projects/:id/secure_files/:secure_file_id` |
| Download file | N/A | `GET /projects/:id/secure_files/:secure_file_id/download` |

### Environments

Deployment target management.

| Operation | API Endpoint |
|-----------|--------------|
| List environments | `GET /projects/:id/environments` |
| Get environment | `GET /projects/:id/environments/:environment_id` |
| Create environment | `POST /projects/:id/environments` |
| Update environment | `PUT /projects/:id/environments/:environment_id` |
| Delete environment | `DELETE /projects/:id/environments/:environment_id` |
| Stop environment | `POST /projects/:id/environments/:environment_id/stop` |
| Stop stale environments | `POST /projects/:id/environments/stop_stale` |

### Deployments

Track deployments to environments.

| Operation | API Endpoint |
|-----------|--------------|
| List deployments | `GET /projects/:id/deployments` |
| Get deployment | `GET /projects/:id/deployments/:deployment_id` |
| Create deployment | `POST /projects/:id/deployments` |
| Update deployment | `PUT /projects/:id/deployments/:deployment_id` |
| List MRs for deployment | `GET /projects/:id/deployments/:deployment_id/merge_requests` |

### YAML Validation

Validate CI configuration.

| Operation | API Endpoint |
|-----------|--------------|
| Lint CI config | `POST /projects/:id/ci/lint` |
| Validate project config | `GET /projects/:id/ci/lint` |

---

## Releases & Registry

### Releases

Version release management.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List releases | `glab release list` | `GET /projects/:id/releases` |
| Get release | `glab release view {tag}` | `GET /projects/:id/releases/:tag_name` |
| Create release | `glab release create {tag}` | `POST /projects/:id/releases` |
| Update release | N/A | `PUT /projects/:id/releases/:tag_name` |
| Delete release | `glab release delete {tag}` | `DELETE /projects/:id/releases/:tag_name` |
| Get latest release | N/A | `GET /projects/:id/releases/permalink/latest` |

### Release Links

Attach assets and links to releases.

| Operation | API Endpoint |
|-----------|--------------|
| List links | `GET /projects/:id/releases/:tag_name/assets/links` |
| Get link | `GET /projects/:id/releases/:tag_name/assets/links/:link_id` |
| Create link | `POST /projects/:id/releases/:tag_name/assets/links` |
| Update link | `PUT /projects/:id/releases/:tag_name/assets/links/:link_id` |
| Delete link | `DELETE /projects/:id/releases/:tag_name/assets/links/:link_id` |

**Link types:** `other`, `runbook`, `image`, `package`

### Container Registry

Docker image management.

| Operation | API Endpoint |
|-----------|--------------|
| List repositories | `GET /projects/:id/registry/repositories` |
| Get repository | `GET /registry/repositories/:repository_id` |
| Delete repository | `DELETE /projects/:id/registry/repositories/:repository_id` |
| List tags | `GET /projects/:id/registry/repositories/:repository_id/tags` |
| Get tag | `GET /projects/:id/registry/repositories/:repository_id/tags/:tag_name` |
| Delete tag | `DELETE /projects/:id/registry/repositories/:repository_id/tags/:tag_name` |
| Bulk delete tags | `DELETE /projects/:id/registry/repositories/:repository_id/tags` |

### Package Registry

Multi-format package management.

| Operation | API Endpoint |
|-----------|--------------|
| List packages | `GET /projects/:id/packages` |
| Get package | `GET /projects/:id/packages/:package_id` |
| Delete package | `DELETE /projects/:id/packages/:package_id` |
| List package files | `GET /projects/:id/packages/:package_id/package_files` |
| Delete package file | `DELETE /projects/:id/packages/:package_id/package_files/:package_file_id` |

**Supported formats:**
- npm: `GET /projects/:id/packages/npm/*package_name`
- Maven: `GET /projects/:id/packages/maven/*path/:file_name`
- PyPI: `GET /projects/:id/packages/pypi/simple/:package_name`
- NuGet: `GET /projects/:id/packages/nuget/index.json`
- Composer: `GET /projects/:id/packages/composer/packages.json`
- Conan: `GET /projects/:id/packages/conan/v1/...`
- Helm: `GET /projects/:id/packages/helm/stable/:chart.tgz`
- Generic: `GET /projects/:id/packages/generic/:package_name/:version/:file_name`

### Terraform Module Registry

| Operation | API Endpoint |
|-----------|--------------|
| List modules | `GET /projects/:id/packages?package_type=terraform_module` |
| Get module | Via generic packages API |
| Publish module | `PUT /projects/:id/packages/terraform/modules/:module_name/:module_system/:module_version/file` |

---

## Repository Management

### Projects (Repositories)

Core project operations.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List projects | N/A | `GET /projects` |
| Get project | `glab repo view` | `GET /projects/:id` |
| Create project | N/A | `POST /projects` |
| Update project | N/A | `PUT /projects/:id` |
| Delete project | N/A | `DELETE /projects/:id` |
| Fork project | `glab repo fork` | `POST /projects/:id/fork` |
| List forks | N/A | `GET /projects/:id/forks` |
| Archive project | `glab repo archive` | `POST /projects/:id/archive` |
| Unarchive project | N/A | `POST /projects/:id/unarchive` |
| Star project | N/A | `POST /projects/:id/star` |
| Unstar project | N/A | `POST /projects/:id/unstar` |
| Clone project | `glab repo clone` | N/A (git clone) |
| Search projects | `glab repo search` | `GET /projects?search=:query` |

### Repository Files

File operations via API.

| Operation | API Endpoint |
|-----------|--------------|
| Get file | `GET /projects/:id/repository/files/:file_path` |
| Get raw file | `GET /projects/:id/repository/files/:file_path/raw` |
| Get file blame | `GET /projects/:id/repository/files/:file_path/blame` |
| Create file | `POST /projects/:id/repository/files/:file_path` |
| Update file | `PUT /projects/:id/repository/files/:file_path` |
| Delete file | `DELETE /projects/:id/repository/files/:file_path` |

### Branches

Branch management.

| Operation | API Endpoint |
|-----------|--------------|
| List branches | `GET /projects/:id/repository/branches` |
| Get branch | `GET /projects/:id/repository/branches/:branch` |
| Create branch | `POST /projects/:id/repository/branches` |
| Delete branch | `DELETE /projects/:id/repository/branches/:branch` |
| Delete merged branches | `DELETE /projects/:id/repository/merged_branches` |

### Protected Branches

Branch protection rules.

| Operation | API Endpoint |
|-----------|--------------|
| List protected branches | `GET /projects/:id/protected_branches` |
| Get protected branch | `GET /projects/:id/protected_branches/:name` |
| Protect branch | `POST /projects/:id/protected_branches` |
| Update protection | `PATCH /projects/:id/protected_branches/:name` |
| Unprotect branch | `DELETE /projects/:id/protected_branches/:name` |

**Protection levels:** No access (0), Developer (30), Maintainer (40), Admin (60)

### Tags

Git tag management.

| Operation | API Endpoint |
|-----------|--------------|
| List tags | `GET /projects/:id/repository/tags` |
| Get tag | `GET /projects/:id/repository/tags/:tag_name` |
| Create tag | `POST /projects/:id/repository/tags` |
| Delete tag | `DELETE /projects/:id/repository/tags/:tag_name` |

### Protected Tags

Tag protection rules.

| Operation | API Endpoint |
|-----------|--------------|
| List protected tags | `GET /projects/:id/protected_tags` |
| Get protected tag | `GET /projects/:id/protected_tags/:name` |
| Protect tag | `POST /projects/:id/protected_tags` |
| Unprotect tag | `DELETE /projects/:id/protected_tags/:name` |

### Deploy Keys

SSH keys for CI/CD access.

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List keys | `glab deploy-key list` | `GET /projects/:id/deploy_keys` |
| Get key | N/A | `GET /projects/:id/deploy_keys/:key_id` |
| Add key | `glab deploy-key add` | `POST /projects/:id/deploy_keys` |
| Update key | N/A | `PUT /projects/:id/deploy_keys/:key_id` |
| Delete key | `glab deploy-key delete {id}` | `DELETE /projects/:id/deploy_keys/:key_id` |
| Enable key | N/A | `POST /projects/:id/deploy_keys/:key_id/enable` |

### Deploy Tokens

Tokens for registry and repository access.

| Operation | API Endpoint |
|-----------|--------------|
| List tokens | `GET /projects/:id/deploy_tokens` |
| Get token | `GET /projects/:id/deploy_tokens/:token_id` |
| Create token | `POST /projects/:id/deploy_tokens` |
| Delete token | `DELETE /projects/:id/deploy_tokens/:token_id` |

### Remote Mirrors

Repository mirroring.

| Operation | API Endpoint |
|-----------|--------------|
| List mirrors | `GET /projects/:id/remote_mirrors` |
| Get mirror | `GET /projects/:id/remote_mirrors/:mirror_id` |
| Create mirror | `POST /projects/:id/remote_mirrors` |
| Update mirror | `PUT /projects/:id/remote_mirrors/:mirror_id` |
| Delete mirror | `DELETE /projects/:id/remote_mirrors/:mirror_id` |
| Trigger sync | `POST /projects/:id/remote_mirrors/:mirror_id/sync` |

### Webhooks

Project event notifications.

| Operation | API Endpoint |
|-----------|--------------|
| List webhooks | `GET /projects/:id/hooks` |
| Get webhook | `GET /projects/:id/hooks/:hook_id` |
| Add webhook | `POST /projects/:id/hooks` |
| Update webhook | `PUT /projects/:id/hooks/:hook_id` |
| Delete webhook | `DELETE /projects/:id/hooks/:hook_id` |
| Test webhook | `POST /projects/:id/hooks/:hook_id/test/:trigger` |

**Triggers:** `push_events`, `tag_push_events`, `merge_requests_events`, `issues_events`, `pipeline_events`, `job_events`, etc.

---

## Security & Compliance

### Vulnerabilities (Ultimate)

Security vulnerability tracking.

| Operation | API Endpoint |
|-----------|--------------|
| List vulnerabilities | `GET /projects/:id/vulnerabilities` |
| Get vulnerability | `GET /vulnerabilities/:id` |
| Create vulnerability | `POST /projects/:id/vulnerabilities` |
| Update vulnerability | N/A |
| Confirm vulnerability | `POST /vulnerabilities/:id/confirm` |
| Dismiss vulnerability | `POST /vulnerabilities/:id/dismiss` |
| Resolve vulnerability | `POST /vulnerabilities/:id/resolve` |
| Revert to detected | `POST /vulnerabilities/:id/revert` |

### Vulnerability Findings (Ultimate)

Raw security scan results.

| Operation | API Endpoint |
|-----------|--------------|
| List findings | `GET /projects/:id/vulnerability_findings` |

### Vulnerability Exports (Ultimate)

Export vulnerability data.

| Operation | API Endpoint |
|-----------|--------------|
| Create export | `POST /projects/:id/vulnerability_exports` |
| Get export | `GET /projects/:id/vulnerability_exports/:export_id` |
| Download export | `GET /projects/:id/vulnerability_exports/:export_id/download` |

### Dependency List (Ultimate)

| Operation | API Endpoint |
|-----------|--------------|
| List dependencies | `GET /projects/:id/dependencies` |

### External Status Checks (Ultimate)

Third-party approval requirements.

| Operation | API Endpoint |
|-----------|--------------|
| List checks | `GET /projects/:id/external_status_checks` |
| Create check | `POST /projects/:id/external_status_checks` |
| Update check | `PUT /projects/:id/external_status_checks/:check_id` |
| Delete check | `DELETE /projects/:id/external_status_checks/:check_id` |
| Set MR status | `POST /projects/:id/merge_requests/:mr_iid/status_check_responses` |

---

## Infrastructure

### Kubernetes Agents (Premium)

GitLab Agent for Kubernetes.

| Operation | API Endpoint |
|-----------|--------------|
| List agents | `GET /projects/:id/cluster_agents` |
| Get agent | `GET /projects/:id/cluster_agents/:agent_id` |
| Register agent | `POST /projects/:id/cluster_agents` |
| Delete agent | `DELETE /projects/:id/cluster_agents/:agent_id` |
| List agent tokens | `GET /projects/:id/cluster_agents/:agent_id/tokens` |
| Create agent token | `POST /projects/:id/cluster_agents/:agent_id/tokens` |
| Revoke agent token | `DELETE /projects/:id/cluster_agents/:agent_id/tokens/:token_id` |

### Feature Flags (Premium)

| Operation | API Endpoint |
|-----------|--------------|
| List flags | `GET /projects/:id/feature_flags` |
| Get flag | `GET /projects/:id/feature_flags/:name` |
| Create flag | `POST /projects/:id/feature_flags` |
| Update flag | `PUT /projects/:id/feature_flags/:name` |
| Delete flag | `DELETE /projects/:id/feature_flags/:name` |

**Feature flag user lists:**
| Operation | API Endpoint |
|-----------|--------------|
| List user lists | `GET /projects/:id/feature_flags_user_lists` |
| Get user list | `GET /projects/:id/feature_flags_user_lists/:iid` |
| Create user list | `POST /projects/:id/feature_flags_user_lists` |
| Update user list | `PUT /projects/:id/feature_flags_user_lists/:iid` |
| Delete user list | `DELETE /projects/:id/feature_flags_user_lists/:iid` |

### Freeze Periods

Prevent deployments during specific times.

| Operation | API Endpoint |
|-----------|--------------|
| List freeze periods | `GET /projects/:id/freeze_periods` |
| Get freeze period | `GET /projects/:id/freeze_periods/:freeze_period_id` |
| Create freeze period | `POST /projects/:id/freeze_periods` |
| Update freeze period | `PUT /projects/:id/freeze_periods/:freeze_period_id` |
| Delete freeze period | `DELETE /projects/:id/freeze_periods/:freeze_period_id` |

---

## AI Features

### GitLab Duo

AI-powered assistance.

| Operation | CLI Command |
|-----------|-------------|
| Ask Duo | `glab duo ask` |

**Duo capabilities:**
- Git command suggestions
- Code explanations
- Code generation
- Vulnerability explanations

---

## Groups

### Group Management

| Operation | API Endpoint |
|-----------|--------------|
| List groups | `GET /groups` |
| Get group | `GET /groups/:id` |
| Create group | `POST /groups` |
| Update group | `PUT /groups/:id` |
| Delete group | `DELETE /groups/:id` |
| List subgroups | `GET /groups/:id/subgroups` |
| List descendant groups | `GET /groups/:id/descendant_groups` |
| List projects | `GET /groups/:id/projects` |
| Transfer project | `POST /groups/:id/projects/:project_id` |

### Group Members

| Operation | API Endpoint |
|-----------|--------------|
| List members | `GET /groups/:id/members` |
| Get member | `GET /groups/:id/members/:user_id` |
| Add member | `POST /groups/:id/members` |
| Update member | `PUT /groups/:id/members/:user_id` |
| Remove member | `DELETE /groups/:id/members/:user_id` |
| List all members (inherited) | `GET /groups/:id/members/all` |

### Group Access Tokens

| Operation | API Endpoint |
|-----------|--------------|
| List tokens | `GET /groups/:id/access_tokens` |
| Get token | `GET /groups/:id/access_tokens/:token_id` |
| Create token | `POST /groups/:id/access_tokens` |
| Revoke token | `DELETE /groups/:id/access_tokens/:token_id` |
| Rotate token | `POST /groups/:id/access_tokens/:token_id/rotate` |

---

## User Management

### Authentication

| Operation | CLI Command |
|-----------|-------------|
| Login | `glab auth login` |
| Logout | `glab auth logout` |
| Status | `glab auth status` |

### SSH Keys

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List keys | `glab ssh-key list` | `GET /user/keys` |
| Get key | N/A | `GET /user/keys/:key_id` |
| Add key | `glab ssh-key add` | `POST /user/keys` |
| Delete key | `glab ssh-key delete {id}` | `DELETE /user/keys/:key_id` |

### GPG Keys

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List keys | `glab gpg-key list` | `GET /user/gpg_keys` |
| Get key | N/A | `GET /user/gpg_keys/:key_id` |
| Add key | `glab gpg-key add` | `POST /user/gpg_keys` |
| Delete key | N/A | `DELETE /user/gpg_keys/:key_id` |

### Personal Access Tokens

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| List tokens | `glab token list` | `GET /personal_access_tokens` |
| Get token | N/A | `GET /personal_access_tokens/:id` |
| Create token | `glab token create` | `POST /users/:user_id/personal_access_tokens` |
| Revoke token | `glab token revoke {id}` | `DELETE /personal_access_tokens/:id` |
| Rotate token | N/A | `POST /personal_access_tokens/:id/rotate` |

### Users

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| Get current user | `glab user` | `GET /user` |
| Get user | N/A | `GET /users/:id` |
| Search users | N/A | `GET /users?search=:query` |
| Get user status | N/A | `GET /users/:id/status` |
| Set user status | N/A | `PUT /user/status` |

---

## To-Do List

Personal task reminders.

| Operation | API Endpoint |
|-----------|--------------|
| List to-dos | `GET /todos` |
| Mark as done | `POST /todos/:id/mark_as_done` |
| Mark all as done | `POST /todos/mark_all_as_done` |

---

## Search

### Search API

| Operation | API Endpoint |
|-----------|--------------|
| Global search | `GET /search?scope=:scope&search=:query` |
| Group search | `GET /groups/:id/search?scope=:scope&search=:query` |
| Project search | `GET /projects/:id/search?scope=:scope&search=:query` |

**Scopes:** `projects`, `issues`, `merge_requests`, `milestones`, `snippet_titles`, `wiki_blobs`, `commits`, `blobs`, `notes`, `users`

---

## Utility Commands

### API Access

| Operation | CLI Command |
|-----------|-------------|
| Raw API call | `glab api {endpoint}` |

### Aliases

| Operation | CLI Command |
|-----------|-------------|
| List aliases | `glab alias list` |
| Set alias | `glab alias set {name} {command}` |
| Delete alias | `glab alias delete {name}` |

### Configuration

| Operation | CLI Command |
|-----------|-------------|
| Get config | `glab config get {key}` |
| Set config | `glab config set {key} {value}` |

### Changelog

| Operation | CLI Command | API Endpoint |
|-----------|-------------|--------------|
| Generate changelog | `glab changelog generate` | `POST /projects/:id/repository/changelog` |

---

## Rate Limits

| Type | Limit |
|------|-------|
| Unauthenticated | 500 requests/minute |
| Authenticated | 2,000 requests/minute |
| Protected paths | 10 requests/minute |
| Raw endpoints | 300 requests/minute |
| Files API | 10 requests/minute (some operations) |

Check rate limit headers: `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset`

---

## Pagination

GitLab supports two pagination methods:

**Offset-based (default):**
- `page`: Page number (default: 1)
- `per_page`: Items per page (default: 20, max: 100)
- Response headers: `X-Total`, `X-Total-Pages`, `X-Page`, `X-Per-Page`, `X-Next-Page`, `X-Prev-Page`

**Keyset-based (recommended for large datasets):**
- Add `pagination=keyset` parameter
- Use `Link` header for next page URL
- More efficient for large collections

---

## GitLab Tiers

Some features require paid tiers:

| Feature | Tier Required |
|---------|---------------|
| Epics | Premium |
| Roadmap | Premium |
| Iterations | Premium |
| Merge Trains | Premium |
| Approval Rules | Premium |
| Code Owners | Premium |
| Feature Flags | Premium |
| Kubernetes Agents | Premium |
| Secure Files | Premium |
| Child Epics | Ultimate |
| Linked Epics | Ultimate |
| Vulnerabilities | Ultimate |
| Dependency Scanning | Ultimate |
| Container Scanning | Ultimate |
| DAST | Ultimate |
| External Status Checks | Ultimate |

---

## References

- [GitLab CLI (glab) Documentation](https://docs.gitlab.com/cli/)
- [GitLab REST API Documentation](https://docs.gitlab.com/api/rest/)
- [GitLab REST API Resources](https://docs.gitlab.com/api/api_resources/)
- [GitLab Epics Documentation](https://docs.gitlab.com/user/group/epics/)
- [GitLab Roadmap Documentation](https://docs.gitlab.com/user/group/roadmap/)
- [python-gitlab Documentation](https://python-gitlab.readthedocs.io/)
