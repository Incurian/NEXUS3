# nexus3.skill.vcs - Version Control Service Integrations

Version-control platform integrations for NEXUS3. The package currently
registers GitLab skills when configuration and permissions allow it, while
leaving a narrow extension point for future providers such as GitHub.

## Overview

This package is intentionally small. It does not implement VCS behavior
directly; instead it owns the top-level registration gate that decides whether
provider-specific VCS skills should appear for the current agent.

Current behavior:

- only GitLab is implemented today
- VCS skills are hidden from `SANDBOXED` agents
- registration is config-driven; no arbitrary ad-hoc VCS endpoints are exposed
- destructive actions use the same confirmation and allowance model as other
  security-sensitive tool families

## Package Structure

```text
nexus3/skill/vcs/
├── README.md        # This file
├── __init__.py      # register_vcs_skills(...) entry point
└── gitlab/          # Concrete GitLab skill package
    ├── __init__.py  # register_gitlab_skills(...)
    ├── base.py      # Shared GitLabSkill base class
    ├── client.py    # Async GitLab HTTP client
    ├── permissions.py
    └── <skill>.py   # Individual GitLab skill implementations
```

There is intentionally no local `config.py` in this package. GitLab config
models live in the main config schema under
[`nexus3/config/README.md`](/home/inc/repos/NEXUS3/nexus3/config/README.md)
and [`nexus3/config/schema.py`](/home/inc/repos/NEXUS3/nexus3/config/schema.py).

## Visibility And Safety

| Requirement | Behavior |
|-------------|----------|
| Pre-configured instances only | Skills are registered only for configured GitLab instances from `config.json` |
| `TRUSTED` or `YOLO` required | `SANDBOXED` agents never get GitLab skills |
| Read-only actions | Allowed without confirmation |
| Destructive actions in `TRUSTED` | Require confirmation unless a matching session allowance already exists |
| Session allowances | Persist the approved `skill@instance` pair for the session |
| SSRF protection | All GitLab HTTP traffic uses URL validation and controlled instance configuration |

The package-level gate delegates the detailed confirmation logic to
[`gitlab/permissions.py`](/home/inc/repos/NEXUS3/nexus3/skill/vcs/gitlab/permissions.py).

## GitLab Surface

When GitLab is visible and configured, the package registers **21 GitLab
skills**:

- Foundation: `gitlab_repo`, `gitlab_issue`, `gitlab_mr`, `gitlab_label`,
  `gitlab_branch`, `gitlab_tag`
- Project management: `gitlab_epic`, `gitlab_iteration`,
  `gitlab_milestone`, `gitlab_board`, `gitlab_time`
- Code review: `gitlab_approval`, `gitlab_draft`, `gitlab_discussion`
- CI/CD: `gitlab_pipeline`, `gitlab_job`, `gitlab_artifact`,
  `gitlab_variable`
- Configuration: `gitlab_deploy_key`, `gitlab_deploy_token`,
  `gitlab_feature_flag`

The shared GitLab runtime lives under
[`gitlab/README.md`](/home/inc/repos/NEXUS3/nexus3/skill/vcs/gitlab/README.md),
with common behavior centered in:

- [`base.py`](/home/inc/repos/NEXUS3/nexus3/skill/vcs/gitlab/base.py) for
  instance resolution, project autodetection, and client caching
- [`client.py`](/home/inc/repos/NEXUS3/nexus3/skill/vcs/gitlab/client.py) for
  async HTTP operations, retries, pagination, and raw/text helpers
- [`permissions.py`](/home/inc/repos/NEXUS3/nexus3/skill/vcs/gitlab/permissions.py)
  for visibility and confirmation rules

## Configuration

GitLab configuration lives in the root config schema:

```json
{
  "gitlab": {
    "instances": {
      "gitlab": {
        "url": "https://gitlab.com",
        "token_env": "GITLAB_TOKEN",
        "username": "your-username",
        "email": "you@example.com"
      }
    },
    "default_instance": "gitlab"
  }
}
```

Important config behavior:

- each instance uses either `token` or `token_env`
- `default_instance` must refer to a configured instance name
- skill execution can auto-detect the instance and project from the current git
  remote when the request omits them

For the authoritative config fields, see
[`nexus3/config/README.md`](/home/inc/repos/NEXUS3/nexus3/config/README.md)
and the `GitLabConfig` / `GitLabInstanceConfig` models in
[`nexus3/config/schema.py`](/home/inc/repos/NEXUS3/nexus3/config/schema.py).

## Registration

Top-level registration happens in
[`__init__.py`](/home/inc/repos/NEXUS3/nexus3/skill/vcs/__init__.py):

```python
count = register_vcs_skills(
    registry,
    services,
    permissions,
    gitlab_visible=None,
)
```

Current registration rules:

- return `0` when no GitLab instances are configured
- return `0` when the current agent cannot use GitLab
- otherwise defer to `register_gitlab_skills(...)` and return the number of
  registered GitLab skill factories

The optional `gitlab_visible` override is used by higher-level runtime wiring
that needs to compute or restore agent state without re-deriving visibility in
multiple places.

## Future Providers

`register_vcs_skills(...)` keeps a commented placeholder for future GitHub
registration, but no GitHub package ships today. The current public VCS surface
is GitLab-only.

## Related Docs

- GitLab package details:
  [`nexus3/skill/vcs/gitlab/README.md`](/home/inc/repos/NEXUS3/nexus3/skill/vcs/gitlab/README.md)
- Skill-system overview:
  [`nexus3/skill/README.md`](/home/inc/repos/NEXUS3/nexus3/skill/README.md)
- Config reference:
  [`nexus3/config/README.md`](/home/inc/repos/NEXUS3/nexus3/config/README.md)
