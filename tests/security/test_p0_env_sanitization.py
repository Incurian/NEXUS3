"""P0.3: Test that subprocess execution does not leak secret environment variables.

This tests the security bug where bash and run_python skills passed the
full os.environ to subprocesses, potentially leaking API keys, tokens,
and other secrets.

The fix uses a minimal safe environment allowlist.
"""

import os

import pytest

from nexus3.skill.builtin.env import (
    DEFAULT_PATH,
    SAFE_ENV_VARS,
    filter_env,
    get_full_env,
    get_safe_env,
)


class TestSafeEnvVars:
    """Test the SAFE_ENV_VARS constant contains expected values."""

    def test_contains_path(self) -> None:
        """PATH is essential for finding executables."""
        assert "PATH" in SAFE_ENV_VARS

    def test_contains_home(self) -> None:
        """HOME is needed for many programs."""
        assert "HOME" in SAFE_ENV_VARS

    def test_contains_locale(self) -> None:
        """Locale variables are safe and needed for i18n."""
        assert "LANG" in SAFE_ENV_VARS
        assert "LC_ALL" in SAFE_ENV_VARS

    def test_does_not_contain_secrets(self) -> None:
        """Common secret variable names must NOT be in safe list."""
        dangerous = {
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "OPENROUTER_API_KEY",
            "GITHUB_TOKEN",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "DATABASE_URL",
            "DB_PASSWORD",
            "SECRET_KEY",
            "API_KEY",
            "PASSWORD",
            "TOKEN",
            "NEXUS3_API_KEY",
        }
        leaked = dangerous & SAFE_ENV_VARS
        assert not leaked, f"SECURITY BUG: Dangerous vars in safe list: {leaked}"


class TestGetSafeEnv:
    """Test get_safe_env() filters environment correctly."""

    def test_filters_out_secrets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CRITICAL: Secret variables must NOT be passed to subprocesses."""
        # Set up a "secret" env var
        monkeypatch.setenv("SECRET_FOR_TEST", "leaked_secret_123")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        monkeypatch.setenv("PATH", "/usr/bin:/bin")

        env = get_safe_env()

        assert "SECRET_FOR_TEST" not in env, (
            "SECURITY BUG: Arbitrary env var leaked to subprocess"
        )
        assert "OPENAI_API_KEY" not in env, (
            "SECURITY BUG: API key leaked to subprocess"
        )

    def test_preserves_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """PATH must be preserved for finding executables."""
        monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin:/bin")

        env = get_safe_env()

        assert "PATH" in env
        assert env["PATH"] == "/usr/local/bin:/usr/bin:/bin"

    def test_preserves_home(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """HOME should be preserved if set."""
        monkeypatch.setenv("HOME", "/home/testuser")

        env = get_safe_env()

        assert env.get("HOME") == "/home/testuser"

    def test_provides_default_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default PATH provided if not set."""
        monkeypatch.delenv("PATH", raising=False)

        env = get_safe_env()

        assert "PATH" in env
        assert env["PATH"]  # Non-empty

    def test_sets_pwd_from_cwd(self) -> None:
        """PWD is set to cwd argument if provided."""
        env = get_safe_env(cwd="/some/work/dir")

        assert env.get("PWD") == "/some/work/dir"

    def test_only_safe_vars_copied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only explicitly safe variables should be in output."""
        # Set a bunch of vars
        monkeypatch.setenv("PATH", "/bin")
        monkeypatch.setenv("HOME", "/home/test")
        monkeypatch.setenv("CUSTOM_VAR", "should_not_leak")
        monkeypatch.setenv("ANOTHER_VAR", "also_should_not_leak")

        env = get_safe_env()

        for key in env:
            assert key in SAFE_ENV_VARS or key == "PWD", (
                f"SECURITY BUG: Unexpected var '{key}' in safe env"
            )


class TestGetFullEnv:
    """Test get_full_env() for trusted workflows."""

    def test_includes_all_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Full env should include all variables (use with caution)."""
        monkeypatch.setenv("SECRET_FOR_TEST", "secret_value")

        env = get_full_env()

        assert "SECRET_FOR_TEST" in env
        assert env["SECRET_FOR_TEST"] == "secret_value"


class TestFilterEnv:
    """Test filter_env() for custom filtering."""

    def test_additional_vars(self) -> None:
        """Can add additional allowed vars."""
        base = {"PATH": "/bin", "CUSTOM": "value", "SECRET": "hidden"}

        env = filter_env(base, additional_vars=frozenset({"CUSTOM"}))

        assert "PATH" in env
        assert "CUSTOM" in env
        assert "SECRET" not in env

    def test_block_vars(self) -> None:
        """Can block specific vars (takes precedence)."""
        base = {"PATH": "/bin", "HOME": "/home/test"}

        env = filter_env(base, block_vars=frozenset({"HOME"}))

        assert "PATH" in env
        assert "HOME" not in env


class TestIntegrationWithSkills:
    """Integration tests verifying skills use safe env."""

    @pytest.fixture
    def mock_services(self):
        """Create a mock service container with required methods."""
        from unittest.mock import MagicMock
        mock = MagicMock()
        mock.policy.cwd = "/tmp"
        mock.get_cwd.return_value = "/tmp"
        return mock

    @pytest.mark.asyncio
    async def test_bash_safe_does_not_leak_env(
        self, monkeypatch: pytest.MonkeyPatch, mock_services
    ) -> None:
        """BashSafeSkill should not leak arbitrary env vars."""
        # Set a secret that should NOT appear in subprocess
        monkeypatch.setenv("SECRET_TEST_VAR", "super_secret_value")

        # Import here to get fresh imports with monkeypatched env
        from nexus3.skill.builtin.bash import BashSafeSkill

        skill = BashSafeSkill(mock_services)
        result = await skill.execute(command="env", timeout=5)

        # The output should NOT contain our secret
        assert "SECRET_TEST_VAR" not in (result.output or ""), (
            "SECURITY BUG: Secret env var leaked to bash subprocess"
        )
        assert "super_secret_value" not in (result.output or ""), (
            "SECURITY BUG: Secret value leaked to bash subprocess"
        )

    @pytest.mark.asyncio
    async def test_run_python_does_not_leak_env(
        self, monkeypatch: pytest.MonkeyPatch, mock_services
    ) -> None:
        """RunPythonSkill should not leak arbitrary env vars."""
        monkeypatch.setenv("SECRET_TEST_VAR", "super_secret_value")

        from nexus3.skill.builtin.run_python import RunPythonSkill

        skill = RunPythonSkill(mock_services)
        result = await skill.execute(
            code="import os; print(os.environ.get('SECRET_TEST_VAR', 'NOT_FOUND'))",
            timeout=5,
        )

        # The output should show NOT_FOUND, not the secret
        assert "super_secret_value" not in (result.output or ""), (
            "SECURITY BUG: Secret env var leaked to Python subprocess"
        )
        # Ideally it should print "NOT_FOUND"
        assert "NOT_FOUND" in (result.output or ""), (
            "Expected Python to not find SECRET_TEST_VAR"
        )
