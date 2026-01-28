# Windows Compatibility Live Testing Guide

Manual testing procedures to validate Windows-native compatibility features including process termination, ESC key detection, line ending preservation, file attributes, error sanitization, and subprocess handling.

**Branch:** `feature/windows-native-compat`
**Date:** 2026-01-28

---

## Prerequisites

```bash
# Ensure you're on the right branch
git checkout feature/windows-native-compat

# Activate virtualenv
source .venv/bin/activate  # Unix/WSL
# OR
.venv\Scripts\activate     # Windows cmd
# OR
.venv\Scripts\Activate.ps1 # Windows PowerShell

# Verify tests pass first
.venv/bin/pytest tests/unit/core/test_process.py -v --tb=short
.venv/bin/pytest tests/unit/skill/test_file_info.py -v --tb=short
```

---

## Part 1: Process Termination Utility

### 1.1 Unix Process Group Termination

Test that subprocesses and their children are properly terminated.

```bash
# Create a process that spawns children
.venv/bin/python -c "
import asyncio
import sys

async def test():
    # Start a process that spawns a child (sleep)
    if sys.platform == 'win32':
        proc = await asyncio.create_subprocess_shell(
            'ping -n 60 localhost',
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    else:
        proc = await asyncio.create_subprocess_shell(
            'sleep 60 & sleep 60',
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )

    print(f'Started process PID: {proc.pid}')
    await asyncio.sleep(1)

    # Terminate using our utility
    from nexus3.core.process import terminate_process_tree
    await terminate_process_tree(proc)

    print(f'Process terminated, return code: {proc.returncode}')
    assert proc.returncode is not None, 'Process should be terminated'

asyncio.run(test())
"

# Expected: Process terminated successfully with non-None return code
```

### 1.2 Windows taskkill Fallback

On Windows, verify taskkill is used for stubborn processes.

```powershell
# Windows PowerShell
.venv\Scripts\python.exe -c "
import asyncio
import subprocess

async def test():
    # Start a process
    proc = await asyncio.create_subprocess_exec(
        'ping', '-n', '60', 'localhost',
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    print(f'Started process PID: {proc.pid}')

    from nexus3.core.process import terminate_process_tree
    await terminate_process_tree(proc)

    print(f'Process terminated, return code: {proc.returncode}')

asyncio.run(test())
"
```

### 1.3 Already-Terminated Process

```bash
.venv/bin/python -c "
import asyncio
from nexus3.core.process import terminate_process_tree

async def test():
    # Start and immediately wait for a fast process
    proc = await asyncio.create_subprocess_exec(
        'echo', 'hello',
        stdout=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    print(f'Process already done: {proc.returncode}')

    # This should not raise
    await terminate_process_tree(proc)
    print('terminate_process_tree handled already-terminated process')

asyncio.run(test())
"

# Expected: No errors, graceful handling
```

---

## Part 2: ESC Key Detection

### 2.1 Unix Terminal Detection

```bash
# Test ESC key detection on Unix (requires interactive terminal)
.venv/bin/python -c "
import sys
print(f'Platform: {sys.platform}')

if sys.platform != 'win32':
    try:
        import termios, tty
        print('termios available - ESC key detection will use Unix method')
    except ImportError:
        print('termios NOT available')
else:
    try:
        import msvcrt
        print('msvcrt available - ESC key detection will use Windows method')
    except ImportError:
        print('msvcrt NOT available')
"
```

### 2.2 Windows msvcrt Detection

```powershell
# Windows PowerShell - Test msvcrt availability
.venv\Scripts\python.exe -c "
import msvcrt
print('msvcrt module loaded successfully')
print(f'kbhit available: {hasattr(msvcrt, \"kbhit\")}')
print(f'getwch available: {hasattr(msvcrt, \"getwch\")}')
"

# Expected: All True
```

### 2.3 Live REPL ESC Test

```bash
# Start NEXUS3 REPL
nexus3 --fresh

# In the REPL:
# 1. Send a message that takes a while to process
# 2. Press ESC during response generation
# 3. Verify the response is cancelled

# Example message to trigger long response:
# > Write a 500-word essay about the history of computing
# > [Press ESC while it's generating]
# Expected: Response cancelled, prompt returns
```

