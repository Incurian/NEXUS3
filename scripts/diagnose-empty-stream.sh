#!/usr/bin/env bash
# =============================================================================
# NEXUS3 Empty Stream Diagnostic Script (v2)
#
# Run this IMMEDIATELY when a blank response occurs to capture evidence
# before the intermittent issue clears. Runs 10 tests against your LLM
# endpoint and saves verbose logs for analysis.
#
# Compatible with: WSL, Git Bash (MSYS2), Linux, macOS
#
# Usage:
#   ./scripts/diagnose-empty-stream.sh
#   ./scripts/diagnose-empty-stream.sh --quick    # Steps 1-3 only (no rapid-fire/parallel)
#
# Output:
#   Creates a timestamped directory under ./err/diagnose-YYYYMMDD-HHMMSS/
#   with individual log files per test and a combined summary.
# =============================================================================

set -euo pipefail

# =============================================================================
# CONFIGURATION -- Edit these to match your environment
# =============================================================================

# LLM endpoint (OpenAI-compatible /v1/chat/completions)
ENDPOINT="https://your-llm-endpoint.example.com/v1/chat/completions"

# Model identifier
MODEL="your-model-id"

# Optional: alternate model to test (leave empty to skip Step 9)
ALT_MODEL=""

# Environment variable name that holds your API key
API_KEY_ENV="LM_API_KEY"

# Test message (keep it short -- we want fast responses)
TEST_MESSAGE="Respond with exactly: Hello, diagnostic test passed."

# Request timeout in seconds
TIMEOUT=30

# Number of rapid-fire requests in Step 4
RAPID_COUNT=5

# Number of parallel streaming requests in Step 8
PARALLEL_COUNT=3

# Backend identity header name (for load balancer detection in Step 4)
# Set to the response header your infra uses to identify which backend served the request.
# Common: x-backend-server, x-served-by, x-aifactory-server
SERVER_HEADER="x-aifactory-server"

# Optional: path to corporate CA bundle for TLS comparison tests (Step 6)
# e.g., /etc/ssl/certs/corporate-ca.pem or /usr/local/share/ca-certificates/corporate.crt
CERT_PATH=""

# =============================================================================
# END CONFIGURATION -- No need to edit below this line
# =============================================================================

# --- Sanity check: was config edited? ---
if [[ "$ENDPOINT" == "https://your-llm-endpoint.example.com/v1/chat/completions" ]]; then
    echo "ERROR: You must edit the CONFIGURATION section at the top of this script."
    echo "At minimum, set ENDPOINT and MODEL to match your LLM deployment."
    exit 1
fi

QUICK_MODE=false
if [[ "${1:-}" == "--quick" ]]; then
    QUICK_MODE=true
fi

# --- Platform detection ---
PYTHON=""
if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
fi

if [[ -n "${MSYSTEM:-}" ]]; then
    PLATFORM="Git Bash (MSYS2: ${MSYSTEM})"
elif [[ -f /proc/version ]] && grep -qi microsoft /proc/version 2>/dev/null; then
    PLATFORM="WSL"
elif [[ "$(uname -s)" == "Darwin" ]]; then
    PLATFORM="macOS"
else
    PLATFORM="Linux"
fi

# --- Colors (disabled if not a terminal) ---
if [[ -t 1 ]]; then
    BOLD='\033[1m'
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[0;33m'
    CYAN='\033[0;36m'
    DIM='\033[2m'
    RESET='\033[0m'
else
    BOLD='' RED='' GREEN='' YELLOW='' CYAN='' DIM='' RESET=''
fi

# --- Setup ---
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
OUTDIR="./err/diagnose-${TIMESTAMP}"
mkdir -p "$OUTDIR"

API_KEY="${!API_KEY_ENV:-}"
if [[ -z "$API_KEY" ]]; then
    echo -e "${RED}ERROR: Environment variable ${API_KEY_ENV} is not set.${RESET}"
    echo "Set it with: export ${API_KEY_ENV}=your-api-key"
    exit 1
fi

KEY_PREVIEW="${API_KEY:0:8}..."

# JSON payload templates
PAYLOAD_SYNC=$(cat <<ENDJSON
{
  "model": "${MODEL}",
  "messages": [{"role": "user", "content": "${TEST_MESSAGE}"}],
  "stream": false,
  "max_tokens": 100
}
ENDJSON
)

PAYLOAD_STREAM=$(cat <<ENDJSON
{
  "model": "${MODEL}",
  "messages": [{"role": "user", "content": "${TEST_MESSAGE}"}],
  "stream": true,
  "max_tokens": 100
}
ENDJSON
)

# Extract base URL (everything before /v1/...)
BASE_URL=$(echo "$ENDPOINT" | sed 's|\(/v1\)/.*|\1|')
ENDPOINT_HOST=$(echo "$ENDPOINT" | sed 's|https\?://||' | cut -d/ -f1)

# --- Helper functions ---

header() {
    echo ""
    echo -e "${BOLD}${CYAN}======================================================================${RESET}"
    echo -e "${BOLD}${CYAN}  $1${RESET}"
    echo -e "${BOLD}${CYAN}======================================================================${RESET}"
}

info() {
    echo -e "${DIM}  $1${RESET}"
}

result_pass() {
    echo -e "  ${GREEN}PASS${RESET}: $1"
}

result_fail() {
    echo -e "  ${RED}FAIL${RESET}: $1"
}

result_warn() {
    echo -e "  ${YELLOW}WARN${RESET}: $1"
}

advice() {
    echo -e "  ${DIM}=> $1${RESET}"
}

# Check if response body has content (uses Python if available, grep fallback)
# Usage: has_content "$body"  -> prints char count (0 if empty)
check_content() {
    local body="$1"
    if [[ -n "$PYTHON" ]]; then
        echo "$body" | $PYTHON -c "
import sys, json
try:
    d = json.load(sys.stdin)
    c = d.get('choices', [{}])[0].get('message', {}).get('content', '')
    print(len(c))
except: print('0')
" 2>/dev/null || echo "0"
    else
        if echo "$body" | grep -q '"content"[[:space:]]*:[[:space:]]*"[^"]'; then
            echo "1"
        else
            echo "0"
        fi
    fi
}

# Build curl cert args based on mode: "default", "custom", "insecure"
# Usage: cert_args=($(curl_cert_args "custom"))
curl_cert_args() {
    local mode="$1"
    case "$mode" in
        custom)
            if [[ -n "$CERT_PATH" && -f "$CERT_PATH" ]]; then
                echo "--cacert" "$CERT_PATH"
            fi
            ;;
        insecure)
            echo "--insecure"
            ;;
        *)  # default: no extra args
            ;;
    esac
}

# Label for cert mode
cert_label() {
    local mode="$1"
    case "$mode" in
        custom)  echo "custom CA (${CERT_PATH})" ;;
        insecure) echo "--insecure (skip verify)" ;;
        *)       echo "system default" ;;
    esac
}

write_config() {
    local f="$OUTDIR/00-config.txt"
    cat > "$f" <<EOF
Diagnostic run: ${TIMESTAMP}
Endpoint:       ${ENDPOINT}
Base URL:       ${BASE_URL}
Model:          ${MODEL}
Alt model:      ${ALT_MODEL:-NONE}
API key env:    ${API_KEY_ENV}
API key:        ${KEY_PREVIEW}
Test message:   ${TEST_MESSAGE}
Timeout:        ${TIMEOUT}s
Quick mode:     ${QUICK_MODE}
Rapid count:    ${RAPID_COUNT}
Parallel count: ${PARALLEL_COUNT}
Server header:  ${SERVER_HEADER}
Cert path:      ${CERT_PATH:-NONE}
Hostname:       $(hostname)
Date:           $(date '+%Y-%m-%dT%H:%M:%S%z')
Platform:       ${PLATFORM}
Python:         ${PYTHON:-NONE}
curl version:   $(curl --version | head -1)
EOF
    echo "$f"
}

# =============================================================================
# STEP 0: Configuration echo
# =============================================================================

header "STEP 0: Diagnostic Configuration"
echo ""
echo -e "  Endpoint:     ${BOLD}${ENDPOINT}${RESET}"
echo -e "  Base URL:     ${BASE_URL}"
echo -e "  Model:        ${BOLD}${MODEL}${RESET}"
echo -e "  Alt model:    ${ALT_MODEL:-NONE}"
echo -e "  API key:      ${KEY_PREVIEW}"
echo -e "  Timeout:      ${TIMEOUT}s"
echo -e "  Server hdr:   ${SERVER_HEADER}"
echo -e "  Cert path:    ${CERT_PATH:-NONE}"
echo -e "  Output dir:   ${BOLD}${OUTDIR}/${RESET}"
echo -e "  Platform:     ${PLATFORM}"
echo -e "  Python:       ${PYTHON:-NOT FOUND}"
echo -e "  Timestamp:    ${TIMESTAMP}"
echo ""
write_config > /dev/null

# =============================================================================
# STEP 1: Non-streaming request (curl)
# =============================================================================

header "STEP 1: Non-streaming request (curl, stream=false)"
info "Tests whether the server returns content for a basic synchronous request."
info "This is the simplest possible test -- if this fails, the server is down."
echo ""

STEP1_LOG="$OUTDIR/01-sync-request.txt"
STEP1_HTTP=0
STEP1_BODY=""

{
    echo "=== REQUEST ==="
    echo "POST ${ENDPOINT}"
    echo "Authorization: Bearer ${KEY_PREVIEW}"
    echo "Content-Type: application/json"
    echo ""
    echo "${PAYLOAD_SYNC}"
    echo ""
    echo "=== CURL VERBOSE OUTPUT ==="
} > "$STEP1_LOG"

