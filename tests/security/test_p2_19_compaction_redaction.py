"""Tests for P2.19: Compaction Secrets Redaction.

These tests verify that sensitive information (API keys, tokens, passwords,
private keys, connection strings) is redacted before conversation history
is sent to the summarization LLM during context compaction.

This prevents secrets from being leaked to the summarization model, which
may have different security properties than the main conversation model.
"""

import pytest

from nexus3.config.schema import CompactionConfig
from nexus3.context.compaction import format_messages_for_summary
from nexus3.core.redaction import (
    REDACTED,
    SECRET_PATTERNS,
    redact_dict,
    redact_secrets,
)
from nexus3.core.types import Message, Role, ToolCall


class TestOpenAIKeyRedaction:
    """Tests for OpenAI API key detection and redaction."""

    def test_redacts_openai_key_basic(self) -> None:
        """Standard OpenAI API key is redacted."""
        text = "My API key is sk-abcdefghijklmnopqrstuvwxyz123456789012345678"
        result = redact_secrets(text)
        assert "sk-abcdefghijklmnopqrstuvwxyz" not in result
        assert REDACTED in result

    def test_redacts_openai_key_in_env(self) -> None:
        """OpenAI key in environment variable format is redacted."""
        text = "OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz1234567890"
        result = redact_secrets(text)
        assert "sk-proj" not in result
        assert REDACTED in result

    def test_redacts_openai_key_in_json(self) -> None:
        """OpenAI key in JSON format is redacted."""
        text = '{"api_key": "sk-1234567890abcdefghijklmnopqrstuvwxyz123"}'
        result = redact_secrets(text)
        assert "sk-1234567890" not in result
        assert REDACTED in result

    def test_preserves_short_sk_prefix(self) -> None:
        """Short strings starting with 'sk-' are not redacted (not long enough)."""
        text = "The variable sk-short is not a key"
        result = redact_secrets(text)
        # sk-short is only 8 chars, pattern requires 20+
        assert "sk-short" in result


class TestAnthropicKeyRedaction:
    """Tests for Anthropic API key detection and redaction."""

    def test_redacts_anthropic_key_basic(self) -> None:
        """Standard Anthropic API key is redacted."""
        text = "Key: sk-ant-api03-abcdefghijklmnopqrstuvwxyz123456"
        result = redact_secrets(text)
        assert "sk-ant-api03" not in result
        assert REDACTED in result

    def test_redacts_anthropic_key_in_config(self) -> None:
        """Anthropic key in config format is redacted."""
        text = 'anthropic_key = "sk-ant-test-abcdefghijklmnopqrstuvwxyz"'
        result = redact_secrets(text)
        assert "sk-ant-test" not in result
        assert REDACTED in result


class TestGitHubTokenRedaction:
    """Tests for GitHub token detection and redaction."""

    def test_redacts_ghp_token(self) -> None:
        """GitHub personal access token (ghp_) is redacted."""
        text = "GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz1234567890"
        result = redact_secrets(text)
        assert "ghp_" not in result
        assert REDACTED in result

    def test_redacts_gho_token(self) -> None:
        """GitHub OAuth token (gho_) is redacted."""
        text = "token: gho_abcdefghijklmnopqrstuvwxyz1234567890"
        result = redact_secrets(text)
        assert "gho_" not in result
        assert REDACTED in result

    def test_redacts_ghs_token(self) -> None:
        """GitHub server token (ghs_) is redacted."""
        text = "GHS_TOKEN=ghs_abcdefghijklmnopqrstuvwxyz1234567890"
        result = redact_secrets(text)
        assert "ghs_" not in result
        assert REDACTED in result

    def test_redacts_ghr_token(self) -> None:
        """GitHub refresh token (ghr_) is redacted."""
        text = "refresh: ghr_abcdefghijklmnopqrstuvwxyz1234567890"
        result = redact_secrets(text)
        assert "ghr_" not in result
        assert REDACTED in result