---

## Part 3: BOM Handling

### 3.1 Create BOM-Prefixed Config Files

```bash
# Create test files with BOM
mkdir -p /tmp/bom-test/.nexus3

# Create config.json with UTF-8 BOM
printf '\xef\xbb\xbf{"default_model": "haiku"}\n' > /tmp/bom-test/.nexus3/config.json

# Create NEXUS.md with UTF-8 BOM
printf '\xef\xbb\xbf# Test NEXUS.md\n\nThis file has a BOM.\n' > /tmp/bom-test/.nexus3/NEXUS.md

# Verify BOM is present
hexdump -C /tmp/bom-test/.nexus3/config.json | head -1
# Expected: 00000000  ef bb bf 7b 22 64 65 66  61 75 6c 74 5f 6d 6f 64  |...{"default_mod|
```

### 3.2 Load BOM Config

```bash
cd /tmp/bom-test
.venv/bin/python -c "
from nexus3.config.loader import load_config
from pathlib import Path

config = load_config(Path('.'))
print(f'Config loaded successfully: {config}')
print(f'default_model: {config.default_model}')
"

# Expected: Config loads without errors, no BOM in values
```

### 3.3 Load BOM Context

```bash
.venv/bin/python -c "
from nexus3.context.loader import ContextLoader
from pathlib import Path

loader = ContextLoader()
context = loader.load(Path('/tmp/bom-test'))
print(f'Context loaded: {len(context.system_prompt)} chars')
print(f'First 50 chars: {repr(context.system_prompt[:50])}')
# Should NOT start with BOM bytes
"

# Expected: No \ufeff or BOM characters in output
```

---

## Part 4: Environment Variables

### 4.1 Verify Windows Env Vars in Safe List

```bash
.venv/bin/python -c "
from nexus3.skill.builtin.env import SAFE_ENV_VARS

windows_vars = ['USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'PATHEXT', 'SYSTEMROOT', 'COMSPEC']
for var in windows_vars:
    status = 'PRESENT' if var in SAFE_ENV_VARS else 'MISSING'
    print(f'{var}: {status}')
"

# Expected: All 6 vars should be PRESENT
```

### 4.2 Test Safe Env Building

```bash
.venv/bin/python -c "
from nexus3.skill.builtin.env import get_safe_env
import os

# Set a test secret (should NOT be passed)
os.environ['SECRET_API_KEY'] = 'super-secret'
os.environ['OPENROUTER_API_KEY'] = 'also-secret'

env = get_safe_env('/tmp')
print('Safe env built successfully')

# Check secrets are NOT included
assert 'SECRET_API_KEY' not in env, 'SECRET_API_KEY should not be in safe env'
assert 'OPENROUTER_API_KEY' not in env, 'API keys should not be in safe env'

# Check safe vars ARE included (if set)
if 'PATH' in os.environ:
    assert 'PATH' in env, 'PATH should be in safe env'
    print(f'PATH included: {env[\"PATH\"][:50]}...')

print('Environment isolation verified!')
"
```

### 4.3 Platform-Aware DEFAULT_PATH

```bash
.venv/bin/python -c "
import sys
from nexus3.skill.builtin.env import DEFAULT_PATH

print(f'Platform: {sys.platform}')
print(f'DEFAULT_PATH: {DEFAULT_PATH}')

if sys.platform == 'win32':
    assert 'Windows' in DEFAULT_PATH, 'Should have Windows path on Windows'
else:
    assert '/usr' in DEFAULT_PATH, 'Should have Unix path on Unix'
"
```

---

## Part 5: Line Ending Preservation

### 5.1 Test detect_line_ending Utility

