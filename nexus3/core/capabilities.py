"""Capability token primitives for delegated agent operations."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

_CAPABILITY_PREFIX = "n3cap"
_CAPABILITY_VERSION = "v1"
_MIN_SECRET_BYTES = 16

# Direct in-process RPC capability scopes (Plan B Phase 2).
DIRECT_RPC_SCOPE_BY_METHOD: dict[str, str] = {
    "send": "rpc:agent:send",
    "cancel": "rpc:agent:cancel",
    "compact": "rpc:agent:compact",
    "shutdown": "rpc:agent:shutdown",
    "get_tokens": "rpc:agent:get_tokens",
    "get_context": "rpc:agent:get_context",
    "get_messages": "rpc:agent:get_messages",
    "create_agent": "rpc:global:create_agent",
    "destroy_agent": "rpc:global:destroy_agent",
    "list_agents": "rpc:global:list_agents",
    "shutdown_server": "rpc:global:shutdown_server",
}
DIRECT_RPC_ALL_SCOPES: tuple[str, ...] = tuple(
    sorted(set(DIRECT_RPC_SCOPE_BY_METHOD.values()))
)


def direct_rpc_scope_for_method(method: str) -> str | None:
    """Return required direct-RPC capability scope for a method."""
    return DIRECT_RPC_SCOPE_BY_METHOD.get(method)


class CapabilityError(ValueError):
    """Base exception for capability token failures."""


class CapabilityFormatError(CapabilityError):
    """Raised when a capability token has invalid wire format."""


class CapabilitySignatureError(CapabilityError):
    """Raised when a capability signature check fails."""


class CapabilityExpiredError(CapabilityError):
    """Raised when a capability is expired (or not yet valid)."""


class CapabilityScopeError(CapabilityError):
    """Raised when required scopes are missing or attenuation fails."""


class CapabilityRevokedError(CapabilityError):
    """Raised when a revoked capability is used."""


class CapabilityReplayError(CapabilityError):
    """Raised when a replayed capability is detected."""


class CapabilityRevocationStore(Protocol):
    """Revocation lookup contract."""

    def is_revoked(self, token_id: str) -> bool:
        """Return True when token_id has been revoked."""


class CapabilityReplayStore(Protocol):
    """Replay tracking contract."""

    def mark_seen(self, token_id: str) -> bool:
        """Mark token_id as used.

        Returns False when token_id was already seen.
        """


@dataclass
class InMemoryCapabilityRevocationStore:
    """In-memory revocation store for local/direct execution flows."""

    _revoked_token_ids: set[str] = field(default_factory=set)

    def revoke(self, token_id: str) -> None:
        """Mark token_id as revoked."""
        self._revoked_token_ids.add(token_id)

    def is_revoked(self, token_id: str) -> bool:
        """Return True when token_id has been revoked."""
        return token_id in self._revoked_token_ids


@dataclass
class InMemoryCapabilityReplayStore:
    """In-memory replay detector keyed by token_id."""

    _seen_token_ids: set[str] = field(default_factory=set)

    def mark_seen(self, token_id: str) -> bool:
        """Track token_id usage.

        Returns:
            True if this is the first use, False on replay.
        """
        if token_id in self._seen_token_ids:
            return False
        self._seen_token_ids.add(token_id)
        return True


def _urlsafe_b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _urlsafe_b64decode(encoded: str) -> bytes:
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(encoded + padding)


def _canonical_json(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _normalize_scopes(scopes: Iterable[str]) -> tuple[str, ...]:
    normalized = sorted({scope for scope in scopes if scope})
    if not normalized:
        raise CapabilityScopeError("Capability must contain at least one scope")
    return tuple(normalized)


def generate_capability_secret(num_bytes: int = 32) -> str:
    """Generate a URL-safe capability signing secret."""
    if num_bytes < _MIN_SECRET_BYTES:
        raise CapabilityError(
            f"Capability secret must be at least {_MIN_SECRET_BYTES} bytes"
        )
    return _urlsafe_b64encode(secrets.token_bytes(num_bytes))


@dataclass(frozen=True)
class CapabilityClaims:
    """Typed capability claim set."""

    token_id: str
    issuer_id: str
    subject_id: str
    scopes: tuple[str, ...]
    issued_at: int
    expires_at: int
    parent_token_id: str | None = None
    nonce: str = ""

    def to_payload(self) -> dict[str, object]:
        """Convert claims to canonical payload dict."""
        payload: dict[str, object] = {
            "ver": _CAPABILITY_VERSION,
            "tid": self.token_id,
            "iss": self.issuer_id,
            "sub": self.subject_id,
            "scp": list(self.scopes),
            "iat": self.issued_at,
            "exp": self.expires_at,
            "non": self.nonce,
        }
        if self.parent_token_id is not None:
            payload["pid"] = self.parent_token_id
        return payload

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> CapabilityClaims:
        """Parse and validate claims from payload."""
        version = payload.get("ver")
        if version != _CAPABILITY_VERSION:
            raise CapabilityFormatError(
                f"Unsupported capability payload version: {version!r}"
            )

        token_id = payload.get("tid")
        issuer_id = payload.get("iss")
        subject_id = payload.get("sub")
        scopes_raw = payload.get("scp")
        issued_at = payload.get("iat")
        expires_at = payload.get("exp")
        parent_token_id = payload.get("pid")
        nonce = payload.get("non", "")

        if not isinstance(token_id, str) or not token_id:
            raise CapabilityFormatError("Capability payload must include string tid")
        if not isinstance(issuer_id, str) or not issuer_id:
            raise CapabilityFormatError("Capability payload must include string iss")
        if not isinstance(subject_id, str) or not subject_id:
            raise CapabilityFormatError("Capability payload must include string sub")
        if not isinstance(scopes_raw, list) or not all(
            isinstance(scope, str) for scope in scopes_raw
        ):
            raise CapabilityFormatError("Capability payload must include string-list scp")
        if not isinstance(issued_at, int):
            raise CapabilityFormatError("Capability payload must include integer iat")
        if not isinstance(expires_at, int):
            raise CapabilityFormatError("Capability payload must include integer exp")
        if parent_token_id is not None and not isinstance(parent_token_id, str):
            raise CapabilityFormatError("Capability payload pid must be string when set")
        if not isinstance(nonce, str):
            raise CapabilityFormatError("Capability payload non must be string")

        scopes = _normalize_scopes(scopes_raw)
        if expires_at <= issued_at:
            raise CapabilityFormatError("Capability exp must be greater than iat")

        return cls(
            token_id=token_id,
            issuer_id=issuer_id,
            subject_id=subject_id,
            scopes=scopes,
            issued_at=issued_at,
            expires_at=expires_at,
            parent_token_id=parent_token_id,
            nonce=nonce,
        )


class CapabilitySigner:
    """Issue and verify signed capability tokens."""

    def __init__(
        self,
        secret: bytes | str,
        *,
        max_clock_skew_seconds: int = 30,
    ) -> None:
        if isinstance(secret, str):
            secret_bytes = secret.encode("utf-8")
        else:
            secret_bytes = secret

        if len(secret_bytes) < _MIN_SECRET_BYTES:
            raise CapabilityError(
                f"Capability secret must be at least {_MIN_SECRET_BYTES} bytes"
            )

        if max_clock_skew_seconds < 0:
            raise CapabilityError("max_clock_skew_seconds must be non-negative")

        self._secret = secret_bytes
        self._max_clock_skew_seconds = max_clock_skew_seconds

    def issue(
        self,
        *,
        issuer_id: str,
        subject_id: str,
        scopes: Iterable[str],
        ttl_seconds: int,
        parent_claims: CapabilityClaims | None = None,
        now: int | None = None,
    ) -> str:
        """Issue a signed capability token."""
        if not issuer_id:
            raise CapabilityError("issuer_id must be non-empty")
        if not subject_id:
            raise CapabilityError("subject_id must be non-empty")
        if ttl_seconds <= 0:
            raise CapabilityError("ttl_seconds must be > 0")

        issued_at = int(time.time() if now is None else now)
        normalized_scopes = _normalize_scopes(scopes)
        expires_at = issued_at + ttl_seconds
        parent_token_id: str | None = None

        if parent_claims is not None:
            parent_scopes = set(parent_claims.scopes)
            child_scopes = set(normalized_scopes)
            missing = sorted(child_scopes - parent_scopes)
            if missing:
                raise CapabilityScopeError(
                    f"Child scopes exceed parent grant: {missing}"
                )
            expires_at = min(expires_at, parent_claims.expires_at)
            parent_token_id = parent_claims.token_id

        claims = CapabilityClaims(
            token_id=secrets.token_hex(16),
            issuer_id=issuer_id,
            subject_id=subject_id,
            scopes=normalized_scopes,
            issued_at=issued_at,
            expires_at=expires_at,
            parent_token_id=parent_token_id,
            nonce=secrets.token_hex(8),
        )
        return self.serialize(claims)

    def serialize(self, claims: CapabilityClaims) -> str:
        """Serialize claims into signed token wire format."""
        payload_bytes = _canonical_json(claims.to_payload())
        signature = hmac.new(self._secret, payload_bytes, hashlib.sha256).digest()
        return ".".join(
            (
                _CAPABILITY_PREFIX,
                _CAPABILITY_VERSION,
                _urlsafe_b64encode(payload_bytes),
                _urlsafe_b64encode(signature),
            )
        )

    def verify(
        self,
        token: str,
        *,
        required_scopes: Iterable[str] | None = None,
        revocation_store: CapabilityRevocationStore | None = None,
        replay_store: CapabilityReplayStore | None = None,
        now: int | None = None,
    ) -> CapabilityClaims:
        """Verify token format, signature, expiry, and optional scope/store checks."""
        parts = token.split(".")
        if len(parts) != 4:
            raise CapabilityFormatError("Capability token must have 4 dot-separated parts")
        if parts[0] != _CAPABILITY_PREFIX or parts[1] != _CAPABILITY_VERSION:
            raise CapabilityFormatError("Capability token prefix/version mismatch")

        try:
            payload_bytes = _urlsafe_b64decode(parts[2])
            signature = _urlsafe_b64decode(parts[3])
        except Exception as exc:  # pragma: no cover - defensive decode guard
            raise CapabilityFormatError("Capability token contains invalid base64 data") from exc

        expected_signature = hmac.new(
            self._secret, payload_bytes, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(signature, expected_signature):
            raise CapabilitySignatureError("Capability token signature mismatch")

        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CapabilityFormatError("Capability payload is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise CapabilityFormatError("Capability payload root must be an object")

        claims = CapabilityClaims.from_payload(payload)
        now_epoch = int(time.time() if now is None else now)

        if now_epoch + self._max_clock_skew_seconds < claims.issued_at:
            raise CapabilityExpiredError("Capability token not yet valid")
        if now_epoch >= claims.expires_at:
            raise CapabilityExpiredError("Capability token expired")

        if required_scopes is not None:
            missing_scopes = sorted(set(required_scopes) - set(claims.scopes))
            if missing_scopes:
                raise CapabilityScopeError(
                    f"Capability missing required scopes: {missing_scopes}"
                )

        if revocation_store is not None and revocation_store.is_revoked(claims.token_id):
            raise CapabilityRevokedError("Capability token has been revoked")

        if replay_store is not None and not replay_store.mark_seen(claims.token_id):
            raise CapabilityReplayError("Capability token replay detected")

        return claims


__all__ = [
    "CapabilityError",
    "CapabilityFormatError",
    "CapabilitySignatureError",
    "CapabilityExpiredError",
    "CapabilityScopeError",
    "CapabilityRevokedError",
    "CapabilityReplayError",
    "CapabilityClaims",
    "CapabilitySigner",
    "CapabilityRevocationStore",
    "CapabilityReplayStore",
    "InMemoryCapabilityRevocationStore",
    "InMemoryCapabilityReplayStore",
    "DIRECT_RPC_SCOPE_BY_METHOD",
    "DIRECT_RPC_ALL_SCOPES",
    "direct_rpc_scope_for_method",
    "generate_capability_secret",
]
