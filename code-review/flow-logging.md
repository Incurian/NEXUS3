# Code Review: Logging Flow

**Reviewer:** Claude Opus 4.5
**Date:** 2026-01-08
**Files Reviewed:**
- `/home/inc/repos/NEXUS3/nexus3/session/logging.py`
- `/home/inc/repos/NEXUS3/nexus3/session/storage.py`
- `/home/inc/repos/NEXUS3/nexus3/session/markdown.py`
- `/home/inc/repos/NEXUS3/nexus3/session/types.py`
- `/home/inc/repos/NEXUS3/nexus3/session/session.py`
- `/home/inc/repos/NEXUS3/nexus3/context/manager.py`

---

## Executive Summary

The logging system in NEXUS3 is well-architected with clear separation of concerns between SQLite storage, Markdown generation, and raw API logging. The three-stream model (CONTEXT, VERBOSE, RAW) provides good flexibility. However, there are several issues ranging from missing encoding specifications to potential performance bottlenecks and incomplete event capture.

**Overall Assessment:** Good foundation with room for improvement in robustness and completeness.

---

## 1. Log Event Capture Completeness

### Issues Found

#### 1.1 Missing Token Logging in Assistant Messages

**Location:** `/home/inc/repos/NEXUS3/nexus3/session/session.py:183-187` and `/home/inc/repos/NEXUS3/nexus3/context/manager.py:129-130`

**Severity:** Medium

**Description:** When `log_assistant()` is called from `ContextManager.add_assistant_message()`, the `tokens` parameter is never passed:

```python
# context/manager.py:129-130
if self._logger:
    self._logger.log_assistant(content, tool_calls)  # tokens is never passed!
```

The `log_assistant()` method accepts an optional `tokens` parameter, but it's never utilized in the actual integration points. Token counts from the API response are not being captured.

**Recommendation:** Pass token counts from the provider's `StreamComplete` event through to the logging layer.

---

#### 1.2 Thinking Content Not Captured in Tool Execution Loop

**Location:** `/home/inc/repos/NEXUS3/nexus3/session/session.py:221-248`

**Severity:** Medium

**Description:** During the tool execution loop in `_execute_tool_loop_streaming()`, `ReasoningDelta` events are processed for callback notifications, but the actual thinking content is discarded:

```python
if isinstance(event, ReasoningDelta):
    # Notify callback when reasoning starts
    if not is_reasoning and self.on_reasoning:
        self.on_reasoning(True)
    is_reasoning = True
    # The actual reasoning text from event is never captured!
```

The reasoning/thinking text is never accumulated or logged.

**Recommendation:** Accumulate thinking content and pass it to `log_assistant()` via the `thinking` parameter.

---

#### 1.3 No Error Event Logging

**Location:** `/home/inc/repos/NEXUS3/nexus3/session/logging.py`

**Severity:** Low

**Description:** There is no `log_error()` method for capturing errors that occur during session operation. Errors in skill execution are captured as tool results, but provider errors, network failures, or other session-level errors have no dedicated logging path.

**Recommendation:** Add `log_error(error_type, message, metadata)` method to capture session-level errors in the events table.

---

#### 1.4 Missing Cancel Event Logging

**Location:** `/home/inc/repos/NEXUS3/nexus3/session/session.py:100-120`

**Severity:** Low

**Description:** When tools are cancelled via `add_cancelled_tools()`, the cancellation is recorded as a tool result, but there is no explicit cancellation event in the verbose log. This makes it harder to analyze session behavior when reviewing logs.

**Recommendation:** Add `log_cancellation()` to record when and why cancellation occurred.

---

## 2. SQLite Schema and Queries

### Issues Found

#### 2.1 No Transaction Wrapping for Related Operations

**Location:** `/home/inc/repos/NEXUS3/nexus3/session/storage.py:252-271`

**Severity:** Medium

**Description:** The `mark_as_summary()` method performs two separate operations that should be atomic:

```python
def mark_as_summary(self, summary_id: int, replaced_ids: list[int]) -> None:
    conn = self._get_conn()

    # Operation 1: Update summary message
    conn.execute(
        "UPDATE messages SET summary_of = ? WHERE id = ?",
        (summary_of, summary_id),
    )

    # Operation 2: Mark replaced messages
    self.update_context_status(replaced_ids, in_context=False)  # Commits separately!
```

If the application crashes between these operations, the database could be left in an inconsistent state.

**Recommendation:** Wrap related operations in an explicit transaction:
```python
with conn:  # Context manager provides transaction
    conn.execute(...)
    conn.execute(...)
```

---

#### 2.2 Commit After Every Insert

**Location:** `/home/inc/repos/NEXUS3/nexus3/session/storage.py:204-212`, `320-330`

**Severity:** Medium (Performance)

