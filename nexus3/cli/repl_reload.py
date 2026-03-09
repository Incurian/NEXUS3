"""Serve-mode reload helper for REPL entrypoint."""

import argparse
import sys
from pathlib import Path

from nexus3.cli.repl_formatting import (
    _format_reload_detected_changes_line,
    _format_reload_starting_line,
    _format_reload_watching_line,
)
from nexus3.display import get_console
from nexus3.display.safe_sink import SafeSink


def run_with_reload(args: argparse.Namespace) -> None:
    """Run serve mode with auto-reload using watchfiles."""
    try:
        import watchfiles
    except ImportError:
        print("Auto-reload requires watchfiles: pip install watchfiles")
        print("Or install dev dependencies: uv pip install -e '.[dev]'")
        return

    # Find the nexus3 package directory to watch
    import nexus3

    watch_path = Path(nexus3.__file__).parent
    console = get_console()
    safe_sink = SafeSink(console)

    console.print(_format_reload_watching_line(safe_sink, watch_path))
    console.print(_format_reload_starting_line(safe_sink, args.serve))
    console.print("")

    # Build the command to run
    cmd = [
        sys.executable, "-m", "nexus3",
        "--serve", str(args.serve),
    ]
    if args.verbose:
        cmd.append("--verbose")
    if getattr(args, "log_verbose", False):
        cmd.append("--log-verbose")
    if args.raw_log:
        cmd.append("--raw-log")
    if args.log_dir:
        cmd.extend(["--log-dir", str(args.log_dir)])

    # Run with watchfiles - restarts on any .py file change
    watchfiles.run_process(
        watch_path,
        target=cmd[0],
        args=tuple(cmd[1:]),
        callback=lambda changes: console.print(
            _format_reload_detected_changes_line(safe_sink, changes)
        ),
    )
