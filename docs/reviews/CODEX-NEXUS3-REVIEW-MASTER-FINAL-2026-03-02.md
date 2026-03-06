# NEXUS3 Review Master Final (Expanded)

Date: 2026-03-02  
Status: canonical master review document (supersedes prior same-day review docs).

## Purpose

This is the single source of truth for the March 2, 2026 review cycle. It is intentionally written as an implementation-oriented remediation guide, not just a defect list.

Use this document to:
- understand each issue without reading all prior reports,
- estimate risk and blast radius,
- implement fixes with minimal additional discovery,
- add tests that prevent regressions.

## Source Inputs Used

1. [CODEX-NEXUS3-REVIEW-2026-03-02.md](/home/inc/repos/NEXUS3/docs/reviews/archive/CODEX-NEXUS3-REVIEW-2026-03-02.md)
2. [CODEX-NEXUS3-REVIEW-MERGED-2026-03-02.md](/home/inc/repos/NEXUS3/docs/reviews/archive/CODEX-NEXUS3-REVIEW-MERGED-2026-03-02.md)
3. [CODEX-NEXUS3-STATIC-TOPICS-2026-03-02.md](/home/inc/repos/NEXUS3/docs/reviews/archive/CODEX-NEXUS3-STATIC-TOPICS-2026-03-02.md)
4. [CODEX-NEXUS3-VALIDATION-SWARM-2026-03-02.md](/home/inc/repos/NEXUS3/docs/reviews/archive/CODEX-NEXUS3-VALIDATION-SWARM-2026-03-02.md)

## Severity and Confidence Model

- `Critical`: likely boundary break (security/tenant isolation/trust domain violation).
- `High`: serious correctness or security issue with meaningful operational impact.
- `Medium`: important bug/hardening gap; usually bounded blast radius.
- `Low`: standards-compliance or edge-case weakness with lower direct risk.

Confidence tags:
- `Confirmed`: repeatedly validated by independent reviewers/validators.
- `Partial`: real issue exists, but original framing was too broad.
- `Reclassified`: prior wording overstated exploitability; still potentially worth hardening.

## Adjudicated Contradictions (Resolved)

These were explicitly reviewed because earlier reports conflicted.

### 1) `X-Nexus-Agent` spoofing framed as direct privilege escalation

Final status: `Reclassified`.

What changed:
- The original framing as guaranteed privilege escalation is not accurate under current destroy-policy defaults.
- The underlying concern remains real as an identity-integrity/audit-trust weakness.

Key code references:
- [rpc/http.py](/home/inc/repos/NEXUS3/nexus3/rpc/http.py:570)
- [rpc/pool.py](/home/inc/repos/NEXUS3/nexus3/rpc/pool.py:1101)
- [test_destroy_authorization.py](/home/inc/repos/NEXUS3/tests/security/test_destroy_authorization.py:183)

### 2) Destroy-path requester propagation missing

Final status: `Partial`.

What changed:
- In-process path appears to propagate requester correctly.
- HTTP fallback path does not carry requester identity via header, so it is treated as external.

Key code references:
- [rpc/pool.py](/home/inc/repos/NEXUS3/nexus3/rpc/pool.py:616)
- [rpc/agent_api.py](/home/inc/repos/NEXUS3/nexus3/rpc/agent_api.py:311)
- [skill/base.py](/home/inc/repos/NEXUS3/nexus3/skill/base.py:774)
- [client.py](/home/inc/repos/NEXUS3/nexus3/client.py:181)
- [rpc/http.py](/home/inc/repos/NEXUS3/nexus3/rpc/http.py:570)

### 3) “Sandbox hard-deny is absolute”

Final status: `Reclassified` (wording correction).

What changed:
- Absolute deny is not true in current design.
- There is an explicit override path (`enabled=True`) and at least one intentional use case (`nexus_send`).

Key code references:
- [session/enforcer.py](/home/inc/repos/NEXUS3/nexus3/session/enforcer.py:121)
- [core/presets.py](/home/inc/repos/NEXUS3/nexus3/core/presets.py:154)

### 4) Clipboard manager persistent in-memory divergence

Final status: `Partial` (narrowed).

What changed:
- Broad “persistent manager cache divergence” claim was too wide for project/system-scope fetch behavior.
- Core integrity concern remains around storage atomicity on create/tag operations.