**Description:** Both `insert_message()` and `insert_event()` call `conn.commit()` after every single insert:

```python
def insert_message(...) -> int:
    cursor = conn.execute(...)
    conn.commit()  # Commits after EVERY insert
    return cursor.lastrowid
```

During a conversation with many tool calls, this results in numerous disk syncs. SQLite commits are expensive operations.

**Recommendation:** Consider a batch commit strategy or use WAL mode:
```python
# In _ensure_schema():
self._conn.execute("PRAGMA journal_mode=WAL")
```

---

#### 2.3 Missing Index for Common Query Pattern

**Location:** `/home/inc/repos/NEXUS3/nexus3/session/storage.py:49-53`

**Severity:** Low

**Description:** There is an index on `messages(in_context)`, but the most common query pattern is:
```sql
SELECT * FROM messages WHERE in_context = 1 ORDER BY id
```

A covering index would be more efficient:
```sql
CREATE INDEX idx_messages_context_order ON messages(in_context, id);
```

---

#### 2.4 No Vacuum or Maintenance Strategy

**Location:** `/home/inc/repos/NEXUS3/nexus3/session/storage.py`

**Severity:** Low

**Description:** Long-running sessions with many compaction cycles (marking messages as out of context) will accumulate deleted rows. There is no automatic `VACUUM` or `PRAGMA auto_vacuum` setting.

**Recommendation:** Consider enabling auto_vacuum:
```python
self._conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
```

---

## 3. Markdown Formatting

### Issues Found

#### 3.1 Fixed Truncation Length Without User Control

**Location:** `/home/inc/repos/NEXUS3/nexus3/session/markdown.py:99-101`

**Severity:** Low

**Description:** Tool result output is truncated at a hardcoded 2000 characters:

```python
if len(content) > 2000:
    content = content[:2000] + "\n... (truncated)"
```

This may be too short for some use cases (e.g., large file reads) and too long for others.

**Recommendation:** Make truncation configurable via `LogConfig` or `MarkdownWriter` constructor.

---

#### 3.2 No Escaping of Markdown Special Characters

**Location:** `/home/inc/repos/NEXUS3/nexus3/session/markdown.py:59-88`

**Severity:** Medium

**Description:** User and assistant content is written directly without escaping Markdown special characters:

```python
def write_user(self, content: str) -> None:
    md = f"## User [{timestamp}]\n\n{content}\n\n"  # content not escaped
    self._append(self.context_path, md)
```

If user input contains Markdown syntax (e.g., `# Heading` or `**bold**`), it will be rendered as formatting rather than literal text. More critically, if content contains triple backticks, it could break code block formatting.

**Recommendation:** Consider escaping or using HTML entities for special characters in user content, or wrap all content in fenced code blocks.

---

#### 3.3 Timestamp Inconsistency Between SQLite and Markdown

**Location:** `/home/inc/repos/NEXUS3/nexus3/session/markdown.py:51-55` vs `/home/inc/repos/NEXUS3/nexus3/session/logging.py:82`

**Severity:** Low

**Description:** SQLite uses `time()` (Unix timestamp float), while Markdown uses `datetime.now()`. These could theoretically differ if called at different times:

```python
# logging.py
msg_id = self.storage.insert_message(..., timestamp=time())
self._md_writer.write_user(content)  # Uses datetime.now() internally
```

**Recommendation:** Pass the same timestamp to both storage and writer methods.

---

#### 3.4 Tool Arguments Pretty-Printed But May Be Large

**Location:** `/home/inc/repos/NEXUS3/nexus3/session/markdown.py:81-85`

**Severity:** Low

**Description:** Tool call arguments are JSON-dumped with indentation:

```python
args_str = json.dumps(args, indent=2)
md += f"**{name}**\n```json\n{args_str}\n```\n\n"
```

For tools with large arguments (e.g., file content), this could produce massive, unreadable Markdown sections.

**Recommendation:** Truncate large argument values or implement a summary view.

---

## 4. File Handling and Encoding

### Issues Found

#### 4.1 Missing Explicit Encoding on File Operations

**Location:** `/home/inc/repos/NEXUS3/nexus3/session/markdown.py:46-49`, `241-243`

**Severity:** High

**Description:** File operations do not specify encoding:

```python
def _append(self, path: Path, content: str) -> None:
    with path.open("a") as f:  # No encoding specified!
        f.write(content)

def _append_jsonl(self, entry: dict[str, Any]) -> None:
    with self.raw_path.open("a") as f:  # No encoding specified!
        f.write(json.dumps(entry) + "\n")
```

This violates the project's own SOP: "Always `encoding='utf-8', errors='replace'`". On Windows or systems with non-UTF-8 default encodings, this could cause UnicodeEncodeError or produce corrupted files.

