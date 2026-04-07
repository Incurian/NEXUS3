# nexus3.skill.vcs.gitlab

GitLab skill implementations for NEXUS3.

## Overview

This package provides the concrete GitLab integration registered by
`register_gitlab_skills(...)` in
[`__init__.py`](/home/inc/repos/NEXUS3/nexus3/skill/vcs/gitlab/__init__.py).
When configuration and permissions allow it, the package currently registers
**21 GitLab skills**.

## Package Structure

- [`__init__.py`](/home/inc/repos/NEXUS3/nexus3/skill/vcs/gitlab/__init__.py)
  - registration entry point and compatibility exports
- [`base.py`](/home/inc/repos/NEXUS3/nexus3/skill/vcs/gitlab/base.py)
  - shared `GitLabSkill` base class for instance/project resolution and client
    caching
- [`client.py`](/home/inc/repos/NEXUS3/nexus3/skill/vcs/gitlab/client.py)
  - async HTTP client with SSRF checks, retries, pagination, and raw helpers
- [`permissions.py`](/home/inc/repos/NEXUS3/nexus3/skill/vcs/gitlab/permissions.py)
  - visibility checks plus destructive-action confirmation rules
- `*.py`
  - one skill family implementation per GitLab surface area

## Skill Families

- Foundation: `gitlab_repo`, `gitlab_issue`, `gitlab_mr`, `gitlab_label`,
  `gitlab_branch`, `gitlab_tag`
- Project management: `gitlab_epic`, `gitlab_iteration`,
  `gitlab_milestone`, `gitlab_board`, `gitlab_time`
- Code review: `gitlab_approval`, `gitlab_draft`, `gitlab_discussion`
- CI/CD: `gitlab_pipeline`, `gitlab_job`, `gitlab_artifact`,
  `gitlab_variable`
- Configuration: `gitlab_deploy_key`, `gitlab_deploy_token`,
  `gitlab_feature_flag`

## Shared Runtime Behavior

- instance resolution priority is:
  1. explicit `instance`
  2. auto-detected instance from the current git remote
  3. configured default instance
- project resolution priority is:
  1. explicit `project` unless it is `"this"`
  2. git-remote autodetection from the current working tree
- GitLab clients are cached per instance host inside `GitLabSkill`
- user-facing API errors are normalized through the shared client/base helpers

## Registration Behavior

- returns `0` and registers nothing when GitLab is not configured
- returns `0` for agents that cannot use GitLab
- otherwise registers all 21 GitLab skill factories
- uses deferred imports so the package can fail closed if a skill module is
  missing during phased work
- wraps constructed skill instances with the shared validation adapter before
  exposing them through the registry

## Permission Model

- GitLab visibility requires `TRUSTED` or `YOLO`; `SANDBOXED` agents do not get
  GitLab skills
- read-only actions never require confirmation
- destructive actions require confirmation in `TRUSTED` mode unless the
  `skill@instance` pair is already allowed in session allowances
- `YOLO` skips the confirmation layer but still uses the same configured
  instance list and SSRF validation

## Related Docs

- VCS-level overview and config model:
  [`nexus3/skill/vcs/README.md`](/home/inc/repos/NEXUS3/nexus3/skill/vcs/README.md)
- Tool-system overview:
  [`nexus3/skill/README.md`](/home/inc/repos/NEXUS3/nexus3/skill/README.md)
- GitLab config models:
  [`nexus3/config/README.md`](/home/inc/repos/NEXUS3/nexus3/config/README.md)
