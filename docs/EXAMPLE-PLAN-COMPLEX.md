# Example Implementation Plan (Complex)

> **This is a reference example for the Planning SOP.** See `CLAUDE.md` for the planning process documentation. This plan demonstrates the standard structure for large multi-phase features with multiple skills, security considerations, and phased rollout. For simpler single-feature plans, see `EXAMPLE-PLAN-SIMPLE.md`.

---

# GitLab Tools Implementation Plan

This document outlines the implementation plan for GitLab integration in NEXUS3. The design prioritizes GitLab features while maintaining abstractions that allow future GitHub support.

---

## Goals

1. **GitLab-first**: Full-featured GitLab integration covering project management, code review, and CI/CD
2. **Dual-use ready**: Abstract interfaces where GitHub has equivalent concepts
3. **Agent-friendly**: Designed for LLM agents, not just human CLI users
4. **Permission-aware**: Integrate with NEXUS3's existing permission system
5. **Secure by default**: Pre-configured instances, TRUSTED+ required, per-skill confirmation
6. **Context-efficient**: Only load skills when GitLab is configured (no unused tools)
7. **Consistent patterns**: Follow existing skill conventions (FileSkill, NexusSkill, etc.)

---

## Scope

### Included in v1

| Category | Features |
|----------|----------|
| **Core Git** | Repositories, branches, tags, commits, diffs |
| **Code Review** | Merge requests, approvals, draft notes, discussions |
| **Issues** | Issues, comments, labels, assignees |
| **Project Management** | Epics, epic links, roadmaps, iterations, milestones, issue boards, time tracking |
| **CI/CD** | Pipelines, jobs, artifacts, variables |
| **Repository Config** | Protected branches/tags, deploy keys/tokens |
| **Premium Features** | Feature flags, MR approvals, iterations |

### Deferred to Future Versions

| Feature | Reason |
|---------|--------|
| Pipeline schedules & triggers | Automation feature, not core workflow |
| Environments & deployments | Useful context, but secondary |
| Webhooks | Admin/integration setup |

### Explicitly Excluded

| Feature | Reason |
|---------|--------|
| Merge trains | Advanced CI, niche |
| Incidents | SRE-specific |
| Snippets | Niche use case |
| Container/Package registry | Separate deployment concern |
| Kubernetes agents | Infrastructure-specific |
| Vulnerability scanning | Requires Ultimate, specialized |

---

## Security Model

GitLab tools follow a defense-in-depth security model with three layers of protection, consistent with how NEXUS3 handles providers and MCP servers.

### Design Principles

1. **No implicit network access**: GitLab instances must be explicitly configured
2. **TRUSTED minimum**: SANDBOXED agents cannot use GitLab tools (network blocked)
3. **User visibility**: Per-skill confirmation prompts on first use
4. **Context efficiency**: Skills not registered if no GitLab instance configured

### Layer 1: Pre-Configured Instances

Users must explicitly configure GitLab instances before skills become available. This prevents agents from connecting to arbitrary servers.

**Configuration (`~/.nexus3/config.json` or `.nexus3/config.json`):**

```json
{
  "gitlab": {
    "instances": {
      "default": {
        "url": "https://gitlab.com",
        "token_env": "GITLAB_TOKEN",
        "token": null
      },
      "work": {
        "url": "https://gitlab.mycompany.com",
        "token_env": "GITLAB_WORK_TOKEN",
        "token": null
      }
    },
    "default_instance": "default"
  }
}
```

**Configuration fields:**

| Field | Required | Description |
|-------|----------|-------------|
| `url` | Yes | GitLab instance base URL (must be HTTPS, or HTTP localhost only) |
| `token_env` | No | Environment variable containing the token |
| `token` | No | Direct token value (not recommended, use `token_env`) |

**Token resolution order:**
1. `token` field (if set)
2. Environment variable from `token_env`
3. Prompt user interactively (REPL only)

**URL validation:**
- HTTPS required for remote instances
- HTTP allowed only for localhost/127.0.0.1 (local development)
- Uses existing `validate_url()` from `nexus3/core/url_validator.py`
- Cloud metadata endpoints (169.254.169.254) always blocked

### Layer 2: Permission Level Requirement

All GitLab skills require **TRUSTED or higher** permission level.

| Permission Level | GitLab Access |
|------------------|---------------|
| SANDBOXED | **Blocked** - `can_network() = False` |
| TRUSTED | Allowed with confirmation prompts |
| YOLO | Allowed without prompts |

**Rationale:** Network access is inherently privileged. SANDBOXED mode is designed for untrusted agents that should not exfiltrate data or access external services.

### Layer 3: Per-Skill Confirmation Prompts

In TRUSTED mode, each GitLab skill prompts for confirmation on first use. Users can allow for the remainder of the session.

**First invocation of `gitlab_issue`:**
```
┌─ GitLab Access ─────────────────────────────────────────┐
│                                                         │
│  gitlab_issue wants to connect to:                      │
│  https://gitlab.com                                     │
│                                                         │
│  Action: list issues in "mygroup/myproject"             │
│                                                         │
│  [Allow once]  [Allow for session]  [Deny]              │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**Session allowances storage:**
```json
{
  "session_allowances": {
    "gitlab_issue@gitlab.com": true,
    "gitlab_mr@gitlab.com": true,
    "gitlab_issue@gitlab.mycompany.com": true
  }
}
```

**Key format:** `{skill_name}@{instance_host}`

This means:
- Allowing `gitlab_issue` on `gitlab.com` doesn't allow it on `gitlab.mycompany.com`
- Allowing `gitlab_issue` doesn't allow `gitlab_mr` (separate prompts)
- Session allowances reset when session ends

**YOLO mode:** Prompts skipped entirely (user accepts all risk at session start).

### Layer 4: Conditional Skill Registration

**Critical for context efficiency:** GitLab skills are only registered if at least one GitLab instance is configured.

```python
# nexus3/skill/vcs/gitlab/__init__.py

def register_gitlab_skills(
    registry: SkillRegistry,
    container: ServiceContainer,
    config: Config,
) -> int:
    """
    Register GitLab skills if GitLab is configured.

    Returns the number of skills registered (0 if no GitLab config).
    """
    gitlab_config = config.get("gitlab", {})
    instances = gitlab_config.get("instances", {})

    if not instances:
        # No GitLab configured - don't pollute tool context
        return 0

    # Register all GitLab skills
    skills = [
        gitlab_repo_factory(container),
        gitlab_issue_factory(container),
        gitlab_mr_factory(container),
        # ... etc
    ]

    for skill in skills:
        registry.register(skill)

    return len(skills)
```

**Benefits:**
- Agents without GitLab access don't see 20 unusable tools
- Reduces context window usage (~2-3k tokens saved)
- Clearer tool list for agents
- Faster tool selection (fewer options to evaluate)

**Same pattern for future GitHub support:**
```python
def register_vcs_skills(registry, container, config):
    """Register VCS skills based on configuration."""
    count = 0

    if config.get("gitlab", {}).get("instances"):
        count += register_gitlab_skills(registry, container, config)

    if config.get("github", {}).get("instances"):
        count += register_github_skills(registry, container, config)

    return count
```

### Security Comparison

| Aspect | Providers | MCP | GitLab Tools |
|--------|-----------|-----|--------------|
| Pre-configured | ✓ `config.json` | ✓ `mcp.json` | ✓ `config.json` |
| URL validation | ✓ SSRF protection | ✓ SSRF protection | ✓ SSRF protection |
| Permission level | N/A (core) | TRUSTED+ | TRUSTED+ |
| Per-use confirmation | N/A | Per-server | Per-skill |
| Session allowances | N/A | ✓ | ✓ |
| Conditional registration | N/A | ✓ | ✓ |

### Attack Mitigation

| Attack Vector | Mitigation |
|---------------|------------|
| Agent connects to malicious server | Pre-configured instances only |
| SSRF to internal networks | URL validation, HTTPS required |
| Data exfiltration via SANDBOXED agent | TRUSTED+ required |
| User unaware of network access | Per-skill confirmation prompts |
| Token theft via config | Support `token_env` over direct `token` |
| Cloud metadata access | Always blocked by URL validator |

### REPL Commands for GitLab Configuration

```bash
# Show GitLab configuration status
/gitlab                     # List configured instances and auth status

# Manage instances (writes to config.json)
/gitlab add <name> <url>    # Add instance (prompts for token)
/gitlab remove <name>       # Remove instance
/gitlab default <name>      # Set default instance

# Test connectivity
/gitlab test [name]         # Test connection to instance
```

**Example session:**
```
> /gitlab
GitLab Instances:
  default: https://gitlab.com (authenticated as @username)
  work: https://gitlab.mycompany.com (no token configured)

> /gitlab add personal https://gitlab.example.com
GitLab token for https://gitlab.example.com: ****
Instance 'personal' added and authenticated as @myuser

> /gitlab default personal
Default instance set to 'personal'
```

---

## Architecture

### Directory Structure

```
nexus3/skill/vcs/
├── __init__.py              # Conditional registration based on config
├── base.py                  # VCSSkill base class, platform detection, client management
├── types.py                 # Shared types (IssueState, MRState, LinkType, etc.)
├── config.py                # GitLabConfig, GitHubConfig Pydantic models
│
├── gitlab/
│   ├── __init__.py          # register_gitlab_skills(), skill factories
│   ├── client.py            # GitLab async HTTP client with SSRF protection
│   │
│   │  # Core Operations
│   ├── repo.py              # Repository operations
│   ├── branch.py            # Branch & tag management
│   ├── mr.py                # Merge requests (full lifecycle)
│   ├── issue.py             # Issues (full lifecycle)
│   │
│   │  # Project Management
│   ├── epic.py              # Epics & epic hierarchy
│   ├── iteration.py         # Iterations (sprints)
│   ├── milestone.py         # Milestones
│   ├── board.py             # Issue boards
│   ├── label.py             # Labels
│   ├── time_tracking.py     # Time estimates & spent
│   │
│   │  # Code Review
│   ├── approval.py          # MR approvals & rules
│   ├── draft_note.py        # Batch review drafts
│   ├── discussion.py        # Threaded discussions
│   │
│   │  # CI/CD
│   ├── pipeline.py          # Pipelines & jobs
│   ├── artifact.py          # Job artifacts
│   ├── variable.py          # CI/CD variables
│   │
│   │  # Repository Config
│   ├── protected.py         # Protected branches/tags
│   ├── deploy_key.py        # Deploy keys
│   ├── deploy_token.py      # Deploy tokens
│   │
│   │  # Premium Features
│   └── feature_flag.py      # Feature flags
│
└── github/                  # Future: GitHub implementations
    └── __init__.py          # Placeholder
```

### Base Classes

```python
# nexus3/skill/vcs/base.py

class VCSSkill(BaseSkill):
    """Base class for version control skills with platform detection."""

    def __init__(self, container: ServiceContainer) -> None:
        self._container = container
        self._clients: dict[str, GitLabClient | GitHubClient] = {}

    def _detect_platform(self, remote_url: str | None = None) -> Platform:
        """
        Detect platform from git remote or explicit URL.

        Returns Platform.GITLAB, Platform.GITHUB, or Platform.UNKNOWN.
        """
        ...

    def _get_gitlab_client(self, instance_url: str | None = None) -> GitLabClient:
        """Get or create GitLab client for instance."""
        ...

    def _resolve_project(self, project: str | None, cwd: str | None) -> str:
        """
        Resolve project identifier.

        - If project provided: use it (e.g., "group/repo")
        - If cwd provided: detect from git remote
        - Otherwise: use skill's working directory
        """
        ...


class GitLabSkill(VCSSkill):
    """Base class for GitLab-specific skills."""

    @property
    def _client(self) -> GitLabClient:
        """Convenience accessor for default GitLab client."""
        return self._get_gitlab_client()
```

### Client Design

Two options for GitLab API client:

**Option A: Wrap python-gitlab library**
```python
# Pros: Full API coverage, maintained, handles pagination
# Cons: Dependency, may not match our async patterns

import gitlab

class GitLabClient:
    def __init__(self, url: str, token: str):
        self._gl = gitlab.Gitlab(url, private_token=token)

    async def get_project(self, project_id: str) -> Project:
        # python-gitlab is sync, wrap in executor
        return await asyncio.to_thread(self._gl.projects.get, project_id)
```

**Option B: Native async HTTP client**
```python
# Pros: Async-native, no dependency, full control
# Cons: More code to write, pagination handling

class GitLabClient:
    def __init__(self, url: str, token: str):
        self._base_url = url.rstrip("/") + "/api/v4"
        self._token = token
        self._http: httpx.AsyncClient | None = None

    async def get_project(self, project_id: str) -> dict[str, Any]:
        return await self._get(f"/projects/{quote(project_id, safe='')}")

    async def _get(self, path: str, **params) -> dict[str, Any]:
        async with self._ensure_client() as client:
            resp = await client.get(
                f"{self._base_url}{path}",
                params=params,
                headers={"PRIVATE-TOKEN": self._token}
            )
            resp.raise_for_status()
            return resp.json()
```

**Recommendation:** Option B (native async HTTP). Keeps us async-native, avoids dependency, and we only need a subset of endpoints.

### Skill Pattern

Each skill follows a consistent pattern with action-based dispatch:

```python
# nexus3/skill/vcs/gitlab/issue.py

