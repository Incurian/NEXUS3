from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

DEFAULT_SOAK_RUN_ID = "post-m4-20260306-live1b"
DEFAULT_RACE_RUN_ID = "post-m4-20260306-live1c"
DEFAULT_TERMINAL_RUN_ID = "post-m4-20260306-live1d"
DEFAULT_WINDOWS_RUN_ID = "post-m4-20260306-live1b"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def gate_script_path() -> Path:
    return repo_root() / "scripts" / "validation" / "post_m4_closeout_gate.py"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_terminal_summary(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_tracker_doc(path: Path, race_status: str, term_status: str, win_status: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent(
        f"""\
        # Tracker

        ### POSTM4-FU-RACE-001
        - Status: `{race_status}`

        ### POSTM4-FU-TERM-001
        - Status: `{term_status}`

        ### POSTM4-FU-WIN-001
        - Status: `{win_status}`
        """
    )
    path.write_text(content, encoding="utf-8")


def seed_common_artifacts(artifact_root: Path, windows_status: str, terminal_summary: str) -> None:
    write_json(
        artifact_root / DEFAULT_SOAK_RUN_ID / "soak" / "verdict.json",
        {"pass": True, "failed_checks": []},
    )
    write_json(
        artifact_root / DEFAULT_RACE_RUN_ID / "race" / "verdict.json",
        {"pass": True, "failed_checks": []},
    )
    write_json(
        artifact_root / DEFAULT_TERMINAL_RUN_ID / "terminal" / "verdict.json",
        {"pass": True, "failed_checks": []},
    )
    write_json(
        artifact_root / DEFAULT_WINDOWS_RUN_ID / "windows" / "summary.json",
        {"status": windows_status},
    )
    write_terminal_summary(
        artifact_root / DEFAULT_TERMINAL_RUN_ID / "terminal" / "summary.md",
        terminal_summary,
    )


def run_gate_checker(
    artifact_root: Path, tracker_doc: Path, json_out: Path | None = None
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(gate_script_path()),
        "--artifact-root",
        str(artifact_root),
        "--tracker-doc",
        str(tracker_doc),
    ]
    if json_out is not None:
        command.extend(["--json-out", str(json_out)])
    return subprocess.run(
        command,
        cwd=repo_root(),
        capture_output=True,
        text=True,
        check=False,
    )


def test_post_m4_closeout_gate_fails_for_open_gate(tmp_path: Path) -> None:
    artifact_root = tmp_path / "validation"
    tracker_doc = tmp_path / "tracker.md"
    seed_common_artifacts(
        artifact_root=artifact_root,
        windows_status="pending_real_host",
        terminal_summary="manual follow-up is still open.\n",
    )
    write_tracker_doc(
        tracker_doc,
        race_status="validation-closed",
        term_status="open",
        win_status="open",
    )

    completed = run_gate_checker(artifact_root=artifact_root, tracker_doc=tracker_doc)

    assert completed.returncode == 1, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["pass"] is False
    assert isinstance(payload["failed_checks"], list)
    assert any("windows_summary_pass" in item for item in payload["failed_checks"])
    assert any("terminal_manual_emulator_closure" in item for item in payload["failed_checks"])
    assert any("tracker_followups_closed" in item for item in payload["failed_checks"])
    assert payload["config"]["soak_run_id"] == DEFAULT_SOAK_RUN_ID
    assert payload["config"]["race_run_id"] == DEFAULT_RACE_RUN_ID
    assert payload["config"]["terminal_run_id"] == DEFAULT_TERMINAL_RUN_ID
    assert payload["config"]["windows_run_id"] == DEFAULT_WINDOWS_RUN_ID


def test_post_m4_closeout_gate_passes_when_fully_closed(tmp_path: Path) -> None:
    artifact_root = tmp_path / "validation"
    tracker_doc = tmp_path / "tracker.md"
    json_out = tmp_path / "closeout-result.json"
    seed_common_artifacts(
        artifact_root=artifact_root,
        windows_status="pass",
        terminal_summary="Multi-Emulator Verification: PASS\n",
    )
    write_tracker_doc(
        tracker_doc,
        race_status="validation-closed",
        term_status="validation-closed",
        win_status="validation-closed",
    )

    completed = run_gate_checker(
        artifact_root=artifact_root,
        tracker_doc=tracker_doc,
        json_out=json_out,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["pass"] is True
    assert payload["failed_checks"] == []
    assert all(check["pass"] for check in payload["checks"])
    assert "generated_at" in payload
    assert json_out.is_file()
    saved_payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert saved_payload == payload
