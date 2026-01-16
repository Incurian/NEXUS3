"""Unit tests for HTTP pipeline layer functions.

Sprint 5 D2: Tests for the extracted authentication, routing, and restore layers
in the HTTP pipeline.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock


class TestAuthenticateRequest:
    """Tests for _authenticate_request layer function."""

    def test_no_auth_configured_succeeds(self) -> None:
        """When api_key is None, auth always succeeds."""
        from nexus3.rpc.http import _authenticate_request, HttpRequest

        http_request = HttpRequest(
            method="POST",
            path="/",
            headers={},
            body="{}",
        )

        error, status = _authenticate_request(http_request, api_key=None)

        assert error is None
        assert status == 0

    def test_missing_auth_header_fails(self) -> None:
        """When api_key is set but no auth header, returns 401."""
        from nexus3.rpc.http import _authenticate_request, HttpRequest

        http_request = HttpRequest(
            method="POST",
            path="/",
            headers={},  # No authorization header
            body="{}",
        )

        error, status = _authenticate_request(http_request, api_key="secret-key")

        assert error is not None
        assert status == 401
        assert "Authorization header required" in error.error["message"]

    def test_invalid_api_key_fails(self) -> None:
        """When api_key doesn't match provided token, returns 403."""
        from nexus3.rpc.http import _authenticate_request, HttpRequest

        http_request = HttpRequest(
            method="POST",
            path="/",
            headers={"authorization": "Bearer wrong-key"},
            body="{}",
        )

        error, status = _authenticate_request(http_request, api_key="secret-key")

        assert error is not None
        assert status == 403
        assert "Invalid API key" in error.error["message"]

    def test_valid_api_key_succeeds(self) -> None:
        """When api_key matches provided token, auth succeeds."""
        from nexus3.rpc.http import _authenticate_request, HttpRequest

        http_request = HttpRequest(
            method="POST",
            path="/",
            headers={"authorization": "Bearer correct-key"},
            body="{}",
        )

        error, status = _authenticate_request(http_request, api_key="correct-key")

        assert error is None
        assert status == 0


class TestRouteToDispatcher:
    """Tests for _route_to_dispatcher layer function."""

    def test_root_path_routes_to_global(self) -> None:
        """Request to / routes to global dispatcher."""
        from nexus3.rpc.http import _route_to_dispatcher

        mock_pool = MagicMock()
        mock_global = MagicMock()

        dispatcher, agent_id, error, status = _route_to_dispatcher(
            "/", mock_pool, mock_global
        )

        assert dispatcher is mock_global
        assert agent_id is None
        assert error is None
        assert status == 0

    def test_rpc_path_routes_to_global(self) -> None:
        """Request to /rpc routes to global dispatcher."""
        from nexus3.rpc.http import _route_to_dispatcher

        mock_pool = MagicMock()
        mock_global = MagicMock()

        dispatcher, agent_id, error, status = _route_to_dispatcher(
            "/rpc", mock_pool, mock_global
        )

        assert dispatcher is mock_global
        assert agent_id is None
        assert error is None
        assert status == 0

    def test_invalid_path_returns_404(self) -> None:
        """Request to invalid path returns 404 error."""
        from nexus3.rpc.http import _route_to_dispatcher

        mock_pool = MagicMock()
        mock_global = MagicMock()

        dispatcher, agent_id, error, status = _route_to_dispatcher(
            "/invalid", mock_pool, mock_global
        )

        assert dispatcher is None
        assert agent_id is None
        assert error is not None
        assert status == 404
        assert "Not found" in error.error["message"]

    def test_agent_path_with_active_agent_routes_to_agent(self) -> None:
        """Request to /agent/{id} with active agent routes to agent's dispatcher."""
        from nexus3.rpc.http import _route_to_dispatcher

        mock_agent = MagicMock()
        mock_agent.dispatcher = MagicMock()
        mock_pool = MagicMock()
        mock_pool.get.return_value = mock_agent
        mock_global = MagicMock()

        dispatcher, agent_id, error, status = _route_to_dispatcher(
            "/agent/test-agent", mock_pool, mock_global
        )

        assert dispatcher is mock_agent.dispatcher
        assert agent_id == "test-agent"
        assert error is None
        assert status == 0
        mock_pool.get.assert_called_once_with("test-agent")

    def test_agent_path_with_inactive_agent_returns_agent_id(self) -> None:
        """Request to /agent/{id} with inactive agent returns agent_id for restore."""
        from nexus3.rpc.http import _route_to_dispatcher

        mock_pool = MagicMock()
        mock_pool.get.return_value = None  # Agent not active
        mock_global = MagicMock()

        dispatcher, agent_id, error, status = _route_to_dispatcher(
            "/agent/inactive-agent", mock_pool, mock_global
        )

        # Dispatcher is None, but agent_id is set - caller should try restore
        assert dispatcher is None
        assert agent_id == "inactive-agent"
        assert error is None
        assert status == 0

    def test_agent_path_with_invalid_agent_id_returns_404(self) -> None:
        """Request to /agent/{invalid_id} with invalid ID returns 404."""
        from nexus3.rpc.http import _route_to_dispatcher

        mock_pool = MagicMock()
        mock_global = MagicMock()

        # Invalid agent ID (contains path traversal)
        dispatcher, agent_id, error, status = _route_to_dispatcher(
            "/agent/../etc/passwd", mock_pool, mock_global
        )

        assert dispatcher is None
        assert agent_id is None
        assert error is not None
        assert status == 404