class GitLabIssueSkill(GitLabSkill):
    """Manage GitLab issues."""

    @property
    def name(self) -> str:
        return "gitlab_issue"

    @property
    def description(self) -> str:
        return "Create, view, update, and manage GitLab issues"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "create", "update", "close", "reopen",
                             "comment", "link", "unlink", "list-links"],
                    "description": "Action to perform"
                },
                "project": {
                    "type": "string",
                    "description": "Project path (e.g., 'group/repo'). Auto-detected from cwd if omitted."
                },
                "iid": {
                    "type": "integer",
                    "description": "Issue IID (required for get/update/close/reopen/comment/link operations)"
                },
                "title": {"type": "string", "description": "Issue title (for create)"},
                "description": {"type": "string", "description": "Issue description"},
                "labels": {"type": "array", "items": {"type": "string"}},
                "assignees": {"type": "array", "items": {"type": "string"}},
                "milestone": {"type": "string", "description": "Milestone title"},
                "epic_id": {"type": "integer", "description": "Epic ID to assign"},
                "weight": {"type": "integer", "description": "Issue weight (0-9)"},
                "due_date": {"type": "string", "description": "Due date (YYYY-MM-DD)"},
                # Link parameters
                "target_iid": {"type": "integer", "description": "Target issue IID for linking"},
                "link_type": {
                    "type": "string",
                    "enum": ["relates_to", "blocks", "is_blocked_by"],
                    "description": "Relationship type"
                },
                # List filters
                "state": {"type": "string", "enum": ["opened", "closed", "all"]},
                "search": {"type": "string", "description": "Search in title/description"},
                "author": {"type": "string", "description": "Filter by author username"},
                "assignee": {"type": "string", "description": "Filter by assignee username"},
                "limit": {"type": "integer", "description": "Max results (default 20)"},
            },
            "required": ["action"]
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "")
        project = self._resolve_project(kwargs.get("project"), kwargs.get("cwd"))

        match action:
            case "list":
                return await self._list_issues(project, **kwargs)
            case "get":
                return await self._get_issue(project, kwargs["iid"])
            case "create":
                return await self._create_issue(project, **kwargs)
            case "update":
                return await self._update_issue(project, kwargs["iid"], **kwargs)
            case "close":
                return await self._close_issue(project, kwargs["iid"])
            case "reopen":
                return await self._reopen_issue(project, kwargs["iid"])
            case "comment":
                return await self._add_comment(project, kwargs["iid"], kwargs["body"])
            case "link":
                return await self._link_issue(project, kwargs["iid"], kwargs["target_iid"], kwargs.get("link_type", "relates_to"))
            case "unlink":
                return await self._unlink_issue(project, kwargs["iid"], kwargs["link_id"])
            case "list-links":
                return await self._list_links(project, kwargs["iid"])
            case _:
                return ToolResult(success=False, error=f"Unknown action: {action}")
```

---

## Skill Specifications

### Note on Authentication

Unlike some GitLab CLI tools, NEXUS3 does **not** have a `gitlab_auth` skill that agents can invoke to authenticate. This is intentional:

1. **Tokens are pre-configured** by the user in `config.json` or via environment variables
2. **Agents should not handle credentials** directly (security boundary)
3. **Instance management is human-only** via `/gitlab` REPL commands

**Token resolution order for configured instances:**
1. `token` field in config (not recommended)
2. Environment variable from `token_env` field
3. Interactive prompt in REPL (if no token found)

**This means:** An agent cannot add new GitLab instances or modify tokens. It can only use instances the user has pre-configured. This is a security feature, not a limitation.

---

### Repository Operations

**Skill:** `gitlab_repo`

| Action | Parameters | Description |
|--------|------------|-------------|
| `get` | `project` | Get project details |
| `list` | `owned?`, `membership?`, `search?`, `limit?` | List accessible projects |
| `create` | `name`, `namespace?`, `description?`, `visibility?` | Create project |
| `fork` | `project`, `namespace?` | Fork a project |
| `archive` | `project` | Archive project |
| `unarchive` | `project` | Unarchive project |
| `delete` | `project` | Delete project (dangerous) |

**Dual-use notes:** All operations map directly to GitHub. Abstract as `vcs_repo` later.

---

### Branch & Tag Management

**Skill:** `gitlab_branch`

| Action | Parameters | Description |
|--------|------------|-------------|
| `list` | `project`, `search?` | List branches |
| `get` | `project`, `branch` | Get branch details |
| `create` | `project`, `branch`, `ref` | Create branch from ref |
| `delete` | `project`, `branch` | Delete branch |
| `protect` | `project`, `branch`, `push_level?`, `merge_level?` | Protect branch |
| `unprotect` | `project`, `branch` | Remove protection |
| `list-protected` | `project` | List protected branches |

**Skill:** `gitlab_tag`

| Action | Parameters | Description |
|--------|------------|-------------|
| `list` | `project`, `search?` | List tags |
| `get` | `project`, `tag` | Get tag details |
| `create` | `project`, `tag`, `ref`, `message?` | Create tag |
| `delete` | `project`, `tag` | Delete tag |
| `protect` | `project`, `tag`, `create_level?` | Protect tag pattern |
| `unprotect` | `project`, `tag` | Remove protection |

---

### Merge Requests

**Skill:** `gitlab_mr`

| Action | Parameters | Description |
|--------|------------|-------------|
| `list` | `project`, `state?`, `author?`, `assignee?`, `reviewer?`, `labels?`, `search?`, `limit?` | List MRs |
| `get` | `project`, `iid` | Get MR details |
| `create` | `project`, `source_branch`, `target_branch`, `title`, `description?`, `labels?`, `assignees?`, `reviewers?`, `draft?` | Create MR |
| `update` | `project`, `iid`, `title?`, `description?`, `labels?`, `assignees?`, `reviewers?` | Update MR |
| `close` | `project`, `iid` | Close MR |
| `reopen` | `project`, `iid` | Reopen MR |
| `merge` | `project`, `iid`, `squash?`, `delete_source?`, `message?` | Merge MR |
| `rebase` | `project`, `iid` | Rebase MR |
| `diff` | `project`, `iid` | Get MR diff |
| `commits` | `project`, `iid` | List MR commits |
| `pipelines` | `project`, `iid` | List MR pipelines |
| `comment` | `project`, `iid`, `body` | Add comment |

**Dual-use notes:** Direct mapping to GitHub PRs. `merge` options differ slightly (squash/rebase/merge commit).

---

### MR Approvals (Premium)

**Skill:** `gitlab_approval`

| Action | Parameters | Description |
|--------|------------|-------------|
| `status` | `project`, `iid` | Get approval state (who approved, who's pending) |
| `approve` | `project`, `iid` | Approve MR |
| `unapprove` | `project`, `iid` | Revoke approval |
| `rules` | `project`, `iid?` | List approval rules (MR or project level) |
| `create-rule` | `project`, `name`, `approvals_required`, `users?`, `groups?` | Create project approval rule |
| `delete-rule` | `project`, `rule_id` | Delete approval rule |

---

### Draft Notes (Batch Review)

**Skill:** `gitlab_draft`

| Action | Parameters | Description |
|--------|------------|-------------|
| `list` | `project`, `iid` | List pending draft notes |
| `add` | `project`, `iid`, `body`, `path?`, `line?`, `line_type?` | Add draft note (optionally on specific line) |
| `update` | `project`, `iid`, `draft_id`, `body` | Update draft |
| `delete` | `project`, `iid`, `draft_id` | Delete draft |
| `publish` | `project`, `iid` | Publish all drafts as review |

**Line comments:** `path` is file path, `line` is line number, `line_type` is `new` or `old` (for diff context).

---

### Discussions

**Skill:** `gitlab_discussion`

| Action | Parameters | Description |
|--------|------------|-------------|
| `list` | `project`, `iid`, `target_type` | List discussions on MR/issue |
| `get` | `project`, `iid`, `discussion_id`, `target_type` | Get discussion thread |
| `create` | `project`, `iid`, `body`, `target_type`, `path?`, `line?` | Start discussion |
| `reply` | `project`, `iid`, `discussion_id`, `body`, `target_type` | Reply to discussion |
| `resolve` | `project`, `iid`, `discussion_id`, `target_type` | Resolve discussion |
| `unresolve` | `project`, `iid`, `discussion_id`, `target_type` | Unresolve discussion |

`target_type`: `mr` or `issue`

---

### Issues

**Skill:** `gitlab_issue`

| Action | Parameters | Description |
|--------|------------|-------------|
| `list` | `project`, `state?`, `labels?`, `milestone?`, `author?`, `assignee?`, `search?`, `limit?` | List issues |
| `get` | `project`, `iid` | Get issue details |
| `create` | `project`, `title`, `description?`, `labels?`, `assignees?`, `milestone?`, `epic_id?`, `weight?`, `due_date?` | Create issue |
| `update` | `project`, `iid`, (same as create) | Update issue |
| `close` | `project`, `iid` | Close issue |
| `reopen` | `project`, `iid` | Reopen issue |
| `comment` | `project`, `iid`, `body` | Add comment |
| `link` | `project`, `iid`, `target_iid`, `link_type?` | Link to another issue |
| `unlink` | `project`, `iid`, `link_id` | Remove link |
| `list-links` | `project`, `iid` | List issue links |
| `move` | `project`, `iid`, `target_project` | Move issue to another project |

---

### Epics (Premium)

**Skill:** `gitlab_epic`

| Action | Parameters | Description |
|--------|------------|-------------|
| `list` | `group`, `state?`, `labels?`, `author?`, `search?`, `limit?` | List epics |
| `get` | `group`, `iid` | Get epic details |
| `create` | `group`, `title`, `description?`, `labels?`, `start_date?`, `due_date?`, `parent_id?` | Create epic |
| `update` | `group`, `iid`, (same as create) | Update epic |
| `close` | `group`, `iid` | Close epic |
| `reopen` | `group`, `iid` | Reopen epic |
| `add-issue` | `group`, `iid`, `issue_id` | Add issue to epic |
| `remove-issue` | `group`, `iid`, `epic_issue_id` | Remove issue from epic |
| `list-issues` | `group`, `iid` | List issues in epic |
| `add-child` | `group`, `iid`, `child_epic_id` | Add child epic (Ultimate) |
| `remove-child` | `group`, `iid`, `child_epic_id` | Remove child epic |
| `list-children` | `group`, `iid` | List child epics |
| `link` | `group`, `iid`, `target_group`, `target_iid`, `link_type?` | Link to another epic |
| `unlink` | `group`, `iid`, `link_id` | Remove epic link |
| `list-links` | `group`, `iid` | List linked epics |

**Roadmap view:** No specific API endpoint. Roadmap is rendered from epics with dates. Agents can query epics with date filters and construct roadmap view.

---

### Iterations (Premium)

**Skill:** `gitlab_iteration`

| Action | Parameters | Description |
|--------|------------|-------------|
| `list` | `group`, `state?`, `search?` | List iterations |
| `get` | `group`, `iteration_id` | Get iteration details |
| `create` | `group`, `title`, `start_date`, `due_date`, `description?`, `cadence_id?` | Create iteration |
| `update` | `group`, `iteration_id`, `title?`, `description?` | Update iteration |
| `delete` | `group`, `iteration_id` | Delete iteration |
| `list-cadences` | `group` | List iteration cadences (auto-scheduling) |
| `create-cadence` | `group`, `title`, `start_date`, `duration_in_weeks`, `iterations_in_advance?`, `automatic?` | Create cadence |

---

### Milestones

**Skill:** `gitlab_milestone`

| Action | Parameters | Description |
|--------|------------|-------------|
| `list` | `project` or `group`, `state?`, `search?` | List milestones |
| `get` | `project` or `group`, `milestone_id` | Get milestone |
| `create` | `project` or `group`, `title`, `description?`, `start_date?`, `due_date?` | Create milestone |
| `update` | `project` or `group`, `milestone_id`, ... | Update milestone |
| `close` | `project` or `group`, `milestone_id` | Close milestone |
| `issues` | `project` or `group`, `milestone_id` | List milestone issues |
| `merge-requests` | `project` or `group`, `milestone_id` | List milestone MRs |

---

### Issue Boards

**Skill:** `gitlab_board`

| Action | Parameters | Description |
|--------|------------|-------------|
| `list` | `project` or `group` | List boards |
| `get` | `project` or `group`, `board_id` | Get board with lists |
| `create` | `project` or `group`, `name`, `labels?` | Create board |
| `update` | `project` or `group`, `board_id`, `name?` | Update board |
| `delete` | `project` or `group`, `board_id` | Delete board |
| `list-lists` | `project` or `group`, `board_id` | Get board lists (columns) |
| `create-list` | `project` or `group`, `board_id`, `label_id?`, `assignee_id?`, `milestone_id?`, `iteration_id?` | Add list to board |
| `update-list` | `project` or `group`, `board_id`, `list_id`, `position` | Reorder list |
| `delete-list` | `project` or `group`, `board_id`, `list_id` | Remove list |

---

### Labels

**Skill:** `gitlab_label`

| Action | Parameters | Description |
|--------|------------|-------------|
| `list` | `project` or `group`, `search?` | List labels |
| `get` | `project` or `group`, `label_id` | Get label |
| `create` | `project` or `group`, `name`, `color`, `description?` | Create label |
| `update` | `project` or `group`, `label_id`, `name?`, `color?`, `description?` | Update label |
| `delete` | `project` or `group`, `label_id` | Delete label |
| `promote` | `project`, `label_id` | Promote project label to group |

---

### Time Tracking

**Skill:** `gitlab_time`

| Action | Parameters | Description |
|--------|------------|-------------|
| `estimate` | `project`, `iid`, `target_type`, `duration` | Set time estimate (e.g., "2d", "8h") |
| `reset-estimate` | `project`, `iid`, `target_type` | Remove estimate |
| `spend` | `project`, `iid`, `target_type`, `duration`, `date?` | Log time spent |
| `reset-spent` | `project`, `iid`, `target_type` | Reset time spent |
| `stats` | `project`, `iid`, `target_type` | Get time tracking stats |

`target_type`: `issue` or `mr`

`duration` format: `1mo 2w 3d 4h 5m` (month, week, day, hour, minute)

---

### Pipelines

**Skill:** `gitlab_pipeline`

| Action | Parameters | Description |
|--------|------------|-------------|
| `list` | `project`, `ref?`, `status?`, `source?`, `limit?` | List pipelines |
| `get` | `project`, `pipeline_id` | Get pipeline details |
| `create` | `project`, `ref`, `variables?` | Trigger new pipeline |
| `retry` | `project`, `pipeline_id` | Retry failed jobs |
| `cancel` | `project`, `pipeline_id` | Cancel running pipeline |
| `delete` | `project`, `pipeline_id` | Delete pipeline |
| `jobs` | `project`, `pipeline_id`, `scope?` | List pipeline jobs |
| `variables` | `project`, `pipeline_id` | Get pipeline variables |

---

### Jobs

**Skill:** `gitlab_job`

| Action | Parameters | Description |
|--------|------------|-------------|
| `list` | `project`, `scope?` | List project jobs |
| `get` | `project`, `job_id` | Get job details |
| `log` | `project`, `job_id`, `tail?` | Get job log (optionally last N lines) |
| `retry` | `project`, `job_id` | Retry job |
| `cancel` | `project`, `job_id` | Cancel job |
| `play` | `project`, `job_id`, `variables?` | Start manual job |
| `erase` | `project`, `job_id` | Erase job (logs + artifacts) |

---

### Artifacts

**Skill:** `gitlab_artifact`

| Action | Parameters | Description |
|--------|------------|-------------|
| `download` | `project`, `job_id`, `output_path` | Download job artifacts |
| `download-file` | `project`, `job_id`, `artifact_path`, `output_path` | Download single file |
| `browse` | `project`, `job_id` | List artifact contents |
| `delete` | `project`, `job_id` | Delete artifacts |
| `keep` | `project`, `job_id` | Prevent artifact expiration |
| `download-ref` | `project`, `ref`, `job_name`, `output_path` | Download by branch and job name |

---

### CI/CD Variables

**Skill:** `gitlab_variable`

| Action | Parameters | Description |
|--------|------------|-------------|
| `list` | `project` or `group` | List variables |
| `get` | `project` or `group`, `key` | Get variable |
| `create` | `project` or `group`, `key`, `value`, `protected?`, `masked?`, `environment_scope?` | Create variable |
| `update` | `project` or `group`, `key`, ... | Update variable |
| `delete` | `project` or `group`, `key` | Delete variable |

---

### Deploy Keys

**Skill:** `gitlab_deploy_key`

| Action | Parameters | Description |
|--------|------------|-------------|
| `list` | `project` | List deploy keys |
| `get` | `project`, `key_id` | Get deploy key |
| `create` | `project`, `title`, `key`, `can_push?` | Add deploy key |
| `update` | `project`, `key_id`, `title?`, `can_push?` | Update key |
| `delete` | `project`, `key_id` | Remove key |
| `enable` | `project`, `key_id` | Enable existing key from another project |

---

### Deploy Tokens

**Skill:** `gitlab_deploy_token`

| Action | Parameters | Description |
|--------|------------|-------------|
| `list` | `project` or `group` | List deploy tokens |
| `get` | `project` or `group`, `token_id` | Get token details |
| `create` | `project` or `group`, `name`, `scopes`, `expires_at?`, `username?` | Create token |
| `delete` | `project` or `group`, `token_id` | Revoke token |

`scopes`: `read_repository`, `read_registry`, `write_registry`, `read_package_registry`, `write_package_registry`

---

### Feature Flags (Premium)

**Skill:** `gitlab_feature_flag`

| Action | Parameters | Description |
|--------|------------|-------------|
| `list` | `project`, `scope?` | List feature flags |
| `get` | `project`, `name` | Get flag details with strategies |
| `create` | `project`, `name`, `description?`, `active?`, `strategies?` | Create flag |
| `update` | `project`, `name`, `description?`, `active?`, `strategies?` | Update flag |
| `delete` | `project`, `name` | Delete flag |
| `list-user-lists` | `project` | List user lists for targeting |
| `create-user-list` | `project`, `name`, `user_xids` | Create user list |
| `update-user-list` | `project`, `list_id`, `name?`, `user_xids?` | Update user list |
| `delete-user-list` | `project`, `list_id` | Delete user list |

**Strategies:** `default`, `gradualRolloutUserId`, `userWithId`, `gitlabUserList`, `flexibleRollout`

---

## Implementation Phases

### Phase 1: Foundation

**Goal:** Core infrastructure, security model, and basic operations

1. **Configuration & Security**
   - `GitLabConfig` Pydantic model for config validation
   - Config loading from `~/.nexus3/config.json` and `.nexus3/config.json`
   - URL validation using existing `validate_url()`
   - Token resolution (config → env var → prompt)

2. **Client Infrastructure**
   - `GitLabClient` async HTTP client with httpx
   - SSRF protection on all requests
   - Pagination handling
   - Error handling and retries

3. **Conditional Registration**
   - `register_gitlab_skills()` checks config before registering
   - Skip registration if no GitLab configured (save context)
   - Skip registration if SANDBOXED (network blocked)

4. **Confirmation System**
   - Per-skill confirmation prompts (TRUSTED mode)
   - Session allowances storage and lookup
   - Integration with existing REPL confirmation UI

5. **REPL Commands**
   - `/gitlab` - list instances and status
   - `/gitlab add`, `/gitlab remove`, `/gitlab default`
   - `/gitlab test` - connectivity check

6. **Basic Skills**
   - `gitlab_repo` (get, list, fork)
   - `gitlab_issue` (list, get, create, update, close, comment)
   - `gitlab_mr` (list, get, create, merge, comment)
   - `gitlab_label` (list, get, create, delete)

**Deliverable:** Secure foundation with working basic operations. Agent can browse projects, create issues/MRs, add comments - but only after user configures GitLab and approves access.

---

### Phase 2: Project Management

**Goal:** Full project management capabilities

1. **Epics**
   - `gitlab_epic` (full implementation including hierarchy and links)

2. **Iterations**
   - `gitlab_iteration` (including cadences)

3. **Milestones**
   - `gitlab_milestone` (project and group level)

4. **Issue Boards**
   - `gitlab_board` (boards and lists)

5. **Time Tracking**
   - `gitlab_time` (estimates and spent)

6. **Issue/Epic Links**
   - Add link actions to `gitlab_issue` and `gitlab_epic`

**Deliverable:** Agent can manage full project workflow with epics, iterations, boards

---

### Phase 3: Code Review

**Goal:** Complete code review workflow

1. **MR Enhancements**
   - Add diff, commits, pipelines actions to `gitlab_mr`

2. **Approvals**
   - `gitlab_approval` (approve, rules)

3. **Draft Notes**
   - `gitlab_draft` (batch review)

4. **Discussions**
   - `gitlab_discussion` (threaded comments, resolve)

**Deliverable:** Agent can perform complete code reviews with approvals and discussions

---

### Phase 4: CI/CD

**Goal:** Pipeline visibility and management

1. **Pipelines**
   - `gitlab_pipeline` (list, trigger, retry, cancel)

2. **Jobs**
   - `gitlab_job` (list, logs, retry, play)

3. **Artifacts**
   - `gitlab_artifact` (download, browse)

4. **Variables**
   - `gitlab_variable` (CRUD for CI variables)

**Deliverable:** Agent can monitor CI, read logs, download artifacts, manage variables

---

### Phase 5: Repository Config & Premium

**Goal:** Repository governance and premium features

1. **Protected Branches/Tags**
   - Add protection actions to `gitlab_branch` and `gitlab_tag`

2. **Deploy Keys/Tokens**
   - `gitlab_deploy_key`
   - `gitlab_deploy_token`

3. **Feature Flags**
   - `gitlab_feature_flag`

**Deliverable:** Full feature set complete

---

## Permission Integration

### Skill Registration

GitLab skills are conditionally registered based on configuration and permission level:

```python
# nexus3/skill/vcs/gitlab/__init__.py

