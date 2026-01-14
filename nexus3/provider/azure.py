"""Azure OpenAI provider for NEXUS3.

This module implements the provider for Azure OpenAI Service.
Azure uses the same message format as OpenAI but with different:
- Endpoint format: /openai/deployments/{deployment}/chat/completions
- Authentication: api-key header instead of Bearer token
- API versioning: ?api-version=YYYY-MM-DD query parameter
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nexus3.provider.openai_compat import OpenAICompatProvider

if TYPE_CHECKING:
    from nexus3.config.schema import ProviderConfig
    from nexus3.core.interfaces import RawLogCallback


class AzureOpenAIProvider(OpenAICompatProvider):
    """Provider for Azure OpenAI Service.

    Extends OpenAICompatProvider with Azure-specific endpoint formatting.
    Uses the same message and tool format as OpenAI.

    Configuration:
        - type: "azure"
        - base_url: https://<resource>.openai.azure.com
        - deployment: Azure deployment name (defaults to model if not set)
        - api_version: API version string (defaults to 2024-02-01)
        - api_key_env: Environment variable for API key
        - auth_method: Should be "api-key" (auto-set by factory)

    Example config.json:
        {
            "provider": {
                "type": "azure",
                "base_url": "https://my-resource.openai.azure.com",
                "api_key_env": "AZURE_OPENAI_KEY",
                "deployment": "gpt-4",
                "api_version": "2024-02-01"
            }
        }

    Example:
        config = ProviderConfig(
            type="azure",
            base_url="https://my-resource.openai.azure.com",
            api_key_env="AZURE_OPENAI_KEY",
            deployment="gpt-4",
            api_version="2024-02-01",
            auth_method=AuthMethod.API_KEY,
        )
        provider = AzureOpenAIProvider(config)
    """

    def __init__(
        self,
        config: ProviderConfig,
        model_id: str,
        raw_log: RawLogCallback | None = None,
        reasoning: bool = False,
    ) -> None:
        """Initialize the Azure OpenAI provider.

        Args:
            config: Provider configuration with Azure-specific fields.
            model_id: The model ID to use for API requests.
            raw_log: Optional callback for raw API logging.
            reasoning: Whether to enable extended thinking/reasoning.
        """
        super().__init__(config, model_id, raw_log, reasoning)

    def _build_endpoint(self, stream: bool = False) -> str:
        """Build Azure-specific endpoint URL.

        Azure endpoint format:
            https://<resource>.openai.azure.com/openai/deployments/<deployment>/chat/completions?api-version=<version>

        Args:
            stream: Whether this is a streaming request (unused, same endpoint).

        Returns:
            Full URL for Azure OpenAI chat completions.
        """
        # Use deployment if set, otherwise fall back to model
        deployment = self._config.deployment or self._model

        # Use configured API version or default
        api_version = self._config.api_version or "2024-02-01"

        return (
            f"{self._base_url}/openai/deployments/{deployment}"
            f"/chat/completions?api-version={api_version}"
        )
