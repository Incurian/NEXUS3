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
