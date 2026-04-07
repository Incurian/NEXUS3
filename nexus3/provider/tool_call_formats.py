"""Shared inbound tool-call parsing and normalization helpers."""

from __future__ import annotations

import ast
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from nexus3.core.types import ToolCall

logger = logging.getLogger(__name__)

_UNSET = object()


def _stringify_payload(payload: Any) -> str:
    """Return a stable text representation for raw payload preservation."""
    if isinstance(payload, str):
        return payload

    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return repr(payload)


def _string_key_dict_or_none(payload: Any) -> dict[str, Any] | None:
    """Return a shallow-copied dict when all keys are strings."""
    if not isinstance(payload, dict):
        return None

    if any(not isinstance(key, str) for key in payload):
        return None

    return dict(payload)


def _build_unresolved_meta(
    *,
    source_format: str,
    argument_format: str,
    raw_arguments: str,
    normalization_error: str,
) -> dict[str, Any]:
    """Return metadata for unresolved/raw tool arguments."""
    return {
        "source_format": source_format,
        "argument_format": argument_format,
        "raw_arguments": raw_arguments,
        "normalization_error": normalization_error,
        "arguments_unresolved": True,
    }


def _normalize_python_dict_literal(raw: str) -> dict[str, Any] | None:
    """Parse a Python dict literal safely."""
    try:
        parsed = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return None

    return _string_key_dict_or_none(parsed)


def _normalize_python_kwargs(raw: str) -> dict[str, Any] | None:
    """Parse raw keyword arguments like `path='x', limit=5` safely."""
    try:
        expr = ast.parse(f"_nexus_kwargs({raw})", mode="eval")
    except SyntaxError:
        return None

    if not isinstance(expr.body, ast.Call):
        return None
    if expr.body.args:
        return None

    kwargs: dict[str, Any] = {}
    for kw in expr.body.keywords:
        if kw.arg is None:
            return None
        try:
            kwargs[kw.arg] = ast.literal_eval(kw.value)
        except (ValueError, SyntaxError):
            return None

    return kwargs


def _normalize_python_call_expression(raw: str, tool_name: str) -> dict[str, Any] | None:
    """Parse a Pythonic call expression like `read_file(path='x')` safely."""
    try:
        expr = ast.parse(raw, mode="eval")
    except SyntaxError:
        return None

    call = expr.body
    if not isinstance(call, ast.Call):
        return None
    if call.args:
        return None
    if not isinstance(call.func, ast.Name):
        return None
    if not tool_name or call.func.id != tool_name:
        return None

    kwargs: dict[str, Any] = {}
    for kw in call.keywords:
        if kw.arg is None:
            return None
        try:
            kwargs[kw.arg] = ast.literal_eval(kw.value)
        except (ValueError, SyntaxError):
            return None

    return kwargs


