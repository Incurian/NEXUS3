from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def prepare_script_path() -> Path:
    return repo_root() / "scripts" / "validation" / "prepare_post_m4_manual_closeout.py"


def run_prepare(
    artifact_root: Path,
    run_id: str,
    windows_source_run_id: str,
    terminal_source_run_id: str,
    force: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(prepare_script_path()),
        "--artifact-root",
        str(artifact_root),
        "--run-id",
        run_id,
        "--windows-source-run-id",
        windows_source_run_id,
        "--terminal-source-run-id",
        terminal_source_run_id,
    ]
    if force:
        command.append("--force")
    return subprocess.run(
        command,
        cwd=repo_root(),
        capture_output=True,
        text=True,
        check=False,
    )


def test_prepare_post_m4_manual_closeout_scaffolds_fresh(tmp_path: Path) -> None:
    artifact_root = tmp_path / "validation"
    run_id = "post-m4-manual-closeout-a"
    windows_source_run_id = "source-win"
    terminal_source_run_id = "source-term"

    completed = run_prepare(
        artifact_root=artifact_root,
        run_id=run_id,
        windows_source_run_id=windows_source_run_id,
        terminal_source_run_id=terminal_source_run_id,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "ok"

    run_dir = artifact_root / run_id
    expected_files = {
        run_dir / "windows" / "metadata.json",
        run_dir / "windows" / "checklist.md",
        run_dir / "windows" / "summary.json",
        run_dir / "windows" / "notes.md",
        run_dir / "terminal" / "summary.md",
        run_dir / "closeout-handoff.md",
    }
    assert set(payload["created_files"]) == {str(path) for path in expected_files}
    assert payload["updated_files"] == []
    assert payload["validation"]["required_windows_files_present"] is True
    assert payload["validation"]["terminal_summary"]["has_todo_marker"] is True
    assert payload["validation"]["terminal_summary"]["has_plain_closure_marker"] is False

    windows_summary = json.loads(
        (run_dir / "windows" / "summary.json").read_text(encoding="utf-8")
    )
    assert windows_summary["status"] == "pending_real_host"

    terminal_summary = (run_dir / "terminal" / "summary.md").read_text(encoding="utf-8")
    assert "TODO: Manual emulator verification: **PASS**" in terminal_summary
    assert "Manual emulator verification: PASS" not in terminal_summary

    handoff_note = (run_dir / "closeout-handoff.md").read_text(encoding="utf-8")
    assert "docs/testing/WINDOWS-LIVE-TESTING-GUIDE.md" in handoff_note
    assert "--soak-run-id source-win" in handoff_note
    assert "--race-run-id post-m4-20260306-live1c" in handoff_note
    assert "--terminal-run-id source-term" in handoff_note
    assert "--windows-run-id post-m4-manual-closeout-a" in handoff_note


def test_prepare_post_m4_manual_closeout_does_not_overwrite_without_force(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "validation"
    run_id = "post-m4-manual-closeout-b"
    run_dir = artifact_root / run_id

    existing_content: dict[Path, str] = {
        run_dir / "windows" / "metadata.json": '{"custom":"metadata"}\n',
        run_dir / "windows" / "checklist.md": "# custom checklist\n",
        run_dir / "windows" / "summary.json": '{"status":"custom"}\n',
        run_dir / "windows" / "notes.md": "# custom notes\n",
        run_dir / "terminal" / "summary.md": "# custom terminal summary\n",
        run_dir / "closeout-handoff.md": "# custom handoff\n",
    }

    for path, content in existing_content.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    completed = run_prepare(
        artifact_root=artifact_root,
        run_id=run_id,
        windows_source_run_id="source-win",
        terminal_source_run_id="source-term",
        force=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "ok"
    assert payload["created_files"] == []
    assert payload["updated_files"] == []
    assert set(payload["unchanged_files"]) == {str(path) for path in existing_content}

    for path, original_content in existing_content.items():
        assert path.read_text(encoding="utf-8") == original_content
