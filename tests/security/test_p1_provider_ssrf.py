"""P1.6: Test that provider base_url has SSRF protection.

This tests the security issue where a malicious base_url config could make
the server send requests to internal services (Server-Side Request Forgery).

The fix:
- HTTPS URLs are always allowed
- HTTP URLs only allowed for loopback (localhost, 127.0.0.1, ::1)
- Other schemes (file://, ftp://, etc.) are rejected
- Explicit opt-in required for HTTP on non-loopback
"""

import pytest


class TestValidateBaseUrl:
    """Test the validate_base_url function directly."""

    def test_https_allowed(self) -> None:
        """HTTPS URLs should always be allowed."""
        from nexus3.provider.base import validate_base_url

        # These should not raise
        validate_base_url("https://api.openai.com/v1")
        validate_base_url("https://openrouter.ai/api/v1")
        validate_base_url("https://api.anthropic.com")
        validate_base_url("https://internal.corp.com/api")
        validate_base_url("HTTPS://UPPERCASE.COM")

    def test_http_localhost_allowed(self) -> None:
        """HTTP localhost URLs should be allowed."""
        from nexus3.provider.base import validate_base_url

        # These should not raise
        validate_base_url("http://localhost:11434/v1")
        validate_base_url("http://localhost/api")
        validate_base_url("http://127.0.0.1:8080")
        validate_base_url("http://127.0.0.1/v1")
        validate_base_url("HTTP://LOCALHOST:8000")

    def test_http_ipv6_localhost_allowed(self) -> None:
        """HTTP IPv6 loopback should be allowed."""
        from nexus3.provider.base import validate_base_url

        # These should not raise
        validate_base_url("http://[::1]:8080")
        validate_base_url("http://[::1]/api")

    def test_http_non_localhost_rejected(self) -> None:
        """HTTP non-localhost URLs should be rejected."""
        from nexus3.core.errors import ProviderError
        from nexus3.provider.base import validate_base_url

        bad_urls = [
            "http://internal.corp.com/api",
            "http://192.168.1.1:8080",
            "http://10.0.0.5/v1",
            "http://172.16.0.1/api",
            "http://example.com",
            "http://metadata.google.internal/",  # Cloud metadata endpoint
            "http://169.254.169.254/",  # AWS metadata endpoint
        ]

        for url in bad_urls:
            with pytest.raises(ProviderError) as exc_info:
                validate_base_url(url)
            assert "security" in str(exc_info.value).lower()

    def test_http_allowed_with_insecure_flag(self) -> None:
        """HTTP non-localhost allowed when allow_insecure=True."""
        from nexus3.provider.base import validate_base_url

        # With allow_insecure=True, HTTP should be allowed
        validate_base_url("http://internal.corp.com/api", allow_insecure=True)
        validate_base_url("http://10.0.0.5/v1", allow_insecure=True)

    def test_empty_url_rejected(self) -> None:
        """Empty URLs should be rejected."""
        from nexus3.core.errors import ProviderError
        from nexus3.provider.base import validate_base_url

        with pytest.raises(ProviderError) as exc_info:
            validate_base_url("")
        assert "empty" in str(exc_info.value).lower()

    def test_no_scheme_rejected(self) -> None:
        """URLs without scheme should be rejected."""
        from nexus3.core.errors import ProviderError
        from nexus3.provider.base import validate_base_url

        with pytest.raises(ProviderError) as exc_info:
            validate_base_url("api.openai.com/v1")
        assert "scheme" in str(exc_info.value).lower()

    def test_file_scheme_rejected(self) -> None:
        """file:// URLs should be rejected."""
        from nexus3.core.errors import ProviderError
        from nexus3.provider.base import validate_base_url

        with pytest.raises(ProviderError) as exc_info:
            validate_base_url("file:///etc/passwd")
        assert "not allowed" in str(exc_info.value).lower()

    def test_ftp_scheme_rejected(self) -> None:
        """ftp:// URLs should be rejected."""
        from nexus3.core.errors import ProviderError
        from nexus3.provider.base import validate_base_url

        with pytest.raises(ProviderError) as exc_info:
            validate_base_url("ftp://evil.com/malware")
        assert "not allowed" in str(exc_info.value).lower()


