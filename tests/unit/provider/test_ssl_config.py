"""Tests for SSL configuration: custom CA cert handling and path normalization.

Verifies:
- ssl_ca_cert path is normalized via Pydantic field validator
- _ensure_client() builds ssl.SSLContext when ssl_ca_cert is set
- Custom CA is added to system CAs (not replacing them)
- Non-existent cert path produces a warning
"""

import os
import ssl
import warnings
from unittest.mock import MagicMock, patch

import httpx
import pytest

from nexus3.config.schema import ProviderConfig
from nexus3.provider import OpenRouterProvider


class TestSSLCaCertNormalization:
    """Tests for ssl_ca_cert field validator in ProviderConfig."""

    def test_ssl_ca_cert_normalized_to_absolute(self, tmp_path: object) -> None:
        """ssl_ca_cert is normalized to an absolute path."""
        cert_file = tmp_path / "cert.pem"  # type: ignore[operator]
        cert_file.write_text("-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----\n")

        config = ProviderConfig(ssl_ca_cert=str(cert_file))

        assert config.ssl_ca_cert is not None
        assert os.path.isabs(config.ssl_ca_cert)
        assert config.ssl_ca_cert == str(cert_file)

    def test_ssl_ca_cert_expands_tilde(self, tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
        """ssl_ca_cert expands ~ to home directory."""
        monkeypatch.setenv("HOME", str(tmp_path))
        cert_file = tmp_path / "my-cert.pem"  # type: ignore[operator]
        cert_file.write_text("-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----\n")

        config = ProviderConfig(ssl_ca_cert="~/my-cert.pem")

        assert config.ssl_ca_cert is not None
        assert str(tmp_path) in config.ssl_ca_cert
        assert "~" not in config.ssl_ca_cert

    def test_ssl_ca_cert_warns_nonexistent_file(self) -> None:
        """ssl_ca_cert warns when the file does not exist."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = ProviderConfig(ssl_ca_cert="/nonexistent/path/cert.pem")

        assert len(w) == 1
        assert "does not exist" in str(w[0].message)
        assert "/nonexistent/path/cert.pem" in str(w[0].message)
        # Path still normalized even if it doesn't exist
        assert config.ssl_ca_cert is not None
        assert os.path.isabs(config.ssl_ca_cert)

    def test_ssl_ca_cert_none_stays_none(self) -> None:
        """ssl_ca_cert=None is not normalized (stays None)."""
        config = ProviderConfig(ssl_ca_cert=None)
        assert config.ssl_ca_cert is None

    def test_ssl_ca_cert_default_is_none(self) -> None:
        """ssl_ca_cert defaults to None."""
        config = ProviderConfig()
        assert config.ssl_ca_cert is None


class TestSSLContextBuilding:
    """Tests for _ensure_client() SSL context building with custom CA."""

    @pytest.fixture
    def ssl_provider(self, tmp_path: object) -> OpenRouterProvider:
        """Create a provider with ssl_ca_cert set."""
        cert_file = tmp_path / "ca-cert.pem"  # type: ignore[operator]
        cert_file.write_text("-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----\n")

        config = ProviderConfig(
            api_key_env="TEST_SSL_CONFIG_KEY",
            ssl_ca_cert=str(cert_file),
        )
        os.environ["TEST_SSL_CONFIG_KEY"] = "test-key"
        try:
            provider = OpenRouterProvider(config, "test-model")
        finally:
            os.environ.pop("TEST_SSL_CONFIG_KEY", None)
        return provider

    @pytest.fixture
    def plain_provider(self) -> OpenRouterProvider:
        """Create a provider without ssl_ca_cert."""
        config = ProviderConfig(api_key_env="TEST_SSL_CONFIG_PLAIN_KEY")
        os.environ["TEST_SSL_CONFIG_PLAIN_KEY"] = "test-key"
        try:
            provider = OpenRouterProvider(config, "test-model")
        finally:
            os.environ.pop("TEST_SSL_CONFIG_PLAIN_KEY", None)
        return provider

    @pytest.mark.asyncio
    async def test_ensure_client_builds_ssl_context_with_ca_cert(
        self, ssl_provider: OpenRouterProvider
    ) -> None:
        """_ensure_client() passes ssl.SSLContext (not string) when ssl_ca_cert is set."""
        mock_ctx = MagicMock(spec=ssl.SSLContext)
        call_kwargs: dict[str, object] = {}
        original_init = httpx.AsyncClient.__init__

        def patched_init(self: httpx.AsyncClient, **kwargs: object) -> None:
            call_kwargs.update(kwargs)
            return original_init(self, **kwargs)

        with (
            patch("nexus3.provider.base.ssl.create_default_context", return_value=mock_ctx),
            patch.object(httpx.AsyncClient, "__init__", patched_init),
        ):
            await ssl_provider._ensure_client()

        # Verify ssl.create_default_context was used (loads system CAs)
        # and load_verify_locations was called with the cert path
        mock_ctx.load_verify_locations.assert_called_once()
        assert call_kwargs.get("verify") is mock_ctx
        await ssl_provider.aclose()

    @pytest.mark.asyncio
    async def test_ensure_client_without_ca_cert_uses_bool(
        self, plain_provider: OpenRouterProvider
    ) -> None:
        """_ensure_client() passes bool verify when ssl_ca_cert is not set."""
        call_kwargs: dict[str, object] = {}
        original_init = httpx.AsyncClient.__init__

        def patched_init(self: httpx.AsyncClient, **kwargs: object) -> None:
            call_kwargs.update(kwargs)
            return original_init(self, **kwargs)

        with patch.object(httpx.AsyncClient, "__init__", patched_init):
            await plain_provider._ensure_client()

        assert isinstance(call_kwargs.get("verify"), bool)
        assert call_kwargs["verify"] is True
        await plain_provider.aclose()

    @pytest.mark.asyncio
    async def test_ensure_client_calls_load_verify_locations(
        self, ssl_provider: OpenRouterProvider
    ) -> None:
        """_ensure_client() calls load_verify_locations with the cert path."""
        mock_ctx = MagicMock(spec=ssl.SSLContext)
        original_init = httpx.AsyncClient.__init__

        def patched_init(self: httpx.AsyncClient, **kwargs: object) -> None:
            return original_init(self, **kwargs)

        with (
            patch("nexus3.provider.base.ssl.create_default_context", return_value=mock_ctx),
            patch.object(httpx.AsyncClient, "__init__", patched_init),
        ):
            await ssl_provider._ensure_client()

        # The cert path should be the normalized absolute path
        cert_path = mock_ctx.load_verify_locations.call_args[0][0]
        assert os.path.isabs(cert_path)
        assert cert_path.endswith("ca-cert.pem")
        await ssl_provider.aclose()
