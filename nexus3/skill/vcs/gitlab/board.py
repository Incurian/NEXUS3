"""GitLab board management skill."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexus3.core.types import ToolResult
from nexus3.skill.vcs.gitlab.base import GitLabSkill
from nexus3.skill.vcs.gitlab.client import GitLabClient

if TYPE_CHECKING:
    pass


class GitLabBoardSkill(GitLabSkill):
    """Create, view, update, and manage GitLab issue boards and board lists.

    Works at project or group level. Actions: list, get, create, update, delete,
    list-lists, create-list, update-list, delete-list.
    """

    @property
    def name(self) -> str:
        return "gitlab_board"

    @property
    def description(self) -> str:
        return (
            "Create, view, update, and manage GitLab issue boards and board lists. "
            "Works at project or group level. "
            "Actions: list, get, create, update, delete, "
            "list-lists, create-list, update-list, delete-list."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list",
                        "get",
                        "create",
                        "update",
                        "delete",
                        "list-lists",
                        "create-list",
                        "update-list",
                        "delete-list",
                    ],
                    "description": "Action to perform",
                },
                "instance": {
                    "type": "string",
                    "description": "GitLab instance name (uses default if omitted)",
                },
                "project": {
                    "type": "string",
                    "description": "Project path (e.g., 'group/repo'). "
                    "Either project or group required.",
                },
                "group": {
                    "type": "string",
                    "description": "Group path (e.g., 'my-group'). "
                    "Either project or group required.",
                },
                "board_id": {
                    "type": "integer",
                    "description": "Board ID (required for most actions)",
                },
                "list_id": {
                    "type": "integer",
                    "description": "List ID (for list operations)",
                },
                "name": {
                    "type": "string",
                    "description": "Board name",
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Labels for board scope",
                },
                "label_id": {
                    "type": "integer",
                    "description": "Label ID for creating label list",
                },
                "assignee_id": {
                    "type": "integer",
                    "description": "User ID for creating assignee list",
                },
                "milestone_id": {
                    "type": "integer",
                    "description": "Milestone ID for creating milestone list",
                },
                "iteration_id": {
                    "type": "integer",
                    "description": "Iteration ID for creating iteration list",
                },
                "position": {
                    "type": "integer",
                    "description": "List position (for reordering)",
                },
            },
            "required": ["action"],
        }

    def _get_base_path(
        self,
        client: GitLabClient,
        project: str | None,
        group: str | None,
    ) -> str:
        """Get API base path for project or group boards."""
        if group:
            return f"/groups/{client._encode_path(group)}"
        if project:
            resolved = self._resolve_project(project)
            return f"/projects/{client._encode_path(resolved)}"
        raise ValueError("Either 'project' or 'group' parameter is required")

    async def _execute_impl(
        self,
        client: GitLabClient,
        **kwargs: Any,
    ) -> ToolResult:
        action = kwargs.get("action", "")
        project = kwargs.get("project")
        group = kwargs.get("group")

        # Filter out consumed kwargs to avoid passing them twice
        filtered = {
            k: v
            for k, v in kwargs.items()
            if k not in ("action", "project", "group", "instance", "board_id", "list_id")
        }

        match action:
            case "list":
                return await self._list_boards(client, project, group)
            case "get":
                board_id = kwargs.get("board_id")
                if not board_id:
                    return ToolResult(error="board_id parameter required for get action")
                return await self._get_board(client, project, group, board_id)
            case "create":
                return await self._create_board(client, project, group, **filtered)
            case "update":
                board_id = kwargs.get("board_id")
                if not board_id:
                    return ToolResult(error="board_id parameter required for update action")
                return await self._update_board(client, project, group, board_id, **filtered)
            case "delete":
                board_id = kwargs.get("board_id")
                if not board_id:
                    return ToolResult(error="board_id parameter required for delete action")
                return await self._delete_board(client, project, group, board_id)
            case "list-lists":
                board_id = kwargs.get("board_id")
                if not board_id:
                    return ToolResult(
                        error="board_id parameter required for list-lists action"
                    )
                return await self._list_lists(client, project, group, board_id)
            case "create-list":
                board_id = kwargs.get("board_id")
                if not board_id:
                    return ToolResult(
                        error="board_id parameter required for create-list action"
                    )
                return await self._create_list(client, project, group, board_id, **filtered)
            case "update-list":
                board_id = kwargs.get("board_id")
                list_id = kwargs.get("list_id")
                if not board_id:
                    return ToolResult(
                        error="board_id parameter required for update-list action"
                    )
                if not list_id:
                    return ToolResult(
                        error="list_id parameter required for update-list action"
                    )
                return await self._update_list(
                    client, project, group, board_id, list_id, **filtered
                )
            case "delete-list":
                board_id = kwargs.get("board_id")
                list_id = kwargs.get("list_id")
                if not board_id:
                    return ToolResult(
                        error="board_id parameter required for delete-list action"
                    )
                if not list_id:
                    return ToolResult(
                        error="list_id parameter required for delete-list action"
                    )
                return await self._delete_list(client, project, group, board_id, list_id)
            case _:
                return ToolResult(error=f"Unknown action: {action}")

    async def _list_boards(
        self,
        client: GitLabClient,
        project: str | None,
        group: str | None,
    ) -> ToolResult:
        base_path = self._get_base_path(client, project, group)

        boards = [
            board
            async for board in client.paginate(f"{base_path}/boards", limit=100)
        ]

        if not boards:
            return ToolResult(output="No boards found")

        lines = [f"Found {len(boards)} board(s):"]
        for board in boards:
            web_url = f" - {board['web_url']}" if board.get("web_url") else ""
            lines.append(f"  #{board['id']}: {board['name']}{web_url}")

        return ToolResult(output="\n".join(lines))

    async def _get_board(
        self,
        client: GitLabClient,
        project: str | None,
        group: str | None,
        board_id: int,
    ) -> ToolResult:
        base_path = self._get_base_path(client, project, group)
        board = await client.get(f"{base_path}/boards/{board_id}")

        lines = [
            f"# {board['name']}",
            "",
            f"ID: {board['id']}",
        ]

        if board.get("web_url"):
            lines.append(f"URL: {board['web_url']}")

        # Show milestone scope if set
        if board.get("milestone"):
            lines.append(f"Milestone: {board['milestone'].get('title', 'N/A')}")

        # Show iteration scope if set
        if board.get("iteration"):
            lines.append(f"Iteration: {board['iteration'].get('title', 'N/A')}")

        # Show assignee scope if set
        if board.get("assignee"):
            lines.append(f"Assignee: {board['assignee'].get('username', 'N/A')}")

        # Show label scopes if set
        if board.get("labels"):
            label_names = [lbl.get("name", "?") for lbl in board["labels"]]
            lines.append(f"Labels: {', '.join(label_names)}")

        # Show lists (columns)
        if board.get("lists"):
            lines.append("")
            lines.append("Lists:")
            for lst in board["lists"]:
                lines.append(self._format_list_item(lst))

        return ToolResult(output="\n".join(lines))

    def _format_list_item(self, lst: dict[str, Any]) -> str:
        """Format a board list item for display."""
        list_id = lst["id"]
        position = lst.get("position", "?")
        list_type = lst.get("list_type", "label")

        if list_type == "label" and lst.get("label"):
            name = lst["label"]["name"]
            return f"  #{list_id}: {name} (position: {position})"
        elif list_type == "assignee" and lst.get("assignee"):
            username = lst["assignee"]["username"]
            return f"  #{list_id}: @{username} (position: {position})"
        elif list_type == "milestone" and lst.get("milestone"):
            title = lst["milestone"]["title"]
            return f"  #{list_id}: %{title} (position: {position})"
        elif list_type == "iteration" and lst.get("iteration"):
            title = lst["iteration"]["title"]
            return f"  #{list_id}: *{title} (position: {position})"
        else:
            return f"  #{list_id}: {list_type} (position: {position})"

    async def _create_board(
        self,
        client: GitLabClient,
        project: str | None,
        group: str | None,
        **kwargs: Any,
    ) -> ToolResult:
        base_path = self._get_base_path(client, project, group)

        data: dict[str, Any] = {}

        if name := kwargs.get("name"):
            data["name"] = name
        if labels := kwargs.get("labels"):
            data["labels"] = ",".join(labels)

        board = await client.post(f"{base_path}/boards", **data)

        return ToolResult(output=f"Created board '{board['name']}' (ID: {board['id']})")

    async def _update_board(
        self,
        client: GitLabClient,
        project: str | None,
        group: str | None,
        board_id: int,
        **kwargs: Any,
    ) -> ToolResult:
        base_path = self._get_base_path(client, project, group)

        data: dict[str, Any] = {}

        if name := kwargs.get("name"):
            data["name"] = name
        if labels := kwargs.get("labels"):
            data["labels"] = ",".join(labels)

        if not data:
            return ToolResult(error="No fields to update")

        board = await client.put(f"{base_path}/boards/{board_id}", **data)

        return ToolResult(output=f"Updated board '{board['name']}'")

    async def _delete_board(
        self,
        client: GitLabClient,
        project: str | None,
        group: str | None,
        board_id: int,
    ) -> ToolResult:
        base_path = self._get_base_path(client, project, group)
        await client.delete(f"{base_path}/boards/{board_id}")
        return ToolResult(output=f"Deleted board {board_id}")

    async def _list_lists(
        self,
        client: GitLabClient,
        project: str | None,
        group: str | None,
        board_id: int,
    ) -> ToolResult:
        base_path = self._get_base_path(client, project, group)

        lists = [
            lst
            async for lst in client.paginate(
                f"{base_path}/boards/{board_id}/lists", limit=100
            )
        ]

        if not lists:
            return ToolResult(output="No lists found on this board")

        lines = [f"Found {len(lists)} list(s):"]
        for lst in lists:
            lines.append(self._format_list_item(lst))

        return ToolResult(output="\n".join(lines))

    async def _create_list(
        self,
        client: GitLabClient,
        project: str | None,
        group: str | None,
        board_id: int,
        **kwargs: Any,
    ) -> ToolResult:
        base_path = self._get_base_path(client, project, group)

        data: dict[str, Any] = {}

        if label_id := kwargs.get("label_id"):
            data["label_id"] = label_id
        if assignee_id := kwargs.get("assignee_id"):
            data["assignee_id"] = assignee_id
        if milestone_id := kwargs.get("milestone_id"):
            data["milestone_id"] = milestone_id
        if iteration_id := kwargs.get("iteration_id"):
            data["iteration_id"] = iteration_id

        if not data:
            return ToolResult(
                error="At least one of label_id, assignee_id, milestone_id, "
                "or iteration_id required"
            )

        lst = await client.post(f"{base_path}/boards/{board_id}/lists", **data)

        list_type = lst.get("list_type", "unknown")
        position = lst.get("position", "?")
        return ToolResult(
            output=f"Created {list_type} list (ID: {lst['id']}, position: {position})"
        )

    async def _update_list(
        self,
        client: GitLabClient,
        project: str | None,
        group: str | None,
        board_id: int,
        list_id: int,
        **kwargs: Any,
    ) -> ToolResult:
        base_path = self._get_base_path(client, project, group)

        data: dict[str, Any] = {}

        if position := kwargs.get("position"):
            data["position"] = position

        if not data:
            return ToolResult(error="position parameter required for update-list action")

        lst = await client.put(f"{base_path}/boards/{board_id}/lists/{list_id}", **data)

        return ToolResult(
            output=f"Updated list {list_id} (new position: {lst.get('position', '?')})"
        )

    async def _delete_list(
        self,
        client: GitLabClient,
        project: str | None,
        group: str | None,
        board_id: int,
        list_id: int,
    ) -> ToolResult:
        base_path = self._get_base_path(client, project, group)
        await client.delete(f"{base_path}/boards/{board_id}/lists/{list_id}")
        return ToolResult(output=f"Deleted list {list_id} from board {board_id}")