class TestProviderInitValidation:
    """Test that providers validate base_url on init."""

    def test_provider_rejects_http_non_localhost(self) -> None:
        """Provider constructor should reject HTTP non-localhost."""
        from nexus3.config.schema import AuthMethod, ProviderConfig
        from nexus3.core.errors import ProviderError
        from nexus3.provider.openai_compat import OpenAICompatProvider

        config = ProviderConfig(
            type="openai",
            base_url="http://internal.corp.com/api",
            auth_method=AuthMethod.NONE,  # Skip API key check
        )

        with pytest.raises(ProviderError) as exc_info:
            OpenAICompatProvider(config, model_id="test")

        assert "security" in str(exc_info.value).lower()

    def test_provider_accepts_https(self) -> None:
        """Provider constructor should accept HTTPS."""
        from nexus3.config.schema import AuthMethod, ProviderConfig
        from nexus3.provider.openai_compat import OpenAICompatProvider

        config = ProviderConfig(
            type="openai",
            base_url="https://api.openai.com/v1",
            auth_method=AuthMethod.NONE,  # Skip API key check
        )

        # Should not raise
        provider = OpenAICompatProvider(config, model_id="gpt-4")
        assert provider._base_url == "https://api.openai.com/v1"

    def test_provider_accepts_http_localhost(self) -> None:
        """Provider constructor should accept HTTP localhost."""
        from nexus3.config.schema import AuthMethod, ProviderConfig
        from nexus3.provider.openai_compat import OpenAICompatProvider

        config = ProviderConfig(
            type="ollama",
            base_url="http://localhost:11434/v1",
            auth_method=AuthMethod.NONE,
        )

        # Should not raise
        provider = OpenAICompatProvider(config, model_id="llama3")
        assert provider._base_url == "http://localhost:11434/v1"

    def test_provider_accepts_http_with_insecure_flag(self) -> None:
        """Provider should accept HTTP non-localhost with allow_insecure_http."""
        from nexus3.config.schema import AuthMethod, ProviderConfig
        from nexus3.provider.openai_compat import OpenAICompatProvider

        config = ProviderConfig(
            type="vllm",
            base_url="http://gpu-server.internal:8000/v1",
            auth_method=AuthMethod.NONE,
            allow_insecure_http=True,  # Explicit opt-in
        )

        # Should not raise
        provider = OpenAICompatProvider(config, model_id="llama")
        assert provider._base_url == "http://gpu-server.internal:8000/v1"


class TestSSRFAttackVectors:
    """Test specific SSRF attack vectors are blocked."""

    def test_blocks_aws_metadata(self) -> None:
        """Block access to AWS metadata endpoint."""
        from nexus3.core.errors import ProviderError
        from nexus3.provider.base import validate_base_url

        with pytest.raises(ProviderError):
            validate_base_url("http://169.254.169.254/latest/meta-data/")

    def test_blocks_gcp_metadata(self) -> None:
        """Block access to GCP metadata endpoint."""
        from nexus3.core.errors import ProviderError
        from nexus3.provider.base import validate_base_url

        with pytest.raises(ProviderError):
            validate_base_url("http://metadata.google.internal/")

    def test_blocks_azure_metadata(self) -> None:
        """Block access to Azure metadata endpoint."""
        from nexus3.core.errors import ProviderError
        from nexus3.provider.base import validate_base_url

        with pytest.raises(ProviderError):
            validate_base_url("http://169.254.169.254/metadata/instance")

    def test_blocks_internal_network(self) -> None:
        """Block access to internal network ranges."""
        from nexus3.core.errors import ProviderError
        from nexus3.provider.base import validate_base_url

        internal_urls = [
            "http://10.0.0.1/internal-api",
            "http://172.16.0.1/internal-api",
            "http://192.168.1.1/internal-api",
        ]

        for url in internal_urls:
            with pytest.raises(ProviderError):
                validate_base_url(url)
