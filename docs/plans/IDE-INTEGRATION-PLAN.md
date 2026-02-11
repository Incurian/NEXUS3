# Plan: VS Code IDE Integration

## Context

NEXUS3 agents have no awareness of the user's editor. Other coding agents (Claude Code, Cline, Cursor) integrate with VS Code to show diffs for approval, open files, and inject editor context (diagnostics, selection). Co-workers specifically want the ability to view and approve diffs in VS Code instead of the terminal.

We're building two components:
1. **NEXUS3 side** (`nexus3/ide/`): IDE bridge module that discovers and connects to an IDE's WebSocket MCP server
2. **VS Code extension** (`editors/vscode/`): Thin extension that starts a WebSocket MCP server exposing editor capabilities

**Protocol**: We adopt Claude Code's WebSocket+MCP protocol (lock file discovery, JSON-RPC 2.0 over WebSocket, MCP tool calls). This is proven, documented, and gets potential Neovim compatibility via claudecode.nvim. The protocol is purely extensible — we implement their base tools and can add NEXUS3-specific tools on top.

---

## Scope

### Included in v1
- WebSocket MCP transport, lock file discovery, auth
- 11 IDE tools: openDiff, openFile, getDiagnostics, getCurrentSelection, getLatestSelection, getOpenEditors, getWorkspaceFolders, checkDocumentDirty, saveDocument, closeTab, closeAllDiffTabs
- IDE-aware confirmation callback (openDiff for file writes in TRUSTED mode)
- IDE context injection into system prompt (diagnostics, open editors)
- `/ide` REPL command
- VS Code extension with WebSocket MCP server

### Deferred
- `executeCode` tool (complex, security implications)
- Multi-IDE support (JetBrains, Neovim extensions — same protocol, separate projects)
- `at_mentioned` notification handling
- IDE-driven context compaction

### Excluded
- Exposing NEXUS3 as MCP server to IDE (separate project, see MCP-SERVER-PLAN)
- Automatic file watching (too noisy)

---

## Design Decisions

| Question | Decision | Rationale |
|----------|----------|-----------|
| Protocol | Claude Code's WebSocket+MCP | Proven, documented, Neovim-compatible, extensible |
| Lock file location | `~/.nexus3/ide/<port>.lock` | Matches existing `~/.nexus3/` pattern, no conflict with Claude Code |
| Transport | New `WebSocketTransport` subclass of `MCPTransport` | Reuses existing `MCPClient` unchanged |
| IDE bridge ownership | Singleton on `SharedComponents` | One IDE connection shared by all agents in same pool |
| Context injection | Follow git_context pattern exactly | Cached `str | None` on ContextManager, caller passes formatted string, inject in `_build_system_prompt_for_api_call()` |
| Confirmation integration | Wrap existing `on_confirm` callback | When IDE connected + file write, call `openDiff`; fallback to terminal |
| WebSocket library (Python) | `websockets>=13.0` | Standard, async-native, well-maintained |
| WebSocket library (Node.js) | `ws` npm package | Node.js has no built-in WebSocket server; `ws` is the standard |
| Build tool (extension) | esbuild | Fast, simple, standard for modern VS Code extensions |
| YOLO mode | Skip openDiff, still inject IDE context | YOLO = no confirmations; diagnostics still useful |
| Extension location | `editors/vscode/` in this repo | Easier to iterate, single repo |
| Content extraction for diff | Compute full file with edit applied | Show complete before/after for all tool types |
| Multiple diffs in one batch | Serialize through IDEBridge asyncio.Lock | Avoid overwhelming user with simultaneous diff tabs |
| New file creation diff | Empty string as old side | VS Code diff editor handles this naturally |
| `getLatestSelection` vs `getCurrentSelection` | `latest` persists across focus changes | Track via `onDidChangeTextEditorSelection`, persist even when editor loses focus |

---

## Security Considerations

1. **Localhost-only binding**: WebSocket server binds to `127.0.0.1` only. No network exposure.
2. **Per-session auth tokens**: UUID v4 token in lock file, validated via `x-nexus3-ide-authorization` header on WebSocket upgrade.
3. **Lock file permissions**: Created with `0600` (owner-only read/write). Stale files cleaned up via PID validation.
4. **PID validation**: Before connecting, verify the IDE process is still alive (`os.kill(pid, 0)`). `ProcessLookupError` = stale (delete lock file), `PermissionError` = process exists (valid).
5. **Path validation**: `openDiff` only operates on files within workspace folders. Extension validates paths.
6. **No credential leakage**: Lock files contain only PID, workspace folders, IDE name, transport type, and auth token.
7. **Confirmation integrity**: `openDiff` blocks until explicit user action in VS Code. The JSON-RPC response is held until accept/reject.
8. **Multi-agent isolation**: IDE bridge is per-pool (shared singleton). All agents share one IDE connection, but each agent's confirmation is independent.

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| WebSocket connection drops mid-diff | User's accept/reject lost | Auto-reconnect + fallback to terminal confirmation |
| IDE extension crashes | Lock file left behind | PID validation catches dead processes; stale cleanup |
| User takes very long to review diff | Agent blocked indefinitely | No timeout by design (user is in control); agent can be cancelled via `/cancel` |
| Multiple agents request diffs simultaneously | Confusing UX | Serialize diff requests through IDEBridge `asyncio.Lock` |
| Lock file directory doesn't exist | Connection fails silently | Auto-create `~/.nexus3/ide/` on extension activation |
| `websockets` dependency conflict | Install failure | Pin to `>=13.0` (stable, widely compatible) |

---

## Architecture

### New Module: `nexus3/ide/`