STEP1_BODY=$(curl -sS -v -w '\n__HTTP_CODE__:%{http_code}\n__TIME_TOTAL__:%{time_total}\n__TIME_CONNECT__:%{time_connect}\n__TIME_STARTTRANSFER__:%{time_starttransfer}\n__SIZE_DOWNLOAD__:%{size_download}\n' \
    --max-time "$TIMEOUT" \
    -H "Authorization: Bearer ${API_KEY}" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD_SYNC" \
    "$ENDPOINT" 2>>"$STEP1_LOG" || true)

echo "$STEP1_BODY" >> "$STEP1_LOG"

STEP1_HTTP=$(echo "$STEP1_BODY" | grep '__HTTP_CODE__' | cut -d: -f2 || echo "0")
STEP1_TIME=$(echo "$STEP1_BODY" | grep '__TIME_TOTAL__' | cut -d: -f2 || echo "?")
STEP1_TTFB=$(echo "$STEP1_BODY" | grep '__TIME_STARTTRANSFER__' | cut -d: -f2 || echo "?")
STEP1_SIZE=$(echo "$STEP1_BODY" | grep '__SIZE_DOWNLOAD__' | cut -d: -f2 || echo "0")
STEP1_CONTENT=$(echo "$STEP1_BODY" | grep -v '^__' || true)

echo -e "  HTTP status:       ${BOLD}${STEP1_HTTP}${RESET}"
echo -e "  Response size:     ${STEP1_SIZE} bytes"
echo -e "  Time to first byte: ${STEP1_TTFB}s"
echo -e "  Total time:        ${STEP1_TIME}s"
echo ""

if [[ "$STEP1_HTTP" == "200" && "${STEP1_SIZE:-0}" -gt 10 ]]; then
    HAS_CONTENT=$(check_content "$STEP1_CONTENT")
    if [[ "$HAS_CONTENT" -gt 0 ]]; then
        result_pass "Server returned content (${HAS_CONTENT} chars)"
        advice "Non-streaming endpoint is healthy."
    else
        result_fail "HTTP 200 but response has no content in choices[0].message.content"
        advice "Server returned 200 OK but the response body has empty content."
        advice "This suggests the model is generating empty responses -- server-side issue."
    fi
elif [[ "$STEP1_HTTP" == "200" ]]; then
    result_warn "HTTP 200 but tiny response (${STEP1_SIZE} bytes)"
    advice "Response was suspiciously small. Check ${STEP1_LOG} for full body."
else
    result_fail "HTTP ${STEP1_HTTP} (expected 200)"
    advice "Server returned an error. Check ${STEP1_LOG} for response body."
    if [[ "$STEP1_HTTP" == "0" ]]; then
        advice "HTTP 0 = connection failed. Server may be unreachable (DNS, firewall, TLS)."
    elif [[ "$STEP1_HTTP" == "429" ]]; then
        advice "HTTP 429 = rate limited. Wait and retry."
    elif [[ "$STEP1_HTTP" == "502" || "$STEP1_HTTP" == "503" ]]; then
        advice "HTTP ${STEP1_HTTP} = server/gateway error. Likely infrastructure issue."
    fi
fi
echo -e "  ${DIM}Full log: ${STEP1_LOG}${RESET}"

# =============================================================================
# STEP 2: Streaming request (curl) + TTFB analysis
# =============================================================================

header "STEP 2: Streaming request (curl, stream=true)"
info "Tests whether SSE streaming returns content events."
info "This is the path NEXUS uses -- if this is empty but Step 1 works,"
info "the issue is specific to the streaming endpoint."
echo ""

STEP2_LOG="$OUTDIR/02-stream-request.txt"
STEP2_VERBOSE="$OUTDIR/02-stream-verbose.txt"

{
    echo "=== REQUEST ==="
    echo "POST ${ENDPOINT}"
    echo "stream: true"
    echo ""
} > "$STEP2_LOG"

STEP2_BODY=$(curl -sS -v -N -w '\n__HTTP_CODE__:%{http_code}\n__TIME_TOTAL__:%{time_total}\n__TIME_STARTTRANSFER__:%{time_starttransfer}\n__SIZE_DOWNLOAD__:%{size_download}\n' \
    --max-time "$TIMEOUT" \
    -H "Authorization: Bearer ${API_KEY}" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD_STREAM" \
    "$ENDPOINT" 2>"$STEP2_VERBOSE" || true)

echo "$STEP2_BODY" >> "$STEP2_LOG"
cat "$STEP2_VERBOSE" >> "$STEP2_LOG"

STEP2_HTTP=$(echo "$STEP2_BODY" | grep '__HTTP_CODE__' | cut -d: -f2 || echo "0")
STEP2_TIME=$(echo "$STEP2_BODY" | grep '__TIME_TOTAL__' | cut -d: -f2 || echo "?")
STEP2_TTFB=$(echo "$STEP2_BODY" | grep '__TIME_STARTTRANSFER__' | cut -d: -f2 || echo "?")
STEP2_SIZE=$(echo "$STEP2_BODY" | grep '__SIZE_DOWNLOAD__' | cut -d: -f2 || echo "0")
STEP2_SSE=$(echo "$STEP2_BODY" | grep -v '^__' || true)

DATA_LINES=$(echo "$STEP2_SSE" | grep -c '^data: ' || true)
HAS_DONE=$(echo "$STEP2_SSE" | grep -c '^[[:space:]]*data: \[DONE\]' || true)

CONTENT_EVENTS=$(echo "$STEP2_SSE" | grep '^data: ' | grep -v '\[DONE\]' | head -20 || true)
HAS_CONTENT_DELTA=0
if echo "$CONTENT_EVENTS" | grep -q '"content"'; then
    HAS_CONTENT_DELTA=1
elif echo "$CONTENT_EVENTS" | grep -q '"text_delta"'; then
    HAS_CONTENT_DELTA=1
fi

echo -e "  HTTP status:       ${BOLD}${STEP2_HTTP}${RESET}"
echo -e "  Response size:     ${STEP2_SIZE} bytes"
echo -e "  Time to first byte: ${STEP2_TTFB}s"
echo -e "  Total time:        ${STEP2_TIME}s"
echo -e "  SSE data lines:    ${DATA_LINES}"
echo -e "  [DONE] marker:     $([ "$HAS_DONE" -gt 0 ] && echo 'yes' || echo 'NO')"
echo -e "  Content deltas:    $([ "$HAS_CONTENT_DELTA" -eq 1 ] && echo 'yes' || echo 'NO')"
echo ""

# TTFB analysis: flag suspiciously fast responses
if [[ "$STEP2_TTFB" != "?" ]]; then
    # Convert to milliseconds for comparison (bash can't do float comparison natively)
    TTFB_MS=""
    if [[ -n "$PYTHON" ]]; then
        TTFB_MS=$($PYTHON -c "print(int(float('${STEP2_TTFB}') * 1000))" 2>/dev/null || echo "")
    fi
    if [[ -n "$TTFB_MS" && "$TTFB_MS" -lt 50 ]]; then
        result_warn "TTFB is ${TTFB_MS}ms (<50ms) -- suspiciously fast"
        advice "A real model inference takes >100ms. TTFB <50ms suggests the response"
        advice "came from a proxy/cache/gateway, NOT the model. The model may never have run."
        echo ""
    fi
fi

if [[ "$STEP2_HTTP" == "200" && "$DATA_LINES" -gt 1 && "$HAS_CONTENT_DELTA" -eq 1 ]]; then
    result_pass "Streaming returned ${DATA_LINES} SSE events with content"
    advice "Streaming endpoint is healthy right now."
    if [[ "$HAS_DONE" -eq 0 ]]; then
        result_warn "No [DONE] marker at end of stream"
        advice "Server didn't send [DONE]. NEXUS handles this, but it's unusual."
    fi
elif [[ "$STEP2_HTTP" == "200" && "$DATA_LINES" -le 1 ]]; then
    result_fail "HTTP 200 but only ${DATA_LINES} SSE data lines (empty or near-empty stream)"
    advice "THIS IS THE BUG. Server returned 200 OK with SSE headers but no content."
    advice "The issue is server-side, not NEXUS. The server's streaming endpoint is"
    advice "returning empty responses intermittently."
    if [[ "$HAS_DONE" -gt 0 && "$DATA_LINES" -eq 1 ]]; then
        advice "Specifically: only a [DONE] marker with zero content events before it."
    fi
    echo ""
    echo -e "  ${YELLOW}First few SSE lines:${RESET}"
    echo "$STEP2_SSE" | head -10 | sed 's/^/    /'
elif [[ "$STEP2_HTTP" == "200" && "$HAS_CONTENT_DELTA" -eq 0 ]]; then
    result_fail "HTTP 200 with ${DATA_LINES} SSE events but NO content deltas"
    advice "Server sent events but none contained text content. Check the raw SSE below."
    echo ""
    echo -e "  ${YELLOW}First few SSE lines:${RESET}"
    echo "$STEP2_SSE" | grep '^data: ' | head -5 | sed 's/^/    /'
else
    result_fail "HTTP ${STEP2_HTTP}"
    advice "Streaming request failed. Check ${STEP2_LOG} for details."
fi
echo -e "  ${DIM}Full log: ${STEP2_LOG}${RESET}"
echo -e "  ${DIM}Verbose:  ${STEP2_VERBOSE}${RESET}"

# =============================================================================
# STEP 3: Python httpx (same HTTP client as NEXUS)
# =============================================================================

header "STEP 3: Python httpx streaming (same HTTP client as NEXUS)"
info "Uses the exact same HTTP library NEXUS uses internally."
info "If this fails but curl works, the issue is in httpx/httpcore."
echo ""

STEP3_LOG="$OUTDIR/03-httpx-stream.txt"

if [[ -z "$PYTHON" ]]; then
    echo "RESULT: SKIP - No python found" > "$STEP3_LOG"
else
$PYTHON - "$ENDPOINT" "$API_KEY" "$MODEL" "$TEST_MESSAGE" "$TIMEOUT" > "$STEP3_LOG" 2>&1 <<'PYEOF'
import sys, json, time

endpoint, api_key, model, message, timeout_s = sys.argv[1:6]
timeout_s = int(timeout_s)

try:
    import httpx
except ImportError:
    print("SKIP: httpx not installed")
    sys.exit(0)

payload = {
    "model": model,
    "messages": [{"role": "user", "content": message}],
    "stream": True,
    "max_tokens": 100,
}
headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
}

print(f"POST {endpoint}")
print(f"Timeout: {timeout_s}s")
print(f"httpx version: {httpx.__version__}")
print()

event_count = 0
content_chars = 0
received_done = False
finish_reason = None
start = time.monotonic()

try:
    with httpx.Client(timeout=timeout_s) as client:
        with client.stream("POST", endpoint, json=payload, headers=headers) as response:
            print(f"HTTP {response.status_code}")
            print(f"Headers: {dict(response.headers)}")
            print()

            for chunk in response.iter_text():
                for raw_line in chunk.split("\n"):
                    line = raw_line.strip()
                    if not line or line.startswith("event:"):
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            received_done = True
                            print(f"  [{event_count+1}] [DONE]")
                            continue
                        try:
                            data = json.loads(data_str)
                            event_count += 1
                            choices = data.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                text = delta.get("content", "")
                                fr = choices[0].get("finish_reason")
                                if fr:
                                    finish_reason = fr
                                content_chars += len(text)
                                preview = repr(text[:80]) if text else "(empty delta)"
                                print(f"  [{event_count}] {preview}")
                            elif data.get("type"):
                                etype = data["type"]
                                if etype == "content_block_delta":
                                    text = data.get("delta", {}).get("text", "")
                                    content_chars += len(text)
                                    preview = repr(text[:80]) if text else "(empty)"
                                    print(f"  [{event_count}] {etype}: {preview}")
                                elif etype == "message_delta":
                                    sr = data.get("delta", {}).get("stop_reason")
                                    if sr:
                                        finish_reason = sr
                                    print(f"  [{event_count}] {etype}: stop_reason={sr}")
                                else:
                                    print(f"  [{event_count}] {etype}")
                        except json.JSONDecodeError:
                            print(f"  [?] JSON parse error: {data_str[:100]}")

    duration_ms = round((time.monotonic() - start) * 1000)
    print()
    print(f"=== SUMMARY ===")
    print(f"Events:         {event_count}")
    print(f"Content chars:  {content_chars}")
    print(f"[DONE]:         {received_done}")
    print(f"finish_reason:  {finish_reason}")
    print(f"Duration:       {duration_ms}ms")

    if content_chars > 0:
        print(f"RESULT: PASS")
    elif event_count == 0:
        print(f"RESULT: FAIL - Zero events (empty stream)")
    else:
        print(f"RESULT: FAIL - {event_count} events but no content")

except httpx.TimeoutException as e:
    print(f"RESULT: FAIL - Timeout after {timeout_s}s: {e}")
except httpx.ConnectError as e:
    print(f"RESULT: FAIL - Connection error: {e}")
except Exception as e:
    print(f"RESULT: FAIL - {type(e).__name__}: {e}")
PYEOF
fi

# Display results
STEP3_RESULT=$(grep '^RESULT:' "$STEP3_LOG" || echo "RESULT: UNKNOWN")
STEP3_EVENTS=$(grep '^Events:' "$STEP3_LOG" | awk '{print $2}' || echo "?")
STEP3_CONTENT=$(grep '^Content chars:' "$STEP3_LOG" | awk '{print $3}' || echo "?")
STEP3_DURATION=$(grep '^Duration:' "$STEP3_LOG" | awk '{print $2}' || echo "?")

if echo "$STEP3_RESULT" | grep -q "SKIP"; then
    result_warn "Skipped (${PYTHON:-no python found}; needs httpx: pip install httpx)"
elif echo "$STEP3_RESULT" | grep -q "PASS"; then
    echo -e "  Events: ${STEP3_EVENTS}, Content: ${STEP3_CONTENT} chars, Duration: ${STEP3_DURATION}"
    result_pass "httpx streaming returned content"
    advice "Same HTTP library as NEXUS works fine. If NEXUS had an empty response"
    advice "at the same time, it was likely a transient server issue that resolved."
elif echo "$STEP3_RESULT" | grep -q "Zero events"; then
    echo -e "  Events: ${STEP3_EVENTS}, Content: ${STEP3_CONTENT} chars, Duration: ${STEP3_DURATION}"
    result_fail "httpx got zero events (empty stream body)"
    advice "Same HTTP library, same result. Confirms this is NOT a NEXUS bug."
    advice "The server is returning empty streaming responses."
else
    echo -e "  ${STEP3_RESULT}"
    result_fail "httpx request failed"
    advice "Check ${STEP3_LOG} for details."
fi
echo -e "  ${DIM}Full log: ${STEP3_LOG}${RESET}"

# =============================================================================
# STEP 4: Rapid-fire requests + backend server header tracking
# =============================================================================

if [[ "$QUICK_MODE" == true ]]; then
    header "STEP 4: Rapid-fire requests -- SKIPPED (--quick mode)"
else
    header "STEP 4: Rapid-fire ${RAPID_COUNT}x requests (load balancer detection)"
    info "Sends ${RAPID_COUNT} quick non-streaming requests in sequence."
    info "If some succeed and some fail, a load balancer is routing to a bad backend."
    info "Tracks '${SERVER_HEADER}' response header to identify which backend served each."
    echo ""

    STEP4_LOG="$OUTDIR/04-rapid-fire.txt"
    PASS_COUNT=0
    FAIL_COUNT=0
    EMPTY_COUNT=0
    declare -A BACKEND_PASS 2>/dev/null || true
    declare -A BACKEND_FAIL 2>/dev/null || true
    BACKENDS_SEEN=""

    for i in $(seq 1 "$RAPID_COUNT"); do
        # Capture response headers to a temp file for server header extraction
        STEP4_HDRFILE="$OUTDIR/04-headers-${i}.txt"
        RESP=$(curl -sS -D "$STEP4_HDRFILE" -w '\n__HTTP_CODE__:%{http_code}' \
            --max-time "$TIMEOUT" \
            -H "Authorization: Bearer ${API_KEY}" \
            -H "Content-Type: application/json" \
            -d "$PAYLOAD_SYNC" \
            "$ENDPOINT" 2>/dev/null || true)

        HTTP=$(echo "$RESP" | grep '__HTTP_CODE__' | cut -d: -f2 || echo "0")
        BODY=$(echo "$RESP" | grep -v '^__' || true)
        HAS_CONTENT=$(check_content "$BODY")

        # Extract backend server header (case-insensitive grep)
        BACKEND=$(grep -i "^${SERVER_HEADER}:" "$STEP4_HDRFILE" 2>/dev/null | head -1 | sed "s/^[^:]*:[[:space:]]*//" | tr -d '\r' || echo "unknown")
        if [[ -z "$BACKEND" ]]; then
            BACKEND="(no header)"
        fi

        {
            echo "--- Request $i ---"
            echo "HTTP: $HTTP"
            echo "Backend: $BACKEND"
            echo "Content length: $HAS_CONTENT"
            echo "$BODY" | head -5
            echo ""
        } >> "$STEP4_LOG"

        if [[ "$HTTP" == "200" && "$HAS_CONTENT" -gt 0 ]]; then
            echo -e "  Request ${i}/${RAPID_COUNT}: ${GREEN}HTTP ${HTTP}${RESET} -- ${HAS_CONTENT} chars  [backend: ${BACKEND}]"
            PASS_COUNT=$((PASS_COUNT + 1))
        elif [[ "$HTTP" == "200" ]]; then
            echo -e "  Request ${i}/${RAPID_COUNT}: ${YELLOW}HTTP ${HTTP}${RESET} -- EMPTY (0 chars)  [backend: ${BOLD}${BACKEND}${RESET}]"
            EMPTY_COUNT=$((EMPTY_COUNT + 1))
        else
            echo -e "  Request ${i}/${RAPID_COUNT}: ${RED}HTTP ${HTTP}${RESET}  [backend: ${BOLD}${BACKEND}${RESET}]"
            FAIL_COUNT=$((FAIL_COUNT + 1))
        fi

        # Track unique backends
        if [[ "$BACKENDS_SEEN" != *"$BACKEND"* ]]; then
            if [[ -n "$BACKENDS_SEEN" ]]; then
                BACKENDS_SEEN="${BACKENDS_SEEN}, ${BACKEND}"
            else
                BACKENDS_SEEN="$BACKEND"
            fi
        fi

        # Clean up header file
        rm -f "$STEP4_HDRFILE"
    done

    echo ""
    echo -e "  Results:  ${GREEN}${PASS_COUNT} pass${RESET}, ${YELLOW}${EMPTY_COUNT} empty${RESET}, ${RED}${FAIL_COUNT} error${RESET}"
    echo -e "  Backends: ${BACKENDS_SEEN}"

    if [[ "$PASS_COUNT" -eq "$RAPID_COUNT" ]]; then
        result_pass "All ${RAPID_COUNT} requests returned content"
        advice "Server is consistently healthy right now. The issue may have been transient."
    elif [[ "$EMPTY_COUNT" -gt 0 && "$PASS_COUNT" -gt 0 ]]; then
        result_fail "${EMPTY_COUNT}/${RAPID_COUNT} returned empty responses"
        advice "INTERMITTENT EMPTY RESPONSES CONFIRMED. Mixed results strongly suggest"
        advice "a load balancer routing to multiple backends, some of which are broken."
        advice "Check the backend column above -- if empty responses correlate with a"
        advice "specific backend name, that's your culprit."
        advice "Report this to your infrastructure team with this log."
    elif [[ "$EMPTY_COUNT" -eq "$RAPID_COUNT" ]]; then
        result_fail "ALL ${RAPID_COUNT} requests returned empty"
        advice "Server is consistently returning empty responses. Not intermittent --"
        advice "the model or endpoint is broken right now."
    elif [[ "$FAIL_COUNT" -gt 0 ]]; then
        result_fail "${FAIL_COUNT}/${RAPID_COUNT} returned HTTP errors"
        advice "Server errors. Could be rate limiting (429) or backend issues (502/503)."
    fi
    echo -e "  ${DIM}Full log: ${STEP4_LOG}${RESET}"
fi

# =============================================================================
# STEP 5: TLS and connectivity details
# =============================================================================

header "STEP 5: Connection details (TLS, DNS, routing)"
info "Captures low-level connection info that may help infra teams debug."
echo ""

STEP5_LOG="$OUTDIR/05-connection-info.txt"

{
    echo "=== DNS Resolution ==="
    nslookup "$ENDPOINT_HOST" 2>&1 || echo "(nslookup failed)"
    echo ""
    echo "=== TLS Certificate (leaf) ==="
    echo | openssl s_client -connect "${ENDPOINT_HOST}:443" -servername "$ENDPOINT_HOST" 2>/dev/null | openssl x509 -noout -subject -issuer -dates 2>/dev/null || echo "(openssl check failed)"
    echo ""
    echo "=== curl connection trace ==="
    curl -sS -v -o /dev/null --max-time 10 \
        -H "Authorization: Bearer ${API_KEY}" \
        "https://${ENDPOINT_HOST}/v1/models" 2>&1 || echo "(connection trace failed)"
} > "$STEP5_LOG" 2>&1

DNS_IPS=$(grep -E '^[[:space:]]*Address:' "$STEP5_LOG" | tail -n +2 | awk '{print $2}' | tr '\n' ', ' || echo "unknown")
echo -e "  Endpoint host: ${BOLD}${ENDPOINT_HOST}${RESET}"
echo -e "  Resolved IPs:  ${DNS_IPS:-unknown}"

TLS_ISSUER=$(grep 'issuer=' "$STEP5_LOG" | head -1 | sed 's/issuer=//' || echo "unknown")
echo -e "  TLS issuer:    ${TLS_ISSUER:-unknown}"

result_pass "Connection details captured"
echo -e "  ${DIM}Full log: ${STEP5_LOG}${RESET}"

# =============================================================================
# STEP 6: Corporate certificate chain + TLS comparison matrix
# =============================================================================

header "STEP 6: Certificate chain analysis + TLS comparison matrix"
info "Analyzes the full certificate chain for TLS inspection proxies"
info "(Zscaler, Blue Coat, Palo Alto, Fortinet, etc.) and runs transport"
info "tests with different cert configurations."
echo ""

STEP6_LOG="$OUTDIR/06-cert-analysis.txt"

{
    echo "=== Full Certificate Chain ==="
    echo | openssl s_client -showcerts -connect "${ENDPOINT_HOST}:443" -servername "$ENDPOINT_HOST" 2>/dev/null || echo "(openssl s_client failed)"
    echo ""

    echo "=== Certificate Chain Summary ==="
    echo | openssl s_client -connect "${ENDPOINT_HOST}:443" -servername "$ENDPOINT_HOST" 2>/dev/null | \
        openssl x509 -noout -text 2>/dev/null | grep -E '(Issuer:|Subject:|Not Before|Not After)' || echo "(cert parse failed)"
    echo ""

    echo "=== Relevant Environment Variables ==="
    echo "SSL_CERT_FILE=${SSL_CERT_FILE:-NOT SET}"
    echo "SSL_CERT_DIR=${SSL_CERT_DIR:-NOT SET}"
    echo "REQUESTS_CA_BUNDLE=${REQUESTS_CA_BUNDLE:-NOT SET}"
    echo "CURL_CA_BUNDLE=${CURL_CA_BUNDLE:-NOT SET}"
    echo "NODE_EXTRA_CA_CERTS=${NODE_EXTRA_CA_CERTS:-NOT SET}"
    echo ""

    if [[ -n "$PYTHON" ]]; then
        echo "=== Python certifi CA Bundle ==="
        $PYTHON -c "
try:
    import certifi
    print(f'certifi path: {certifi.where()}')
    # Check if corporate CA is in the bundle
    import os
    path = certifi.where()
    size = os.path.getsize(path)
    print(f'Bundle size: {size} bytes')
    # Count certificates in bundle
    with open(path, 'r') as f:
        cert_count = f.read().count('BEGIN CERTIFICATE')
    print(f'Certificate count: {cert_count}')
except ImportError:
    print('certifi not installed')
except Exception as e:
    print(f'Error: {e}')
" 2>&1 || echo "(python certifi check failed)"
        echo ""

        echo "=== Python SSL Default Paths ==="
        $PYTHON -c "
import ssl
ctx = ssl.create_default_context()
print(f'Default CA file: {ssl.get_default_verify_paths().cafile}')
print(f'Default CA path: {ssl.get_default_verify_paths().capath}')
print(f'OpenSSL default: {ssl.get_default_verify_paths().openssl_cafile_env}')
" 2>&1 || echo "(python ssl check failed)"
        echo ""
    fi

    if [[ -n "$CERT_PATH" ]]; then
        echo "=== Custom CA Bundle ==="
        if [[ -f "$CERT_PATH" ]]; then
            echo "File exists: $CERT_PATH"
            echo "Size: $(wc -c < "$CERT_PATH") bytes"
            CERT_COUNT=$(grep -c 'BEGIN CERTIFICATE' "$CERT_PATH" || echo "0")
            echo "Certificate count: $CERT_COUNT"
            echo ""
            echo "Subjects in bundle:"
            openssl crl2pkcs7 -nocrl -certfile "$CERT_PATH" 2>/dev/null | \
                openssl pkcs7 -print_certs -noout 2>/dev/null | \
                grep 'subject=' || echo "(could not parse bundle)"
        else
            echo "WARNING: CERT_PATH='$CERT_PATH' does not exist!"
        fi
        echo ""
    fi
} > "$STEP6_LOG" 2>&1

# Detect TLS inspection proxy from cert chain
TLS_PROXY="none"
CHAIN_ISSUERS=$(grep -i 'issuer=' "$STEP6_LOG" | head -5 || true)
for proxy_name in "zscaler" "blue coat" "bluecoat" "symantec" "fortigate" "fortinet" "palo alto" "barracuda" "mcafee" "websense" "sophos" "cisco umbrella" "netskope"; do
    if echo "$CHAIN_ISSUERS" | grep -qi "$proxy_name"; then
        TLS_PROXY="$proxy_name"
        break
    fi
done

echo -e "  TLS inspection proxy: ${BOLD}${TLS_PROXY}${RESET}"
if [[ "$TLS_PROXY" != "none" ]]; then
    result_warn "TLS inspection proxy detected: ${TLS_PROXY}"
    advice "Your traffic passes through a TLS inspection proxy (${TLS_PROXY})."
    advice "These proxies can buffer, modify, or truncate SSE streams."
    advice "This is a LIKELY CAUSE of intermittent empty streaming responses."
    advice "Ask your network team if SSE/chunked-transfer is exempted from inspection."
else
    result_pass "No known TLS inspection proxy detected in cert chain"
fi

# Show relevant env vars
for var in SSL_CERT_FILE SSL_CERT_DIR REQUESTS_CA_BUNDLE CURL_CA_BUNDLE NODE_EXTRA_CA_CERTS; do
    val="${!var:-}"
    if [[ -n "$val" ]]; then
        echo -e "  ${var}=${val}"
    fi
done

echo ""

# --- TLS Comparison Matrix ---
# Run the same request with different cert configurations and compare
echo -e "  ${BOLD}TLS Comparison Matrix:${RESET}"
echo -e "  ${DIM}(testing curl sync, curl stream, httpx stream with different cert modes)${RESET}"
echo ""

STEP6_MATRIX="$OUTDIR/06-tls-matrix.txt"
echo "=== TLS Comparison Matrix ===" > "$STEP6_MATRIX"
echo "" >> "$STEP6_MATRIX"

# Determine which cert modes to test
CERT_MODES=("default" "insecure")
if [[ -n "$CERT_PATH" && -f "$CERT_PATH" ]]; then
    CERT_MODES=("default" "custom" "insecure")
fi

# Table header
printf "  %-12s %-14s %-14s %-14s\n" "Cert Mode" "curl sync" "curl stream" "httpx stream"
printf "  %-12s %-14s %-14s %-14s\n" "----------" "----------" "-----------" "------------"

for cert_mode in "${CERT_MODES[@]}"; do
    CERT_ARGS_STR=""
    case "$cert_mode" in
        custom)   CERT_ARGS_STR="--cacert ${CERT_PATH}" ;;
        insecure) CERT_ARGS_STR="--insecure" ;;
    esac

    # --- curl sync ---
    CURL_SYNC_RESULT="?"
    CURL_SYNC_RESP=$(curl -sS -w '\n__HTTP_CODE__:%{http_code}' \
        --max-time "$TIMEOUT" $CERT_ARGS_STR \
        -H "Authorization: Bearer ${API_KEY}" \
        -H "Content-Type: application/json" \
        -d "$PAYLOAD_SYNC" \
        "$ENDPOINT" 2>/dev/null || true)
    CURL_SYNC_HTTP=$(echo "$CURL_SYNC_RESP" | grep '__HTTP_CODE__' | cut -d: -f2 || echo "0")
    CURL_SYNC_BODY=$(echo "$CURL_SYNC_RESP" | grep -v '^__' || true)
    CURL_SYNC_CONTENT=$(check_content "$CURL_SYNC_BODY")
    if [[ "$CURL_SYNC_HTTP" == "200" && "$CURL_SYNC_CONTENT" -gt 0 ]]; then
        CURL_SYNC_RESULT="PASS"
    elif [[ "$CURL_SYNC_HTTP" == "200" ]]; then
        CURL_SYNC_RESULT="EMPTY"
    else
        CURL_SYNC_RESULT="HTTP ${CURL_SYNC_HTTP}"
    fi

    # --- curl stream ---
    CURL_STREAM_RESULT="?"
    CURL_STREAM_RESP=$(curl -sS -N -w '\n__HTTP_CODE__:%{http_code}\n__SIZE_DOWNLOAD__:%{size_download}\n' \
        --max-time "$TIMEOUT" $CERT_ARGS_STR \
        -H "Authorization: Bearer ${API_KEY}" \
        -H "Content-Type: application/json" \
        -d "$PAYLOAD_STREAM" \
        "$ENDPOINT" 2>/dev/null || true)
    CURL_STREAM_HTTP=$(echo "$CURL_STREAM_RESP" | grep '__HTTP_CODE__' | cut -d: -f2 || echo "0")
    CURL_STREAM_SSE=$(echo "$CURL_STREAM_RESP" | grep -v '^__' || true)
    CURL_STREAM_DATA=$(echo "$CURL_STREAM_SSE" | grep -c '^data: ' || true)
    CURL_STREAM_HAS_CONTENT=0
    if echo "$CURL_STREAM_SSE" | grep '^data: ' | grep -v '\[DONE\]' | grep -q '"content"'; then
        CURL_STREAM_HAS_CONTENT=1
    fi
    if [[ "$CURL_STREAM_HTTP" == "200" && "$CURL_STREAM_DATA" -gt 1 && "$CURL_STREAM_HAS_CONTENT" -eq 1 ]]; then
        CURL_STREAM_RESULT="PASS"
    elif [[ "$CURL_STREAM_HTTP" == "200" ]]; then
        CURL_STREAM_RESULT="EMPTY"
    else
        CURL_STREAM_RESULT="HTTP ${CURL_STREAM_HTTP}"
    fi

    # --- httpx stream ---
    HTTPX_STREAM_RESULT="SKIP"
    if [[ -n "$PYTHON" ]]; then
        HTTPX_OUT=$($PYTHON -c "
import sys, json
try:
    import httpx
except ImportError:
    print('SKIP')
    sys.exit(0)

cert_mode = '${cert_mode}'
cert_path = '${CERT_PATH}'
verify = True
if cert_mode == 'insecure':
    verify = False
elif cert_mode == 'custom' and cert_path:
    verify = cert_path

payload = {
    'model': '${MODEL}',
    'messages': [{'role': 'user', 'content': '${TEST_MESSAGE}'}],
    'stream': True,
    'max_tokens': 100,
}
headers = {
    'Authorization': 'Bearer ${API_KEY}',
    'Content-Type': 'application/json',
}

try:
    with httpx.Client(timeout=${TIMEOUT}, verify=verify) as client:
        with client.stream('POST', '${ENDPOINT}', json=payload, headers=headers) as response:
            if response.status_code != 200:
                print(f'HTTP {response.status_code}')
                sys.exit(0)
            content_chars = 0
            for chunk in response.iter_text():
                for line in chunk.split('\n'):
                    line = line.strip()
                    if line.startswith('data: ') and line != 'data: [DONE]':
                        try:
                            d = json.loads(line[6:])
                            choices = d.get('choices', [])
                            if choices:
                                text = choices[0].get('delta', {}).get('content', '')
                                content_chars += len(text)
                        except: pass
            if content_chars > 0:
                print('PASS')
            else:
                print('EMPTY')
except Exception as e:
    print(f'ERR: {type(e).__name__}')
" 2>/dev/null || echo "ERR")
        HTTPX_STREAM_RESULT="$HTTPX_OUT"
    fi

    # Color-code results
    color_result() {
        local r="$1"
        case "$r" in
            PASS)  echo -e "${GREEN}${r}${RESET}" ;;
            EMPTY) echo -e "${YELLOW}${r}${RESET}" ;;
            SKIP)  echo -e "${DIM}${r}${RESET}" ;;
            *)     echo -e "${RED}${r}${RESET}" ;;
        esac
    }

    printf "  %-12s %-14b %-14b %-14b\n" \
        "$cert_mode" \
        "$(color_result "$CURL_SYNC_RESULT")" \
        "$(color_result "$CURL_STREAM_RESULT")" \
        "$(color_result "$HTTPX_STREAM_RESULT")"

    # Log to matrix file
    echo "${cert_mode}: curl_sync=${CURL_SYNC_RESULT} curl_stream=${CURL_STREAM_RESULT} httpx_stream=${HTTPX_STREAM_RESULT}" >> "$STEP6_MATRIX"
