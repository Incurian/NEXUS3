"""Phase 2 regressions for the byte-strict AST-v2 apply path."""

from pathlib import Path
from typing import cast

from nexus3.patch import apply_patch_byte_strict, parse_unified_diff_v2
from nexus3.patch.ast_v2 import HunkLineV2

_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "arch_baseline"
def _apply_byte_strict_to_bytes(source_bytes: bytes, diff_text: str) -> bytes:
    """Parse v2 diff and apply via byte-strict entrypoint, returning utf-8 bytes."""
    parsed_files = parse_unified_diff_v2(diff_text)
    assert len(parsed_files) == 1
    patch = parsed_files[0]
    result = apply_patch_byte_strict(
        source_bytes.decode("utf-8", errors="surrogatepass"),
        patch,
    )
    assert result.success, result.failed_hunks
    return result.new_content.encode("utf-8", errors="surrogatepass")


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