```
nexus3/ide/
├── __init__.py       # Public API exports
├── bridge.py         # IDEBridge lifecycle, auto-connect, reconnect
├── connection.py     # IDEConnection typed wrappers + result types (DiffResult, Diagnostic, etc.)
├── discovery.py      # Lock file scanning, PID validation, workspace matching
├── transport.py      # WebSocketTransport (MCPTransport subclass)
├── context.py        # IDE context formatting for system prompt injection
└── README.md
```

### VS Code Extension: `editors/vscode/`

```
editors/vscode/
├── package.json
├── tsconfig.json
├── src/
│   ├── extension.ts      # Activation, server lifecycle, lock file
│   ├── server.ts         # WebSocket server + MCP protocol handler
│   ├── tools/
│   │   ├── index.ts      # Tool registry + dispatch
│   │   ├── openDiff.ts   # Diff viewer (blocking, accept/reject)
│   │   ├── openFile.ts   # File navigation with selection
│   │   ├── diagnostics.ts
│   │   ├── selection.ts
│   │   ├── workspace.ts
│   │   ├── document.ts
│   │   └── tabs.ts
│   └── types.ts
└── README.md
```

### Lock File Format

```json
{
  "pid": 12345,
  "workspaceFolders": ["/home/user/project"],
  "ideName": "VS Code",
  "transport": "ws",
  "authToken": "550e8400-e29b-41d4-a716-446655440000"
}
```

Port extracted from filename: `~/.nexus3/ide/12345.lock` → `ws://127.0.0.1:12345`

### Integration Flow (Confirmation)

```
[Agent requests write_file("foo.py", content)]
  → Session._execute_tool_call()
  → PermissionEnforcer.requires_confirmation() → True
  → ConfirmationController.request(callback)
  → IDE-aware callback:
      ├─ IDE connected + file write? → IDEConnection.open_diff()
      │    → VS Code shows diff editor, user clicks Accept/Reject
      │    → Returns FILE_SAVED → ALLOW_ONCE
      │    → Returns DIFF_REJECTED → DENY
      └─ Otherwise → terminal confirm_tool_action() (existing behavior)
```

---

## Implementation Details: Phase 1 (Python — `nexus3/ide/`)

### Result Types (`nexus3/ide/connection.py`, top of file)

All result types used by IDEConnection methods:

```python
from dataclasses import dataclass
from enum import Enum

class DiffOutcome(Enum):
    """Result of an openDiff operation."""
    FILE_SAVED = "FILE_SAVED"
    DIFF_REJECTED = "DIFF_REJECTED"

@dataclass
class Diagnostic:
    """LSP diagnostic from IDE."""
    file_path: str
    line: int
    message: str
    severity: str  # "error", "warning", "info", "hint"
    source: str | None = None

@dataclass
class Selection:
    """Editor text selection."""
    file_path: str
    text: str
    start_line: int
    start_character: int
    end_line: int
    end_character: int

@dataclass
class EditorInfo:
    """Open editor tab info."""
    file_path: str
    is_active: bool = False
    is_dirty: bool = False
    language_id: str | None = None
```

### MCP Tool Name + Schema Table (Definitive)

These exact names and parameter schemas are used by both IDEConnection (Python) and the VS Code extension (TypeScript). They are the contract between the two.

| Tool Name | Parameters | Return (in MCP `content[0].text`) |
|-----------|-----------|--------|
| `openDiff` | `old_file_path: str`, `new_file_path: str`, `new_file_contents: str`, `tab_name: str` | `"FILE_SAVED"` or `"DIFF_REJECTED"` |
| `openFile` | `filePath: str`, `preview?: bool` | `"ok"` |
| `getDiagnostics` | `uri?: str` | JSON array: `[{filePath, line, message, severity, source?}]` |
| `getCurrentSelection` | *(none)* | JSON: `{filePath, text, startLine, startCharacter, endLine, endCharacter}` or `"null"` |
| `getLatestSelection` | *(none)* | Same as getCurrentSelection (persists across focus changes) |
| `getOpenEditors` | *(none)* | JSON array: `[{filePath, isActive, isDirty, languageId}]` |
| `getWorkspaceFolders` | *(none)* | JSON array: `["/path/to/folder", ...]` |
| `checkDocumentDirty` | `filePath: str` | JSON: `{dirty: bool}` |
| `saveDocument` | `filePath: str` | `"ok"` |
| `closeTab` | `tabName: str` | `"ok"` |
| `closeAllDiffTabs` | *(none)* | `"ok"` |

All responses use standard MCP format: `{content: [{type: "text", text: "<value>"}]}`. Complex data is JSON-stringified in the `text` field.

### WebSocketTransport (`nexus3/ide/transport.py`)

Subclass of `MCPTransport` (at `nexus3/mcp/transport.py:179`). Must implement abstract methods: `connect()`, `send()`, `receive()`, `close()`. Add concrete `is_connected` property (NOT on ABC, but `MCPClient` calls it via duck typing at `mcp/client.py:497`).

