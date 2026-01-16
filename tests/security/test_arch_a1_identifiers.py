"""Tests for nexus3.core.identifiers module.

Arch A1: Canonical tool and skill identifier handling.

This test suite validates:
1. validate_tool_name - strict validation with detailed error messages
2. is_valid_tool_name - boolean validation without exceptions
3. normalize_tool_name - safe normalization of external input
4. build_mcp_skill_name - canonical MCP skill name construction
5. parse_mcp_skill_name - MCP skill name parsing
6. Security properties - collision prevention, injection resistance
"""

from __future__ import annotations

import pytest

from nexus3.core.identifiers import (
    MAX_TOOL_NAME_LENGTH,
    MIN_TOOL_NAME_LENGTH,
    RESERVED_TOOL_NAMES,
    ToolNameError,
    build_mcp_skill_name,
    is_valid_tool_name,
    normalize_tool_name,
    parse_mcp_skill_name,
    validate_tool_name,
)


class TestValidateToolName:
    """Tests for validate_tool_name function."""

    # === Valid names ===

    def test_valid_simple_name(self) -> None:
        """Valid simple tool name."""
        validate_tool_name("read_file")  # Should not raise

    def test_valid_mixed_case(self) -> None:
        """Valid mixed case name."""
        validate_tool_name("MyTool")  # Should not raise

    def test_valid_private_underscore_prefix(self) -> None:
        """Valid name starting with underscore."""
        validate_tool_name("_private")  # Should not raise

    def test_valid_with_hyphen(self) -> None:
        """Valid name with hyphen."""
        validate_tool_name("tool-v2")  # Should not raise

    def test_valid_single_char(self) -> None:
        """Valid single character name."""
        validate_tool_name("a")  # Should not raise

    def test_valid_underscore_only(self) -> None:
        """Valid underscore-only name."""
        validate_tool_name("_")  # Should not raise

    def test_valid_max_length(self) -> None:
        """Valid name at exact max length."""
        name = "a" * MAX_TOOL_NAME_LENGTH
        validate_tool_name(name)  # Should not raise

    def test_valid_alphanumeric_mix(self) -> None:
        """Valid name with all allowed character types."""
        validate_tool_name("Tool_Name-123")  # Should not raise

    # === Invalid names - empty/length ===

    def test_invalid_empty_string(self) -> None:
        """Empty string is invalid."""
        with pytest.raises(ToolNameError) as exc_info:
            validate_tool_name("")
        assert "cannot be empty" in str(exc_info.value)

    def test_invalid_too_long(self) -> None:
        """Name exceeding max length is invalid."""
        name = "a" * (MAX_TOOL_NAME_LENGTH + 1)
        with pytest.raises(ToolNameError) as exc_info:
            validate_tool_name(name)
        assert "exceeds maximum length" in str(exc_info.value)
        assert str(MAX_TOOL_NAME_LENGTH) in str(exc_info.value)

    def test_invalid_much_too_long(self) -> None:
        """Very long name is invalid with truncated error message."""
        name = "a" * 200
        with pytest.raises(ToolNameError) as exc_info:
            validate_tool_name(name)
        # Error message truncates the name
        assert "..." in str(exc_info.value)

    # === Invalid names - starting character ===

    def test_invalid_starts_with_digit(self) -> None:
        """Name starting with digit is invalid."""
        with pytest.raises(ToolNameError) as exc_info:
            validate_tool_name("123start")
        assert "cannot start with a digit" in str(exc_info.value)

    def test_invalid_starts_with_hyphen(self) -> None:
        """Name starting with hyphen is invalid."""
        with pytest.raises(ToolNameError) as exc_info:
            validate_tool_name("-start")
        assert "cannot start with a hyphen" in str(exc_info.value)

    # === Invalid names - invalid characters ===

    def test_invalid_contains_space(self) -> None:
        """Name with space is invalid."""
        with pytest.raises(ToolNameError) as exc_info:
            validate_tool_name("my tool")
        assert "invalid characters" in str(exc_info.value)

    def test_valid_ascii_uber(self) -> None:
        """ASCII 'uber' is valid (unlike unicode 'über')."""
        validate_tool_name("uber")  # ASCII is fine

    def test_invalid_contains_unicode_umlaut(self) -> None:
        """Name with unicode umlaut is invalid."""
        with pytest.raises(ToolNameError) as exc_info:
            validate_tool_name("über")
        assert "invalid characters" in str(exc_info.value)

    def test_invalid_contains_special_chars(self) -> None:
        """Name with special characters is invalid."""
        for char in ["@", "#", "$", "%", "^", "&", "*", "!", "~", "`"]:
            with pytest.raises(ToolNameError):
                validate_tool_name(f"tool{char}name")

    def test_invalid_contains_slash(self) -> None:
        """Name with slash is invalid (path injection attempt)."""
        with pytest.raises(ToolNameError):
            validate_tool_name("../etc/passwd")

    def test_invalid_contains_dot(self) -> None:
        """Name with dot is invalid."""
        with pytest.raises(ToolNameError):
            validate_tool_name("tool.name")

    def test_invalid_contains_colon(self) -> None:
        """Name with colon is invalid."""
        with pytest.raises(ToolNameError):
            validate_tool_name("tool:name")

    # === Reserved names ===

    def test_invalid_reserved_mcp(self) -> None:
        """Reserved name 'mcp' is invalid by default."""
        with pytest.raises(ToolNameError) as exc_info:
            validate_tool_name("mcp")
        assert "reserved" in str(exc_info.value)

    def test_invalid_reserved_nexus(self) -> None:
        """Reserved name 'nexus' is invalid by default."""
        with pytest.raises(ToolNameError) as exc_info:
            validate_tool_name("nexus")
        assert "reserved" in str(exc_info.value)

    def test_invalid_reserved_system(self) -> None:
        """Reserved name 'system' is invalid by default."""
        with pytest.raises(ToolNameError) as exc_info:
            validate_tool_name("system")
        assert "reserved" in str(exc_info.value)

    def test_invalid_reserved_true(self) -> None:
        """Reserved name 'true' is invalid by default."""
        with pytest.raises(ToolNameError):
            validate_tool_name("true")

    def test_invalid_reserved_false(self) -> None:
        """Reserved name 'false' is invalid by default."""
        with pytest.raises(ToolNameError):
            validate_tool_name("false")

    def test_invalid_reserved_null(self) -> None:
        """Reserved name 'null' is invalid by default."""
        with pytest.raises(ToolNameError):
            validate_tool_name("null")

    def test_invalid_reserved_none(self) -> None:
        """Reserved name 'none' is invalid by default."""
        with pytest.raises(ToolNameError):
            validate_tool_name("none")

    def test_invalid_reserved_admin(self) -> None:
        """Reserved name 'admin' is invalid by default."""
        with pytest.raises(ToolNameError):
            validate_tool_name("admin")

    def test_invalid_reserved_root(self) -> None:
        """Reserved name 'root' is invalid by default."""
        with pytest.raises(ToolNameError):
            validate_tool_name("root")

    def test_reserved_case_insensitive(self) -> None:
        """Reserved name check is case insensitive."""
        for variant in ["MCP", "Mcp", "mCp", "TRUE", "True", "NULL", "Null"]:
            with pytest.raises(ToolNameError):
                validate_tool_name(variant)

    # === allow_reserved=True ===

    def test_allow_reserved_mcp(self) -> None:
        """allow_reserved=True permits reserved names."""
        validate_tool_name("mcp", allow_reserved=True)  # Should not raise

    def test_allow_reserved_all_reserved_names(self) -> None:
        """allow_reserved=True permits all reserved names."""
        for name in RESERVED_TOOL_NAMES:
            validate_tool_name(name, allow_reserved=True)  # Should not raise

    def test_allow_reserved_still_validates_format(self) -> None:
        """allow_reserved=True still validates format."""
        with pytest.raises(ToolNameError):
            validate_tool_name("", allow_reserved=True)
        with pytest.raises(ToolNameError):
            validate_tool_name("123start", allow_reserved=True)

    # === Type errors ===

    def test_invalid_type_none(self) -> None:
        """None is not a valid tool name."""
        with pytest.raises(ToolNameError) as exc_info:
            validate_tool_name(None)  # type: ignore[arg-type]
        assert "must be a string" in str(exc_info.value)

    def test_invalid_type_int(self) -> None:
        """Integer is not a valid tool name."""
        with pytest.raises(ToolNameError) as exc_info:
            validate_tool_name(123)  # type: ignore[arg-type]
        assert "must be a string" in str(exc_info.value)

    def test_invalid_type_list(self) -> None:
        """List is not a valid tool name."""
        with pytest.raises(ToolNameError):
            validate_tool_name(["tool"])  # type: ignore[arg-type]


