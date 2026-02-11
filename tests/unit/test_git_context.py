"""Tests for git_context module."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from nexus3.context.git_context import (
    _parse_status_counts,
    _sanitize_remote_url,
    get_git_context,
    should_refresh_git_context,
)


class TestShouldRefreshGitContext:
    """Test the should_refresh_git_context() helper."""

    def test_git_tool(self):
        assert should_refresh_git_context("git") is True

    def test_file_write_tools(self):
        for tool in ("write_file", "edit_file", "edit_lines", "append_file",
                      "rename", "copy_file", "regex_replace", "patch", "mkdir"):
            assert should_refresh_git_context(tool) is True, f"{tool} should trigger refresh"

    def test_exec_tools(self):
        for tool in ("bash_safe", "shell_UNSAFE", "run_python"):
            assert should_refresh_git_context(tool) is True, f"{tool} should trigger refresh"

    def test_gitlab_prefix(self):
        assert should_refresh_git_context("gitlab_mr") is True
        assert should_refresh_git_context("gitlab_issue") is True
        assert should_refresh_git_context("gitlab_branch") is True
        assert should_refresh_git_context("gitlab_pipeline") is True

    def test_read_tools_do_not_trigger(self):
        for tool in ("read_file", "list_directory", "glob", "grep",
                      "file_info", "tail", "clipboard_list"):
            assert should_refresh_git_context(tool) is False, f"{tool} should not trigger refresh"

    def test_nexus_tools_do_not_trigger(self):
        for tool in ("nexus_create", "nexus_send", "nexus_status"):
            assert should_refresh_git_context(tool) is False


class TestSanitizeRemoteUrl:
    """Test remote URL sanitization."""

    def test_https_url(self):
        assert _sanitize_remote_url("https://github.com/user/repo.git") == "github.com/user/repo"

    def test_https_url_no_git_suffix(self):
        assert _sanitize_remote_url("https://github.com/user/repo") == "github.com/user/repo"

    def test_https_with_credentials(self):
        url = "https://user:token@github.com/org/repo.git"
        assert _sanitize_remote_url(url) == "github.com/org/repo"

    def test_ssh_style_url(self):
        assert _sanitize_remote_url("git@github.com:user/repo.git") == "github.com/user/repo"

    def test_ssh_protocol_url(self):
        assert _sanitize_remote_url("ssh://git@github.com/user/repo.git") == "github.com/user/repo"

    def test_plain_url(self):
        assert _sanitize_remote_url("example.com/repo") == "example.com/repo"


class TestParseStatusCounts:
    """Test git status --porcelain parsing."""

    def test_empty_output(self):
        counts = _parse_status_counts("")
        assert counts == {"staged": 0, "modified": 0, "untracked": 0}

    def test_untracked_files(self):
        output = "?? file1.txt\n?? file2.txt"
        counts = _parse_status_counts(output)
        assert counts == {"staged": 0, "modified": 0, "untracked": 2}

    def test_staged_files(self):
        output = "A  new_file.txt\nM  modified.txt"
        counts = _parse_status_counts(output)
        assert counts == {"staged": 2, "modified": 0, "untracked": 0}

    def test_modified_files(self):
        output = " M file1.txt\n M file2.txt"
        counts = _parse_status_counts(output)
        assert counts == {"staged": 0, "modified": 2, "untracked": 0}

    def test_mixed_status(self):
        output = "A  staged.txt\n M modified.txt\n?? untracked.txt\nMM both.txt"
        counts = _parse_status_counts(output)
        # MM = staged (M in X) + modified (M in Y)
        assert counts == {"staged": 2, "modified": 2, "untracked": 1}

    def test_renamed_file(self):
        output = "R  old.txt -> new.txt"
        counts = _parse_status_counts(output)
        assert counts == {"staged": 1, "modified": 0, "untracked": 0}

    def test_deleted_staged(self):
        output = "D  deleted.txt"
        counts = _parse_status_counts(output)
        assert counts == {"staged": 1, "modified": 0, "untracked": 0}

    def test_deleted_unstaged(self):
        output = " D deleted.txt"
        counts = _parse_status_counts(output)
        assert counts == {"staged": 0, "modified": 1, "untracked": 0}


class TestGetGitContext:
    """Test the main get_git_context() function."""

    def _make_run_side_effect(self, responses: dict[str, str | None]):
        """Create a subprocess.run side effect based on git command args.

        Args:
            responses: Maps git subcommand key to stdout value.
                Keys: "rev-parse-work-tree", "rev-parse-branch", "status",
                      "stash", "log", "remote", "worktree"
                Values: stdout string or None (for returncode=1).
        """
        def side_effect(args, **kwargs):
            cmd = args[1] if len(args) > 1 else ""

            if cmd == "rev-parse":
                if "--is-inside-work-tree" in args:
                    key = "rev-parse-work-tree"
                else:
                    key = "rev-parse-branch"
            elif cmd == "status":
                key = "status"
            elif cmd == "stash":
                key = "stash"
            elif cmd == "log":
                key = "log"
            elif cmd == "remote":
                key = "remote"
            elif cmd == "worktree":
                key = "worktree"
            else:
                key = cmd

            value = responses.get(key)
            if value is None:
                return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="")
            return subprocess.CompletedProcess(args, returncode=0, stdout=value, stderr="")

        return side_effect

    @patch("nexus3.context.git_context.subprocess.run")
    def test_not_a_git_repo(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            ["git", "rev-parse", "--is-inside-work-tree"],
            returncode=128, stdout="", stderr="not a git repo",
        )
        result = get_git_context("/tmp/not-a-repo")
        assert result == "No git repository detected in CWD."

    @patch("nexus3.context.git_context.subprocess.run")
    def test_git_not_installed(self, mock_run):
        mock_run.side_effect = OSError("No such file or directory")
        assert get_git_context("/tmp") is None

    @patch("nexus3.context.git_context.subprocess.run")
    def test_git_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("git", 5)
        assert get_git_context("/tmp") is None

    @patch("nexus3.context.git_context.subprocess.run")
    def test_basic_repo(self, mock_run):
        mock_run.side_effect = self._make_run_side_effect({
            "rev-parse-work-tree": "true",
            "rev-parse-branch": "main",
            "status": "",
            "stash": "",
            "log": "abc1234 fix login bug",
            "remote": "https://github.com/user/repo.git",
            "worktree": "worktree /home/user/repo\n",
        })

        result = get_git_context("/home/user/repo")

        assert result is not None
        assert "Branch: main" in result
        assert "Status: clean" in result
        assert "abc1234 fix login bug" in result
        assert "github.com/user/repo" in result
        # Only one worktree - should not show worktrees section
        assert "Worktrees:" not in result

    @patch("nexus3.context.git_context.subprocess.run")
    def test_dirty_repo_with_stashes(self, mock_run):
        mock_run.side_effect = self._make_run_side_effect({
            "rev-parse-work-tree": "true",
            "rev-parse-branch": "feature/test",
            "status": "M  file1.txt\n?? file2.txt\n M file3.txt",
            "stash": (
                "stash@{0}: WIP on main: abc1234 first\n"
                "stash@{1}: WIP on main: def5678 second"
            ),
            "log": "def5678 add tests",
            "remote": "git@github.com:org/project.git",
            "worktree": "worktree /home/user/repo\n",
        })

        result = get_git_context("/home/user/repo")

        assert result is not None
        assert "Branch: feature/test" in result
        assert "1 staged" in result
        assert "1 modified" in result
        assert "1 untracked" in result
        assert "2 stashes" in result
        assert "def5678 add tests" in result
        assert "github.com/org/project" in result

    @patch("nexus3.context.git_context.subprocess.run")
    def test_single_stash_no_plural(self, mock_run):
        mock_run.side_effect = self._make_run_side_effect({
            "rev-parse-work-tree": "true",
            "rev-parse-branch": "main",
            "status": "",
            "stash": "stash@{0}: WIP on main: abc1234 first",
            "log": "abc1234 first",
            "remote": None,
            "worktree": "worktree /home/user/repo\n",
        })

        result = get_git_context("/home/user/repo")
        assert result is not None
        assert "1 stash" in result
        assert "1 stashes" not in result

    @patch("nexus3.context.git_context.subprocess.run")
    def test_long_commit_message_truncated(self, mock_run):
        long_msg = "abc1234 " + "x" * 100
        mock_run.side_effect = self._make_run_side_effect({
            "rev-parse-work-tree": "true",
            "rev-parse-branch": "main",
            "status": "",
            "stash": "",
            "log": long_msg,
            "remote": None,
            "worktree": "worktree /home/user/repo\n",
        })

        result = get_git_context("/home/user/repo")
        assert result is not None
        # Check commit line is truncated
        for line in result.splitlines():
            if "Last commit:" in line:
                commit_part = line.split("Last commit: ")[1]
                assert len(commit_part) <= 72
                assert commit_part.endswith("...")
                break
        else:
            pytest.fail("No 'Last commit' line found")

    @patch("nexus3.context.git_context.subprocess.run")
    def test_no_remote(self, mock_run):
        mock_run.side_effect = self._make_run_side_effect({
            "rev-parse-work-tree": "true",
            "rev-parse-branch": "main",
            "status": "",
            "stash": "",
            "log": "abc1234 commit",
            "remote": None,
            "worktree": "worktree /home/user/repo\n",
        })

        result = get_git_context("/home/user/repo")
        assert result is not None
        assert "Remote:" not in result

    @patch("nexus3.context.git_context.subprocess.run")
    def test_hard_cap_applied(self, mock_run):
        mock_run.side_effect = self._make_run_side_effect({
            "rev-parse-work-tree": "true",
            "rev-parse-branch": "a" * 200,
            "status": "\n".join(f"?? file{i}.txt" for i in range(100)),
            "stash": "\n".join(f"stash@{{{i}}}: WIP" for i in range(50)),
            "log": "abc1234 " + "x" * 200,
            "remote": "https://github.com/" + "x" * 200 + ".git",
            "worktree": "worktree /a\nworktree /b\nworktree /c\n",
        })

        result = get_git_context("/home/user/repo")
        assert result is not None
        assert len(result) <= 500

    @patch("nexus3.context.git_context.subprocess.run")
    def test_multiple_worktrees_shown(self, mock_run):
        mock_run.side_effect = self._make_run_side_effect({
            "rev-parse-work-tree": "true",
            "rev-parse-branch": "main",
            "status": "",
            "stash": "",
            "log": "abc1234 commit",
            "remote": None,
            "worktree": "worktree /home/user/repo\nworktree /home/user/repo-hotfix\n",
        })

        result = get_git_context("/home/user/repo")
        assert result is not None
        assert "Worktrees:" in result
        assert "repo-hotfix" in result

    @patch("nexus3.context.git_context.subprocess.run")
    def test_detached_head(self, mock_run):
        mock_run.side_effect = self._make_run_side_effect({
            "rev-parse-work-tree": "true",
            "rev-parse-branch": "HEAD",
            "status": "",
            "stash": "",
            "log": "abc1234 commit",
            "remote": None,
            "worktree": "worktree /home/user/repo\n",
        })

        result = get_git_context("/home/user/repo")
        assert result is not None
        assert "Branch: HEAD" in result

    @patch("nexus3.context.git_context.subprocess.run")
    def test_result_starts_with_header(self, mock_run):
        mock_run.side_effect = self._make_run_side_effect({
            "rev-parse-work-tree": "true",
            "rev-parse-branch": "main",
            "status": "",
            "stash": "",
            "log": "abc1234 commit",
            "remote": None,
            "worktree": "worktree /home/user/repo\n",
        })

        result = get_git_context("/home/user/repo")
        assert result is not None
        assert result.startswith("Git repository detected in CWD.")


class TestGetGitContextLive:
    """Integration tests that run against the actual NEXUS3 git repo.

    These tests verify get_git_context works with real git commands.
    They are skipped if the test is not running from a git repo.
    """

    @pytest.fixture
    def repo_root(self):
        """Get the NEXUS3 repo root directory."""
        root = Path(__file__).parent.parent.parent
        if not (root / ".git").exists():
            pytest.skip("Not running from a git repo")
        return root

    def test_live_repo_returns_context(self, repo_root):
        result = get_git_context(repo_root)
        assert result is not None
        assert "Git repository detected in CWD." in result
        assert "Branch:" in result
        assert "Last commit:" in result

    def test_live_repo_within_cap(self, repo_root):
        result = get_git_context(repo_root)
        assert result is not None
        assert len(result) <= 500

    def test_live_non_git_dir(self, tmp_path):
        result = get_git_context(tmp_path)
        assert result == "No git repository detected in CWD."