```python
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import websockets
from websockets.asyncio.client import ClientConnection

from nexus3.mcp.transport import MCPTransport

logger = logging.getLogger(__name__)

class WebSocketTransport(MCPTransport):
    """WebSocket transport for IDE MCP communication."""

    def __init__(self, url: str, auth_token: str) -> None:
        self._url = url
        self._auth_token = auth_token
        self._ws: ClientConnection | None = None
        self._receive_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._listener_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        # Use await directly (NOT async with) since lifecycle is managed by connect/close
        self._ws = await websockets.connect(
            self._url,
            additional_headers={"x-nexus3-ide-authorization": self._auth_token},
            ping_interval=30,
            ping_timeout=10,
        )
        self._listener_task = asyncio.create_task(self._listen())

    async def _listen(self) -> None:
        """Background: read frames, put ALL messages on queue.

        IMPORTANT: Must queue ALL messages including notifications.
        MCPClient._call() (mcp/client.py:230) has its own notification-discarding
        loop that expects to see everything via receive(). Pre-filtering would break it.
        """
        assert self._ws is not None
        try:
            async for data in self._ws:
                # websockets v13: recv() returns str for text frames
                msg = json.loads(data)
                await self._receive_queue.put(msg)
        except websockets.exceptions.ConnectionClosed:
            logger.debug("WebSocket connection closed")
        except Exception:
            logger.exception("WebSocket listener error")

    async def send(self, message: dict[str, Any]) -> None:
        assert self._ws is not None
        await self._ws.send(json.dumps(message, separators=(",", ":")))

    async def receive(self) -> dict[str, Any]:
        return await self._receive_queue.get()

    async def close(self) -> None:
        if self._listener_task:
            self._listener_task.cancel()
            self._listener_task = None
        if self._ws:
            await self._ws.close()
            self._ws = None

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and self._ws.protocol is not None
```

### Lock File Discovery (`nexus3/ide/discovery.py`)

```python
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class IDEInfo:
    pid: int
    workspace_folders: list[str]
    ide_name: str
    transport: str
    auth_token: str
    port: int
    lock_path: Path

def discover_ides(cwd: Path, lock_dir: Path | None = None) -> list[IDEInfo]:
    """Scan lock files, validate PIDs, match workspace to cwd.

    Returns list sorted by best workspace match (longest prefix first).
    Returns [] if directory doesn't exist or no matches found.
    """
    lock_dir = lock_dir or Path.home() / ".nexus3" / "ide"
    if not lock_dir.is_dir():
        return []

    resolved_cwd = cwd.resolve()
    results: list[IDEInfo] = []

    for lock_file in lock_dir.glob("*.lock"):
        # Port from filename stem
        try:
            port = int(lock_file.stem)
        except ValueError:
            continue

        # Parse JSON
        try:
            data = json.loads(lock_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        pid = data.get("pid", 0)
        if not _is_pid_alive(pid):
            # Stale lock file — clean up
            try:
                lock_file.unlink()
            except OSError:
                pass
            continue

        # Check workspace match
        folders = data.get("workspaceFolders", [])
        if not any(resolved_cwd.is_relative_to(Path(f).resolve()) for f in folders):
            continue

        results.append(IDEInfo(
            pid=pid,
            workspace_folders=folders,
            ide_name=data.get("ideName", "Unknown"),
            transport=data.get("transport", "ws"),
            auth_token=data.get("authToken", ""),
            port=port,
            lock_path=lock_file,
        ))

    # Sort by longest matching workspace prefix (best match first)
    results.sort(
        key=lambda i: max(
            (len(str(Path(f).resolve())) for f in i.workspace_folders
             if resolved_cwd.is_relative_to(Path(f).resolve())),
            default=0,
        ),
        reverse=True,
    )
    return results


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False  # Process doesn't exist
    except PermissionError:
        return True  # Exists but different user
    except OSError:
        return False
```

### IDEConnection (`nexus3/ide/connection.py`)

```python
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from nexus3.mcp.client import MCPClient

# Result types (DiffOutcome, Diagnostic, Selection, EditorInfo defined at top of file — see above)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from nexus3.ide.discovery import IDEInfo

class IDEConnection:
    """Typed async wrappers around MCPClient.call_tool()."""

    def __init__(self, client: MCPClient, ide_info: IDEInfo) -> None:
        self._client = client
        self.ide_info = ide_info

    async def open_diff(
        self,
        old_file_path: str,
        new_file_path: str,
        new_file_contents: str,
        tab_name: str,
    ) -> DiffOutcome:
        """Show diff in IDE. BLOCKS until user accepts/rejects."""
        result = await self._client.call_tool("openDiff", {
            "old_file_path": old_file_path,
            "new_file_path": new_file_path,
            "new_file_contents": new_file_contents,
            "tab_name": tab_name,
        })
        text = result.content[0]["text"] if result.content else ""
        if "FILE_SAVED" in text:
            return DiffOutcome.FILE_SAVED
        return DiffOutcome.DIFF_REJECTED

    async def open_file(self, file_path: str, preview: bool = False) -> None:
        await self._client.call_tool("openFile", {"filePath": file_path, "preview": preview})

    async def get_diagnostics(self, uri: str | None = None) -> list[Diagnostic]:
        args: dict = {}
        if uri:
            args["uri"] = uri
        result = await self._client.call_tool("getDiagnostics", args)
        text = result.content[0]["text"] if result.content else "[]"
        items = json.loads(text)
        return [Diagnostic(**d) for d in items]

    # ... (similar pattern for remaining 8 tools — parse MCPToolResult.content[0].text)

    @property
    def is_connected(self) -> bool:
        return self._client._transport.is_connected  # noqa: SLF001

    async def close(self) -> None:
        await self._client.close()
```

### IDEBridge (`nexus3/ide/bridge.py`)