```bash
.venv/bin/python -c "
from nexus3.core.paths import detect_line_ending

# Test CRLF detection
assert detect_line_ending('line1\r\nline2\r\n') == '\r\n', 'Should detect CRLF'

# Test LF detection
assert detect_line_ending('line1\nline2\n') == '\n', 'Should detect LF'

# Test CR detection (legacy Mac)
assert detect_line_ending('line1\rline2\r') == '\r', 'Should detect CR'

# Test empty defaults to LF
assert detect_line_ending('') == '\n', 'Empty should default to LF'

# Test mixed (CRLF wins if present)
assert detect_line_ending('line1\r\nline2\n') == '\r\n', 'CRLF should win if present'

print('All line ending detection tests passed!')
"
```

### 5.2 Edit File Preserves CRLF

```bash
# Create test file with CRLF
mkdir -p /tmp/line-ending-test
printf 'line1\r\nline2\r\nline3\r\n' > /tmp/line-ending-test/crlf.txt

# Verify CRLF
hexdump -C /tmp/line-ending-test/crlf.txt
# Expected: 0d 0a between lines

# Test edit_file preserves CRLF
.venv/bin/python -c "
import asyncio
from pathlib import Path
from nexus3.skill.builtin.edit_file import EditFileSkill
from nexus3.skill.container import ServiceContainer
from nexus3.core.types import ToolResult

async def test():
    container = ServiceContainer(
        cwd=Path('/tmp/line-ending-test'),
        permission_level='YOLO',
    )
    skill = EditFileSkill(container)

    result = await skill.execute(
        path='/tmp/line-ending-test/crlf.txt',
        old_string='line2',
        new_string='MODIFIED',
    )
    print(f'Edit result: {result}')

    # Verify CRLF preserved
    content = Path('/tmp/line-ending-test/crlf.txt').read_bytes()
    print(f'File bytes: {content}')

    assert b'\r\n' in content, 'CRLF should be preserved'
    assert b'MODIFIED\r\n' in content, 'New content should have CRLF'
    print('CRLF preservation verified!')

asyncio.run(test())
"
```

### 5.3 Append File Uses Correct Line Ending

```bash
# Create CRLF file
printf 'existing\r\ncontent' > /tmp/line-ending-test/append.txt

.venv/bin/python -c "
import asyncio
from pathlib import Path
from nexus3.skill.builtin.append_file import AppendFileSkill
from nexus3.skill.container import ServiceContainer

async def test():
    container = ServiceContainer(
        cwd=Path('/tmp/line-ending-test'),
        permission_level='YOLO',
    )
    skill = AppendFileSkill(container)

    result = await skill.execute(
        path='/tmp/line-ending-test/append.txt',
        content='new line',
        newline=True,
    )
    print(f'Append result: {result}')

    content = Path('/tmp/line-ending-test/append.txt').read_bytes()
    print(f'File bytes: {content}')

    # Should have CRLF before 'new line' since original was CRLF
    # Note: This depends on implementation - check actual behavior
    print('Append completed - verify line ending manually')

asyncio.run(test())
"
```

---

## Part 6: Windows File Attributes

### 6.1 Test Attribute Detection (Windows Only)

```powershell
# Windows PowerShell
# Create test file with attributes
$testFile = "C:\Temp\attr-test.txt"
"test content" | Out-File $testFile
attrib +R $testFile  # Set Read-only

.venv\Scripts\python.exe -c "
import asyncio
from pathlib import Path
from nexus3.skill.builtin.file_info import FileInfoSkill
from nexus3.skill.container import ServiceContainer

async def test():
    container = ServiceContainer(
        cwd=Path('C:/Temp'),
        permission_level='YOLO',
    )
    skill = FileInfoSkill(container)
    result = await skill.execute(path='C:/Temp/attr-test.txt')
    print(result.output)
    # Expected: permissions field shows 'R---' (Read-only set)

asyncio.run(test())
"

# Cleanup
attrib -R $testFile
del $testFile
```

### 6.2 Test Unix Permission Format (Unix Only)

```bash
# Unix/WSL
touch /tmp/attr-test.txt
chmod 755 /tmp/attr-test.txt

.venv/bin/python -c "
import asyncio
from pathlib import Path
from nexus3.skill.builtin.file_info import FileInfoSkill
from nexus3.skill.container import ServiceContainer

async def test():
    container = ServiceContainer(
        cwd=Path('/tmp'),
        permission_level='YOLO',
    )
    skill = FileInfoSkill(container)
    result = await skill.execute(path='/tmp/attr-test.txt')
    print(result.output)
    # Expected: permissions field shows 'rwxr-xr-x'

asyncio.run(test())
"

rm /tmp/attr-test.txt
```

