# nexus3.skill.vcs.gitlab

GitLab skill implementations for NEXUS3.

## Overview

This package provides the concrete GitLab integration registered by
`register_gitlab_skills(...)` in
[`__init__.py`](/home/inc/repos/NEXUS3/nexus3/skill/vcs/gitlab/__init__.py).
When configuration and permissions allow it, the package currently registers
**21 GitLab skills**.

Skill families:

- Foundation: `gitlab_repo`, `gitlab_issue`, `gitlab_mr`, `gitlab_label`,
  `gitlab_branch`, `gitlab_tag`
- Project management: `gitlab_epic`, `gitlab_iteration`,
  `gitlab_milestone`, `gitlab_board`, `gitlab_time`
- Code review: `gitlab_approval`, `gitlab_draft`, `gitlab_discussion`
- CI/CD: `gitlab_pipeline`, `gitlab_job`, `gitlab_artifact`,
  `gitlab_variable`
- Configuration: `gitlab_deploy_key`, `gitlab_deploy_token`,
  `gitlab_feature_flag`

Supporting modules:

- [`base.py`](/home/inc/repos/NEXUS3/nexus3/skill/vcs/gitlab/base.py)
  - shared `GitLabSkill` base class
- [`client.py`](/home/inc/repos/NEXUS3/nexus3/skill/vcs/gitlab/client.py)
  - async HTTP client and API helpers
- [`permissions.py`](/home/inc/repos/NEXUS3/nexus3/skill/vcs/gitlab/permissions.py)
  - permission and confirmation logic

Registration behavior:

- returns `0` and registers nothing when GitLab is not configured
- returns `0` for agents that cannot use GitLab
- otherwise registers all 21 GitLab skill factories

For user-facing behavior and configuration, see
[`nexus3/skill/vcs/README.md`](/home/inc/repos/NEXUS3/nexus3/skill/vcs/README.md)
and [`nexus3/skill/README.md`](/home/inc/repos/NEXUS3/nexus3/skill/README.md).
