#!/usr/bin/env python3
"""Validate Post-M4 campaign closeout gates from archived validation artifacts."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

DEFAULT_ARTIFACT_ROOT = Path("docs/validation")
DEFAULT_SOAK_RUN_ID = "post-m4-20260306-live1b"
DEFAULT_RACE_RUN_ID = "post-m4-20260306-live1c"
DEFAULT_TERMINAL_RUN_ID = "post-m4-20260306-live1d"
DEFAULT_WINDOWS_RUN_ID = "post-m4-20260306-live1b"
DEFAULT_TRACKER_DOC = Path(
    "docs/plans/POST-M4-VALIDATION-FOLLOWUP-TRACKER-2026-03-06.md"
)
TERMINAL_CLOSURE_MARKERS = (
    "manual emulator verification: pass",
    "multi-emulator verification: pass",
)
REQUIRED_TRACKER_IDS = (
    "POSTM4-FU-RACE-001",
    "POSTM4-FU-TERM-001",
    "POSTM4-FU-WIN-001",
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--soak-run-id", type=str, default=DEFAULT_SOAK_RUN_ID)
    parser.add_argument("--race-run-id", type=str, default=DEFAULT_RACE_RUN_ID)
    parser.add_argument("--terminal-run-id", type=str, default=DEFAULT_TERMINAL_RUN_ID)
    parser.add_argument("--windows-run-id", type=str, default=DEFAULT_WINDOWS_RUN_ID)
    parser.add_argument("--tracker-doc", type=Path, default=DEFAULT_TRACKER_DOC)
    parser.add_argument("--json-out", type=Path, default=None)
    return parser.parse_args()


def read_json_object(path: Path) -> tuple[dict[str, Any] | None, str]:
    if not path.is_file():
        return None, f"missing file: {path}"
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"failed to parse json file {path}: {exc}"
    if not isinstance(loaded, dict):
        return None, f"json payload is not an object in {path}"
    return cast(dict[str, Any], loaded), ""


def check_verdict_pass(name: str, verdict_path: Path) -> CheckResult:
    payload, error = read_json_object(verdict_path)
    if payload is None:
        return CheckResult(name=name, passed=False, detail=error)
    pass_value = payload.get("pass")
    if pass_value is True:
        return CheckResult(name=name, passed=True, detail=f"pass=true ({verdict_path})")
    return CheckResult(
        name=name,
        passed=False,
        detail=f"expected pass=true in {verdict_path}, got {pass_value!r}",
    )


def check_windows_summary_pass(summary_path: Path) -> CheckResult:
    payload, error = read_json_object(summary_path)
    if payload is None:
        return CheckResult(name="windows_summary_pass", passed=False, detail=error)
    status = payload.get("status")
    if status == "pass":
        return CheckResult(
            name="windows_summary_pass",
            passed=True,
            detail=f"status=pass ({summary_path})",
        )
    return CheckResult(
        name="windows_summary_pass",
        passed=False,
        detail=f"expected status='pass' in {summary_path}, got {status!r}",
    )


def check_terminal_summary_manual_closure(summary_path: Path) -> CheckResult:
    if not summary_path.is_file():
        return CheckResult(
            name="terminal_manual_emulator_closure",
            passed=False,
            detail=f"missing file: {summary_path}",
        )
    try:
        content = summary_path.read_text(encoding="utf-8")
    except OSError as exc:
        return CheckResult(
            name="terminal_manual_emulator_closure",
            passed=False,
            detail=f"failed to read {summary_path}: {exc}",
        )

    lowered = content.lower()
    for marker in TERMINAL_CLOSURE_MARKERS:
        if marker in lowered:
            return CheckResult(
                name="terminal_manual_emulator_closure",
                passed=True,
                detail=f"found marker '{marker}' ({summary_path})",
            )

    marker_list = ", ".join(repr(marker) for marker in TERMINAL_CLOSURE_MARKERS)
    return CheckResult(
        name="terminal_manual_emulator_closure",
        passed=False,
        detail=(
            f"missing manual emulator closure marker in {summary_path}; "
            f"accepted markers: {marker_list}"
        ),
    )


def extract_tracker_statuses(
    tracker_path: Path, followup_ids: tuple[str, ...]
) -> tuple[dict[str, str], list[str]]:
    if not tracker_path.is_file():
        return {}, [f"missing file: {tracker_path}"]
    try:
        content = tracker_path.read_text(encoding="utf-8")
    except OSError as exc:
        return {}, [f"failed to read {tracker_path}: {exc}"]

    statuses: dict[str, str] = {}
    errors: list[str] = []
    for followup_id in followup_ids:
        section_match = re.search(
            rf"(?ms)^###\s+{re.escape(followup_id)}\s*$([\s\S]*?)(?=^###\s+|\Z)",
            content,
        )
        if section_match is None:
            errors.append(f"missing tracker section: {followup_id}")
            continue
        section_body = section_match.group(1)
        status_match = re.search(
            r"(?mi)^\s*-\s*Status:\s*`?([a-zA-Z0-9_-]+)`?\s*$",
            section_body,
        )
        if status_match is None:
            errors.append(f"missing status line in section: {followup_id}")
            continue
        statuses[followup_id] = status_match.group(1).strip()

    return statuses, errors


def check_tracker_followups_closed(tracker_path: Path) -> CheckResult:
    statuses, errors = extract_tracker_statuses(tracker_path, REQUIRED_TRACKER_IDS)
    if errors:
        return CheckResult(
            name="tracker_followups_closed",
            passed=False,
            detail="; ".join(errors),
        )

    non_closed = {
        followup_id: status
        for followup_id, status in statuses.items()
        if status.lower() != "validation-closed"
    }
    if non_closed:
        details = ", ".join(f"{key}={value!r}" for key, value in sorted(non_closed.items()))
        return CheckResult(
            name="tracker_followups_closed",
            passed=False,
            detail=f"expected validation-closed statuses in {tracker_path}, got: {details}",
        )

    summary = ", ".join(f"{key}={value}" for key, value in sorted(statuses.items()))
    return CheckResult(
        name="tracker_followups_closed",
        passed=True,
        detail=f"all required follow-ups closed ({summary})",
    )


def main() -> int:
    args = parse_args()
    artifact_root = args.artifact_root

    soak_verdict_path = artifact_root / args.soak_run_id / "soak" / "verdict.json"
    race_verdict_path = artifact_root / args.race_run_id / "race" / "verdict.json"
    terminal_verdict_path = artifact_root / args.terminal_run_id / "terminal" / "verdict.json"
    windows_summary_path = artifact_root / args.windows_run_id / "windows" / "summary.json"
    terminal_summary_path = artifact_root / args.terminal_run_id / "terminal" / "summary.md"
    tracker_doc_path = args.tracker_doc

    checks = [
        check_verdict_pass(name="soak_verdict_pass", verdict_path=soak_verdict_path),
        check_verdict_pass(name="race_verdict_pass", verdict_path=race_verdict_path),
        check_verdict_pass(name="terminal_verdict_pass", verdict_path=terminal_verdict_path),
        check_windows_summary_pass(summary_path=windows_summary_path),
        check_terminal_summary_manual_closure(summary_path=terminal_summary_path),
        check_tracker_followups_closed(tracker_path=tracker_doc_path),
    ]

    failed_checks = [f"{check.name}: {check.detail}" for check in checks if not check.passed]
    payload: dict[str, Any] = {
        "pass": len(failed_checks) == 0,
        "failed_checks": failed_checks,
        "checks": [
            {
                "name": check.name,
                "pass": check.passed,
                "detail": check.detail,
            }
            for check in checks
        ],
        "generated_at": utc_now_iso(),
        "config": {
            "artifact_root": str(artifact_root),
            "soak_run_id": args.soak_run_id,
            "race_run_id": args.race_run_id,
            "terminal_run_id": args.terminal_run_id,
            "windows_run_id": args.windows_run_id,
            "tracker_doc": str(tracker_doc_path),
            "paths": {
                "soak_verdict": str(soak_verdict_path),
                "race_verdict": str(race_verdict_path),
                "terminal_verdict": str(terminal_verdict_path),
                "windows_summary": str(windows_summary_path),
                "terminal_summary": str(terminal_summary_path),
            },
        },
    }

    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