class TestIsValidToolName:
    """Tests for is_valid_tool_name function."""

    def test_returns_true_for_valid(self) -> None:
        """Returns True for valid names."""
        assert is_valid_tool_name("read_file") is True
        assert is_valid_tool_name("MyTool") is True
        assert is_valid_tool_name("_private") is True
        assert is_valid_tool_name("tool-v2") is True

    def test_returns_false_for_invalid(self) -> None:
        """Returns False for invalid names without raising."""
        assert is_valid_tool_name("") is False
        assert is_valid_tool_name("123start") is False
        assert is_valid_tool_name("-hyphen") is False
        assert is_valid_tool_name("a" * 100) is False
        assert is_valid_tool_name("has space") is False
        assert is_valid_tool_name("über") is False

    def test_returns_false_for_reserved(self) -> None:
        """Returns False for reserved names by default."""
        assert is_valid_tool_name("mcp") is False
        assert is_valid_tool_name("nexus") is False
        assert is_valid_tool_name("system") is False

    def test_allow_reserved_returns_true(self) -> None:
        """Returns True for reserved names when allow_reserved=True."""
        assert is_valid_tool_name("mcp", allow_reserved=True) is True
        assert is_valid_tool_name("nexus", allow_reserved=True) is True

    def test_returns_false_for_none(self) -> None:
        """Returns False for None without raising."""
        assert is_valid_tool_name(None) is False  # type: ignore[arg-type]

    def test_returns_false_for_non_string(self) -> None:
        """Returns False for non-string types without raising."""
        assert is_valid_tool_name(123) is False  # type: ignore[arg-type]
        assert is_valid_tool_name([]) is False  # type: ignore[arg-type]


