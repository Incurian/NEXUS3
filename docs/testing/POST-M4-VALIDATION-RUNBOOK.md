# Post-M4 Validation Runbook

## Purpose

This is the canonical execution runbook for the Post-M4 validation campaign:

1. Soak/performance
2. Windows-native
3. TOCTOU/lifecycle race
4. Terminal red-team

All runs must write artifacts under `docs/validation/<run-id>/`.

## Prerequisites

1. Start from a candidate branch/commit with M4 implementation gates green.
2. Use the project virtualenv executables only.
3. Run preflight quality gates:

```bash
.venv/bin/ruff check nexus3/
.venv/bin/mypy nexus3/
.venv/bin/pytest tests/unit -q
.venv/bin/pytest tests/security -q
```

4. Ensure an RPC server is available for soak/race tracks:

```bash
NEXUS_DEV=1 .venv/bin/python -m nexus3 --serve 9000
```

## Run ID and Artifact Contract

Use one run id per campaign execution window (example: `post-m4-20260306-a`).

Required for automated tracks (`soak`, `race`, `terminal`):

- `metadata.json`: immutable run config + environment metadata.
- `commands.log`: attempted command transcript.
- `events.jsonl`: structured event stream per operation/check.
- `summary.md`: human-readable summary and repro command.
- `verdict.json`: machine-readable pass/fail verdict + failed checks.

Required for the Windows manual track (`windows`):

- `metadata.json`: host/build/shell metadata.
- `checklist.md`: pass/fail checklist by section.
- `summary.json`: overall verdict/counters.
- `notes.md`: caveats and reproduction notes.

Optional per track:

- `summary.json`: compact counters/status snapshot (present in
  soak/race/terminal).
- `failures.log`: failure excerpts and reproduction details.
- track-specific notes/checklists.

Expected layout:

```text
docs/validation/<run-id>/
  soak/
    metadata.json
    commands.log
    events.jsonl
    summary.md
    verdict.json
    summary.json
    failures.log (optional)
  race/
    metadata.json
    commands.log
    events.jsonl
    summary.md
    verdict.json
    summary.json
    failures.log (optional)
  terminal/
    metadata.json
    commands.log
    events.jsonl
    summary.md
    verdict.json
    summary.json
    failures.log (optional)
  windows/
    metadata.json
    checklist.md
    summary.json
    notes.md
  findings.md
  issue-links.md
```

## Track 1: Soak/Performance

Script:

```bash
.venv/bin/python scripts/validation/soak_workload.py \
  --run-id post-m4-20260306-a \
  --port 9000 \
  --duration-seconds 3600
```

Pass gate (default target):

- No crashes or stuck commands.
- Failure rate <= 1% (`verdict.json.failed_checks` does not include
  failure-rate threshold breach).
- No uninvestigated entries in `failures.log` (if present).

## Track 2: Windows-Native

Manual validation is executed on real Windows hosts using:

- `docs/testing/WINDOWS-LIVE-TESTING-GUIDE.md`

Required artifact outputs under `docs/validation/<run-id>/windows/`:

- `metadata.json` (host, OS build, shell).
- `checklist.md` (pass/fail by section).
- `summary.json` (overall verdict).
- `notes.md` (known caveats + reproduction steps).

Pass gate:

- All required checklist sections pass on at least one supported Windows host.
- Any failures have reproducible steps recorded.

## Track 3: TOCTOU/Lifecycle Race

Script:

```bash
.venv/bin/python scripts/validation/race_harness.py \
  --artifact-root docs/validation \
  --run-id post-m4-20260306-a \
  --port 9000 \
  --workers 8 \
  --rounds 20
```

Pass gate:

- `verdict.json.pass == true`.
- No authorization/state-integrity violations in failures.
- All timeouts investigated and documented.

## Track 4: Terminal Red-Team

Script (matrix artifact generation):

```bash
.venv/bin/python scripts/validation/terminal_payload_matrix.py \
  --artifact-root docs/validation \
  --run-id post-m4-20260306-a
```

Pass gate:

- No successful control-sequence spoofing in script verdict + emulator follow-up.
- `summary.md` captures any manual emulator follow-up required by payload class.
- Any failure includes screenshot/transcript and owner assignment.

## Campaign Closeout

After all four tracks complete:

1. Create `docs/validation/<run-id>/findings.md` with severity + owner + target window.
2. Create `docs/validation/<run-id>/issue-links.md` with issue/plan references.
3. Update:
   - `docs/plans/POST-M4-VALIDATION-CAMPAIGN-PLAN-2026-03-05.md`
   - `docs/plans/ARCH-MILESTONE-SCHEDULE-2026-03-02.md`
   - `AGENTS.md` running status

4. Mark deferred validation backlog items closed only with artifact evidence links.