def register_gitlab_skills(
    registry: SkillRegistry,
    container: ServiceContainer,
    config: Config,
    permissions: PermissionConfig,
) -> int:
    """
    Register GitLab skills if configured and permitted.

    Returns 0 if:
    - No GitLab instances configured (don't pollute context)
    - Permission level is SANDBOXED (network blocked)
    """
    # Check configuration
    gitlab_config = config.get("gitlab", {})
    instances = gitlab_config.get("instances", {})
    if not instances:
        return 0  # No GitLab configured

    # Check permission level
    if permissions.level == PermissionLevel.SANDBOXED:
        return 0  # Network access blocked

    # Register all GitLab skills
    skills = [
        gitlab_repo_factory(container, gitlab_config),
        gitlab_issue_factory(container, gitlab_config),
        gitlab_mr_factory(container, gitlab_config),
        gitlab_epic_factory(container, gitlab_config),
        gitlab_pipeline_factory(container, gitlab_config),
        # ... all 20 skills
    ]

    for skill in skills:
        registry.register(skill)

    return len(skills)
```

### Confirmation Integration

Each GitLab skill checks session allowances before executing:

```python
# nexus3/skill/vcs/gitlab/base.py

class GitLabSkill(VCSSkill):
    """Base class for GitLab skills with confirmation support."""

    async def execute(self, **kwargs: Any) -> ToolResult:
        # Resolve which instance we're connecting to
        instance = self._resolve_instance(kwargs.get("instance"))
        instance_host = urlparse(instance.url).netloc

        # Check session allowance
        allowance_key = f"{self.name}@{instance_host}"
        if not self._container.session_allowances.get(allowance_key):
            # Request confirmation (handled by REPL/display layer)
            allowed = await self._request_confirmation(
                skill=self.name,
                instance_url=instance.url,
                action=kwargs.get("action", "access"),
                target=kwargs.get("project") or kwargs.get("group", ""),
            )

            if not allowed:
                return ToolResult(
                    success=False,
                    error=f"Access to {instance.url} denied by user"
                )

            # User selected "Allow for session"
            if allowed == "session":
                self._container.session_allowances[allowance_key] = True

        # Proceed with actual execution
        return await self._execute_impl(**kwargs)
```

### Permission Presets

Custom presets can further restrict GitLab access:

```json
{
  "permissions": {
    "presets": {
      "gitlab-readonly": {
        "level": "TRUSTED",
        "description": "GitLab read-only access",
        "tools": {
          "gitlab_*": {
            "actions": ["list", "get", "diff", "commits", "log", "browse", "stats"]
          }
        }
      },
      "gitlab-contributor": {
        "level": "TRUSTED",
        "description": "GitLab read/write, no admin actions",
        "tools": {
          "gitlab_*": true,
          "gitlab_repo": {"actions": ["get", "list", "fork"]},
          "gitlab_branch": {"actions": ["list", "get", "create"]},
          "gitlab_variable": false,
          "gitlab_deploy_key": false,
          "gitlab_deploy_token": false,
          "gitlab_feature_flag": false
        }
      }
    }
  }
}
```

### Per-Action Permissions (Future)

The permission system supports action-level restrictions, enabling fine-grained control:

| Preset | Can list issues | Can create issues | Can delete issues |
|--------|----------------|-------------------|-------------------|
| gitlab-readonly | ✓ | ✗ | ✗ |
| gitlab-contributor | ✓ | ✓ | ✗ |
| gitlab-admin | ✓ | ✓ | ✓ |

---

## Dual-Use Abstraction Strategy

For future GitHub support, we'll create abstract interfaces:

```python
# nexus3/skill/vcs/types.py

class Issue(Protocol):
    """Abstract issue interface."""
    id: int
    iid: int  # GitLab-specific, same as id for GitHub
    title: str
    description: str
    state: IssueState
    labels: list[str]
    assignees: list[str]
    created_at: datetime
    updated_at: datetime

class MergeRequest(Protocol):
    """Abstract MR/PR interface."""
    id: int
    iid: int
    title: str
    description: str
    state: MRState
    source_branch: str
    target_branch: str
    author: str
    assignees: list[str]
    reviewers: list[str]
    labels: list[str]
    draft: bool
    mergeable: bool

