# Fix Plan: Source Attribution Persistence + Incoming Notifications (Post-SSE Removal)

This replaces the previous plan. It addresses the newly discovered problems:
- `Message.meta` exists in memory but is **not persisted** to `session.db` and is **not displayed** in `context.md`.
- Incoming-turn notifications currently do not fire for source-less RPC sends.

Design goals:
- Minimal changes, no re-architecture.
- Preserve existing message model and tool-call grouping.
- Make attribution durable (DB + markdown) and visible.

---

## Phase 1: Persist `meta` end-to-end (schema migration + storage + logger + markdown)

### Files to modify
- `nexus3/session/storage.py`
- `nexus3/session/logging.py`
- `nexus3/context/manager.py`
- `nexus3/session/markdown.py`

### Exact changes

#### 1) Add `meta` column to SQLite schema

In `nexus3/session/storage.py`:

1) Bump schema version:
```diff
- SCHEMA_VERSION = 2
+ SCHEMA_VERSION = 3
```

2) Add `meta` column to the `messages` table in `SCHEMA`:
```diff
 CREATE TABLE IF NOT EXISTS messages (
     id INTEGER PRIMARY KEY AUTOINCREMENT,
     role TEXT NOT NULL,
     content TEXT NOT NULL,
+    meta TEXT,
     name TEXT,
     tool_call_id TEXT,
     tool_calls TEXT,
     tokens INTEGER,
     timestamp REAL NOT NULL,
     in_context INTEGER DEFAULT 1,
     summary_of TEXT
 );
```

3) Add migration 2 → 3:

Locate `_migrate(self, from_version: int, to_version: int)`.
Add a new block after the existing `from_version < 2` migration:

```py
if from_version < 3 <= to_version:
    # Migration 2 -> 3: Add meta column to messages table
    try:
        conn.execute("ALTER TABLE messages ADD COLUMN meta TEXT")
    except sqlite3.OperationalError:
        # Column may already exist (defensive)
        pass
    conn.execute("UPDATE schema_version SET version = ?", (3,))
    conn.commit()
```

Notes:
- `sqlite3` is already imported at top of file.
- This is safe for existing DBs.

#### 2) Teach storage layer to write/read meta

In `nexus3/session/storage.py`:

1) Extend `MessageRow` dataclass to include `meta`:
```diff
 @dataclass
 class MessageRow:
@@
     role: str
     content: str
+    meta: dict[str, Any] | None
     name: str | None
@@
```

2) Update `MessageRow.from_row()` to decode JSON:
```py
meta = None
if "meta" in row.keys() and row["meta"]:
    raw_meta = row["meta"]
    if len(raw_meta) <= MAX_JSON_FIELD_SIZE:
        try:
            meta = json.loads(raw_meta)
        except (json.JSONDecodeError, TypeError):
            meta = None
```

Then include it in the return value.

3) Extend `insert_message(...)` to accept `meta` and write it:

```diff
 def insert_message(
     self,
     role: str,
     content: str,
     *,
+    meta: dict[str, Any] | None = None,
     name: str | None = None,
     tool_call_id: str | None = None,
     tool_calls: list[dict[str, Any]] | None = None,
     tokens: int | None = None,
     timestamp: float | None = None,
 ) -> int:
@@
-    tool_calls_json = json.dumps(tool_calls) if tool_calls else None
+    tool_calls_json = json.dumps(tool_calls) if tool_calls else None
+    meta_json = json.dumps(meta) if meta else None
@@
-    INSERT INTO messages (role, content, name, tool_call_id, tool_calls, tokens, timestamp)
-    VALUES (?, ?, ?, ?, ?, ?, ?)
+    INSERT INTO messages (role, content, meta, name, tool_call_id, tool_calls, tokens, timestamp)
+    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
@@
-    (role, content, name, tool_call_id, tool_calls_json, tokens, ts),
+    (role, content, meta_json, name, tool_call_id, tool_calls_json, tokens, ts),
```

#### 3) Plumb meta through SessionLogger

In `nexus3/session/logging.py`:

```diff
- def log_user(self, content: str) -> int:
+ def log_user(self, content: str, meta: dict[str, Any] | None = None) -> int:
@@
     msg_id = self.storage.insert_message(
         role="user",
         content=content,
+        meta=meta,
         timestamp=time(),
     )
-    self._md_writer.write_user(content)
+    self._md_writer.write_user(content, meta=meta)
     return msg_id
```

#### 4) Pass meta from ContextManager into logger

In `nexus3/context/manager.py`:

```diff
 def add_user_message(self, content: str, meta: dict[str, Any] | None = None) -> None:
@@
     self._messages.append(msg)
     if self._logger:
-        self._logger.log_user(content)
+        self._logger.log_user(content, meta=meta)
```

