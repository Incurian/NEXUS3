# NEXUS3 Findings Validation Swarm

Date: 2026-03-02
Goal: independently validate previously reported findings and explicitly identify errors/overstatements.
Method: 6 parallel validation agents + 1 replacement validator for interrupted domain.

## Validation Outcome Summary

- Confirmed: many high-impact findings remain valid (RPC race, blocked-path bypasses, context invariants, terminal safety sinks, patch fidelity, config/parser robustness issues).
- Partially confirmed: several findings are real but narrower in scope than originally phrased.
- Disputed/reclassified: a subset of claims were over-broad or framed as escalation when they are integrity/semantics issues.

## Disputed / Reclassified First

1. `X-Nexus-Agent` spoofing as direct privilege escalation in destroy flow.
- Status: `disputed as escalation framing`
- Reason: external caller context (`requester_id=None`) is already privileged in current destroy policy path.
- Evidence:
  - [rpc/http.py](/home/inc/repos/NEXUS3/nexus3/rpc/http.py:570)
  - [rpc/pool.py](/home/inc/repos/NEXUS3/nexus3/rpc/pool.py:1080)

2. Missing requester propagation in destroy path.
- Status: `disputed`
- Reason: current code propagates requester through agent API to global dispatcher and pool auth check.
- Evidence:
  - [rpc/pool.py](/home/inc/repos/NEXUS3/nexus3/rpc/pool.py:619)
  - [rpc/agent_api.py](/home/inc/repos/NEXUS3/nexus3/rpc/agent_api.py:311)
  - [rpc/global_dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/global_dispatcher.py:507)

3. “Sandbox hard-deny is absolute” (wording issue).
- Status: `false positive as absolute claim`
- Reason: sandbox deny list is intentionally overrideable via explicit per-tool `enabled=True` (used for `nexus_send`).
- Evidence:
  - [session/enforcer.py](/home/inc/repos/NEXUS3/nexus3/session/enforcer.py:121)
  - [core/presets.py](/home/inc/repos/NEXUS3/nexus3/core/presets.py:154)

4. Clipboard manager in-memory divergence claim.
- Status: `disputed/limited`
- Reason: for project/system scopes manager fetches entries from storage on demand, reducing persistent divergence risk in tested path.
- Evidence:
  - [clipboard/manager.py](/home/inc/repos/NEXUS3/nexus3/clipboard/manager.py:202)
  - [clipboard/manager.py](/home/inc/repos/NEXUS3/nexus3/clipboard/manager.py:204)

## Confirmed Findings (Representative)

1. Cross-request requester race via shared mutable field.
- [rpc/global_dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/global_dispatcher.py:108)

2. Private MCP visibility bypass at execution-time skill lookup.
- [session/dispatcher.py](/home/inc/repos/NEXUS3/nexus3/session/dispatcher.py:50)
- [mcp/registry.py](/home/inc/repos/NEXUS3/nexus3/mcp/registry.py:349)

3. Context compaction can split tool-call/tool-result pairing.
- [context/compaction.py](/home/inc/repos/NEXUS3/nexus3/context/compaction.py:154)

4. Context truncation can exceed budget invariants.
- [context/manager.py](/home/inc/repos/NEXUS3/nexus3/context/manager.py:701)

5. Provider registry reasoning cache-key collision.
- [provider/registry.py](/home/inc/repos/NEXUS3/nexus3/provider/registry.py:98)

6. Blocked-path bypass in multi-file tools.
- [skill/builtin/concat_files.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/concat_files.py:553)
- [skill/builtin/outline.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/outline.py:1547)

7. Terminal/output injection sinks remain in REPL/client paths.
- [cli/repl.py](/home/inc/repos/NEXUS3/nexus3/cli/repl.py:1500)
- [cli/client_commands.py](/home/inc/repos/NEXUS3/nexus3/cli/client_commands.py:51)

8. Patch fidelity issues (trailing whitespace, EOF newline marker semantics).
- [patch/applier.py](/home/inc/repos/NEXUS3/nexus3/patch/applier.py:247)
- [patch/parser.py](/home/inc/repos/NEXUS3/nexus3/patch/parser.py:217)

9. `mcp.json` non-dict server entry can crash loader.
- [context/loader.py](/home/inc/repos/NEXUS3/nexus3/context/loader.py:495)

10. JSON-RPC bool ID acceptance.
- [rpc/protocol.py](/home/inc/repos/NEXUS3/nexus3/rpc/protocol.py:66)

## Partially Confirmed Findings (Narrowed)

1. `parent_agent_id` trust issue exists, but escalation impact is context-dependent.
- [rpc/global_dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/global_dispatcher.py:217)

2. Agent-destroy teardown race exists structurally; practical impact depends on timing/tool behavior.
- [rpc/pool.py](/home/inc/repos/NEXUS3/nexus3/rpc/pool.py:1120)

3. `concat_files` output redirection concern is narrower because output location is generated under validated base path, but race/symlink concerns remain.
- [skill/builtin/concat_files.py](/home/inc/repos/NEXUS3/nexus3/skill/builtin/concat_files.py:826)

## Coverage Notes from Validation

- Validators ran targeted tests (reported passing subsets like `55` and `169` tests), but repeatedly found missing negative tests for failure modes.
- Prior proposed test additions in existing review docs remain valid and should still be implemented.

## Final Validation Verdict

The swarm did find a few overstatements and reclassified items, but the core security/correctness risk picture remains intact. High-priority fixes should proceed, while reclassified items should be rewritten in docs to avoid overstating exploitability.

## Related Documents

- [Reviews Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/reviews/README.md)
- [Plans Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/plans/README.md)
- [Canonical Review Master Final](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
- [Architecture Investigation](/home/inc/repos/NEXUS3/docs/plans/ARCH-INVESTIGATION-2026-03-02.md)
- [Architecture Milestone Schedule](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
