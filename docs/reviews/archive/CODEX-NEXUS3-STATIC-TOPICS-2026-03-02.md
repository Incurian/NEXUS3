# NEXUS3 Static-Only Topic Reviews (Codex)

Date: 2026-03-02
Scope constraint: only reviews feasible in current environment without live soak testing or alternate OS/runtime.

## Completed Topics

1. Threat-model by trust boundary
2. Concurrency/race audit
3. Parser/protocol fuzzing-surface audit (static)
4. Filesystem adversarial static review
5. Auth/session hardening static review
6. Context invariant/property review
7. Privilege-delta matrix review
8. Terminal/output safety review

## Key Findings (Consolidated)

### Critical

1. Private MCP visibility boundary bypass at execution-time lookup (agent-to-agent boundary).
- Files:
  - [session/dispatcher.py](/home/inc/repos/NEXUS3/nexus3/session/dispatcher.py:50)
  - [mcp/registry.py](/home/inc/repos/NEXUS3/nexus3/mcp/registry.py:349)
- Issue: caller identity is not enforced in execution-time MCP skill lookup, risking access to non-visible MCP servers/tools.

2. SANDBOXED hard-deny tools can be re-enabled through per-tool `enabled=True` override path.
- Files:
  - [session/enforcer.py](/home/inc/repos/NEXUS3/nexus3/session/enforcer.py:123)
  - [core/policy.py](/home/inc/repos/NEXUS3/nexus3/core/policy.py:93)
- Issue: explicit per-tool enable short-circuits sandbox hard-deny set.

### High

1. Cross-request requester race in global dispatcher shared state.
- File: [rpc/global_dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/global_dispatcher.py:107)

2. Agent destroy lifecycle race: resources can close before in-flight work fully stops.
- Files:
  - [rpc/pool.py](/home/inc/repos/NEXUS3/nexus3/rpc/pool.py:1120)
  - [rpc/dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/dispatcher.py:432)

3. Concurrent `compact` can mutate context while active `send` turn appends messages.
- Files:
  - [rpc/dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/dispatcher.py:399)
  - [context/manager.py](/home/inc/repos/NEXUS3/nexus3/context/manager.py:520)

4. Session restore trust of persisted preset can bypass create-time RPC constraints.
- Files:
  - [rpc/pool.py](/home/inc/repos/NEXUS3/nexus3/rpc/pool.py:866)
  - [session/persistence.py](/home/inc/repos/NEXUS3/nexus3/session/persistence.py:107)

5. `outline` directory mode can read symlinked files outside sandbox.
- File: [skill/builtin/outline.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/outline.py:1547)

6. `concat_files` output write path can be redirected via dangling symlink.
- File: [skill/builtin/concat_files.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/concat_files.py:1042)

7. Multi-file scanner boundary bypass (`blocked_paths` omission) remains exploitable (`grep`, `concat_files`, `glob` leakage).
- Files:
  - [skill/builtin/grep.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/grep.py:540)
  - [skill/builtin/concat_files.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/concat_files.py:553)
  - [skill/builtin/glob_search.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/glob_search.py:97)

8. Context compaction/tool-call pairing invariant break (orphan tool messages).
- File: [context/compaction.py](/home/inc/repos/NEXUS3/nexus3/context/compaction.py:154)

9. Context truncation budget-fit invariant break.
- File: [context/manager.py](/home/inc/repos/NEXUS3/nexus3/context/manager.py:701)

10. MCP and REPL error-output paths allow untrusted formatting/control payloads into terminal UI.
- Files:
  - [cli/repl_commands.py](/home/inc/repos/NEXUS3/nexus3/cli/repl_commands.py:1968)
  - [mcp/error_formatter.py](/home/inc/repos/NEXUS3/nexus3/mcp/error_formatter.py:130)
  - [display/streaming.py](/home/inc/repos/NEXUS3/nexus3/display/streaming.py:180)

11. Privilege policy deltas with deny-all semantics not honored:
- Files:
  - [core/presets.py](/home/inc/repos/NEXUS3/nexus3/core/presets.py:225) (`allowed_paths=[]` collapse)
  - [core/permissions.py](/home/inc/repos/NEXUS3/nexus3/core/permissions.py:352) (sandboxed empty list fallback)

12. `ToolPermission.requires_confirmation` declared but not enforced.
- Files:
  - [core/presets.py](/home/inc/repos/NEXUS3/nexus3/core/presets.py:47)
  - [session/enforcer.py](/home/inc/repos/NEXUS3/nexus3/session/enforcer.py:320)

13. Non-dict MCP config entries can crash loader with uncaught `AttributeError`.
- File: [context/loader.py](/home/inc/repos/NEXUS3/nexus3/context/loader.py:494)

### Medium / Low Highlights

1. JSON-RPC parser accepts bool IDs and weak error-object schema typing.
- File: [rpc/protocol.py](/home/inc/repos/NEXUS3/nexus3/rpc/protocol.py:66)

2. Non-finite float handling remains permissive (`NaN`, `Infinity`).
- File: [rpc/protocol.py](/home/inc/repos/NEXUS3/nexus3/rpc/protocol.py:37)

3. Instruction file decode errors are not normalized.
- File: [context/loader.py](/home/inc/repos/NEXUS3/nexus3/context/loader.py:232)

4. Duplicate request-id cancellation behavior can mis-target active request token.
- File: [rpc/dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/dispatcher.py:172)

5. `\r` preservation enables line-rewrite spoofing in some output paths.
- File: [core/text_safety.py](/home/inc/repos/NEXUS3/nexus3/core/text_safety.py:42)

6. Patch parser/applier malformed-input ambiguities remain (silent drop/over-span risk paths).
- Files:
  - [patch/parser.py](/home/inc/repos/NEXUS3/nexus3/patch/parser.py:221)
  - [patch/applier.py](/home/inc/repos/NEXUS3/nexus3/patch/applier.py:253)

## Recommended Follow-Up (Still Static-Feasible)

1. Add matrix/property tests for:
- sandboxed hard-deny invariants
- allowed_paths empty-list semantics
- tool-call/result pairing under compaction
- strict budget-fit guarantees in `build_messages`
- malformed `mcp.json` and instruction decode failures

2. Add concurrency tests for requester isolation and compact/send races.

## Deferred Topics (Require Live Testing or Other Environments)

These were intentionally deferred and should be run later:

1. Long-duration performance/stability soak tests (real workloads, repeated create/send/destroy, compaction churn).
2. Windows-native runtime validation on actual Windows host (junction/reparse behavior, `taskkill` resolution, console behavior).
3. End-to-end exploit validation requiring realistic multi-process timing and environment manipulation (TOCTOU and lifecycle races under load).
4. Full terminal red-team validation against real terminals/shells (OSC/CSI behavior differs across emulators).


## Related Documents

- [Reviews Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/reviews/README.md)
- [Plans Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/plans/README.md)
- [Canonical Review Master Final](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
- [Architecture Investigation](/home/inc/repos/NEXUS3/docs/plans/ARCH-INVESTIGATION-2026-03-02.md)
- [Architecture Milestone Schedule](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