**Recommendation:** Add explicit encoding to all file operations:
```python
with path.open("a", encoding="utf-8", errors="replace") as f:
```

---

#### 4.2 Initial File Creation Also Missing Encoding

**Location:** `/home/inc/repos/NEXUS3/nexus3/session/markdown.py:37`, `44`

**Severity:** High

**Description:** Initial file creation uses `write_text()` without encoding:

```python
self.context_path.write_text(header)  # No encoding!
self.verbose_path.write_text(header)  # No encoding!
```

**Recommendation:** Use `write_text(header, encoding="utf-8")`.

---

#### 4.3 No File Locking or Atomic Writes

**Location:** `/home/inc/repos/NEXUS3/nexus3/session/markdown.py:46-49`

**Severity:** Low

**Description:** Markdown files are opened in append mode without any locking. In multi-agent scenarios where agents might share a parent logger, concurrent writes could interleave.

**Recommendation:** Either document that each agent must have its own logger (already the case in AgentPool), or add file locking for the nested subagent case.

---

## 5. Performance Implications

### Issues Found

#### 5.1 Synchronous File I/O in Async Context

**Location:** `/home/inc/repos/NEXUS3/nexus3/session/logging.py:77-161`

**Severity:** Medium

**Description:** All logging methods (e.g., `log_user()`, `log_assistant()`) perform synchronous SQLite and file I/O. When called from async context (which is the normal case in NEXUS3), this blocks the event loop:

```python
async for chunk in session.send(user_input):
    # When this completes, log_assistant() is called synchronously
    # blocking the event loop during disk I/O
```

For interactive REPL use, this is likely acceptable. For high-throughput server scenarios, it could cause latency spikes.

**Recommendation:** Consider using `asyncio.to_thread()` for I/O-bound operations, or use aiosqlite for async database access.

---

#### 5.2 Repeated Message Building

**Location:** `/home/inc/repos/NEXUS3/nexus3/session/logging.py:242-268`

**Severity:** Low

**Description:** `get_context_messages()` rebuilds the entire message list from SQLite every time it's called, including JSON parsing and ToolCall object construction:

```python
def get_context_messages(self) -> list[Message]:
    rows = self.storage.get_messages(in_context_only=True)
    messages: list[Message] = []
    for row in rows:
        # JSON parsing and object construction for every message
```

This is called during context building but the result is not cached.

**Recommendation:** Consider caching the result and invalidating on message insertion.

---

#### 5.3 Markdown File Growth

**Location:** `/home/inc/repos/NEXUS3/nexus3/session/markdown.py`

**Severity:** Low

**Description:** Markdown files grow indefinitely with each logged message. For long sessions, `context.md` could become very large, making it slow to open and review.

**Recommendation:** Consider log rotation or splitting into multiple files after a size threshold.

---

## 6. Error Handling in Logging

### Issues Found

#### 6.1 No Error Handling on File Operations

**Location:** `/home/inc/repos/NEXUS3/nexus3/session/markdown.py:46-49`

**Severity:** High

**Description:** File append operations have no error handling:

```python
def _append(self, path: Path, content: str) -> None:
    with path.open("a") as f:
        f.write(content)  # Could raise IOError, disk full, etc.
```

If the disk is full or the file is locked, this will raise an exception that propagates up to the session, potentially crashing the agent.

**Recommendation:** Add try/except with appropriate handling (log warning, continue operation, or fail gracefully).

---

#### 6.2 SQLite Operations Not Wrapped in Error Handling

**Location:** `/home/inc/repos/NEXUS3/nexus3/session/storage.py:204-212`

**Severity:** Medium

**Description:** SQLite insertions can fail (disk full, corruption, etc.) but exceptions are not caught:

```python
def insert_message(...) -> int:
    cursor = conn.execute(...)  # Could raise sqlite3.Error
    conn.commit()  # Could raise sqlite3.Error
    return cursor.lastrowid
```

While the fail-fast principle is good for development, production systems should handle storage failures gracefully.

**Recommendation:** Add error handling that either:
- Logs the error and returns a sentinel value
- Re-raises with more context
- Falls back to in-memory operation

---

#### 6.3 JSON Serialization Can Fail

**Location:** `/home/inc/repos/NEXUS3/nexus3/session/storage.py:201`, `/home/inc/repos/NEXUS3/nexus3/session/markdown.py:84`

**Severity:** Low

**Description:** `json.dumps()` is called without handling potential serialization failures:

```python
tool_calls_json = json.dumps(tool_calls) if tool_calls else None
```

If tool_calls contains non-serializable objects (unlikely but possible), this will raise.

**Recommendation:** Add a fallback with `default=str` or explicit type checking.

---

## 7. Subagent Nesting Support

### Issues Found

#### 7.1 Child Logger Uses Parent's Session Directory as Base

