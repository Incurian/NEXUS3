# Plan: NEXUS as MCP Server

## OPEN QUESTIONS

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| **Q1** | Separate project or subpackage? | A) New repo B) nexus3.mcp_server subpackage | **A) New repo** - cleaner separation |
| **Q2** | Which skills to expose? | A) All safe skills B) Configurable list C) Category-based | **C) Categories** - flexible |
| **Q3** | Transport modes? | A) stdio only B) HTTP only C) Both | **C) Both** - max compatibility |
| **Q4** | Permission model? | A) All tools unrestricted B) Configurable per-tool C) Inherit from config | **B) Configurable** |
| **Q5** | State management? | A) Stateless B) Session support | **A) Stateless** - simpler, MCP standard |

---

## Overview

**Concept:** Expose NEXUS3's built-in skills as MCP tools for use by any MCP-compatible agent system (Claude Desktop, other agents, etc.).

**Value:** Users get NEXUS3's file operations, search, git integration without running full NEXUS3 agent.

---

## Scope

### Included (v1)
- MCPServer class handling protocol
- Stdio transport (for subprocess mode)
- HTTP transport (for remote/API mode)
- Configurable skill exposure by category
- Basic permission filtering

### Deferred (v2+)
- MCP Resources (file access)
- MCP Prompts (skill templates)
- Session/state management
- Streaming tool output

### Explicitly Excluded
- Agent management skills (nexus_create, etc.)
- Clipboard skills (require session state)
- GitLab skills (require auth tokens)

---

## Architecture

### New Project Structure

```
nexus-mcp-server/
├── pyproject.toml
├── README.md
├── nexus_mcp/
│   ├── __init__.py
│   ├── server.py          # MCPServer class
│   ├── transport/
│   │   ├── __init__.py
│   │   ├── base.py        # MCPServerTransport protocol
│   │   ├── stdio.py       # StdioServerTransport
│   │   └── http.py        # HTTPServerTransport
│   ├── skills/            # Copied/adapted from nexus3
│   │   ├── __init__.py
│   │   ├── base.py        # Simplified Skill protocol
│   │   ├── read_file.py
│   │   ├── write_file.py
│   │   ├── glob.py
│   │   ├── grep.py
│   │   └── ...
│   └── config.py          # Skill exposure config
└── tests/
```

### Key Differences from NEXUS3

| Aspect | NEXUS3 | Standalone MCP Server |
|--------|--------|----------------------|
| **Context** | Multi-agent framework | Stateless tool server |
| **Permissions** | 3 levels + per-tool config | Simple enabled/disabled per category |
| **Path Control** | Per-tool allowed_paths | Global config-based |
| **Dependencies** | ServiceContainer DI | Simple config object |
| **Tool Format** | OpenAI function calling | MCP tool schema |
| **State** | Session-aware | Stateless |

### Skill Categories

| Category | Skills | Default |
|----------|--------|---------|
| **read** | read_file, tail, file_info, list_directory | Enabled |
| **search** | glob, grep, concat_files | Enabled |
| **write** | write_file, edit_file, append_file, mkdir, rename, copy_file | Disabled |
| **execute** | bash_safe, run_python | Disabled |
| **vcs** | git (read-only subset) | Enabled |

### Protocol Flow

```
External Client                    NEXUS MCP Server
     │                                   │
     │──── initialize ──────────────────>│
     │<─── capabilities ─────────────────│
     │                                   │
     │──── tools/list ──────────────────>│
     │<─── tool definitions ─────────────│
     │                                   │
     │──── tools/call {read_file} ──────>│
     │                      ┌────────────┤
     │                      │ skill.execute()
     │                      └────────────┤
     │<─── tool result ──────────────────│
```

---

## What to Extract from NEXUS3

### Can Copy Directly
- `core/types.py` - `ToolResult` dataclass
- `core/errors.py` - `PathSecurityError`, `NexusError`
- `core/paths.py` - Path validation logic

### Need Moderate Adaptation
- `skill/base.py` - Simplified `FileSkill` without `ServiceContainer`
- `skill/registry.py` - Remove permission filtering, simpler registration
- `skill/builtin/read_file.py` - Direct config instead of services
- `skill/builtin/glob_search.py` - Same as read_file
- `skill/builtin/grep.py` - Remove sandbox checks, keep parallel search

