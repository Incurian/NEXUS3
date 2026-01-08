"""HTTP server mode for NEXUS3.

This module provides the HTTP server entry point, which runs NEXUS3 as a
JSON-RPC 2.0 server over HTTP. This enables programmatic control for
automation, integration with external tools, and multi-client access.

Protocol:
    - POST / with JSON-RPC 2.0 request body
    - Response: JSON-RPC 2.0 response

Example:
    python -m nexus3 --serve
    curl -X POST http://localhost:8765 \\
        -H "Content-Type: application/json" \\
        -d '{"jsonrpc":"2.0","method":"send","params":{"content":"Hi"},"id":1}'
"""

from pathlib import Path

from dotenv import load_dotenv

from nexus3.config.loader import load_config
from nexus3.context import ContextConfig, ContextManager, PromptLoader
from nexus3.core.encoding import configure_stdio
from nexus3.core.errors import NexusError
from nexus3.provider.openrouter import OpenRouterProvider
from nexus3.rpc import Dispatcher
from nexus3.rpc.http import DEFAULT_PORT, run_http_server
from nexus3.session import LogConfig, LogStream, Session, SessionLogger
from nexus3.skill import ServiceContainer, SkillRegistry
from nexus3.skill.builtin import register_builtin_skills

# Configure UTF-8 at module load
configure_stdio()

# Load .env file if present
load_dotenv()


async def run_serve(
    port: int = DEFAULT_PORT,
    verbose: bool = False,
    raw_log: bool = False,
    log_dir: Path | None = None,
) -> None:
    """Run NEXUS3 as an HTTP JSON-RPC server.

    Starts an HTTP server that accepts JSON-RPC 2.0 requests.
    Each request/response uses the JSON-RPC protocol.

    Args:
        port: Port to listen on (default: 8765).
        verbose: Enable verbose logging stream.
        raw_log: Enable raw API logging stream.
        log_dir: Directory for session logs.
    """
    # Load configuration
    try:
        config = load_config()
    except NexusError as e:
        print(f"Configuration error: {e.message}")
        return

    # Create provider
    try:
        provider = OpenRouterProvider(config.provider)
    except NexusError as e:
        print(f"Provider error: {e.message}")
        return

    # Configure logging streams - all on by default for debugging
    streams = LogStream.ALL

    # Create session logger
    log_config = LogConfig(
        base_dir=log_dir or Path(".nexus3/logs"),
        streams=streams,
        mode="serve",
    )
    logger = SessionLogger(log_config)

    # Wire up raw logging callback if enabled
    raw_callback = logger.get_raw_log_callback()
    if raw_callback is not None:
        provider.set_raw_log_callback(raw_callback)

    # Load system prompt (is_repl=False for server mode)
    prompt_loader = PromptLoader()
    loaded_prompt = prompt_loader.load(is_repl=False)
    system_prompt = loaded_prompt.content

    # Create context manager
    context = ContextManager(
        config=ContextConfig(),
        logger=logger,
    )
    context.set_system_prompt(system_prompt)

    # Create skill registry with services
    services = ServiceContainer()
    registry = SkillRegistry(services)
    register_builtin_skills(registry)

    # Inject tool definitions into context
    context.set_tool_definitions(registry.get_definitions())

    # Create session with context
    session = Session(provider, context=context, logger=logger, registry=registry)

    # Create dispatcher with context for token info
    dispatcher = Dispatcher(session, context=context)

    # Print session info
    print("NEXUS3 HTTP Server")
    print(f"Session: {logger.session_dir}")
    if loaded_prompt.personal_path:
        print(f"Personal: {loaded_prompt.personal_path}")
    if loaded_prompt.project_path:
        print(f"Project: {loaded_prompt.project_path}")
    print(f"Listening on http://localhost:{port}")
    print("Press Ctrl+C to stop")
    print("")

    # Run the HTTP server
    try:
        await run_http_server(dispatcher, port)
    finally:
        # Clean up logger
        logger.close()
