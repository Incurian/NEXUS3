# NEXUS3 Review Master (All Codex Rounds)

Date: 2026-03-02

This is the unified master index for all review passes run today.

## Included Reports

1. [CODEX-NEXUS3-REVIEW-2026-03-02.md](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-2026-03-02.md) (Round 1)
2. [CODEX-NEXUS3-REVIEW-MERGED-2026-03-02.md](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MERGED-2026-03-02.md) (Rounds 1+2, deduped/reclassified)
3. [CODEX-NEXUS3-STATIC-TOPICS-2026-03-02.md](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-STATIC-TOPICS-2026-03-02.md) (additional static-only topic sweeps)

## Consolidated Additions From Static-Only Sweep

These are major items added or materially strengthened after the prior merged report:

### Critical

1. MCP visibility boundary bypass at execution-time lookup.
- Files:
  - [session/dispatcher.py](/home/inc/repos/NEXUS3/nexus3/session/dispatcher.py:50)
  - [mcp/registry.py](/home/inc/repos/NEXUS3/nexus3/mcp/registry.py:349)

2. SANDBOXED hard-deny tools can be re-enabled via per-tool `enabled=True` short-circuit.
- Files:
  - [session/enforcer.py](/home/inc/repos/NEXUS3/nexus3/session/enforcer.py:123)
  - [core/policy.py](/home/inc/repos/NEXUS3/nexus3/core/policy.py:93)

### High

1. Agent destroy lifecycle race with resource teardown before in-flight work is fully quiesced.
- Files:
  - [rpc/pool.py](/home/inc/repos/NEXUS3/nexus3/rpc/pool.py:1120)
  - [rpc/dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/dispatcher.py:432)

2. Concurrent `compact` vs `send` race on message history mutation.
- Files:
  - [rpc/dispatcher.py](/home/inc/repos/NEXUS3/nexus3/rpc/dispatcher.py:399)
  - [context/manager.py](/home/inc/repos/NEXUS3/nexus3/context/manager.py:520)

3. Session restore preset trust permits create-time policy bypass scenarios (e.g., yolo reintroduction through tampered session JSON).
- Files:
  - [rpc/pool.py](/home/inc/repos/NEXUS3/nexus3/rpc/pool.py:866)
  - [session/persistence.py](/home/inc/repos/NEXUS3/nexus3/session/persistence.py:107)

4. `ToolPermission.requires_confirmation` currently has no enforcement effect.
- Files:
  - [core/presets.py](/home/inc/repos/NEXUS3/nexus3/core/presets.py:47)
  - [session/enforcer.py](/home/inc/repos/NEXUS3/nexus3/session/enforcer.py:320)

5. `allowed_paths=[]` deny-all semantics are not preserved in key resolution paths.
- Files:
  - [core/presets.py](/home/inc/repos/NEXUS3/nexus3/core/presets.py:225)
  - [core/permissions.py](/home/inc/repos/NEXUS3/nexus3/core/permissions.py:352)

6. Additional output-safety findings in REPL/MCP formatting paths (markup/control-sequence injection surfaces).
- Files:
  - [cli/repl_commands.py](/home/inc/repos/NEXUS3/nexus3/cli/repl_commands.py:1968)
  - [mcp/error_formatter.py](/home/inc/repos/NEXUS3/nexus3/mcp/error_formatter.py:130)
  - [cli/repl.py](/home/inc/repos/NEXUS3/nexus3/cli/repl.py:1506)

## Reclassification Notes Carried Forward

1. `X-Nexus-Agent` spoofing as direct privilege escalation was reclassified as context-dependent (identity-integrity issue still stands).
2. Earlier destroy-path requester-propagation bypass claim was reclassified as not reproducible in current code/tests.

## Deferred Work (Must Still Be Done Later)

These require live testing, prolonged runtime, or other environments and were not completed in this static-only phase:

1. Long soak/performance stability tests under sustained load and compaction churn.
2. Windows-native runtime verification on real Windows host (junction/reparse, taskkill path behavior, console specifics).
3. Timing-sensitive exploit validation for TOCTOU and lifecycle races under realistic multi-process conditions.
4. Full terminal red-team validation on real terminal emulators/shell combinations.

## Usage Guidance

- Use this master file as entry point.
- Use [CODEX-NEXUS3-REVIEW-MERGED-2026-03-02.md](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MERGED-2026-03-02.md) for the most complete deduped list from rounds 1+2.
- Use [CODEX-NEXUS3-STATIC-TOPICS-2026-03-02.md](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-STATIC-TOPICS-2026-03-02.md) for the extra topic sweeps and explicit deferred test plan.

## Related Documents

- [Reviews Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/reviews/README.md)
- [Plans Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/plans/README.md)
- [Canonical Review Master Final](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
- [Architecture Investigation](/home/inc/repos/NEXUS3/docs/plans/ARCH-INVESTIGATION-2026-03-02.md)
- [Architecture Milestone Schedule](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
