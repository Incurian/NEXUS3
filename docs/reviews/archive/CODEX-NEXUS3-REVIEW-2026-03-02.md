# NEXUS3 Multi-Agent Review (Codex)

Date: 2026-03-02
Reviewer mode: Parallel Codex subagents (`explorer`) with consolidated triage.
Scope: `nexus3/` major subsystems (`rpc`, `cli/session`, `skill/permissions`, `provider/context`, `patch/clipboard/display`, `windows/security`).

## Summary

- High: 13
- Medium: 14
- Low: 1
- Total findings: 28

Note: This is a static review pass. Findings include suggested test gaps from subagents.

## High Severity Findings

1. Cross-request requester identity race in global dispatcher state.
- File: [nexus3/rpc/global_dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/global_dispatcher.py:108)
- Detail: `requester_id` stored on shared instance (`_current_requester_id`) across awaited handler execution.
- Impact: concurrent requests can overwrite requester identity before auth checks.
- Test gap: concurrency test with parallel `dispatch()` calls and different requesters.

2. Requester spoofing via `X-Nexus-Agent` header.
- File: [nexus3/rpc/http.py](/home/inc/repos/NEXUS3/nexus3/rpc/http.py:570)
- Detail: header value is trusted for authorization context.
- Impact: authenticated client can impersonate agent for global auth decisions.
- Test gap: integration test rejecting spoofed parent header on destroy.

3. `parent_agent_id` trust without caller validation.
- File: [nexus3/rpc/global_dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/global_dispatcher.py:217)
- Detail: caller-supplied parent influences inherited permissions/cwd.
- Impact: parent impersonation in subagent creation path.
- Test gap: ensure agent A cannot create with `parent_agent_id=B` unless authorized.

4. REPL `/agent <saved_session>` restore is lossy.
- File: [nexus3/cli/repl.py](/home/inc/repos/NEXUS3/nexus3/cli/repl.py:1399)
- Detail: fresh agent created and only message history appended.
- Impact: saved prompt/cwd/model/permissions/clipboard state not restored.
- Test gap: restore parity test for full `SavedSession` state.

5. `/cancel` command discards specific request-id semantics.
- File: [nexus3/commands/core.py](/home/inc/repos/NEXUS3/nexus3/commands/core.py:495)
- Detail: forces `int(request_id)` then calls `cancel_all_requests()`.
- Impact: cannot reliably cancel specific in-flight request (hex IDs break).
- Test gap: `/cancel <agent> <hex_id>` should target only that request.

6. Provider cache key omits `reasoning` dimension.
- File: [nexus3/provider/registry.py](/home/inc/repos/NEXUS3/nexus3/provider/registry.py:98)
- Detail: cache key uses `provider_name:model_id` only.
- Impact: wrong provider instance reused across reasoning mode variants.
- Test gap: same model fetched with reasoning false/true should not alias incorrectly.

7. Subagent context truncation on first `# Environment` occurrence.
- File: [nexus3/context/loader.py](/home/inc/repos/NEXUS3/nexus3/context/loader.py:669)
- Detail: `find("# Environment")` used to strip parent environment section.
- Impact: user-authored section with same heading can cause instruction loss.
- Test gap: parent prompt containing earlier `# Environment` should preserve custom text.

8. `middle_out` truncation can still exceed budget.
- File: [nexus3/context/manager.py](/home/inc/repos/NEXUS3/nexus3/context/manager.py:753)
- Detail: returns first+last groups without enforcing combined budget fit.
- Impact: request can still exceed context limit after truncation.
- Test gap: scenario where first+last > budget must degrade to fit.

9. `blocked_paths` bypass in multi-file traversal/content tools.
- Files:
  - [nexus3/skill/builtin/glob_search.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/glob_search.py:97)
  - [nexus3/skill/builtin/grep.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/grep.py:424)
  - [nexus3/skill/builtin/grep.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/grep.py:540)
  - [nexus3/skill/builtin/concat_files.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/concat_files.py:553)
  - [nexus3/skill/builtin/concat_files.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/concat_files.py:606)
  - [nexus3/skill/builtin/outline.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/outline.py:1538)
- Detail: root path validated, descendants enumerated/read without per-candidate blocked-path enforcement.
- Impact: blocked descendants may still be listed/read/searched.
- Test gap: blocked-subdir denial tests for each multi-file tool.

