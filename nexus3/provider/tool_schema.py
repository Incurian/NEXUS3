"""Shared outbound tool-schema normalization for provider adapters."""

from typing import Any

_TOP_LEVEL_PROVIDER_INCOMPATIBLE_KEYS = frozenset(
    {"anyOf", "oneOf", "allOf", "not", "enum"}
)
_TOP_LEVEL_METADATA_KEYS = frozenset(
    {"title", "description", "$schema", "$defs", "definitions", "examples", "default"}
)


def normalize_tool_parameters_for_provider(
    schema: dict[str, Any] | None,
) -> dict[str, Any]:
    """Normalize tool schemas for provider tool/function APIs.

    Provider tool-calling APIs expect an object-shaped top-level parameters
    schema. Dynamic MCP tools can arrive with omitted placeholders, nested
    fragments missing `properties`/`items`, or top-level combinator/scalar
    shapes that providers reject outright.
    """
    if not schema:
        return {"type": "object", "properties": {}}

    def _normalize_fragment(fragment: Any) -> Any:
        if isinstance(fragment, list):
            return [_normalize_fragment(item) for item in fragment]

        if not isinstance(fragment, dict):
            return fragment

        normalized = {
            key: _normalize_fragment(value) for key, value in fragment.items()
        }

        if normalized.get("type") == "object" and "properties" not in normalized:
            normalized["properties"] = {}

        if normalized.get("type") == "array" and "items" not in normalized:
            normalized["items"] = {}

        return normalized

    normalized = _normalize_fragment(schema)
    if not isinstance(normalized, dict):
        return {"type": "object", "properties": {}}

    provider_schema = {
        key: value
        for key, value in normalized.items()
        if key not in _TOP_LEVEL_PROVIDER_INCOMPATIBLE_KEYS
    }

    has_object_shape = (
        provider_schema.get("type") == "object"
        or "properties" in provider_schema
        or "patternProperties" in provider_schema
        or "additionalProperties" in provider_schema
    )

    if not has_object_shape:
        provider_schema = {
            key: value
            for key, value in provider_schema.items()
            if key in _TOP_LEVEL_METADATA_KEYS
        }

    provider_schema["type"] = "object"
    provider_schema.setdefault("properties", {})
    provider_schema.pop("items", None)

    return provider_schema