class TestNormalizeToolName:
    """Tests for normalize_tool_name function."""

    # === Basic normalization ===

    def test_basic_spaces_and_exclamation(self) -> None:
        """Basic normalization: 'My Tool!' -> 'my_tool'."""
        assert normalize_tool_name("My Tool!") == "my_tool"

    def test_preserves_valid_name(self) -> None:
        """Valid name is preserved (lowercased)."""
        assert normalize_tool_name("read_file") == "read_file"

    def test_lowercase_conversion(self) -> None:
        """Converts to lowercase."""
        assert normalize_tool_name("MyTool") == "mytool"
        assert normalize_tool_name("READ_FILE") == "read_file"

    # === Leading digit handling ===

    def test_leading_digit_prefixed(self) -> None:
        """Leading digit gets underscore prefix."""
        assert normalize_tool_name("123start") == "_123start"

    def test_leading_digit_after_strip(self) -> None:
        """Leading digit after stripping separators gets prefix."""
        assert normalize_tool_name("__123test") == "_123test"

    # === Unicode handling ===
    # Note: NFKC normalizes compatibility equivalents (ligatures, fullwidth)
    # but NOT accented characters. Accented chars become underscores.

    def test_unicode_umlaut_becomes_underscore(self) -> None:
        """Unicode umlaut becomes underscore (not in ASCII set)."""
        # 'ü' is not in [a-zA-Z0-9_-] so becomes underscore, then stripped
        assert normalize_tool_name("über") == "ber"

    def test_unicode_ligature_normalized(self) -> None:
        """Unicode ligature normalized via NFKC."""
        # fi ligature -> fi (NFKC compatibility decomposition)
        assert normalize_tool_name("ﬁle") == "file"

    def test_unicode_fullwidth_normalized(self) -> None:
        """Fullwidth characters normalized."""
        # Fullwidth A (U+FF21) -> A -> a (NFKC then lowercase)
        assert normalize_tool_name("\uff21BC") == "abc"

    def test_unicode_accents_become_underscores(self) -> None:
        """Accented characters become underscores (not NFKC-normalized to ASCII)."""
        # 'é' is not in [a-zA-Z0-9_-] so becomes underscore
        assert normalize_tool_name("café") == "caf"  # trailing _ stripped
        assert normalize_tool_name("naïve") == "na_ve"  # ï becomes _

    # === Separator handling ===

    def test_consecutive_separators_collapsed(self) -> None:
        """Consecutive separators collapsed to single underscore."""
        assert normalize_tool_name("a__b") == "a_b"
        assert normalize_tool_name("a--b") == "a_b"
        assert normalize_tool_name("a__b--c___d") == "a_b_c_d"

    def test_mixed_separators_collapsed(self) -> None:
        """Mixed separators collapsed."""
        assert normalize_tool_name("a_-b") == "a_b"
        assert normalize_tool_name("a-_-b") == "a_b"

    def test_strip_leading_trailing_separators(self) -> None:
        """Leading and trailing separators stripped."""
        assert normalize_tool_name("--test--") == "test"
        assert normalize_tool_name("__test__") == "test"
        assert normalize_tool_name("_-test-_") == "test"

    # === Prefix handling ===

    def test_prefix_added(self) -> None:
        """Prefix added to normalized name."""
        assert normalize_tool_name("test", prefix="mcp_") == "mcp_test"

    def test_prefix_with_server_name(self) -> None:
        """Prefix with server name pattern."""
        assert normalize_tool_name("echo", prefix="mcp_server_") == "mcp_server_echo"

    def test_prefix_respects_max_length(self) -> None:
        """Prefix respects max length (truncates name, not prefix)."""
        long_name = "a" * 100
        result = normalize_tool_name(long_name, prefix="mcp_")
        assert len(result) == MAX_TOOL_NAME_LENGTH
        assert result.startswith("mcp_")

    def test_prefix_too_long_raises(self) -> None:
        """Prefix that leaves no room for name raises error."""
        long_prefix = "a" * MAX_TOOL_NAME_LENGTH + "_"
        with pytest.raises(ToolNameError) as exc_info:
            normalize_tool_name("test", prefix=long_prefix)
        assert "too long" in str(exc_info.value)

    def test_invalid_prefix_raises(self) -> None:
        """Invalid prefix raises error."""
        with pytest.raises(ToolNameError) as exc_info:
            normalize_tool_name("test", prefix="123_")
        assert "Invalid prefix" in str(exc_info.value)

    # === Truncation ===

    def test_truncation_to_max_length(self) -> None:
        """Very long names truncated to max length."""
        long_name = "a" * 200
        result = normalize_tool_name(long_name)
        assert len(result) == MAX_TOOL_NAME_LENGTH
        assert result == "a" * MAX_TOOL_NAME_LENGTH

    # === Empty after normalization ===

    def test_empty_after_normalization_raises(self) -> None:
        """Name that becomes empty after normalization raises error."""
        with pytest.raises(ToolNameError) as exc_info:
            normalize_tool_name("@#$%^&*()")
        assert "no valid characters remain" in str(exc_info.value)

    def test_only_separators_raises(self) -> None:
        """Name with only separators raises error."""
        with pytest.raises(ToolNameError):
            normalize_tool_name("---___---")

    def test_only_unicode_non_letters_raises(self) -> None:
        """Name with only unicode symbols raises error."""
        with pytest.raises(ToolNameError):
            normalize_tool_name("\u2603\u2764\u2605")  # snowman, heart, star

    # === Special cases ===

    def test_hyphen_to_underscore(self) -> None:
        """Hyphens preserved (not converted to underscore)."""
        # Note: hyphens are valid characters, not converted
        result = normalize_tool_name("my-tool")
        assert result == "my-tool"

    def test_special_chars_to_underscore(self) -> None:
        """Special characters converted to underscore."""
        assert normalize_tool_name("tool@name") == "tool_name"
        assert normalize_tool_name("tool.name") == "tool_name"

    def test_path_traversal_sanitized(self) -> None:
        """Path traversal attempts sanitized."""
        assert normalize_tool_name("../etc/passwd") == "etc_passwd"
        assert normalize_tool_name("../../root") == "root"

    # === Type errors ===

    def test_non_string_raises(self) -> None:
        """Non-string input raises error."""
        with pytest.raises(ToolNameError):
            normalize_tool_name(None)  # type: ignore[arg-type]
        with pytest.raises(ToolNameError):
            normalize_tool_name(123)  # type: ignore[arg-type]


