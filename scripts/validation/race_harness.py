#!/usr/bin/env python3
"""Run concurrent lifecycle workload and archive artifacts for race validation."""

from __future__ import annotations

import argparse
import json
import platform
import shlex
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TRACK = "race"
SECURITY_PATTERNS = (
    "permission denied",
    "not allowed",
    "authorization",
    "forbidden",
    "invalid capability",
    "invariant",
    "state mismatch",
)
EXPECTED_CONTENTION_PATTERNS = (
    "agent already exists",
    "agent not found",
)


@dataclass(frozen=True)
class Outcome:
    worker: int
    round_index: int
    operation: str
    command: list[str]
    started_at: str
    duration_seconds: float
    returncode: int
    stdout_tail: str
    stderr_tail: str
    skipped: bool


def now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def run_id(value: str | None) -> str:
    if value:
        return value
    return f"race-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"


def tail(text: str, size: int = 400) -> str:
    compact = text.strip()
    if len(compact) <= size:
        return compact
    return compact[-size:]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_line(path: Path, line: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.write("\n")


def append_event(path: Path, event: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True))
        handle.write("\n")


def p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = round((len(ordered) - 1) * 0.95)
    return ordered[index]


def run_cmd(command: list[str], timeout: float, dry_run: bool) -> tuple[int, float, str, str, bool]:
    if dry_run:
        return (0, 0.0, "", "", True)
    started = datetime.now(UTC)
    try:
        done = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        elapsed = (datetime.now(UTC) - started).total_seconds()
        return (done.returncode, elapsed, tail(done.stdout), tail(done.stderr), False)
    except subprocess.TimeoutExpired as exc:
        elapsed = (datetime.now(UTC) - started).total_seconds()
        if isinstance(exc.stdout, bytes):
            stdout = exc.stdout.decode("utf-8", errors="replace")
        else:
            stdout = exc.stdout or ""
        return (124, elapsed, tail(stdout), f"timeout after {timeout:.1f}s", False)


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
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--rounds", type=int, default=100)
    parser.add_argument("--shared-agent-pool-size", type=int, default=4)
    parser.add_argument("--agent-prefix", type=str, default="postm4-race")
    parser.add_argument("--message", type=str, default="Reply with race-ok.")
    parser.add_argument("--send-timeout", type=int, default=90)
    parser.add_argument("--command-timeout", type=float, default=120.0)
    parser.add_argument("--max-failure-rate", type=float, default=0.02)
    parser.add_argument("--max-security-failures", type=int, default=0)
    parser.add_argument(
        "--exclude-expected-contention-errors",
        action="store_true",
        help=(
            "Exclude known contention outcomes from failure-rate gating "
            "(agent already exists / agent not found)."
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def worker_round(worker: int, args: argparse.Namespace) -> list[Outcome]:
    results: list[Outcome] = []
    for round_index in range(args.rounds):
        slot = (worker + round_index) % max(1, args.shared_agent_pool_size)
        agent = f"{args.agent_prefix}-slot{slot:03d}"
        commands = [
            (
                "create",
                [args.python_bin, "-m", "nexus3", "rpc", "create", agent, "--port", str(args.port)],
            ),
            (
                "send",
                [
                    args.python_bin,
                    "-m",
                    "nexus3",
                    "rpc",
                    "send",
                    agent,
                    args.message,
                    "--port",
                    str(args.port),
                    "--timeout",
                    str(args.send_timeout),
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
                    agent,
                    "--port",
                    str(args.port),
                ],
            ),
        ]
        for operation, command in commands:
            started_at = now_iso()
            rc, elapsed, stdout_tail, stderr_tail, skipped = run_cmd(
                command=command,
                timeout=args.command_timeout,
                dry_run=args.dry_run,
            )
            results.append(
                Outcome(
                    worker=worker,
                    round_index=round_index,
                    operation=operation,
                    command=command,
                    started_at=started_at,
                    duration_seconds=elapsed,
                    returncode=rc,
                    stdout_tail=stdout_tail,
                    stderr_tail=stderr_tail,
                    skipped=skipped,
                )
            )
    return results


def main() -> int:
    args = parse_args()
    run = run_id(args.run_id)
    out_dir = args.output_root / run / TRACK
    out_dir.mkdir(parents=True, exist_ok=True)

    commands_log = out_dir / "commands.log"
    events_jsonl = out_dir / "events.jsonl"
    verdict_json = out_dir / "verdict.json"
    metadata_json = out_dir / "metadata.json"
    summary_json = out_dir / "summary.json"
    summary_md = out_dir / "summary.md"

    started_at = now_iso()

    outcomes: list[Outcome] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(worker_round, worker, args) for worker in range(args.workers)]
        for future in as_completed(futures):
            outcomes.extend(future.result())

    outcomes.sort(key=lambda item: item.started_at)
    for item in outcomes:
        append_line(
            commands_log,
            (
                f"{item.started_at} | worker={item.worker} | round={item.round_index} | "
                f"{item.operation} | rc={item.returncode} | "
                f"duration={item.duration_seconds:.3f}s | {shlex.join(item.command)}"
            ),
        )
        append_event(
            events_jsonl,
            {
                "timestamp": item.started_at,
                "operation": item.operation,
                "status": "ok" if item.returncode == 0 else "error",
                "duration_seconds": item.duration_seconds,
                "details": {
                    "worker": item.worker,
                    "round_index": item.round_index,
                    "returncode": item.returncode,
                    "skipped": item.skipped,
                    "stdout_tail": item.stdout_tail,
                    "stderr_tail": item.stderr_tail,
                },
            },
        )

    failures = [item for item in outcomes if item.returncode != 0]
    expected_contention_failures = [
        item
        for item in failures
        if any(
            pattern in f"{item.stdout_tail}\n{item.stderr_tail}".lower()
            for pattern in EXPECTED_CONTENTION_PATTERNS
        )
    ]
    if args.exclude_expected_contention_errors:
        unexpected_failures = [
            item for item in failures if item not in expected_contention_failures
        ]
    else:
        unexpected_failures = failures
    raw_failure_rate = (len(failures) / len(outcomes)) if outcomes else 0.0
    unexpected_failure_rate = (
        len(unexpected_failures) / len(outcomes) if outcomes else 0.0
    )
    send_latencies = [item.duration_seconds for item in outcomes if item.operation == "send"]
    security_failures = [
        item
        for item in failures
        if any(
            pattern in f"{item.stdout_tail}\n{item.stderr_tail}".lower()
            for pattern in SECURITY_PATTERNS
        )
    ]

    failed_checks: list[str] = []
    warnings: list[str] = []
    if unexpected_failure_rate > args.max_failure_rate:
        failed_checks.append(
            "unexpected failure rate "
            f"{unexpected_failure_rate:.3%} exceeded threshold "
            f"{args.max_failure_rate:.3%}"
        )
    if len(security_failures) > args.max_security_failures:
        failed_checks.append(
            "security failures "
            f"{len(security_failures)} exceeded threshold "
            f"{args.max_security_failures}"
        )
    if args.exclude_expected_contention_errors and expected_contention_failures:
        warnings.append(
            "excluded expected contention failures from failure-rate gate: "
            f"{len(expected_contention_failures)}"
        )
    if args.dry_run:
        warnings.append("dry-run mode enabled: commands were not executed")

    verdict = {
        "pass": len(failed_checks) == 0,
        "failed_checks": failed_checks,
        "warnings": warnings,
        "highlights": [
            f"workers={args.workers}",
            f"rounds={args.rounds}",
            f"total_commands={len(outcomes)}",
            f"failures_raw={len(failures)}",
            f"failures_unexpected={len(unexpected_failures)}",
            f"expected_contention_failures={len(expected_contention_failures)}",
            f"send_p95_seconds={p95(send_latencies):.3f}",
            f"security_failures={len(security_failures)}",
        ],
        "generated_at": now_iso(),
    }
    write_json(verdict_json, verdict)

    metadata = {
        "run_id": run,
        "track": TRACK,
        "started_at": started_at,
        "finished_at": now_iso(),
        "duration_seconds": sum(item.duration_seconds for item in outcomes),
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
            "workers": args.workers,
            "rounds": args.rounds,
            "shared_agent_pool_size": args.shared_agent_pool_size,
            "agent_prefix": args.agent_prefix,
            "send_timeout": args.send_timeout,
            "command_timeout": args.command_timeout,
            "max_failure_rate": args.max_failure_rate,
            "max_security_failures": args.max_security_failures,
            "exclude_expected_contention_errors": args.exclude_expected_contention_errors,
            "dry_run": args.dry_run,
        },
    }
    write_json(metadata_json, metadata)
    write_json(
        summary_json,
        {
            "status": "pass" if verdict["pass"] else "fail",
            "dry_run": args.dry_run,
            "workers": args.workers,
            "rounds": args.rounds,
            "shared_agent_pool_size": args.shared_agent_pool_size,
            "commands_total": len(outcomes),
            "commands_failed_raw": len(failures),
            "commands_failed_unexpected": len(unexpected_failures),
            "expected_contention_failures": len(expected_contention_failures),
            "failure_rate_raw": raw_failure_rate,
            "failure_rate_unexpected": unexpected_failure_rate,
            "send_p95_seconds": p95(send_latencies),
            "security_failures": len(security_failures),
        },
    )

    summary_md.write_text(
        "\n".join(
            [
                f"# Race Validation Summary: `{run}`",
                "",
                f"- total commands: {len(outcomes)}",
                f"- failures (raw): {len(failures)} ({raw_failure_rate:.3%})",
                f"- failures (unexpected): "
                f"{len(unexpected_failures)} ({unexpected_failure_rate:.3%})",
                f"- expected contention failures: {len(expected_contention_failures)}",
                f"- send p95 latency: {p95(send_latencies):.3f}s",
                f"- security failures: {len(security_failures)}",
                f"- pass: {verdict['pass']}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"artifact_dir={out_dir}")
    print(f"pass={verdict['pass']}")
    print(f"security_failures={len(security_failures)}")
    return 0 if verdict["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
