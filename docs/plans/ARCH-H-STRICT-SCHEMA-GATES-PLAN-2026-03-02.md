# Plan H: Strict Schema Gates at Boundaries (2026-03-02)

## Overview

Enforce strict typed validation at config, MCP, and JSON-RPC ingress boundaries before business logic executes.

## Scope

Included:
- Typed RPC method parameter models.
- Strict `mcp.json` envelope validation (no silent malformed container skips).
- Protocol ID and error-object shape hardening.
- Unify duplicated MCP server config model usage.

Deferred:
- Permanent removal of compatibility mode until migration completes.

Excluded:
- New schema framework adoption.

## Design Decisions and Rationale

1. Parse and validate once at ingress, then operate on typed objects.
2. Reject malformed boundary payloads with explicit actionable diagnostics.
3. Use a compatibility phase with warnings for RPC method params only; existing strict MCP entry validation remains fail-fast.

## Implementation Details

Primary files to change:
- [config/schema.py](/home/inc/repos/NEXUS3/nexus3/config/schema.py)
- [config/loader.py](/home/inc/repos/NEXUS3/nexus3/config/loader.py)
- [context/loader.py](/home/inc/repos/NEXUS3/nexus3/context/loader.py)
- [mcp/registry.py](/home/inc/repos/NEXUS3/nexus3/mcp/registry.py)
- [rpc/protocol.py](/home/inc/repos/NEXUS3/nexus3/rpc/protocol.py)
- [rpc/dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/dispatcher.py)
- [rpc/global_dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/global_dispatcher.py)
- New: `nexus3/rpc/schemas.py`

Phases:
1. Add typed RPC schemas and `mcp.json` envelope schema without behavior flip.
2. Route dispatch/load paths through schema validators with compatibility warnings (RPC params only; do not relax strict MCP validation).
3. Consolidate MCP config model definitions to one source of truth.
4. Enforce strict mode by default where typed schemas and compatibility telemetry are established; remove silent fallthrough.

## Testing Strategy

- Add boundary-negative tests for malformed RPC and malformed `mcp.json` payloads.
- Add explicit bool-ID rejection and error-object shape tests.
- Add compatibility-mode tests and strict-mode tests.

## Implementation Checklist

- [x] Define RPC param schema models.
- [x] Define strict `mcp.json` envelope model.
- [ ] Wire schema validation into ingress paths.
  - [x] M1 Phase 2 slice: wired typed validation in `rpc/global_dispatcher.py::_handle_destroy_agent` and `rpc/dispatcher.py::_handle_get_messages` with compatibility-style `InvalidParamsError` mapping.
  - [x] M1 Phase 2 slice: wired typed validation in `rpc/dispatcher.py::_handle_cancel` and `rpc/dispatcher.py::_handle_compact` with compat-safe (`strict=False`) `InvalidParamsError` mapping.
  - [x] M1 Phase 2 slice: wired compat-safe typed ingress hooks for remaining low-risk no-arg methods in `rpc/dispatcher.py` (`shutdown`, `get_tokens`, `get_context`) and `rpc/global_dispatcher.py` (`list_agents`, `shutdown_server`) while preserving permissive extras behavior.
  - [x] M1 Phase 2 behavior-sensitive slice: wired compat-safe typed ingress validation in `rpc/dispatcher.py::_handle_send` and `rpc/global_dispatcher.py::_handle_create_agent` with legacy-style `InvalidParamsError` mapping and focused wiring tests.
  - [x] M1 Phase 2 behavior-sensitive extension: validated `parent_agent_id` and conditional `wait_for_initial_response` in `rpc/global_dispatcher.py::_handle_create_agent` with preserved legacy `InvalidParamsError` wording and focused ingress wiring tests.
  - [x] M1 Phase 2 behavior-sensitive extension: expanded `rpc/dispatcher.py::_handle_send` compat-safe ingress validation to include optional `request_id`/`source`/`source_agent_id` with legacy-style `InvalidParamsError` mappings and focused malformed-parameter regressions.
  - [x] M1 Phase 2 protocol boundary hardening: `rpc/protocol.py` now rejects boolean JSON-RPC `id` values in both request/response parsing with focused tests.
  - [x] M1 Phase 2 protocol response-envelope ingress hardening: `rpc/protocol.py::parse_response` now validates via `RpcResponseEnvelopeSchema` with preserved legacy ParseError wording for malformed `error` object shapes and existing envelope invariants.
  - [x] M1 Phase 2 handler cleanup slice: removed ad hoc `cancel` request_id precheck in `rpc/dispatcher.py` and rely on `CancelParamsSchema` ingress validation with preserved legacy compat errors; removed duplicate post-create wait-flag parsing in `rpc/global_dispatcher.py` and reused already schema-validated field.
  - [x] M1 Phase 2 projection cleanup slice: introduced shared schema-field projection helper (`project_known_schema_fields`) and used it in `rpc/dispatcher.py::_handle_send` and `rpc/global_dispatcher.py::_handle_create_agent` to reduce ad hoc field-selection branches while preserving compat-safe behavior and legacy error wording.
  - [x] M1 Phase 2 create-agent cleanup slice: removed redundant post-schema `allowed_write_paths` type guards in `rpc/global_dispatcher.py` and preserved malformed-shape wording via schema error mapping; kept path/security containment checks unchanged.
  - [ ] Remaining M1 Phase 2 ingress coverage beyond low-risk methods (including stricter/behavior-sensitive paths) still pending.
    - Resume target: prioritize remaining residual handler guards and strict mode tightening where compat telemetry is already stable.
- [x] Remove silent malformed-entry skips.
  - [x] M1 Phase 3 slice: `context/loader.py::_merge_mcp_servers` now fail-fast rejects malformed MCP container/entry shapes (`mcpServers` non-object, `servers` non-array, non-object entries in `servers[]`) with actionable `MCPConfigError` context.
- [x] Consolidate duplicate MCP config models.
  - [x] M1 Phase 3 slice: unified `MCPServerConfig` to `config.schema` as source of truth, removed duplicate dataclass in `mcp/registry.py`, and retained compatibility import path via registry re-export.

## Documentation Updates

- Update config/RPC/MCP docs with strict boundary behavior and compatibility-window notes.
- Update CLI/RPC error-message examples for new validation outputs.

## Related Documents

- [Reviews Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/reviews/README.md)
- [Plans Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/plans/README.md)
- [Canonical Review Master Final](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
- [Architecture Investigation](/home/inc/repos/NEXUS3/docs/plans/ARCH-INVESTIGATION-2026-03-02.md)
- [Architecture Milestone Schedule](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