# Unified skill would wrap platform-specific implementations
class VCSIssueSkill(VCSSkill):
    """Unified issue skill that delegates to platform-specific implementation."""

    async def execute(self, **kwargs) -> ToolResult:
        platform = self._detect_platform(kwargs.get("project"))

        if platform == Platform.GITLAB:
            return await self._gitlab_impl.execute(**kwargs)
        elif platform == Platform.GITHUB:
            return await self._github_impl.execute(**kwargs)
        else:
            return ToolResult(success=False, error="Could not detect VCS platform")
```

---

## Testing Strategy

### Unit Tests

- Mock GitLabClient responses
- Test action dispatch and parameter validation
- Test error handling

### Integration Tests

- Use GitLab test instance or gitlab.com test project
- Test full skill workflows
- Requires `GITLAB_TEST_TOKEN` and `GITLAB_TEST_PROJECT`

### E2E Tests

- Create test project, run full workflows, clean up
- Scheduled CI job (not on every commit due to rate limits)

---

### Integration Point: `nexus3/session/enforcer.py` Changes

Add GitLab skill confirmation handling:

```python
# In PermissionEnforcer class

GITLAB_WRITE_ACTIONS = frozenset({
    "create", "update", "close", "reopen", "delete", "merge",
    "comment", "link", "unlink", "move", "approve", "unapprove",
    "add", "remove", "publish", "protect", "unprotect",
    "spend", "estimate", "reset-estimate", "reset-spent",
    "play", "retry", "cancel", "erase", "keep",
})

def requires_confirmation(
    self,
    tool_call: ToolCall,
    permissions: AgentPermissions | None,
) -> bool:
    """Check if tool call requires user confirmation."""

    # ... existing checks ...

    # GitLab skill confirmation (TRUSTED mode)
    if tool_call.name.startswith("gitlab_"):
        return self._requires_gitlab_confirmation(tool_call, permissions)

    return False

def _requires_gitlab_confirmation(
    self,
    tool_call: ToolCall,
    permissions: AgentPermissions | None,
) -> bool:
    """Check if GitLab skill needs confirmation."""
    if not permissions:
        return True

    # YOLO mode: no confirmation
    if permissions.level == PermissionLevel.YOLO:
        return False

    # Check if action is read-only
    action = tool_call.arguments.get("action", "")
    if action not in self.GITLAB_WRITE_ACTIONS:
        return False  # Read-only actions don't need confirmation

    # Check session allowances
    instance = tool_call.arguments.get("instance", "default")
    # Would need instance host resolution here
    allowances = self._services.get("session_allowances") or {}
    allowance_key = f"{tool_call.name}@{instance}"
    if allowances.get(allowance_key):
        return False  # Already allowed for session

    return True  # Requires confirmation
```

---

### Integration Point: `nexus3/session/session.py` Changes

Handle GitLab confirmation results:

```python
# In Session._execute_tool_call()

async def _execute_tool_call(self, tool_call: ToolCall) -> ToolResult:
    # ... existing code ...

    # Handle GitLab confirmation
    if tool_call.name.startswith("gitlab_") and self._enforcer.requires_confirmation(tool_call, permissions):
        result = await self._request_gitlab_confirmation(tool_call)
        if result == ConfirmationResult.DENY:
            return ToolResult(success=False, error="Action cancelled by user")
        if result == ConfirmationResult.ALLOW_GITLAB_SKILL:
            # Store session allowance
            instance = tool_call.arguments.get("instance", "default")
            allowances = self._services.get("session_allowances") or {}
            allowances[f"{tool_call.name}@{instance}"] = True
            self._services.register("session_allowances", allowances)

    # ... continue with execution ...


async def _request_gitlab_confirmation(self, tool_call: ToolCall) -> ConfirmationResult:
    """Request confirmation for GitLab skill."""
    instance = tool_call.arguments.get("instance", "default")
    action = tool_call.arguments.get("action", "access")
    target = tool_call.arguments.get("project") or tool_call.arguments.get("group") or ""

    # Use existing confirmation callback
    if self.on_confirm:
        # Format message for GitLab
        message = f"{tool_call.name} wants to {action}"
        if target:
            message += f" on '{target}'"
        message += f"\nInstance: {instance}"

        return await self.on_confirm(
            tool_call=tool_call,
            display_path=message,
            agent_cwd=str(self._services.get_cwd()),
        )

    # Non-interactive: deny by default
    return ConfirmationResult.DENY
```

---

### Test Integration Points

```python
# tests/unit/skill/vcs/conftest.py

import pytest
from unittest.mock import MagicMock, AsyncMock
from nexus3.skill.services import ServiceContainer
from nexus3.skill.vcs.config import GitLabConfig, GitLabInstance
from nexus3.core.permissions import PermissionLevel


@pytest.fixture
def mock_services():
    """Create mock ServiceContainer for testing."""
    services = MagicMock(spec=ServiceContainer)
    services.get.return_value = None
    services.get_cwd.return_value = Path("/tmp/test")
    services.get_permission_level.return_value = PermissionLevel.TRUSTED
    return services


@pytest.fixture
def gitlab_config():
    """Create test GitLab config."""
    return GitLabConfig(
        instances={
            "test": GitLabInstance(
                url="https://gitlab.com",
                token="test-token",
            )
        },
        default_instance="test",
    )


@pytest.fixture
def mock_gitlab_client():
    """Create mock GitLab client."""
    client = AsyncMock()
    client.get.return_value = {"id": 1, "title": "Test"}
    client.post.return_value = {"id": 1, "iid": 1, "title": "Test", "web_url": "https://..."}
    client.put.return_value = {"id": 1, "iid": 1, "title": "Test"}
    client.delete.return_value = None
    return client
```

---

## Resolved Design Decisions

| Decision | Resolution | Rationale |
|----------|------------|-----------|
| **Network security model** | Pre-configured instances + TRUSTED+ + per-skill confirmation | Defense in depth, consistent with MCP pattern |
| **Skill registration** | Conditional on GitLab config | Don't pollute context with unusable tools |
| **Self-hosted instances** | Yes, multiple named instances | Enterprise requirement, clean config structure |
| **Token storage** | `token_env` preferred, direct `token` supported | Avoid secrets in config files |
| **Permission level** | TRUSTED minimum | Network access is privileged |

## Open Questions

1. **Rate limiting:** Implement client-side rate limit tracking? GitLab is generous (2000/min authenticated), probably not needed initially. Monitor in practice.

2. **Pagination:** Auto-paginate or return page info? Default to auto-paginate with configurable `limit` parameter.

3. **GraphQL:** Some operations are better via GraphQL (epics hierarchy). Use REST primarily, GraphQL where beneficial. Evaluate during implementation.

4. **Keyring integration:** Secure token storage via system keyring? Defer to later version. Current approach (env var + config) is sufficient.

5. **Offline/cached mode:** Cache project metadata for offline access? Out of scope for v1, but architecture should allow future addition.

6. **Confirmation UX:** Exact prompt format and interaction model? Needs design alignment with existing NEXUS3 confirmation prompts.

---

## Concrete Implementation Details

This section provides copy-paste ready code and exact specifications for implementation.

### File: `nexus3/skill/vcs/__init__.py`

```python
"""VCS (Version Control Service) skills for GitLab and GitHub integration."""

from nexus3.config import Config
from nexus3.core.permissions import PermissionConfig, PermissionLevel
from nexus3.skill import SkillRegistry
from nexus3.session import ServiceContainer


def register_vcs_skills(
    registry: SkillRegistry,
    container: ServiceContainer,
    config: Config,
    permissions: PermissionConfig,
) -> int:
    """
    Register VCS skills based on configuration and permissions.

    Only registers skills for configured platforms. Skips registration
    entirely if permission level is SANDBOXED (network blocked).

    Returns total number of skills registered.
    """
    # SANDBOXED agents cannot use network - don't register any VCS skills
    if permissions.level == PermissionLevel.SANDBOXED:
        return 0

    count = 0

    # GitLab skills
    gitlab_config = config.get("gitlab", {})
    if gitlab_config.get("instances"):
        from nexus3.skill.vcs.gitlab import register_gitlab_skills
        count += register_gitlab_skills(registry, container, gitlab_config)

    # GitHub skills (future)
    github_config = config.get("github", {})
    if github_config.get("instances"):
        from nexus3.skill.vcs.github import register_github_skills
        count += register_github_skills(registry, container, github_config)

    return count
```

---

### File: `nexus3/skill/vcs/config.py`

```python
"""Configuration models for VCS integrations."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, field_validator, model_validator

from nexus3.core.url_validator import validate_url


class GitLabInstance(BaseModel):
    """Configuration for a single GitLab instance."""

    url: str
    token: str | None = None
    token_env: str | None = None

    @field_validator("url")
    @classmethod
    def validate_url_format(cls, v: str) -> str:
        """Validate URL is well-formed and safe."""
        # Use existing SSRF protection
        # allow_localhost=True for local GitLab development instances
        return validate_url(v, allow_localhost=True, allow_private=False)

    def get_token(self) -> str | None:
        """
        Resolve token from config or environment.

        Resolution order:
        1. Direct token value (if set)
        2. Environment variable from token_env
        3. None (caller should prompt interactively)
        """
        if self.token:
            return self.token
        if self.token_env:
            return os.environ.get(self.token_env)
        return None

    @property
    def host(self) -> str:
        """Extract hostname from URL."""
        return urlparse(self.url).netloc


class GitLabConfig(BaseModel):
    """GitLab configuration with multiple instances."""

    instances: dict[str, GitLabInstance] = {}
    default_instance: str | None = None

    @model_validator(mode="after")
    def validate_default_instance(self) -> "GitLabConfig":
        """Ensure default_instance references a valid instance."""
        if self.default_instance and self.default_instance not in self.instances:
            raise ValueError(
                f"default_instance '{self.default_instance}' not found in instances"
            )
        # If no default set but instances exist, use first one
        if not self.default_instance and self.instances:
            self.default_instance = next(iter(self.instances))
        return self

    def get_instance(self, name: str | None = None) -> GitLabInstance | None:
        """Get instance by name, or default instance."""
        if name:
            return self.instances.get(name)
        if self.default_instance:
            return self.instances.get(self.default_instance)
        return None


def load_gitlab_config(config_dict: dict[str, Any]) -> GitLabConfig | None:
    """
    Load GitLab config from raw config dict.

    Returns None if no GitLab configuration present.
    """
    gitlab_raw = config_dict.get("gitlab")
    if not gitlab_raw:
        return None

    return GitLabConfig.model_validate(gitlab_raw)
```

---

### File: `nexus3/skill/vcs/gitlab/client.py`

```python
"""Async HTTP client for GitLab API."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator
from urllib.parse import quote

import httpx

from nexus3.core.url_validator import validate_url
from nexus3.skill.vcs.config import GitLabInstance


class GitLabAPIError(Exception):
    """GitLab API error with status code and message."""

    def __init__(self, status_code: int, message: str, response_body: Any = None):
        self.status_code = status_code
        self.message = message
        self.response_body = response_body
        super().__init__(f"GitLab API error {status_code}: {message}")


