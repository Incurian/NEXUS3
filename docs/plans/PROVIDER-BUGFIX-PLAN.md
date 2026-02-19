# Plan: Provider Bugfixes — SSL, Path Normalization, Reasoning Content

## Context

During diagnostic testing of NEXUS on a corporate OpenAI-compatible endpoint (Azure AI Factory), we discovered three bugs in the NEXUS provider code and one deferred investigation item. These were found via the `scripts/diagnose-empty-stream.sh` diagnostic script run on Git Bash/Windows against a thinking model (`gpt-oss-120b`).

**Bugs to fix:**
1. Custom CA cert replaces system CAs instead of adding to them → TLS failures on corporate proxies
2. `ssl_ca_cert` config path not normalized → MSYS2/Git Bash paths fail in Python
3. Non-streaming `_parse_response()` silently discards `reasoning_content` → no logging, could confuse debugging

**Deferred:**
- Keep-alive connection failures (test 10: "fresh works but keep-alive fails") — the empty stream guard already protects against the worst outcome. Investigation deferred.

## Bug Details

### Bug 1: Custom cert replaces system CAs (HIGH)

**File:** `nexus3/provider/base.py:188-189`
```python
if self._ssl_ca_cert:
    verify: bool | str | ssl.SSLContext = self._ssl_ca_cert  # BUG: replaces ALL system CAs
```

When `ssl_ca_cert` is set, httpx uses ONLY that file as its CA bundle. Corporate proxies need both the custom CA AND standard root CAs (e.g., for intermediate cert chains). This causes HTTP 502 errors.

**Fix:** Use `ssl.create_default_context()` + `load_verify_locations()` to ADD the custom cert on top of system CAs, matching the pattern already used in the Windows fallback (line 203).

### Bug 2: `ssl_ca_cert` path not normalized (MEDIUM)

**File:** `nexus3/config/schema.py:152-154`
```python
ssl_ca_cert: str | None = None
```

On Git Bash, users enter paths like `/c/Users/me/cert.pem`. Python doesn't understand MSYS2 paths. The config already normalizes `allowed_paths` and `blocked_paths` via `_normalize_paths()` (lines 11-49) using `os.path.expanduser()` + `os.path.abspath()` — but `ssl_ca_cert` is not normalized.

**Fix:** Add a Pydantic field validator for `ssl_ca_cert` that normalizes the path using `os.path.expanduser()` + `os.path.abspath()`, following the existing pattern.

### Bug 3: Non-streaming ignores reasoning_content (LOW)

**File:** `nexus3/provider/openai_compat.py:221-259`
```python
content = msg.get("content") or ""
# ... no check for reasoning_content or reasoning
```

The streaming path (`_process_stream_event`) now checks both `reasoning_content` and `reasoning`. But the non-streaming `_parse_response()` completely ignores these fields. The `Message` dataclass has no `reasoning` field, so we can't store it — but we should log it for debugging.

**Fix:** Add a debug log when reasoning content is present in the non-streaming response. This doesn't change behavior but makes debugging much easier.

## Files to Modify

| File | Change | Bug |
|------|--------|-----|
| `nexus3/provider/base.py` | SSL context with `load_verify_locations()` | #1 |
| `nexus3/config/schema.py` | Field validator for `ssl_ca_cert` | #2 |
| `nexus3/provider/openai_compat.py` | Log reasoning in `_parse_response()` | #3 |
| `tests/unit/provider/test_empty_stream.py` | Test reasoning in non-streaming | #3 |
| `tests/unit/provider/test_ssl_config.py` | New: test SSL context building | #1, #2 |

## Implementation Details

### Phase 1: SSL cert fix (`base.py`)

**Current code (line 188-189):**
```python
if self._ssl_ca_cert:
    verify: bool | str | ssl.SSLContext = self._ssl_ca_cert
```

**Fixed code:**
```python
if self._ssl_ca_cert:
    # Add custom CA on top of system CAs (not replacing them)
    # Corporate proxies need both the custom CA and standard root CAs
    ssl_context = ssl.create_default_context()
    ssl_context.load_verify_locations(self._ssl_ca_cert)
    verify: bool | str | ssl.SSLContext = ssl_context
```

This matches the diagnostic script fix (commit `423a52c`).

### Phase 2: Path normalization (`schema.py`)

Add a field validator following the existing `normalize_allowed_paths` pattern (line 181-185):

```python
@field_validator("ssl_ca_cert", mode="before")
@classmethod
def normalize_ssl_ca_cert(cls, v: str | None) -> str | None:
    """Normalize ssl_ca_cert to absolute path."""
    if v is None:
        return None
    expanded = os.path.expanduser(v)
    absolute = os.path.abspath(expanded)
    if not os.path.isfile(absolute):
        warnings.warn(
            f"SSL CA cert file does not exist: {v!r} -> {absolute}",
            UserWarning,
            stacklevel=4,
        )
    return absolute
```

`os.path.abspath()` on Windows/Git Bash converts `/c/Users/...` to `C:\Users\...` automatically.

### Phase 3: Reasoning logging (`openai_compat.py`)

In `_parse_response()`, after extracting content (line 238):

```python
content = msg.get("content") or ""

# Log reasoning content if present (not stored in Message, but useful for debugging)
reasoning = msg.get("reasoning_content") or msg.get("reasoning")
if reasoning:
    logger.debug(
        "Non-streaming response includes reasoning (%d chars, content=%d chars)",
        len(reasoning), len(content),
    )
```

### Phase 4: Tests

**`tests/unit/provider/test_ssl_config.py`** (new):
- Test that `ssl_ca_cert` path is normalized via field validator
- Test that `_ensure_client()` builds an `ssl.SSLContext` when `ssl_ca_cert` is set (not a raw string)
- Test Windows fallback still works

**`tests/unit/provider/test_empty_stream.py`** (existing):
- Add test for non-streaming response with `reasoning_content` field → verify debug log emitted, content still extracted correctly

### Phase 5: Verification

1. `.venv/bin/pytest tests/ -v` — all tests pass
2. `.venv/bin/ruff check nexus3/` — clean
3. Verify no regressions in existing SSL/provider tests

## Implementation Checklist

### Phase 1: SSL cert fix
- [x] **P1.1** Update `base.py:_ensure_client()` to use `ssl.create_default_context()` + `load_verify_locations()` when `ssl_ca_cert` is set

### Phase 2: Path normalization
- [x] **P2.1** Add `normalize_ssl_ca_cert` field validator to `ProviderConfig` in `schema.py`

### Phase 3: Reasoning logging
- [x] **P3.1** Add reasoning debug log to `openai_compat.py:_parse_response()`

### Phase 4: Tests (after P1-P3)
- [x] **P4.1** New `tests/unit/provider/test_ssl_config.py` — SSL context building, path normalization (8 tests)
- [x] **P4.2** Add non-streaming reasoning test to `tests/unit/provider/test_empty_stream.py` (3 tests)
- [x] **P4.3** Full test suite + lints pass (3726 passed, 3 skipped, ruff clean)

### Phase 5: Documentation
- [x] **P5.1** Update memory notes with completed fixes

## Deferred

- **Keep-alive failures**: Test 10 showed "fresh connection works but keep-alive fails". This is likely the corporate proxy routing reused connections to a bad backend (matching earlier `gcell`/`pcell` observations). The empty stream guard (c735329) already prevents cascading failures from this. httpx's connection pool should handle stale connections gracefully in most cases. Defer investigation unless users report intermittent failures that the guard doesn't catch.