Key code references:
- [clipboard/manager.py](/home/inc/repos/NEXUS3/nexus3/clipboard/manager.py:197)
- [clipboard/storage.py](/home/inc/repos/NEXUS3/nexus3/clipboard/storage.py:179)

## Prioritized Risk Register and Remediation Guide

## Critical-1: MCP Visibility Boundary Bypass at Execution-Time Lookup (`Confirmed`)

Affected code:
- [session/dispatcher.py](/home/inc/repos/NEXUS3/nexus3/session/dispatcher.py:50)
- [mcp/registry.py](/home/inc/repos/NEXUS3/nexus3/mcp/registry.py:349)

Issue summary:
- Execution-time lookup for MCP-backed tools does not consistently enforce caller visibility/ownership boundaries.
- A caller that should only see a constrained set of MCP servers/tools may still execute against non-visible entries if lookup path is not identity-scoped.

Why this happens:
- Tool resolution and authorization checks appear to be split across call sites with insufficient binding to caller identity at the point of execution.

Potential impact:
- Cross-agent boundary violations.
- Accidental or malicious access to tools outside intended scope.
- Audit inconsistency (what caller “can see” diverges from what caller “can run”).

Suggested fix:
- Centralize execution-time authorization in one function that takes `(requester_id, tool_name, server_id)` and returns either a fully authorized target or denial.
- Ensure all MCP execution paths call that function immediately before invocation.
- Make visibility and execute-authorization use the same policy object/data source.
- Treat missing requester identity as least-privileged by default unless explicitly in trusted server-internal path.

Suggested tests:
- Add security tests where Agent A cannot execute Agent B-private MCP server/tool even if tool name is known.
- Add regression test for “visible list” parity with “executable list”.
- Add negative tests for fallback resolution paths.

## Critical-2: Sandbox Deny Overrides Require Governance Hardening (`Confirmed`, framing adjusted)

Affected code:
- [session/enforcer.py](/home/inc/repos/NEXUS3/nexus3/session/enforcer.py:121)

Issue summary:
- Sandbox-denied tools can be re-enabled by per-tool `enabled=True` overrides.
- This is partly intentional, but currently behaves like a powerful escape hatch if configuration governance is weak.

Why this matters:
- Design may be valid, but operational risk is high when config provenance/trust is not strict.
- A feature intended for narrow exceptions can become a broad policy bypass in practice.

Potential impact:
- Unexpected tool availability in sandboxed contexts.
- Drift between security expectations and actual runtime policy.

Suggested fix:
- Introduce explicit “non-overridable” deny set for sandbox preset.
- Require additional trust gate for override (for example: only from trusted config source, or only in trusted preset).
- Emit warning or hard error when sandbox profile attempts to re-enable hard-denied tools.
- Add policy linter on startup to detect dangerous override combinations.

Suggested tests:
- Matrix tests covering preset x tool override x expected allow/deny.
- Ensure known intentional exception (`nexus_send`) remains explicit and documented.

## High-1: Cross-Request Requester Race in Global Dispatcher (`Confirmed`)

Affected code:
- [rpc/global_dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/global_dispatcher.py:108)

Issue summary:
- Shared mutable requester state in a global dispatcher can be overwritten by concurrent requests.

Why this happens:
- Request-scoped identity is stored in shared object state rather than immutable per-request context.

Potential impact:
- Authorization checks can evaluate against wrong requester.
- Logs and attribution can be incorrect.
- Rare, timing-sensitive policy failures under concurrent load.

Suggested fix:
- Remove mutable global requester field for active request handling.
- Pass requester identity as explicit function parameter throughout dispatch chain.
- If context-local storage is used, ensure strict request-task boundary and cleanup.

Suggested tests:
- Concurrent stress test: many overlapping requests with unique requester IDs; assert no cross-attribution.
- Repeat test with mixed allow/deny policy outcomes to detect privilege bleed.

## High-2: Context Compaction Can Break Tool-Call/Tool-Result Pairing (`Confirmed`)

Affected code:
- [context/compaction.py](/home/inc/repos/NEXUS3/nexus3/context/compaction.py:154)

Issue summary:
- Compaction may preserve orphan `tool` messages without matching assistant tool-call message.

Why this matters:
- Providers consuming malformed conversational state can hallucinate state, fail function-call continuity, or produce unstable outputs.

Potential impact:
- Lower answer quality.
- Tool-call protocol confusion.
- Hard-to-debug non-deterministic model behavior.

