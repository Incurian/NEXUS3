# nexus3

Top-level package for the NEXUS3 agent framework.

## Overview

The package root intentionally stays small. It exposes package metadata in
[`__init__.py`](/home/inc/repos/NEXUS3/nexus3/__init__.py), while the actual
implementation is organized into module-focused subpackages with their own
readmes.

Primary subpackages:

- `cli/` - Unified REPL, client mode, serve mode, and slash-command surfaces
- `clipboard/` - Scoped clipboard storage and persistence
- `commands/` - Shared command protocol and implementations
- `config/` - Config schema, merging, and loader logic
- `context/` - Context loading, token counting, and compaction
- `core/` - Shared types, validation, permissions, paths, and low-level helpers
- `defaults/` - Default prompts and configuration guidance
- `display/` - Spinner-based REPL display and SafeSink boundaries
- `mcp/` - Model Context Protocol client integration
- `patch/` - Unified diff parsing and application
- `provider/` - Provider abstraction and retry/stream handling
- `rpc/` - HTTP JSON-RPC server/client/auth/discovery
- `session/` - Session coordination, persistence, and logging
- `skill/` - Built-in skills, VCS skills, registration, and service wiring

Deferred area:

- `ide/` remains intentionally deferred and does not yet have a module README

For project-level architecture and usage, see the repo root
[`README.md`](/home/inc/repos/NEXUS3/README.md).
