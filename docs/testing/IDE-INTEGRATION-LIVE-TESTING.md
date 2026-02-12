# IDE Integration Live Testing Plan (Windows)

**Feature:** IDE Integration (VS Code ↔ NEXUS3 via WebSocket MCP)
**Branch:** `feature/ide-integration`
**Plan:** `docs/plans/IDE-INTEGRATION-PLAN.md`

---

## Prerequisites

- Windows 10/11 with VS Code installed (>= 1.85.0)
- Node.js 18+ installed and available in PowerShell (`node --version`, `npm --version`)
  - If not installed: `winget install OpenJS.NodeJS.LTS` then **reopen PowerShell**
- NEXUS3 repo cloned and on `feature/ide-integration` branch
- Working NEXUS3 virtualenv with `nexus3` alias

---

## Phase 0: Build & Install the VS Code Extension

### Important: Cross-Filesystem npm Issues

**Windows npm cannot run `npm install` on WSL filesystem paths** (via `\\wsl.localhost\...`). It fails with `EISDIR` errors because Linux symlinks in `node_modules/.bin/` are incompatible with Windows. You must copy the extension source to a native Windows path first.

### Build Steps

```powershell
# Copy extension source to a native Windows path (skipping any existing node_modules)
robocopy \\wsl.localhost\Ubuntu\home\inc\repos\NEXUS3\editors\vscode C:\temp\nexus3-vscode /E /XD node_modules

# Build from the Windows-native copy
cd C:\temp\nexus3-vscode
npm install
npm run build       # Should produce dist/extension.js
npm run lint        # Should show zero errors, zero output
```

> **If `npm` is not recognized:** Install Node.js first with `winget install OpenJS.NodeJS.LTS`, then close and reopen PowerShell so the PATH update takes effect.
>
> **If you change extension source in WSL:** Re-copy the changed files before rebuilding:
> ```powershell
> # Copy just the changed file (e.g., package.json)
> Copy-Item \\wsl.localhost\Ubuntu\home\inc\repos\NEXUS3\editors\vscode\package.json C:\temp\nexus3-vscode\package.json
> cd C:\temp\nexus3-vscode
> npm install && npm run build
> ```

### Install into VS Code

Copy the **built** extension (from `C:\temp\nexus3-vscode`, NOT from the WSL path) into VS Code's extensions directory:

```powershell
# From C:\temp\nexus3-vscode (the directory you just built in)
Copy-Item -Recurse C:\temp\nexus3-vscode "$env:USERPROFILE\.vscode\extensions\nexus3-ide"
```

> **Common mistake:** Don't use a relative path like `editors\vscode` — that's relative to the repo root. Use the full `C:\temp\nexus3-vscode` path since that's where you built.

After installing, **reload VS Code** (`Ctrl+Shift+P` → "Developer: Reload Window").

---

## Phase 1: Verify Extension Activation

1. Open your project folder in VS Code

2. Check the **Developer Tools console** (NOT the Output panel):
   - `Ctrl+Shift+P` → "Developer: Toggle Developer Tools"
   - Click the **Console** tab
   - Look for these three lines:
     ```
     [Extension Host] NEXUS3 IDE integration activating...
     [Extension Host] NEXUS3 IDE MCP server listening on 127.0.0.1:<PORT>
     [Extension Host] NEXUS3 IDE: server on port <PORT>, lock file: C:\Users\<you>\.nexus3\ide\<PORT>.lock
     ```

   > **Note:** The Output panel's "Log (Extension Host)" channel shows VS Code framework messages like `ExtensionService#_doActivateExtension nexus3.nexus3-ide`, but the extension's own `console.log` output appears in Developer Tools instead.

3. Verify lock file exists:
   ```powershell
   dir $env:USERPROFILE\.nexus3\ide\
   # Should show a .lock file named with the port number (e.g., 64451.lock)
   ```

4. Read the lock file (replace `<PORT>` with the actual port from step 2):
   ```powershell
   type $env:USERPROFILE\.nexus3\ide\64451.lock
   ```
   Should show JSON with `pid`, `workspaceFolders`, `ideName`, `authToken`.

5. Note the `workspaceFolders` value:
   - If VS Code opened a **local Windows folder**: `C:\Users\...`
   - If VS Code opened a **WSL folder**: `\\wsl.localhost\Ubuntu\home\...`

**If no output / no lock file:** Check VS Code version >= 1.85.0, check extension is recognized in Extensions panel (search "nexus3").

---

## Phase 2: Verify NEXUS3 Auto-Connect

### WSL ↔ Windows Cross-OS Setup

If you run NEXUS3 in WSL but VS Code on Windows (common setup), discovery works automatically:
- NEXUS3 in WSL scans **both** `~/.nexus3/ide/` (Linux) and the Windows user's `~/.nexus3/ide/` (via `/mnt/c/Users/<you>/.nexus3/ide/`)
- UNC workspace paths like `\\wsl.localhost\Ubuntu\home\...` are translated to Linux paths `/home/...`
- Windows PIDs are validated via `powershell.exe` interop

### Test Auto-Connect

1. From a terminal **whose CWD is within the VS Code workspace**:
   ```bash
   # WSL
   nexus3 --fresh
   # Or PowerShell
   nexus3 --fresh
   ```
2. On startup, look for the dim message:
   ```
   IDE connected: VS Code
   ```
3. Run `/ide` — should show:
   ```
   IDE: connected to VS Code (port <PORT>)
     Workspace: <workspace path>
     Diagnostics: X errors, Y warnings
     Open editors: N

     auto_connect: True
     use_ide_diffs: True
     inject_diagnostics: True
     inject_open_editors: True
   ```

**If "No IDE found":**
- Verify NEXUS3's CWD matches (or is a subdirectory of) a VS Code workspace folder
- Check lock file exists: `ls ~/.nexus3/ide/` (Linux) or `ls /mnt/c/Users/$USER/.nexus3/ide/` (WSL checking Windows)
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
   ```bash
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

# Remove extension
Remove-Item -Recurse "$env:USERPROFILE\.vscode\extensions\nexus3-ide"

# Remove build directory
Remove-Item -Recurse C:\temp\nexus3-vscode

# Remove any config overrides you added
# Stale lock files are auto-cleaned by NEXUS3
```

---

## Known Windows/WSL Considerations

| Item | Status | Notes |
|------|--------|-------|
| Lock file `mode: 0o600` | No-op on Windows | `fs.writeFileSync` mode is ignored; files use NTFS ACLs |
| Cross-filesystem npm | **Fails** | Cannot `npm install` on `\\wsl.localhost\...` paths — copy to `C:\temp\` first |
| WSL ↔ Windows discovery | Works | NEXUS3 in WSL scans Windows lock dir via `/mnt/c/`, translates UNC paths |
| Windows PID validation from WSL | Works | Uses `powershell.exe` interop (falls back to "assume alive" if unavailable) |
| UNC workspace paths | Translated | `\\wsl.localhost\Ubuntu\home\...` → `/home/...` automatically |
| Path separators | Handled | `Path.resolve()` and `is_relative_to` use native format |
| WebSocket `127.0.0.1` | Works | WSL2 can reach Windows localhost; Windows Defender may prompt on first run |
| Extension `console.log` | Developer Tools | Use `Ctrl+Shift+P` → "Developer: Toggle Developer Tools" → Console tab (NOT Output panel) |