def normalize_tool_arguments(
    payload: Any,
    *,
    tool_name: str,
    source_format: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Normalize provider-specific tool arguments into a dict contract.

    Returns:
        `(arguments, meta)` where `arguments` is always dict-shaped. Unresolved
        payloads preserve the original text in both `arguments["_raw_arguments"]`
        and `meta["raw_arguments"]` for backwards compatibility.
    """
    if payload is None:
        return {}, {
            "source_format": source_format,
            "argument_format": "empty",
        }

    if isinstance(payload, str):
        if not payload.strip():
            return {}, {
                "source_format": source_format,
                "argument_format": "empty",
            }

        try:
            json_parsed = json.loads(payload)
        except json.JSONDecodeError:
            json_parsed = _UNSET

        if json_parsed is not _UNSET:
            mapping = _string_key_dict_or_none(json_parsed)
            if mapping is not None:
                return mapping, {
                    "source_format": source_format,
                    "argument_format": "json_object",
                }

            raw = _stringify_payload(payload)
            logger.warning("Failed to normalize non-object JSON tool arguments: %.100s", raw)
            meta = _build_unresolved_meta(
                source_format=source_format,
                argument_format="json_non_object",
                raw_arguments=raw,
                normalization_error="Tool arguments must decode to an object",
            )
            return {"_raw_arguments": raw}, meta

        python_dict = _normalize_python_dict_literal(payload)
        if python_dict is not None:
            return python_dict, {
                "source_format": source_format,
                "argument_format": "python_dict",
            }

        python_kwargs = _normalize_python_kwargs(payload)
        if python_kwargs is not None:
            return python_kwargs, {
                "source_format": source_format,
                "argument_format": "python_kwargs",
            }

        python_call = _normalize_python_call_expression(payload, tool_name)
        if python_call is not None:
            return python_call, {
                "source_format": source_format,
                "argument_format": "python_call",
            }

        raw = _stringify_payload(payload)
        logger.warning("Failed to parse tool arguments into an object: %.100s", raw)
        meta = _build_unresolved_meta(
            source_format=source_format,
            argument_format="raw_text",
            raw_arguments=raw,
            normalization_error="Unable to normalize tool arguments to an object",
        )
        return {"_raw_arguments": raw}, meta

    mapping = _string_key_dict_or_none(payload)
    if mapping is not None:
        return mapping, {
            "source_format": source_format,
            "argument_format": "object",
        }

    raw = _stringify_payload(payload)
    logger.warning("Unsupported non-object tool argument payload: %.100s", raw)
    meta = _build_unresolved_meta(
        source_format=source_format,
        argument_format=type(payload).__name__,
        raw_arguments=raw,
        normalization_error="Tool arguments must be an object-shaped payload",
    )
    return {"_raw_arguments": raw}, meta


def build_tool_call(
    *,
    call_id: str,
    name: str,
    payload: Any,
    source_format: str,
) -> ToolCall:
    """Build a normalized ToolCall from an arbitrary inbound payload."""
    arguments, meta = normalize_tool_arguments(
        payload,
        tool_name=name,
        source_format=source_format,
    )
    return ToolCall(
        id=call_id,
        name=name,
        arguments=arguments,
        meta=meta,
    )


def _first_present(mapping: dict[str, Any], *keys: str) -> Any:
    """Return the first present key value from mapping."""
    for key in keys:
        if key in mapping:
            return mapping[key]
    return _UNSET


def _first_string(mapping: dict[str, Any], *keys: str) -> str:
    """Return the first present string-ish value from mapping."""
    value = _first_present(mapping, *keys)
    if value is _UNSET:
        return ""
    return str(value)


def parse_openai_chat_tool_calls(
    tool_calls_data: list[dict[str, Any]],
    *,
    source_format: str = "openai_chat",
) -> tuple[ToolCall, ...]:
    """Parse chat-completions style tool calls."""
    result: list[ToolCall] = []
    for item in tool_calls_data:
        function_data = item.get("function")
        if isinstance(function_data, dict):
            name = _first_string(function_data, "name") or _first_string(item, "name")
            payload = _first_present(function_data, "arguments", "input", "args")
            if payload is _UNSET:
                payload = _first_present(item, "arguments", "input", "args")
        else:
            name = _first_string(item, "name")
            payload = _first_present(item, "arguments", "input", "args")
            if payload is _UNSET:
                payload = {}

        call_id = _first_string(item, "id", "call_id", "tool_call_id")
        result.append(
            build_tool_call(
                call_id=call_id,
                name=name,
                payload={} if payload is _UNSET else payload,
                source_format=source_format,
            )
        )

    return tuple(result)


def parse_anthropic_content_blocks(
    content_blocks: list[dict[str, Any]],
    *,
    source_format: str = "anthropic_content_blocks",
) -> tuple[str, tuple[ToolCall, ...]]:
    """Parse Anthropic-style content blocks into text and tool calls."""
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []

    for block in content_blocks:
        block_type = block.get("type")
        if block_type == "text":
            text_parts.append(str(block.get("text", "")))
            continue

        if block_type == "tool_use":
            tool_calls.append(
                build_tool_call(
                    call_id=_first_string(block, "id", "tool_use_id"),
                    name=_first_string(block, "name"),
                    payload=block.get("input", {}),
                    source_format=source_format,
                )
            )

    return "".join(text_parts), tuple(tool_calls)


def _extract_responses_text_from_message(message_item: dict[str, Any]) -> str:
    """Extract text from a Responses API message item."""
    content = message_item.get("content")
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue

        block_type = str(block.get("type", ""))
        if block_type in {"output_text", "text"}:
            text = block.get("text", "")
            if isinstance(text, dict):
                text = text.get("value", "")
            parts.append(str(text))

    return "".join(parts)


def parse_responses_output_items(
    output_items: list[dict[str, Any]],
    *,
    source_format: str = "openai_responses",
) -> tuple[str, tuple[ToolCall, ...]]:
    """Parse a Responses API output array into text and tool calls."""
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []

    for item in output_items:
        item_type = str(item.get("type", ""))

        if item_type == "message":
            message_text = _extract_responses_text_from_message(item)
            if message_text:
                text_parts.append(message_text)
            continue

        if item_type in {"function_call", "custom_tool_call", "tool_call"}:
            payload = _first_present(item, "arguments", "input", "args")
            if payload is _UNSET:
                payload = {}
            tool_calls.append(
                build_tool_call(
                    call_id=_first_string(item, "call_id", "id", "tool_call_id"),
                    name=_first_string(item, "name"),
                    payload=payload,
                    source_format=source_format,
                )
            )
            continue

        if "functionCall" in item and isinstance(item["functionCall"], dict):
            function_call = item["functionCall"]
            payload = _first_present(function_call, "args", "arguments", "input")
            if payload is _UNSET:
                payload = {}
            tool_calls.append(
                build_tool_call(
                    call_id=_first_string(item, "id", "call_id"),
                    name=_first_string(function_call, "name"),
                    payload=payload,
                    source_format="gemini_function_call",
                )
            )
            continue

        if item_type in {"output_text", "text"}:
            text = item.get("text", "")
            if isinstance(text, dict):
                text = text.get("value", "")
            if text:
                text_parts.append(str(text))

    return "".join(text_parts), tuple(tool_calls)


@dataclass
class StreamingToolCallAccumulator:
    """Provider-agnostic tool-call accumulator for streaming protocols."""

    source_format: str
    id: str = ""
    name: str = ""
    _string_fragments: list[str] = field(default_factory=list)
    _object_payload: Any = _UNSET
    _mixed_payload_types: bool = False

    @property
    def argument_text(self) -> str:
        """Return the accumulated string payload, if any."""
        return "".join(self._string_fragments)

    @property
    def payload_object(self) -> Any:
        """Return the accumulated object payload, if any."""
        return None if self._object_payload is _UNSET else self._object_payload

    def add_payload(self, payload: Any) -> None:
        """Add a streamed argument fragment or whole payload."""
        if payload is None or payload == "":
            return

        if isinstance(payload, str):
            if self._object_payload is not _UNSET:
                self._mixed_payload_types = True
            self._string_fragments.append(payload)
            return

        if self._string_fragments:
            self._mixed_payload_types = True

        if self._object_payload is _UNSET:
            self._object_payload = payload
            return

        if isinstance(self._object_payload, dict) and isinstance(payload, dict):
            self._object_payload.update(payload)
            return

        if payload != self._object_payload:
            self._mixed_payload_types = True

    def replace_payload(self, payload: Any) -> None:
        """Replace the accumulated payload with a terminal snapshot."""
        if payload is None or payload == "":
            return

        self._string_fragments.clear()
        self._object_payload = _UNSET
        self._mixed_payload_types = False

        if isinstance(payload, str):
            self._string_fragments.append(payload)
            return

        self._object_payload = payload

    def build_tool_call(self) -> ToolCall:
        """Finalize the accumulated payload into a normalized ToolCall."""
        if self._mixed_payload_types:
            raw_payload = "".join(self._string_fragments) or _stringify_payload(
                self._object_payload if self._object_payload is not _UNSET else ""
            )
            logger.warning(
                "Failed to normalize mixed streaming tool payload: %.100s",
                raw_payload,
            )
            return ToolCall(
                id=self.id,
                name=self.name,
                arguments={"_raw_arguments": raw_payload},
                meta=_build_unresolved_meta(
                    source_format=self.source_format,
                    argument_format="mixed_stream_payload",
                    raw_arguments=raw_payload,
                    normalization_error=(
                        "Streaming tool-call payload mixed string and object argument forms"
                    ),
                ),
            )

        if self._string_fragments:
            payload: Any = "".join(self._string_fragments)
        elif self._object_payload is not _UNSET:
            payload = self._object_payload
        else:
            payload = {}

        return build_tool_call(
            call_id=self.id,
            name=self.name,
            payload=payload,
            source_format=self.source_format,
        )
