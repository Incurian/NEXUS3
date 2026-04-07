# nexus3

Top-level Python package for the NEXUS3 agent framework.

## Overview

The package root intentionally stays small. Most implementation lives in
module-focused subpackages with their own READMEs, while the root provides the
main package entry points and a small programmatic client surface.

## Package Root Files

| File | Purpose |
|------|---------|
| [`__init__.py`](/home/inc/repos/NEXUS3/nexus3/__init__.py) | Package metadata; currently exports `__version__` |
| [`__main__.py`](/home/inc/repos/NEXUS3/nexus3/__main__.py) | `python -m nexus3` entry point wired to the CLI REPL launcher |
| [`client.py`](/home/inc/repos/NEXUS3/nexus3/client.py) | Async `NexusClient` for JSON-RPC communication with NEXUS3 servers |
| [`py.typed`](/home/inc/repos/NEXUS3/nexus3/py.typed) | PEP 561 marker indicating the package ships typing information |

## Subpackages

- `cli/` - Unified REPL, connect/lobby flows, serve mode, and slash-command surfaces
- `clipboard/` - Scoped clipboard storage, search, import/export, and persistence
- `commands/` - Shared command protocol and command implementations
- `config/` - Config schema, merge rules, and loader logic
- `context/` - Context loading, token counting, prompt building, and compaction
- `core/` - Shared types, validation, permissions, paths, SSRF protection, and low-level helpers
- `defaults/` - Default prompts, default config, and init-time templates
- `display/` - Spinner-based REPL display, inline printing, and SafeSink boundaries
- `mcp/` - Model Context Protocol client/runtime integration
- `patch/` - Unified diff parsing, validation, and application
- `provider/` - Provider abstraction, retry logic, prompt caching, and stream handling
- `rpc/` - HTTP JSON-RPC protocol, dispatch, discovery, auth, and agent pool plumbing
- `session/` - Session coordination, tool execution, persistence, and logging
- `skill/` - Skill protocol, built-in tools, VCS integrations, registration, and service wiring

## Deferred Area

- `ide/` remains intentionally deferred and does not yet have a module README

## Related Docs

- Repo overview and user-facing usage:
  [`README.md`](/home/inc/repos/NEXUS3/README.md)
- Interactive command surface:
  [`nexus3/cli/README.md`](/home/inc/repos/NEXUS3/nexus3/cli/README.md)
- Programmatic RPC surface:
  [`nexus3/rpc/README.md`](/home/inc/repos/NEXUS3/nexus3/rpc/README.md)
- Skill and tool system:
  [`nexus3/skill/README.md`](/home/inc/repos/NEXUS3/nexus3/skill/README.md)
