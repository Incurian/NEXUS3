# NEXUS3 Review (Merged Round 1 + Round 2)

Date: 2026-03-02
Sources:
- Round 1: `/docs/reviews/CODEX-NEXUS3-REVIEW-2026-03-02.md`
- Round 2: six independent subagent passes (exploitability, validation, test-gap mapping, platform/security)

This merged report deduplicates findings and adds status labels:
- `CONFIRMED`: independently supported by multiple passes and/or local repro by reviewers
- `PROBABLE`: code path strongly indicates bug; exploitability depends on deployment context
- `RECLASSIFIED`: prior claim adjusted (design tradeoff or false-positive-as-escalation)

## Executive Summary

- Critical: 1 (`CONFIRMED`)
- High: 13 (`CONFIRMED` or `PROBABLE`)
- Medium: 14
- Low: 1
- Reclassified/false-positive-as-escalation items: 2

## Critical Findings

1. `CONFIRMED` Sandbox escape via symlink traversal in `outline` directory mode.
- Files:
  - [outline.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/outline.py:1448)
  - [outline.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/outline.py:1538)
  - [outline.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/outline.py:1547)
  - [outline.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/outline.py:1580)
- Why: directory path is validated once; per-entry reads can follow symlinks outside sandbox/blocked areas.

## High Findings

1. `CONFIRMED` Cross-request requester race in global dispatcher shared state.
- File: [global_dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/global_dispatcher.py:108)

2. `PROBABLE` `create_agent.parent_agent_id` trust not bound to requester identity.
- Files:
  - [global_dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/global_dispatcher.py:92)
  - [global_dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/global_dispatcher.py:217)
  - [global_dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/global_dispatcher.py:401)

3. `CONFIRMED` REPL `/agent <saved_session>` restore is lossy vs full saved state.
- File: [repl.py](/home/inc/repos/NEXUS3/nexus3/cli/repl.py:1399)

4. `CONFIRMED` `/cancel` command behavior mismatched for specific request-id cancellation.
- File: [core.py](/home/inc/repos/NEXUS3/nexus3/commands/core.py:495)

5. `CONFIRMED` Context truncation can return over-budget context.
- File: [manager.py](/home/inc/repos/NEXUS3/nexus3/context/manager.py:751)

6. `CONFIRMED` Compaction can preserve orphan `tool` message without originating assistant tool-call.
- File: [compaction.py](/home/inc/repos/NEXUS3/nexus3/context/compaction.py:154)

7. `CONFIRMED` `blocked_paths` bypass in multi-file scanners (`grep`, `concat_files`, `outline`) and listing leakage in `glob`.
- Files:
  - [grep.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/grep.py:540)
  - [concat_files.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/concat_files.py:553)
  - [outline.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/outline.py:1538)
  - [glob_search.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/glob_search.py:97)

8. `CONFIRMED` Patch applier strips trailing spaces in tolerant/fuzzy modes (data corruption).
- File: [applier.py](/home/inc/repos/NEXUS3/nexus3/patch/applier.py:247)

9. `CONFIRMED` Patch newline marker semantics dropped end-to-end.
- Files:
  - [parser.py](/home/inc/repos/NEXUS3/nexus3/patch/parser.py:217)
  - [applier.py](/home/inc/repos/NEXUS3/nexus3/patch/applier.py:343)

10. `CONFIRMED` Clipboard create/tag operations are non-atomic and can persist partial state on failure.
- Files:
  - [storage.py](/home/inc/repos/NEXUS3/nexus3/clipboard/storage.py:179)
  - [storage.py](/home/inc/repos/NEXUS3/nexus3/clipboard/storage.py:302)

11. `CONFIRMED` Clipboard manager mutates in-memory tags before persistent write (divergence on failure).
- Files:
  - [manager.py](/home/inc/repos/NEXUS3/nexus3/clipboard/manager.py:521)
  - [manager.py](/home/inc/repos/NEXUS3/nexus3/clipboard/manager.py:533)

12. `CONFIRMED` MCP command resolution may use wrong PATH context (host vs effective child env).
- File: [transport.py](/home/inc/repos/NEXUS3/nexus3/mcp/transport.py:164)

13. `CONFIRMED` Terminal escape injection risk via MCP error propagation to streaming display.
- Files:
  - [client.py](/home/inc/repos/NEXUS3/nexus3/mcp/client.py:278)
  - [streaming.py](/home/inc/repos/NEXUS3/nexus3/display/streaming.py:180)

## Medium Findings

1. Subagent context stripping can truncate user instructions when `# Environment` appears earlier.
- File: [loader.py](/home/inc/repos/NEXUS3/nexus3/context/loader.py:669)

2. `oldest_first` truncation can still return oversized group for tiny budgets.
- File: [manager.py](/home/inc/repos/NEXUS3/nexus3/context/manager.py:701)

3. Provider cache key omits `reasoning` mode (mode aliasing bug).
- File: [registry.py](/home/inc/repos/NEXUS3/nexus3/provider/registry.py:98)

4. Token accounting drift vs actual payload shape for dynamic context injection.
- Files:
  - [manager.py](/home/inc/repos/NEXUS3/nexus3/context/manager.py:573)
  - [openai_compat.py](/home/inc/repos/NEXUS3/nexus3/provider/openai_compat.py:170)
  - [anthropic.py](/home/inc/repos/NEXUS3/nexus3/provider/anthropic.py:201)

5. Mid-stream read interruptions are not retried (resilience gap).
- Files:
  - [base.py](/home/inc/repos/NEXUS3/nexus3/provider/base.py:610)
  - [openai_compat.py](/home/inc/repos/NEXUS3/nexus3/provider/openai_compat.py:330)

