# Architecture Milestone Schedule (2026-03-02)

## Overview

This schedule turns the A-H architecture plans into execution milestones with dependency gates, owner placeholders, and ship criteria.

## Milestone Order

### M0: Foundation and Safety Harness

Target scope:
- Plan H Phase 1 (schema inventory/models, no behavior flip)
- Plan A Phase 1 (authorization inventory + kernel interface)
- Baseline tests/fixtures for Plan E/F migration harness

Owners:
- `Owner H: TBD`
- `Owner A: TBD`
- `Owner E/F harness: TBD`

Dependencies:
- None

Exit gates:
- New schema and kernel interfaces merged behind behavior-preserving adapters.
- Added baseline regression fixtures for context compile and patch byte roundtrips, including:
  - `tests/unit/patch/test_byte_roundtrip_baseline.py`
  - `tests/unit/context/test_compile_baseline.py`
  - fixtures under `tests/fixtures/arch_baseline/`
- CI green on `.venv/bin/pytest tests/ -v`, `.venv/bin/ruff check nexus3/`, `.venv/bin/mypy nexus3/`.

Status note (2026-03-04):
- M0 E/F harness baseline implemented with deterministic fixture-driven parity tests for context repair/build sequencing and patch byte roundtrip behavior.

### M1: Boundary Enforcement Wave

Target scope:
- Plan D Phases 1-3 (filesystem gateway + multi-file tool migration)
- Plan H Phase 2 (ingress schema wiring with compatibility warnings)
- Plan G Phase 1-2 (safe sink API + high-risk path migration)

Owners:
- `Owner D: TBD`
- `Owner H: TBD`
- `Owner G: TBD`

Dependencies:
- M0 complete

Exit gates:
- `outline`, `concat_files`, `grep`, `glob` enforce per-file allowed/blocked decisions.
- Malformed RPC/mcp inputs fail through typed validators (compat mode enabled if needed).
- High-risk untrusted terminal outputs routed through safe sink.
- Security regression suite for blocked-path/symlink/terminal payloads passing.

### M2: Authorization and Concurrency Wave

Target scope:
- Plan A Phases 2-4 (route checks through kernel, remove duplicate branches)
- Plan C Phases 1-3 (immutable request context + skill statelessness)
- Plan H Phase 3 (strict mode default flip where safe and validated)

Owners:
- `Owner A: TBD`
- `Owner C: TBD`
- `Owner H strict flip: TBD`

Dependencies:
- M1 complete
- Plan C phases 1-2 complete before Plan A phase 3/4 cutover.

Exit gates:
- All lifecycle/tool authorization uses kernel path.
- No shared mutable requester state in global dispatcher path.
- Parallel skill execution tests prove no cross-call mutable state leaks.
- Strict schema mode default enabled only for approved ingress surfaces with typed schemas and compatibility telemetry.

### M3: Data Integrity Wave

Target scope:
- Plan F Phases 1-4 (Patch AST v2 + byte_strict path + safer target resolution)
- Plan E Phases 1-2 (context compiler with invariants; provider parity)

Owners:
- `Owner F: TBD`
- `Owner E: TBD`

Dependencies:
- M2 complete

Exit gates:
- Patch apply preserves whitespace/newline semantics in byte_strict mode.
- Ambiguous patch targets fail closed.
- Provider pipelines consume invariant-checked compiled context.
- No orphan tool-result messages in compiler outputs.
- Quality gates green: `.venv/bin/pytest tests/ -v`, `.venv/bin/pytest tests/integration/ -v`, `.venv/bin/ruff check nexus3/`, `.venv/bin/mypy nexus3/`.
- Live validation executed for behavior/RPC/skills/permissions changes:
  - `nexus3 &`
  - `nexus3 rpc create test-agent`
  - `nexus3 rpc send test-agent "describe your permissions and what you can do"`
  - `nexus3 rpc destroy test-agent`

Status note (2026-03-05):
- Plan F Phase 1 foundation committed as `1079cd7`:
  - AST v2 models + parser hook + applier bridge (no default behavior flip)
  - Expanded fixture-driven patch byte roundtrip baselines (explicit no-EOL marker + whitespace-sensitive payload)
- Plan F Phase 2 committed as `4ded3fa`:
  - explicit `apply_patch_byte_strict(...)` entrypoint for AST-v2 patches
  - focused newline/EOF fidelity regressions including mixed-newline preservation
- Plan F Phase 3 committed as `4c10b0b`:
  - patch-skill migration flag `fidelity_mode=legacy|byte_strict` with default legacy behavior preserved
  - migration regressions for byte-strict no-EOL marker path and invalid flag fail-fast behavior
