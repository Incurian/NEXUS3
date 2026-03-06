#!/usr/bin/env python3
"""Run sustained RPC workload and archive artifacts for post-M4 soak validation."""

from __future__ import annotations

import argparse
import json
import platform
import shlex
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TRACK = "soak"


@dataclass(frozen=True)
class CommandOutcome:
    operation: str
    command: list[str]
    started_at: str
    finished_at: str
    duration_seconds: float
    returncode: int
    stdout_tail: str
    stderr_tail: str
    skipped: bool


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_utc(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def make_run_id(track: str, provided: str | None) -> str:
    if provided:
        return provided
    timestamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    return f"{track}-{timestamp}"


def tail_text(value: str, limit: int = 400) -> str:
    trimmed = value.strip()
    if len(trimmed) <= limit:
        return trimmed
    return trimmed[-limit:]


def coerce_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


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


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    left = int(position)
    right = min(left + 1, len(ordered) - 1)
    weight = position - left
    return ordered[left] * (1.0 - weight) + ordered[right] * weight


def run_command(
    command: list[str],
    operation: str,
    timeout_seconds: float,
    dry_run: bool,
) -> CommandOutcome:
    started = utc_now()
    if dry_run:
        finished = utc_now()
        return CommandOutcome(
            operation=operation,
            command=command,
            started_at=iso_utc(started),
            finished_at=iso_utc(finished),
            duration_seconds=0.0,
            returncode=0,
            stdout_tail="",
            stderr_tail="",
            skipped=True,
        )

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        returncode = completed.returncode
        stdout_tail = tail_text(completed.stdout)
        stderr_tail = tail_text(completed.stderr)
    except subprocess.TimeoutExpired as exc:
        returncode = 124
        stdout_tail = tail_text(coerce_text(exc.stdout))
        stderr_tail = f"timeout after {timeout_seconds:.1f}s"
    finished = utc_now()
    return CommandOutcome(
        operation=operation,
        command=command,
        started_at=iso_utc(started),
        finished_at=iso_utc(finished),
        duration_seconds=max(0.0, (finished - started).total_seconds()),
        returncode=returncode,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
        skipped=False,
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
    parser.add_argument("--python-bin", type=str, default=".venv/bin/python")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--duration-seconds", type=int, default=None)
    parser.add_argument("--agent-prefix", type=str, default="postm4-soak")
    parser.add_argument(
        "--message",
        type=str,
        default="Reply with OK and your agent id in one short sentence.",
    )
    parser.add_argument("--send-timeout", type=int, default=90)
    parser.add_argument("--command-timeout", type=float, default=120.0)
    parser.add_argument("--pause-seconds", type=float, default=0.0)
    parser.add_argument("--max-failure-rate", type=float, default=0.01)
    parser.add_argument("--max-send-p50-seconds", type=float, default=10.0)
    parser.add_argument("--max-send-p95-seconds", type=float, default=20.0)
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
    started_monotonic = time.monotonic()
    deadline = None
    if args.duration_seconds is not None:
        deadline = started_monotonic + max(0, args.duration_seconds)

    outcomes: list[CommandOutcome] = []
    send_latencies: list[float] = []

    for index in range(args.iterations):
        if deadline is not None and time.monotonic() >= deadline:
            break
        agent_id = f"{args.agent_prefix}-{index:04d}"
        commands: list[tuple[str, list[str]]] = [
            (
                "create",
                [
                    args.python_bin,
                    "-m",
                    "nexus3",
                    "rpc",
                    "create",
                    agent_id,
                    "--port",
                    str(args.port),
                ],
            ),
            (
                "send",
                [
                    args.python_bin,
                    "-m",
                    "nexus3",
                    "rpc",
                    "send",
                    agent_id,
                    args.message,
                    "--port",
                    str(args.port),
                    "--timeout",
                    str(args.send_timeout),
                ],
            ),
            (
                "compact",
                [
                    args.python_bin,
                    "-m",
                    "nexus3",
                    "rpc",
                    "compact",
                    agent_id,
                    "--port",
                    str(args.port),
                ],
            ),
            (
                "destroy",
                [
                    args.python_bin,
                    "-m",
                    "nexus3",
                    "rpc",
                    "destroy",
                    agent_id,
                    "--port",
                    str(args.port),
                ],
            ),
        ]

        for operation, command in commands:
            outcome = run_command(
                command=command,
                operation=operation,
                timeout_seconds=args.command_timeout,
                dry_run=args.dry_run,
            )
            outcomes.append(outcome)
            append_line(
                commands_path,
                (
                    f"{outcome.started_at} | {operation} | rc={outcome.returncode} | "
                    f"duration={outcome.duration_seconds:.3f}s | {shlex.join(command)}"
                ),
            )
            append_jsonl(
                events_path,
                {
                    "timestamp": outcome.started_at,
                    "operation": operation,
                    "status": "ok" if outcome.returncode == 0 else "error",
                    "duration_seconds": outcome.duration_seconds,
                    "details": {
                        "agent_id": agent_id,
                        "returncode": outcome.returncode,
                        "skipped": outcome.skipped,
                        "stdout_tail": outcome.stdout_tail,
                        "stderr_tail": outcome.stderr_tail,
                    },
                },
            )
            if operation == "send":
                send_latencies.append(outcome.duration_seconds)
            if args.pause_seconds > 0:
                time.sleep(args.pause_seconds)

    finished = utc_now()
    total_commands = len(outcomes)
    failures = [outcome for outcome in outcomes if outcome.returncode != 0]
    failure_rate = (len(failures) / total_commands) if total_commands else 0.0
    send_p50 = percentile(send_latencies, 0.5)
    send_p95 = percentile(send_latencies, 0.95)

    failed_checks: list[str] = []
    warnings: list[str] = []
    if not send_latencies:
        failed_checks.append("no send latency samples were collected")
    if failure_rate > args.max_failure_rate:
        failed_checks.append(
            f"failure rate {failure_rate:.3%} exceeded "
            f"threshold {args.max_failure_rate:.3%}"
        )
    if send_p50 > args.max_send_p50_seconds:
        failed_checks.append(
            f"send p50 latency {send_p50:.3f}s exceeded "
            f"threshold {args.max_send_p50_seconds:.3f}s"
        )
    if send_p95 > args.max_send_p95_seconds:
        failed_checks.append(
            f"send p95 latency {send_p95:.3f}s exceeded "
            f"threshold {args.max_send_p95_seconds:.3f}s"
        )
    if args.dry_run:
        warnings.append("dry-run mode enabled: commands were not executed")

    highlights = [
        f"iterations={args.iterations}",
        f"total_commands={total_commands}",
        f"failures={len(failures)}",
        f"send_p50_seconds={send_p50:.3f}",
        f"send_p95_seconds={send_p95:.3f}",
    ]

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
            "python_bin": args.python_bin,
            "port": args.port,
            "iterations": args.iterations,
            "duration_seconds": args.duration_seconds,
            "agent_prefix": args.agent_prefix,
            "send_timeout": args.send_timeout,
            "command_timeout": args.command_timeout,
            "pause_seconds": args.pause_seconds,
            "max_failure_rate": args.max_failure_rate,
            "max_send_p50_seconds": args.max_send_p50_seconds,
            "max_send_p95_seconds": args.max_send_p95_seconds,
            "dry_run": args.dry_run,
        },
        "counts": {
            "total_commands": total_commands,
            "failures": len(failures),
            "send_samples": len(send_latencies),
        },
    }
    write_json(metadata_path, metadata)

    verdict = {
        "pass": len(failed_checks) == 0,
        "failed_checks": failed_checks,
        "warnings": warnings,
        "highlights": highlights,
        "generated_at": iso_utc(utc_now()),
    }
    write_json(verdict_path, verdict)
    write_json(
        summary_json_path,
        {
            "status": "pass" if verdict["pass"] else "fail",
            "dry_run": args.dry_run,
            "duration_seconds": max(0.0, (finished - started).total_seconds()),
            "iterations_requested": args.iterations,
            "commands_total": total_commands,
            "commands_failed": len(failures),
            "failure_rate": failure_rate,
            "send_p50_seconds": send_p50,
            "send_p95_seconds": send_p95,
        },
    )

    failure_excerpt = [
        (
            f"- `{item.operation}` rc={item.returncode}: "
            f"{item.stderr_tail or item.stdout_tail or 'no output'}"
        )
        for item in failures[:10]
    ]
    if not failure_excerpt:
        failure_excerpt = ["- none"]

    summary_lines = [
        f"# Soak Validation Summary: `{run_id}`",
        "",
        "## Configuration",
        f"- iterations: {args.iterations}",
        f"- port: {args.port}",
        f"- dry_run: {args.dry_run}",
        "",
        "## Metrics",
        f"- total commands: {total_commands}",
        f"- failures: {len(failures)} ({failure_rate:.3%})",
        f"- send p50 latency: {send_p50:.3f}s",
        f"- send p95 latency: {send_p95:.3f}s",
        "",
        "## Verdict",
        f"- pass: {verdict['pass']}",
        f"- failed checks: {len(failed_checks)}",
    ]
    if failed_checks:
        summary_lines.extend(["", "### Failed checks"])
        summary_lines.extend([f"- {check}" for check in failed_checks])
    if warnings:
        summary_lines.extend(["", "### Warnings"])
        summary_lines.extend([f"- {item}" for item in warnings])
    summary_lines.extend(["", "## Failure Excerpt"])
    summary_lines.extend(failure_excerpt)
    summary_lines.extend(
        [
            "",
            "## Reproduction Command",
            "```bash",
            (
                ".venv/bin/python scripts/validation/soak_workload.py "
                f"--port {args.port} --iterations {args.iterations} "
                f"--agent-prefix {args.agent_prefix}"
            ),
            "```",
        ]
    )
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    print(f"artifact_dir={run_dir}")
    print(f"pass={verdict['pass']}")
    return 0 if verdict["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
