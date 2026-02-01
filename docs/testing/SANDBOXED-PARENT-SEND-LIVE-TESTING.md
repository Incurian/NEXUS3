# Sandboxed Parent Send Live Testing Guide

## Overview

This guide validates the sandboxed parent send feature: **sandboxed agents can use `nexus_send` but only to their parent agent**.

The feature allows child agents to report results back without breaking the security sandbox.

**Key behaviors to verify:**
1. Sandboxed child can send messages to parent
2. Sandboxed child CANNOT send to siblings or other agents
3. Root sandboxed agent (no parent) CANNOT send to anyone
4. Error messages clearly explain restrictions

---

## Prerequisites

```bash
# Ensure you're on the correct branch
git checkout feature/sandboxed-parent-send  # or wherever the feature is

# Install dependencies
.venv/bin/pip install -e .

# Run unit tests first to catch obvious issues
.venv/bin/pytest tests/unit/session/test_enforcer.py -v -k "target"
.venv/bin/pytest tests/unit/core/test_presets.py -v -k "allowed_targets"
```

---

## Test 1: Sandboxed Child Reports to Parent

**Purpose:** Verify a sandboxed child agent can successfully send messages to its parent.

### Steps

1. Start REPL:
   ```bash
   nexus3 --fresh
   ```

2. Create a trusted parent agent:
   ```
   /create parent --trusted
   /agent parent
   ```

3. Have the parent create a sandboxed child with an initial task:
   ```
   Use nexus_create to create a sandboxed child agent named "worker" with an initial message asking it to "Count to 3 and report back to me using nexus_send"
   ```

4. Wait for the child to process and attempt to send back to parent.

5. Check if parent received the message:
   ```
   /agent parent
   What messages have you received?
   ```

### Expected Output

- Child agent successfully created
- Child agent calls `nexus_send` targeting "parent"
- `nexus_send` succeeds (no error)
- Parent agent's context contains the child's message

### Pass Criteria
- [ ] `nexus_create` with `initial_message` works for sandboxed agent
- [ ] Child's `nexus_send` to parent returns success (no error)
- [ ] Parent can see/receive the message from child

---

## Test 2: Sandboxed Child Cannot Send to Sibling

**Purpose:** Verify a sandboxed child agent CANNOT send messages to a sibling agent.

### Steps

1. Start REPL (or continue from Test 1):
   ```bash
   nexus3 --fresh
   ```

2. Create parent and two children:
   ```
   /create parent --trusted
   /agent parent
   ```

3. Have parent create two sandboxed children:
   ```
   Use nexus_create to create two sandboxed agents: "child1" and "child2"
   ```

4. Send a task to child1 to message child2:
   ```
   /send child1 "Try to send a message to agent 'child2' using nexus_send. Tell it hello."
   ```

5. Observe the error response.

### Expected Output

```
Tool 'nexus_send' can only target parent agent ('parent')
```

### Pass Criteria
- [ ] `nexus_send` from child1 to child2 is **rejected**
- [ ] Error message clearly states "can only target parent agent"
- [ ] Error message includes the parent's ID ('parent')

---

## Test 3: Root Sandboxed Cannot Send

**Purpose:** Verify a standalone sandboxed agent (no parent) cannot send to any agent.

### Steps

1. Start headless server in one terminal:
   ```bash
   NEXUS_DEV=1 .venv/bin/python -m nexus3 --serve 9000 &
   ```

2. Create a standalone sandboxed agent via RPC:
   ```bash
   .venv/bin/python -m nexus3 rpc create lonely --preset sandboxed --port 9000
   ```

3. Create another agent to be a target:
   ```bash
   .venv/bin/python -m nexus3 rpc create target --preset trusted --port 9000
   ```

4. Send a task to the lonely agent to message someone:
   ```bash
   .venv/bin/python -m nexus3 rpc send lonely "Try to send a message to agent 'target' using nexus_send" --port 9000 --timeout 120
   ```

5. Observe the error in the response.

### Expected Output

```
Tool 'nexus_send' can only target parent agent ('none')
```

### Pass Criteria
- [ ] `nexus_send` from lonely to any agent is **rejected**
- [ ] Error message says "can only target parent agent ('none')"
- [ ] The `('none')` indicates no parent exists

### Cleanup

```bash
.venv/bin/python -m nexus3 rpc destroy lonely --port 9000
.venv/bin/python -m nexus3 rpc destroy target --port 9000
.venv/bin/python -m nexus3 rpc shutdown --port 9000
```

---

## Test 4: Error Message Clarity

**Purpose:** Verify error messages are helpful and include relevant context.

### Steps

Test various failure scenarios and verify error messages:

#### 4a. Child targets non-existent agent