### Reference for Protocol
- `mcp/transport.py` - Flip client→server logic
- `mcp/client.py` - Understand JSON-RPC message format

---

## Implementation

### Phase 1: Core Server

**File:** `nexus_mcp/server.py`

```python
from typing import Any
from nexus_mcp.skills import SkillRegistry

class MCPServer:
    """MCP Server exposing NEXUS skills as tools."""

    def __init__(self, config: ServerConfig):
        self.config = config
        self.registry = SkillRegistry(config.enabled_categories)

    async def handle_request(self, request: dict) -> dict:
        method = request.get("method")

        if method == "initialize":
            return self._handle_initialize(request)
        elif method == "tools/list":
            return self._handle_list_tools(request)
        elif method == "tools/call":
            return await self._handle_call_tool(request)
        else:
            return {"error": {"code": -32601, "message": "Method not found"}}

    def _handle_initialize(self, request: dict) -> dict:
        return {
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "nexus-mcp", "version": "1.0.0"},
                "capabilities": {"tools": {}}
            }
        }

    def _handle_list_tools(self, request: dict) -> dict:
        tools = []
        for skill in self.registry.all():
            tools.append({
                "name": skill.name,
                "description": skill.description,
                "inputSchema": skill.parameters,  # MCP uses inputSchema, not parameters
            })
        return {"result": {"tools": tools}}

    async def _handle_call_tool(self, request: dict) -> dict:
        params = request.get("params", {})
        name = params.get("name")
        arguments = params.get("arguments", {})

        skill = self.registry.get(name)
        if not skill:
            return {"error": {"code": -32602, "message": f"Unknown tool: {name}"}}

        result = await skill.execute(**arguments)

        return {
            "result": {
                "content": [{"type": "text", "text": result.output or result.error}],
                "isError": not result.success
            }
        }
```

### Phase 2: Simplified Config

**File:** `nexus_mcp/config.py`

```python
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class ServerConfig:
    """Configuration for MCP server behavior."""
    working_directory: Path = field(default_factory=Path.cwd)
    allowed_paths: list[Path] | None = None  # None = unrestricted
    blocked_paths: list[Path] = field(default_factory=list)
    enabled_categories: set[str] = field(default_factory=lambda: {"read", "search", "vcs"})
    max_file_size: int = 50 * 1024 * 1024  # 50MB
```

### Phase 3: Simplified FileSkill

**File:** `nexus_mcp/skills/base.py`

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

@dataclass
class ToolResult:
    """Result from skill execution."""
    output: str = ""
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.error is None

class Skill(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def description(self) -> str: ...
    @property
    def parameters(self) -> dict[str, Any]: ...
    async def execute(self, **kwargs: Any) -> ToolResult: ...

class FileSkill:
    """Base class for file-based skills with path validation."""

    def __init__(self, config: "ServerConfig"):
        self.config = config

    def _validate_path(self, path_str: str) -> Path | ToolResult:
        """Validate and resolve a path. Returns Path or error ToolResult."""
        if not path_str:
            return ToolResult(error="No path provided")

        resolved = (self.config.working_directory / path_str).resolve()

        # Check blocked paths
        for blocked in self.config.blocked_paths:
            if resolved == blocked or blocked in resolved.parents:
                return ToolResult(error="Access denied")

        # Check allowed paths
        if self.config.allowed_paths is not None:
            allowed = False
            for allowed_path in self.config.allowed_paths:
                if resolved == allowed_path or allowed_path in resolved.parents:
                    allowed = True
                    break
            if not allowed:
                return ToolResult(error="Path not in allowed list")

        return resolved
```

### Phase 4: Example Skill Port

**File:** `nexus_mcp/skills/read_file.py`

```python
from pathlib import Path
from typing import Any
from nexus_mcp.skills.base import FileSkill, ToolResult

class ReadFileSkill(FileSkill):
    """Read contents of a file."""

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read contents of a file"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to file"},
                "offset": {"type": "integer", "description": "Line offset (0-indexed)"},
                "limit": {"type": "integer", "description": "Max lines to read"},
            },
            "required": ["path"],
        }

    async def execute(
        self, path: str = "", offset: int = 0, limit: int = 2000, **kwargs: Any
    ) -> ToolResult:
        validated = self._validate_path(path)
        if isinstance(validated, ToolResult):
            return validated

        if not validated.is_file():
            return ToolResult(error=f"Not a file: {path}")

        try:
            content = validated.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()

            # Apply offset and limit
            if offset > 0:
                lines = lines[offset:]
            if limit > 0:
                lines = lines[:limit]

            # Format with line numbers
            numbered = [f"{i + offset + 1:6d}  {line}" for i, line in enumerate(lines)]
            return ToolResult(output="\n".join(numbered))
        except Exception as e:
            return ToolResult(error=str(e))