```python
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from nexus3.ide.connection import IDEConnection
from nexus3.ide.discovery import IDEInfo, discover_ides
from nexus3.ide.transport import WebSocketTransport
from nexus3.mcp.client import MCPClient

if TYPE_CHECKING:
    from nexus3.config.schema import IDEConfig

logger = logging.getLogger(__name__)

class IDEBridge:
    """Manages IDE discovery and connection lifecycle.

    Created once per SharedComponents. Not connected until auto_connect() or connect() called.
    """

    def __init__(self, config: IDEConfig) -> None:
        self._config = config
        self._connection: IDEConnection | None = None
        self._diff_lock = asyncio.Lock()  # Serialize openDiff requests

    async def auto_connect(self, cwd: Path) -> IDEConnection | None:
        if not self._config.enabled or not self._config.auto_connect:
            return None
        lock_dir = self._config.lock_dir_path  # Path | None
        ides = discover_ides(cwd, lock_dir=lock_dir)
        if not ides:
            return None
        return await self.connect(ides[0])

    async def connect(self, ide_info: IDEInfo) -> IDEConnection:
        if self._connection:
            await self.disconnect()
        transport = WebSocketTransport(
            url=f"ws://127.0.0.1:{ide_info.port}",
            auth_token=ide_info.auth_token,
        )
        client = MCPClient(transport)
        await client.connect(timeout=10.0)  # Handles initialize handshake
        self._connection = IDEConnection(client, ide_info)
        logger.info("IDE connected: %s (port %d)", ide_info.ide_name, ide_info.port)
        return self._connection

    async def disconnect(self) -> None:
        if self._connection:
            await self._connection.close()
            self._connection = None

    @property
    def connection(self) -> IDEConnection | None:
        return self._connection

    @property
    def is_connected(self) -> bool:
        return self._connection is not None and self._connection.is_connected
```

### IDE Context Formatting (`nexus3/ide/context.py`)

Takes primitive types (not IDEConfig — avoids cross-phase dependency). Follows `nexus3/context/git_context.py` pattern.

```python
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nexus3.ide.connection import Diagnostic, EditorInfo

_MAX_IDE_CONTEXT_LENGTH = 800

def format_ide_context(
    ide_name: str,
    open_editors: list[EditorInfo] | None = None,
    diagnostics: list[Diagnostic] | None = None,
    *,
    inject_diagnostics: bool = True,
    inject_open_editors: bool = True,
    max_diagnostics: int = 50,
) -> str | None:
    """Format IDE state for system prompt injection.

    Returns formatted string (max 800 chars), or None if nothing to inject.
    """
    lines = [f"IDE connected: {ide_name}"]

    if inject_open_editors and open_editors:
        names = [Path(e.file_path).name for e in open_editors[:10]]
        lines.append(f"  Open tabs: {', '.join(names)}")

    if inject_diagnostics and diagnostics:
        errors = [d for d in diagnostics if d.severity == "error"]
        warnings = [d for d in diagnostics if d.severity == "warning"]
        if errors or warnings:
            parts = []
            if errors:
                parts.append(f"{len(errors)} errors")
            if warnings:
                parts.append(f"{len(warnings)} warnings")
            lines.append(f"  Diagnostics: {', '.join(parts)}")
            for d in errors[:max_diagnostics]:
                lines.append(f"    {Path(d.file_path).name}:{d.line}: {d.message}")

    if len(lines) <= 1:
        return None

    result = "\n".join(lines)
    if len(result) > _MAX_IDE_CONTEXT_LENGTH:
        result = result[: _MAX_IDE_CONTEXT_LENGTH - 3] + "..."
    return result
```

### `__init__.py` exports (implement LAST, after all modules exist)

```python
from nexus3.ide.bridge import IDEBridge
from nexus3.ide.connection import (
    DiffOutcome,
    Diagnostic,
    EditorInfo,
    IDEConnection,
    Selection,
)
from nexus3.ide.context import format_ide_context
from nexus3.ide.discovery import IDEInfo, discover_ides
from nexus3.ide.transport import WebSocketTransport

__all__ = [
    "DiffOutcome", "Diagnostic", "EditorInfo", "IDEBridge", "IDEConnection",
    "IDEInfo", "Selection", "WebSocketTransport", "discover_ides", "format_ide_context",
]
```

---

## Implementation Details: Phase 2 (TypeScript — `editors/vscode/`)

### `package.json` (Key Fields)

```json
{
  "name": "nexus3-ide",
  "displayName": "NEXUS3 IDE Integration",
  "description": "IDE integration for NEXUS3 AI agent framework",
  "version": "0.1.0",
  "publisher": "nexus3",
  "engines": { "vscode": "^1.85.0" },
  "activationEvents": ["onStartupFinished"],
  "main": "./dist/extension.js",
  "contributes": {
    "commands": [
      { "command": "nexus3.diffAccept", "title": "Accept Changes", "icon": "$(check)" },
      { "command": "nexus3.diffReject", "title": "Reject Changes", "icon": "$(close)" }
    ],
    "menus": {
      "editor/title": [
        { "command": "nexus3.diffAccept", "when": "resourceScheme == nexus3-diff", "group": "navigation@1" },
        { "command": "nexus3.diffReject", "when": "resourceScheme == nexus3-diff", "group": "navigation@2" }
      ]
    }
  },
  "dependencies": { "ws": "^8.16.0" },
  "devDependencies": {
    "@types/vscode": "^1.85.0",
    "@types/ws": "^8.5.10",
    "typescript": "^5.3.0",
    "esbuild": "^0.19.0"
  }
}
```

### MCP Server Handshake (in `src/server.ts`)

The server must implement this sequence:

1. **Receive `initialize` request**: Client sends `{method: "initialize", params: {protocolVersion, capabilities, clientInfo}}`.
2. **Respond**: `{result: {protocolVersion: "2024-11-05", capabilities: {tools: {}}, serverInfo: {name: "nexus3-ide", version: "0.1.0"}}}`.
3. **Receive `notifications/initialized`**: Client sends notification (no response needed).
4. **Handle `tools/list`**: Return array of all 11 tool schemas with `name`, `description`, `inputSchema` (JSON Schema).
5. **Handle `tools/call`**: Dispatch to tool handlers. Return `{result: {content: [{type: "text", text: "..."}]}}`.