Suggested fix:
- Treat tool-call and tool-result as an atomic pair/unit during compaction.
- If one side would be removed, remove both or re-summarize both into a consistent synthetic state.
- Add invariants checker post-compaction.

Suggested tests:
- Property tests generating random message streams with tool calls/results; assert no orphan results post-compaction.
- Regression tests for smallest-token-budget edge cases.

## High-3: Budget-Fit Truncation Invariant Break (`Confirmed`)

Affected code:
- [context/manager.py](/home/inc/repos/NEXUS3/nexus3/context/manager.py:701)

Issue summary:
- Truncation strategy can still return a context over budget in some edge/grouping paths.

Potential impact:
- Upstream provider rejections.
- Silent retries/fallback churn.
- Increased latency and cost.

Suggested fix:
- Enforce hard post-condition: `final_token_count <= budget` before returning.
- If strategy output exceeds budget, run deterministic emergency trimming pass.
- Prefer deterministic ordering so behavior is reproducible.

Suggested tests:
- Budget invariant test across multiple truncation strategies and message-shape permutations.
- Include tiny-budget and huge-single-message edge cases.

## High-4: Blocked-Path and Symlink Gaps in Multi-File Tools (`Confirmed`)

Affected code:
- [skill/builtin/outline.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/outline.py:1547)
- [skill/builtin/concat_files.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/concat_files.py:553)

Related areas identified in supporting reports:
- `grep` and `glob` family behavior should be treated as same-class risk until verified fixed.

Issue summary:
- Some multi-file paths are validated at directory level but per-entry operations can follow symlinks or miss blocked-path enforcement consistently.

Potential impact:
- Reads outside intended sandbox roots.
- Leakage of sensitive files through scanner/listing operations.

Suggested fix:
- Canonicalize each candidate file path at read time (not just root path once).
- Reject if resolved path escapes allowed roots or intersects blocked paths.
- Use safe-open primitives that avoid symlink traversal where platform allows.
- Align all multi-file tools to one shared path-authorization helper.

Suggested tests:
- Security tests with symlink farms, nested symlinks, and blocked directories.
- Cross-tool consistency tests for `outline`, `concat_files`, `grep`, `glob_search`.

## High-5: Patch Fidelity Defects (Whitespace + EOF Newline Semantics) (`Confirmed`)

Affected code:
- [patch/applier.py](/home/inc/repos/NEXUS3/nexus3/patch/applier.py:247)
- [patch/parser.py](/home/inc/repos/NEXUS3/nexus3/patch/parser.py:217)

Issue summary:
- Trailing whitespace may be altered in tolerant/fuzzy modes.
- EOF newline marker semantics are not preserved end-to-end.

Potential impact:
- Silent content corruption.
- Surprising diffs after patch application.
- Risky behavior for code/style-sensitive files and generated artifacts.

Suggested fix:
- Preserve exact line bytes unless an explicit normalization mode is selected.
- Carry EOF-newline metadata through parse model to final write path.
- Make tolerant/fuzzy matching independent from final output byte fidelity.

Suggested tests:
- Golden tests for trailing-space preservation.
- End-to-end patch tests for files with/without terminal newline.
- Fuzzy matching tests asserting exact output fidelity when patch applies.

## High-6: Terminal Output Injection Surfaces (`Confirmed`)

Affected code:
- [cli/repl.py](/home/inc/repos/NEXUS3/nexus3/cli/repl.py:1500)
- [mcp/error_formatter.py](/home/inc/repos/NEXUS3/nexus3/mcp/error_formatter.py:130)
- [cli/client_commands.py](/home/inc/repos/NEXUS3/nexus3/cli/client_commands.py:51)

Issue summary:
- Untrusted strings can reach terminal rendering paths with insufficient normalization of control sequences.

Potential impact:
- Terminal spoofing (line rewrite, fake prompts, visual deception).
- Operator confusion during incident response.
- Potential copy/paste trap vectors.

Suggested fix:
- Introduce one mandatory terminal-safety sanitizer in final rendering pipeline.
- Strip or encode dangerous control sequences (`OSC`, `CSI`, and carriage-return-based rewrites where unsafe).
- Clearly mark untrusted error payloads as escaped text.

Suggested tests:
- Regression fixtures containing ANSI/OSC/CR payloads.
- Snapshot tests for display output in REPL + client command paths.

