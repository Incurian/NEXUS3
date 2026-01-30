"""GitLab MR approval management skill."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexus3.core.types import ToolResult
from nexus3.skill.vcs.gitlab.base import GitLabSkill
from nexus3.skill.vcs.gitlab.client import GitLabClient

if TYPE_CHECKING:
    pass


class GitLabApprovalSkill(GitLabSkill):
    """Manage MR approvals and approval rules."""

    @property
    def name(self) -> str:
        return "gitlab_approval"

    @property
    def description(self) -> str:
        return "Manage MR approvals and approval rules"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "status", "approve", "unapprove",
                        "rules", "create-rule", "delete-rule",
                    ],
                    "description": "Action to perform",
                },
                "instance": {
                    "type": "string",
                    "description": "GitLab instance name (uses default if omitted)",
                },
                "project": {
                    "type": "string",
                    "description": (
                        "Project path (e.g., 'group/repo'). "
                        "Auto-detected from git remote if omitted."
                    ),
                },
                "iid": {
                    "type": "integer",
                    "description": (
                        "Merge request IID "
                        "(required for status/approve/unapprove, optional for rules)"
                    ),
                },
                "sha": {
                    "type": "string",
                    "description": "HEAD SHA of MR for verification (optional, for approve action)",
                },
                "rule_id": {
                    "type": "integer",
                    "description": "Approval rule ID (required for delete-rule)",
                },
                "name": {
                    "type": "string",
                    "description": "Approval rule name (required for create-rule)",
                },
                "approvals_required": {
                    "type": "integer",
                    "description": "Number of approvals required (required for create-rule)",
                },
                "users": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "User IDs eligible to approve (for create-rule)",
                },
                "groups": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Group IDs eligible to approve (for create-rule)",
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
        project = kwargs.get("project")
        iid = kwargs.get("iid")
        rule_id = kwargs.get("rule_id")

        # Filter out consumed kwargs to avoid passing them twice
        filtered = {
            k: v for k, v in kwargs.items()
            if k not in ("action", "project", "instance", "iid", "rule_id")
        }

        match action:
            case "status":
                if not iid:
                    return ToolResult(error="iid parameter required for status action")
                return await self._get_approval_status(client, project, iid)
            case "approve":
                if not iid:
                    return ToolResult(error="iid parameter required for approve action")
                return await self._approve_mr(client, project, iid, **filtered)
            case "unapprove":
                if not iid:
                    return ToolResult(error="iid parameter required for unapprove action")
                return await self._unapprove_mr(client, project, iid)
            case "rules":
                return await self._list_approval_rules(client, project, iid)
            case "create-rule":
                return await self._create_approval_rule(client, project, **filtered)
            case "delete-rule":
                if not rule_id:
                    return ToolResult(error="rule_id parameter required for delete-rule action")
                return await self._delete_approval_rule(client, project, rule_id)
            case _:
                return ToolResult(error=f"Unknown action: {action}")

    async def _get_approval_status(
        self,
        client: GitLabClient,
        project: str | None,
        iid: int,
    ) -> ToolResult:
        resolved = self._resolve_project(project)
        path = f"/projects/{client._encode_path(resolved)}/merge_requests/{iid}/approvals"
        data = await client.get(path)

        lines = [f"# Approval Status for MR !{iid}"]
        lines.append("")

        # Approval counts
        approved = data.get("approved", False)
        approvals_required = data.get("approvals_required", 0)
        approvals_left = data.get("approvals_left", 0)

        status_icon = "\u2705" if approved else "\u23f3"  # checkmark or hourglass
        lines.append(f"Status: {status_icon} {'Approved' if approved else 'Pending approval'}")
        lines.append(f"Required: {approvals_required}, Remaining: {approvals_left}")
        lines.append("")

        # Approved by
        approved_by = data.get("approved_by", [])
        if approved_by:
            lines.append("## Approved By")
            for approver in approved_by:
                user = approver.get("user", {})
                username = user.get("username", "unknown")
                name = user.get("name", "")
                lines.append(f"  \u2714 @{username} ({name})" if name else f"  \u2714 @{username}")
            lines.append("")

        # Suggested approvers (pending)
        suggested = data.get("suggested_approvers", [])
        if suggested:
            lines.append("## Suggested Approvers")
            for approver in suggested:
                username = approver.get("username", "unknown")
                name = approver.get("name", "")
                lines.append(f"  \u25cb @{username} ({name})" if name else f"  \u25cb @{username}")
            lines.append("")

        # Approval rules summary
        rules = data.get("approval_rules_overwritten", False)
        if rules:
            lines.append("Note: Approval rules have been overwritten for this MR")

        return ToolResult(output="\n".join(lines))

    async def _approve_mr(
        self,
        client: GitLabClient,
        project: str | None,
        iid: int,
        **kwargs: Any,
    ) -> ToolResult:
        resolved = self._resolve_project(project)
        path = f"/projects/{client._encode_path(resolved)}/merge_requests/{iid}/approve"

        data: dict[str, Any] = {}
        if sha := kwargs.get("sha"):
            data["sha"] = sha

        await client.post(path, **data)
        return ToolResult(output=f"Approved merge request !{iid}")

    async def _unapprove_mr(
        self,
        client: GitLabClient,
        project: str | None,
        iid: int,
    ) -> ToolResult:
        resolved = self._resolve_project(project)
        path = f"/projects/{client._encode_path(resolved)}/merge_requests/{iid}/unapprove"

        await client.post(path)
        return ToolResult(output=f"Revoked approval for merge request !{iid}")

    async def _list_approval_rules(
        self,
        client: GitLabClient,
        project: str | None,
        iid: int | None,
    ) -> ToolResult:
        resolved = self._resolve_project(project)
        encoded_project = client._encode_path(resolved)

        if iid:
            # MR-level approval rules
            path = f"/projects/{encoded_project}/merge_requests/{iid}/approval_rules"
            scope = f"MR !{iid}"
        else:
            # Project-level approval rules
            path = f"/projects/{encoded_project}/approval_rules"
            scope = "project"

        rules = [rule async for rule in client.paginate(path, limit=100)]

        if not rules:
            return ToolResult(output=f"No approval rules found for {scope}")

        lines = [f"# Approval Rules ({scope})"]
        lines.append("")

        for rule in rules:
            rule_id = rule.get("id", "N/A")
            name = rule.get("name", "Unnamed")
            approvals_required = rule.get("approvals_required", 0)
            rule_type = rule.get("rule_type", "regular")

            lines.append(f"## {name}")
            lines.append(f"ID: {rule_id}")
            lines.append(f"Type: {rule_type}")
            lines.append(f"Approvals required: {approvals_required}")

            # Eligible approvers (users)
            eligible_users = rule.get("eligible_approvers", [])
            if eligible_users:
                user_list = ", ".join(
                    f"@{u.get('username', 'unknown')}" for u in eligible_users
                )
                lines.append(f"Eligible users: {user_list}")

            # Groups
            groups = rule.get("groups", [])
            if groups:
                group_list = ", ".join(g.get("name", "unknown") for g in groups)
                lines.append(f"Eligible groups: {group_list}")

            # Contains hidden groups (Premium feature)
            if rule.get("contains_hidden_groups"):
                lines.append("Note: Contains hidden groups")

            lines.append("")

        return ToolResult(output="\n".join(lines))

    async def _create_approval_rule(
        self,
        client: GitLabClient,
        project: str | None,
        **kwargs: Any,
    ) -> ToolResult:
        name = kwargs.get("name")
        approvals_required = kwargs.get("approvals_required")

        if not name:
            return ToolResult(error="name parameter required for create-rule action")
        if approvals_required is None:
            return ToolResult(error="approvals_required parameter required for create-rule action")

        resolved = self._resolve_project(project)
        path = f"/projects/{client._encode_path(resolved)}/approval_rules"

        data: dict[str, Any] = {
            "name": name,
            "approvals_required": approvals_required,
        }

        if users := kwargs.get("users"):
            data["user_ids"] = users
        if groups := kwargs.get("groups"):
            data["group_ids"] = groups

        rule = await client.post(path, **data)
        return ToolResult(
            output=f"Created approval rule '{rule.get('name')}' (ID: {rule['id']}) "
            f"requiring {rule.get('approvals_required', 0)} approval(s)"
        )

    async def _delete_approval_rule(
        self,
        client: GitLabClient,
        project: str | None,
        rule_id: int,
    ) -> ToolResult:
        resolved = self._resolve_project(project)
        path = f"/projects/{client._encode_path(resolved)}/approval_rules/{rule_id}"

        await client.delete(path)
        return ToolResult(output=f"Deleted approval rule (ID: {rule_id})")
