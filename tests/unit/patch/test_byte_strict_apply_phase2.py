"""Phase 2 regressions for the byte-strict AST-v2 apply path."""

from pathlib import Path
from typing import cast

from nexus3.patch import apply_patch_byte_strict, parse_unified_diff_v2
from nexus3.patch.ast_v2 import HunkLineV2

_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "arch_baseline"


def _apply_byte_strict_to_bytes(
    source_bytes: bytes,
    diff_text: str,
    *,
    codec_errors: str = "surrogateescape",
) -> bytes:
    """Parse/apply via byte-strict entrypoint with a reversible UTF-8 error mode."""
    parsed_files = parse_unified_diff_v2(diff_text)
    assert len(parsed_files) == 1
    patch = parsed_files[0]
    result = apply_patch_byte_strict(source_bytes, patch)
    assert result.success, result.failed_hunks
    return result.new_content.encode("utf-8", errors=codec_errors)


def test_byte_strict_apply_handles_explicit_no_final_newline_marker() -> None:
    """Explicit '\\ No newline at end of file' markers must keep EOF newline absent."""
    source_bytes = b"alpha\nbeta"
    diff_text = (_FIXTURE_DIR / "patch_noeol_marker_update.diff").read_text(
        encoding="utf-8"
    )

    assert "\\ No newline at end of file" in diff_text
    parsed_files = parse_unified_diff_v2(diff_text)
    assert len(parsed_files) == 1
    hunk_lines = cast(list[HunkLineV2], parsed_files[0].hunks[0].lines)
    marked_old_side = [line for line in hunk_lines if line.prefix == "-" and line.no_newline_at_eof]
    marked_new_side = [line for line in hunk_lines if line.prefix == "+" and line.no_newline_at_eof]
    assert len(marked_old_side) == 1
    assert len(marked_new_side) == 1

    patched_bytes = _apply_byte_strict_to_bytes(source_bytes, diff_text)

    assert patched_bytes == b"alpha\nBETA"
    assert not patched_bytes.endswith(b"\n")


def test_byte_strict_apply_preserves_mixed_newline_styles() -> None:
    """Byte-strict apply should preserve mixed CRLF/LF layout in patched output."""
    source_bytes = b"alpha\r\nbeta\ngamma\r\n"
    diff_text = (_FIXTURE_DIR / "patch_mixed_newline_update.diff").read_text(
        encoding="utf-8"
    )

    patched_bytes = _apply_byte_strict_to_bytes(source_bytes, diff_text)

    assert patched_bytes == b"alpha\r\nBETA\ngamma\r\n"
    assert patched_bytes.splitlines(keepends=True) == [
        b"alpha\r\n",
        b"BETA\n",
        b"gamma\r\n",
    ]


def test_byte_strict_apply_preserves_adjacent_invalid_utf8_bytes() -> None:
    """Unchanged adjacent invalid UTF-8 bytes must survive byte-strict patching."""
    source_bytes = b"\x80prefix\xff\nalpha\nsuffix\n"
    diff_text = (
        "--- a/sample.bin\n"
        "+++ b/sample.bin\n"
        "@@ -2,1 +2,1 @@\n"
        "-alpha\n"
        "+ALPHA\n"
    )

    patched_bytes = _apply_byte_strict_to_bytes(
        source_bytes,
        diff_text,
        codec_errors="surrogateescape",
    )

    assert patched_bytes == b"\x80prefix\xff\nALPHA\nsuffix\n"
    assert patched_bytes.splitlines(keepends=True)[0] == b"\x80prefix\xff\n"


def test_byte_strict_apply_preserves_binary_adjacent_payload_bytes() -> None:
    """NUL/control bytes on nearby unchanged lines must remain byte-identical."""
    source_bytes = b"blob:\x00\x01\x02\x1f\x7fEND\nstatus=old\ntail\n"
    diff_text = (
        "--- a/sample.bin\n"
        "+++ b/sample.bin\n"
        "@@ -2,1 +2,1 @@\n"
        "-status=old\n"
        "+status=new\n"
    )

    patched_bytes = _apply_byte_strict_to_bytes(source_bytes, diff_text)

    assert patched_bytes == b"blob:\x00\x01\x02\x1f\x7fEND\nstatus=new\ntail\n"
    assert patched_bytes.splitlines(keepends=True)[0] == b"blob:\x00\x01\x02\x1f\x7fEND\n"