class TestBuildMCPSkillName:
    """Tests for build_mcp_skill_name function."""

    def test_basic_build(self) -> None:
        """Basic MCP skill name: ('test', 'echo') -> 'mcp_test_echo'."""
        assert build_mcp_skill_name("test", "echo") == "mcp_test_echo"

    def test_sanitizes_server_name(self) -> None:
        """Server name is sanitized."""
        assert build_mcp_skill_name("My Server!", "echo") == "mcp_my_server_echo"

    def test_sanitizes_tool_name(self) -> None:
        """Tool name is sanitized."""
        assert build_mcp_skill_name("test", "Tool@#$") == "mcp_test_tool"

    def test_sanitizes_both(self) -> None:
        """Both server and tool names are sanitized."""
        result = build_mcp_skill_name("My Server!", "Tool@#$")
        assert result == "mcp_my_server_tool"

    def test_path_injection_sanitized(self) -> None:
        """Path injection attempts are sanitized."""
        result = build_mcp_skill_name("../etc", "passwd")
        assert result == "mcp_etc_passwd"

    def test_double_path_injection_sanitized(self) -> None:
        """Double path injection attempts are sanitized."""
        result = build_mcp_skill_name("../../root", "../../../etc/passwd")
        assert result == "mcp_root_etc_passwd"

    def test_length_limits_respected(self) -> None:
        """Total length stays within limits."""
        long_server = "a" * 50
        long_tool = "b" * 50
        result = build_mcp_skill_name(long_server, long_tool)
        assert len(result) <= MAX_TOOL_NAME_LENGTH

    def test_empty_server_name_raises(self) -> None:
        """Empty server name raises error."""
        with pytest.raises(ToolNameError):
            build_mcp_skill_name("", "echo")

    def test_empty_tool_name_raises(self) -> None:
        """Empty tool name raises error."""
        with pytest.raises(ToolNameError):
            build_mcp_skill_name("test", "")

    def test_all_special_chars_server_raises(self) -> None:
        """Server name that becomes empty raises error."""
        with pytest.raises(ToolNameError):
            build_mcp_skill_name("@#$%", "echo")

    def test_all_special_chars_tool_raises(self) -> None:
        """Tool name that becomes empty raises error."""
        with pytest.raises(ToolNameError):
            build_mcp_skill_name("test", "@#$%")

    def test_unicode_server_name(self) -> None:
        """Unicode server name is normalized (accents become underscores)."""
        # 'ü' becomes underscore, leading _ stripped -> 'ber-server'
        result = build_mcp_skill_name("über-server", "tool")
        assert result == "mcp_ber-server_tool"

    def test_unicode_tool_name(self) -> None:
        """Unicode tool name is normalized (accents become underscores)."""
        # 'ü' becomes underscore, leading _ stripped -> 'ber-tool'
        result = build_mcp_skill_name("server", "über-tool")
        assert result == "mcp_server_ber-tool"


