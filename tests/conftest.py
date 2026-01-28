"""Shared pytest fixtures and configuration for pytest."""

import sys

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers for platform-specific tests."""
    config.addinivalue_line("markers", "windows: mark test to run only on Windows")
    config.addinivalue_line(
        "markers", "windows_mock: mark test that mocks Windows behavior (runs everywhere)"
    )
    config.addinivalue_line("markers", "unix_only: mark test to run only on Unix")


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Auto-skip tests based on platform markers."""
    skip_windows = pytest.mark.skip(reason="Windows-only test")
    skip_unix = pytest.mark.skip(reason="Unix-only test")

    for item in items:
        if "windows" in item.keywords and sys.platform != "win32":
            item.add_marker(skip_windows)
        if "unix_only" in item.keywords and sys.platform == "win32":
            item.add_marker(skip_unix)