## High-7: Provider Reasoning Cache-Key Collision (`Confirmed`)

Affected code:
- [provider/registry.py](/home/inc/repos/NEXUS3/nexus3/provider/registry.py:98)

Issue summary:
- Provider cache key appears to omit `reasoning` mode dimensions, causing aliasing between semantically different configurations.

Potential impact:
- Wrong provider/client reuse.
- Inconsistent behavior and hard-to-reproduce inference differences.

Suggested fix:
- Include all behavior-affecting fields in key material (including reasoning config).
- Version the cache key schema to avoid silent collisions after future changes.

Suggested tests:
- Unit tests for key inequality across reasoning-mode permutations.
- Cache hit/miss behavior tests to confirm correct segregation.

## High-8: Loader/Protocol Robustness Gaps (`Confirmed`)

Affected code:
- [context/loader.py](/home/inc/repos/NEXUS3/nexus3/context/loader.py:495)
- [rpc/protocol.py](/home/inc/repos/NEXUS3/nexus3/rpc/protocol.py:66)
- [rpc/protocol.py](/home/inc/repos/NEXUS3/nexus3/rpc/protocol.py:219)

Issue summary:
- Non-dict `mcp.json` server entries can crash loader path.
- JSON-RPC bool IDs are accepted due to Python type behavior.
- Error-object typing is weak in protocol validation.

Potential impact:
- Parser crashes from malformed config.
- Non-compliant protocol behavior and edge-case interoperability issues.

Suggested fix:
- Strict schema validation at load/parse boundaries with explicit error messages.
- Reject bool IDs explicitly even though `bool` subclasses `int`.
- Validate error object shape and types per protocol spec.

Suggested tests:
- Negative tests for malformed `mcp.json` structures.
- Protocol tests for bool ID rejection and error-object shape enforcement.

## Additional Important Findings (Not in Top-8, Still Worth Scheduling)

These were repeatedly surfaced but ranked lower than immediate top blockers.

1. Agent destroy lifecycle race under concurrent activity.
- [rpc/pool.py](/home/inc/repos/NEXUS3/nexus3/rpc/pool.py:1120)

2. Session restore trust of persisted preset can bypass create-time assumptions.
- [rpc/pool.py](/home/inc/repos/NEXUS3/nexus3/rpc/pool.py:866)

3. `ToolPermission.requires_confirmation` appears declared but not consistently enforced.
- [core/presets.py](/home/inc/repos/NEXUS3/nexus3/core/presets.py:47)
- [session/enforcer.py](/home/inc/repos/NEXUS3/nexus3/session/enforcer.py:320)

4. `allowed_paths=[]` semantics may not preserve deny-all intent in all paths.
- [core/presets.py](/home/inc/repos/NEXUS3/nexus3/core/presets.py:225)
- [core/permissions.py](/home/inc/repos/NEXUS3/nexus3/core/permissions.py:352)

5. `\r` handling can allow line-rewrite style spoofing in some render flows.
- [core/text_safety.py](/home/inc/repos/NEXUS3/nexus3/core/text_safety.py:42)

## Suggested Implementation Order (Practical)

1. Fix boundary/security invariants first.
- MCP execution authorization unification.
- Multi-file path enforcement + symlink hardening.
- Requester isolation in global dispatcher.

2. Fix correctness integrity hazards second.
- Context invariants (pairing + budget hard guarantees).
- Patch fidelity (whitespace/newline).
- Provider key correctness.

3. Harden input/output and parser robustness third.
- Terminal-safe rendering.
- Loader/protocol strict validation.
- Follow-up on confirmation/deny-all semantics.

4. Close with reliability races and lower-severity semantic issues.

## Suggested Work Breakdown for Less-Capable Agents

If delegated to an agent with limited reasoning depth, assign one bounded package at a time:

1. `MCP auth package`
- Scope: `session/dispatcher.py`, `mcp/registry.py`, relevant tests under `tests/security`.
- Done criteria: execution-time authorization and visibility parity tests passing.

2. `Filesystem boundary package`
- Scope: `skill/builtin/outline.py`, `concat_files.py`, `grep.py`, `glob_search.py`, shared path helpers.
- Done criteria: symlink and blocked-path tests pass across all tools.

3. `RPC requester isolation package`
- Scope: `rpc/global_dispatcher.py` plus auth call chain.
- Done criteria: concurrent requester-race tests prove isolation.