class GitLabClient:
    """
    Async HTTP client for GitLab REST API.

    Features:
    - Async-native with httpx
    - SSRF protection via URL validation
    - Automatic pagination
    - Retry with exponential backoff
    - Connection pooling
    """

    DEFAULT_TIMEOUT = 30.0
    DEFAULT_PER_PAGE = 20
    MAX_PER_PAGE = 100
    MAX_RETRIES = 3
    RETRY_BACKOFF = 1.5

    def __init__(
        self,
        instance: GitLabInstance,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self._instance = instance
        self._base_url = instance.url.rstrip("/") + "/api/v4"
        self._timeout = timeout
        self._http: httpx.AsyncClient | None = None
        self._token: str | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Lazily create HTTP client."""
        if self._http is None or self._http.is_closed:
            # Resolve token
            self._token = self._instance.get_token()
            if not self._token:
                raise GitLabAPIError(401, "No GitLab token configured")

            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
                headers={
                    "PRIVATE-TOKEN": self._token,
                    "User-Agent": "NEXUS3-GitLab-Client/1.0",
                },
                # Don't follow redirects automatically (security)
                follow_redirects=False,
            )
        return self._http

    async def close(self) -> None:
        """Close HTTP client."""
        if self._http and not self._http.is_closed:
            await self._http.aclose()
            self._http = None

    async def __aenter__(self) -> "GitLabClient":
        await self._ensure_client()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    def _encode_path(self, project_or_group: str) -> str:
        """URL-encode project/group path (e.g., 'group/subgroup/repo')."""
        return quote(project_or_group, safe="")

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        retry: int = 0,
    ) -> Any:
        """
        Make HTTP request with retry logic.

        Returns parsed JSON response.
        Raises GitLabAPIError on failure.
        """
        client = await self._ensure_client()
        url = f"{self._base_url}{path}"

        # Validate URL before request (defense in depth)
        validate_url(url, allow_localhost=True, allow_private=False)

        try:
            response = await client.request(
                method=method,
                url=url,
                params=params,
                json=json,
            )

            # Handle rate limiting
            if response.status_code == 429:
                if retry < self.MAX_RETRIES:
                    retry_after = int(response.headers.get("Retry-After", 5))
                    await asyncio.sleep(min(retry_after, 60))
                    return await self._request(method, path, params, json, retry + 1)
                raise GitLabAPIError(429, "Rate limit exceeded")

            # Handle server errors with retry
            if response.status_code >= 500:
                if retry < self.MAX_RETRIES:
                    await asyncio.sleep(self.RETRY_BACKOFF ** retry)
                    return await self._request(method, path, params, json, retry + 1)

            # Handle client errors
            if response.status_code >= 400:
                try:
                    body = response.json()
                    message = body.get("message", body.get("error", str(body)))
                except Exception:
                    message = response.text
                raise GitLabAPIError(response.status_code, message, body if 'body' in dir() else None)

            # Return JSON response (or None for 204)
            if response.status_code == 204:
                return None
            return response.json()

        except httpx.TimeoutException:
            if retry < self.MAX_RETRIES:
                await asyncio.sleep(self.RETRY_BACKOFF ** retry)
                return await self._request(method, path, params, json, retry + 1)
            raise GitLabAPIError(0, "Request timeout")

        except httpx.RequestError as e:
            raise GitLabAPIError(0, f"Request failed: {e}")

    async def get(self, path: str, **params: Any) -> Any:
        """GET request."""
        return await self._request("GET", path, params=params or None)

    async def post(self, path: str, **data: Any) -> Any:
        """POST request."""
        return await self._request("POST", path, json=data or None)

    async def put(self, path: str, **data: Any) -> Any:
        """PUT request."""
        return await self._request("PUT", path, json=data or None)

    async def delete(self, path: str) -> Any:
        """DELETE request."""
        return await self._request("DELETE", path)

    async def paginate(
        self,
        path: str,
        limit: int = DEFAULT_PER_PAGE,
        **params: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Auto-paginate through results.

        Yields individual items up to `limit` total.
        """
        per_page = min(limit, self.MAX_PER_PAGE)
        page = 1
        count = 0

        while count < limit:
            params["page"] = page
            params["per_page"] = per_page

            results = await self.get(path, **params)

            if not results:
                break

            for item in results:
                yield item
                count += 1
                if count >= limit:
                    break

            if len(results) < per_page:
                break

            page += 1

    # =========================================================================
    # Convenience methods for common endpoints
    # =========================================================================

    async def get_current_user(self) -> dict[str, Any]:
        """Get authenticated user info."""
        return await self.get("/user")

    async def get_project(self, project: str) -> dict[str, Any]:
        """Get project by path or ID."""
        return await self.get(f"/projects/{self._encode_path(project)}")

    async def list_projects(
        self,
        owned: bool = False,
        membership: bool = False,
        search: str | None = None,
        limit: int = DEFAULT_PER_PAGE,
    ) -> list[dict[str, Any]]:
        """List accessible projects."""
        params: dict[str, Any] = {}
        if owned:
            params["owned"] = True
        if membership:
            params["membership"] = True
        if search:
            params["search"] = search

        return [item async for item in self.paginate("/projects", limit=limit, **params)]
```

---

### File: `nexus3/skill/vcs/gitlab/base.py`

```python
"""Base class for GitLab skills."""

from __future__ import annotations

import subprocess
from typing import Any, TYPE_CHECKING
from urllib.parse import urlparse

from nexus3.core.types import ToolResult
from nexus3.skill.base import BaseSkill
from nexus3.skill.vcs.config import GitLabConfig, GitLabInstance
from nexus3.skill.vcs.gitlab.client import GitLabClient, GitLabAPIError

if TYPE_CHECKING:
    from nexus3.session import ServiceContainer


class GitLabSkill(BaseSkill):
    """
    Base class for all GitLab skills.

    Provides:
    - Instance resolution (which GitLab to connect to)
    - Client management (lazy initialization, caching)
    - Project resolution from git remote
    - Confirmation prompt integration
    - Standard error handling
    """

    def __init__(
        self,
        container: "ServiceContainer",
        gitlab_config: GitLabConfig,
    ):
        self._container = container
        self._config = gitlab_config
        self._clients: dict[str, GitLabClient] = {}

    def _resolve_instance(self, instance_name: str | None = None) -> GitLabInstance:
        """
        Resolve which GitLab instance to use.

        Priority:
        1. Explicit instance_name parameter
        2. Detect from git remote (if in a git repo)
        3. Default instance from config
        """
        # Explicit instance requested
        if instance_name:
            instance = self._config.get_instance(instance_name)
            if not instance:
                raise ValueError(f"GitLab instance '{instance_name}' not configured")
            return instance

        # Try to detect from git remote
        detected = self._detect_instance_from_remote()
        if detected:
            return detected

        # Fall back to default
        instance = self._config.get_instance()
        if not instance:
            raise ValueError("No GitLab instance configured")
        return instance

    def _detect_instance_from_remote(self) -> GitLabInstance | None:
        """
        Detect GitLab instance from current git remote.

        Returns instance if a configured instance matches the remote URL.
        """
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=self._container.cwd,
            )
            if result.returncode != 0:
                return None

            remote_url = result.stdout.strip()
            remote_host = self._extract_host(remote_url)

            # Find matching instance
            for instance in self._config.instances.values():
                if instance.host == remote_host:
                    return instance

            return None
        except Exception:
            return None

    def _extract_host(self, url: str) -> str:
        """Extract hostname from git URL (supports HTTPS and SSH)."""
        # SSH format: git@gitlab.com:group/repo.git
        if url.startswith("git@"):
            return url.split("@")[1].split(":")[0]
        # HTTPS format: https://gitlab.com/group/repo.git
        return urlparse(url).netloc

    def _get_client(self, instance: GitLabInstance) -> GitLabClient:
        """Get or create client for instance."""
        key = instance.host
        if key not in self._clients:
            self._clients[key] = GitLabClient(instance)
        return self._clients[key]

    def _resolve_project(
        self,
        project: str | None,
        cwd: str | None = None,
    ) -> str:
        """
        Resolve project path.

        Priority:
        1. Explicit project parameter
        2. Detect from git remote
        """
        if project:
            return project

        # Try to detect from git remote
        try:
            work_dir = cwd or self._container.cwd
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=work_dir,
            )
            if result.returncode == 0:
                return self._extract_project_path(result.stdout.strip())
        except Exception:
            pass

        raise ValueError("No project specified and could not detect from git remote")

    def _extract_project_path(self, url: str) -> str:
        """Extract project path from git URL."""
        # SSH format: git@gitlab.com:group/repo.git
        if url.startswith("git@"):
            path = url.split(":")[1]
        else:
            # HTTPS format: https://gitlab.com/group/repo.git
            path = urlparse(url).path.lstrip("/")

        # Remove .git suffix
        if path.endswith(".git"):
            path = path[:-4]

        return path

    async def _check_confirmation(
        self,
        instance: GitLabInstance,
        action: str,
        target: str,
    ) -> bool:
        """
        Check if skill has confirmation for this instance.

        Returns True if:
        - Permission level is YOLO (no confirmation needed)
        - Session allowance exists for this skill+instance
        - User approves via confirmation prompt

        Returns False if user denies.
        """
        # Check if YOLO mode (no confirmation needed)
        if self._container.permissions.level.name == "YOLO":
            return True

        # Check session allowance
        allowance_key = f"{self.name}@{instance.host}"
        if self._container.session_allowances.get(allowance_key):
            return True

        # Request confirmation via container's confirmation handler
        result = await self._container.request_confirmation(
            title="GitLab Access",
            message=f"{self.name} wants to connect to:\n{instance.url}\n\nAction: {action} on \"{target}\"",
            options=["Allow once", "Allow for session", "Deny"],
        )

        if result == "Deny":
            return False

        if result == "Allow for session":
            self._container.session_allowances[allowance_key] = True

        return True

    def _format_error(self, error: GitLabAPIError) -> ToolResult:
        """Format API error as ToolResult."""
        if error.status_code == 401:
            return ToolResult(
                success=False,
                error="Authentication failed. Check your GitLab token.",
            )
        if error.status_code == 403:
            return ToolResult(
                success=False,
                error="Permission denied. You may not have access to this resource.",
            )
        if error.status_code == 404:
            return ToolResult(
                success=False,
                error="Resource not found. Check the project/issue/MR exists.",
            )
        return ToolResult(success=False, error=str(error))

    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute skill with confirmation and error handling.

        Subclasses should override _execute_impl() instead of this method.
        """
        try:
            # Resolve instance
            instance = self._resolve_instance(kwargs.get("instance"))

            # Resolve project/group for confirmation message
            target = kwargs.get("project") or kwargs.get("group") or "GitLab"
            action = kwargs.get("action", "access")

            # Check confirmation
            if not await self._check_confirmation(instance, action, target):
                return ToolResult(
                    success=False,
                    error=f"Access to {instance.url} denied by user",
                )

            # Get client and execute
            client = self._get_client(instance)
            return await self._execute_impl(client, **kwargs)

        except GitLabAPIError as e:
            return self._format_error(e)
        except ValueError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            return ToolResult(success=False, error=f"Unexpected error: {e}")

    async def _execute_impl(
        self,
        client: GitLabClient,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Implement skill logic. Override in subclasses.

        Args:
            client: Authenticated GitLab client
            **kwargs: Skill parameters

        Returns:
            ToolResult with success/error status
        """
        raise NotImplementedError("Subclasses must implement _execute_impl")