10. Patch applier strips trailing spaces in tolerant/fuzzy modes.
- File: [nexus3/patch/applier.py](/home/inc/repos/NEXUS3/nexus3/patch/applier.py:247)
- Detail: added lines `rstrip()` before insertion.
- Impact: silent content corruption where trailing spaces are meaningful.
- Test gap: preserve trailing spaces test in tolerant/fuzzy modes.

11. Patch newline marker semantics lost across parse/apply.
- Files:
  - [nexus3/patch/parser.py](/home/inc/repos/NEXUS3/nexus3/patch/parser.py:217)
  - [nexus3/patch/applier.py](/home/inc/repos/NEXUS3/nexus3/patch/applier.py:343)
- Detail: `\ No newline at end of file` is not preserved end-to-end for apply behavior.
- Impact: cannot faithfully represent final newline add/remove transitions.
- Test gap: apply-time newline transition tests.

12. MCP command resolution ignores effective child PATH.
- File: [nexus3/mcp/transport.py](/home/inc/repos/NEXUS3/nexus3/mcp/transport.py:164)
- Detail: `shutil.which()` resolution uses parent env, launch uses sanitized/explicit child env.
- Impact: wrong executable selection, compatibility breakage, command confusion risk.
- Test gap: resolution tests with explicit child PATH overrides.

13. Windows `taskkill` invocation is path-hijackable.
- File: [nexus3/core/process.py](/home/inc/repos/NEXUS3/nexus3/core/process.py:125)
- Detail: runs bare `taskkill` instead of trusted absolute system path.
- Impact: executable planting/search-order hijack risk on Windows.
- Test gap: test/assert trusted absolute command resolution.

## Medium Severity Findings

1. Fire-and-forget `initial_message` lifecycle race after destroy.
- File: [nexus3/rpc/global_dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/global_dispatcher.py:453)
- Impact: background send may run after agent teardown.
- Test gap: create with initial message then immediate destroy.

2. Slash-command help detection misroutes payloads containing `--help`.
- File: [nexus3/cli/repl.py](/home/inc/repos/NEXUS3/nexus3/cli/repl.py:1106)
- Impact: valid `/send` messages can be treated as help invocations.
- Test gap: `/send agent "... --help ..."` should still send.

3. Whisper mode auto-save writes wrong agent session.
- File: [nexus3/cli/repl.py](/home/inc/repos/NEXUS3/nexus3/cli/repl.py:1509)
- Impact: data-loss/state drift for whisper target conversations.
- Test gap: ensure persisted session corresponds to agent whose context changed.

4. Corrupt `last-session.json` handling mismatch.
- File: [nexus3/session/session_manager.py](/home/inc/repos/NEXUS3/nexus3/session/session_manager.py:252)
- Impact: malformed session file may raise unexpectedly instead of graceful recovery.
- Test gap: corrupt JSON should produce controlled fallback path.

5. Active-agent `/clone` and `/rename` drop runtime state.
- File: [nexus3/commands/core.py](/home/inc/repos/NEXUS3/nexus3/commands/core.py:652)
- Impact: model/cwd/permissions/tool toggles/clipboard not preserved.
- Test gap: stateful clone/rename parity tests.

6. `oldest_first` truncation can return oversized last group when budget <= 0.
- File: [nexus3/context/manager.py](/home/inc/repos/NEXUS3/nexus3/context/manager.py:701)
- Impact: provider context overflow despite truncation path.
- Test gap: tiny-budget + huge-last-group scenario.

7. Token accounting undercounts serialized tool metadata.
- Files:
  - [nexus3/context/token_counter.py](/home/inc/repos/NEXUS3/nexus3/context/token_counter.py:59)
  - [nexus3/provider/openai_compat.py](/home/inc/repos/NEXUS3/nexus3/provider/openai_compat.py:194)
  - [nexus3/provider/anthropic.py](/home/inc/repos/NEXUS3/nexus3/provider/anthropic.py:305)
- Impact: delayed compaction/truncation due to underestimated token cost.
- Test gap: serialized-payload vs estimator parity tests.

8. Stream read failures are not retried mid-iteration.
- Files:
  - [nexus3/provider/base.py](/home/inc/repos/NEXUS3/nexus3/provider/base.py:610)
  - [nexus3/provider/openai_compat.py](/home/inc/repos/NEXUS3/nexus3/provider/openai_compat.py:330)
  - [nexus3/provider/anthropic.py](/home/inc/repos/NEXUS3/nexus3/provider/anthropic.py:448)