done

echo ""

# Interpretation
echo -e "  ${DIM}How to read the matrix:${RESET}"
echo -e "  ${DIM}  All PASS across modes -> TLS config is not the issue${RESET}"
echo -e "  ${DIM}  default FAIL but insecure PASS -> cert validation issue${RESET}"
echo -e "  ${DIM}  custom PASS but default FAIL -> system CA bundle missing corporate CA${RESET}"
echo -e "  ${DIM}  curl PASS but httpx FAIL -> httpx uses different TLS path${RESET}"
echo -e "  ${DIM}  stream FAIL but sync PASS -> streaming specifically broken (proxy buffering?)${RESET}"

echo -e "  ${DIM}Full log: ${STEP6_LOG}${RESET}"
echo -e "  ${DIM}Matrix:   ${STEP6_MATRIX}${RESET}"

# =============================================================================
# STEP 7: /v1/models health check
# =============================================================================

header "STEP 7: /v1/models endpoint health check"
info "Checks whether the model is listed as available on the server."
info "If the model isn't listed, requests may be silently dropped or misrouted."
echo ""

STEP7_LOG="$OUTDIR/07-models-check.txt"
MODELS_URL="${BASE_URL}/models"

{
    echo "=== GET ${MODELS_URL} ==="
    echo ""
} > "$STEP7_LOG"

