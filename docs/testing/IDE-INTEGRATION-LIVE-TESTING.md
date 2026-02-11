# IDE Integration Live Testing Plan (Windows)

**Feature:** IDE Integration (VS Code ↔ NEXUS3 via WebSocket MCP)
**Branch:** `feature/ide-integration`
**Plan:** `docs/plans/IDE-INTEGRATION-PLAN.md`

---

## Prerequisites

- Windows 10/11 with VS Code installed (>= 1.85.0)
- Node.js 18+ (`node --version`)
- NEXUS3 repo cloned and on `feature/ide-integration` branch
- Working NEXUS3 virtualenv with `nexus3` alias

---

## Phase 0: Build & Install the VS Code Extension

```powershell
# From the repo root
cd editors\vscode
npm install
npm run build
npm run lint        # Should show zero errors
```

This produces `dist/extension.js`. To install in VS Code:

```powershell
# Option A: Symlink for development (run from elevated PowerShell)
New-Item -ItemType Junction -Path "$env:USERPROFILE\.vscode\extensions\nexus3-ide" -Target "$(Get-Location)\editors\vscode"

# Option B: Copy manually
Copy-Item -Recurse editors\vscode "$env:USERPROFILE\.vscode\extensions\nexus3-ide"
```

After installing, **reload VS Code** (`Ctrl+Shift+P` → "Developer: Reload Window").

---

## Phase 1: Verify Extension Activation

1. Open your NEXUS3 project folder in VS Code
2. Open the Output panel (`Ctrl+Shift+U`) → select "Log (Extension Host)" from dropdown
3. Look for:
   ```
   NEXUS3 IDE integration activating...
   NEXUS3 IDE MCP server listening on 127.0.0.1:<PORT>
   NEXUS3 IDE: server on port <PORT>, lock file: C:\Users\<you>\.nexus3\ide\<PORT>.lock
   ```
4. Verify lock file exists:
   ```powershell
   dir $env:USERPROFILE\.nexus3\ide\
   # Should show <PORT>.lock
   type $env:USERPROFILE\.nexus3\ide\<PORT>.lock
   # Should show JSON with pid, workspaceFolders, authToken
   ```
5. Verify `workspaceFolders` in the lock file matches your open VS Code workspace path

**If no output / no lock file:** Check VS Code version >= 1.85.0, check extension is recognized in Extensions panel.

---

## Phase 2: Verify NEXUS3 Auto-Connect

1. From a terminal **inside the same folder** that VS Code has open:
   ```powershell
   nexus3 --fresh
   ```
2. On startup, look for the dim message:
   ```
   IDE connected: VS Code
   ```
3. Run `/ide` — should show:
   ```
   IDE: connected to VS Code (port <PORT>)
     Workspace: C:\Users\<you>\repos\NEXUS3
     Diagnostics: X errors, Y warnings
     Open editors: N

     auto_connect: True
     use_ide_diffs: True
     inject_diagnostics: True
     inject_open_editors: True
   ```

**If "No IDE found":**
- Verify NEXUS3's CWD matches (or is a subdirectory of) a VS Code workspace folder
- Check lock file exists and has correct workspace path
- Try `/ide connect` manually

---

## Phase 3: Test `/ide` Commands

```
/ide                 # Status (already tested above)
/ide disconnect      # Should say "Disconnected from IDE"
/ide                 # Should say "IDE: not connected"
/ide connect         # Should reconnect and show "Connected to: VS Code (port ...)"
```

---

## Phase 4: Test Diff Confirmations (Core Feature)

This is the main user-facing feature. You need a **trusted** agent (the default for REPL).

1. Make sure you're connected (`/ide` shows connected)
2. Ask the agent to write a file that will trigger a confirmation:
   ```
   Create a file called test_ide_diff.py with a hello world function
   ```
3. **Expected behavior:**
   - VS Code should open a diff tab titled "NEXUS3: test_ide_diff.py"
   - Left side: empty or original content
   - Right side: proposed content from the agent
   - Two buttons in the editor title bar: ✓ (Accept) and ✗ (Reject)
4. Click **Accept (✓)**:
   - File should be written to disk
   - NEXUS3 terminal should continue (the agent sees approval)
   - Check the file exists with correct content
5. Now ask the agent to **edit** that file:
   ```
   Add a docstring to the function in test_ide_diff.py
   ```
6. This time click **Reject (✗)**:
   - Diff tab closes
   - Agent should see the rejection and respond accordingly
7. Test **closing the tab** without clicking either button (X on the tab):
   - Should count as rejection (DIFF_REJECTED)

---

## Phase 5: Test Terminal Fallback

1. Disconnect from IDE: `/ide disconnect`
2. Ask the agent to write a file:
   ```
   Add a comment to test_ide_diff.py
   ```
3. **Expected:** Normal terminal confirmation prompt (not VS Code diff)
4. Approve in terminal, verify it works
5. Reconnect: `/ide connect`

---

## Phase 6: Test Context Injection

1. Open several files in VS Code (3-4 different files)
2. Introduce a deliberate Python syntax error in one file (save it)
3. Ask the agent:
   ```
   What files do I have open in my editor? Are there any errors?
   ```
4. The agent should mention the open tabs and the syntax error from VS Code diagnostics
5. Fix the error, save, then ask again — diagnostics should update

---

## Phase 7: Test Reconnection

1. While NEXUS3 is running and connected, **reload VS Code** (`Ctrl+Shift+P` → "Reload Window")
2. This kills the old WebSocket server and starts a new one (new port, new lock file)
3. Ask the agent to write a file — it should detect the dead connection, reconnect to the new VS Code instance, and show the diff
4. If auto-reconnect fails, `/ide connect` should manually reconnect

---

## Phase 8: Test Edge Cases

1. **Multiple VS Code windows:** Open a second VS Code window with a different folder. Check that NEXUS3 connects to the one whose workspace matches the CWD (longest prefix match).

2. **No VS Code running:** Close all VS Code windows, then start NEXUS3:
   ```powershell
   nexus3 --fresh
   ```
   Should start normally with no IDE connection, no errors. `/ide` shows "not connected".

3. **Config disable:** Add to your config (`.nexus3/config.json` or `~/.nexus3/config.json`):
   ```json
   {"ide": {"enabled": false}}
   ```
   Start NEXUS3 — should show no IDE messages. `/ide` should say "IDE integration is disabled". Remove the config override when done.

4. **Diff for edit_file:** Ask the agent to make a specific string replacement in an existing file. Verify the diff shows only the changed lines highlighted.

---

## Cleanup

```powershell
# Remove test file
del test_ide_diff.py

# Remove extension (if using symlink/junction)
rmdir "$env:USERPROFILE\.vscode\extensions\nexus3-ide"
# Or if copied:
Remove-Item -Recurse "$env:USERPROFILE\.vscode\extensions\nexus3-ide"

# Remove any config overrides you added
# Stale lock files are auto-cleaned by NEXUS3
```

---

## Known Windows Considerations

| Item | Status | Notes |
|------|--------|-------|
| Lock file `mode: 0o600` | No-op on Windows | `fs.writeFileSync` mode is ignored; files use NTFS ACLs |
| `os.kill(pid, 0)` | Works | Python uses `OpenProcess` on Windows |
| Path separators | Handled | `Path.resolve()` and `is_relative_to` use native format |
| `~/.nexus3/ide/` | Works | `Path.home()` → `C:\Users\<user>` |
| WebSocket `127.0.0.1` | Works | Windows Defender may prompt on first run |
