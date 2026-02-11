"""Git repository context detection and formatting for NEXUS3 agents."""

import re
import subprocess
from pathlib import Path

# Hard cap on total git context length
_MAX_CONTEXT_LENGTH = 500

# Git convention: truncate commit messages at 72 chars
_MAX_COMMIT_MSG_LENGTH = 72

# Timeout for each git subprocess call (seconds)
_GIT_TIMEOUT = 5

# Tools whose execution should trigger a git context refresh
_GIT_REFRESH_TOOLS = frozenset({
    "git",           # Any git command could change state
    "bash_safe",     # Could run git commands
    "shell_UNSAFE",  # Could run git commands
    "run_python",    # Could run git via subprocess
    "write_file",    # Changes working tree
    "edit_file",     # Changes working tree
    "edit_lines",    # Changes working tree
    "append_file",   # Changes working tree
    "rename",        # Changes working tree
    "copy_file",     # Changes working tree
    "regex_replace", # Changes working tree
    "patch",         # Changes working tree
    "mkdir",         # Changes working tree
})

# Prefix matches (covers all gitlab_* tools)
_GIT_REFRESH_PREFIXES = ("gitlab_",)


def should_refresh_git_context(tool_name: str) -> bool:
    """Check if a tool execution should trigger a git context refresh.

    Args:
        tool_name: Name of the tool that was executed.

    Returns:
        True if the tool could modify git or working tree state.
    """
    return tool_name in _GIT_REFRESH_TOOLS or tool_name.startswith(_GIT_REFRESH_PREFIXES)


def _run_git(args: list[str], cwd: str | Path) -> str | None:
    """Run a git command and return stdout, or None on any failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _sanitize_remote_url(url: str) -> str:
    """Strip credentials and .git suffix from remote URL.

    Handles:
        https://user:pass@github.com/org/repo.git -> github.com/org/repo
        git@github.com:org/repo.git -> github.com/org/repo
        ssh://git@github.com/org/repo.git -> github.com/org/repo
    """
    # Strip .git suffix
    if url.endswith(".git"):
        url = url[:-4]

    # Handle SSH-style URLs: git@host:org/repo
    ssh_match = re.match(r"^[\w.-]+@([\w.-]+):(.*)", url)
    if ssh_match:
        return f"{ssh_match.group(1)}/{ssh_match.group(2)}"

    # Handle https:// and ssh:// URLs - strip scheme and credentials
    proto_match = re.match(r"^(?:https?|ssh)://(?:[^@]+@)?(.*)", url)
    if proto_match:
        return proto_match.group(1)

    return url


def _parse_status_counts(porcelain_output: str) -> dict[str, int]:
    """Parse `git status --porcelain` output into counts.

    Returns dict with keys: staged, modified, untracked.
    """
    staged = 0
    modified = 0
    untracked = 0

    for line in porcelain_output.splitlines():
        if len(line) < 2:
            continue
        x, y = line[0], line[1]
        if x == "?" and y == "?":
            untracked += 1
        else:
            if x in "AMDRC":
                staged += 1
            if y in "MD":
                modified += 1

    return {"staged": staged, "modified": modified, "untracked": untracked}


def get_git_context(cwd: str | Path) -> str | None:
    """Get formatted git repository context for the given directory.

    Runs several git commands to gather repository information and formats
    it into a concise block suitable for system prompt injection.

    Args:
        cwd: Working directory to check for git repository.

    Returns:
        Formatted git context string. Returns "No git repository detected
        in CWD." if not a repo. Returns None only if git is not installed
        or commands fail unexpectedly. Output is hard-capped at 500 characters.
    """
    # Check if inside a git repo — distinguish "not a repo" from "git unavailable"
    try:
        check = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
            encoding="utf-8",
            errors="replace",
        )
        if check.stdout.strip() != "true":
            # git ran but this is not a repo
            return "No git repository detected in CWD."
    except (OSError, subprocess.TimeoutExpired, ValueError):
        # git not installed or other system error — omit silently
        return None

    lines = ["Git repository detected in CWD."]

    # Branch name
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    if branch:
        lines.append(f"  Branch: {branch}")

    # Status counts + stash count
    status_output = _run_git(["status", "--porcelain"], cwd)
    stash_output = _run_git(["stash", "list"], cwd)

    status_parts: list[str] = []
    if status_output is not None:
        counts = _parse_status_counts(status_output)
        if counts["staged"]:
            status_parts.append(f"{counts['staged']} staged")
        if counts["modified"]:
            status_parts.append(f"{counts['modified']} modified")
        if counts["untracked"]:
            status_parts.append(f"{counts['untracked']} untracked")

    if stash_output:
        stash_count = len(stash_output.splitlines())
        if stash_count > 0:
            status_parts.append(f"{stash_count} stash{'es' if stash_count != 1 else ''}")

    if status_parts:
        lines.append(f"  Status: {', '.join(status_parts)}")
    elif status_output is not None:
        lines.append("  Status: clean")

    # Last commit
    commit = _run_git(["log", "-1", "--format=%h %s"], cwd)
    if commit:
        if len(commit) > _MAX_COMMIT_MSG_LENGTH:
            commit = commit[:_MAX_COMMIT_MSG_LENGTH - 3] + "..."
        lines.append(f"  Last commit: {commit}")

    # Remote URL
    remote = _run_git(["remote", "get-url", "origin"], cwd)
    if remote:
        sanitized = _sanitize_remote_url(remote)
        lines.append(f"  Remote: origin \u2192 {sanitized}")

    # Worktrees (only show if more than the main one)
    worktree_output = _run_git(["worktree", "list", "--porcelain"], cwd)
    if worktree_output:
        worktrees = [
            line.split(" ", 1)[1]
            for line in worktree_output.splitlines()
            if line.startswith("worktree ")
        ]
        if len(worktrees) > 1:
            # Show additional worktrees (skip main)
            extra = worktrees[1:]
            wt_strs = [str(Path(wt).name) for wt in extra]
            lines.append(f"  Worktrees: {', '.join(wt_strs)}")

    result = "\n".join(lines)

    # Hard cap
    if len(result) > _MAX_CONTEXT_LENGTH:
        result = result[:_MAX_CONTEXT_LENGTH - 3] + "..."

    return result
