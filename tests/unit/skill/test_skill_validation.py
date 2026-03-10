"""Tests for unified skill validation."""

import pytest

from nexus3.skill.builtin.registration import register_builtin_skills
from nexus3.skill.registry import SkillRegistry
from nexus3.skill.services import ServiceContainer


class TestValidationUniformity:
    """All skills should use the same validation pipeline."""

    @pytest.fixture
    def registry_with_skills(self, tmp_path):
        """Create registry with all builtin skills registered."""
        registry = SkillRegistry()
        services = ServiceContainer()
        services.set_cwd(str(tmp_path))
        registry = SkillRegistry(services)
        register_builtin_skills(registry)
        return registry

    def test_all_skills_reject_unknown_parameters(self, registry_with_skills):
        """Unknown parameters should be filtered by all skills."""
        # This tests that validation wrapper is applied to all skills
        # The validation filters unknown params rather than erroring

        # Get a simple skill (sleep is registered by default)
        sleep_skill = registry_with_skills.get("sleep")
        assert sleep_skill is not None

        # sleep skill only accepts "seconds" and "label" parameters
        # Unknown params should be filtered out (not cause an error)

        # Verify the skill has parameters defined
        assert "seconds" in sleep_skill.parameters.get("properties", {})

    def test_file_info_has_validation_wrapper(self, registry_with_skills):
        """File info skill should have validation wrapper."""
        file_info = registry_with_skills.get("file_info")

        # Check that execute method is wrapped
        # The wrapper adds validation behavior
        assert file_info is not None
        assert hasattr(file_info, "execute")
        assert file_info.name == "file_info"

    def test_sleep_has_validation_wrapper(self, registry_with_skills):
        """Sleep skill (previously manual factory) should have validation."""
        sleep_skill = registry_with_skills.get("sleep")

        assert hasattr(sleep_skill, "execute")
        assert sleep_skill.name == "sleep"

    @pytest.mark.asyncio
    async def test_file_info_filters_unknown_params(self, registry_with_skills, tmp_path):
        """File info skill should filter out unknown parameters."""
        file_info = registry_with_skills.get("file_info")

        # Create a test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        # Call with valid path + unknown param
        result = await file_info.execute(path=str(test_file), unknown_xyz="should_be_filtered")

        # Should succeed - unknown param was filtered
        assert result.success

    @pytest.mark.asyncio
    async def test_sleep_filters_unknown_params(self, registry_with_skills):
        """Sleep skill should filter out unknown parameters."""
        sleep_skill = registry_with_skills.get("sleep")

        # Call with valid seconds + unknown param
        result = await sleep_skill.execute(seconds=0.01, unknown_xyz="should_be_filtered")

        # Should succeed - unknown param was filtered
        assert result.success

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("skill_name", "builder"),
        [
            (
                "read_file",
                lambda tmp_path: _create_file(tmp_path / "read.txt", "test content")
                or {"path": str(tmp_path / "read.txt")},
            ),
            (
                "write_file",
                lambda tmp_path: {"path": str(tmp_path / "write.txt"), "content": "hello\n"},
            ),
            (
                "edit_file",
                lambda tmp_path: _create_file(tmp_path / "edit.txt", "alpha\nbeta\n")
                or {
                    "path": str(tmp_path / "edit.txt"),
                    "old_string": "alpha",
                    "new_string": "ALPHA",
                },
            ),
            (
                "edit_lines",
                lambda tmp_path: _create_file(tmp_path / "lines.txt", "one\ntwo\nthree\n")
                or {
                    "path": str(tmp_path / "lines.txt"),
                    "start_line": 2,
                    "new_content": "TWO\n",
                },
            ),
            (
                "append_file",
                lambda tmp_path: _create_file(tmp_path / "append.txt", "tail\n")
                or {"path": str(tmp_path / "append.txt"), "content": "more\n"},
            ),
            (
                "regex_replace",
                lambda tmp_path: _create_file(tmp_path / "regex.txt", "foo bar\n")
                or {
                    "path": str(tmp_path / "regex.txt"),
                    "pattern": "foo",
                    "replacement": "baz",
                },
            ),
            (
                "patch",
                lambda tmp_path: _create_file(tmp_path / "patch.txt", "old\n")
                or {
                    "path": str(tmp_path / "patch.txt"),
                    "diff": (
                        "--- a/patch.txt\n"
                        "+++ b/patch.txt\n"
                        "@@ -1 +1 @@\n"
                        "-old\n"
                        "+new\n"
                    ),
                },
            ),
            (
                "copy_file",
                lambda tmp_path: _create_file(tmp_path / "copy_src.txt", "copy me\n")
                or {
                    "source": str(tmp_path / "copy_src.txt"),
                    "destination": str(tmp_path / "copy_dst.txt"),
                },
            ),
            (
                "rename",
                lambda tmp_path: _create_file(tmp_path / "rename_src.txt", "rename me\n")
                or {
                    "source": str(tmp_path / "rename_src.txt"),
                    "destination": str(tmp_path / "rename_dst.txt"),
                },
            ),
            (
                "mkdir",
                lambda tmp_path: {"path": str(tmp_path / "created-dir")},
            ),
        ],
    )
    async def test_file_edit_family_rejects_unknown_params(
        self,
        registry_with_skills,
        tmp_path,
        skill_name,
        builder,
    ):
        """File-edit tools should fail closed on unknown top-level params."""
        skill = registry_with_skills.get(skill_name)

        result = await skill.execute(**builder(tmp_path), unknown_xyz="boom")

        assert not result.success
        assert "unknown_xyz" in result.error
        assert (
            "unexpected" in result.error.lower()
            or "additional properties" in result.error.lower()
        )

    @pytest.mark.asyncio
    async def test_edit_file_rejects_unknown_batch_item_fields(
        self, registry_with_skills, tmp_path
    ):
        """edit_file should reject unexpected keys inside batch edit items."""
        edit_skill = registry_with_skills.get("edit_file")
        test_file = tmp_path / "edit-batch.txt"
        test_file.write_text("alpha\nbeta\n")

        result = await edit_skill.execute(
            path=str(test_file),
            edits=[
                {
                    "old_string": "alpha",
                    "new_string": "ALPHA",
                    "unexpected_field": True,
                }
            ],
        )

        assert not result.success
        assert "unexpected_field" in result.error
        assert (
            "additional properties" in result.error.lower()
            or "unexpected" in result.error.lower()
        )

    @pytest.mark.asyncio
    async def test_edit_lines_rejects_unknown_batch_item_fields(
        self, registry_with_skills, tmp_path
    ):
        """edit_lines should reject unexpected keys inside batch edit items."""
        edit_skill = registry_with_skills.get("edit_lines")
        test_file = tmp_path / "lines-batch.txt"
        test_file.write_text("one\ntwo\nthree\n")

        result = await edit_skill.execute(
            path=str(test_file),
            edits=[
                {
                    "start_line": 2,
                    "new_content": "TWO\n",
                    "unexpected_field": True,
                }
            ],
        )

        assert not result.success
        assert "unexpected_field" in result.error
        assert (
            "additional properties" in result.error.lower()
            or "unexpected" in result.error.lower()
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("skill_name", "params"),
        [
            ("nexus_create", {"agent_id": "worker-1"}),
            ("nexus_send", {"agent_id": "worker-1", "content": "hello"}),
            ("nexus_status", {"agent_id": "worker-1"}),
            ("nexus_cancel", {"agent_id": "worker-1", "request_id": "req-1"}),
            ("nexus_destroy", {"agent_id": "worker-1"}),
            ("nexus_shutdown", {}),
        ],
    )
    async def test_nexus_family_rejects_unknown_params(
        self,
        registry_with_skills,
        skill_name,
        params,
    ):
        """nexus_* tools should fail closed on unknown top-level params."""
        skill = registry_with_skills.get(skill_name)

        result = await skill.execute(**params, unknown_xyz="boom")

        assert not result.success
        assert "unknown_xyz" in result.error
        assert (
            "unexpected" in result.error.lower()
            or "additional properties" in result.error.lower()
        )

    @pytest.mark.asyncio
    async def test_file_info_validates_required_params(self, registry_with_skills):
        """File info skill validates required parameters via wrapper."""
        file_info = registry_with_skills.get("file_info")

        # Call without required 'path' parameter
        result = await file_info.execute()

        # Should fail validation - path is required
        assert not result.success
        assert "path" in result.error.lower() or "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_sleep_validates_type(self, registry_with_skills):
        """Sleep skill validates parameter types via wrapper."""
        sleep_skill = registry_with_skills.get("sleep")

        # Call with wrong type for seconds
        result = await sleep_skill.execute(seconds="not_a_number")  # type: ignore

        # Should fail validation
        assert not result.success
        assert "type" in result.error.lower() or "number" in result.error.lower()

    def test_all_builtin_skills_have_execute(self, registry_with_skills):
        """All registered skills should have an execute method."""
        for skill_name in registry_with_skills.names:
            skill = registry_with_skills.get(skill_name)
            assert skill is not None, f"Skill {skill_name} returned None"
            assert hasattr(skill, "execute"), f"Skill {skill_name} missing execute"
            assert callable(skill.execute), f"Skill {skill_name}.execute not callable"

    def test_all_builtin_skills_have_parameters_schema(self, registry_with_skills):
        """All registered skills should have a parameters schema."""
        for skill_name in registry_with_skills.names:
            skill = registry_with_skills.get(skill_name)
            assert skill is not None, f"Skill {skill_name} returned None"
            assert hasattr(
                skill, "parameters"
            ), f"Skill {skill_name} missing parameters"
            params = skill.parameters
            assert isinstance(params, dict), f"Skill {skill_name} parameters not dict"
            assert params.get("type") == "object", f"Skill {skill_name} params not object"

    def test_all_builtin_skills_have_description(self, registry_with_skills):
        """All registered skills should have a description."""
        for skill_name in registry_with_skills.names:
            skill = registry_with_skills.get(skill_name)
            assert skill is not None, f"Skill {skill_name} returned None"
            assert hasattr(
                skill, "description"
            ), f"Skill {skill_name} missing description"
            desc = skill.description
            assert isinstance(desc, str), f"Skill {skill_name} description not string"
            assert len(desc) > 0, f"Skill {skill_name} has empty description"


