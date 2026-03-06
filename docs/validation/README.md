# Validation Artifacts

This directory stores execution artifacts for the Post-M4 validation campaign.

## Directory Rules

1. Use one folder per run id: `docs/validation/<run-id>/`.
2. Never overwrite historical runs.
3. Keep raw evidence (logs/transcripts/checklists) with each run.

## Minimum Artifact Schema

Automated track folders (`soak`, `race`, `terminal`) must contain:

- `metadata.json`
- `commands.log`
- `events.jsonl`
- `summary.md`
- `verdict.json`

Windows manual track folder (`windows`) must contain:

- `metadata.json`
- `checklist.md`
- `summary.json`
- `notes.md`

Recommended:

- `summary.json` (compact counters/status snapshot; currently present in
  soak/race/terminal scripts)
- `failures.log` with reproduction details and environment notes.

Top-level run folder should include:

- `findings.md`
- `issue-links.md`

## `metadata.json` Contract

Required keys:

- `track`: track name (`soak`, `race`, `terminal`, or `windows`)
- `run_id`
- `started_at`
- `finished_at`
- `duration_seconds`
- `config` object
- `environment` object

## `verdict.json` Contract (Automated Tracks)

Required keys:

- `pass`: boolean
- `failed_checks`: string list
- `warnings`: string list
- `highlights`: string list
- `generated_at`

## `summary.json` Contract

Required for Windows manual track and recommended for automated tracks.
When present, include:

- `status`: `pass` or `fail`
- `duration_seconds`
- track counters (attempts/success/failures or equivalent)
- `dry_run`

## Example Layout

```text
docs/validation/post-m4-20260306-a/
  soak/
    metadata.json
    commands.log
    events.jsonl
    summary.md
    verdict.json
    summary.json
  race/
    metadata.json
    commands.log
    events.jsonl
    summary.md
    verdict.json
    summary.json
  terminal/
    metadata.json
    commands.log
    events.jsonl
    summary.md
    verdict.json
    summary.json
  windows/
    metadata.json
    checklist.md
    summary.json
    notes.md
  findings.md
  issue-links.md
```

## Script Entry Points

Use the campaign scripts in `scripts/validation/`:

- `soak_workload.py`
- `race_harness.py`
- `terminal_payload_matrix.py`

For full execution and pass/fail criteria, use:

- `docs/testing/POST-M4-VALIDATION-RUNBOOK.md`
