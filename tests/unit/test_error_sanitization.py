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
        # "NOT FOUND" alone is ambiguous - could be file, key, string, etc.
        # Path should still be sanitized, but generic "not found" shouldn't
        # assume it means "file not found" (that was the original bug)
        result = sanitize_error_for_agent("NOT FOUND: /tmp/test.txt")
        # Path is sanitized but message is preserved
        assert "/tmp/test.txt" not in result
        assert "[path]" in result

    def test_file_not_found_case_insensitive(self):
        """Explicit 'file not found' should sanitize regardless of case."""
        result = sanitize_error_for_agent("FILE NOT FOUND: /tmp/test.txt")
        assert result == "File or directory not found"

    # === Bug fix: "String not found" should not become "File not found" ===

    def test_string_not_found_preserves_meaning(self):
        """Content-level errors should not be mapped to file errors."""
        error = "String not found in file: def foo()..."
        result = sanitize_error_for_agent(error, "edit_file")
        assert "file or directory not found" not in result.lower()
        assert "string" in result.lower() or "not found in file" in result.lower()

    def test_clipboard_key_not_found_preserves_meaning(self):
        """Clipboard key errors should not become file errors."""
        error = "Clipboard key 'backup' not found in agent scope"
        result = sanitize_error_for_agent(error, "clipboard_get")
        assert "file or directory not found" not in result.lower()
        assert "clipboard" in result.lower() or "key" in result.lower()

    def test_marker_not_found_preserves_meaning(self):
        """Marker errors should not become file errors."""
        error = "Marker 'SECTION_END' not found in file"
        result = sanitize_error_for_agent(error, "paste")
        assert "file or directory not found" not in result.lower()
        assert "marker" in result.lower()

    def test_file_not_found_still_sanitized(self):
        """File-level errors should still be sanitized."""
        error = "File not found: /home/user/secret/passwords.txt"
        result = sanitize_error_for_agent(error, "read_file")
        assert result == "File or directory not found"

    def test_directory_not_found_still_sanitized(self):
        """Directory-level errors should still be sanitized."""
        error = "Directory not found: /home/user/.ssh"
        result = sanitize_error_for_agent(error, "list_directory")
        assert result == "File or directory not found"

    def test_path_not_found_still_sanitized(self):
        """Path not found errors should still be sanitized."""
        error = "Path not found: /etc/secret.conf"
        result = sanitize_error_for_agent(error, "grep")
        assert result == "File or directory not found"

    def test_source_not_found_still_sanitized(self):
        """Source not found errors should still be sanitized."""
        error = "Source not found: /home/alice/file.txt"
        result = sanitize_error_for_agent(error, "copy_file")
        assert result == "File or directory not found"

    # === Bug fix: URLs should not be mangled ===

    def test_url_http_preserved(self):
        """HTTP URLs should not have paths sanitized."""
        error = "Error connecting to http://example.com/api/v1/users"
        result = sanitize_error_for_agent(error, "bash")
        assert "http://example.com/api/v1/users" in result

    def test_url_https_preserved(self):
        """HTTPS URLs should not have paths sanitized."""
        error = "Failed to fetch https://docs.example.com/guide/setup"
        result = sanitize_error_for_agent(error, "bash")
        assert "https://docs.example.com/guide/setup" in result

    def test_url_with_port_preserved(self):
        """URLs with ports should not have paths sanitized."""
        error = "Connection refused: http://localhost:8765/agent/main"
        result = sanitize_error_for_agent(error, "nexus_send")
        assert "http://localhost:8765/agent/main" in result

    def test_social_media_path_preserved(self):
        """Reddit-style paths should not be sanitized."""
        error = "Check /r/python for more info"
        result = sanitize_error_for_agent(error, "bash")
        assert "/r/python" in result

    def test_price_expression_preserved(self):
        """Price expressions like $50/month should not be sanitized."""
        error = "Cost is $50/month for this service"
        result = sanitize_error_for_agent(error, "bash")
        assert "$50/month" in result

    def test_filesystem_paths_still_sanitized(self):
        """Real filesystem paths should still be sanitized."""
        error = "Cannot read /home/alice/secrets.txt"
        result = sanitize_error_for_agent(error, "read_file")
        assert "/home/alice" not in result
        assert "[path]" in result or "[user]" in result

    def test_etc_paths_still_sanitized(self):
        """System paths should still be sanitized."""
        error = "Access denied to /etc/shadow"
        result = sanitize_error_for_agent(error, "read_file")
        assert "/etc/shadow" not in result

    def test_var_paths_still_sanitized(self):
        """Var paths should still be sanitized."""
        error = "Log file at /var/log/auth.log"
        result = sanitize_error_for_agent(error, "read_file")
        assert "/var/log" not in result

    # === Windows path tests (previously untested) ===

    def test_windows_user_path_backslash(self):
        """Windows user paths with backslashes should be sanitized."""
        error = "Cannot write to C:\\Users\\alice\\Documents\\secret.txt"
        result = sanitize_error_for_agent(error, "write_file")
        assert "alice" not in result

    def test_windows_user_path_forward_slash(self):
        """Windows user paths with forward slashes should be sanitized."""
        error = "Error at C:/Users/bob/AppData/Local/config.json"
        result = sanitize_error_for_agent(error, "read_file")
        assert "bob" not in result

    def test_unc_path_sanitized(self):
        """UNC paths should be sanitized."""
        error = "Cannot access \\\\fileserver\\Projects\\secret.doc"
        result = sanitize_error_for_agent(error, "read_file")
        assert "fileserver" not in result

    def test_domain_user_sanitized(self):
        """Domain\\user patterns should be sanitized."""
        error = "Permission denied for DOMAIN\\alice"
        result = sanitize_error_for_agent(error, "bash")
        assert "alice" not in result