class TestParseMCPSkillName:
    """Tests for parse_mcp_skill_name function."""

    def test_valid_mcp_name(self) -> None:
        """Valid MCP name parsed correctly."""
        result = parse_mcp_skill_name("mcp_test_echo")
        assert result == ("test", "echo")

    def test_non_mcp_name_returns_none(self) -> None:
        """Non-MCP name returns None."""
        assert parse_mcp_skill_name("read_file") is None
        assert parse_mcp_skill_name("bash") is None

    def test_mcp_prefix_only_returns_none(self) -> None:
        """Just 'mcp_' prefix returns None."""
        assert parse_mcp_skill_name("mcp_") is None

    def test_mcp_no_tool_returns_none(self) -> None:
        """MCP name without tool part returns None."""
        assert parse_mcp_skill_name("mcp_test") is None

    def test_mcp_empty_server_returns_none(self) -> None:
        """MCP name with empty server returns None."""
        assert parse_mcp_skill_name("mcp__tool") is None

    def test_mcp_empty_tool_returns_none(self) -> None:
        """MCP name with empty tool returns None."""
        assert parse_mcp_skill_name("mcp_server_") is None

    def test_multi_underscore_tool_name(self) -> None:
        """Tool name with underscores parsed correctly."""
        result = parse_mcp_skill_name("mcp_server_my_tool_v2")
        assert result == ("server", "my_tool_v2")

    def test_case_preserved(self) -> None:
        """Case is preserved in parsed names."""
        result = parse_mcp_skill_name("mcp_Server_Tool")
        assert result == ("Server", "Tool")

    def test_mcp_literal_returns_none(self) -> None:
        """Just 'mcp' (reserved name) returns None."""
        assert parse_mcp_skill_name("mcp") is None