```

---

## CLI Usage

```bash
# Stdio mode (for Claude Desktop, etc.)
nexus-mcp-server

# HTTP mode
nexus-mcp-server --http --port 8766

# With config
nexus-mcp-server --config ~/.config/nexus-mcp/config.json

# Enable specific categories
nexus-mcp-server --enable read,search,write
```

### Claude Desktop Integration

```json
// claude_desktop_config.json
{
  "mcpServers": {
    "nexus": {
      "command": "nexus-mcp-server",
      "args": ["--enable", "read,search,vcs"]
    }
  }
}
```

---

## Files to Create (New Project)

| File | Purpose |
|------|---------|
| `nexus_mcp/server.py` | Core MCPServer class |
| `nexus_mcp/transport/stdio.py` | Stdio transport |
| `nexus_mcp/transport/http.py` | HTTP transport |
| `nexus_mcp/skills/base.py` | Skill protocol, ToolResult, FileSkill |
| `nexus_mcp/skills/*.py` | Individual skill implementations |
| `nexus_mcp/config.py` | Configuration handling |
| `nexus_mcp/__main__.py` | CLI entry point |

---

## Implementation Checklist

### Phase 1: Project Setup
- [ ] **P1.1** Create new repo `nexus-mcp-server`
- [ ] **P1.2** Set up pyproject.toml with dependencies
- [ ] **P1.3** Create base Skill protocol and ToolResult

### Phase 2: Core Server
- [ ] **P2.1** Implement MCPServer class
- [ ] **P2.2** Handle initialize, tools/list, tools/call
- [ ] **P2.3** Error handling for unknown methods/tools

### Phase 3: Transports
- [ ] **P3.1** Implement StdioServerTransport
- [ ] **P3.2** Implement HTTPServerTransport
- [ ] **P3.3** CLI argument parsing for transport selection

### Phase 4: Skills
- [ ] **P4.1** Port read_file, tail, file_info, list_directory
- [ ] **P4.2** Port glob, grep
- [ ] **P4.3** Port write_file, edit_file (gated by config)
- [ ] **P4.4** Port git (read-only commands only)

### Phase 5: Configuration
- [ ] **P5.1** Config file loading
- [ ] **P5.2** Category-based skill enabling
- [ ] **P5.3** Path restrictions

### Phase 6: Testing
- [ ] **P6.1** Unit tests for server protocol
- [ ] **P6.2** Integration tests with stdio transport
- [ ] **P6.3** Test with Claude Desktop

### Phase 7: Documentation
- [ ] **P7.1** README with setup instructions
- [ ] **P7.2** Claude Desktop integration guide
- [ ] **P7.3** Skill reference documentation

---

## Effort Estimate

| Phase | Effort |
|-------|--------|
| Project setup | 1 day |
| Core server | 2 days |
| Transports | 1 day |
| Skills (10 skills) | 3 days |
| Configuration | 1 day |
| Testing | 2 days |
| Documentation | 1 day |
| **Total** | **~2 weeks** |

---

## Future Extensions (v2+)

1. **MCP Resources** - Expose file system as resources
2. **MCP Prompts** - Skill usage templates
3. **Streaming** - Stream long tool outputs
4. **Session state** - For clipboard-like operations
5. **Plugin system** - Load custom skills from config