```

---

### File: `nexus3/skill/vcs/gitlab/issue.py`

```python
"""GitLab issue management skill."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from nexus3.core.types import ToolResult
from nexus3.skill.vcs.gitlab.base import GitLabSkill
from nexus3.skill.vcs.gitlab.client import GitLabClient

if TYPE_CHECKING:
    from nexus3.session import ServiceContainer
    from nexus3.skill.vcs.config import GitLabConfig


class GitLabIssueSkill(GitLabSkill):
    """Create, view, update, and manage GitLab issues."""

    @property
    def name(self) -> str:
        return "gitlab_issue"

    @property
    def description(self) -> str:
        return "Create, view, update, and manage GitLab issues"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list", "get", "create", "update", "close", "reopen",
                        "comment", "link", "unlink", "list-links", "move"
                    ],
                    "description": "Action to perform",
                },
                "instance": {
                    "type": "string",
                    "description": "GitLab instance name (uses default if omitted)",
                },
                "project": {
                    "type": "string",
                    "description": "Project path (e.g., 'group/repo'). Auto-detected from git remote if omitted.",
                },
                "iid": {
                    "type": "integer",
                    "description": "Issue IID (required for get/update/close/reopen/comment/link/move)",
                },
                "title": {
                    "type": "string",
                    "description": "Issue title (required for create)",
                },
                "description": {
                    "type": "string",
                    "description": "Issue description (markdown supported)",
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Labels to apply",
                },
                "assignees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Usernames to assign",
                },
                "milestone": {
                    "type": "string",
                    "description": "Milestone title to set",
                },
                "epic_id": {
                    "type": "integer",
                    "description": "Epic ID to assign issue to (Premium)",
                },
                "weight": {
                    "type": "integer",
                    "description": "Issue weight 0-9 (Premium)",
                },
                "due_date": {
                    "type": "string",
                    "description": "Due date (YYYY-MM-DD format)",
                },
                "confidential": {
                    "type": "boolean",
                    "description": "Mark issue as confidential",
                },
                # Link parameters
                "target_iid": {
                    "type": "integer",
                    "description": "Target issue IID for linking",
                },
                "link_type": {
                    "type": "string",
                    "enum": ["relates_to", "blocks", "is_blocked_by"],
                    "description": "Relationship type for link",
                },
                "link_id": {
                    "type": "integer",
                    "description": "Link ID for unlink operation",
                },
                # Move parameters
                "target_project": {
                    "type": "string",
                    "description": "Target project path for move operation",
                },
                # List filters
                "state": {
                    "type": "string",
                    "enum": ["opened", "closed", "all"],
                    "description": "Filter by state (default: opened)",
                },
                "search": {
                    "type": "string",
                    "description": "Search in title and description",
                },
                "author": {
                    "type": "string",
                    "description": "Filter by author username",
                },
                "assignee": {
                    "type": "string",
                    "description": "Filter by assignee username (or 'None' for unassigned)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results to return (default: 20)",
                },
                # Comment parameters
                "body": {
                    "type": "string",
                    "description": "Comment body (markdown supported)",
                },
            },
            "required": ["action"],
        }

    async def _execute_impl(
        self,
        client: GitLabClient,
        **kwargs: Any,
    ) -> ToolResult:
        action = kwargs.get("action", "")
        project = self._resolve_project(kwargs.get("project"))
        project_encoded = client._encode_path(project)

        match action:
            case "list":
                return await self._list_issues(client, project_encoded, **kwargs)
            case "get":
                return await self._get_issue(client, project_encoded, kwargs["iid"])
            case "create":
                return await self._create_issue(client, project_encoded, **kwargs)
            case "update":
                return await self._update_issue(client, project_encoded, kwargs["iid"], **kwargs)
            case "close":
                return await self._close_issue(client, project_encoded, kwargs["iid"])
            case "reopen":
                return await self._reopen_issue(client, project_encoded, kwargs["iid"])
            case "comment":
                return await self._add_comment(client, project_encoded, kwargs["iid"], kwargs["body"])
            case "link":
                return await self._link_issue(
                    client, project_encoded, kwargs["iid"],
                    kwargs["target_iid"], kwargs.get("link_type", "relates_to")
                )
            case "unlink":
                return await self._unlink_issue(client, project_encoded, kwargs["iid"], kwargs["link_id"])
            case "list-links":
                return await self._list_links(client, project_encoded, kwargs["iid"])
            case "move":
                return await self._move_issue(client, project_encoded, kwargs["iid"], kwargs["target_project"])
            case _:
                return ToolResult(success=False, error=f"Unknown action: {action}")

    async def _list_issues(
        self,
        client: GitLabClient,
        project: str,
        **kwargs: Any,
    ) -> ToolResult:
        params: dict[str, Any] = {}

        if state := kwargs.get("state"):
            params["state"] = state
        if search := kwargs.get("search"):
            params["search"] = search
        if author := kwargs.get("author"):
            params["author_username"] = author
        if assignee := kwargs.get("assignee"):
            if assignee.lower() == "none":
                params["assignee_id"] = "None"
            else:
                params["assignee_username"] = assignee
        if labels := kwargs.get("labels"):
            params["labels"] = ",".join(labels)

        limit = kwargs.get("limit", 20)

        issues = [
            issue async for issue in
            client.paginate(f"/projects/{project}/issues", limit=limit, **params)
        ]

        # Format output
        lines = [f"Found {len(issues)} issue(s):"]
        for issue in issues:
            state_icon = "🟢" if issue["state"] == "opened" else "🔴"
            labels_str = f" [{', '.join(issue.get('labels', []))}]" if issue.get("labels") else ""
            lines.append(f"  {state_icon} #{issue['iid']}: {issue['title']}{labels_str}")

        return ToolResult(success=True, output="\n".join(lines))

    async def _get_issue(
        self,
        client: GitLabClient,
        project: str,
        iid: int,
    ) -> ToolResult:
        issue = await client.get(f"/projects/{project}/issues/{iid}")

        # Format detailed output
        lines = [
            f"# {issue['title']}",
            f"IID: #{issue['iid']} | State: {issue['state']} | Author: @{issue['author']['username']}",
            f"Created: {issue['created_at']} | Updated: {issue['updated_at']}",
        ]

        if issue.get("labels"):
            lines.append(f"Labels: {', '.join(issue['labels'])}")
        if issue.get("assignees"):
            assignees = [f"@{a['username']}" for a in issue["assignees"]]
            lines.append(f"Assignees: {', '.join(assignees)}")
        if issue.get("milestone"):
            lines.append(f"Milestone: {issue['milestone']['title']}")
        if issue.get("due_date"):
            lines.append(f"Due: {issue['due_date']}")
        if issue.get("weight"):
            lines.append(f"Weight: {issue['weight']}")
        if issue.get("time_stats"):
            ts = issue["time_stats"]
            if ts.get("time_estimate"):
                lines.append(f"Estimate: {ts['human_time_estimate']}")
            if ts.get("total_time_spent"):
                lines.append(f"Spent: {ts['human_total_time_spent']}")

        lines.append("")
        lines.append(issue.get("description") or "(no description)")
        lines.append("")
        lines.append(f"Web URL: {issue['web_url']}")

        return ToolResult(success=True, output="\n".join(lines))

    async def _create_issue(
        self,
        client: GitLabClient,
        project: str,
        **kwargs: Any,
    ) -> ToolResult:
        data: dict[str, Any] = {"title": kwargs["title"]}

        if description := kwargs.get("description"):
            data["description"] = description
        if labels := kwargs.get("labels"):
            data["labels"] = ",".join(labels)
        if assignees := kwargs.get("assignees"):
            # Need to resolve usernames to IDs - for now, use assignee_ids if numeric
            # or let GitLab resolve via username (may need project members lookup)
            data["assignee_ids"] = assignees  # GitLab accepts usernames in some contexts
        if milestone := kwargs.get("milestone"):
            data["milestone_id"] = milestone  # Might need resolution
        if epic_id := kwargs.get("epic_id"):
            data["epic_id"] = epic_id
        if weight := kwargs.get("weight"):
            data["weight"] = weight
        if due_date := kwargs.get("due_date"):
            data["due_date"] = due_date
        if kwargs.get("confidential"):
            data["confidential"] = True

        issue = await client.post(f"/projects/{project}/issues", **data)

        return ToolResult(
            success=True,
            output=f"Created issue #{issue['iid']}: {issue['title']}\n{issue['web_url']}",
        )

    async def _update_issue(
        self,
        client: GitLabClient,
        project: str,
        iid: int,
        **kwargs: Any,
    ) -> ToolResult:
        data: dict[str, Any] = {}

        if title := kwargs.get("title"):
            data["title"] = title
        if description := kwargs.get("description"):
            data["description"] = description
        if labels := kwargs.get("labels"):
            data["labels"] = ",".join(labels)
        if due_date := kwargs.get("due_date"):
            data["due_date"] = due_date
        if weight := kwargs.get("weight"):
            data["weight"] = weight

        if not data:
            return ToolResult(success=False, error="No fields to update")

        issue = await client.put(f"/projects/{project}/issues/{iid}", **data)

        return ToolResult(
            success=True,
            output=f"Updated issue #{issue['iid']}: {issue['title']}",
        )

    async def _close_issue(
        self,
        client: GitLabClient,
        project: str,
        iid: int,
    ) -> ToolResult:
        issue = await client.put(f"/projects/{project}/issues/{iid}", state_event="close")
        return ToolResult(success=True, output=f"Closed issue #{issue['iid']}")

    async def _reopen_issue(
        self,
        client: GitLabClient,
        project: str,
        iid: int,
    ) -> ToolResult:
        issue = await client.put(f"/projects/{project}/issues/{iid}", state_event="reopen")
        return ToolResult(success=True, output=f"Reopened issue #{issue['iid']}")

    async def _add_comment(
        self,
        client: GitLabClient,
        project: str,
        iid: int,
        body: str,
    ) -> ToolResult:
        note = await client.post(f"/projects/{project}/issues/{iid}/notes", body=body)
        return ToolResult(
            success=True,
            output=f"Added comment to issue #{iid}",
        )

    async def _link_issue(
        self,
        client: GitLabClient,
        project: str,
        iid: int,
        target_iid: int,
        link_type: str,
    ) -> ToolResult:
        link = await client.post(
            f"/projects/{project}/issues/{iid}/links",
            target_project_id=project,
            target_issue_iid=target_iid,
            link_type=link_type,
        )
        return ToolResult(
            success=True,
            output=f"Linked issue #{iid} to #{target_iid} ({link_type})",
        )

    async def _unlink_issue(
        self,
        client: GitLabClient,
        project: str,
        iid: int,
        link_id: int,
    ) -> ToolResult:
        await client.delete(f"/projects/{project}/issues/{iid}/links/{link_id}")
        return ToolResult(success=True, output=f"Removed link {link_id} from issue #{iid}")

    async def _list_links(
        self,
        client: GitLabClient,
        project: str,
        iid: int,
    ) -> ToolResult:
        links = await client.get(f"/projects/{project}/issues/{iid}/links")

        if not links:
            return ToolResult(success=True, output=f"Issue #{iid} has no linked issues")

        lines = [f"Issue #{iid} links:"]
        for link in links:
            lines.append(f"  {link['link_type']}: #{link['iid']} - {link['title']}")

        return ToolResult(success=True, output="\n".join(lines))

    async def _move_issue(
        self,
        client: GitLabClient,
        project: str,
        iid: int,
        target_project: str,
    ) -> ToolResult:
        target_encoded = client._encode_path(target_project)
        issue = await client.post(
            f"/projects/{project}/issues/{iid}/move",
            to_project_id=target_encoded,
        )
        return ToolResult(
            success=True,
            output=f"Moved issue to {target_project}#{issue['iid']}",
        )


def gitlab_issue_factory(
    container: "ServiceContainer",
    gitlab_config: "GitLabConfig",
) -> GitLabIssueSkill:
    """Factory function for GitLabIssueSkill."""
    return GitLabIssueSkill(container, gitlab_config)
```

---

### File: `nexus3/skill/vcs/gitlab/__init__.py`

```python
"""GitLab skills package."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nexus3.skill.vcs.config import GitLabConfig

if TYPE_CHECKING:
    from nexus3.skill import SkillRegistry
    from nexus3.session import ServiceContainer


def register_gitlab_skills(
    registry: "SkillRegistry",
    container: "ServiceContainer",
    gitlab_config_dict: dict,
) -> int:
    """
    Register all GitLab skills.

    Args:
        registry: Skill registry to register with
        container: Service container for dependency injection
        gitlab_config_dict: Raw gitlab config from config.json

    Returns:
        Number of skills registered
    """
    # Parse config
    config = GitLabConfig.model_validate(gitlab_config_dict)

    if not config.instances:
        return 0

    # Import skill factories
    from nexus3.skill.vcs.gitlab.issue import gitlab_issue_factory
    from nexus3.skill.vcs.gitlab.mr import gitlab_mr_factory
    from nexus3.skill.vcs.gitlab.repo import gitlab_repo_factory
    from nexus3.skill.vcs.gitlab.label import gitlab_label_factory
    from nexus3.skill.vcs.gitlab.branch import gitlab_branch_factory
    from nexus3.skill.vcs.gitlab.tag import gitlab_tag_factory
    from nexus3.skill.vcs.gitlab.epic import gitlab_epic_factory
    from nexus3.skill.vcs.gitlab.iteration import gitlab_iteration_factory
    from nexus3.skill.vcs.gitlab.milestone import gitlab_milestone_factory
    from nexus3.skill.vcs.gitlab.board import gitlab_board_factory
    from nexus3.skill.vcs.gitlab.time_tracking import gitlab_time_factory
    from nexus3.skill.vcs.gitlab.approval import gitlab_approval_factory
    from nexus3.skill.vcs.gitlab.draft_note import gitlab_draft_factory
    from nexus3.skill.vcs.gitlab.discussion import gitlab_discussion_factory
    from nexus3.skill.vcs.gitlab.pipeline import gitlab_pipeline_factory
    from nexus3.skill.vcs.gitlab.job import gitlab_job_factory
    from nexus3.skill.vcs.gitlab.artifact import gitlab_artifact_factory
    from nexus3.skill.vcs.gitlab.variable import gitlab_variable_factory
    from nexus3.skill.vcs.gitlab.deploy_key import gitlab_deploy_key_factory
    from nexus3.skill.vcs.gitlab.deploy_token import gitlab_deploy_token_factory
    from nexus3.skill.vcs.gitlab.feature_flag import gitlab_feature_flag_factory

    # Create and register skills
    factories = [
        # Phase 1: Foundation
        gitlab_repo_factory,
        gitlab_issue_factory,
        gitlab_mr_factory,
        gitlab_label_factory,
        gitlab_branch_factory,
        gitlab_tag_factory,
        # Phase 2: Project Management
        gitlab_epic_factory,
        gitlab_iteration_factory,
        gitlab_milestone_factory,
        gitlab_board_factory,
        gitlab_time_factory,
        # Phase 3: Code Review
        gitlab_approval_factory,
        gitlab_draft_factory,
        gitlab_discussion_factory,
        # Phase 4: CI/CD
        gitlab_pipeline_factory,
        gitlab_job_factory,
        gitlab_artifact_factory,
        gitlab_variable_factory,
        # Phase 5: Config & Premium
        gitlab_deploy_key_factory,
        gitlab_deploy_token_factory,
        gitlab_feature_flag_factory,
    ]

    for factory in factories:
        skill = factory(container, config)
        registry.register(skill)

    return len(factories)
