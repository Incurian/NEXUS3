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
- Plan F Phase 7 committed as `6e946cf`:
  - runtime legacy patch-skill apply path retired; patch now always executes via AST-v2 + byte-strict applier
  - `fidelity_mode=legacy` now fails fast with explicit migration guidance
- Plan E Phase 1 committed as `e9d6c3e`:
  - added `nexus3/context/compiler.py` typed compiler IR + invariant checker
  - added `tests/unit/context/test_compiler.py` for fixture parity, diagnostics, and invariant-report regressions
  - exported compiler interfaces in `nexus3/context/__init__.py`
- Plan E Phase 2 committed as `e3cd304`:
  - migrated session preflight repair to compiler-backed normalization with
    persisted repaired history update in `nexus3/session/session.py` /
    `nexus3/context/manager.py`
  - routed Anthropic/OpenAI request shaping through compiler output
    (`nexus3/provider/anthropic.py`, `nexus3/provider/openai_compat.py`)
  - retired Anthropic-local orphan synthesis in `_convert_messages(...)`
  - added focused regressions in
    `tests/unit/session/test_session_cancellation.py` and
    `tests/unit/provider/test_compiler_integration.py`
- Plan E Phase 3 committed as `5632652`:
  - added compiler-backed graph prototype in `nexus3/context/graph.py`
    (typed edges + tool-batch atomic groups)
  - exported graph interfaces in `nexus3/context/__init__.py`
  - added focused graph regressions in `tests/unit/context/test_graph.py`
- Plan E Phase 4 committed as `00c59ed`:
  - migrated truncation grouping in `nexus3/context/manager.py` to
    compiler/graph-derived atomic groups
  - migrated compaction selection in `nexus3/context/compaction.py` to
    compiler-normalized atomic-group preservation
  - added focused compaction/truncation regressions in
    `tests/unit/test_compaction.py` and `tests/unit/test_context_manager.py`
- Plan B Phase 1 committed as `14bc820`:
  - added `nexus3/core/capabilities.py` (signed capability claims +
    issue/verify + revocation/replay primitives)
  - exported capability APIs in `nexus3/core/__init__.py`
  - added focused capability regressions in `tests/unit/core/test_capabilities.py`
- Plan B Phase 2 committed as `43773be`:
  - integrated capability verification into direct in-process dispatch
    boundaries in `nexus3/rpc/dispatcher.py` and
    `nexus3/rpc/global_dispatcher.py`
  - added pool-owned direct capability issue/verify/revoke lifecycle in
    `nexus3/rpc/pool.py`
  - migrated `nexus3/rpc/agent_api.py` direct calls to attach per-call
    capability tokens (compat requester_id retained)
  - added focused regressions in `tests/unit/test_agent_api.py`,
    `tests/unit/test_rpc_dispatcher.py`, `tests/unit/test_global_dispatcher.py`,
    `tests/unit/test_pool.py`, and `tests/unit/core/test_request_context.py`
- Plan B Phase 3A committed as `6b65b17`:
  - HTTP ingress now forwards optional `X-Nexus-Capability` as dispatch
    `capability_token` on global and `/agent/{id}` routes
  - client supports explicit optional `X-Nexus-Capability` emission
  - focused HTTP/client capability transport regressions are green
- Plan B Phase 4B completed as `ffb8b87`:
  - HTTP ingress enforces capability-first requester identity semantics
  - `X-Nexus-Capability` is required whenever `X-Nexus-Agent` is sent
  - requester-only `X-Nexus-Agent` is rejected with deterministic `INVALID_PARAMS`
- Plan G Phase 4 closeout completed (2026-03-06, local pending commit):
  - no residual SafeSink bypasses found in final display/CLI audit for scoped
    surfaces.
  - grep ripgrep fast path now enforces size-limit parity with secure
    expectations and preserves context match markers for consistent output.
  - MCP/test expectation drift and destroy-authorization security parity tests
    aligned with current kernel-authoritative behavior.
- M4 quality and live gates are green (2026-03-06 local snapshot):
  - `.venv/bin/ruff check nexus3/` passed.
  - `.venv/bin/mypy nexus3/` passed.
  - `.venv/bin/pytest tests/ -v` passed (`4102 passed`, `3 skipped`).
  - `.venv/bin/pytest tests/integration/ -v` passed (`211 passed`, `2 skipped`).
  - live RPC create/send/destroy validation on `:9000` passed.
- Next target: close remaining post-M4 validation findings by:
  - executing Windows-native checklist on a real Windows host with artifacts.
  - completing terminal emulator follow-up for carriage-return handling.

### M4: Delegation and Strategic Evolution

