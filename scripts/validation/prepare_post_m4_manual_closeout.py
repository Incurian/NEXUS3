#!/usr/bin/env python3
"""Scaffold and validate manual Post-M4 closeout handoff artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from textwrap import dedent
from typing import Any

DEFAULT_ARTIFACT_ROOT = Path("docs/validation")
DEFAULT_WINDOWS_SOURCE_RUN_ID = "post-m4-20260306-live1b"
DEFAULT_TERMINAL_SOURCE_RUN_ID = "post-m4-20260306-live1d"
DEFAULT_RACE_SOURCE_RUN_ID = "post-m4-20260306-live1c"
TERMINAL_TODO_MARKER = "TODO: Manual emulator verification: **PASS**"
TERMINAL_CLOSURE_MARKERS = (
    "Manual emulator verification: PASS",
    "Multi-emulator verification: PASS",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--run-id", type=str, required=True)
    parser.add_argument(
        "--windows-source-run-id",
        type=str,
        default=DEFAULT_WINDOWS_SOURCE_RUN_ID,
    )
    parser.add_argument(
        "--terminal-source-run-id",
        type=str,
        default=DEFAULT_TERMINAL_SOURCE_RUN_ID,
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if not args.run_id.strip():
        parser.error("--run-id must not be empty")
    return args


def json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def windows_metadata_template(run_id: str, source_run_id: str) -> str:
    return json_text(
        {
            "track": "windows",
            "run_id": run_id,
            "started_at": "TBD",
            "finished_at": "TBD",
            "duration_seconds": 0.0,
            "config": {
                "execution_mode": "pending_real_host",
                "runbook": "docs/testing/WINDOWS-LIVE-TESTING-GUIDE.md",
                "source_run_id": source_run_id,
            },
            "environment": {
                "host": "TBD-real-windows-host",
                "notes": (
                    "Pending real-host execution. Replace placeholders after running "
                    "the Windows live testing guide."
                ),
            },
        }
    )


def windows_checklist_template(run_id: str) -> str:
    return dedent(
        f"""\
        # Windows Track Checklist: {run_id}

        Status: pending real-host execution

        - [ ] Process termination utility checks (Part 1)
        - [ ] ESC key detection checks (Part 2)
        - [ ] BOM handling checks (Part 3)
        - [ ] Environment variable safe-list checks (Part 4)
        - [ ] Subprocess/cancellation behavior checks
        - [ ] CLI/terminal behavior checks

        Reference:
        - [WINDOWS-LIVE-TESTING-GUIDE.md](docs/testing/WINDOWS-LIVE-TESTING-GUIDE.md)
        """
    )


def windows_summary_template() -> str:
    return json_text(
        {
            "status": "pending_real_host",
            "dry_run": False,
            "duration_seconds": 0.0,
            "required_sections_total": 6,
            "required_sections_passed": 0,
            "required_sections_failed": 0,
            "required_sections_pending": 6,
        }
    )


def windows_notes_template(run_id: str) -> str:
    return dedent(
        f"""\
        # Windows Track Notes: {run_id}

        - Pending real-host execution.
        - No Windows-native assertions are closed in this scaffold.
        - Next action: run `docs/testing/WINDOWS-LIVE-TESTING-GUIDE.md` on a
          real Windows host and replace this placeholder with real results.
        """
    )


def terminal_summary_template(run_id: str, source_run_id: str) -> str:
    return dedent(
        f"""\
        # Terminal Manual Follow-Up: `{run_id}`

        ## Scope
        - Capture live multi-emulator carriage-return verification notes here.
        - Automated baseline source run: `{source_run_id}`.

        ## Manual Verification Closure
        - {TERMINAL_TODO_MARKER}
        - Replace the TODO line above with a non-TODO closure line after live
          verification (`PASS` or `FAIL`).
        """
    )


def handoff_note_template(
    artifact_root: Path,
    run_id: str,
    windows_source_run_id: str,
    terminal_source_run_id: str,
) -> str:
    closeout_json = artifact_root / run_id / "closeout-gate.json"
    return dedent(
        f"""\
        # Post-M4 Manual Closeout Handoff: `{run_id}`

        1. Run the Windows guide on a real Windows host and update:
           `windows/metadata.json`, `windows/checklist.md`, `windows/summary.json`,
           and `windows/notes.md`.
           Reference: `docs/testing/WINDOWS-LIVE-TESTING-GUIDE.md`
        2. Run live multi-emulator carriage-return verification and replace the
           TODO marker in `terminal/summary.md` with a real `PASS`/`FAIL` result.
           Mirror the final closure marker into
           `{artifact_root / terminal_source_run_id / "terminal" / "summary.md"}`
           because the closeout gate reads that terminal run id.
        3. Update tracker statuses in
           `docs/plans/POST-M4-VALIDATION-FOLLOWUP-TRACKER-2026-03-06.md` after
           linking evidence for terminal and Windows follow-ups.
        4. Run the closeout gate with explicit run ids:

        ```bash
        .venv/bin/python scripts/validation/post_m4_closeout_gate.py \
          --artifact-root {artifact_root} \
          --soak-run-id {windows_source_run_id} \
          --race-run-id {DEFAULT_RACE_SOURCE_RUN_ID} \
          --terminal-run-id {terminal_source_run_id} \
          --windows-run-id {run_id} \
          --json-out {closeout_json}
        ```
        """
    )


def ensure_text_file(path: Path, content: str, force: bool) -> str:
    if path.exists() and path.is_dir():
        raise IsADirectoryError(f"expected file path but found directory: {path}")
    existed = path.exists()
    if existed and not force:
        return "unchanged"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return "updated" if existed else "created"


def terminal_marker_validation(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "exists": False,
            "has_todo_marker": False,
            "has_plain_closure_marker": False,
        }
    content = path.read_text(encoding="utf-8")
    lowered = content.lower()
    return {
        "exists": True,
        "has_todo_marker": TERMINAL_TODO_MARKER.lower() in lowered,
        "has_plain_closure_marker": any(
            marker.lower() in lowered for marker in TERMINAL_CLOSURE_MARKERS
        ),
    }


def source_validation(
    artifact_root: Path, windows_source_run_id: str, terminal_source_run_id: str
) -> dict[str, bool]:
    return {
        "windows_source_summary_exists": (
            artifact_root / windows_source_run_id / "windows" / "summary.json"
        ).is_file(),
        "terminal_source_summary_exists": (
            artifact_root / terminal_source_run_id / "terminal" / "summary.md"
        ).is_file(),
        "terminal_source_verdict_exists": (
            artifact_root / terminal_source_run_id / "terminal" / "verdict.json"
        ).is_file(),
    }


def prepare_artifacts(args: argparse.Namespace) -> dict[str, Any]:
    artifact_root: Path = args.artifact_root
    run_id: str = args.run_id
    run_dir = artifact_root / run_id

    run_dir_preexisted = run_dir.exists()
    run_dir.mkdir(parents=True, exist_ok=True)

    windows_dir = run_dir / "windows"
    terminal_dir = run_dir / "terminal"
    managed_files: tuple[tuple[Path, str], ...] = (
        (
            windows_dir / "metadata.json",
            windows_metadata_template(
                run_id=run_id, source_run_id=args.windows_source_run_id
            ),
        ),
        (windows_dir / "checklist.md", windows_checklist_template(run_id=run_id)),
        (windows_dir / "summary.json", windows_summary_template()),
        (windows_dir / "notes.md", windows_notes_template(run_id=run_id)),
        (
            terminal_dir / "summary.md",
            terminal_summary_template(
                run_id=run_id,
                source_run_id=args.terminal_source_run_id,
            ),
        ),
        (
            run_dir / "closeout-handoff.md",
            handoff_note_template(
                artifact_root=artifact_root,
                run_id=run_id,
                windows_source_run_id=args.windows_source_run_id,
                terminal_source_run_id=args.terminal_source_run_id,
            ),
        ),
    )

    created_files: list[str] = []
    updated_files: list[str] = []
    unchanged_files: list[str] = []
    for path, content in managed_files:
        action = ensure_text_file(path=path, content=content, force=args.force)
        file_label = str(path)
        if action == "created":
            created_files.append(file_label)
        elif action == "updated":
            updated_files.append(file_label)
        else:
            unchanged_files.append(file_label)

    terminal_summary_path = terminal_dir / "summary.md"
    source_checks = source_validation(
        artifact_root=artifact_root,
        windows_source_run_id=args.windows_source_run_id,
        terminal_source_run_id=args.terminal_source_run_id,
    )
    validation: dict[str, Any] = {
        "required_windows_files_present": all(
            (windows_dir / name).is_file()
            for name in ("metadata.json", "checklist.md", "summary.json", "notes.md")
        ),
        "terminal_summary": terminal_marker_validation(terminal_summary_path),
        "sources": source_checks,
    }

    warnings: list[str] = []
    if not source_checks["windows_source_summary_exists"]:
        warnings.append(
            "windows source summary is missing; verify --windows-source-run-id"
        )
    if not source_checks["terminal_source_summary_exists"]:
        warnings.append(
            "terminal source summary is missing; verify --terminal-source-run-id"
        )
    if not source_checks["terminal_source_verdict_exists"]:
        warnings.append(
            "terminal source verdict is missing; verify --terminal-source-run-id"
        )

    return {
        "status": "ok",
        "run_id": run_id,
        "artifact_root": str(artifact_root),
        "run_dir": str(run_dir),
        "run_dir_preexisted": run_dir_preexisted,
        "force": args.force,
        "source_run_ids": {
            "windows": args.windows_source_run_id,
            "race": DEFAULT_RACE_SOURCE_RUN_ID,
            "terminal": args.terminal_source_run_id,
        },
        "created_files": created_files,
        "updated_files": updated_files,
        "unchanged_files": unchanged_files,
        "validation": validation,
        "warnings": warnings,
    }


def main() -> int:
    args = parse_args()
    try:
        payload = prepare_artifacts(args)
    except OSError as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "run_id": args.run_id,
                    "artifact_root": str(args.artifact_root),
                    "error": str(exc),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
