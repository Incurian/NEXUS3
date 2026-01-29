# Windows Troubleshooting Guide

## Requirements

- Windows 10 or later (Windows 11 recommended)
- Windows Terminal or PowerShell 7+ (for proper ANSI support)
- Python 3.10+ from python.org (not Microsoft Store version)

## Common Issues

### ESC Key Not Working

**Symptom:** Pressing ESC doesn't cancel in-progress requests.

**Causes and fixes:**
1. **Using legacy cmd.exe**: Switch to Windows Terminal or PowerShell 7+
2. **ConPTY not available**: Ensure Windows 10 build 17763+ (October 2018 Update)

### Console Output Garbled

**Symptom:** Strange characters like `[32m` appearing in output.

**Causes and fixes:**
1. **Legacy Windows console**: Set `legacy_windows=False` is default in NEXUS3 - use Windows Terminal
2. **Old PowerShell**: Update to PowerShell 7+ or use Windows Terminal

### Subprocess Windows Flashing

**Symptom:** Brief cmd.exe windows appearing during git/bash operations.

**Status:** Fixed in v3.x - subprocess CREATE_NO_WINDOW flag is now applied.

### Line Endings Issues

**Symptom:** Files have mixed or wrong line endings after editing.

**Status:** Fixed in v3.x - NEXUS3 now detects and preserves original line endings (CRLF/LF).

**Workaround for older versions:**
```bash
# Configure git to handle line endings
git config --global core.autocrlf true
```

### Process Not Terminating

**Symptom:** Child processes remain after timeout or ESC.

**Status:** Fixed in v3.x - Uses `taskkill /T /F` for reliable process tree termination.

**Manual cleanup:**
```powershell
# Find and kill orphaned processes
Get-Process python | Where-Object {$_.MainWindowTitle -eq ""} | Stop-Process
```

### Permission Errors

**Symptom:** "Access denied" when reading/writing files.

**Common causes:**
1. **Antivirus interference**: Add NEXUS3 and Python to exclusions
2. **File in use**: Close other editors/processes
3. **System files**: NEXUS3 cannot modify protected system files

### Config File BOM Issues

**Symptom:** JSON parse error on config files created in Notepad.

**Status:** Fixed in v3.x - NEXUS3 now handles UTF-8 BOM automatically.

**For older versions:** Save config files as "UTF-8" not "UTF-8 with BOM" in your editor.

## Shell-Specific Troubleshooting

Different Windows shells have different capabilities. NEXUS3 detects your shell and adapts automatically, but some issues are shell-specific.

### Detecting Your Shell

Run this to see what shell NEXUS3 detects:

```bash
.venv/bin/python -c "
from nexus3.core.shell_detection import detect_windows_shell, supports_ansi, supports_unicode, check_console_codepage
shell = detect_windows_shell()
print(f'Detected shell: {shell}')
print(f'Supports ANSI: {supports_ansi()}')
print(f'Supports Unicode: {supports_unicode()}')
codepage, is_utf8 = check_console_codepage()
print(f'Console codepage: {codepage} (UTF-8: {is_utf8})')
"
```

### CMD.exe Issues

**Symptom:** Output shows plain text without colors or formatting.

**Cause:** CMD.exe does not support ANSI escape sequences. NEXUS3 detects this and uses legacy mode automatically.

**Solutions:**
1. **Best:** Use Windows Terminal instead (free from Microsoft Store)
2. **Alternative:** Use PowerShell 7+ which has better ANSI support
3. **Workaround:** If you must use CMD.exe, the plain text output is functional but less readable

**Symptom:** Unicode characters show as `?` or boxes.

**Cause:** CMD.exe default code page doesn't support Unicode box drawing.

**Solutions:**
1. Run `chcp 65001` before starting NEXUS3 to switch to UTF-8
2. Use Windows Terminal which defaults to UTF-8

### PowerShell 5.1 Issues