4. `Context invariants package`
- Scope: `context/compaction.py`, `context/manager.py`.
- Done criteria: no orphan tool results; hard budget post-condition always true.

5. `Patch fidelity package`
- Scope: `patch/parser.py`, `patch/applier.py`.
- Done criteria: golden fidelity tests for whitespace and EOF newline semantics.

6. `Terminal and parser hardening package`
- Scope: `cli/*`, `display/*`, `mcp/error_formatter.py`, `context/loader.py`, `rpc/protocol.py`.
- Done criteria: injected control-sequence payloads render safely; malformed configs/protocol payloads fail cleanly.

## Deferred Work (Status Update: 2026-03-06)

Post-M4 deferred validation campaign closeout is complete with archived evidence:

1. Long soak/performance stability runs:
   - closed in `post-m4-20260306-live1b` soak artifacts.
2. Windows-native validation on actual Windows host:
   - closed in `post-m4-20260306-live1e/windows/`.
3. Timing-sensitive TOCTOU/lifecycle race validation:
   - closed in `post-m4-20260306-live1c/race/`.
4. Real terminal-emulator validation for OSC/CSI/CR behavior differences:
   - automated matrix coverage in `post-m4-20260306-live1d/terminal/`
   - live multi-emulator carriage-return closure in
     `post-m4-20260306-live1e/terminal/`.

Deterministic campaign gate result:
- `docs/validation/post-m4-20260306-live1e/closeout-gate.json` (`pass=true`)

## Final Notes

- Validation agents found some wording overstatements in earlier drafts; those are corrected in this version.
- Core risk picture remains intact: boundary enforcement, requester isolation, and context/patch integrity are the highest value fixes.
- This file should remain the primary entry point for remediation until each item is closed and linked to merged fixes.

## Owner-Ready Ticket Templates

Use these as copy-paste issue bodies. Replace `Owner: TBD` during triage.

### Ticket R1: Enforce MCP Execution Authorization at Runtime

- Priority: `P0`
- Severity: `Critical`
- Owner: `TBD`
- Related findings: `Critical-1`
- Primary files:
- [session/dispatcher.py](/home/inc/repos/NEXUS3/nexus3/session/dispatcher.py:50)
- [mcp/registry.py](/home/inc/repos/NEXUS3/nexus3/mcp/registry.py:349)
- Scope:
- Bind execution-time MCP lookup to requester identity.
- Use one authorization path for both visibility and execution.
- Out of scope:
- MCP UX polish and non-security refactors.
- Acceptance criteria:
- Agent without visibility to private MCP server cannot execute its tools by direct name/reference.
- Visibility list and executable list are consistent for same requester.
- Missing requester identity defaults to least privilege unless explicit trusted internal path.
- Required tests:
- Add `tests/security/test_mcp_execution_visibility_enforcement.py`.
- Add regression test for fallback lookup paths and alias resolution.

### Ticket R2: Harden Sandbox Hard-Deny Override Semantics

- Priority: `P0`
- Severity: `Critical`
- Owner: `TBD`
- Related findings: `Critical-2`
- Primary files:
- [session/enforcer.py](/home/inc/repos/NEXUS3/nexus3/session/enforcer.py:121)
- [core/presets.py](/home/inc/repos/NEXUS3/nexus3/core/presets.py:154)
- Scope:
- Define explicit non-overridable deny list for sandbox preset.
- Gate any override behind trusted configuration source or trusted preset.
- Out of scope:
- Broad permission model redesign.
- Acceptance criteria:
- Sandbox hard-denied tools remain denied even when per-tool `enabled=True` is set, except explicitly whitelisted exceptions.
- Policy startup validation emits actionable errors for unsafe combinations.
- Required tests:
- Add `tests/security/test_sandbox_hard_deny_override_matrix.py`.
- Ensure intentional exception behavior (`nexus_send`) is tested and documented.

### Ticket R3: Remove Cross-Request Requester Race in Global Dispatcher

- Priority: `P1`
- Severity: `High`
- Owner: `TBD`
- Related findings: `High-1`
- Primary files:
- [rpc/global_dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/global_dispatcher.py:108)
- Scope:
- Eliminate mutable shared requester identity from concurrent request handling.
- Pass requester as explicit per-request context through authorization calls.
- Out of scope:
- Unrelated dispatcher feature changes.
- Acceptance criteria:
- Concurrent requests cannot affect one another’s requester identity or auth result.
- Attribution/logging remains correct under high concurrency.
- Required tests:
- Add `tests/security/test_h1_global_dispatcher_requester_race.py`.
- Add stress test with mixed permit/deny request set.