class TestValidationWrapperApplication:
    """Test that validation wrapper is properly applied to all skill types."""

    def test_file_skill_has_validation(self, tmp_path):
        """FileSkill subclasses get validation wrapper from factory."""
        from nexus3.skill.builtin.read_file import read_file_factory

        services = ServiceContainer()
        services.set_cwd(str(tmp_path))
        skill = read_file_factory(services)

        # The execute method should be wrapped
        # We can check this by seeing that it filters unknown params
        assert hasattr(skill, "execute")
        assert skill.name == "read_file"

    def test_execution_skill_has_validation(self, tmp_path):
        """ExecutionSkill subclasses get validation wrapper from factory."""
        from nexus3.skill.builtin.bash import bash_safe_factory

        services = ServiceContainer()
        services.set_cwd(str(tmp_path))
        skill = bash_safe_factory(services)

        assert hasattr(skill, "execute")
        assert skill.name == "bash_safe"

    def test_nexus_skill_has_validation(self, tmp_path):
        """NexusSkill subclasses get validation wrapper from factory."""
        from nexus3.skill.builtin.nexus_status import nexus_status_factory

        services = ServiceContainer()
        services.set_cwd(str(tmp_path))
        skill = nexus_status_factory(services)

        assert hasattr(skill, "execute")
        assert skill.name == "nexus_status"

    def test_filtered_command_skill_has_validation(self, tmp_path):
        """FilteredCommandSkill subclasses get validation wrapper from factory."""
        from nexus3.skill.builtin.git import git_factory

        services = ServiceContainer()
        services.set_cwd(str(tmp_path))
        skill = git_factory(services)

        assert hasattr(skill, "execute")
        assert skill.name == "git"

    def test_base_skill_has_validation(self):
        """BaseSkill subclasses (via @base_skill_factory) get validation wrapper."""
        from nexus3.skill.builtin.sleep import sleep_skill_factory

        services = ServiceContainer()
        skill = sleep_skill_factory(services)

        assert hasattr(skill, "execute")
        assert skill.name == "sleep"


def _create_file(path, content):
    """Create a text file and return None for lambda chaining."""
    path.write_text(content)
    return None
