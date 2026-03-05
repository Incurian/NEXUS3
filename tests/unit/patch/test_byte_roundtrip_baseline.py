"""Baseline parity fixtures for current patch byte roundtrip behavior.

These tests snapshot current newline/byte semantics through the patch pipeline
without filesystem I/O, so they remain stable in sandboxed test runs.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from nexus3.core.paths import detect_line_ending
from nexus3.patch import ApplyMode, apply_patch, parse_unified_diff

_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "arch_baseline"
_CASES = json.loads(
    (_FIXTURE_DIR / "patch_byte_roundtrip_cases.json").read_text(encoding="utf-8")
)["cases"]


def _restore_original_line_endings(text: str, original_line_ending: str) -> str:
    """Mirror current line-ending restoration used by byte baseline snapshots."""
    if original_line_ending == "\r\n" and "\r\n" not in text:
        return text.replace("\n", "\r\n")
    if original_line_ending == "\r" and "\r" not in text:
        return text.replace("\n", "\r")
    return text


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case["id"])
def test_patch_byte_roundtrip_baseline(case: dict[str, Any]) -> None:
    """Apply fixture patches and assert exact output bytes."""
    raw_bytes = bytes.fromhex(case["initial_hex"])
    original_text = raw_bytes.decode("utf-8", errors="replace")
    original_line_ending = detect_line_ending(original_text)
    assert original_line_ending == case["expected_original_line_ending"]

    diff_text = (_FIXTURE_DIR / case["diff_file"]).read_text(encoding="utf-8")
    if case.get("expect_noeol_marker", False):
        assert "\\ No newline at end of file" in diff_text

    patch_files = parse_unified_diff(diff_text)
    assert len(patch_files) == 1
    patch_file = patch_files[0]
    assert len(patch_file.hunks) == case["expected_hunk_count"]
    assert len(patch_file.hunks[0].lines) == case["expected_hunk_line_count"]
    assert all(
        not line.startswith("\\ No newline at end of file")
        for _, line in patch_file.hunks[0].lines
    )

    result = apply_patch(original_text, patch_file, mode=ApplyMode.STRICT)
    assert result.success, result.failed_hunks

    patched_text = _restore_original_line_endings(result.new_content, original_line_ending)

    assert patched_text.endswith("\n") is case["expected_has_trailing_newline"]
    assert patched_text.encode("utf-8").hex() == case["expected_hex"]