### Ticket R4: Preserve Tool-Call/Tool-Result Invariants During Compaction

- Priority: `P1`
- Severity: `High`
- Owner: `TBD`
- Related findings: `High-2`
- Primary files:
- [context/compaction.py](/home/inc/repos/NEXUS3/nexus3/context/compaction.py:154)
- Scope:
- Treat assistant tool-call + tool-result as atomic for compaction/trimming.
- Add post-compaction invariant check for orphan tool messages.
- Out of scope:
- New compaction strategies unrelated to correctness.
- Acceptance criteria:
- No compacted output contains orphan `tool` message lacking originating assistant tool call.
- Behavior is deterministic for equal inputs.
- Required tests:
- Add `tests/unit/context/test_compaction_tool_pair_invariant.py`.
- Add tiny-budget edge-case regressions.

### Ticket R5: Enforce Strict Budget-Fit Postcondition in Context Builder

- Priority: `P1`
- Severity: `High`
- Owner: `TBD`
- Related findings: `High-3`
- Primary files:
- [context/manager.py](/home/inc/repos/NEXUS3/nexus3/context/manager.py:701)
- Scope:
- Guarantee `final_token_count <= budget` before returning messages.
- Add deterministic emergency trimming if primary strategy overshoots.
- Out of scope:
- Tokenizer/provider abstraction redesign.
- Acceptance criteria:
- All context builder strategies satisfy strict budget fit across edge cases.
- No over-budget payloads are returned to provider layer.
- Required tests:
- Add `tests/unit/context/test_middle_out_budget_invariant.py`.
- Add multi-strategy parameterized test covering tiny and adversarial budgets.

### Ticket R6: Close Multi-File Tool Path and Symlink Boundary Gaps

- Priority: `P1`
- Severity: `High`
- Owner: `TBD`
- Related findings: `High-4`
- Primary files:
- [skill/builtin/outline.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/outline.py:1547)
- [skill/builtin/concat_files.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/concat_files.py:553)
- Scope:
- Enforce blocked-path and allowed-root checks per resolved file entry.
- Prevent symlink traversal outside policy boundaries across all multi-file tools.
- Normalize implementation through shared path-authorization helper.
- Out of scope:
- Full filesystem virtualization.
- Acceptance criteria:
- `outline`, `concat_files`, `grep`, and `glob_search` consistently deny escaped or blocked resolved paths.
- Symlink chain attacks do not leak contents.
- Required tests:
- Add `tests/security/test_blocked_paths_multifile_tools.py`.
- Add explicit symlink-chain and nested-blocked-path fixtures.

### Ticket R7: Fix Patch Fidelity for Trailing Whitespace and EOF Newline

- Priority: `P1`
- Severity: `High`
- Owner: `TBD`
- Related findings: `High-5`
- Primary files:
- [patch/applier.py](/home/inc/repos/NEXUS3/nexus3/patch/applier.py:247)
- [patch/parser.py](/home/inc/repos/NEXUS3/nexus3/patch/parser.py:217)
- Scope:
- Preserve original line bytes unless explicit normalization mode is selected.
- Carry EOF newline metadata through parse and apply layers.
- Out of scope:
- New patch formats.
- Acceptance criteria:
- Trailing whitespace is preserved after successful patch application.
- “No newline at end of file” semantics are preserved end-to-end.
- Required tests:
- Add `tests/unit/patch/test_applier_trailing_space_fidelity.py`.
- Add `tests/unit/patch/test_newline_marker_end_to_end.py`.

### Ticket R8: Sanitize Untrusted Terminal Output in REPL/MCP/Client Paths