For `openDiff`: the JSON-RPC response is **deferred** — the server holds the response callback until the user accepts/rejects. The WebSocket connection stays open; this is standard async behavior over WebSocket (no HTTP timeout issue).

### openDiff Tool (Critical — `src/tools/openDiff.ts`)

This is the most complex tool. Implementation:

**1. Register a `TextDocumentContentProvider`** with custom URI scheme `nexus3-diff`:

```typescript
const proposedContent = new Map<string, string>();  // tabName → content

class DiffContentProvider implements vscode.TextDocumentContentProvider {
    provideTextDocumentContent(uri: vscode.Uri): string {
        return proposedContent.get(uri.query) ?? "";
    }
}
vscode.workspace.registerTextDocumentContentProvider("nexus3-diff", new DiffContentProvider());
```

**2. When `openDiff` is called:**

```typescript
async function handleOpenDiff(params: OpenDiffParams): Promise<string> {
    const { old_file_path, new_file_path, new_file_contents, tab_name } = params;

    // Store proposed content for the content provider
    proposedContent.set(tab_name, new_file_contents);

    // Create URIs
    const originalUri = vscode.Uri.file(old_file_path);
    const proposedUri = vscode.Uri.from({ scheme: "nexus3-diff", path: new_file_path, query: tab_name });

    // Open VS Code's native diff editor
    await vscode.commands.executeCommand("vscode.diff", originalUri, proposedUri, `NEXUS3: ${tab_name}`);

    // Return a Promise that resolves when user clicks Accept or Reject
    return new Promise<string>((resolve) => {
        pendingDiffs.set(tab_name, { resolve });
    });
}
```

**3. Accept/Reject via editor title buttons:**

Commands registered in `package.json` (`contributes.menus["editor/title"]`) show checkmark/X buttons ONLY when `resourceScheme == nexus3-diff`.

```typescript
vscode.commands.registerCommand("nexus3.diffAccept", async () => {
    // Find which diff tab is active
    const activeTab = vscode.window.tabGroups.activeTabGroup.activeTab;
    const tabName = extractTabName(activeTab);  // from URI query param
    if (!tabName || !pendingDiffs.has(tabName)) return;

    // Write the proposed content to disk
    const content = proposedContent.get(tabName)!;
    await vscode.workspace.fs.writeFile(
        vscode.Uri.file(extractFilePath(activeTab)),
        Buffer.from(content, "utf-8"),
    );

    // Resolve the pending promise → sends JSON-RPC response
    pendingDiffs.get(tabName)!.resolve("FILE_SAVED");
    pendingDiffs.delete(tabName);
    proposedContent.delete(tabName);

    // Close the diff tab
    await vscode.commands.executeCommand("workbench.action.closeActiveEditor");
});

vscode.commands.registerCommand("nexus3.diffReject", async () => {
    const activeTab = vscode.window.tabGroups.activeTabGroup.activeTab;
    const tabName = extractTabName(activeTab);
    if (!tabName || !pendingDiffs.has(tabName)) return;

    pendingDiffs.get(tabName)!.resolve("DIFF_REJECTED");
    pendingDiffs.delete(tabName);
    proposedContent.delete(tabName);
    await vscode.commands.executeCommand("workbench.action.closeActiveEditor");
});
```

**4. Safety net — tab close detection:**

If user closes the diff tab without clicking either button, treat as rejection:

```typescript
vscode.window.tabGroups.onDidChangeTabs((event) => {
    for (const closed of event.closed) {
        if (closed.input instanceof vscode.TabInputTextDiff) {
            const uri = closed.input.modified;
            if (uri.scheme === "nexus3-diff") {
                const tabName = uri.query;
                if (pendingDiffs.has(tabName)) {
                    pendingDiffs.get(tabName)!.resolve("DIFF_REJECTED");
                    pendingDiffs.delete(tabName);
                    proposedContent.delete(tabName);
                }
            }
        }
    }
});
```

### `getLatestSelection` vs `getCurrentSelection`

- `getCurrentSelection`: Returns `vscode.window.activeTextEditor?.selection` — only available when an editor has focus.
- `getLatestSelection`: Extension tracks a `lastSelection` variable updated via `vscode.window.onDidChangeTextEditorSelection`. Persists even after focus moves to terminal or other panels. Returns the tracked value.

### Lock File Lifecycle (in `src/extension.ts`)

1. **activate()**: Create `~/.nexus3/ide/` directory (via `os.homedir()` + `fs.mkdirSync`). Start WebSocket server on port 0 (OS auto-assign). Write lock file `<port>.lock` with `0o600` permissions.
2. **deactivate()**: Delete lock file. Close WebSocket server.
3. **Crash recovery**: NEXUS3's `discover_ides()` validates PIDs and cleans up stale files.

---

## Implementation Details: Phase 3 (NEXUS3 Integration)

### P3.1 — IDEConfig (`nexus3/config/schema.py`)

Add after `ClipboardConfig` (line 315), before `ContextConfig` (line 317). Uses same `ConfigDict(extra="forbid")` pattern. Add `ide: IDEConfig = IDEConfig()` to `Config` class fields (after `clipboard` field, around line 674).

### P3.2 — SharedComponents + ServiceContainer (`nexus3/rpc/pool.py`)

Add `IDEBridge` import under `TYPE_CHECKING` block (line 69) to avoid circular imports:
```python
if TYPE_CHECKING:
    ...
    from nexus3.ide.bridge import IDEBridge
```