```

---

### File: `nexus3/commands/gitlab.py` (REPL Command)

```python
"""REPL commands for GitLab instance management."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from nexus3.skill.vcs.config import GitLabConfig, GitLabInstance
from nexus3.skill.vcs.gitlab.client import GitLabClient, GitLabAPIError

if TYPE_CHECKING:
    from nexus3.cli.repl import Repl


async def handle_gitlab_command(repl: "Repl", args: str) -> None:
    """
    Handle /gitlab commands.

    Usage:
        /gitlab              - List configured instances
        /gitlab add <name> <url>  - Add new instance
        /gitlab remove <name>     - Remove instance
        /gitlab default <name>    - Set default instance
        /gitlab test [name]       - Test connectivity
    """
    parts = args.strip().split()

    if not parts:
        await _list_instances(repl)
    elif parts[0] == "add" and len(parts) >= 3:
        await _add_instance(repl, parts[1], parts[2])
    elif parts[0] == "remove" and len(parts) >= 2:
        await _remove_instance(repl, parts[1])
    elif parts[0] == "default" and len(parts) >= 2:
        await _set_default(repl, parts[1])
    elif parts[0] == "test":
        name = parts[1] if len(parts) > 1 else None
        await _test_instance(repl, name)
    else:
        repl.display.print(
            "Usage: /gitlab [add <name> <url> | remove <name> | default <name> | test [name]]"
        )


async def _list_instances(repl: "Repl") -> None:
    """List configured GitLab instances."""
    config = repl.config.get("gitlab", {})
    instances = config.get("instances", {})
    default = config.get("default_instance")

    if not instances:
        repl.display.print("No GitLab instances configured.")
        repl.display.print("Use /gitlab add <name> <url> to add one.")
        return

    repl.display.print("GitLab Instances:")
    for name, inst_data in instances.items():
        inst = GitLabInstance.model_validate(inst_data)
        default_marker = " (default)" if name == default else ""
        token_status = "configured" if inst.get_token() else "no token"
        repl.display.print(f"  {name}: {inst.url} ({token_status}){default_marker}")


async def _add_instance(repl: "Repl", name: str, url: str) -> None:
    """Add a new GitLab instance."""
    # Prompt for token
    token = await repl.display.prompt_secret(f"GitLab token for {url}: ")

    if not token:
        repl.display.print("No token provided. Instance not added.")
        return

    # Validate by connecting
    try:
        instance = GitLabInstance(url=url, token=token)
        client = GitLabClient(instance)
        user = await client.get_current_user()
        await client.close()
    except GitLabAPIError as e:
        repl.display.print(f"Failed to connect: {e}")
        return
    except Exception as e:
        repl.display.print(f"Invalid configuration: {e}")
        return

    # Update config
    config = repl.config.get("gitlab", {"instances": {}, "default_instance": None})
    config["instances"][name] = {
        "url": url,
        "token": token,  # In practice, should use token_env
    }
    if not config.get("default_instance"):
        config["default_instance"] = name

    repl.config["gitlab"] = config
    _save_config(repl)

    repl.display.print(f"Instance '{name}' added and authenticated as @{user['username']}")


async def _remove_instance(repl: "Repl", name: str) -> None:
    """Remove a GitLab instance."""
    config = repl.config.get("gitlab", {})
    instances = config.get("instances", {})

    if name not in instances:
        repl.display.print(f"Instance '{name}' not found.")
        return

    del instances[name]

    # Update default if needed
    if config.get("default_instance") == name:
        config["default_instance"] = next(iter(instances), None)

    repl.config["gitlab"] = config
    _save_config(repl)

    repl.display.print(f"Instance '{name}' removed.")


async def _set_default(repl: "Repl", name: str) -> None:
    """Set default GitLab instance."""
    config = repl.config.get("gitlab", {})
    instances = config.get("instances", {})

    if name not in instances:
        repl.display.print(f"Instance '{name}' not found.")
        return

    config["default_instance"] = name
    repl.config["gitlab"] = config
    _save_config(repl)

    repl.display.print(f"Default instance set to '{name}'.")


async def _test_instance(repl: "Repl", name: str | None) -> None:
    """Test connectivity to GitLab instance."""
    config = repl.config.get("gitlab", {})
    gitlab_config = GitLabConfig.model_validate(config) if config else None

    if not gitlab_config or not gitlab_config.instances:
        repl.display.print("No GitLab instances configured.")
        return

    instance = gitlab_config.get_instance(name)
    if not instance:
        repl.display.print(f"Instance '{name}' not found.")
        return

    try:
        client = GitLabClient(instance)
        user = await client.get_current_user()
        await client.close()
        repl.display.print(f"✓ Connected to {instance.url} as @{user['username']}")
    except GitLabAPIError as e:
        repl.display.print(f"✗ Connection failed: {e}")


def _save_config(repl: "Repl") -> None:
    """Save config to local .nexus3/config.json."""
    config_dir = Path(repl.cwd) / ".nexus3"
    config_dir.mkdir(exist_ok=True)
    config_path = config_dir / "config.json"

    # Merge with existing config
    existing = {}
    if config_path.exists():
        existing = json.loads(config_path.read_text())

    existing["gitlab"] = repl.config.get("gitlab", {})

    config_path.write_text(json.dumps(existing, indent=2))
```

---

### Test File: `tests/unit/skill/vcs/test_gitlab_client.py`

```python
"""Unit tests for GitLab client."""

import pytest
from unittest.mock import AsyncMock, patch

from nexus3.skill.vcs.config import GitLabInstance
from nexus3.skill.vcs.gitlab.client import GitLabClient, GitLabAPIError


@pytest.fixture
def instance():
    return GitLabInstance(
        url="https://gitlab.com",
        token="test-token",
    )


@pytest.fixture
def client(instance):
    return GitLabClient(instance)


class TestGitLabClient:
    """Tests for GitLabClient."""

    async def test_get_current_user(self, client):
        """Test getting current user."""
        with patch.object(client, "_request", new_callable=AsyncMock) as mock:
            mock.return_value = {"id": 1, "username": "testuser"}
            user = await client.get_current_user()
            assert user["username"] == "testuser"
            mock.assert_called_once_with("GET", "/user", params=None, json=None, retry=0)

    async def test_encode_path(self, client):
        """Test URL encoding of project paths."""
        assert client._encode_path("group/repo") == "group%2Frepo"
        assert client._encode_path("group/subgroup/repo") == "group%2Fsubgroup%2Frepo"

    async def test_rate_limit_retry(self, client):
        """Test retry on rate limit."""
        # Implementation depends on mocking httpx
        pass

    async def test_server_error_retry(self, client):
        """Test retry on 5xx errors."""
        pass


class TestGitLabInstance:
    """Tests for GitLabInstance configuration."""

    def test_url_validation_https(self):
        """Test HTTPS URLs are accepted."""
        inst = GitLabInstance(url="https://gitlab.com", token="x")
        assert inst.url == "https://gitlab.com"

    def test_url_validation_localhost_http(self):
        """Test HTTP localhost is accepted."""
        inst = GitLabInstance(url="http://localhost:8080", token="x")
        assert inst.url == "http://localhost:8080"

    def test_url_validation_rejects_http_remote(self):
        """Test HTTP to remote hosts is rejected."""
        with pytest.raises(ValueError):
            GitLabInstance(url="http://gitlab.example.com", token="x")

    def test_token_resolution_direct(self):
        """Test direct token is used."""
        inst = GitLabInstance(url="https://gitlab.com", token="direct-token")
        assert inst.get_token() == "direct-token"

    def test_token_resolution_env(self, monkeypatch):
        """Test env var token resolution."""
        monkeypatch.setenv("MY_TOKEN", "env-token")
        inst = GitLabInstance(url="https://gitlab.com", token_env="MY_TOKEN")
        assert inst.get_token() == "env-token"

    def test_token_resolution_none(self):
        """Test None when no token configured."""
        inst = GitLabInstance(url="https://gitlab.com")
        assert inst.get_token() is None
```

---

### Test File: `tests/integration/skill/vcs/test_gitlab_skills.py`

```python
"""Integration tests for GitLab skills.

Requires environment variables:
- GITLAB_TEST_TOKEN: Personal access token with api scope
- GITLAB_TEST_PROJECT: Project path (e.g., 'username/test-project')
"""

import os
import pytest

from nexus3.skill.vcs.config import GitLabConfig, GitLabInstance
from nexus3.skill.vcs.gitlab.client import GitLabClient
from nexus3.skill.vcs.gitlab.issue import GitLabIssueSkill


# Skip if no test credentials
pytestmark = pytest.mark.skipif(
    not os.environ.get("GITLAB_TEST_TOKEN"),
    reason="GITLAB_TEST_TOKEN not set",
)


@pytest.fixture
def gitlab_config():
    return GitLabConfig(
        instances={
            "test": GitLabInstance(
                url="https://gitlab.com",
                token=os.environ.get("GITLAB_TEST_TOKEN"),
            )
        },
        default_instance="test",
    )


@pytest.fixture
def test_project():
    return os.environ.get("GITLAB_TEST_PROJECT", "test/test-project")


class TestGitLabIssueSkillIntegration:
    """Integration tests for issue skill."""

    async def test_list_issues(self, gitlab_config, test_project, mock_container):
        """Test listing issues."""
        skill = GitLabIssueSkill(mock_container, gitlab_config)
        result = await skill.execute(action="list", project=test_project, limit=5)
        assert result.success

    async def test_create_and_close_issue(self, gitlab_config, test_project, mock_container):
        """Test creating and closing an issue."""
        skill = GitLabIssueSkill(mock_container, gitlab_config)

        # Create
        result = await skill.execute(
            action="create",
            project=test_project,
            title="[TEST] Automated test issue",
            description="This issue was created by an automated test.",
            labels=["test", "automated"],
        )
        assert result.success
        assert "Created issue #" in result.output

        # Extract IID from output
        import re
        match = re.search(r"#(\d+)", result.output)
        assert match
        iid = int(match.group(1))

        # Close
        result = await skill.execute(action="close", project=test_project, iid=iid)
        assert result.success
        assert "Closed issue" in result.output
```

---

### Integration Point: `nexus3/skill/registry.py` Changes

Add to existing skill registration:

```python
# In register_default_skills() or equivalent

def register_default_skills(
    registry: SkillRegistry,
    container: ServiceContainer,
    config: Config,
    permissions: PermissionConfig,
) -> None:
    """Register all default skills."""

    # ... existing skill registration ...

    # VCS skills (conditional based on config)
    from nexus3.skill.vcs import register_vcs_skills
    vcs_count = register_vcs_skills(registry, container, config, permissions)
    if vcs_count > 0:
        logger.info(f"Registered {vcs_count} VCS skills")
```

---

### Alignment with NEXUS3 Patterns

Based on analysis of the actual NEXUS3 codebase, here are the correct patterns to follow:

#### Skill Registration (Correct Pattern)

NEXUS3 uses `SkillSpec` with metadata caching for lazy instantiation:

```python
# nexus3/skill/registry.py pattern
@dataclass(frozen=True)
class SkillSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    factory: SkillFactory  # Callable[[ServiceContainer], Skill]

# Registration stores spec, not instance
registry.register(
    name="gitlab_issue",
    factory=gitlab_issue_factory,
    description="Create, view, update, and manage GitLab issues",
    parameters={...},  # JSON Schema
)
```

#### ServiceContainer (Correct Pattern)

ServiceContainer uses a generic dict with typed accessors:

```python
# nexus3/skill/services.py pattern
@dataclass
class ServiceContainer:
    _services: dict[str, Any] = field(default_factory=dict)

    def get(self, name: str) -> Any: ...
    def require(self, name: str) -> Any: ...  # Raises if missing
    def register(self, name: str, service: Any) -> None: ...

    # Typed accessors
    def get_permissions(self) -> AgentPermissions | None: ...
    def get_cwd(self) -> Path: ...
    def get_permission_level(self) -> PermissionLevel | None: ...
    def get_tool_allowed_paths(self, tool_name: str | None = None) -> list[Path] | None: ...
```

**For GitLab, we'll add:**
```python
# In ServiceContainer
def get_gitlab_config(self) -> GitLabConfig | None:
    return self.get("gitlab_config")

def get_session_allowances(self) -> dict[str, bool]:
    allowances = self.get("session_allowances")
    if allowances is None:
        allowances = {}
        self.register("session_allowances", allowances)
    return allowances
```

#### Factory Pattern (Correct Pattern)

Use the existing `*_skill_factory` decorators for base classes:

```python
# For network skills, create a new base similar to NexusSkill
def gitlab_skill_factory(cls: type[GitLabSkill]) -> SkillFactory:
    """Factory wrapper for GitLab skills."""

    def factory(services: ServiceContainer) -> GitLabSkill:
        gitlab_config = services.get_gitlab_config()
        if not gitlab_config:
            raise ValueError("GitLab not configured")
        return cls(services, gitlab_config)

    return factory


# Usage
class GitLabIssueSkill(GitLabSkill):
    ...

gitlab_issue_factory = gitlab_skill_factory(GitLabIssueSkill)
```

#### Confirmation Pattern (Correct Pattern)

NEXUS3 uses `ConfirmationResult` enum and `ConfirmationController`:

```python
# nexus3/core/permissions.py
class ConfirmationResult(Enum):
    DENY = "deny"
    ALLOW_ONCE = "allow_once"
    ALLOW_FILE = "allow_file"
    ALLOW_WRITE_DIRECTORY = "allow_write_directory"
    ALLOW_EXEC_CWD = "allow_exec_cwd"
    ALLOW_EXEC_GLOBAL = "allow_exec_global"
```

**For GitLab, add new result types:**
```python
# Add to ConfirmationResult enum
ALLOW_GITLAB_SKILL = "allow_gitlab_skill"  # Allow this skill for session
ALLOW_GITLAB_INSTANCE = "allow_gitlab_instance"  # Allow all skills for this instance
```

**Or use session_allowances dict directly:**
```python
# In PermissionEnforcer or GitLabSkill base
def requires_gitlab_confirmation(
    self,
    skill_name: str,
    instance_host: str,
    permission_level: PermissionLevel,
) -> bool:
    """Check if GitLab skill requires confirmation."""
    if permission_level == PermissionLevel.YOLO:
        return False

    allowances = self._services.get_session_allowances()
    key = f"{skill_name}@{instance_host}"
    return not allowances.get(key, False)
```

#### Config Integration (Correct Pattern)

Add GitLab config to existing Pydantic schema:

```python
# nexus3/config/schema.py additions

class GitLabInstanceConfig(BaseModel):
    """Single GitLab instance configuration."""
    url: str
    token: str | None = None
    token_env: str | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        from nexus3.core.url_validator import validate_url
        return validate_url(v, allow_localhost=True, allow_private=False)


class GitLabConfig(BaseModel):
    """GitLab integration configuration."""
    instances: dict[str, GitLabInstanceConfig] = {}
    default_instance: str | None = None

    @model_validator(mode="after")
    def validate_default(self) -> "GitLabConfig":
        if self.default_instance and self.default_instance not in self.instances:
            raise ValueError(f"default_instance '{self.default_instance}' not in instances")
        if not self.default_instance and self.instances:
            self.default_instance = next(iter(self.instances))
        return self


# Add to main Config class
class Config(BaseModel):
    # ... existing fields ...
    gitlab: GitLabConfig | None = None
```

#### Destructive Tools Registration

Add write-capable GitLab skills to destructive_tools for confirmation:

```python
# In config schema or PermissionsConfig
GITLAB_DESTRUCTIVE_SKILLS = [
    "gitlab_issue",  # create, update, close, delete
    "gitlab_mr",     # create, merge, close
    "gitlab_epic",   # create, update, delete
    "gitlab_repo",   # create, delete, archive
    "gitlab_variable",  # create, update, delete
    "gitlab_deploy_key",
    "gitlab_deploy_token",
    "gitlab_feature_flag",
]

# These trigger confirmation in TRUSTED mode
```

---

### Updated File: `nexus3/skill/vcs/gitlab/base.py` (Aligned)

```python
"""Base class for GitLab skills - aligned with NEXUS3 patterns."""

from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING
from urllib.parse import urlparse

from nexus3.core.types import ToolResult
from nexus3.core.permissions import PermissionLevel
from nexus3.skill.vcs.gitlab.client import GitLabClient, GitLabAPIError

if TYPE_CHECKING:
    from nexus3.skill.services import ServiceContainer
    from nexus3.skill.vcs.config import GitLabConfig, GitLabInstance


class GitLabSkill(ABC):
    """
    Base class for all GitLab skills.

    Aligned with NEXUS3 patterns:
    - Uses ServiceContainer for dependency injection
    - Uses existing confirmation patterns
    - Follows Skill protocol (name, description, parameters, execute)
    """

    def __init__(
        self,
        services: "ServiceContainer",
        gitlab_config: "GitLabConfig",
    ):
        self._services = services
        self._config = gitlab_config
        self._clients: dict[str, GitLabClient] = {}

    @property
    @abstractmethod
    def name(self) -> str:
        """Skill name for registration."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description."""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for parameters."""
        ...

    def _get_cwd(self) -> str:
        """Get current working directory from services."""
        return str(self._services.get_cwd())

    def _get_permission_level(self) -> PermissionLevel:
        """Get current permission level."""
        level = self._services.get_permission_level()
        return level or PermissionLevel.SANDBOXED

    def _resolve_instance(self, instance_name: str | None = None) -> "GitLabInstance":
        """Resolve which GitLab instance to use."""
        if instance_name:
            instance = self._config.get_instance(instance_name)
            if not instance:
                raise ValueError(f"GitLab instance '{instance_name}' not configured")
            return instance

        # Try git remote detection
        detected = self._detect_instance_from_remote()
        if detected:
            return detected

        # Fall back to default
        instance = self._config.get_instance()
        if not instance:
            raise ValueError("No GitLab instance configured")
        return instance

    def _detect_instance_from_remote(self) -> "GitLabInstance | None":
        """Detect GitLab instance from git remote."""
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=self._get_cwd(),
            )
            if result.returncode != 0:
                return None

            remote_url = result.stdout.strip()
            remote_host = self._extract_host(remote_url)

            for instance in self._config.instances.values():
                if instance.host == remote_host:
                    return instance
            return None
        except Exception:
            return None

    def _extract_host(self, url: str) -> str:
        """Extract hostname from git URL."""
        if url.startswith("git@"):
            return url.split("@")[1].split(":")[0]
        return urlparse(url).netloc

    def _get_client(self, instance: "GitLabInstance") -> GitLabClient:
        """Get or create client for instance."""
        key = instance.host
        if key not in self._clients:
            self._clients[key] = GitLabClient(instance)
        return self._clients[key]

    def _resolve_project(self, project: str | None) -> str:
        """Resolve project path from param or git remote."""
        if project:
            return project

        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=self._get_cwd(),
            )
            if result.returncode == 0:
                return self._extract_project_path(result.stdout.strip())
        except Exception:
            pass

        raise ValueError("No project specified and could not detect from git remote")

    def _extract_project_path(self, url: str) -> str:
        """Extract project path from git URL."""
        if url.startswith("git@"):
            path = url.split(":")[1]
        else:
            path = urlparse(url).path.lstrip("/")
        return path.removesuffix(".git")

    def _check_session_allowance(self, instance_host: str) -> bool:
        """Check if skill is allowed for this instance in current session."""
        allowances = self._services.get("session_allowances") or {}
        key = f"{self.name}@{instance_host}"
        return allowances.get(key, False)

    def _set_session_allowance(self, instance_host: str) -> None:
        """Mark skill as allowed for this instance in current session."""
        allowances = self._services.get("session_allowances")
        if allowances is None:
            allowances = {}
            self._services.register("session_allowances", allowances)
        key = f"{self.name}@{instance_host}"
        allowances[key] = True

    def _format_error(self, error: GitLabAPIError) -> ToolResult:
        """Format API error as ToolResult."""
        if error.status_code == 401:
            return ToolResult(success=False, error="Authentication failed. Check GitLab token.")
        if error.status_code == 403:
            return ToolResult(success=False, error="Permission denied.")
        if error.status_code == 404:
            return ToolResult(success=False, error="Resource not found.")
        return ToolResult(success=False, error=str(error))

    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute skill with error handling.

        Confirmation is handled by PermissionEnforcer before this is called,
        similar to other destructive tools.
        """
        try:
            instance = self._resolve_instance(kwargs.get("instance"))
            client = self._get_client(instance)
            return await self._execute_impl(client, **kwargs)

        except GitLabAPIError as e:
            return self._format_error(e)
        except ValueError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            return ToolResult(success=False, error=f"Unexpected error: {e}")

    @abstractmethod
    async def _execute_impl(
        self,
        client: GitLabClient,
        **kwargs: Any,
    ) -> ToolResult:
        """Implement skill logic. Override in subclasses."""
        ...


