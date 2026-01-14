"""Tests for skill parameter validation decorator."""

from typing import Any

import pytest

from nexus3.core.types import ToolResult
from nexus3.skill.base import validate_skill_parameters


class MockSkill:
    """Mock skill for testing the validation decorator."""

    def __init__(self, schema: dict[str, Any]):
        self._schema = schema
        self._name = "mock_skill"

    @property
    def name(self) -> str:
        return self._name

    @property
    def parameters(self) -> dict[str, Any]:
        return self._schema


class TestValidateSkillParameters:
    """Tests for the validate_skill_parameters decorator."""

    @pytest.mark.asyncio
    async def test_valid_params_pass_through(self) -> None:
        """Valid parameters are passed to the execute method."""
        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "count": {"type": "integer"},
            },
            "required": ["path"],
        }

        class TestSkill(MockSkill):
            @validate_skill_parameters()
            async def execute(self, path: str = "", count: int = 1, **kwargs: Any) -> ToolResult:
                return ToolResult(output=f"path={path}, count={count}")

        skill = TestSkill(schema)
        result = await skill.execute(path="/test/file", count=5)
        assert result.success
        assert result.output == "path=/test/file, count=5"

    @pytest.mark.asyncio
    async def test_missing_required_param_returns_error(self) -> None:
        """Missing required parameter returns error ToolResult."""
        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
            },
            "required": ["path"],
        }

        class TestSkill(MockSkill):
            @validate_skill_parameters()
            async def execute(self, path: str = "", **kwargs: Any) -> ToolResult:
                return ToolResult(output=f"path={path}")

        skill = TestSkill(schema)
        result = await skill.execute()  # Missing required 'path'
        assert not result.success
        assert "path" in result.error.lower()
        assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_wrong_type_returns_error(self) -> None:
        """Wrong parameter type returns error ToolResult."""
        schema = {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
            },
        }

        class TestSkill(MockSkill):
            @validate_skill_parameters()
            async def execute(self, count: int = 0, **kwargs: Any) -> ToolResult:
                return ToolResult(output=f"count={count}")

        skill = TestSkill(schema)
        result = await skill.execute(count="not_an_int")  # type: ignore
        assert not result.success
        assert "type" in result.error.lower() or "integer" in result.error.lower()

    @pytest.mark.asyncio
    async def test_extra_params_filtered_non_strict(self) -> None:
        """In non-strict mode, extra parameters are filtered out."""
        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
            },
        }

        received_kwargs: dict[str, Any] = {}

        class TestSkill(MockSkill):
            @validate_skill_parameters(strict=False)
            async def execute(self, **kwargs: Any) -> ToolResult:
                received_kwargs.update(kwargs)
                return ToolResult(output="ok")

        skill = TestSkill(schema)
        result = await skill.execute(path="/test", extra_param="ignored")
        assert result.success
        assert "path" in received_kwargs
        assert "extra_param" not in received_kwargs

    @pytest.mark.asyncio
    async def test_extra_params_rejected_strict(self) -> None:
        """In strict mode, extra parameters return an error."""
        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
            },
        }

        class TestSkill(MockSkill):
            @validate_skill_parameters(strict=True)
            async def execute(self, path: str = "", **kwargs: Any) -> ToolResult:
                return ToolResult(output=f"path={path}")

        skill = TestSkill(schema)
        result = await skill.execute(path="/test", extra_param="rejected")
        assert not result.success
        assert "unexpected" in result.error.lower()
        assert "extra_param" in result.error.lower()

    @pytest.mark.asyncio
    async def test_allowed_internal_params_pass_through(self) -> None:
        """Whitelisted internal params (_parallel) are passed through."""
        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
            },
        }

        received_kwargs: dict[str, Any] = {}

        class TestSkill(MockSkill):
            @validate_skill_parameters(strict=True)
            async def execute(self, **kwargs: Any) -> ToolResult:
                received_kwargs.update(kwargs)
                return ToolResult(output="ok")

        skill = TestSkill(schema)
        result = await skill.execute(path="/test", _parallel=True)
        assert result.success
        assert "_parallel" in received_kwargs

    @pytest.mark.asyncio
    async def test_enum_validation(self) -> None:
        """Enum parameter validation with friendly error."""
        schema = {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["read", "write", "append"]},
            },
            "required": ["mode"],
        }

        class TestSkill(MockSkill):
            @validate_skill_parameters()
            async def execute(self, mode: str = "", **kwargs: Any) -> ToolResult:
                return ToolResult(output=f"mode={mode}")

        skill = TestSkill(schema)
        result = await skill.execute(mode="invalid")
        assert not result.success
        # Should mention the valid options
        assert "read" in result.error or "enum" in result.error.lower()

    @pytest.mark.asyncio
    async def test_minimum_validation(self) -> None:
        """Minimum value validation."""
        schema = {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "minimum": 1},
            },
        }

        class TestSkill(MockSkill):
            @validate_skill_parameters()
            async def execute(self, count: int = 1, **kwargs: Any) -> ToolResult:
                return ToolResult(output=f"count={count}")

        skill = TestSkill(schema)
        result = await skill.execute(count=0)
        assert not result.success
        assert "minimum" in result.error.lower() or "less than" in result.error.lower()

    @pytest.mark.asyncio
    async def test_optional_param_with_default(self) -> None:
        """Optional parameters work correctly."""
        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["path"],
        }

        class TestSkill(MockSkill):
            @validate_skill_parameters()
            async def execute(self, path: str = "", limit: int = 100, **kwargs: Any) -> ToolResult:
                return ToolResult(output=f"path={path}, limit={limit}")

        skill = TestSkill(schema)
        # Call with only required param
        result = await skill.execute(path="/test")
        assert result.success
        # The method default is used since limit wasn't in kwargs
        assert "limit=100" in result.output

    @pytest.mark.asyncio
    async def test_error_includes_skill_name(self) -> None:
        """Error messages include the skill name for context."""
        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
            },
            "required": ["path"],
        }

        class TestSkill(MockSkill):
            @validate_skill_parameters()
            async def execute(self, path: str = "", **kwargs: Any) -> ToolResult:
                return ToolResult(output=f"path={path}")

        skill = TestSkill(schema)
        skill._name = "test_skill_name"
        result = await skill.execute()
        assert not result.success
        assert "test_skill_name" in result.error