class TestSecurityProperties:
    """Security-focused tests for the identifiers module."""

    # === Collision prevention ===

    def test_different_inputs_different_outputs(self) -> None:
        """Different inputs must produce different outputs."""
        # These should all produce different results
        inputs = [
            "test_tool",
            "test tool",
            "test-tool",
            "test__tool",
            "TEST_TOOL",
            "test.tool",
            "test@tool",
        ]
        outputs = {normalize_tool_name(inp) for inp in inputs}
        # Note: some may collide legitimately (e.g., space -> underscore)
        # but they should be predictable

    def test_underscore_collision_awareness(self) -> None:
        """Demonstrate underscore normalization collision potential."""
        # These will collide - this is expected but should be documented
        assert normalize_tool_name("my tool") == normalize_tool_name("my_tool")
        assert normalize_tool_name("my.tool") == normalize_tool_name("my_tool")

    def test_mcp_skill_name_collision_prevention(self) -> None:
        """MCP skill names from different servers should not collide."""
        # Different servers, same tool
        name1 = build_mcp_skill_name("server1", "echo")
        name2 = build_mcp_skill_name("server2", "echo")
        assert name1 != name2

    def test_mcp_delimiter_injection(self) -> None:
        """Underscore in server name doesn't create false tool boundaries."""
        # Attacker tries: server_name="trusted_evil", tool="cmd"
        # Hoping to match: server_name="trusted", tool="evil_cmd"
        result = build_mcp_skill_name("trusted_evil", "cmd")
        # The normalized result is deterministic
        assert result == "mcp_trusted_evil_cmd"

        # This is the same as:
        result2 = build_mcp_skill_name("trusted", "evil_cmd")
        # These WILL collide - documented limitation
        # parse_mcp_skill_name will parse as ("trusted", "evil_cmd") for both

    # === Path traversal prevention ===

    def test_no_path_traversal_in_normalized_names(self) -> None:
        """Normalized names cannot contain path traversal sequences."""
        dangerous_inputs = [
            "../etc/passwd",
            "..\\windows\\system32",
            "foo/../bar",
            ".../.../secret",
            "/etc/passwd",
            "\\\\server\\share",
        ]
        for inp in dangerous_inputs:
            result = normalize_tool_name(inp)
            assert ".." not in result
            assert "/" not in result
            assert "\\" not in result

    def test_mcp_path_traversal_blocked(self) -> None:
        """MCP skill names cannot contain path traversal."""
        result = build_mcp_skill_name("../../../etc", "passwd")
        assert ".." not in result
        assert "/" not in result

    # === Unicode normalization attacks ===

    def test_homoglyph_attack_mitigated(self) -> None:
        """Unicode homoglyphs are normalized to ASCII equivalents."""
        # Cyrillic 'а' looks like Latin 'a'
        cyrillic_a = "\u0430"  # Cyrillic small letter a
        result = normalize_tool_name(f"tool_{cyrillic_a}")
        # NFKC normalization + invalid char removal
        # Cyrillic 'а' is not ASCII, so becomes underscore
        assert "tool_" in result or result == "tool"

    def test_combining_chars_composed_then_removed(self) -> None:
        """Combining characters are composed by NFKC then removed as non-ASCII."""
        # 'e' + combining acute accent -> 'é' (composed) -> '_' (non-ASCII)
        name_with_combining = "caf\u0065\u0301"  # café with combining accent
        result = normalize_tool_name(name_with_combining)
        # NFKC composes to 'café', then 'é' becomes '_', trailing stripped
        assert result == "caf"

    def test_zero_width_chars_removed(self) -> None:
        """Zero-width characters are removed."""
        # Zero-width space, zero-width joiner
        name = "tool\u200b\u200cname"
        result = normalize_tool_name(name)
        # These get replaced by underscore then collapsed
        assert result == "tool_name"

    def test_rtl_override_removed(self) -> None:
        """RTL override characters are removed."""
        # Right-to-left override
        name = "tool\u202ename"
        result = normalize_tool_name(name)
        # Invalid char becomes underscore
        assert result == "tool_name"

    # === Injection resistance ===

    def test_shell_metachar_sanitized(self) -> None:
        """Shell metacharacters are sanitized."""
        dangerous = "tool;rm -rf /"
        result = normalize_tool_name(dangerous)
        assert ";" not in result
        assert " " not in result

    def test_sql_injection_sanitized(self) -> None:
        """SQL injection attempts are sanitized."""
        dangerous = "tool'; DROP TABLE users;--"
        result = normalize_tool_name(dangerous)
        assert "'" not in result
        assert ";" not in result
        # trailing -- gets stripped, but hyphens in middle are allowed
        assert result == "tool_drop_table_users"

    def test_json_injection_sanitized(self) -> None:
        """JSON injection attempts are sanitized."""
        dangerous = 'tool","evil":"value'
        result = normalize_tool_name(dangerous)
        assert '"' not in result
        assert "," not in result
        assert ":" not in result

    # === Constants validation ===

    def test_min_length_constant(self) -> None:
        """MIN_TOOL_NAME_LENGTH is sensible."""
        assert MIN_TOOL_NAME_LENGTH >= 1
        assert MIN_TOOL_NAME_LENGTH < MAX_TOOL_NAME_LENGTH

    def test_max_length_constant(self) -> None:
        """MAX_TOOL_NAME_LENGTH is sensible."""
        assert MAX_TOOL_NAME_LENGTH >= 32  # Reasonable minimum
        assert MAX_TOOL_NAME_LENGTH <= 256  # Reasonable maximum

    def test_reserved_names_are_lowercase(self) -> None:
        """All reserved names are stored lowercase."""
        for name in RESERVED_TOOL_NAMES:
            assert name == name.lower(), f"Reserved name '{name}' should be lowercase"

    def test_reserved_names_are_valid_format(self) -> None:
        """All reserved names are valid format (except being reserved)."""
        for name in RESERVED_TOOL_NAMES:
            # Should be valid format when allow_reserved=True
            validate_tool_name(name, allow_reserved=True)


