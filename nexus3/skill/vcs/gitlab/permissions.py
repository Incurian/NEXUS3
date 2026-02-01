"""GitLab-specific permission checks.

These functions determine whether an agent can use GitLab tools and if
confirmation is required for GitLab skill actions.

Security model:
- Only TRUSTED and YOLO agents can use GitLab tools
- SANDBOXED agents cannot access external VCS providers
- TRUSTED agents require confirmation for destructive actions
- Once allowed, skill@instance pairs are stored in session allowances

Read-only actions (list, get, search, diff, etc.) never require confirmation.
Destructive actions (create, update, delete, merge, etc.) require confirmation
in TRUSTED mode unless the skill@instance is already allowed in the session.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nexus3.core.permissions import PermissionLevel

if TYPE_CHECKING:
    from nexus3.core.permissions import AgentPermissions

logger = logging.getLogger(__name__)


# Actions that only read data - never require confirmation
GITLAB_READ_ONLY_ACTIONS = frozenset({
    # List/get operations
    "list",
    "get",
    "search",
    # MR inspection
    "diff",
    "commits",
    "pipelines",
    # Job/pipeline inspection
    "jobs",
    "variables",
    "log",
    "status",
    # Artifact browsing (not download)
    "browse",
    # Protection listing
    "list-protected",
    # Feature flag user lists
    "list-user-lists",
    # Cadence listing (iterations)
    "cadences",
})


# Actions that modify data - require confirmation in TRUSTED mode
GITLAB_DESTRUCTIVE_ACTIONS = frozenset({
    # CRUD operations
    "create",
    "update",
    "delete",
    # State changes
    "close",
    "reopen",
    "merge",
    # Approvals
    "approve",
    "unapprove",
    # Comments/discussions
    "comment",
    "reply",
    "resolve",
    "unresolve",
    "publish",
    # Issue/epic links
    "add",
    "remove",
    # Time tracking
    "spend",
    "estimate",
    "reset",
    # CI/CD operations
    "retry",
    "cancel",
    "play",
    "erase",
    # Downloads (could be large/sensitive)
    "download",
    "download-file",
    "download-ref",
    # Artifact management
    "keep",
    # Protection management
    "protect",
    "unprotect",
    # Deploy key operations
    "enable",
    # Feature flag user lists
    "create-user-list",
    "update-user-list",
    "delete-user-list",
    # Forking
    "fork",
})


def can_use_gitlab(permissions: AgentPermissions | None) -> bool:
    """Check if agent can use GitLab tools.

    GitLab tools require TRUSTED+ (no SANDBOXED).
    Returns True if YOLO or TRUSTED, False otherwise.

    Args:
        permissions: Agent permissions. If None, GitLab access is denied.

    Returns:
        True if GitLab is allowed (YOLO/TRUSTED with explicit permissions).
        False for SANDBOXED, or if no permissions set.
    """
    if permissions is None:
        logger.debug("GitLab access denied: no permissions configured")
        return False
    level = permissions.effective_policy.level
    return level in (PermissionLevel.YOLO, PermissionLevel.TRUSTED)


def is_gitlab_read_only(action: str) -> bool:
    """Check if action is read-only (no confirmation needed)."""
    return action in GITLAB_READ_ONLY_ACTIONS


def requires_gitlab_confirmation(
    permissions: AgentPermissions | None,
    skill_name: str,
    instance_host: str,
    action: str,
) -> bool:
    """Check if GitLab action requires user confirmation.

    Args:
        permissions: Agent permissions. If None, confirmation required.
        skill_name: GitLab skill name (e.g., 'gitlab_issue').
        instance_host: GitLab instance hostname (e.g., 'gitlab.com').
        action: The action being performed (e.g., 'create', 'list').

    Returns:
        False if no confirmation needed (YOLO, read-only, or already allowed).
        True if confirmation should be requested.
    """
    if permissions is None:
        # Defense in depth - require confirmation if no permissions
        logger.debug("GitLab confirmation required: no permissions configured")
        return True

    level = permissions.effective_policy.level

    # YOLO mode skips all confirmations
    if level == PermissionLevel.YOLO:
        return False

    # Read-only actions never need confirmation
    if is_gitlab_read_only(action):
        return False

    # Check session allowances for this skill@instance
    if permissions.session_allowances.is_gitlab_skill_allowed(skill_name, instance_host):
        return False

    return True
