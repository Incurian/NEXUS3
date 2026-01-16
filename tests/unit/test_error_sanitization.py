"""Tests for error sanitization."""

from nexus3.core.errors import sanitize_error_for_agent


class TestSanitizeErrorForAgent:
    def test_permission_denied_generic(self):
        result = sanitize_error_for_agent("Permission denied: /etc/shadow")
        assert result == "Permission denied for this operation"
        assert "/etc/shadow" not in result

    def test_permission_denied_with_tool(self):
        result = sanitize_error_for_agent("Permission denied", "read_file")
        assert result == "Permission denied for read_file"

    def test_file_not_found(self):
        result = sanitize_error_for_agent(
            "No such file or directory: /home/user/secret.txt"
        )
        assert result == "File or directory not found"
        assert "secret" not in result

    def test_file_not_found_variant(self):
        result = sanitize_error_for_agent("File not found: /tmp/missing.txt")
        assert result == "File or directory not found"
        assert "missing" not in result

    def test_is_a_directory(self):
        result = sanitize_error_for_agent(
            "Is a directory: /home/alice/Documents"
        )
        assert result == "Expected a file but got a directory"
        assert "alice" not in result

    def test_not_a_directory(self):
        result = sanitize_error_for_agent(
            "Not a directory: /home/bob/file.txt"
        )
        assert result == "Expected a directory but got a file"
        assert "bob" not in result

    def test_file_exists(self):
        result = sanitize_error_for_agent(
            "File exists: /home/user/important.txt"
        )
        assert result == "File already exists"
        assert "important" not in result

    def test_disk_quota(self):
        result = sanitize_error_for_agent("Disk quota exceeded")
        assert result == "Insufficient disk space"

    def test_no_space(self):
        result = sanitize_error_for_agent("No space left on device")
        assert result == "Insufficient disk space"

    def test_timeout_error(self):
        result = sanitize_error_for_agent("Command timed out after 30s", "bash")
        assert result == "bash timed out"

    def test_timeout_error_generic(self):
        result = sanitize_error_for_agent("Operation timed out")
        assert result == "Operation timed out"

    def test_path_sanitization(self):
        result = sanitize_error_for_agent(
            "Error at /home/alice/project/src/main.py line 42"
        )
        assert "/home/alice" not in result
        assert "[path]" in result or "[user]" in result

    def test_path_sanitization_preserves_message(self):
        result = sanitize_error_for_agent(
            "Cannot parse JSON at /home/user/config.json"
        )
        assert "Cannot parse JSON" in result
        assert "/home/user" not in result
        assert "[path]" in result or "[user]" in result

    def test_empty_error_unchanged(self):
        assert sanitize_error_for_agent("") == ""

    def test_none_error_unchanged(self):
        assert sanitize_error_for_agent(None) is None

    def test_generic_error_keeps_message(self):
        result = sanitize_error_for_agent("Something went wrong")
        assert "Something went wrong" in result

    def test_multiple_paths_sanitized(self):
        result = sanitize_error_for_agent(
            "Failed to copy /home/alice/src to /home/alice/dst"
        )
        assert "/home/alice" not in result
        # All paths should be sanitized
        assert result.count("[path]") >= 1 or result.count("[user]") >= 1

    def test_home_pattern_specific(self):
        result = sanitize_error_for_agent(
            "Error in /home/secretuser/private/data.txt"
        )
        assert "secretuser" not in result

    def test_system_paths_sanitized(self):
        result = sanitize_error_for_agent(
            "Cannot access /etc/passwd or /var/log/syslog"
        )
        assert "/etc/passwd" not in result
        assert "/var/log/syslog" not in result

    def test_case_insensitive_matching(self):
        # "PERMISSION DENIED" should still match
        result = sanitize_error_for_agent("PERMISSION DENIED: /root/.ssh/id_rsa")
        assert result == "Permission denied for this operation"
        assert "id_rsa" not in result

    def test_mixed_case_not_found(self):
        result = sanitize_error_for_agent("NOT FOUND: /tmp/test.txt")
        assert result == "File or directory not found"