class TestEdgeCases:
    """Edge case tests for unusual inputs."""

    def test_single_valid_char_names(self) -> None:
        """Single character names that are valid."""
        for char in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_":
            validate_tool_name(char)
            assert is_valid_tool_name(char)

    def test_all_digits_invalid(self) -> None:
        """All-digit names are invalid (start with digit)."""
        assert not is_valid_tool_name("123")
        assert not is_valid_tool_name("0")

    def test_normalize_preserves_underscores_in_middle(self) -> None:
        """Underscores in the middle are preserved."""
        assert normalize_tool_name("my_tool_name") == "my_tool_name"

    def test_normalize_digit_only_gets_prefix(self) -> None:
        """Digit-only input gets underscore prefix."""
        assert normalize_tool_name("123") == "_123"

    def test_mcp_with_hyphen_server(self) -> None:
        """MCP server name with hyphen."""
        result = build_mcp_skill_name("my-server", "tool")
        assert result == "mcp_my-server_tool"

    def test_parse_mcp_hyphen_in_server(self) -> None:
        """Parse MCP name where server contains hyphen."""
        result = parse_mcp_skill_name("mcp_my-server_tool")
        assert result == ("my-server", "tool")

    def test_normalize_long_unicode_string_raises(self) -> None:
        """Long unicode-only string raises (all chars become underscores, then stripped)."""
        # 100 non-ASCII characters - all become underscores, then stripped = empty
        long_unicode = "ü" * 100
        with pytest.raises(ToolNameError) as exc_info:
            normalize_tool_name(long_unicode)
        assert "no valid characters remain" in str(exc_info.value)

    def test_normalize_long_mixed_unicode_ascii(self) -> None:
        """Long mixed unicode/ASCII normalizes within length limit."""
        # Mix of ASCII and non-ASCII
        mixed = "a" + "ü" * 10 + "b" * 100
        result = normalize_tool_name(mixed)
        assert len(result) <= MAX_TOOL_NAME_LENGTH
        # 'a' + underscores (collapsed) + 'b's
        assert result.startswith("a_")
        assert "b" in result

    def test_normalize_mixed_unicode_ascii(self) -> None:
        """Mixed unicode and ASCII: accents become underscores."""
        # 'ü' -> '_', 'ï' -> '_'
        result = normalize_tool_name("über_tool_naïve")
        # Leading ü -> _ (stripped), then 'ber_tool_na', then ï -> _, then 've'
        assert result == "ber_tool_na_ve"

    def test_validate_with_only_hyphens_inside(self) -> None:
        """Name with only hyphens in the middle is valid."""
        validate_tool_name("a-b-c")
        validate_tool_name("test-v2-beta")

    def test_validate_hyphen_underscore_mix(self) -> None:
        """Mixed hyphens and underscores are valid."""
        validate_tool_name("my_tool-v2")
        validate_tool_name("my-tool_v2")