- Priority: `P1`
- Severity: `High`
- Owner: `TBD`
- Related findings: `High-6`
- Primary files:
- [cli/repl.py](/home/inc/repos/NEXUS3/nexus3/cli/repl.py:1500)
- [mcp/error_formatter.py](/home/inc/repos/NEXUS3/nexus3/mcp/error_formatter.py:130)
- [cli/client_commands.py](/home/inc/repos/NEXUS3/nexus3/cli/client_commands.py:51)
- Scope:
- Apply one terminal-safety sanitizer in final rendering path for untrusted text.
- Neutralize unsafe OSC/CSI and carriage-return rewrite behavior where needed.
- Out of scope:
- Rich terminal styling redesign.
- Acceptance criteria:
- Known escape-sequence payloads render inertly and cannot visually spoof prompts/output lines.
- Existing legitimate formatting remains readable.
- Required tests:
- Add `tests/security/test_terminal_escape_sanitization.py`.
- Add fixtures for ANSI/OSC/CSI/CR payload variants.

### Ticket R9: Fix Provider Registry Cache-Key Collisions for Reasoning Mode

- Priority: `P1`
- Severity: `High`
- Owner: `TBD`
- Related findings: `High-7`
- Primary files:
- [provider/registry.py](/home/inc/repos/NEXUS3/nexus3/provider/registry.py:98)
- Scope:
- Include reasoning-relevant fields in cache key material.
- Version cache key structure to prevent future silent collisions.
- Out of scope:
- Provider selection policy changes.
- Acceptance criteria:
- Distinct reasoning configurations cannot share cache key.
- Existing non-reasoning behavior remains stable.
- Required tests:
- Add `tests/unit/provider/test_registry_reasoning_cache_key.py`.

### Ticket R10: Harden Loader and JSON-RPC Protocol Validation

- Priority: `P1`
- Severity: `High`
- Owner: `TBD`
- Related findings: `High-8`
- Primary files:
- [context/loader.py](/home/inc/repos/NEXUS3/nexus3/context/loader.py:495)
- [rpc/protocol.py](/home/inc/repos/NEXUS3/nexus3/rpc/protocol.py:66)
- [rpc/protocol.py](/home/inc/repos/NEXUS3/nexus3/rpc/protocol.py:219)
- Scope:
- Reject malformed `mcp.json` entries with structured diagnostics.
- Enforce JSON-RPC ID typing rules (including explicit bool rejection).
- Enforce strict error-object schema validation.
- Out of scope:
- Backward compatibility shims for invalid payloads.
- Acceptance criteria:
- Malformed configs no longer crash loader and return actionable validation errors.
- Bool IDs are rejected as invalid request IDs.
- Invalid error-object shapes are rejected consistently.
- Required tests:
- Add `tests/unit/context/test_mcp_json_schema_validation.py`.
- Add `tests/unit/rpc/test_protocol_id_and_error_schema.py`.

## Backlog Tickets (Schedule After Top-10)

### Ticket B1: Destroy Lifecycle Concurrency Hardening

- Priority: `P2`
- Related findings: agent destroy race
- Primary file:
- [rpc/pool.py](/home/inc/repos/NEXUS3/nexus3/rpc/pool.py:1120)
- Goal:
- Ensure in-flight work is quiesced before teardown finalization.

### Ticket B2: Persisted Preset Trust Revalidation on Restore

- Priority: `P2`
- Related findings: restore trust gap
- Primary file:
- [rpc/pool.py](/home/inc/repos/NEXUS3/nexus3/rpc/pool.py:866)
- Goal:
- Re-validate restored session permissions against current policy constraints.

### Ticket B3: Enforce `requires_confirmation` Semantics

- Priority: `P2`
- Related findings: confirmation policy gap
- Primary files:
- [core/presets.py](/home/inc/repos/NEXUS3/nexus3/core/presets.py:47)
- [session/enforcer.py](/home/inc/repos/NEXUS3/nexus3/session/enforcer.py:320)
- Goal:
- Ensure confirmation gates are actually consulted during tool authorization.

### Ticket B4: Clarify and Enforce `allowed_paths=[]` Deny-All Behavior

- Priority: `P2`
- Related findings: deny-all semantic drift
- Primary files:
- [core/presets.py](/home/inc/repos/NEXUS3/nexus3/core/presets.py:225)
- [core/permissions.py](/home/inc/repos/NEXUS3/nexus3/core/permissions.py:352)
- Goal:
- Make empty-list semantics explicit and consistently enforced.

## Related Documents

- [Reviews Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/reviews/README.md)
- [Plans Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/plans/README.md)
- [Canonical Review Master Final](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
- [Architecture Investigation](/home/inc/repos/NEXUS3/docs/plans/ARCH-INVESTIGATION-2026-03-02.md)
- [Architecture Milestone Schedule](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