class TestAWSKeyRedaction:
    """Tests for AWS credential detection and redaction."""

    def test_redacts_aws_access_key_id(self) -> None:
        """AWS Access Key ID (AKIA...) is redacted."""
        text = "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
        result = redact_secrets(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert REDACTED in result

    def test_redacts_aws_secret_key(self) -> None:
        """AWS Secret Access Key is redacted."""
        text = "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        result = redact_secrets(text)
        assert "wJalrXUtnFEMI" not in result
        assert REDACTED in result

    def test_redacts_aws_secret_key_json(self) -> None:
        """AWS Secret Key in JSON-like format is redacted."""
        # Without quotes around the key name (common in config files, env vars)
        text = 'secret_access_key: "abcdefghijklmnopqrstuvwxyz1234567890AB"'
        result = redact_secrets(text)
        assert "abcdefghijklmnopqrstuvwxyz" not in result
        assert REDACTED in result


class TestBearerTokenRedaction:
    """Tests for Bearer token detection and redaction."""

    def test_redacts_bearer_token(self) -> None:
        """Bearer token in Authorization header is redacted."""
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test"
        result = redact_secrets(text)
        assert "eyJhbGciOiJIUzI1NiI" not in result
        assert "Authorization: Bearer" in result  # Header preserved
        assert REDACTED in result

    def test_redacts_bearer_lowercase(self) -> None:
        """Bearer token with lowercase authorization is redacted."""
        text = "authorization: bearer abc123def456ghi789jkl012mno"
        result = redact_secrets(text)
        assert "abc123def456" not in result
        assert REDACTED in result


class TestPasswordRedaction:
    """Tests for password detection and redaction."""

    def test_redacts_password_assignment(self) -> None:
        """Password in assignment format is redacted."""
        text = 'password = "supersecret123"'
        result = redact_secrets(text)
        assert "supersecret123" not in result
        assert REDACTED in result

    def test_redacts_passwd_assignment(self) -> None:
        """passwd variation is redacted."""
        text = "passwd: mysecretpassword"
        result = redact_secrets(text)
        assert "mysecretpassword" not in result
        assert REDACTED in result

    def test_redacts_pwd_assignment(self) -> None:
        """pwd variation is redacted."""
        text = "pwd=hunter2"
        result = redact_secrets(text)
        assert "hunter2" not in result
        assert REDACTED in result

    def test_redacts_password_in_url(self) -> None:
        """Password in URL credentials is redacted."""
        text = "postgresql://admin:secretpass@localhost:5432/mydb"
        result = redact_secrets(text)
        assert "secretpass" not in result
        assert "admin:" in result  # Username preserved
        assert "@localhost" in result  # Host preserved


class TestPrivateKeyRedaction:
    """Tests for private key block detection and redaction."""

    def test_redacts_rsa_private_key(self) -> None:
        """RSA private key block is redacted."""
        text = """-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA1234567890abcdefghijklmnopqrstuvwxyz
ABCDEFGHIJKLMNOPQRSTUVWXYZ0987654321
-----END RSA PRIVATE KEY-----"""
        result = redact_secrets(text)
        assert "MIIEowIBAAKCAQEA" not in result
        assert "-----BEGIN RSA PRIVATE KEY-----" in result
        assert "-----END RSA PRIVATE KEY-----" in result
        assert REDACTED in result

    def test_redacts_ec_private_key(self) -> None:
        """EC private key block is redacted."""
        text = """-----BEGIN EC PRIVATE KEY-----
MHQCAQEEINJTRu0a1234567890abcdefghijklmnopqrstuvwxyz
-----END EC PRIVATE KEY-----"""
        result = redact_secrets(text)
        assert "MHQCAQEEINJTRu0a" not in result
        assert REDACTED in result

    def test_redacts_openssh_private_key(self) -> None:
        """OpenSSH private key block is redacted."""
        text = """-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmU
-----END OPENSSH PRIVATE KEY-----"""
        result = redact_secrets(text)
        assert "b3BlbnNzaC1rZXktdjE" not in result
        assert REDACTED in result


class TestConnectionStringRedaction:
    """Tests for database connection string credential redaction."""

    def test_redacts_postgresql_password(self) -> None:
        """PostgreSQL connection string password is redacted."""
        text = "DATABASE_URL=postgresql://user:password123@db.example.com:5432/mydb"
        result = redact_secrets(text)
        assert "password123" not in result
        assert "postgresql://user:" in result
        assert "@db.example.com" in result

    def test_redacts_mysql_password(self) -> None:
        """MySQL connection string password is redacted."""
        text = "mysql://root:topsecret@localhost/app"
        result = redact_secrets(text)
        assert "topsecret" not in result
        assert "mysql://root:" in result

    def test_redacts_mongodb_password(self) -> None:
        """MongoDB connection string password is redacted."""
        text = "mongodb://admin:mongopass@mongo.example.com/db"
        result = redact_secrets(text)
        assert "mongopass" not in result
        assert "mongodb://admin:" in result

    def test_redacts_redis_password(self) -> None:
        """Redis connection string password is redacted."""
        text = "redis://default:redispass@cache.example.com:6379"
        result = redact_secrets(text)
        assert "redispass" not in result

    def test_redacts_mongodb_srv_password(self) -> None:
        """MongoDB+srv connection string password is redacted."""
        text = "mongodb+srv://admin:srvpass@cluster.mongodb.net/db"
        result = redact_secrets(text)
        assert "srvpass" not in result


class TestJWTRedaction:
    """Tests for JWT token detection and redaction."""

    def test_redacts_jwt_token(self) -> None:
        """JWT token is redacted."""
        # Standard JWT format: header.payload.signature (all base64url)
        text = "token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        result = redact_secrets(text)
        assert "eyJhbGciOiJIUzI1NiI" not in result
        assert REDACTED in result


class TestNexusTokenRedaction:
    """Tests for NEXUS3 RPC token detection and redaction."""

    def test_redacts_nexus_token_basic(self) -> None:
        """Standard NEXUS RPC token is redacted."""
        text = "RPC_TOKEN=nxk_abcdefghijklmnopqrstuvwxyz1234567890ABCD"
        result = redact_secrets(text)
        assert "nxk_abcdefghijklmnopqrstuvwxyz" not in result
        assert REDACTED in result

    def test_redacts_nexus_token_in_message(self) -> None:
        """NEXUS token in conversation context is redacted."""
        text = "The token file contains: nxk_Xyz123AbcDefGhiJklMnoPqrStUvWxyz0123456789"
        result = redact_secrets(text)
        assert "nxk_Xyz123" not in result
        assert REDACTED in result

    def test_redacts_nexus_token_with_special_chars(self) -> None:
        """NEXUS token with dashes, underscores, and slashes is redacted."""
        text = "token: nxk_abc-def_ghi/jkl-mno_pqr/stu-vwx_yz0123456789"
        result = redact_secrets(text)
        assert "nxk_abc-def" not in result
        assert REDACTED in result

    def test_preserves_short_nxk_prefix(self) -> None:
        """Short strings starting with 'nxk_' are not redacted (not long enough)."""
        text = "The variable nxk_short is not a token"
        result = redact_secrets(text)
        # nxk_short is only 9 chars after prefix, pattern requires 40+
        assert "nxk_short" in result


class TestFalsePositives:
    """Tests that legitimate text is not over-redacted."""

    def test_preserves_normal_text(self) -> None:
        """Normal conversation text is not modified."""
        text = "I want to create a function that processes user input."
        result = redact_secrets(text)
        assert result == text

    def test_preserves_code_snippets(self) -> None:
        """Code without secrets is preserved."""
        text = """def calculate_sum(a, b):
    return a + b"""
        result = redact_secrets(text)
        assert result == text

    def test_preserves_urls_without_credentials(self) -> None:
        """URLs without credentials are preserved."""
        text = "Visit https://example.com/api/v1/users for the API docs."
        result = redact_secrets(text)
        assert result == text

    def test_preserves_word_password(self) -> None:
        """The word 'password' without assignment is preserved."""
        text = "Enter your password in the form below."
        result = redact_secrets(text)
        # "password" alone without = or : is preserved
        assert "password" in result

    def test_preserves_short_tokens(self) -> None:
        """Short strings that look like tokens are preserved."""
        text = "The value is sk-abc"  # Too short to be a real key
        result = redact_secrets(text)
        assert "sk-abc" in result

    def test_preserves_file_paths(self) -> None:
        """File paths are not confused with secrets."""
        text = "/home/user/.ssh/id_rsa is the default key location"
        result = redact_secrets(text)
        assert result == text

    def test_preserves_hex_strings(self) -> None:
        """Generic hex strings without secret context are preserved."""
        text = "The commit hash is abc123def456789012345678901234567890"
        result = redact_secrets(text)
        # Should be preserved (no secret pattern match)
        assert "abc123def456789012345678901234567890" in result


class TestRedactDict:
    """Tests for recursive dictionary redaction."""

    def test_redacts_string_values(self) -> None:
        """String values containing secrets are redacted."""
        data = {"key": "sk-abcdefghijklmnopqrstuvwxyz123456789012345678"}
        result = redact_dict(data)
        assert REDACTED in result["key"]
        assert "sk-abcdefghijklmnopqrstuvwxyz" not in result["key"]

    def test_redacts_nested_dicts(self) -> None:
        """Nested dictionary values are recursively redacted."""
        data = {
            "outer": {
                "inner": {
                    "secret": "sk-abcdefghijklmnopqrstuvwxyz12345678901234"
                }
            }
        }
        result = redact_dict(data)
        assert REDACTED in result["outer"]["inner"]["secret"]

    def test_redacts_list_values(self) -> None:
        """List values are recursively redacted."""
        data = {
            "keys": [
                "sk-key1abcdefghijklmnopqrstuvwxyz123456",
                "sk-key2abcdefghijklmnopqrstuvwxyz123456",
            ]
        }
        result = redact_dict(data)
        assert all(REDACTED in key for key in result["keys"])

    def test_preserves_non_string_values(self) -> None:
        """Non-string values (int, bool, None) are preserved."""
        data = {
            "count": 42,
            "enabled": True,
            "nullable": None,
            "ratio": 3.14,
        }
        result = redact_dict(data)
        assert result == data

    def test_does_not_modify_original(self) -> None:
        """Original dictionary is not modified."""
        original = {"key": "sk-abcdefghijklmnopqrstuvwxyz123456789012345678"}
        original_copy = original.copy()
        redact_dict(original)
        assert original == original_copy

    def test_handles_tuple_values(self) -> None:
        """Tuple values are converted and redacted."""
        data = {
            "tokens": ("sk-token1abcdefghijklmnopqrstuvwxyz1234", "safe_value")
        }
        result = redact_dict(data)
        # Tuples become tuples in result
        assert isinstance(result["tokens"], tuple)
        assert REDACTED in result["tokens"][0]
        assert result["tokens"][1] == "safe_value"


class TestFormatMessagesForSummary:
    """Tests for format_messages_for_summary with redaction."""

    def test_redacts_message_content(self) -> None:
        """Message content with secrets is redacted."""
        messages = [
            Message(
                role=Role.USER,
                content="My API key is sk-abcdefghijklmnopqrstuvwxyz123456789012345678",
            )
        ]
        result = format_messages_for_summary(messages)
        assert "sk-abcdefghijklmnopqrstuvwxyz" not in result
        assert REDACTED in result
        assert "USER:" in result

    def test_redacts_tool_arguments(self) -> None:
        """Tool call arguments with secrets are redacted."""
        messages = [
            Message(
                role=Role.ASSISTANT,
                content="I'll write the config file.",
                tool_calls=(
                    ToolCall(
                        id="tc_1",
                        name="write_file",
                        arguments={
                            "path": "/tmp/config.json",
                            "content": '{"api_key": "sk-secretkey12345678901234567890123456"}',
                        },
                    ),
                ),
            )
        ]
        result = format_messages_for_summary(messages)
        assert "sk-secretkey12345678901234567890" not in result
        assert "write_file" in result
        assert "/tmp/config.json" in result

    def test_redacts_tool_result_content(self) -> None:
        """Tool result message content is redacted."""
        messages = [
            Message(
                role=Role.TOOL,
                content='Config file contents: {"password": "secret123"}',
                tool_call_id="tc_1",
            )
        ]
        result = format_messages_for_summary(messages)
        assert "secret123" not in result
        assert REDACTED in result

    def test_redact_disabled(self) -> None:
        """When redact=False, secrets are preserved."""
        messages = [
            Message(
                role=Role.USER,
                content="Key: sk-abcdefghijklmnopqrstuvwxyz123456789012345678",
            )
        ]
        result = format_messages_for_summary(messages, redact=False)
        assert "sk-abcdefghijklmnopqrstuvwxyz123456789012345678" in result
        assert REDACTED not in result

    def test_preserves_message_structure(self) -> None:
        """Redaction preserves overall message formatting."""
        messages = [
            Message(role=Role.USER, content="Hello"),
            Message(role=Role.ASSISTANT, content="Hi there!"),
            Message(role=Role.USER, content="How are you?"),
        ]
        result = format_messages_for_summary(messages)
        assert "USER: Hello" in result
        assert "ASSISTANT: Hi there!" in result
        assert "USER: How are you?" in result

    def test_multiple_secrets_in_one_message(self) -> None:
        """Multiple secrets in one message are all redacted."""
        messages = [
            Message(
                role=Role.USER,
                content=(
                    "OpenAI: sk-openai12345678901234567890123456789012\n"
                    "Anthropic: sk-ant-anthropic1234567890123456789012\n"
                    "GitHub: ghp_github12345678901234567890123456789012"
                ),
            )
        ]
        result = format_messages_for_summary(messages)
        assert "sk-openai" not in result
        assert "sk-ant-anthropic" not in result
        assert "ghp_github" not in result
        assert result.count(REDACTED) >= 3


class TestCompactionConfigRedactSecrets:
    """Tests for the redact_secrets configuration option."""

    def test_default_is_true(self) -> None:
        """redact_secrets defaults to True."""
        config = CompactionConfig()
        assert config.redact_secrets is True

    def test_can_be_disabled(self) -> None:
        """redact_secrets can be set to False."""
        config = CompactionConfig(redact_secrets=False)
        assert config.redact_secrets is False

    def test_from_dict(self) -> None:
        """redact_secrets can be loaded from dict (like JSON config)."""
        config = CompactionConfig.model_validate({"redact_secrets": False})
        assert config.redact_secrets is False


class TestSecretPatternsCompleteness:
    """Tests to verify all expected patterns are present."""

    def test_all_expected_patterns_exist(self) -> None:
        """All documented secret types have patterns."""
        expected = [
            "openai_key",
            "anthropic_key",
            "github_token",
            "aws_access_key",
            "aws_secret_key",
            "bearer_token",
            "generic_api_key",
            "password_assignment",
            "password_in_url",
            "private_key_block",
            "connection_string",
            "jwt_token",
            "nexus_token",
        ]
        for pattern_name in expected:
            assert pattern_name in SECRET_PATTERNS, f"Missing pattern: {pattern_name}"

    def test_patterns_are_compiled(self) -> None:
        """All patterns are pre-compiled regex objects."""
        import re
        for name, (pattern, _) in SECRET_PATTERNS.items():
            assert isinstance(pattern, re.Pattern), f"{name} is not compiled"


class TestEdgeCases:
    """Edge case tests for robustness."""

    def test_empty_string(self) -> None:
        """Empty string returns empty string."""
        assert redact_secrets("") == ""

    def test_empty_dict(self) -> None:
        """Empty dict returns empty dict."""
        assert redact_dict({}) == {}

    def test_empty_messages_list(self) -> None:
        """Empty messages list returns empty string."""
        assert format_messages_for_summary([]) == ""

    def test_unicode_content(self) -> None:
        """Unicode content is handled correctly."""
        text = "Key: sk-abcdefghijklmnopqrstuvwxyz123456789012345678"
        result = redact_secrets(text)
        assert REDACTED in result

    def test_multiline_message_content(self) -> None:
        """Multiline message content is handled correctly."""
        messages = [
            Message(
                role=Role.USER,
                content="Line 1\nLine 2\nKey: sk-abcdefghijklmnopqrstuvwxyz123456789012345678\nLine 4",
            )
        ]
        result = format_messages_for_summary(messages)
        assert "Line 1" in result
        assert "Line 4" in result
        assert "sk-abcdefghijklmnopqrstuvwxyz" not in result

    def test_special_characters_in_password(self) -> None:
        """Passwords with special characters are redacted."""
        text = 'password = "P@ss!w0rd#$%"'
        result = redact_secrets(text)
        assert "P@ss!w0rd" not in result
        assert REDACTED in result