class TestRestoreAgentIfNeeded:
    """Tests for _restore_agent_if_needed layer function."""

    async def test_no_session_manager_returns_404(self) -> None:
        """When session_manager is None, returns 404."""
        from nexus3.rpc.http import _restore_agent_if_needed

        mock_pool = MagicMock()

        dispatcher, error, status = await _restore_agent_if_needed(
            "test-agent", mock_pool, session_manager=None
        )

        assert dispatcher is None
        assert error is not None
        assert status == 404
        assert "Agent not found" in error.error["message"]

    async def test_session_not_exists_returns_404(self) -> None:
        """When session doesn't exist, returns 404."""
        from nexus3.rpc.http import _restore_agent_if_needed

        mock_pool = MagicMock()
        mock_session_manager = MagicMock()
        mock_session_manager.session_exists.return_value = False

        dispatcher, error, status = await _restore_agent_if_needed(
            "nonexistent-agent", mock_pool, mock_session_manager
        )

        assert dispatcher is None
        assert error is not None
        assert status == 404
        mock_session_manager.session_exists.assert_called_once_with("nonexistent-agent")

    async def test_successful_restore_returns_dispatcher(self) -> None:
        """When restore succeeds, returns agent's dispatcher."""
        from nexus3.rpc.http import _restore_agent_if_needed

        mock_saved = MagicMock()
        mock_agent = MagicMock()
        mock_agent.dispatcher = MagicMock()

        mock_pool = MagicMock()
        mock_pool.restore_from_saved = AsyncMock(return_value=mock_agent)

        mock_session_manager = MagicMock()
        mock_session_manager.session_exists.return_value = True
        mock_session_manager.load_session.return_value = mock_saved

        dispatcher, error, status = await _restore_agent_if_needed(
            "saved-agent", mock_pool, mock_session_manager
        )

        assert dispatcher is mock_agent.dispatcher
        assert error is None
        assert status == 0
        mock_session_manager.load_session.assert_called_once_with("saved-agent")
        mock_pool.restore_from_saved.assert_called_once_with(mock_saved)

    async def test_restore_exception_returns_500(self) -> None:
        """When restore fails with exception, returns 500."""
        from nexus3.rpc.http import _restore_agent_if_needed

        mock_pool = MagicMock()
        mock_pool.restore_from_saved = AsyncMock(
            side_effect=Exception("Database error")
        )

        mock_session_manager = MagicMock()
        mock_session_manager.session_exists.return_value = True
        mock_session_manager.load_session.return_value = MagicMock()

        dispatcher, error, status = await _restore_agent_if_needed(
            "broken-agent", mock_pool, mock_session_manager
        )

        assert dispatcher is None
        assert error is not None
        assert status == 500
        assert "Failed to restore session" in error.error["message"]


class TestPipelineLayerIntegration:
    """Integration tests for the pipeline layers working together."""

    def test_auth_error_codes_are_correct(self) -> None:
        """Auth layer uses correct JSON-RPC error codes."""
        from nexus3.rpc.http import _authenticate_request, HttpRequest
        from nexus3.rpc.protocol import INVALID_REQUEST

        # Missing auth header
        http_request = HttpRequest(
            method="POST", path="/", headers={}, body="{}"
        )
        error, _ = _authenticate_request(http_request, api_key="secret")
        assert error.error["code"] == INVALID_REQUEST

        # Invalid key
        http_request = HttpRequest(
            method="POST", path="/", headers={"authorization": "Bearer bad"}, body="{}"
        )
        error, _ = _authenticate_request(http_request, api_key="secret")
        assert error.error["code"] == INVALID_REQUEST

    def test_route_error_codes_are_correct(self) -> None:
        """Routing layer uses correct JSON-RPC error codes."""
        from nexus3.rpc.http import _route_to_dispatcher
        from nexus3.rpc.protocol import INVALID_PARAMS

        mock_pool = MagicMock()
        mock_global = MagicMock()

        _, _, error, _ = _route_to_dispatcher("/invalid/path", mock_pool, mock_global)
        assert error.error["code"] == INVALID_PARAMS

    async def test_restore_error_codes_are_correct(self) -> None:
        """Restore layer uses correct JSON-RPC error codes."""
        from nexus3.rpc.http import _restore_agent_if_needed
        from nexus3.rpc.protocol import INVALID_PARAMS, INTERNAL_ERROR

        mock_pool = MagicMock()

        # No session manager -> INVALID_PARAMS (not found)
        _, error, _ = await _restore_agent_if_needed("test", mock_pool, None)
        assert error.error["code"] == INVALID_PARAMS

        # Session doesn't exist -> INVALID_PARAMS (not found)
        mock_session_manager = MagicMock()
        mock_session_manager.session_exists.return_value = False
        _, error, _ = await _restore_agent_if_needed(
            "test", mock_pool, mock_session_manager
        )
        assert error.error["code"] == INVALID_PARAMS

        # Restore fails -> INTERNAL_ERROR
        mock_session_manager.session_exists.return_value = True
        mock_session_manager.load_session.side_effect = Exception("DB error")
        _, error, _ = await _restore_agent_if_needed(
            "test", mock_pool, mock_session_manager
        )
        assert error.error["code"] == INTERNAL_ERROR
