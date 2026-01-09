"""Unit tests for agent naming conventions and helpers.

Tests for:
- is_temp_agent(): Detect temp agent IDs (starting with '.')
- generate_temp_id(): Generate sequential temp IDs (.1, .2, etc.)
- AgentPool.create_temp(): Create temp agents with auto-generated IDs
- AgentPool.is_temp(): Convenience method for temp detection
- AgentPool.list() is_temp field: Distinguish temp vs named agents
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nexus3.rpc.pool import (
    AgentPool,
    SharedComponents,
    generate_temp_id,
    is_temp_agent,
)

# -----------------------------------------------------------------------------
# is_temp_agent Tests
# -----------------------------------------------------------------------------


class TestIsTempAgent:
    """Tests for is_temp_agent() function."""

    def test_temp_agent_single_digit(self):
        """Temp agents with single digit IDs are detected."""
        assert is_temp_agent(".1") is True
        assert is_temp_agent(".2") is True
        assert is_temp_agent(".9") is True

    def test_temp_agent_multi_digit(self):
        """Temp agents with multi-digit IDs are detected."""
        assert is_temp_agent(".10") is True
        assert is_temp_agent(".99") is True
        assert is_temp_agent(".100") is True

    def test_temp_agent_named_temp(self):
        """Temp agents with descriptive names are detected."""
        assert is_temp_agent(".quick-test") is True
        assert is_temp_agent(".scratch") is True
        assert is_temp_agent(".temp-worker") is True

    def test_named_agent_simple(self):
        """Simple named agents are not temp."""
        assert is_temp_agent("main") is False
        assert is_temp_agent("worker") is False
        assert is_temp_agent("agent") is False

    def test_named_agent_with_numbers(self):
        """Named agents with numbers are not temp."""
        assert is_temp_agent("worker-1") is False
        assert is_temp_agent("agent-42") is False
        assert is_temp_agent("my-project") is False

    def test_named_agent_complex(self):
        """Named agents with complex names are not temp."""
        assert is_temp_agent("my-project-dev") is False
        assert is_temp_agent("research_assistant") is False
        assert is_temp_agent("code-review-bot") is False

    def test_edge_case_just_dot(self):
        """Just a dot is technically a temp agent."""
        assert is_temp_agent(".") is True

    def test_edge_case_empty_string(self):
        """Empty string is not a temp agent."""
        assert is_temp_agent("") is False

    def test_edge_case_dot_in_middle(self):
        """Dot in middle of name is not a temp agent."""
        assert is_temp_agent("my.agent") is False
        assert is_temp_agent("v1.0") is False


# -----------------------------------------------------------------------------
# generate_temp_id Tests
# -----------------------------------------------------------------------------


class TestGenerateTempId:
    """Tests for generate_temp_id() function."""

    def test_empty_set_returns_dot_one(self):
        """With no existing IDs, returns .1."""
        assert generate_temp_id(set()) == ".1"

    def test_skips_existing_ids(self):
        """Generates next available ID, skipping existing ones."""
        assert generate_temp_id({".1"}) == ".2"
        assert generate_temp_id({".1", ".2"}) == ".3"
        assert generate_temp_id({".1", ".2", ".3"}) == ".4"

    def test_fills_gaps(self):
        """Fills gaps in the sequence."""
        assert generate_temp_id({".2", ".3"}) == ".1"
        assert generate_temp_id({".1", ".3"}) == ".2"
        assert generate_temp_id({".1", ".2", ".4"}) == ".3"

    def test_ignores_named_agents(self):
        """Named agents don't affect temp ID generation."""
        assert generate_temp_id({"main", "worker-1"}) == ".1"
        assert generate_temp_id({".1", "main", "worker-1"}) == ".2"

    def test_ignores_non_numeric_temp_agents(self):
        """Non-numeric temp agents don't affect sequence."""
        assert generate_temp_id({".quick-test", ".scratch"}) == ".1"
        assert generate_temp_id({".1", ".quick-test"}) == ".2"

    def test_large_numbers(self):
        """Handles large sequences correctly."""
        existing = {f".{i}" for i in range(1, 100)}
        assert generate_temp_id(existing) == ".100"

    def test_mixed_agents(self):
        """Handles mix of temp, named, and numeric temp agents."""
        existing = {".1", ".2", "main", ".quick-test", "worker-1", ".5"}
        # Should find .3 as next available
        assert generate_temp_id(existing) == ".3"


# -----------------------------------------------------------------------------
# AgentPool.create_temp() Tests
# -----------------------------------------------------------------------------


def create_mock_shared_components(tmp_path: Path) -> SharedComponents:
    """Create SharedComponents with mocks for testing."""
    mock_config = MagicMock()
    mock_provider = MagicMock()

    # Mock prompt_loader.load() to return a LoadedPrompt-like object
    mock_prompt_loader = MagicMock()
    mock_loaded_prompt = MagicMock()
    mock_loaded_prompt.content = "You are a test assistant."
    mock_prompt_loader.load.return_value = mock_loaded_prompt

    return SharedComponents(
        config=mock_config,
        provider=mock_provider,
        prompt_loader=mock_prompt_loader,
        base_log_dir=tmp_path / "logs",
    )