### 6.3 Platform Detection

```bash
.venv/bin/python -c "
import sys
print(f'Platform: {sys.platform}')
print(f'Will use: {\"Windows RHSA attributes\" if sys.platform == \"win32\" else \"Unix rwx permissions\"}')
"
```

---

## Part 7: Error Path Sanitization

### 7.1 Unix Path Sanitization

```bash
.venv/bin/python -c "
from nexus3.core.errors import sanitize_error_for_agent

# Test Unix path
result = sanitize_error_for_agent('Error: /home/alice/.nexus3/secrets.txt not found')
print(f'Input:  Error: /home/alice/.nexus3/secrets.txt not found')
print(f'Output: {result}')
assert '[user]' in result, 'Username should be sanitized'
"
```

### 7.2 Windows Path Sanitization

```bash
.venv/bin/python -c "
from nexus3.core.errors import sanitize_error_for_agent

test_cases = [
    # (input, expected_substring)
    ('Error in C:\\\\Users\\\\alice\\\\project', '[user]'),
    ('Error in C:/Users/alice/project', '[user]'),
    ('Config at C:\\\\Users\\\\bob\\\\AppData\\\\Local', 'AppData'),
    ('Access denied: \\\\\\\\fileserver\\\\projects', '[server]'),
    ('Access denied: //fileserver/projects', '[server]'),
    ('DOMAIN\\\\alice denied access', '[domain]'),
]

for input_str, expected in test_cases:
    result = sanitize_error_for_agent(input_str)
    print(f'Input:  {input_str}')
    print(f'Output: {result}')
    assert expected in result or '[user]' in result, f'Expected {expected} in result'
    print()

print('All Windows path sanitization tests passed!')
"
```

### 7.3 Mixed Path Test

```bash
.venv/bin/python -c "
from nexus3.core.errors import sanitize_error_for_agent

# Error with both Unix and Windows paths (edge case)
input_str = 'Tried /home/alice/file and C:\\\\Users\\\\bob\\\\file'
result = sanitize_error_for_agent(input_str)
print(f'Input:  {input_str}')
print(f'Output: {result}')
# Both should be sanitized
"
```

---

## Part 8: Subprocess Window Handling

### 8.1 Verify CREATE_NO_WINDOW Flag

```bash
.venv/bin/python -c "
import subprocess
import sys

print(f'Platform: {sys.platform}')

if sys.platform == 'win32':
    print(f'CREATE_NEW_PROCESS_GROUP: {subprocess.CREATE_NEW_PROCESS_GROUP}')
    print(f'CREATE_NO_WINDOW: {subprocess.CREATE_NO_WINDOW}')
    combined = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    print(f'Combined flags: {combined}')
else:
    print('Unix - uses start_new_session=True instead')
"
```

### 8.2 Test Bash Skill Subprocess (No Window Flash)

```powershell
# Windows PowerShell - verify no cmd.exe window appears
.venv\Scripts\python.exe -c "
import asyncio
from pathlib import Path
from nexus3.skill.builtin.bash import BashSafeSkill
from nexus3.skill.container import ServiceContainer

async def test():
    container = ServiceContainer(
        cwd=Path('.'),
        permission_level='YOLO',
    )
    skill = BashSafeSkill(container)
    result = await skill.execute(command='echo Hello from subprocess')
    print(f'Result: {result.output}')
    print('No window should have appeared!')

asyncio.run(test())
"
```

### 8.3 VT100 Console Mode

```bash
.venv/bin/python -c "
from nexus3.display.console import console

print(f'Console force_terminal: {console.force_terminal}')
print(f'Console legacy_windows: {console.legacy_windows}')
# Expected: force_terminal=True, legacy_windows=False

# Test ANSI sequence
print('\033[32mThis should be green\033[0m')
print('\033[1mThis should be bold\033[0m')
"
```