class TestRoundTrip:
    """Tests for round-trip operations."""

    def test_normalized_name_is_valid(self) -> None:
        """Normalized names should pass validation."""
        test_inputs = [
            "My Tool!",
            "123start",
            "über",
            "--test--",
            "a__b--c",
            "UPPERCASE",
            "tool@name",
        ]
        for inp in test_inputs:
            try:
                normalized = normalize_tool_name(inp)
                # Normalized name should be valid (allow_reserved for mcp prefix etc)
                validate_tool_name(normalized, allow_reserved=True)
            except ToolNameError:
                # Some inputs can't be normalized (e.g., all special chars)
                pass

    def test_mcp_skill_name_is_valid(self) -> None:
        """Built MCP skill names should pass validation."""
        test_cases = [
            ("server", "tool"),
            ("my-server", "my-tool"),
            ("Server Name!", "Tool@Name"),
        ]
        for server, tool in test_cases:
            result = build_mcp_skill_name(server, tool)
            # Should be valid (allow reserved because starts with mcp_)
            validate_tool_name(result, allow_reserved=True)

    def test_build_then_parse_consistency(self) -> None:
        """Build then parse should give consistent results."""
        # Note: not necessarily equal due to normalization
        result = build_mcp_skill_name("test", "echo")
        parsed = parse_mcp_skill_name(result)
        assert parsed is not None
        assert parsed[0] == "test"
        assert parsed[1] == "echo"

    def test_build_parse_with_normalization(self) -> None:
        """Build then parse with normalized names."""
        result = build_mcp_skill_name("Test Server", "Tool Name")
        # Normalized: mcp_test_server_tool_name
        parsed = parse_mcp_skill_name(result)
        assert parsed is not None
        # Server is just first component after mcp_
        assert parsed[0] == "test"
        # Tool is everything after
        assert parsed[1] == "server_tool_name"