Add field to `SharedComponents` (after `is_repl`, line 252):
```python
ide_bridge: IDEBridge | None = None
```

Update docstring `Attributes:` section to include `ide_bridge`.

**Also in `_create_unlocked()`**: Register `ide_bridge` in ServiceContainer (like `clipboard_manager` at line ~580):
```python
if self._shared.ide_bridge is not None:
    services.register("ide_bridge", self._shared.ide_bridge)
```

This is critical — Session needs access to the bridge via ServiceContainer (for P3.9).

### P3.3 — Bootstrap (`nexus3/rpc/bootstrap.py`)

Add between Phase 3 (custom presets, line 300) and Phase 4 (SharedComponents creation, line 303):

```python
# Phase 3.5: Create IDE bridge (optional, REPL-only)
ide_bridge: IDEBridge | None = None
if is_repl and config.ide.enabled:
    from nexus3.ide.bridge import IDEBridge
    ide_bridge = IDEBridge(config=config.ide)

# Phase 4: Create SharedComponents
shared = SharedComponents(
    ...existing fields...,
    ide_bridge=ide_bridge,
)
```

Note: Bridge is created but NOT connected here. Connection happens in REPL startup (P3.7) after the agent's CWD is known.

### P3.4/P3.5 — ContextManager (`nexus3/context/manager.py`)

Add `_ide_context` field after `_git_context` (line 240):
```python
self._ide_context: str | None = None
```

Add refresh method after `refresh_git_context()` (line 260):
```python
def refresh_ide_context(self, ide_context: str | None) -> None:
    """Update cached IDE context. Caller is responsible for formatting."""
    self._ide_context = ide_context
```

Note: Takes a pre-formatted string (NOT the bridge). Same pattern as `_git_context` — the caller (session.py or repl.py) fetches IDE state, formats it via `format_ide_context()`, and passes the string in.

In `_build_system_prompt_for_api_call()`, inject after git context (line 330) and before clipboard (line 333):
```python
# Add IDE context if available
if self._ide_context:
    prompt = f"{prompt}\n\n{self._ide_context}"
```

### P3.6 — IDE-Aware Confirmation Callback (`nexus3/cli/repl.py`)

Define after `confirm_with_pause` (line 327):

```python
# Tools eligible for IDE diff approval
_IDE_DIFF_TOOLS = frozenset({
    "write_file", "edit_file", "edit_lines", "append_file",
    "regex_replace", "patch",
})

async def _extract_proposed_content(tool_call: ToolCall, target_path: Path) -> str | None:
    """Extract the full proposed file content for a diff.

    For write_file: content argument IS the full file.
    For edit_file/edit_lines/append_file/regex_replace: read current file, apply change.
    For patch: read current file, apply diff.
    Returns None if extraction fails (fall back to terminal).
    """
    args = tool_call.arguments
    if tool_call.name == "write_file":
        return args.get("content", "")
    # For modification tools, read current file and compute result
    try:
        current = target_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if tool_call.name == "edit_file":
        old = args.get("old_string", "")
        new = args.get("new_string", "")
        if args.get("replace_all"):
            return current.replace(old, new)
        return current.replace(old, new, 1)
    if tool_call.name == "append_file":
        content = args.get("content", "")
        newline = "\n" if args.get("newline", True) else ""
        return current + newline + content
    # regex_replace, edit_lines, patch — more complex, fall back to terminal
    return None

async def confirm_with_ide_or_terminal(
    tool_call: ToolCall,
    target_path: Path | None,
    agent_cwd: Path,
) -> ConfirmationResult:
    """IDE-aware confirmation: route file writes to VS Code diff when available."""
    ide_bridge = shared.ide_bridge if shared else None
    if (
        ide_bridge
        and ide_bridge.is_connected
        and tool_call.name in _IDE_DIFF_TOOLS
        and target_path
    ):
        proposed = await _extract_proposed_content(tool_call, target_path)
        if proposed is not None:
            try:
                async with ide_bridge._diff_lock:  # noqa: SLF001
                    outcome = await ide_bridge.connection.open_diff(
                        old_file_path=str(target_path),
                        new_file_path=str(target_path),
                        new_file_contents=proposed,
                        tab_name=target_path.name,
                    )
                if outcome == DiffOutcome.FILE_SAVED:
                    return ConfirmationResult.ALLOW_ONCE
                return ConfirmationResult.DENY
            except Exception:
                logger.debug("IDE diff failed, falling back to terminal", exc_info=True)
    return await confirm_with_pause(tool_call, target_path, agent_cwd)
```

### P3.7 — Wire callback + auto-connect

Replace `confirm_with_pause` with `confirm_with_ide_or_terminal` at ALL 6 `on_confirm` assignment sites (lines 414, 1365, 1409, 1427, 1461, 1477):
```python
session.on_confirm = confirm_with_ide_or_terminal
```

Auto-connect after main agent creation (after line 414):
```python
if shared.ide_bridge:
    agent_cwd = main_agent.services.get_cwd()
    conn = await shared.ide_bridge.auto_connect(agent_cwd)
    if conn:
        get_console().print(f"[dim]IDE connected: {conn.ide_info.ide_name}[/]")
```

### P3.8 — `/ide` command (`nexus3/cli/repl_commands.py`)

Add after `cmd_gitlab()` (line 2227). Pattern follows `cmd_mcp()` (line 1680):

```python
async def cmd_ide(ctx: CommandContext, args: str | None = None) -> CommandOutput:
    """Handle /ide commands.

    /ide              Show connection status
    /ide connect      Manual connect (scan for IDEs)
    /ide disconnect   Disconnect from IDE
    """
```

