#!/usr/bin/env python3
"""Evaluate terminal payload sanitization matrix and archive run artifacts."""

from __future__ import annotations

import argparse
import json
import platform
import re
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nexus3.core.text_safety import sanitize_for_display

TRACK = "terminal"
DISALLOWED_CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass(frozen=True)
class PayloadCase:
    name: str
    description: str
    payload: str
    required_substrings: tuple[str, ...]
    forbidden_substrings: tuple[str, ...]
    manual_follow_up: bool = False


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_utc(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def make_run_id(track: str, provided: str | None) -> str:
    if provided:
        return provided
    timestamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    return f"{track}-{timestamp}"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_line(path: Path, line: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.write("\n")


def append_jsonl(path: Path, event: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True))
        handle.write("\n")


def evaluate_case(case: PayloadCase) -> dict[str, Any]:
    sanitized = sanitize_for_display(case.payload)
    failed_checks: list[str] = []
    warnings: list[str] = []

    for token in case.required_substrings:
        if token not in sanitized:
            failed_checks.append(f"missing required token: {token!r}")
    for token in case.forbidden_substrings:
        if token in sanitized:
            failed_checks.append(f"forbidden token retained: {token!r}")
    if "\x1b" in sanitized:
        failed_checks.append("escape byte (\\x1b) retained after sanitization")
    if DISALLOWED_CONTROL_PATTERN.search(sanitized):
        failed_checks.append("disallowed control character retained after sanitization")

    if case.manual_follow_up and "\r" in sanitized:
        warnings.append("contains carriage return; requires live emulator verification")

    passed = len(failed_checks) == 0
    return {
        "name": case.name,
        "description": case.description,
        "payload_repr": repr(case.payload),
        "sanitized_repr": repr(sanitized),
        "passed": passed,
        "manual_follow_up": case.manual_follow_up,
        "failed_checks": failed_checks,
        "warnings": warnings,
    }


def payload_cases() -> tuple[PayloadCase, ...]:
    return (
        PayloadCase(
            name="ansi-color",
            description="strip CSI color escapes",
            payload="\x1b[31mALERT\x1b[0m",
            required_substrings=("ALERT",),
            forbidden_substrings=("\x1b[31m", "\x1b[0m"),
        ),
        PayloadCase(
            name="osc-title",
            description="strip OSC title payloads",
            payload="\x1b]2;owned-title\x07visible",
            required_substrings=("visible",),
            forbidden_substrings=("\x1b]", "\x07"),
        ),
        PayloadCase(
            name="csi-clear",
            description="strip clear-screen control sequences",
            payload="prefix\x1b[2Jsuffix",
            required_substrings=("prefixsuffix",),
            forbidden_substrings=("\x1b[2J",),
        ),
        PayloadCase(
            name="rich-markup",
            description="escape rich markup brackets",
            payload="[bold red]boom[/bold red]",
            required_substrings=("\\[bold red]boom\\[/bold red]",),
            forbidden_substrings=("[bold red]boom[/bold red]",),
        ),
        PayloadCase(
            name="mixed-ansi-and-markup",
            description="sanitize mixed ANSI + rich markup payload",
            payload="\x1b[31m[red]boom[/red]\x1b[0m",
            required_substrings=("\\[red]boom\\[/red]",),
            forbidden_substrings=("\x1b", "[red]boom[/red]"),
        ),
        PayloadCase(
            name="control-bytes",
            description="strip C0 controls except documented safe set",
            payload="A\x00B\x07C\x1fD",
            required_substrings=("ABCD",),
            forbidden_substrings=("\x00", "\x07", "\x1f"),
        ),
        PayloadCase(
            name="carriage-return",
            description="carriage return handling requires terminal follow-up",
            payload="stable\roverwrite",
            required_substrings=("stable\roverwrite",),
            forbidden_substrings=("\x1b",),
            manual_follow_up=True,
        ),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        "--artifact-root",
        dest="output_root",
        type=Path,
        default=Path("docs/validation"),
    )
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = make_run_id(TRACK, args.run_id)
    run_dir = args.output_root / run_id / TRACK
    run_dir.mkdir(parents=True, exist_ok=True)

    commands_path = run_dir / "commands.log"
    events_path = run_dir / "events.jsonl"
    summary_path = run_dir / "summary.md"
    summary_json_path = run_dir / "summary.json"
    verdict_path = run_dir / "verdict.json"
    metadata_path = run_dir / "metadata.json"

    started = utc_now()
    append_line(
        commands_path,
        f"{iso_utc(started)} | evaluate terminal payload matrix | dry_run={args.dry_run}",
    )

    results = [evaluate_case(case) for case in payload_cases()]
    for result in results:
        append_jsonl(
            events_path,
            {
                "timestamp": iso_utc(utc_now()),
                "operation": "payload_check",
                "status": "ok" if result["passed"] else "error",
                "duration_seconds": 0.0,
                "details": result,
            },
        )

    strict_failures = [
        result
        for result in results
        if (not result["passed"]) and (not result["manual_follow_up"])
    ]
    manual_follow_ups = [result for result in results if result["manual_follow_up"]]
    failed_checks: list[str] = []
    warnings: list[str] = []

    for result in strict_failures:
        for reason in result["failed_checks"]:
            failed_checks.append(f"{result['name']}: {reason}")
    for result in manual_follow_ups:
        for warning in result["warnings"]:
            warnings.append(f"{result['name']}: {warning}")

    if args.dry_run:
        warnings.append("dry-run mode enabled: strict failure checks are informational")
        failed_checks = []

    finished = utc_now()

    metadata: dict[str, Any] = {
        "run_id": run_id,
        "track": TRACK,
        "started_at": iso_utc(started),
        "finished_at": iso_utc(finished),
        "duration_seconds": max(0.0, (finished - started).total_seconds()),
        "tool_version": "post-m4-validation-v1",
        "git": {"branch": "feat/arch-overhaul-execution", "commit": "unknown"},
        "environment": {
            "os": platform.platform(),
            "python": platform.python_version(),
            "hostname": socket.gethostname(),
        },
        "config": {
            "output_root": str(args.output_root),
            "case_count": len(results),
            "dry_run": args.dry_run,
        },
        "counts": {
            "total_cases": len(results),
            "strict_failures": len(strict_failures),
            "manual_follow_up_cases": len(manual_follow_ups),
        },
    }
    write_json(metadata_path, metadata)

    verdict = {
        "pass": len(failed_checks) == 0,
        "failed_checks": failed_checks,
        "warnings": warnings,
        "highlights": [
            f"total_cases={len(results)}",
            f"strict_failures={len(strict_failures)}",
            f"manual_follow_up_cases={len(manual_follow_ups)}",
        ],
        "generated_at": iso_utc(utc_now()),
    }
    write_json(verdict_path, verdict)
    write_json(
        summary_json_path,
        {
            "status": "pass" if verdict["pass"] else "fail",
            "dry_run": args.dry_run,
            "duration_seconds": max(0.0, (finished - started).total_seconds()),
            "total_cases": len(results),
            "strict_failures": len(strict_failures),
            "manual_follow_up_cases": len(manual_follow_ups),
        },
    )

    summary_lines = [
        f"# Terminal Validation Summary: `{run_id}`",
        "",
        "## Matrix Results",
        "| Case | Result | Manual Follow-Up |",
        "| --- | --- | --- |",
    ]
    for result in results:
        status = "PASS" if result["passed"] else "FAIL"
        follow_up = "yes" if result["manual_follow_up"] else "no"
        summary_lines.append(f"| `{result['name']}` | {status} | {follow_up} |")

    summary_lines.extend(
        [
            "",
            "## Verdict",
            f"- pass: {verdict['pass']}",
            f"- strict failures: {len(strict_failures)}",
            f"- manual follow-up cases: {len(manual_follow_ups)}",
        ]
    )
    if failed_checks:
        summary_lines.extend(["", "### Failed checks"])
        summary_lines.extend([f"- {check}" for check in failed_checks])
    if warnings:
        summary_lines.extend(["", "### Warnings"])
        summary_lines.extend([f"- {warning}" for warning in warnings])
    summary_lines.extend(
        [
            "",
            "## Reproduction Command",
            "```bash",
            ".venv/bin/python scripts/validation/terminal_payload_matrix.py "
            f"--output-root {args.output_root}",
            "```",
        ]
    )
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    print(f"artifact_dir={run_dir}")
    print(f"pass={verdict['pass']}")
    return 0 if verdict["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