class TestAgentPoolCreateTemp:
    """Tests for AgentPool.create_temp() method."""

    @pytest.mark.asyncio
    async def test_create_temp_first_agent(self, tmp_path):
        """First temp agent gets ID .1."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            agent = await pool.create_temp()

            assert agent.agent_id == ".1"
            assert ".1" in pool

    @pytest.mark.asyncio
    async def test_create_temp_sequential(self, tmp_path):
        """Multiple temp agents get sequential IDs."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            agent1 = await pool.create_temp()
            agent2 = await pool.create_temp()
            agent3 = await pool.create_temp()

            assert agent1.agent_id == ".1"
            assert agent2.agent_id == ".2"
            assert agent3.agent_id == ".3"

    @pytest.mark.asyncio
    async def test_create_temp_fills_gaps(self, tmp_path):
        """create_temp fills gaps in temp ID sequence."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            # Create .1 and .2
            await pool.create_temp()
            await pool.create_temp()
            # Destroy .1
            await pool.destroy(".1")
            # Next temp should fill the gap
            agent = await pool.create_temp()
            assert agent.agent_id == ".1"

    @pytest.mark.asyncio
    async def test_create_temp_with_named_agents(self, tmp_path):
        """create_temp works alongside named agents."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            # Create named agent
            await pool.create(agent_id="main")
            # Create temp agents
            temp1 = await pool.create_temp()
            temp2 = await pool.create_temp()

            assert temp1.agent_id == ".1"
            assert temp2.agent_id == ".2"
            # Named agent still exists
            assert "main" in pool

    @pytest.mark.asyncio
    async def test_create_temp_with_config(self, tmp_path):
        """create_temp accepts config with system_prompt."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            from nexus3.rpc.pool import AgentConfig

            pool = AgentPool(shared)
            config = AgentConfig(system_prompt="Custom prompt")
            agent = await pool.create_temp(config=config)

            assert agent.agent_id == ".1"
            # System prompt would be set on the agent

    @pytest.mark.asyncio
    async def test_create_temp_ignores_config_agent_id(self, tmp_path):
        """create_temp ignores agent_id in config."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            from nexus3.rpc.pool import AgentConfig

            pool = AgentPool(shared)
            config = AgentConfig(agent_id="ignored-id")
            agent = await pool.create_temp(config=config)

            # Should still get temp ID, not the one from config
            assert agent.agent_id == ".1"
            assert "ignored-id" not in pool


# -----------------------------------------------------------------------------
# AgentPool.is_temp() Tests
# -----------------------------------------------------------------------------


class TestAgentPoolIsTemp:
    """Tests for AgentPool.is_temp() method."""

    def test_is_temp_returns_true_for_temp(self, tmp_path):
        """is_temp returns True for temp agent IDs."""
        shared = create_mock_shared_components(tmp_path)
        pool = AgentPool(shared)

        assert pool.is_temp(".1") is True
        assert pool.is_temp(".99") is True
        assert pool.is_temp(".quick-test") is True

    def test_is_temp_returns_false_for_named(self, tmp_path):
        """is_temp returns False for named agent IDs."""
        shared = create_mock_shared_components(tmp_path)
        pool = AgentPool(shared)

        assert pool.is_temp("main") is False
        assert pool.is_temp("worker-1") is False
        assert pool.is_temp("my-project") is False


# -----------------------------------------------------------------------------
# AgentPool.list() is_temp Field Tests
# -----------------------------------------------------------------------------


class TestAgentPoolListIsTemp:
    """Tests for is_temp field in AgentPool.list() output."""

    @pytest.mark.asyncio
    async def test_list_includes_is_temp_field(self, tmp_path):
        """list() includes is_temp field for each agent."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            await pool.create(agent_id="main")

            agents = pool.list()
            assert len(agents) == 1
            assert "is_temp" in agents[0]

    @pytest.mark.asyncio
    async def test_list_is_temp_true_for_temp_agents(self, tmp_path):
        """list() returns is_temp=True for temp agents."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            await pool.create_temp()

            agents = pool.list()
            assert agents[0]["agent_id"] == ".1"
            assert agents[0]["is_temp"] is True

    @pytest.mark.asyncio
    async def test_list_is_temp_false_for_named_agents(self, tmp_path):
        """list() returns is_temp=False for named agents."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            await pool.create(agent_id="main")

            agents = pool.list()
            assert agents[0]["agent_id"] == "main"
            assert agents[0]["is_temp"] is False

    @pytest.mark.asyncio
    async def test_list_mixed_agents(self, tmp_path):
        """list() correctly identifies temp vs named in mixed pool."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            await pool.create(agent_id="main")
            await pool.create_temp()  # .1
            await pool.create(agent_id="worker-1")
            await pool.create_temp()  # .2

            agents = pool.list()
            agent_map = {a["agent_id"]: a["is_temp"] for a in agents}

            assert agent_map["main"] is False
            assert agent_map[".1"] is True
            assert agent_map["worker-1"] is False
            assert agent_map[".2"] is True