Target scope:
- Plan B Phases 1-4 (capability tokens in-process, optional HTTP, remove legacy identity path)
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
  - Status note (2026-03-06): execution slices complete:
    - Phase 1 baseline (typed create-context model foundation + pool wiring).
    - Phase 2/3 follow-on (adapter-local grant evaluation from typed context,
      `parent_can_grant` precompute removed from pool call sites, focused
      adapter-authoritative regressions added).
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

Status note (2026-03-06):
- Post-M4 validation campaign bootstrap is completed:
  - added canonical runbook:
    `docs/testing/POST-M4-VALIDATION-RUNBOOK.md`
  - added artifact schema/index:
    `docs/validation/README.md`
  - added campaign harness scripts:
    `scripts/validation/soak_workload.py`,
    `scripts/validation/race_harness.py`,
    `scripts/validation/terminal_payload_matrix.py`
- Next deferred-validation gate is closure of remaining manual tracks:
  Windows real-host validation and terminal emulator follow-up evidence.

Status note (2026-03-06, later):
- First live execution slice recorded under
  `docs/validation/post-m4-20260306-live1b/`.
- Track outcomes:
  - soak: pass
  - race: fail on failure-rate threshold (`13.333%`), with
    `security_failures=0`
  - terminal: pass with manual carriage-return emulator follow-up warning
  - windows: pending real-host execution (placeholder artifact set recorded)
- Findings and follow-up placeholders:
  - `docs/validation/post-m4-20260306-live1b/findings.md`
  - `docs/validation/post-m4-20260306-live1b/issue-links.md`
- Race follow-up status:
  - contention-aware follow-up run
    `docs/validation/post-m4-20260306-live1c/race/verdict.json` passed
    (`security_failures=0`, raw contention failures recorded separately).

Status note (2026-03-06, latest):
- Terminal follow-up refresh run recorded under
  `docs/validation/post-m4-20260306-live1d/terminal/`:
  - `verdict.json`: pass, `strict_failures=0`
  - `summary.json`: `manual_follow_up_cases=1` (`carriage-return`)
- Current deferred-validation closeout remains open on:
  - Windows real-host track execution + artifact evidence.
  - Live multi-emulator carriage-return verification evidence.
- Canonical follow-up mapping is now tracked in
  [POST-M4-VALIDATION-FOLLOWUP-TRACKER-2026-03-06.md](/home/inc/repos/NEXUS3/docs/plans/POST-M4-VALIDATION-FOLLOWUP-TRACKER-2026-03-06.md).

Status note (2026-03-06, gate tooling):
- Added deterministic closeout checker:
  `scripts/validation/post_m4_closeout_gate.py`.
- Added manual closeout prep scaffolder:
  `scripts/validation/prepare_post_m4_manual_closeout.py`.
- CI lint/type coverage now includes `scripts/validation/` and explicit mypy
  checks for closeout tooling scripts.
- Current gate snapshot:
  - `.venv/bin/python scripts/validation/post_m4_closeout_gate.py --json-out /tmp/post-m4-closeout-gate-20260306.json` reports open checks for:
    - Windows summary status (`pending_real_host`).
    - Terminal manual emulator closure marker.
    - Tracker statuses for `POSTM4-FU-TERM-001` and `POSTM4-FU-WIN-001` (`open`).

Status note (2026-03-06, external closeout):
- Real-host Windows and multi-emulator terminal follow-up execution completed
  under `docs/validation/post-m4-20260306-live1e/`.
- Windows track is closed with pass status:
  - `docs/validation/post-m4-20260306-live1e/windows/summary.json`
- Terminal carriage-return follow-up is closed with explicit marker + evidence:
  - `docs/validation/post-m4-20260306-live1d/terminal/summary.md`
  - `docs/validation/post-m4-20260306-live1e/terminal/summary.md`
  - `docs/validation/post-m4-20260306-live1e/terminal/multi-shell-carriage-return-evidence.json`
- Follow-up tracker statuses for `POSTM4-FU-TERM-001` and
  `POSTM4-FU-WIN-001` are now `validation-closed` in
  [POST-M4-VALIDATION-FOLLOWUP-TRACKER-2026-03-06.md](/home/inc/repos/NEXUS3/docs/plans/POST-M4-VALIDATION-FOLLOWUP-TRACKER-2026-03-06.md).
- Deterministic closeout gate passes with explicit run ids and archived output:
  - `docs/validation/post-m4-20260306-live1e/closeout-gate.json`

## Related Documents

- [Reviews Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/reviews/README.md)
- [Plans Index (2026-03-02)](/home/inc/repos/NEXUS3/docs/plans/README.md)
- [Canonical Review Master Final](/home/inc/repos/NEXUS3/docs/reviews/CODEX-NEXUS3-REVIEW-MASTER-FINAL-2026-03-02.md)
- [Architecture Investigation](/home/inc/repos/NEXUS3/docs/plans/ARCH-INVESTIGATION-2026-03-02.md)
- [Architecture Milestone Schedule](/home/inc/repos/NEXUS3/docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md)