- Plan F Phase 4 committed as `a342401`:
  - patch target-resolution hardened to prefer exact path and fail closed on ambiguous basename matches
  - multi-file diff regressions added for exact-match preference and ambiguity errors
- Plan F Phase 5 committed as `87c5df1`:
  - byte-strict non-UTF8/binary-adjacent regression coverage added
  - `apply_patch_byte_strict` byte-input support hardened with reversible `surrogateescape` decoding
- Plan F Phase 6 committed as `195ab86`:
  - patch skill default fidelity flipped to `byte_strict`
  - explicit `legacy` mode retained for compatibility fallback during soak
- Plan F Phase 7 closeout (current working tree):
  - runtime legacy patch-skill apply path retired; patch now always executes via AST-v2 + byte-strict applier
  - `fidelity_mode=legacy` now fails fast with explicit migration guidance
- Plan E Phase 1 (current working tree):
  - added `nexus3/context/compiler.py` typed compiler IR + invariant checker
  - added `tests/unit/context/test_compiler.py` for fixture parity, diagnostics, and invariant-report regressions
  - exported compiler interfaces in `nexus3/context/__init__.py`
- Next M3 target: Plan E Phase 2 provider/session integration against compiler output.

### M4: Delegation and Strategic Evolution

Target scope:
- Plan B Phases 1-4 (capability tokens in-process, optional HTTP, deprecate legacy identity path)
- Plan E Phases 3-4 (graph model introduction and compiler-backed compaction/truncation)
- Plan G Phase 3-4 (complete sink migration, cleanup)

Owners:
- `Owner B: TBD`
- `Owner E: TBD`
- `Owner G: TBD`

Dependencies:
- M3 complete

Exit gates:
- Capability-based delegation active on primary paths; legacy identity path removed.
- Graph-backed context path validated for parity and invariants.
- Terminal sink boundary fully adopted across display/CLI paths.
- Quality gates green: `.venv/bin/pytest tests/ -v`, `.venv/bin/pytest tests/integration/ -v`, `.venv/bin/ruff check nexus3/`, `.venv/bin/mypy nexus3/`.
- Live validation executed for behavior/RPC/skills/permissions changes:
  - `nexus3 &`
  - `nexus3 rpc create test-agent`
  - `nexus3 rpc send test-agent "describe your permissions and what you can do"`
  - `nexus3 rpc destroy test-agent`

## Explicit Deferred Follow-On Backlog (Added 2026-03-05)

1. Plan A follow-on boundary removal:
   - [ARCH-A-AUTH-REQUEST-MODEL-V2-PLAN-2026-03-05.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-A-AUTH-REQUEST-MODEL-V2-PLAN-2026-03-05.md)
   - Target window: M4 early (after M3 data-integrity gates are green).
   - Dependency gates:
     - M3 complete.
     - Current Plan A kernel-authoritative behavior remains stable.
   - Exit gates:
     - Create-stage `parent_can_grant` precompute path removed from `rpc/pool.py`.
     - Create adapter computes grant checks from typed auth request context.
     - Focused create authorization regression suites pass.

2. Plan H follow-on shim retirement:
   - [ARCH-H-RPC-ERROR-SHIM-RETIREMENT-PLAN-2026-03-05.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-H-RPC-ERROR-SHIM-RETIREMENT-PLAN-2026-03-05.md)
   - Target window: post-M4 cleanup after strict ingress has soaked in production-like use.
   - Dependency gates:
     - Strict ingress default remains stable across protocol + direct dispatch + method param ingress.
     - No active client breakage reports that depend on legacy error wording.
   - Exit gates:
     - Compatibility-only error-text mapping shims are removed or explicitly retained with rationale.
     - Canonical malformed-input diagnostics documented in `nexus3/rpc/README.md`.
     - Focused RPC ingress regression suites pass with updated expectations.

3. Plan C follow-on service immutability:
   - [ARCH-C-SERVICE-CONTAINER-IMMUTABILITY-PLAN-2026-03-05.md](/home/inc/repos/NEXUS3/docs/plans/ARCH-C-SERVICE-CONTAINER-IMMUTABILITY-PLAN-2026-03-05.md)
   - Target window: M4 mid (after current Plan A/Plan C runtime behavior is stable).
   - Dependency gates:
     - Current request-context propagation behavior is stable under existing tests.
     - No active regressions in REPL runtime mutation paths (`/cd`, `/permissions`, `/model`).
   - Exit gates:
     - Production runtime mutation paths no longer rely on open-ended `ServiceContainer.register(...)`.
     - Typed immutability/mutation regression coverage is in place for pool + REPL + session paths.
     - Focused pool/repl/session authorization suites pass.

