"""Unit tests for nexus3.core.errors module."""

from nexus3.core.errors import ConfigError, NexusError, ProviderError


class TestNexusError:
    """Tests for NexusError base class."""

    def test_nexus_error_accepts_message(self):
        """NexusError can be created with a message."""
        err = NexusError("Something went wrong")
        assert err.message == "Something went wrong"

    def test_nexus_error_is_exception(self):
        """NexusError inherits from Exception."""
        assert issubclass(NexusError, Exception)

    def test_nexus_error_str_representation(self):
        """NexusError string representation is the message."""
        err = NexusError("Test error message")
        assert str(err) == "Test error message"

    def test_nexus_error_can_be_raised(self):
        """NexusError can be raised and caught."""
        try:
            raise NexusError("Raised error")
        except NexusError as e:
            assert e.message == "Raised error"


class TestConfigError:
    """Tests for ConfigError."""

    def test_config_error_inherits_from_nexus_error(self):
        """ConfigError inherits from NexusError."""
        assert issubclass(ConfigError, NexusError)

    def test_config_error_has_message(self):
        """ConfigError stores the message attribute."""
        err = ConfigError("Invalid configuration")
        assert err.message == "Invalid configuration"

    def test_config_error_can_be_caught_as_nexus_error(self):
        """ConfigError can be caught as NexusError."""
        try:
            raise ConfigError("Config problem")
        except NexusError as e:
            assert e.message == "Config problem"


class TestProviderError:
    """Tests for ProviderError."""

    def test_provider_error_inherits_from_nexus_error(self):
        """ProviderError inherits from NexusError."""
        assert issubclass(ProviderError, NexusError)

    def test_provider_error_has_message(self):
        """ProviderError stores the message attribute."""
        err = ProviderError("API request failed")
        assert err.message == "API request failed"

    def test_provider_error_can_be_caught_as_nexus_error(self):
        """ProviderError can be caught as NexusError."""
        try:
            raise ProviderError("Provider issue")
        except NexusError as e:
            assert e.message == "Provider issue"