6. Fire-and-forget initial-message race against immediate destroy.
- File: [global_dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/global_dispatcher.py:453)

7. Slash command help-token parsing can misroute normal payloads containing `--help`.
- File: [repl.py](/home/inc/repos/NEXUS3/nexus3/cli/repl.py:1106)

8. Whisper-mode autosave can persist wrong agent state.
- File: [repl.py](/home/inc/repos/NEXUS3/nexus3/cli/repl.py:1509)

9. Corrupt `last-session.json` handling path may surface uncaught session error.
- File: [session_manager.py](/home/inc/repos/NEXUS3/nexus3/session/session_manager.py:252)

10. Active-agent clone/rename can drop runtime state beyond message history.
- File: [core.py](/home/inc/repos/NEXUS3/nexus3/commands/core.py:652)

11. Tool-name canonicalization mismatch (`shell_UNSAFE` vs `shell_unsafe`) can break disable intent.
- Files:
  - [bash.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/bash.py:214)
  - [permissions.py](/home/inc/repos/NEXUS3/nexus3/core/permissions.py:245)

12. Windows error sanitization misses generic drive-path redaction.
- File: [errors.py](/home/inc/repos/NEXUS3/nexus3/core/errors.py:73)

13. Windows secure-open fallback has TOCTOU race without `O_NOFOLLOW`.
- Files:
  - [session_manager.py](/home/inc/repos/NEXUS3/nexus3/session/session_manager.py:44)
  - [secure_io.py](/home/inc/repos/NEXUS3/nexus3/core/secure_io.py:179)

14. Terminal sanitizer preserves `\r`, enabling line-rewrite spoofing in some render paths.
- File: [text_safety.py](/home/inc/repos/NEXUS3/nexus3/core/text_safety.py:32)

## Low Findings

1. JSON-RPC parser accepts boolean IDs (`bool` is `int` subclass in Python).
- File: [protocol.py](/home/inc/repos/NEXUS3/nexus3/rpc/protocol.py:66)

## Reclassifications From Round 2

1. `RECLASSIFIED` `X-Nexus-Agent` spoofing as privilege escalation.
- Status: identity-integrity weakness remains, but escalation impact depends on current design where external caller context may already be privileged in destroy path.
- Files:
  - [http.py](/home/inc/repos/NEXUS3/nexus3/rpc/http.py:570)
  - [pool.py](/home/inc/repos/NEXUS3/nexus3/rpc/pool.py:1080)

2. `RECLASSIFIED` Missing requester propagation in destroy path.
- Status: appears addressed in current code/tests; not confirmed exploitable as previously framed.
- Files:
  - [pool.py](/home/inc/repos/NEXUS3/nexus3/rpc/pool.py:619)
  - [agent_api.py](/home/inc/repos/NEXUS3/nexus3/rpc/agent_api.py:311)
  - [test_destroy_authorization.py](/home/inc/repos/NEXUS3/tests/security/test_destroy_authorization.py:1)

## Test Coverage Additions Recommended

Primary suggested files from Round 2 mapping pass:
- [test_h1_global_dispatcher_requester_race.py](/home/inc/repos/NEXUS3/tests/security/test_h1_global_dispatcher_requester_race.py)
- [test_h2_http_requester_header_spoofing.py](/home/inc/repos/NEXUS3/tests/security/test_h2_http_requester_header_spoofing.py)
- [test_h3_parent_agent_authorization_binding.py](/home/inc/repos/NEXUS3/tests/security/test_h3_parent_agent_authorization_binding.py)
- [test_agent_restore_parity.py](/home/inc/repos/NEXUS3/tests/unit/cli/test_agent_restore_parity.py)
- [test_cancel_targeted_request.py](/home/inc/repos/NEXUS3/tests/unit/commands/test_cancel_targeted_request.py)
- [test_registry_reasoning_cache_key.py](/home/inc/repos/NEXUS3/tests/unit/provider/test_registry_reasoning_cache_key.py)
- [test_subagent_environment_strip_safety.py](/home/inc/repos/NEXUS3/tests/unit/context/test_subagent_environment_strip_safety.py)
- [test_middle_out_budget_invariant.py](/home/inc/repos/NEXUS3/tests/unit/context/test_middle_out_budget_invariant.py)
- [test_blocked_paths_multifile_tools.py](/home/inc/repos/NEXUS3/tests/security/test_blocked_paths_multifile_tools.py)
- [test_applier_trailing_space_fidelity.py](/home/inc/repos/NEXUS3/tests/unit/patch/test_applier_trailing_space_fidelity.py)
- [test_newline_marker_end_to_end.py](/home/inc/repos/NEXUS3/tests/unit/patch/test_newline_marker_end_to_end.py)
- [test_stdio_path_resolution_env.py](/home/inc/repos/NEXUS3/tests/unit/mcp/test_stdio_path_resolution_env.py)
- [test_windows_taskkill_absolute_path.py](/home/inc/repos/NEXUS3/tests/security/test_windows_taskkill_absolute_path.py)

## Priority Order for Fixes

1. Close sandbox/permission boundary breaks (`outline` symlink escape, blocked-path bypass family).
2. Fix RPC requester binding/auth races (`dispatch` shared state and parent-binding model).
3. Repair data integrity bugs (patch whitespace/newline fidelity, clipboard atomicity/divergence).
4. Harden terminal and platform security surfaces (MCP/display escape handling, Windows command/path sanitization).
5. Enforce context truncation invariants and provider cache correctness.

## Related Documents

- [Reviews Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/reviews/README.md)
- [Plans Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/plans/README.md)
- [Canonical Review Master Final](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
- [Architecture Investigation](/home/inc/repos/NEXUS3/docs/plans/ARCH-INVESTIGATION-2026-03-02.md)
- [Architecture Milestone Schedule](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