def gitlab_skill_factory(cls: type[GitLabSkill]):
    """
    Factory wrapper for GitLab skills.

    Returns a factory function compatible with SkillRegistry.
    """
    def factory(services: "ServiceContainer") -> GitLabSkill:
        gitlab_config = services.get("gitlab_config")
        if not gitlab_config:
            raise ValueError("GitLab not configured - skill should not be registered")
        return cls(services, gitlab_config)

    # Attach metadata for lazy registration
    factory.skill_class = cls
    return factory
```

---

## Dependencies

**Required:**
- `httpx` - Already used in NEXUS3 for async HTTP

**Optional:**
- `keyring` - Secure token storage (defer to later)
- `python-gitlab` - Consider if REST client becomes unwieldy (avoid for now)

---

## Success Criteria

### Functional
1. Agent can perform complete issue triage workflow (list, comment, label, close)
2. Agent can create and manage epics with child issues
3. Agent can review MRs (view diff, add comments, approve)
4. Agent can monitor and debug CI pipelines (view status, read logs)
5. Agent can manage iterations and track time for sprint planning

### Security
6. GitLab skills only registered when GitLab is configured
7. SANDBOXED agents have no GitLab tools available (no context pollution)
8. TRUSTED agents see confirmation prompts on first skill use
9. Session allowances persist correctly and reset on session end
10. URL validation blocks non-HTTPS and cloud metadata endpoints

### Integration
11. All skills integrate with NEXUS3 permission system
12. Token auth works via env var, config file, or interactive prompt
13. Multiple GitLab instances supported with named configuration
14. `/gitlab` REPL commands work for instance management

---

## Implementation Checklist

Use this checklist to track implementation progress. Each item can be assigned to a task agent.

### Phase 1: Foundation (Required First)

- [ ] **P1.1** Create `nexus3/skill/vcs/` directory structure
- [ ] **P1.2** Implement `nexus3/skill/vcs/config.py` (GitLabConfig, GitLabInstance)
- [ ] **P1.3** Implement `nexus3/skill/vcs/gitlab/client.py` (GitLabClient)
- [ ] **P1.4** Implement `nexus3/skill/vcs/gitlab/base.py` (GitLabSkill base class)
- [ ] **P1.5** Add GitLab config to `nexus3/config/schema.py`
- [ ] **P1.6** Add `get_gitlab_config()` to ServiceContainer
- [ ] **P1.7** Implement `nexus3/skill/vcs/gitlab/__init__.py` (registration)
- [ ] **P1.8** Integrate with skill registry in `nexus3/skill/registry.py`
- [ ] **P1.9** Add session_allowances support to ServiceContainer
- [ ] **P1.10** Implement `gitlab_repo` skill
- [ ] **P1.11** Implement `gitlab_issue` skill
- [ ] **P1.12** Implement `gitlab_mr` skill (basic)
- [ ] **P1.13** Implement `gitlab_label` skill
- [ ] **P1.14** Implement `gitlab_branch` skill
- [ ] **P1.15** Implement `gitlab_tag` skill
- [ ] **P1.16** Implement `/gitlab` REPL command (`nexus3/commands/gitlab.py`)
- [ ] **P1.17** Add unit tests for GitLabClient
- [ ] **P1.18** Add unit tests for GitLabConfig
- [ ] **P1.19** Add unit tests for base skill patterns
- [ ] **P1.20** Integration test with real GitLab (optional, requires token)

### Phase 2: Project Management

- [ ] **P2.1** Implement `gitlab_epic` skill
- [ ] **P2.2** Implement `gitlab_iteration` skill
- [ ] **P2.3** Implement `gitlab_milestone` skill
- [ ] **P2.4** Implement `gitlab_board` skill
- [ ] **P2.5** Implement `gitlab_time` skill
- [ ] **P2.6** Add link actions to `gitlab_issue`
- [ ] **P2.7** Add link actions to `gitlab_epic`
- [ ] **P2.8** Unit tests for Phase 2 skills

### Phase 3: Code Review

- [ ] **P3.1** Add diff/commits/pipelines to `gitlab_mr`
- [ ] **P3.2** Implement `gitlab_approval` skill
- [ ] **P3.3** Implement `gitlab_draft` skill
- [ ] **P3.4** Implement `gitlab_discussion` skill
- [ ] **P3.5** Unit tests for Phase 3 skills

### Phase 4: CI/CD

- [ ] **P4.1** Implement `gitlab_pipeline` skill
- [ ] **P4.2** Implement `gitlab_job` skill
- [ ] **P4.3** Implement `gitlab_artifact` skill
- [ ] **P4.4** Implement `gitlab_variable` skill
- [ ] **P4.5** Unit tests for Phase 4 skills

### Phase 5: Config & Premium

- [ ] **P5.1** Add protection to `gitlab_branch`
- [ ] **P5.2** Add protection to `gitlab_tag`
- [ ] **P5.3** Implement `gitlab_deploy_key` skill
- [ ] **P5.4** Implement `gitlab_deploy_token` skill
- [ ] **P5.5** Implement `gitlab_feature_flag` skill
- [ ] **P5.6** Unit tests for Phase 5 skills

### Phase 6: Integration & Testing

- [ ] **P6.1** Add GitLab confirmation handling to PermissionEnforcer
- [ ] **P6.2** Add destructive GitLab skills to confirmation list
- [ ] **P6.3** E2E test: Full workflow (create issue → link to epic → track time)
- [ ] **P6.4** Live testing with real GitLab instance

### Phase 7: Documentation

- [ ] **P7.1** Update `CLAUDE.md` Built-in Skills table with all GitLab skills
- [ ] **P7.2** Update `CLAUDE.md` Configuration section with GitLab config example
- [ ] **P7.3** Add GitLab section to `nexus3/skill/README.md`
- [ ] **P7.4** Create `nexus3/skill/vcs/README.md` with module documentation
- [ ] **P7.5** Document `/gitlab` command in REPL Commands Reference
- [ ] **P7.6** Ensure all skill `description` properties are comprehensive

---

## Quick Reference: File Locations

| Component | File Path |
|-----------|-----------|
| Config models | `nexus3/skill/vcs/config.py` |
| GitLab client | `nexus3/skill/vcs/gitlab/client.py` |
| Base skill class | `nexus3/skill/vcs/gitlab/base.py` |
| Registration | `nexus3/skill/vcs/gitlab/__init__.py` |
| VCS entry point | `nexus3/skill/vcs/__init__.py` |
| Individual skills | `nexus3/skill/vcs/gitlab/{name}.py` |
| REPL command | `nexus3/commands/gitlab.py` |
| Config schema | `nexus3/config/schema.py` |
| Unit tests | `tests/unit/skill/vcs/` |
| Integration tests | `tests/integration/skill/vcs/` |

---

## API Endpoints Quick Reference

Common GitLab API patterns used by skills:

| Skill | Key Endpoints |
|-------|--------------|
| `gitlab_issue` | `GET/POST/PUT /projects/:id/issues/:iid` |
| `gitlab_mr` | `GET/POST/PUT /projects/:id/merge_requests/:iid` |
| `gitlab_epic` | `GET/POST/PUT /groups/:id/epics/:iid` |
| `gitlab_iteration` | `GET/POST /groups/:id/iterations` |
| `gitlab_pipeline` | `GET/POST /projects/:id/pipelines/:id` |
| `gitlab_job` | `GET/POST /projects/:id/jobs/:id` |

**URL encoding**: Project paths like `group/subgroup/repo` must be URL-encoded as `group%2Fsubgroup%2Frepo` using `urllib.parse.quote(path, safe="")`