4. Provider keep-alive deferred investigation:
   - [PROVIDER-KEEPALIVE-INVESTIGATION-PLAN-2026-03-05.md](/home/inc/repos/NEXUS3/docs/plans/PROVIDER-KEEPALIVE-INVESTIGATION-PLAN-2026-03-05.md)
   - Target window: M4 late / post-M4 stabilization window.
   - Dependency gates:
     - Existing provider empty-stream guards and retry behavior remain stable.
     - Repro artifacts exist from keep-alive diagnostics (Step 10 style runs).
   - Exit gates:
     - Decision recorded as either "no code change required" or "bounded mitigation landed".
     - If mitigation lands, provider keep-alive recovery tests are green.
     - Deferred tracker references are updated in config-ops and provider plan docs.

5. Structural refactor wave:
   - [STRUCTURAL-REFACTOR-WAVE-PLAN-2026-03-05.md](/home/inc/repos/NEXUS3/docs/plans/STRUCTURAL-REFACTOR-WAVE-PLAN-2026-03-05.md)
   - Target window: post-M4 cleanup (non-blocking for security gates).
   - Dependency gates:
     - No unresolved high-priority behavior defects in REPL/session/pool runtime paths.
     - Existing integration and regression baselines are green before each extraction slice.
   - Exit gates:
     - `repl.py`, `session.py`, and `pool.py` responsibilities are decomposed with stable public entrypoints.
     - Display config contract is explicit and no-op placeholder wiring is removed.
     - Focused parity suites remain green after extraction slices.

6. Post-M4 validation campaign:
   - [POST-M4-VALIDATION-CAMPAIGN-PLAN-2026-03-05.md](/home/inc/repos/NEXUS3/docs/plans/POST-M4-VALIDATION-CAMPAIGN-PLAN-2026-03-05.md)
   - Target window: immediate post-M4 release-candidate validation phase.
   - Dependency gates:
     - M4 implementation gates complete.
     - Candidate build designated for live validation campaign.
   - Exit gates:
     - Soak/perf, Windows-native, TOCTOU-race, and terminal red-team tracks are executed with archived artifacts.
     - Follow-up defects are filed with owners and target windows.
     - Deferred validation tracking section is updated with evidence links.

## Cross-Milestone Dependency Rules

1. Do not start Plan B deprecation work before Plan A + Plan C baseline is stable.
2. Do not flip strict schemas globally before compatibility diagnostics are verified in M1/M2.
3. Do not flip patch defaults to byte_strict before M3 fidelity tests are consistently green.
4. Keep one architecture owner accountable per plan, even when implementation contributors are multiple.
5. Scope M0/M1 to remaining gaps; do not duplicate already-landed path decision/resolver integration.
6. Do not execute Plan H shim retirement until strict-ingress behavior has completed a full stability/compatibility observation window.

## Recommended Team Slice

1. Track A+C under one lead (`Auth/Context lead`) to avoid duplicated context plumbing.
2. Track D+G+H under one lead (`Boundary lead`) because all are ingress/egress hardening.
3. Track E+F under one lead (`Data integrity lead`) due to shared invariants/fidelity concerns.
4. Bring B online only after A+C API surfaces settle.

## Reporting Cadence

- Weekly architecture sync with per-plan status:
- `Not Started`
- `In Progress`
- `Blocked`
- `Ready for Review`
- `Merged`

Required status payload per plan:
- Current phase
- PR links
- Test status
- Known risks
- Next gate date

## Deferred Validation Tracking (Post-M4)

Still required after implementation waves:
1. Execute [POST-M4-VALIDATION-CAMPAIGN-PLAN-2026-03-05.md](/home/inc/repos/NEXUS3/docs/plans/POST-M4-VALIDATION-CAMPAIGN-PLAN-2026-03-05.md) as the canonical closeout runbook.
2. Long soak/performance validation under representative workloads.
3. Windows-native validation on actual Windows hosts.
4. Timing-sensitive TOCTOU/lifecycle race validation under high concurrency.
5. Real terminal red-team validation across emulator variants.

## Related Documents

- [Reviews Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/reviews/README.md)
- [Plans Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/plans/README.md)
- [Canonical Review Master Final](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
- [Architecture Investigation](/home/inc/repos/NEXUS3/docs/plans/ARCH-INVESTIGATION-2026-03-02.md)
- [Architecture Milestone Schedule](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