Also update `add_session_start_message()` to keep behavior the same (no meta):
- it can keep calling `log_user(start_msg.content)`.

#### 5) Render meta in context.md (source attribution display)

In `nexus3/session/markdown.py`, update `write_user`:

```diff
- def write_user(self, content: str) -> None:
+ def write_user(self, content: str, meta: dict[str, Any] | None = None) -> None:
     """Write user message to context.md."""
     timestamp = self._format_timestamp()
-    md = f"## User [{timestamp}]\n\n{content}\n\n"
+    label = "User"
+    if meta:
+        src_agent = meta.get("source_agent_id")
+        src = meta.get("source")
+        if src_agent:
+            # Example: User (from trustedguy via nexus_send)
+            if src:
+                label = f"User (from {src_agent} via {src})"
+            else:
+                label = f"User (from {src_agent})"
+        elif src and src != "repl":
+            label = f"User ({src})"
+    md = f"## {label} [{timestamp}]\n\n{content}\n\n"
     self._append(self.context_path, md)
```

This will make receiver logs show attribution, e.g.:
- `## User (from trustedguy via nexus_send) [17:00:21]`
- `## User (rpc) [..]`

### What to test after this phase
1) **DB migration works**:
   - Start REPL, create/send messages, then open `session.db` and confirm:
     - `PRAGMA table_info(messages);` includes `meta`.
     - rows for user messages include JSON meta when source is present.
2) **context.md shows attribution**:
   - Send to an agent via `nexus_send` with `source_agent_id` and confirm header shows “from <agent> via nexus_send”.

---

## Phase 2: Fire incoming-turn hook for source-less sends

### Files to modify
- `nexus3/rpc/dispatcher.py`

### Exact changes

Right now the hook is gated by:

```py
if source and source != "repl":
    ...
```

Change it to treat missing source as external/incoming.

Minimal patch:

```diff
- # Notify REPL when this is an incoming (non-repl) message
- if source and source != "repl":
+ # Notify REPL when this is an incoming (non-repl) message
+ # Treat missing source as "rpc" for visibility.
+ if source != "repl":
+     if not source:
+         source = "rpc"
      preview = (content[:80] + "...") if len(content) > 80 else content
      await self._notify_incoming({
          "phase": "started",
          "request_id": request_id,
          "source": source,
          "source_agent_id": source_agent_id,
          "preview": preview,
      })
@@
- # Notify REPL of completion
- if source and source != "repl":
+ # Notify REPL of completion
+ if source != "repl":
+     if not source:
+         source = "rpc"
      preview = (full[:80] + "...") if len(full) > 80 else full
      await self._notify_incoming({
          "phase": "ended",
          "request_id": request_id,
          "ok": True,
          "content_preview": preview,
      })
@@
- except asyncio.CancelledError:
-     if source and source != "repl":
+ except asyncio.CancelledError:
+     if source != "repl":
+         if not source:
+             source = "rpc"
          await self._notify_incoming({
              "phase": "ended",
              "request_id": request_id,
              "ok": False,
              "cancelled": True,
          })
      return {"cancelled": True, "request_id": request_id}
```

Behavior:
- `nexus3 rpc send subagent "..."` now triggers incoming-start/done lines in the REPL.
- REPL-originated sends (which set `user_meta={"source":"repl"}`) remain excluded.

### What to test after this phase
1) Start REPL on agent A.
2) From another terminal: `nexus3 rpc send A "hello"`.
3) Confirm REPL shows incoming notification labeled `(rpc)`.

---

## Phase 3: Test verification steps (minimal but complete)

### What to test

#### A) Source attribution end-to-end
1) In REPL (trustedguy), create subagent `.1`.
2) Have trustedguy call `nexus_send(agent_id=".1", content="ping")`.
3) Verify in `.1`’s `context.md`:
   - User header is `User (from trustedguy via nexus_send)`.
4) Verify in `.1`’s `session.db`:
   - message row has `meta` JSON containing `source=nexus_send` and `source_agent_id=trustedguy`.

#### B) Incoming notification visibility
1) With REPL connected to `.1` (or whichever current agent), run:
   - `nexus3 rpc send .1 "Test message from CLI"`
2) Confirm REPL prints:
   - `○ incoming: ...` (started)
   - `● incoming done: ...` (ended)

#### C) No regression in normal streaming
1) Send a normal prompt in REPL.
2) Confirm:
   - streaming is smooth
   - cancellation still works
   - tool gumballs still render

#### D) History/tool-call “collapse” expectations
- Confirm `context.md` still shows:
  - assistant tool call section
  - tool result section
- If the user wants an explicit “request/response” summary beyond tool call JSON, implement as a **markdown formatting improvement** (not a storage change).

