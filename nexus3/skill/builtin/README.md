# nexus3.skill.builtin

Built-in skill implementations shipped with NEXUS3.

## Overview

This package contains the concrete implementations behind
`register_builtin_skills(...)` in
[`registration.py`](/home/inc/repos/NEXUS3/nexus3/skill/builtin/registration.py).
The current public registration surface is **43 core built-in skills**.

High-level categories:

- File read/search: `read_file`, `tail`, `file_info`, `list_directory`,
  `glob`, `search_text`, `concat_files`, `outline`
- File write/edit: `write_file`, `edit_file`, `edit_lines`, `append_file`,
  `regex_replace`, `patch`, `copy_file`, `mkdir`, `rename`
- Host processes: `list_processes`, `get_process`, `kill_process`
- Execution: `exec`, `shell_UNSAFE`, `run_python`
- Version control: `git`
- Agent management: `nexus_create`, `nexus_destroy`, `nexus_send`,
  `nexus_cancel`, `nexus_status`, `nexus_shutdown`
- Clipboard: `copy`, `cut`, `paste`, `clipboard_list`, `clipboard_get`,
  `clipboard_update`, `clipboard_delete`, `clipboard_clear`,
  `clipboard_search`, `clipboard_tag`, `clipboard_export`,
  `clipboard_import`
- Utility: `sleep`

Testing-only note:

- [`echo.py`](/home/inc/repos/NEXUS3/nexus3/skill/builtin/echo.py) exists for
  harness/testing use but is not registered by default

Supporting files:

- [`registration.py`](/home/inc/repos/NEXUS3/nexus3/skill/builtin/registration.py)
  - canonical built-in skill registration surface
- [`env.py`](/home/inc/repos/NEXUS3/nexus3/skill/builtin/env.py)
  - shared environment sanitization helpers for execution-oriented skills

For the full public contract and parameter reference, see
[`nexus3/skill/README.md`](/home/inc/repos/NEXUS3/nexus3/skill/README.md).