Register dispatch in `repl.py` (after the `elif cmd_name == "gitlab"` block, around line 1150):
```python
elif cmd_name == "ide":
    return await repl_commands.cmd_ide(ctx, cmd_args or None)
```

### P3.9 — Tool batch IDE context refresh (`nexus3/session/session.py`)

Add after git context refresh (line 593). Session accesses bridge via `self._services.get("ide_bridge")`:

```python
# Refresh IDE context if bridge available
ide_bridge = self._services.get("ide_bridge") if self._services else None
if self.context and ide_bridge and ide_bridge.is_connected:
    try:
        conn = ide_bridge.connection
        editors = await conn.get_open_editors()
        diagnostics = await conn.get_diagnostics()
        from nexus3.ide.context import format_ide_context
        ide_ctx = format_ide_context(
            ide_name=conn.ide_info.ide_name,
            open_editors=editors,
            diagnostics=diagnostics,
            inject_diagnostics=True,
            inject_open_editors=True,
        )
        self.context.refresh_ide_context(ide_ctx)
    except Exception:
        pass  # Non-fatal — IDE context is informational
```

---

## Codebase Validation Notes

Validated by subagent against actual codebase. 7/8 claims verified with zero discrepancies. One minor finding:

| Claim | File:Line | Status | Notes |
|-------|-----------|--------|-------|
| MCPTransport ABC methods | `mcp/transport.py:179` | Verified | `connect`, `send`, `receive`, `close` are abstract; `request()` has default impl |
| `is_connected` on ABC | `mcp/transport.py` | **Not on ABC** | Only on concrete impls (StdioTransport:528, HTTPTransport:788). WebSocketTransport adds it as concrete property. |
| MCPClient.call_tool() | `mcp/client.py:334` | Verified | `call_tool(name, arguments=None) -> MCPToolResult`. Works with any transport. |
| MCPClient.connect() timeout | `mcp/client.py:92` | Verified | Default 30s. Handles cleanup on timeout. |
| SharedComponents frozen | `rpc/pool.py:224` | Verified | `@dataclass(frozen=True)`. Optional fields use `= None` or `field(default_factory=...)`. |
| ContextManager injection | `context/manager.py:310` | Verified | Order: datetime → git → clipboard. `_git_context` at line 240. |
| ConfirmationCallback type | `session/confirmation.py:16` | Verified | `Callable[[ToolCall, Path \| None, Path], Awaitable[ConfirmationResult]]` |
| confirm_with_pause usage | `cli/repl.py:320,414` | Verified | Also re-assigned at lines 1365, 1409, 1427, 1461, 1477 (agent switch/create/restore). |
| Bootstrap SharedComponents | `rpc/bootstrap.py:303` | Verified | Can add field without changing function signature. |
| ClipboardConfig pattern | `config/schema.py:277` | Verified | `ConfigDict(extra="forbid")`, Field with defaults. |
| Git context refresh | `session/session.py:587` | Verified | After `ToolBatchCompleted`, checks `should_refresh_git_context()`. Also refreshed during compaction (line 1046). |
| MCPClient notification loop | `mcp/client.py:230` | Verified | `_call()` has its own notification-discarding loop. WebSocketTransport.receive() must queue ALL messages (don't pre-filter). |

---

## Files to Modify/Create

| File | Change |
|------|--------|
| `nexus3/ide/__init__.py` | **NEW** — Public API |
| `nexus3/ide/bridge.py` | **NEW** — IDEBridge lifecycle |
| `nexus3/ide/connection.py` | **NEW** — IDEConnection + result types |
| `nexus3/ide/discovery.py` | **NEW** — Lock file scanning |
| `nexus3/ide/transport.py` | **NEW** — WebSocketTransport |
| `nexus3/ide/context.py` | **NEW** — IDE context formatting |
| `nexus3/ide/README.md` | **NEW** — Module docs |
| `editors/vscode/` | **NEW** — Entire VS Code extension |
| `nexus3/config/schema.py` | Add IDEConfig |
| `nexus3/rpc/pool.py` | Add ide_bridge to SharedComponents + ServiceContainer registration |
| `nexus3/rpc/bootstrap.py` | Initialize IDE bridge |
| `nexus3/context/manager.py` | Add _ide_context, refresh, inject |
| `nexus3/cli/repl.py` | IDE-aware confirm callback, auto-connect |
| `nexus3/cli/repl_commands.py` | Add /ide command |
| `nexus3/session/session.py` | IDE context refresh on tool batch |
| `pyproject.toml` | Add websockets dependency |
| `tests/unit/ide/` | **NEW** — Unit tests |

---

## Implementation Checklist

### Phase 1: Protocol Foundation — DONE (commit d4a9154)
- [x] **P1.1** Add `websockets>=13.0` to `pyproject.toml`
- [x] **P1.2** `WebSocketTransport` in `nexus3/ide/transport.py`
- [x] **P1.3** Lock file discovery in `nexus3/ide/discovery.py`
- [x] **P1.4** Result types + `IDEConnection` in `nexus3/ide/connection.py`
- [x] **P1.5** `IDEBridge` in `nexus3/ide/bridge.py`
- [x] **P1.6** `format_ide_context()` in `nexus3/ide/context.py`
- [x] **P1.7** `nexus3/ide/__init__.py` with exports
- [x] **P1.8** 52 unit tests in `tests/unit/ide/` (all pass)
- [x] **P1.9** Lint + tests clean

### Phase 2: VS Code Extension — DONE (commit cf1d8e4)
- [x] **P2.1** Scaffold: `package.json`, `tsconfig.json`, `types.ts`
- [x] **P2.2** WebSocket MCP server in `src/server.ts`
- [x] **P2.3** Lock file lifecycle in `src/extension.ts` + `src/uuid.ts`
- [x] **P2.4** `openDiff` tool with accept/reject buttons and tab close fallback
- [x] **P2.5** `openFile` tool
- [x] **P2.6** Remaining tools: diagnostics, selection, workspace, document, tabs
- [x] **P2.7** Tool dispatch in `src/tools/index.ts` (11 tools)
- [x] **P2.8** Extension builds clean (`npm run build` + `tsc --noEmit` zero errors)

### Phase 3: NEXUS3 Integration (IN PROGRESS — next up)
- [ ] **P3.1** Add `IDEConfig` to `nexus3/config/schema.py` (can parallel P3.2–P3.5)
- [ ] **P3.2** Add `ide_bridge` to `SharedComponents` + register in ServiceContainer in `_create_unlocked()` (in `nexus3/rpc/pool.py`)
- [ ] **P3.3** Initialize IDE bridge in `nexus3/rpc/bootstrap.py` (requires P3.1, P3.2)
- [ ] **P3.4** Add `_ide_context` + `refresh_ide_context(ide_context: str | None)` to `ContextManager` (can parallel P3.1–P3.3)
- [ ] **P3.5** Inject IDE context in `_build_system_prompt_for_api_call()` (requires P3.4)
- [ ] **P3.6** Implement IDE-aware confirmation callback + content extraction in `nexus3/cli/repl.py` (requires P3.3)
- [ ] **P3.7** Wire `confirm_with_ide_or_terminal` at all 6 `on_confirm` sites (lines 414, 1365, 1409, 1427, 1461, 1477) + auto-connect on startup (requires P3.6)
- [ ] **P3.8** Add `cmd_ide()` to `nexus3/cli/repl_commands.py` + dispatch in `repl.py` (can parallel P3.6)
- [ ] **P3.9** Add IDE context refresh on tool batch completion in `nexus3/session/session.py` (requires P3.2, P3.4)
- [ ] **P3.10** Write integration tests for confirmation flow and context injection
- [ ] **P3.11** Verify: `ruff check nexus3/` and `pytest tests/` pass

### Phase 4: Polish & Error Recovery (After Phase 2+3)
- [ ] **P4.1** WebSocket reconnection on connection loss
- [ ] **P4.2** Handle IDE restart (extension deactivate/reactivate)
- [ ] **P4.3** Edge cases: new file diff (empty old side), multiple simultaneous diffs, large files

### Phase 5: Documentation (After Implementation Complete)
- [ ] **P5.1** Write `nexus3/ide/README.md` (module architecture, classes, usage)
- [ ] **P5.2** Write `editors/vscode/README.md` (install, configure, develop)
- [ ] **P5.3** Update `CLAUDE.md` Architecture section: add `ide/` module to module structure table
- [ ] **P5.4** Update `CLAUDE.md` REPL Commands Reference: add `/ide` command rows
- [ ] **P5.5** Update `CLAUDE.md` Configuration Reference: add IDEConfig section with example JSON
- [ ] **P5.6** Update `CLAUDE.md` Context System: add "IDE Context" subsection (parallel to "Git Repository Context")
- [ ] **P5.7** Add IDE-aware guidance to `NEXUS-DEFAULT.md` (when IDE connected, how agent should use it)
- [ ] **P5.8** Update root `README.md` feature list with IDE integration

---

## Testing Strategy

### Unit Tests (`tests/unit/ide/`)

Create `tests/unit/ide/__init__.py` (empty). Then:

| File | What to Test | Mocking Strategy |
|------|-------------|-----------------|
| `test_transport.py` | connect/send/receive/close lifecycle, auth header, is_connected, disconnect handling | Mock `websockets.connect()` returning a mock WebSocket |
| `test_discovery.py` | Lock file parsing, PID validation (alive/dead/permission error), workspace matching, stale cleanup, missing directory, malformed JSON | Mock `Path.glob()`, `os.kill()`, `Path.read_text()` |
| `test_connection.py` | Tool call parameter mapping, DiffOutcome parsing, Diagnostic/Selection/EditorInfo parsing, error handling | Mock `MCPClient.call_tool()` returning `MCPToolResult` |
| `test_bridge.py` | auto_connect with/without matching IDE, connect/disconnect lifecycle, diff_lock serialization | Mock `discover_ides()` and `MCPClient` |
| `test_context.py` | Formatting with various inputs, 800-char truncation, empty inputs → None, partial inputs | Direct function calls (no mocking needed) |

Use `@pytest.mark.asyncio` for async tests. Import from `nexus3.ide.*`.

### Integration Tests

- Mock IDE: Create a simple WebSocket MCP server in Python (using `websockets`) that responds to `openDiff` with `FILE_SAVED`. Verify confirmation callback returns `ALLOW_ONCE`.
- Context injection: Verify IDE context appears in system prompt after `refresh_ide_context()`.
- Fallback: Verify terminal confirmation resumes when IDE disconnects.

---

## Verification

1. `.venv/bin/ruff check nexus3/` — 0 errors
2. `.venv/bin/pytest tests/` — all pass
3. Live test:
   - Install VS Code extension: `cd editors/vscode && npm install && npm run build`, then install via VS Code
   - Start NEXUS3 REPL: `nexus3`
   - Verify `/ide` shows "Connected: VS Code"
   - Have agent write a file → diff appears in VS Code with Accept/Reject buttons
   - Accept → file written, agent continues
   - Reject → agent sees rejection, adapts
   - Disconnect IDE (close VS Code) → terminal confirmation resumes
   - Verify diagnostics in agent context via `/status -a`