- Impact: transient network hiccup can terminate long streams despite retry settings.
- Test gap: chunked-stream timeout/disconnect recovery tests.

9. Relative preset paths resolve against process CWD.
- Files:
  - [nexus3/core/presets.py](/home/inc/repos/NEXUS3/nexus3/core/presets.py:213)
  - [nexus3/core/permissions.py](/home/inc/repos/NEXUS3/nexus3/core/permissions.py:359)
  - [nexus3/core/paths.py](/home/inc/repos/NEXUS3/nexus3/core/paths.py:123)
- Impact: policy drift in multi-agent/server contexts.
- Test gap: relative-path presets under varying process/agent cwd.

10. Tool-name canonicalization mismatch (`shell_UNSAFE` vs `shell_unsafe`).
- Files:
  - [nexus3/skill/builtin/bash.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/bash.py:214)
  - [nexus3/core/policy.py](/home/inc/repos/NEXUS3/nexus3/core/policy.py:95)
  - [nexus3/core/permissions.py](/home/inc/repos/NEXUS3/nexus3/core/permissions.py:252)
- Impact: disable/enable deltas may not affect intended unsafe-shell tool.
- Test gap: case/canonicalization enforcement tests.

11. Clipboard storage partial-success on duplicate tags.
- Files:
  - [nexus3/clipboard/storage.py](/home/inc/repos/NEXUS3/nexus3/clipboard/storage.py:179)
  - [nexus3/clipboard/storage.py](/home/inc/repos/NEXUS3/nexus3/clipboard/storage.py:319)
  - [nexus3/clipboard/manager.py](/home/inc/repos/NEXUS3/nexus3/clipboard/manager.py:138)
- Impact: entry persisted but operation can raise due to later unique-tag conflict.
- Test gap: duplicate-tag create/copy rollback consistency tests.

12. Clipboard context injection formatting is not escaped robustly.
- Files:
  - [nexus3/clipboard/injection.py](/home/inc/repos/NEXUS3/nexus3/clipboard/injection.py:63)
  - [nexus3/clipboard/injection.py](/home/inc/repos/NEXUS3/nexus3/clipboard/injection.py:165)
- Impact: `|`/newline/control chars can corrupt table/prompt formatting.
- Test gap: delimiter/control-character escaping tests.

13. Streaming display tool-error text not fully terminal-sanitized.
- Files:
  - [nexus3/display/streaming.py](/home/inc/repos/NEXUS3/nexus3/display/streaming.py:180)
  - [nexus3/display/streaming.py](/home/inc/repos/NEXUS3/nexus3/display/streaming.py:392)
- Impact: terminal control sequence injection risk in live rendering/logs.
- Test gap: StreamingDisplay escape sanitization tests.

14. Windows secure-open fallback has TOCTOU gap without `O_NOFOLLOW`.
- Files:
  - [nexus3/session/session_manager.py](/home/inc/repos/NEXUS3/nexus3/session/session_manager.py:44)
  - [nexus3/core/secure_io.py](/home/inc/repos/NEXUS3/nexus3/core/secure_io.py:179)
- Impact: race-replace with symlink/junction between check and open may bypass protection.
- Test gap: Windows race-window tests for fallback path.

## Low Severity Findings

1. JSON-RPC parser accepts boolean IDs (`true`/`false`).
- File: [nexus3/rpc/protocol.py](/home/inc/repos/NEXUS3/nexus3/rpc/protocol.py:66)
- Detail: `bool` is subclass of `int`; current type check accepts bool IDs.
- Impact: spec compliance gap and edge-case request correlation behavior.
- Test gap: parser rejection tests for bool IDs.

## Suggested Next Pass (Prioritized)

1. Fix auth/requester trust chain in RPC (`X-Nexus-Agent`, shared state race, parent spoofing).
2. Fix permission boundary bypass in multi-file skills (`blocked_paths` enforcement per candidate).
3. Fix truncation invariants to guarantee budget fit (`middle_out`, `oldest_first`).
4. Fix patch fidelity issues (trailing spaces, newline marker semantics).
5. Add targeted regression tests listed above before broader refactors.

## Related Documents

- [Reviews Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/reviews/README.md)
- [Plans Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/plans/README.md)
- [Canonical Review Master Final](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
- [Architecture Investigation](/home/inc/repos/NEXUS3/docs/plans/ARCH-INVESTIGATION-2026-03-02.md)
- [Architecture Milestone Schedule](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