1. Start REPL:
   ```bash
   nexus3 --fresh
   ```

2. Create parent and child:
   ```
   /create parent --trusted
   /agent parent
   Create a sandboxed child agent named "worker"
   ```

3. Have child try to send to non-existent agent:
   ```
   /send worker "Use nexus_send to send a message to agent 'nonexistent'"
   ```

4. **Expected:** Error should be about targeting (not about agent not found)
   ```
   Tool 'nexus_send' can only target parent agent ('parent')
   ```

#### 4b. Verify error includes actual parent ID

1. Create agents with specific names:
   ```
   /create coordinator --trusted
   /agent coordinator
   Create a sandboxed agent named "task-worker"
   ```

2. Have task-worker try to send to wrong agent:
   ```
   /send task-worker "Use nexus_send to send to agent 'other'"
   ```

3. **Expected:** Error should show the correct parent ID:
   ```
   Tool 'nexus_send' can only target parent agent ('coordinator')
   ```

### Pass Criteria
- [ ] Error messages include parent agent ID when applicable
- [ ] Error messages say `('none')` when no parent exists
- [ ] Error messages are actionable (tell user what IS allowed)

---

## Test 5: Nested Parent-Child Chain

**Purpose:** Verify parent restriction works correctly in nested hierarchies.

### Steps

1. Start REPL:
   ```bash
   nexus3 --fresh
   ```

2. Create a chain: grandparent -> parent -> child
   ```
   /create grandparent --trusted
   /agent grandparent
   Create a trusted agent named "parent"
   ```

3. Switch to parent and create sandboxed child:
   ```
   /agent parent
   Create a sandboxed agent named "child"
   ```

4. Have child try to send to grandparent:
   ```
   /send child "Use nexus_send to send a message to agent 'grandparent'"
   ```

5. **Expected:** Should fail - child's parent is "parent", not "grandparent"

6. Have child send to its actual parent:
   ```
   /send child "Use nexus_send to send a message to agent 'parent'"
   ```

7. **Expected:** Should succeed

### Pass Criteria
- [ ] Child CANNOT send to grandparent (not its direct parent)
- [ ] Child CAN send to parent (its direct parent)
- [ ] Error message for grandparent shows "can only target parent agent ('parent')"

---

## Summary Checklist

| Test | Description | Status |
|------|-------------|--------|
| 1 | Sandboxed child can send to parent | [ ] |
| 2 | Sandboxed child cannot send to sibling | [ ] |
| 3 | Root sandboxed agent cannot send to anyone | [ ] |
| 4a | Error message shows target restriction | [ ] |
| 4b | Error message includes actual parent ID | [ ] |
| 5 | Nested hierarchy respects direct parent only | [ ] |

---

## Troubleshooting

### Child agent not created

- Check parent is trusted (only trusted agents can create children)
- Verify `nexus_create` is in parent's available tools
- Check server logs for errors: `tail -f .nexus3/logs/server.log`

### nexus_send tool not available to sandboxed agent

- Verify the sandboxed preset was updated:
  ```python
  # In nexus3/core/presets.py
  "nexus_send": ToolPermission(enabled=True, allowed_targets="parent")
  ```
- Check `/status worker --tools` shows nexus_send as enabled

### Messages not appearing in parent context

- Use `/status parent --tokens` to check context size
- Send a message to parent asking what it has received
- Check if the nexus_send returned success (not an error)

### "Agent not found" error instead of permission error

- The enforcer should check target restrictions BEFORE the skill checks if agent exists
- If you see "Agent not found", the enforcer check may not be wired up correctly
- Verify `_check_target_allowed()` is called in `check_all()` method

### Server not responding to RPC

- Ensure server is running: `.venv/bin/python -m nexus3 rpc detect --port 9000`
- Check correct port (default 8765, tests use 9000)
- Restart server if needed

### Tests pass but feature doesn't work in REPL

- Integration tests mock certain components
- Always live test after passing integration tests
- Check logs for permission enforcement: `tail -f .nexus3/logs/server.log`

---

## Expected Error Message Reference

| Scenario | Expected Error |
|----------|----------------|
| Child sends to sibling | `Tool 'nexus_send' can only target parent agent ('{parent_id}')` |
| Child sends to unrelated agent | `Tool 'nexus_send' can only target parent agent ('{parent_id}')` |
| Root sandboxed sends to anyone | `Tool 'nexus_send' can only target parent agent ('none')` |
| Child sends to parent | (no error - succeeds) |

---

## After Testing

Once all tests pass:

1. Mark P5 as complete in the implementation checklist
2. Proceed to P6 (Documentation) if not already done
3. Commit with message: `test: verify sandboxed-parent-send live (P5.1-P5.2)`
4. Ready for merge after full checklist completion + user sign-off
