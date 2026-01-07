"""UTF-8 encoding constants and helpers for NEXUS3."""

import sys

# Encoding constants
ENCODING = "utf-8"
ENCODING_ERRORS = "replace"  # Preserve data, mark corruption


def configure_stdio() -> None:
    """Reconfigure stdin/stdout/stderr to use UTF-8 with replace error handling.

    Should be called at application startup to ensure consistent encoding
    across all platforms.
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding=ENCODING, errors=ENCODING_ERRORS)