---

## Part 9: Git Skill Async Subprocess

### 9.1 Basic Git Command

```bash
cd /tmp
mkdir -p git-test && cd git-test
git init

.venv/bin/python -c "
import asyncio
from pathlib import Path
from nexus3.skill.builtin.git import GitSkill
from nexus3.skill.container import ServiceContainer

async def test():
    container = ServiceContainer(
        cwd=Path('/tmp/git-test'),
        permission_level='TRUSTED',
    )
    skill = GitSkill(container)
    result = await skill.execute(command='status')
    print(f'Git status result:')
    print(result.output)

asyncio.run(test())
"

rm -rf /tmp/git-test
```

### 9.2 Git with Timeout

```bash
.venv/bin/python -c "
import asyncio
from pathlib import Path
from nexus3.skill.builtin.git import GitSkill, GIT_TIMEOUT
from nexus3.skill.container import ServiceContainer

print(f'Git timeout configured: {GIT_TIMEOUT}s')

async def test():
    container = ServiceContainer(
        cwd=Path('.'),
        permission_level='TRUSTED',
    )
    skill = GitSkill(container)
    # This should complete quickly
    result = await skill.execute(command='--version')
    print(f'Git version: {result.output}')

asyncio.run(test())
"
```

---

## Part 10: REPL Integration Testing

### 10.1 Start NEXUS3 on Windows

```powershell
# Windows PowerShell
.venv\Scripts\python.exe -m nexus3 --fresh

# In the REPL, test:
# 1. ESC key cancellation
# 2. File operations with CRLF files
# 3. Git commands
# 4. Process termination on Ctrl+C
```

### 10.2 Start NEXUS3 on Unix

```bash
nexus3 --fresh

# In the REPL, test:
# 1. ESC key cancellation
# 2. File operations
# 3. Git commands
# 4. Process termination
```

### 10.3 Test File Operations in REPL

```
# In REPL:

# Create a test file
Use write_file to create /tmp/repl-test.txt with content "line1\nline2\nline3"

# Read it back
Use read_file to read /tmp/repl-test.txt

# Edit it
Use edit_file to replace "line2" with "MODIFIED" in /tmp/repl-test.txt

# Verify
Use read_file to read /tmp/repl-test.txt
```

---

## Part 11: Python API Testing

### 11.1 Process Termination API

```bash
.venv/bin/python
```

```python
import asyncio
from nexus3.core.process import terminate_process_tree, GRACEFUL_TIMEOUT

print(f"GRACEFUL_TIMEOUT: {GRACEFUL_TIMEOUT}s")

async def test_api():
    # Start a long-running process
    proc = await asyncio.create_subprocess_shell(
        "sleep 60" if __import__('sys').platform != 'win32' else "ping -n 60 localhost",
        stdout=asyncio.subprocess.DEVNULL,
    )
    print(f"Started PID: {proc.pid}")

    # Terminate it
    await terminate_process_tree(proc)
    print(f"Terminated, returncode: {proc.returncode}")

asyncio.run(test_api())
```

### 11.2 Line Ending API

```python
from nexus3.core.paths import detect_line_ending, atomic_write_bytes
from pathlib import Path

# Test detection
print(detect_line_ending("hello\r\nworld\r\n"))  # Should print \r\n
print(detect_line_ending("hello\nworld\n"))      # Should print \n

# Test atomic write
test_path = Path("/tmp/atomic-test.txt")
atomic_write_bytes(test_path, b"test\r\ncontent\r\n")
print(f"Written: {test_path.read_bytes()}")
test_path.unlink()
```

### 11.3 Error Sanitization API

```python
from nexus3.core.errors import sanitize_error_for_agent

errors = [
    "Failed to read /home/alice/.ssh/id_rsa",
    "Cannot access C:\\Users\\bob\\Documents\\secrets.txt",
    "Permission denied: \\\\server\\share\\private",
    "DOMAIN\\admin attempted unauthorized access",
]

for err in errors:
    print(f"Original: {err}")
    print(f"Sanitized: {sanitize_error_for_agent(err)}")
    print()
```

