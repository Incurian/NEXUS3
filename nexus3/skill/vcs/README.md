# nexus3.skill.vcs - Version Control System Integrations

**Updated: 2026-01-31**

VCS skills provide integration with external version control platforms. Currently supports GitLab, with GitHub planned for future.

---

## Table of Contents

1. [Overview](#overview)
2. [Directory Structure](#directory-structure)
3. [Security Model](#security-model)
4. [GitLab Integration](#gitlab-integration)
5. [Configuration](#configuration)
6. [Registration](#registration)

---

## Overview

VCS skills enable NEXUS3 agents to interact with external version control platforms for:

- Repository management
- Issue and merge request workflows
- CI/CD pipeline operations
- Project configuration

All VCS skills require TRUSTED+ permissions and pre-configured instances. SANDBOXED agents cannot access external VCS providers.

---

## Directory Structure

```
nexus3/skill/vcs/
├── README.md           # This file
├── __init__.py         # register_vcs_skills() entry point
├── config.py           # GitLabConfig, GitLabInstance dataclasses
└── gitlab/             # GitLab skill implementations
    ├── __init__.py     # register_gitlab_skills() function
    ├── base.py         # GitLabSkill base class
    ├── client.py       # Async HTTP client (httpx-based)
    ├── permissions.py  # Permission checks and confirmation logic
    └── <skill>.py      # 21 individual skill files
```

---

## Security Model

| Requirement | Description |
|-------------|-------------|
| Pre-configured instances | No arbitrary server connections; instances must be in config.json |
| TRUSTED+ required | SANDBOXED agents cannot use VCS skills |
| Confirmation prompts | Destructive actions require confirmation in TRUSTED mode |
| Session allowances | Once confirmed, skill@instance pairs are stored for session |
| SSRF protection | URL validation on all requests, no redirect following |

### Permission Levels

| Level | VCS Access |
|-------|------------|
| YOLO | Full access, no confirmations |
| TRUSTED | Full access, confirmations for destructive actions |
| SANDBOXED | No VCS access (network blocked) |

---

## GitLab Integration

### Skills (21 total)

| Phase | Skills | Description |
|-------|--------|-------------|
| Foundation | `gitlab_repo`, `gitlab_issue`, `gitlab_mr`, `gitlab_label`, `gitlab_branch`, `gitlab_tag` | Core repository operations |
| Project Management | `gitlab_epic`, `gitlab_iteration`, `gitlab_milestone`, `gitlab_board`, `gitlab_time` | Planning and tracking |
| Code Review | `gitlab_approval`, `gitlab_draft`, `gitlab_discussion` | MR review workflows |
| CI/CD | `gitlab_pipeline`, `gitlab_job`, `gitlab_artifact`, `gitlab_variable` | Build and deployment |
| Config | `gitlab_deploy_key`, `gitlab_deploy_token`, `gitlab_feature_flag` | Project configuration |

### Base Class

`GitLabSkill` in `base.py` provides shared infrastructure:

```python
class GitLabSkill(BaseSkill):
    """
    Base class for all GitLab skills.

    Provides:
    - Instance resolution (which GitLab to connect to)
    - Client management (lazy initialization, caching)
    - Project resolution from git remote
    - Standard error handling
    """
```

Key methods:
- `_resolve_instance()` - Select GitLab instance by name or auto-detect from git remote
- `_get_client()` - Get or create cached HTTP client for instance
- `_resolve_project()` - Resolve project path from parameter or git remote
- `_execute_impl()` - Override in subclasses to implement skill logic

### HTTP Client

`GitLabClient` in `client.py` provides async HTTP operations:

- Native async with httpx (no python-gitlab dependency)
- SSRF protection via URL validation
- Automatic retry with exponential backoff
- Rate limit handling (429 responses)
- Pagination support for list endpoints
- Connection pooling and lazy initialization

### Action Pattern

Skills use action-based dispatch:

```python
async def _execute_impl(self, client: GitLabClient, **kwargs) -> ToolResult:
    action = kwargs.get("action", "list")
    match action:
        case "list":
            return await self._list(client, **kwargs)
        case "get":
            return await self._get(client, **kwargs)
        case "create":
            return await self._create(client, **kwargs)
        # ...
```

---

## Configuration

GitLab configuration in `config.json`:

```json
{
  "gitlab": {
    "instances": {
      "gitlab": {
        "url": "https://gitlab.com",
        "token_env": "GITLAB_TOKEN"
      },
      "internal": {
        "url": "https://gitlab.internal.company.com",
        "token": "glpat-xxxxxxxxxxxx"
      }
    },
    "default_instance": "gitlab"
  }
}
```

### Config Classes

| Class | Description |
|-------|-------------|
| `GitLabInstance` | Single instance config (url, token/token_env) |
| `GitLabConfig` | Collection of instances with default selection |

Token resolution order:
1. Direct `token` value in config
2. Environment variable from `token_env`
3. None (triggers authentication error)

---

## Registration

VCS skills are registered via `register_vcs_skills()` in `__init__.py`:

```python
from nexus3.skill.vcs import register_vcs_skills

# Called by session setup
count = register_vcs_skills(registry, services, permissions)
```

Registration is conditional:
1. Check if GitLab config exists in services
2. Check if permission level is TRUSTED+
3. If both pass, register all 21 GitLab skill factories

Skills are registered as factories that capture the GitLab config:

```python
def make_factory(skill_class):
    def factory(svc: ServiceContainer):
        config = svc.get_gitlab_config()
        if not config:
            raise ValueError("GitLab not configured")
        return skill_class(svc, config)
    return factory
```

---

## Future: GitHub Integration

GitHub skills are planned but not yet implemented. The structure will mirror GitLab:

```
nexus3/skill/vcs/
├── github/
│   ├── __init__.py     # register_github_skills()
│   ├── base.py         # GitHubSkill base class
│   ├── client.py       # GitHub API client (or gh CLI wrapper)
│   └── <skill>.py      # Individual skills
└── config.py           # Add GitHubConfig, GitHubInstance
```

The `register_vcs_skills()` function already has placeholder logic for GitHub:

```python
# GitHub skills (future)
# github_config = services.get_github_config()
# if github_config and github_config.instances:
#     from nexus3.skill.vcs.github import register_github_skills
#     count += register_github_skills(registry, services, permissions)
```