**Location:** `/home/inc/repos/NEXUS3/nexus3/session/logging.py:281-288`

**Severity:** Low (Design Consideration)

**Description:** When creating a child logger, the parent's `session_dir` becomes the child's `base_dir`:

```python
def create_child_logger(self, name: str | None = None) -> SessionLogger:
    child_config = LogConfig(
        base_dir=self.info.session_dir,  # Parent's session_dir, not base_dir
        streams=self.config.streams,
        parent_session=self.info.session_id,
    )
```

This creates the correct nesting structure, but the `name` parameter is accepted but never used.

**Recommendation:** Either use the `name` parameter in the folder name or remove it from the signature.

---

#### 7.2 Subagent ID Generation Could Collide

**Location:** `/home/inc/repos/NEXUS3/nexus3/session/types.py:64-71`

**Severity:** Low

**Description:** Subagent directories use only 6 hex characters:

```python
suffix = token_hex(3)  # 6 hex chars
session_id = f"{timestamp}_{mode}_{suffix}"

if parent_id:
    session_dir = base_dir / f"subagent_{suffix}"  # Only suffix, no timestamp
```

With 16 million possible values, collision is unlikely but not impossible for long-running sessions with many subagents.

**Recommendation:** Consider including a counter or using the full session_id for subagent directories.

---

#### 7.3 No Parent Link Persistence in Child Database

**Location:** `/home/inc/repos/NEXUS3/nexus3/session/logging.py:44-47`

**Severity:** Low

**Description:** Parent ID is stored in metadata, which is correct:

```python
if self.info.parent_id:
    self.storage.set_metadata("parent_id", self.info.parent_id)
```

However, there is no reciprocal tracking - the parent session has no record of its children. This makes it harder to reconstruct the full session tree from logs.

**Recommendation:** Add `log_child_session(child_id, child_dir)` method to parent logger.

---

## 8. Additional Issues

#### 8.1 RawLogCallbackAdapter Has No Tests for Edge Cases

**Location:** `/home/inc/repos/NEXUS3/nexus3/session/logging.py:309-349`

**Severity:** Low

**Description:** The `RawLogCallbackAdapter` class bridges the provider to the logger, but tests don't cover error cases (e.g., what happens if the logger is closed when a callback is invoked).

---

#### 8.2 LogStream.ALL May Include Too Much

**Location:** `/home/inc/repos/NEXUS3/nexus3/session/types.py:21`

**Severity:** Low (Design Consideration)

**Description:** `LogStream.ALL` is used as the default in several places:

```python
ALL = CONTEXT | VERBOSE | RAW
# ...
streams: LogStream = LogStream.ALL  # All streams on by default for now
```

For production use, RAW logging should probably be opt-in only, as it can produce very large files.

---

#### 8.3 No Log Retention Policy

**Location:** N/A

**Severity:** Low

**Description:** There is no mechanism to clean up old session logs. The `.nexus3/logs` directory will grow indefinitely over time.

**Recommendation:** Consider adding a log retention configuration (max age, max size, max sessions).

---

## Summary of Recommendations

### High Priority
1. Add explicit `encoding='utf-8', errors='replace'` to all file operations
2. Add error handling for file I/O operations
3. Pass token counts through to logging layer

### Medium Priority
4. Wrap related SQLite operations in transactions
5. Capture thinking/reasoning content during tool execution loop
6. Consider async I/O for high-throughput scenarios
7. Escape Markdown special characters in user content
8. Use WAL mode for better SQLite performance

### Low Priority
9. Add configurable truncation length for tool results
10. Add `log_error()` and `log_cancellation()` methods
11. Add covering index for common query patterns
12. Implement log rotation for large sessions
13. Use or remove the `name` parameter in `create_child_logger()`
14. Add log retention policy

---

## Test Coverage Assessment

The test file `/home/inc/repos/NEXUS3/tests/unit/test_session_logging.py` is comprehensive (1118 lines) and covers:
- All LogStream flag combinations
- LogConfig construction and defaults
- SessionInfo creation and subagent nesting
- SessionStorage CRUD operations
- MarkdownWriter formatting
- RawWriter JSONL output
- SessionLogger integration

**Missing test coverage:**
- Error handling when disk is full
- Concurrent access patterns
- Very long content truncation edge cases
- Unicode/encoding edge cases
- Database migration paths

---

## Conclusion

The logging system is well-designed and follows good architectural principles. The separation between SQLite storage (source of truth), Markdown output (human-readable), and raw JSON logging (debugging) is clean and extensible.

The most critical issues are the missing encoding specifications on file operations, which violate the project's own SOPs and could cause issues on Windows systems. The error handling gaps in file and database operations are also concerning for production reliability.

The system would benefit from performance optimizations for server mode (async I/O, batch commits) and better capture of all session events (thinking content, tokens, errors).