---

## Part 12: Checklist

Use this checklist to track your testing:

### Process Termination
- [ ] Unix SIGTERM -> SIGKILL works
- [ ] Windows CTRL_BREAK -> taskkill works
- [ ] Already-terminated process handled gracefully
- [ ] Child processes are terminated with parent

### ESC Key Detection
- [ ] Unix termios detection works (if available)
- [ ] Windows msvcrt detection works
- [ ] ESC cancels REPL response generation
- [ ] Special keys (F1-F12, arrows) don't cause issues

### BOM Handling
- [ ] BOM-prefixed config.json loads
- [ ] BOM-prefixed NEXUS.md loads
- [ ] BOM characters not present in loaded content

### Environment Variables
- [ ] All 6 Windows vars in SAFE_ENV_VARS
- [ ] API keys NOT passed to subprocesses
- [ ] Platform-aware DEFAULT_PATH works

### Line Ending Preservation
- [ ] detect_line_ending() works for CRLF, LF, CR
- [ ] edit_file preserves CRLF in Windows files
- [ ] append_file uses correct line ending
- [ ] regex_replace preserves line endings

### File Attributes
- [ ] Windows shows RHSA attributes
- [ ] Unix shows rwx permissions
- [ ] Platform detection works correctly

### Error Sanitization
- [ ] Unix paths (/home/user) sanitized
- [ ] Windows paths (C:\Users\) sanitized
- [ ] UNC paths (\\server\share) sanitized
- [ ] Forward slash Windows paths sanitized
- [ ] Domain\user format sanitized

### Subprocess Handling
- [ ] No cmd.exe window flash on Windows
- [ ] CREATE_NO_WINDOW flag applied
- [ ] VT100 console mode enabled
- [ ] ANSI sequences work on Windows 10+

### Git Skill
- [ ] Async subprocess execution works
- [ ] Process groups for timeout handling
- [ ] Safe environment passed

### REPL Integration
- [ ] Starts successfully on target platform
- [ ] ESC cancellation works
- [ ] File operations work correctly
- [ ] Clean exit on Ctrl+D

---

## Troubleshooting

### Process won't terminate
```bash
# Check if taskkill is available (Windows)
where taskkill

# Check process group (Unix)
ps -ejH | grep <pid>
```

### ESC key not detected
```bash
# Check terminal capabilities
echo $TERM

# On Windows, verify msvcrt works
python -c "import msvcrt; print('OK')"
```

### BOM causing issues
```bash
# Check for BOM in file
file config.json
hexdump -C config.json | head -1
```

### Line endings wrong
```bash
# Check line endings
file myfile.txt
cat -A myfile.txt  # Shows ^M for CR
```

### ANSI not working on Windows
```powershell
# Check Windows version (need 10+)
winver

# Enable VT100 manually if needed
reg add HKCU\Console /v VirtualTerminalLevel /t REG_DWORD /d 1
```

### Git skill timeout
```bash
# Check GIT_TIMEOUT constant
python -c "from nexus3.skill.builtin.git import GIT_TIMEOUT; print(GIT_TIMEOUT)"
```

---

## Platform-Specific Notes

### Windows
- Requires Windows 10+ for VT100 ANSI support
- `os.chmod()` is effectively a no-op; file permissions rely on NTFS ACLs
- Junction points and reparse points may not be detected by `is_symlink()`
- RPC token files may be readable by other users (no Unix permission model)

### Unix/Linux
- Full ESC key detection via termios
- Process group termination via SIGTERM/SIGKILL
- Standard file permissions (rwx)
- Symlink detection works correctly

### WSL
- Uses Unix code paths (not Windows)
- Clock sync issues with `time.time()` addressed via `time.monotonic()`
- File permissions may not work as expected for Windows-mounted paths

---

## Test File Cleanup

```bash
# Remove test files created during testing
rm -rf /tmp/bom-test
rm -rf /tmp/line-ending-test
rm -rf /tmp/git-test
rm -f /tmp/attr-test.txt
rm -f /tmp/atomic-test.txt
rm -f /tmp/repl-test.txt
```