**Symptom:** ANSI escape sequences visible as `[32m` etc.

**Cause:** PowerShell 5.1 has limited ANSI support outside Windows Terminal.

**Solutions:**
1. **Best:** Upgrade to PowerShell 7+ (`winget install Microsoft.PowerShell`)
2. **Alternative:** Use Windows Terminal which wraps PowerShell with proper ANSI
3. **Workaround:** Set `$env:TERM = "dumb"` to force plain text mode

### Git Bash (MSYS2) Issues

**Symptom:** Windows paths like `C:\Users\foo` converted to `/c/Users/foo`.

**Cause:** MSYS2 automatic path conversion (intended for Unix tool compatibility).

**Solutions:**
1. Disable path conversion for specific commands: `MSYS2_ARG_CONV_EXCL="*" command`
2. Use forward slashes: `C:/Users/foo` (works in most Windows tools)
3. Use quotes around paths: `"C:\Users\foo"`

**Symptom:** SSL certificate errors when connecting to APIs.

**Cause:** Git Bash uses its own certificate store, not Windows.

**Solutions:**
1. Set `ssl_ca_cert` in config to point to Git's CA bundle:
   ```json
   {"provider": {"ssl_ca_cert": "C:/Program Files/Git/mingw64/ssl/certs/ca-bundle.crt"}}
   ```
2. Or set environment variable: `SSL_CERT_FILE=/c/Program Files/Git/mingw64/ssl/certs/ca-bundle.crt`

### Windows Terminal Issues

**Symptom:** Colors or Unicode not working in Windows Terminal.

**Cause:** Rare - Windows Terminal has excellent ANSI/Unicode support.

**Solutions:**
1. Ensure Windows Terminal is up to date
2. Check terminal profile settings (Settings > Defaults > Appearance)
3. Verify the shell inside Terminal is correctly detected (run detection script above)

### Shell Detection Wrong

If NEXUS3 detects the wrong shell:

**Symptom:** Getting plain text when colors should work, or ANSI garbage when they shouldn't.

**Debugging:**
1. Check environment variables:
   ```powershell
   echo WT_SESSION=$env:WT_SESSION MSYSTEM=$env:MSYSTEM PSModulePath=$env:PSModulePath COMSPEC=$env:COMSPEC
   ```
2. Detection order: WT_SESSION > MSYSTEM > PSModulePath > COMSPEC

**Workaround:** Force a specific mode by setting environment variables before starting NEXUS3:
- For full ANSI: `$env:WT_SESSION = "forced"`
- For legacy mode: Clear all detection vars and set only COMSPEC

### Shell Capability Reference

| Shell | ANSI Colors | Unicode | UTF-8 Default | Notes |
|-------|-------------|---------|---------------|-------|
| Windows Terminal | Yes | Yes | Yes | Best experience |
| PowerShell 7+ | Yes | Yes | Yes | Good experience |
| PowerShell 5.1 | No* | Partial | No | *Yes inside Windows Terminal |
| Git Bash | Yes | Yes | Yes | MSYS2 path conversion issues |
| CMD.exe | No | No | No | Plain text fallback |

## Known Limitations

These are documented platform differences, not bugs:

| Issue | Description | Workaround |
|-------|-------------|------------|
| File permissions | `os.chmod()` is limited on Windows | Rely on folder-level ACLs |
| Symlink detection | Junction points not detected as symlinks | Use actual symlinks |
| Token file security | RPC token may be readable by other users | Restrict home directory permissions |

## Performance Tips

1. **Windows Defender**: Add `.nexus3` folder and Python to exclusions
2. **Windows Search**: Exclude project directories from indexing
3. **Real-time scanning**: Disable for development directories

## Getting Help

1. Check this guide first
2. Review `docs/WINDOWS-NATIVE-COMPATIBILITY.md` for technical details
3. File issues at: https://github.com/your-repo/nexus3/issues
