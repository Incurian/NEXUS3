"""Unit tests for capability token primitives."""

import pytest

from nexus3.core.capabilities import (
    CapabilityClaims,
    CapabilityExpiredError,
    CapabilityFormatError,
    CapabilityReplayError,
    CapabilityRevokedError,
    CapabilityScopeError,
    CapabilitySignatureError,
    CapabilitySigner,
    InMemoryCapabilityReplayStore,
    InMemoryCapabilityRevocationStore,
    generate_capability_secret,
)


def test_issue_and_verify_round_trip() -> None:
    signer = CapabilitySigner("super-secret-signing-key")
    token = signer.issue(
        issuer_id="parent-agent",
        subject_id="child-agent",
        scopes={"rpc.send", "rpc.destroy"},
        ttl_seconds=60,
        now=1_700_000_000,
    )

    claims = signer.verify(token, now=1_700_000_010)
    assert claims.issuer_id == "parent-agent"
    assert claims.subject_id == "child-agent"
    assert set(claims.scopes) == {"rpc.send", "rpc.destroy"}


def test_verify_rejects_tampered_signature() -> None:
    signer = CapabilitySigner("super-secret-signing-key")
    token = signer.issue(
        issuer_id="parent-agent",
        subject_id="child-agent",
        scopes={"rpc.send"},
        ttl_seconds=60,
        now=1_700_000_000,
    )

    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(CapabilitySignatureError):
        signer.verify(tampered, now=1_700_000_001)


def test_verify_rejects_expired_capability() -> None:
    signer = CapabilitySigner("super-secret-signing-key")
    token = signer.issue(
        issuer_id="agent-a",
        subject_id="agent-b",
        scopes={"rpc.send"},
        ttl_seconds=10,
        now=1_700_000_000,
    )

    with pytest.raises(CapabilityExpiredError):
        signer.verify(token, now=1_700_000_010)


def test_required_scopes_enforced() -> None:
    signer = CapabilitySigner("super-secret-signing-key")
    token = signer.issue(
        issuer_id="agent-a",
        subject_id="agent-b",
        scopes={"rpc.send"},
        ttl_seconds=60,
        now=1_700_000_000,
    )

    with pytest.raises(CapabilityScopeError):
        signer.verify(token, required_scopes={"rpc.destroy"}, now=1_700_000_001)


def test_child_capability_scope_attenuation_is_enforced() -> None:
    signer = CapabilitySigner("super-secret-signing-key")
    parent_token = signer.issue(
        issuer_id="root",
        subject_id="parent",
        scopes={"rpc.send"},
        ttl_seconds=300,
        now=1_700_000_000,
    )
    parent_claims = signer.verify(parent_token, now=1_700_000_001)

    with pytest.raises(CapabilityScopeError):
        signer.issue(
            issuer_id="parent",
            subject_id="child",
            scopes={"rpc.send", "rpc.destroy"},
            ttl_seconds=60,
            parent_claims=parent_claims,
            now=1_700_000_002,
        )


def test_child_capability_expiry_capped_by_parent() -> None:
    signer = CapabilitySigner("super-secret-signing-key")
    parent_token = signer.issue(
        issuer_id="root",
        subject_id="parent",
        scopes={"rpc.send"},
        ttl_seconds=10,
        now=1_700_000_000,
    )
    parent_claims = signer.verify(parent_token, now=1_700_000_001)

    child_token = signer.issue(
        issuer_id="parent",
        subject_id="child",
        scopes={"rpc.send"},
        ttl_seconds=120,
        parent_claims=parent_claims,
        now=1_700_000_002,
    )
    child_claims = signer.verify(child_token, now=1_700_000_003)

    assert child_claims.expires_at == parent_claims.expires_at
    assert child_claims.parent_token_id == parent_claims.token_id


def test_revocation_store_blocks_token() -> None:
    signer = CapabilitySigner("super-secret-signing-key")
    token = signer.issue(
        issuer_id="agent-a",
        subject_id="agent-b",
        scopes={"rpc.send"},
        ttl_seconds=60,
        now=1_700_000_000,
    )
    claims = signer.verify(token, now=1_700_000_001)

    revocation_store = InMemoryCapabilityRevocationStore()
    revocation_store.revoke(claims.token_id)

    with pytest.raises(CapabilityRevokedError):
        signer.verify(token, now=1_700_000_002, revocation_store=revocation_store)


def test_replay_store_rejects_second_use() -> None:
    signer = CapabilitySigner("super-secret-signing-key")
    token = signer.issue(
        issuer_id="agent-a",
        subject_id="agent-b",
        scopes={"rpc.send"},
        ttl_seconds=60,
        now=1_700_000_000,
    )
    replay_store = InMemoryCapabilityReplayStore()

    signer.verify(token, now=1_700_000_001, replay_store=replay_store)
    with pytest.raises(CapabilityReplayError):
        signer.verify(token, now=1_700_000_002, replay_store=replay_store)


def test_malformed_tokens_rejected() -> None:
    signer = CapabilitySigner("super-secret-signing-key")

    with pytest.raises(CapabilityFormatError):
        signer.verify("not-a-capability-token", now=1_700_000_000)


def test_generate_secret_minimum_length_enforced() -> None:
    with pytest.raises(ValueError):
        generate_capability_secret(num_bytes=8)

    assert generate_capability_secret(num_bytes=16)


def test_claims_payload_round_trip() -> None:
    claims = CapabilityClaims(
        token_id="token-1",
        issuer_id="issuer",
        subject_id="subject",
        scopes=("rpc.send",),
        issued_at=1,
        expires_at=2,
        parent_token_id="parent-1",
        nonce="nonce-1",
    )

    loaded = CapabilityClaims.from_payload(claims.to_payload())
    assert loaded == claims
