# YOLO Safety Live Testing Guide

## Overview

This guide validates the YOLO Safety improvements implemented in the `feature/windows-native-compat` branch:

1. **YOLO Warning Banner** - Visual reminder every turn
2. **Worker Preset Removal** - Legacy preset completely removed
3. **RPC-to-YOLO Block** - Prevents RPC send to unattended YOLO agents

---

## Prerequisites

```bash
# Ensure you're on the correct branch
git checkout feature/windows-native-compat

# Install dependencies
.venv/bin/pip install -e .
```

---

## Test 1: YOLO Warning Banner

**Purpose:** Verify warning displays on every user turn when in YOLO mode.

### Steps

```bash
# Start REPL with YOLO permissions
nexus3 --fresh
```

1. Change to YOLO mode:
   ```
   /permissions yolo
   ```

2. Send any message:
   ```
   hello
   ```

3. **Expected:** Before the agent responds, you should see:
   ```
   ⚠️  YOLO MODE - All actions execute without confirmation
   ```

4. Send another message and verify the warning appears again.

5. Switch back to trusted mode:
   ```
   /permissions trusted
   ```

6. Send a message - warning should NOT appear.

### Pass Criteria
- [ ] Warning appears on EVERY turn when in YOLO mode
- [ ] Warning does NOT appear when in trusted/sandboxed mode
- [ ] Warning is bold red with emoji

---

## Test 2: RPC Send to YOLO Agent (REPL Connected)

**Purpose:** Verify RPC can send to YOLO agent when REPL is actively connected.

### Steps

1. Start REPL:
   ```bash
   nexus3 --fresh
   ```

2. Create YOLO agent and stay connected:
   ```
   /permissions yolo
   /agent yolo-test --yolo
   ```

3. In another terminal, send via RPC:
   ```bash
   nexus3 rpc send yolo-test "What is 2+2?"
   ```

### Pass Criteria
- [ ] RPC send SUCCEEDS (message is delivered)
- [ ] REPL shows "INCOMING" notification
- [ ] Agent processes the message

---

## Test 3: RPC Send to YOLO Agent (No REPL Connected)

**Purpose:** Verify RPC send is BLOCKED when REPL is not connected to the YOLO agent.

### Steps

1. Start REPL:
   ```bash
   nexus3 --fresh
   ```

2. Create YOLO agent:
   ```
   /agent yolo-test --yolo
   ```

3. Switch to a different agent:
   ```
   /agent main
   ```

4. In another terminal, try RPC send:
   ```bash
   nexus3 rpc send yolo-test "What is 2+2?"
   ```

### Pass Criteria
- [ ] RPC send FAILS with error
- [ ] Error message: `"Cannot send to YOLO agent - no REPL connected"`

---

## Test 4: Worker Preset Removed

**Purpose:** Verify the legacy "worker" preset is completely removed.

### Steps

1. Start REPL:
   ```bash
   nexus3 --fresh
   ```

2. Try to change to worker preset:
   ```
   /permissions worker
   ```

3. **Expected:** Error message indicating unknown preset.

4. Try to create agent with worker preset:
   ```
   /agent test-worker --worker
   ```

5. **Expected:** Error or unknown flag message.

6. Try via RPC:
   ```bash
   nexus3 rpc create test-worker --preset worker
   ```

7. **Expected:** Error indicating invalid preset.

### Pass Criteria
- [ ] `/permissions worker` returns error "Unknown preset"
- [ ] `--worker` flag is not recognized
- [ ] RPC `--preset worker` returns error

---

## Test 5: Connection State Tracking

**Purpose:** Verify connection state updates correctly on agent switches.

### Steps

1. Start REPL:
   ```bash
   nexus3 --fresh
   ```

2. Create two agents:
   ```
   /agent yolo-a --yolo
   /agent yolo-b --yolo
   ```

3. Switch to agent A:
   ```
   /agent yolo-a
   ```

4. In another terminal, test RPC:
   ```bash
   # Should succeed (A is connected)
   nexus3 rpc send yolo-a "test"

   # Should fail (B is not connected)
   nexus3 rpc send yolo-b "test"
   ```

5. Switch to agent B:
   ```
   /agent yolo-b
   ```

6. Test RPC again:
   ```bash
   # Should fail (A is no longer connected)
   nexus3 rpc send yolo-a "test"

   # Should succeed (B is now connected)
   nexus3 rpc send yolo-b "test"
   ```

### Pass Criteria
- [ ] RPC to current agent succeeds
- [ ] RPC to non-current YOLO agent fails
- [ ] Connection state updates on switch

---

## Summary Checklist

| Test | Description | Status |
|------|-------------|--------|
| 1 | YOLO warning banner displays every turn | [ ] |
| 2 | RPC send to connected YOLO agent succeeds | [ ] |
| 3 | RPC send to disconnected YOLO agent fails | [ ] |
| 4 | Worker preset completely removed | [ ] |
| 5 | Connection state tracks agent switches | [ ] |

---

## Troubleshooting

### Warning not appearing
- Check `/permissions` shows YOLO level
- Verify PermissionLevel import in repl.py

### RPC not connecting
- Ensure REPL started server (`nexus3 --fresh` auto-starts)
- Check port (default 8765)

### Tests fail intermittently
- Allow agent time to initialize before RPC
- Use `--timeout` flag for RPC commands

---

## After Testing

Once all tests pass:

1. Mark P7 as complete in CLAUDE.md
2. Commit with message: `test: verify YOLO safety features (live testing)`
3. Ready for merge to main
