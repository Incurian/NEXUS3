# NEXUS3 IDE Integration

VS Code extension that bridges NEXUS3 AI agents with the editor via WebSocket MCP (Model Context Protocol). Agents gain access to editor-native capabilities: diff-based file write confirmations, LSP diagnostics, open tab awareness, text selections, and document operations.

## Architecture

```
Extension Activation
└── server.ts (WebSocket MCP Server)
    ├── Lock file lifecycle (extension.ts)
    │   └── ~/.nexus3/ide/<port>.lock
    └── Tool dispatch (tools/index.ts)
        ├── openDiff.ts     (diff + accept/reject)
        ├── openFile.ts     (open file in editor)
        ├── diagnostics.ts  (LSP errors/warnings)
        ├── selection.ts    (text selection tracking)
        ├── workspace.ts    (workspace folders)
        ├── document.ts     (save, dirty check)
        └── tabs.ts         (close tab, close all diffs)
```

On activation, the extension starts a WebSocket server on a dynamic port bound to `127.0.0.1`, writes a lock file to `~/.nexus3/ide/<port>.lock`, and begins accepting MCP connections. On deactivation, the lock file is deleted and the server is closed.

## Installation

### From Source

```bash
cd editors/vscode
npm install
npm run build
```

Then install in VS Code using one of:
- Extensions sidebar > `...` menu > "Install from VSIX..."
- `code --install-extension nexus3-ide-0.1.0.vsix`

### Requirements

- VS Code 1.85.0 or later

## Lock File

Written to `~/.nexus3/ide/<port>.lock` on activation, deleted on deactivation. The filename is the port number. NEXUS3 agents discover running IDE instances by scanning this directory.

```json
{
  "pid": 12345,
  "workspaceFolders": ["/home/user/project"],
  "ideName": "VS Code",
  "transport": "ws",
  "authToken": "random-uuid"
}
```

The workspace folders list updates automatically when folders are added or removed from the VS Code workspace.

## Tools Reference

The extension exposes 11 tools via the MCP `tools/list` and `tools/call` protocol.

### Diff

| Tool | Parameters | Returns | Description |
|------|-----------|---------|-------------|
| `openDiff` | `old_file_path`, `new_file_path`, `new_file_contents`, `tab_name` | `FILE_SAVED` or `DIFF_REJECTED` | Shows a diff editor with Accept/Reject buttons. Blocks until the user acts or closes the tab. |

### File Operations

| Tool | Parameters | Returns | Description |
|------|-----------|---------|-------------|
| `openFile` | `filePath`, `preview`? | -- | Opens a file in the editor. |
| `checkDocumentDirty` | `filePath` | `{dirty: bool}` JSON | Checks if a file has unsaved changes. |
| `saveDocument` | `filePath` | -- | Saves an open document. |

### Editor State

| Tool | Parameters | Returns | Description |
|------|-----------|---------|-------------|
| `getCurrentSelection` | -- | Selection JSON or `null` | Text selection in the active editor. |
| `getLatestSelection` | -- | Selection JSON or `null` | Most recent selection, persists across focus changes. |
| `getOpenEditors` | -- | `EditorInfo[]` JSON | All open editor tabs with path, active, dirty, and language info. |
| `getDiagnostics` | `uri`? | `Diagnostic[]` JSON | LSP diagnostics for a specific file or all files. |

### Workspace

| Tool | Parameters | Returns | Description |
|------|-----------|---------|-------------|
| `getWorkspaceFolders` | -- | `string[]` JSON | Workspace folder paths. |

### Tab Management

| Tool | Parameters | Returns | Description |
|------|-----------|---------|-------------|
| `closeTab` | `tabName` | -- | Closes a tab by its label. |
| `closeAllDiffTabs` | -- | -- | Closes all NEXUS3 diff tabs. |

## Diff Workflow

The `openDiff` tool is the primary integration point for agent-driven file edits:

1. A NEXUS3 agent calls `openDiff` with the original file path and proposed new contents.
2. The extension opens a VS Code diff editor showing original vs. proposed.
3. Accept and Reject buttons appear in the editor title bar.
4. The user clicks Accept -- the file is written with the proposed contents and the tool returns `FILE_SAVED`.
5. The user clicks Reject or closes the diff tab -- the tool returns `DIFF_REJECTED`.
6. The tool call blocks (async promise) until resolution, so the agent waits for the user's decision.

### Editor Commands

| Command | Title | Visible When |
|---------|-------|--------------|
| `nexus3.diffAccept` | Accept Changes | In NEXUS3 diff tabs (`resourceScheme == nexus3-diff`) |
| `nexus3.diffReject` | Reject Changes | In NEXUS3 diff tabs (`resourceScheme == nexus3-diff`) |

## Development

```bash
npm install        # Install dependencies
npm run build      # Build with esbuild
npm run watch      # Watch mode (rebuilds on change)
npm run lint       # TypeScript type checking (tsc --noEmit)
```

### Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `ws` | ^8.16.0 | WebSocket server |
| `typescript` | ^5.3.0 | Type checking (dev) |
| `esbuild` | ^0.19.0 | Bundler (dev) |
| `@types/vscode` | ^1.85.0 | VS Code API types (dev) |
| `@types/ws` | ^8.5.10 | WebSocket types (dev) |
| `@types/node` | ^20.0.0 | Node.js types (dev) |

## Security

- **Localhost only.** The WebSocket server binds to `127.0.0.1` -- no network exposure.
- **Per-session auth token.** A UUID v4 token is generated on activation and written to the lock file. Every incoming WebSocket connection must present this token in the `x-nexus3-ide-authorization` header. Connections with missing or invalid tokens are rejected with close code 4001.
- **Lock file permissions.** The lock file is written with mode `0600` (owner read/write only).
- **PID tracking.** The lock file includes the extension host PID for stale lock detection.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Extension not activating | Check VS Code version >= 1.85.0. Check the Output panel for `NEXUS3 IDE` errors. |
| NEXUS3 agent cannot find IDE | Verify lock file exists in `~/.nexus3/ide/`. Check that the PID in the lock file matches a running VS Code process. |
| Diff accept/reject buttons missing | Buttons only appear when `resourceScheme == nexus3-diff`. Try reloading the VS Code window. |
| WebSocket connection refused | Check if another process is using the port. Check firewall rules for localhost connections. |
| Stale lock file after crash | Delete the orphaned `.lock` file from `~/.nexus3/ide/` manually. |
