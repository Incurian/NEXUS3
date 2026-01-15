"""Core constants and paths for NEXUS3.

Single source of truth for global paths. All modules should import from here
instead of hardcoding paths like `Path.home() / ".nexus3"`.
"""

from pathlib import Path

NEXUS_DIR_NAME = ".nexus3"


def get_nexus_dir() -> Path:
    """Get ~/.nexus3 (global config directory)."""
    return Path.home() / NEXUS_DIR_NAME


def get_defaults_dir() -> Path:
    """Get package defaults directory (shipped with package)."""
    import nexus3
    return Path(nexus3.__file__).parent / "defaults"


def get_sessions_dir() -> Path:
    """Get sessions storage directory."""
    return get_nexus_dir() / "sessions"


def get_default_config_path() -> Path:
    """Get default config file path."""
    return get_nexus_dir() / "config.json"


def get_rpc_token_path(port: int = 8765) -> Path:
    """Get RPC token file path for a given port."""
    nexus_dir = get_nexus_dir()
    return nexus_dir / "rpc.token" if port == 8765 else nexus_dir / f"rpc-{port}.token"
