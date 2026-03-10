"""Input validation utilities for NEXUS3.

This module provides validation functions for security-sensitive inputs
like agent IDs, session names, and tool arguments.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from nexus3.core.errors import NexusError

logger = logging.getLogger(__name__)

# Agent ID pattern: alphanumeric + dot/underscore/hyphen, 1-63 chars total
# Must start with alphanumeric OR dot (for temp agents like .1, .2)
# Dot-prefixed IDs (.1, .2) are temp agents
# Note: {0,61} ensures max 63 chars total (optional dot + first char + 0-61 more)
AGENT_ID_PATTERN = re.compile(r'^\.?[a-zA-Z0-9][a-zA-Z0-9._-]{0,61}$')

# Allowed internal parameters that bypass schema validation
# Only explicitly whitelisted params are allowed, not all underscore-prefixed
ALLOWED_INTERNAL_PARAMS = {"_parallel"}


class ValidationError(NexusError):
    """Raised when validation fails."""

    pass


def validate_agent_id(agent_id: str) -> str:
    """Validate agent ID format.

    Agent IDs must be:
    - 1-63 characters long
    - Alphanumeric, dots, underscores, hyphens only
    - Start with alphanumeric or dot (for temp agents)
    - Not be reserved names like "." or ".."

    Args:
        agent_id: The agent ID to validate.

    Returns:
        The validated agent_id (unchanged if valid).

    Raises:
        ValidationError: If agent_id is invalid.
    """
    if not agent_id:
        raise ValidationError("Agent ID cannot be empty")

    if agent_id in (".", ".."):
        raise ValidationError(f"Agent ID cannot be '{agent_id}'")

    if not AGENT_ID_PATTERN.match(agent_id):
        raise ValidationError(
            f"Invalid agent ID '{agent_id}': must be 1-63 chars, "
            "alphanumeric/dot/underscore/hyphen, start with alphanumeric or dot"
        )

    # Additional safety: no path separators even if they pass regex
    if "/" in agent_id or "\\" in agent_id:
        raise ValidationError(f"Agent ID cannot contain path separators: {agent_id}")

    return agent_id


def is_valid_agent_id(agent_id: str) -> bool:
    """Check if agent ID is valid without raising exception.

    Args:
        agent_id: The agent ID to check.

    Returns:
        True if valid, False otherwise.
    """
    try:
        validate_agent_id(agent_id)
        return True
    except ValidationError:
        return False


def validate_tool_arguments(
    arguments: dict[str, Any],
    schema: dict[str, Any],
) -> dict[str, Any]:
    """Validate tool arguments against JSON schema.

    Validates required fields and types. Warns about (but allows) extra parameters.
    Returns only the validated/known parameters.

    Args:
        arguments: The arguments provided by the LLM.
        schema: The JSON schema for the tool's parameters.

    Returns:
        Dict containing only valid, known parameters.

    Raises:
        ValidationError: If required params missing or types don't match.
    """
    import jsonschema  # type: ignore[import-untyped]

    # Internal execution flags are allowed but should not interfere with schema validation.
    schema_arguments = {
        k: v for k, v in arguments.items() if k not in ALLOWED_INTERNAL_PARAMS
    }

    # Validate against schema (checks required fields and types)
    try:
        jsonschema.validate(schema_arguments, schema)
    except jsonschema.ValidationError as e:
        raise ValidationError(f"Invalid argument: {e.message}") from e

    # Get known properties from schema
    schema_props = set(schema.get("properties", {}).keys())
    preserve_dynamic = schema_preserves_dynamic_top_level_keys(schema)

    # Check for extra properties (warn but don't reject)
    provided = set(arguments.keys())
    # Only allow explicitly whitelisted internal params, not all underscore-prefixed
    extras = {k for k in provided if k not in ALLOWED_INTERNAL_PARAMS} - schema_props
    if extras:
        logger.warning("Unknown tool arguments (ignored): %s", extras)

    # Preserve validated dynamic keys for explicitly open-ended schemas used by
    # MCP-style adapters. Keep the historical filtering behavior for closed or
    # implicitly-loose built-in schemas that do not opt in explicitly.
    if preserve_dynamic:
        return dict(arguments)

    # Return only known properties plus explicitly allowed internal params
    return {
        k: v for k, v in arguments.items()
        if k in schema_props or k in ALLOWED_INTERNAL_PARAMS
    }


def schema_preserves_dynamic_top_level_keys(schema: dict[str, Any]) -> bool:
    """Return True when validated top-level dynamic keys should be preserved.

    This is intentionally narrower than raw JSON Schema defaults. Built-in
    skills that merely omit `additionalProperties` continue to filter unknown
    params unless they explicitly opt into open-ended top-level objects via
    `additionalProperties`, `patternProperties`, or a schema without explicit
    `properties`.
    """
    if schema.get("type") != "object":
        return False

    if schema.get("patternProperties"):
        return True

    if "additionalProperties" in schema:
        return schema["additionalProperties"] is not False

    return not schema.get("properties")