STEP7_BODY=$(curl -sS -w '\n__HTTP_CODE__:%{http_code}\n' \
    --max-time "$TIMEOUT" \
    -H "Authorization: Bearer ${API_KEY}" \
    "$MODELS_URL" 2>>"$STEP7_LOG" || true)

echo "$STEP7_BODY" >> "$STEP7_LOG"

STEP7_HTTP=$(echo "$STEP7_BODY" | grep '__HTTP_CODE__' | cut -d: -f2 || echo "0")
STEP7_CONTENT=$(echo "$STEP7_BODY" | grep -v '^__' || true)

echo -e "  Models URL: ${BOLD}${MODELS_URL}${RESET}"
echo -e "  HTTP status: ${BOLD}${STEP7_HTTP}${RESET}"

if [[ "$STEP7_HTTP" == "200" ]]; then
    # Check if our model is in the list
    if [[ -n "$PYTHON" ]]; then
        MODEL_INFO=$($PYTHON -c "
import sys, json
try:
    data = json.loads(sys.stdin.read())
    models = data.get('data', [])
    model_ids = [m.get('id', '') for m in models]
    target = '${MODEL}'
    if target in model_ids:
        print(f'FOUND ({len(model_ids)} models total)')
    else:
        # Check partial match
        matches = [m for m in model_ids if target in m or m in target]
        if matches:
            print(f'PARTIAL: {matches[0]} ({len(model_ids)} models total)')
        else:
            print(f'NOT FOUND ({len(model_ids)} models total)')
            if model_ids:
                print('Available: ' + ', '.join(model_ids[:10]))
except Exception as e:
    print(f'PARSE ERROR: {e}')
" <<< "$STEP7_CONTENT" 2>/dev/null || echo "PARSE ERROR")
    else
        if echo "$STEP7_CONTENT" | grep -q "\"${MODEL}\""; then
            MODEL_INFO="FOUND"
        else
            MODEL_INFO="NOT FOUND (grep check)"
        fi
    fi

    echo -e "  Model '${MODEL}': ${BOLD}${MODEL_INFO}${RESET}"

    if echo "$MODEL_INFO" | grep -q "FOUND"; then
        result_pass "Model '${MODEL}' is available on the server"
    elif echo "$MODEL_INFO" | grep -q "PARTIAL"; then
        result_warn "Exact model ID not found, but partial match exists"
        advice "Check if you're using the correct model ID."
    else
        result_fail "Model '${MODEL}' is NOT listed by the server"
        advice "The model may have been removed, renamed, or is only available on"
        advice "certain backends. This could explain intermittent failures if some"
        advice "backends have the model and others don't."
    fi
elif [[ "$STEP7_HTTP" == "404" ]]; then
    result_warn "/v1/models endpoint returned 404"
    advice "Server doesn't expose a models listing. This is normal for some deployments."
elif [[ "$STEP7_HTTP" == "401" || "$STEP7_HTTP" == "403" ]]; then
    result_warn "/v1/models returned ${STEP7_HTTP} (auth required or forbidden)"
    advice "Cannot check model availability due to access restrictions."
else
    result_fail "/v1/models returned HTTP ${STEP7_HTTP}"
fi
echo -e "  ${DIM}Full log: ${STEP7_LOG}${RESET}"

# =============================================================================
# STEP 8: Parallel streaming requests
# =============================================================================

if [[ "$QUICK_MODE" == true ]]; then
    header "STEP 8: Parallel streaming -- SKIPPED (--quick mode)"
else
    header "STEP 8: Parallel streaming (${PARALLEL_COUNT} simultaneous streams)"
    info "Fires ${PARALLEL_COUNT} streaming requests simultaneously."
    info "Tests whether concurrent load causes the server to drop streams."
    echo ""

    STEP8_LOG="$OUTDIR/08-parallel-stream.txt"
    echo "=== Parallel Streaming Test (${PARALLEL_COUNT} simultaneous) ===" > "$STEP8_LOG"
    echo "" >> "$STEP8_LOG"

    # Launch parallel curl processes
    STEP8_PIDS=""
    for i in $(seq 1 "$PARALLEL_COUNT"); do
        STEP8_OUTFILE="$OUTDIR/08-parallel-${i}.txt"
        (
            curl -sS -N -w '\n__HTTP_CODE__:%{http_code}\n__TIME_TOTAL__:%{time_total}\n__TIME_STARTTRANSFER__:%{time_starttransfer}\n__SIZE_DOWNLOAD__:%{size_download}\n' \
                --max-time "$TIMEOUT" \
                -H "Authorization: Bearer ${API_KEY}" \
                -H "Content-Type: application/json" \
                -d "$PAYLOAD_STREAM" \
                "$ENDPOINT" > "$STEP8_OUTFILE" 2>&1
        ) &
        STEP8_PIDS="$STEP8_PIDS $!"
    done

    # Wait for all to complete
    for pid in $STEP8_PIDS; do
        wait "$pid" 2>/dev/null || true
    done

    # Analyze results
    PARA_PASS=0
    PARA_EMPTY=0
    PARA_FAIL=0

    for i in $(seq 1 "$PARALLEL_COUNT"); do
        STEP8_OUTFILE="$OUTDIR/08-parallel-${i}.txt"
        P_HTTP=$(grep '__HTTP_CODE__' "$STEP8_OUTFILE" | cut -d: -f2 || echo "0")
        P_TTFB=$(grep '__TIME_STARTTRANSFER__' "$STEP8_OUTFILE" | cut -d: -f2 || echo "?")
        P_SIZE=$(grep '__SIZE_DOWNLOAD__' "$STEP8_OUTFILE" | cut -d: -f2 || echo "0")
        P_SSE=$(grep -v '^__' "$STEP8_OUTFILE" || true)
        P_DATA=$(echo "$P_SSE" | grep -c '^data: ' || true)
        P_HAS_CONTENT=0
        if echo "$P_SSE" | grep '^data: ' | grep -v '\[DONE\]' | grep -q '"content"'; then
            P_HAS_CONTENT=1
        fi

        {
            echo "--- Stream $i ---"
            echo "HTTP: $P_HTTP, TTFB: ${P_TTFB}s, Size: ${P_SIZE}, Data lines: $P_DATA, Content: $P_HAS_CONTENT"
        } >> "$STEP8_LOG"

        if [[ "$P_HTTP" == "200" && "$P_DATA" -gt 1 && "$P_HAS_CONTENT" -eq 1 ]]; then
            echo -e "  Stream ${i}/${PARALLEL_COUNT}: ${GREEN}PASS${RESET} (${P_DATA} events, TTFB ${P_TTFB}s)"
            PARA_PASS=$((PARA_PASS + 1))
        elif [[ "$P_HTTP" == "200" ]]; then
            echo -e "  Stream ${i}/${PARALLEL_COUNT}: ${YELLOW}EMPTY${RESET} (${P_DATA} data lines, TTFB ${P_TTFB}s)"
            PARA_EMPTY=$((PARA_EMPTY + 1))
        else
            echo -e "  Stream ${i}/${PARALLEL_COUNT}: ${RED}HTTP ${P_HTTP}${RESET}"
            PARA_FAIL=$((PARA_FAIL + 1))
        fi
        rm -f "$STEP8_OUTFILE"
    done

    echo ""
    echo -e "  Results: ${GREEN}${PARA_PASS} pass${RESET}, ${YELLOW}${PARA_EMPTY} empty${RESET}, ${RED}${PARA_FAIL} error${RESET}"

    if [[ "$PARA_PASS" -eq "$PARALLEL_COUNT" ]]; then
        result_pass "All ${PARALLEL_COUNT} parallel streams returned content"
        advice "Server handles concurrent streaming fine."
    elif [[ "$PARA_EMPTY" -gt 0 ]]; then
        result_fail "${PARA_EMPTY}/${PARALLEL_COUNT} parallel streams were empty"
        advice "Server drops streams under concurrent load. This could be a"
        advice "connection pool limit, load balancer issue, or model capacity problem."
    elif [[ "$PARA_FAIL" -gt 0 ]]; then
        result_fail "${PARA_FAIL}/${PARALLEL_COUNT} parallel streams returned errors"
        advice "Server rejects concurrent requests. Check rate limits."
    fi
    echo -e "  ${DIM}Full log: ${STEP8_LOG}${RESET}"
fi

# =============================================================================
# STEP 9: Alternate model test
# =============================================================================

if [[ -z "$ALT_MODEL" ]]; then
    header "STEP 9: Alternate model test -- SKIPPED (ALT_MODEL not set)"
    info "Set ALT_MODEL in the config section to test a different model on the same endpoint."
else
    header "STEP 9: Alternate model test (${ALT_MODEL})"
    info "Tests whether a different model on the same endpoint works."
    info "If ALT_MODEL works but MODEL fails, the issue is model-specific."
    echo ""

    STEP9_LOG="$OUTDIR/09-alt-model.txt"

    ALT_PAYLOAD_SYNC=$(cat <<ENDJSON
{
  "model": "${ALT_MODEL}",
  "messages": [{"role": "user", "content": "${TEST_MESSAGE}"}],
  "stream": false,
  "max_tokens": 100
}
ENDJSON
)

    ALT_PAYLOAD_STREAM=$(cat <<ENDJSON
{
  "model": "${ALT_MODEL}",
  "messages": [{"role": "user", "content": "${TEST_MESSAGE}"}],
  "stream": true,
  "max_tokens": 100
}
ENDJSON
)

    {
        echo "=== Non-streaming request (alt model: ${ALT_MODEL}) ==="
        echo ""
    } > "$STEP9_LOG"

    # Test 1: Alt model sync
    ALT_SYNC_RESP=$(curl -sS -w '\n__HTTP_CODE__:%{http_code}\n' \
        --max-time "$TIMEOUT" \
        -H "Authorization: Bearer ${API_KEY}" \
        -H "Content-Type: application/json" \
        -d "$ALT_PAYLOAD_SYNC" \
        "$ENDPOINT" 2>>"$STEP9_LOG" || true)

    ALT_SYNC_HTTP=$(echo "$ALT_SYNC_RESP" | grep '__HTTP_CODE__' | cut -d: -f2 || echo "0")
    ALT_SYNC_BODY=$(echo "$ALT_SYNC_RESP" | grep -v '^__' || true)
    ALT_SYNC_CONTENT=$(check_content "$ALT_SYNC_BODY")

    echo "$ALT_SYNC_RESP" >> "$STEP9_LOG"
    echo "" >> "$STEP9_LOG"

    # Test 2: Alt model stream
    echo "=== Streaming request (alt model: ${ALT_MODEL}) ===" >> "$STEP9_LOG"
    ALT_STREAM_RESP=$(curl -sS -N -w '\n__HTTP_CODE__:%{http_code}\n__SIZE_DOWNLOAD__:%{size_download}\n' \
        --max-time "$TIMEOUT" \
        -H "Authorization: Bearer ${API_KEY}" \
        -H "Content-Type: application/json" \
        -d "$ALT_PAYLOAD_STREAM" \
        "$ENDPOINT" 2>>"$STEP9_LOG" || true)

    ALT_STREAM_HTTP=$(echo "$ALT_STREAM_RESP" | grep '__HTTP_CODE__' | cut -d: -f2 || echo "0")
    ALT_STREAM_SSE=$(echo "$ALT_STREAM_RESP" | grep -v '^__' || true)
    ALT_STREAM_DATA=$(echo "$ALT_STREAM_SSE" | grep -c '^data: ' || true)
    ALT_STREAM_HAS_CONTENT=0
    if echo "$ALT_STREAM_SSE" | grep '^data: ' | grep -v '\[DONE\]' | grep -q '"content"'; then
        ALT_STREAM_HAS_CONTENT=1
    fi

    echo "$ALT_STREAM_RESP" >> "$STEP9_LOG"

    # Display results side by side
    printf "  %-20s %-12s %-12s\n" "" "${MODEL}" "${ALT_MODEL}"
    printf "  %-20s %-12s %-12s\n" "---" "---" "---"

    # Original model results (from Steps 1 and 2)
    ORIG_SYNC="HTTP ${STEP1_HTTP}"
    if [[ "$STEP1_HTTP" == "200" ]]; then
        ORIG_SYNC_CONTENT=$(check_content "$STEP1_CONTENT")
        if [[ "$ORIG_SYNC_CONTENT" -gt 0 ]]; then ORIG_SYNC="PASS"; else ORIG_SYNC="EMPTY"; fi
    fi
    ALT_SYNC="HTTP ${ALT_SYNC_HTTP}"
    if [[ "$ALT_SYNC_HTTP" == "200" && "$ALT_SYNC_CONTENT" -gt 0 ]]; then ALT_SYNC="PASS"
    elif [[ "$ALT_SYNC_HTTP" == "200" ]]; then ALT_SYNC="EMPTY"; fi

    ORIG_STREAM="HTTP ${STEP2_HTTP}"
    if [[ "$STEP2_HTTP" == "200" && "$HAS_CONTENT_DELTA" -eq 1 ]]; then ORIG_STREAM="PASS"
    elif [[ "$STEP2_HTTP" == "200" ]]; then ORIG_STREAM="EMPTY"; fi
    ALT_STREAM_R="HTTP ${ALT_STREAM_HTTP}"
    if [[ "$ALT_STREAM_HTTP" == "200" && "$ALT_STREAM_DATA" -gt 1 && "$ALT_STREAM_HAS_CONTENT" -eq 1 ]]; then ALT_STREAM_R="PASS"
    elif [[ "$ALT_STREAM_HTTP" == "200" ]]; then ALT_STREAM_R="EMPTY"; fi

    printf "  %-20s %-12s %-12s\n" "Non-streaming" "$ORIG_SYNC" "$ALT_SYNC"
    printf "  %-20s %-12s %-12s\n" "Streaming" "$ORIG_STREAM" "$ALT_STREAM_R"
    echo ""

    if [[ "$ALT_SYNC" == "PASS" && "$ALT_STREAM_R" == "PASS" ]]; then
        if [[ "$ORIG_SYNC" == "PASS" && "$ORIG_STREAM" == "PASS" ]]; then
            result_pass "Both models work fine right now"
            advice "Issue was transient. Both models responding normally."
        else
            result_warn "Alt model works but primary model has issues"
            advice "The issue is specific to model '${MODEL}'. The server endpoint"
            advice "is fine for other models. Check if '${MODEL}' is overloaded or misconfigured."
        fi
    elif [[ "$ALT_SYNC" != "PASS" && "$ORIG_SYNC" != "PASS" ]]; then
        result_fail "Both models failing"
        advice "Issue is not model-specific. The endpoint itself has problems."
    else
        result_warn "Mixed results between models"
        advice "Check ${STEP9_LOG} for full details."
    fi
    echo -e "  ${DIM}Full log: ${STEP9_LOG}${RESET}"
fi

# =============================================================================
# STEP 10: Keep-alive vs fresh connection
# =============================================================================

if [[ "$QUICK_MODE" == true ]]; then
    header "STEP 10: Keep-alive test -- SKIPPED (--quick mode)"
else
    header "STEP 10: Keep-alive vs fresh connection"
    info "Compares responses using a reused (keep-alive) connection vs"
    info "a fresh connection. Some proxies/LBs behave differently for each."
    echo ""

    STEP10_LOG="$OUTDIR/10-keepalive.txt"

    {
        echo "=== Keep-alive test ==="
        echo ""
    } > "$STEP10_LOG"

    # Test 1: Fresh connection (Connection: close)
    echo -e "  ${DIM}Testing fresh connection (Connection: close)...${RESET}"
    FRESH_RESP=$(curl -sS -w '\n__HTTP_CODE__:%{http_code}\n__TIME_TOTAL__:%{time_total}\n__TIME_STARTTRANSFER__:%{time_starttransfer}\n' \
        --max-time "$TIMEOUT" \
        -H "Authorization: Bearer ${API_KEY}" \
        -H "Content-Type: application/json" \
        -H "Connection: close" \
        -d "$PAYLOAD_SYNC" \
        "$ENDPOINT" 2>>"$STEP10_LOG" || true)

    FRESH_HTTP=$(echo "$FRESH_RESP" | grep '__HTTP_CODE__' | cut -d: -f2 || echo "0")
    FRESH_TTFB=$(echo "$FRESH_RESP" | grep '__TIME_STARTTRANSFER__' | cut -d: -f2 || echo "?")
    FRESH_TIME=$(echo "$FRESH_RESP" | grep '__TIME_TOTAL__' | cut -d: -f2 || echo "?")
    FRESH_BODY=$(echo "$FRESH_RESP" | grep -v '^__' || true)
    FRESH_CONTENT=$(check_content "$FRESH_BODY")

    echo "Fresh: HTTP=${FRESH_HTTP} TTFB=${FRESH_TTFB} Total=${FRESH_TIME} Content=${FRESH_CONTENT}" >> "$STEP10_LOG"

    # Test 2: Reused connection (2 requests in sequence, same curl handle via retry)
    echo -e "  ${DIM}Testing reused connection (keep-alive, 2 requests)...${RESET}"
    KEEPALIVE_LOG="$OUTDIR/10-keepalive-reuse.txt"

    # Use curl with --next to send two requests on the same connection
    # First request warms up the connection, second uses keep-alive
    REUSE_RESP=$(curl -sS -w '\n__HTTP_CODE__:%{http_code}\n__TIME_TOTAL__:%{time_total}\n__TIME_STARTTRANSFER__:%{time_starttransfer}\n' \
        --max-time "$TIMEOUT" \
        -H "Authorization: Bearer ${API_KEY}" \
        -H "Content-Type: application/json" \
        -d "$PAYLOAD_SYNC" \
        "$ENDPOINT" \
        --next \
        -sS -w '\n__HTTP_CODE2__:%{http_code}\n__TIME_TOTAL2__:%{time_total}\n__TIME_STARTTRANSFER2__:%{time_starttransfer}\n' \
        --max-time "$TIMEOUT" \
        -H "Authorization: Bearer ${API_KEY}" \
        -H "Content-Type: application/json" \
        -d "$PAYLOAD_SYNC" \
        "$ENDPOINT" 2>>"$STEP10_LOG" || true)

    REUSE_HTTP=$(echo "$REUSE_RESP" | grep '__HTTP_CODE2__' | cut -d: -f2 || echo "0")
    REUSE_TTFB=$(echo "$REUSE_RESP" | grep '__TIME_STARTTRANSFER2__' | cut -d: -f2 || echo "?")
    REUSE_TIME=$(echo "$REUSE_RESP" | grep '__TIME_TOTAL2__' | cut -d: -f2 || echo "?")
    REUSE_BODY=$(echo "$REUSE_RESP" | grep -v '^__' || true)
    REUSE_CONTENT=$(check_content "$REUSE_BODY")

    echo "Reuse: HTTP=${REUSE_HTTP} TTFB=${REUSE_TTFB} Total=${REUSE_TIME} Content=${REUSE_CONTENT}" >> "$STEP10_LOG"

    # Test 3: Streaming with fresh connection
    echo -e "  ${DIM}Testing streaming with fresh connection...${RESET}"
    FRESH_STREAM_RESP=$(curl -sS -N -w '\n__HTTP_CODE__:%{http_code}\n__SIZE_DOWNLOAD__:%{size_download}\n' \
        --max-time "$TIMEOUT" \
        -H "Authorization: Bearer ${API_KEY}" \
        -H "Content-Type: application/json" \
        -H "Connection: close" \
        -d "$PAYLOAD_STREAM" \
        "$ENDPOINT" 2>/dev/null || true)

    FRESH_STREAM_HTTP=$(echo "$FRESH_STREAM_RESP" | grep '__HTTP_CODE__' | cut -d: -f2 || echo "0")
    FRESH_STREAM_SSE=$(echo "$FRESH_STREAM_RESP" | grep -v '^__' || true)
    FRESH_STREAM_DATA=$(echo "$FRESH_STREAM_SSE" | grep -c '^data: ' || true)
    FRESH_STREAM_HAS_CONTENT=0
    if echo "$FRESH_STREAM_SSE" | grep '^data: ' | grep -v '\[DONE\]' | grep -q '"content"'; then
        FRESH_STREAM_HAS_CONTENT=1
    fi

    echo "" >> "$STEP10_LOG"
    echo "Fresh stream: HTTP=${FRESH_STREAM_HTTP} Data=${FRESH_STREAM_DATA} Content=${FRESH_STREAM_HAS_CONTENT}" >> "$STEP10_LOG"

    echo ""
    printf "  %-25s %-10s %-10s %-10s\n" "Connection Type" "HTTP" "TTFB" "Content"
    printf "  %-25s %-10s %-10s %-10s\n" "-----" "----" "----" "-------"
    printf "  %-25s %-10s %-10s %-10s\n" "Fresh (sync)" "$FRESH_HTTP" "${FRESH_TTFB}s" "$FRESH_CONTENT chars"
    printf "  %-25s %-10s %-10s %-10s\n" "Keep-alive 2nd req (sync)" "$REUSE_HTTP" "${REUSE_TTFB}s" "$REUSE_CONTENT chars"
    printf "  %-25s %-10s %-10s %-10s\n" "Fresh (stream)" "$FRESH_STREAM_HTTP" "-" "${FRESH_STREAM_DATA} events"
    echo ""

    # Check for differences
    FRESH_OK=0
    REUSE_OK=0
    FRESH_STREAM_OK=0
    [[ "$FRESH_HTTP" == "200" && "$FRESH_CONTENT" -gt 0 ]] && FRESH_OK=1
    [[ "$REUSE_HTTP" == "200" && "$REUSE_CONTENT" -gt 0 ]] && REUSE_OK=1
    [[ "$FRESH_STREAM_HTTP" == "200" && "$FRESH_STREAM_DATA" -gt 1 && "$FRESH_STREAM_HAS_CONTENT" -eq 1 ]] && FRESH_STREAM_OK=1

    if [[ "$FRESH_OK" -eq 1 && "$REUSE_OK" -eq 1 && "$FRESH_STREAM_OK" -eq 1 ]]; then
        result_pass "Both connection types work for sync and streaming"
        advice "Connection reuse is not contributing to the issue."
    elif [[ "$FRESH_OK" -eq 1 && "$REUSE_OK" -eq 0 ]]; then
        result_fail "Fresh connection works but keep-alive fails"
        advice "The server or proxy has issues with connection reuse."
        advice "This could cause intermittent failures if httpx reuses connections."
    elif [[ "$FRESH_OK" -eq 0 && "$REUSE_OK" -eq 1 ]]; then
        result_warn "Keep-alive works but fresh connection fails (unusual)"
        advice "Check for connection limits or rate limiting on new connections."
    elif [[ "$FRESH_STREAM_OK" -eq 0 && "$FRESH_OK" -eq 1 ]]; then
        result_fail "Sync works with fresh connection but streaming doesn't"
        advice "Streaming specifically broken with fresh connections. Proxy may be"
        advice "buffering SSE on new connections differently than reused ones."
    else
        result_fail "Connection issues detected"
        advice "Check ${STEP10_LOG} for details."
    fi
    echo -e "  ${DIM}Full log: ${STEP10_LOG}${RESET}"
fi

# =============================================================================
# SUMMARY
# =============================================================================

header "DIAGNOSTIC SUMMARY"
echo ""
echo -e "  All logs saved to: ${BOLD}${OUTDIR}/${RESET}"
echo ""
echo -e "  Files:"
ls -1 "$OUTDIR"/ | sed 's/^/    /'
echo ""

SUMMARY="$OUTDIR/SUMMARY.md"
cat > "$SUMMARY" <<SUMEOF
# Diagnostic Summary -- ${TIMESTAMP}

## Configuration
- Endpoint: ${ENDPOINT}
- Model: ${MODEL}
- Alt model: ${ALT_MODEL:-NONE}
- Timeout: ${TIMEOUT}s
- Server header: ${SERVER_HEADER}
- Cert path: ${CERT_PATH:-NONE}

## Quick Reference

| Step | Test | Log File |
|------|------|----------|
| 1 | Non-streaming curl | 01-sync-request.txt |
| 2 | Streaming curl (+ TTFB analysis) | 02-stream-request.txt |
| 3 | Python httpx (same lib as NEXUS) | 03-httpx-stream.txt |
| 4 | Rapid-fire ${RAPID_COUNT}x + backend header tracking | 04-rapid-fire.txt |
| 5 | TLS/DNS/connectivity | 05-connection-info.txt |
| 6 | Certificate chain + TLS comparison matrix | 06-cert-analysis.txt, 06-tls-matrix.txt |
| 7 | /v1/models health check | 07-models-check.txt |
| 8 | Parallel streaming (${PARALLEL_COUNT}x) | 08-parallel-stream.txt |
| 9 | Alternate model test | 09-alt-model.txt |
| 10 | Keep-alive vs fresh connection | 10-keepalive.txt |

## How to Interpret

### If Step 1 fails (non-streaming):
The server is unreachable or broken. Not a NEXUS issue.
Check DNS, firewall, and server health.

### If Step 1 passes but Step 2 fails (streaming):
**The streaming endpoint is broken.** The server handles non-streaming
requests fine but returns empty SSE streams. This is a server-side bug.
Report to the team managing the LLM deployment.

### If Step 2 TTFB is <50ms:
The response came back too fast for real model inference. A proxy or
cache returned an empty/error response without the request reaching
the actual model. Check proxy logs.

### If Steps 1-2 pass but NEXUS had a blank response:
The issue was transient and resolved between the NEXUS request and
the diagnostic run. Run this script faster next time, or check if
NEXUS's \`raw.jsonl\` (from \`--raw-log\`) shows the empty stream.

### If Step 3 (httpx) fails but Step 2 (curl) passes:
Rare but possible -- could be an httpx/httpcore bug, TLS library
difference, or connection reuse issue. File a bug with httpx.

### If Step 4 shows mixed results:
**Load balancer routing to a bad backend.** Some requests hit healthy
servers, some hit broken ones. Check the backend server header column
to identify which backend is broken. Report to infrastructure team.

### If Step 4 shows all empty:
The model/endpoint is consistently broken right now. Not intermittent.

### If Step 6 detects a TLS inspection proxy:
Your network uses a TLS inspection proxy (e.g., Zscaler, Blue Coat).
These proxies can buffer, truncate, or modify SSE/chunked-transfer
streams. This is a common cause of intermittent streaming failures
in corporate networks. Ask your network team if SSE traffic is
exempted from TLS inspection.

### TLS Comparison Matrix (Step 6):
- All PASS across cert modes -> TLS/cert config is not the issue
- Default FAIL but --insecure PASS -> certificate validation issue
- Custom PASS but default FAIL -> system CA bundle missing corporate CA
- curl PASS but httpx FAIL -> httpx uses a different TLS/cert path
- Stream FAIL but sync PASS -> streaming specifically broken (proxy buffering?)

### If Step 7 shows model not listed:
The model may not be available on all backends. Combined with mixed
Step 4 results, this could explain intermittent failures -- some
backends have the model, others don't.

### If Step 8 shows failures under parallel load:
The server cannot handle concurrent streaming requests. This could
indicate connection pool limits, GPU memory limits, or load balancer
session affinity issues.

### If Step 9 shows alt model works but primary fails:
The issue is specific to the primary model, not the endpoint itself.
The model may be overloaded, misconfigured, or missing from some
backend servers.

### If Step 10 shows keep-alive vs fresh differences:
Connection reuse behavior differs. If keep-alive fails but fresh works
(or vice versa), the proxy/LB may be handling persistent connections
differently. httpx uses connection pooling by default, so keep-alive
issues would affect NEXUS.

## Decision Tree

\`\`\`
Step 1 fails?
  YES -> Server down. Not NEXUS.
  NO  -> Step 2 fails?
           YES -> Streaming broken. Server-side bug.
           NO  -> Step 4 mixed?
                    YES -> Load balancer issue. Check backend header.
                    NO  -> Step 6 shows TLS proxy?
                             YES -> Proxy may buffer SSE. Ask network team.
                             NO  -> Step 8 fails under load?
                                      YES -> Concurrency limit. Server capacity.
                                      NO  -> Transient issue. Run earlier next time.
\`\`\`

## Next Steps
1. If empty responses confirmed: share this directory with infra team
2. Run NEXUS with \`nexus3 --raw-log -V\` to capture the next occurrence
3. Compare NEXUS's \`raw.jsonl\` stream_complete entry with these results
4. If TLS proxy detected: request SSE exemption from network team
5. If load balancer issue: request sticky sessions or backend health checks
SUMEOF

echo -e "  ${BOLD}Interpretation guide:${RESET}"
echo ""
echo -e "  ${DIM}Step 1 fail            ->${RESET} Server unreachable. Not NEXUS."
echo -e "  ${DIM}Step 1 pass, 2 fail    ->${RESET} ${BOLD}Streaming endpoint broken.${RESET} Server-side bug."
echo -e "  ${DIM}Step 2 TTFB <50ms      ->${RESET} ${BOLD}Proxy short-circuited.${RESET} Model never ran."
echo -e "  ${DIM}Steps 1-2 pass         ->${RESET} Issue was transient. Run faster next time."
echo -e "  ${DIM}Step 3 fail, 2 pass    ->${RESET} httpx library issue (very rare)."
echo -e "  ${DIM}Step 4 mixed results   ->${RESET} ${BOLD}Load balancer routing to bad backend.${RESET}"
echo -e "  ${DIM}Step 4 all empty       ->${RESET} Endpoint consistently broken right now."
echo -e "  ${DIM}Step 6 TLS proxy found ->${RESET} ${BOLD}Proxy may buffer/truncate SSE.${RESET}"
echo -e "  ${DIM}Step 6 matrix mismatch ->${RESET} Cert or transport-specific failure."
echo -e "  ${DIM}Step 7 model missing   ->${RESET} Model not available on all backends."
echo -e "  ${DIM}Step 8 parallel fail   ->${RESET} Server can't handle concurrent streams."
echo -e "  ${DIM}Step 9 alt model works ->${RESET} Issue specific to primary model."
echo -e "  ${DIM}Step 10 keepalive diff ->${RESET} Connection reuse issue (proxy/LB)."
echo ""
echo -e "  Full interpretation guide: ${BOLD}${SUMMARY}${RESET}"
echo ""
echo -e "${GREEN}Done.${RESET} Share ${BOLD}${OUTDIR}/${RESET} with your infra team if issues found."
