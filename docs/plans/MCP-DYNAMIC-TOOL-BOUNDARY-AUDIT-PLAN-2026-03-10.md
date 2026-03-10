# MCP Dynamic Tool Boundary Audit Plan (2026-03-10)

## Overview

The next high-value non-file tool-family audit is the MCP dynamic tool boundary.
This surface is externally shaped, provider-sensitive, and already produced real
OpenAI-compatible schema failures during recent live usage. Unlike the built-in
tool families, MCP-backed tools can introduce arbitrary third-party schemas and
tool metadata at runtime, so this boundary deserves its own focused hardening
pass.

## Scope

### Included

- Audit MCP-backed dynamic tool schema adaptation before provider calls.
- Audit MCP skill registration/refresh visibility and permission shaping.
- Audit user-consent / permission boundary behavior for external MCP tools.
- Audit reconnect / refresh / re-registration paths for stale tool metadata.
- Add focused regressions for any concrete contract or safety gaps found.

### Deferred

- Full MCP resources/prompts audit beyond the dynamic tool surface.
- Provider-wide schema redesign across all providers in the same slice.
- Large UX redesign of MCP consent flows without a concrete defect.

### Excluded

- Built-in file-edit family work already covered by the March 10 file-tool plans.
- GitLab skill audits already completed in the broad-audit plan.
- Server-start/bootstrap UX for the future “NEXUS3 as an MCP server” workstream.

## Design Decisions And Rationale

### 1. Treat runtime-advertised schemas as hostile until normalized

MCP tools are not static built-ins. They arrive from external servers and can
contain incomplete or provider-incompatible JSON Schema fragments, so outbound
provider shaping must be reviewed as a security and reliability boundary.

### 2. Audit the full registration pipeline, not just the provider adapter

Recent fixes normalized provider-facing schemas, but that only covers one leg of
the path. The registry, adapter, and permission/consent layers still decide
which tools become visible and how their contracts are exposed to agents.

### 3. Prefer bounded hardening with concrete regressions

The goal is not a speculative redesign. The audit should produce specific
findings tied to code paths and tests, then land only the bounded fixes that
materially reduce real MCP tool boundary risk.

## Implementation Details

### Target modules

- `nexus3/mcp/skill_adapter.py`
- `nexus3/mcp/registry.py`
- `nexus3/mcp/client.py`
- `nexus3/mcp/permissions.py`
- `nexus3/mcp/protocol.py`
- `nexus3/provider/openai_compat.py`
- `nexus3/provider/anthropic.py`

### Likely validation targets

- `tests/unit/mcp/test_skill_adapter.py`
- `tests/unit/mcp/test_registry.py`
- `tests/unit/mcp/test_client_encapsulation.py`
- `tests/unit/mcp/test_protocol.py`
- `tests/security/test_mcp_security.py`
- `tests/security/test_p2_17_mcp_validation.py`
- provider-facing regressions in `tests/unit/provider/test_compiler_integration.py`

### Audit checklist

- [ ] Review MCP dynamic tool schema translation and normalization boundaries.
- [ ] Review consent/permission shaping for externally registered tools.
- [ ] Review reconnect/refresh behavior for stale or mutated MCP tool schemas.
- [ ] Record concrete findings with severity and affected files.
- [ ] Land bounded fixes for confirmed issues.
- [ ] Add focused automated regressions for every shipped fix.

## Testing Strategy

- Start with focused unit/security coverage on the MCP registry, adapter, and
  provider-facing schema paths.
- Reuse existing real failure shapes from recent OpenAI-compatible provider
  rejections where possible.
- Only add integration coverage when a unit/security test cannot capture the
  boundary correctly.

## Documentation Updates

- Update `AGENTS.md` running status with the selected next audit scope.
- Update `docs/plans/README.md` to index this plan.
- Update `CLAUDE.md` only if the audit lands user-visible behavior changes.
