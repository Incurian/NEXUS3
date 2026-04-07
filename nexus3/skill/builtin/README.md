# nexus3.skill.builtin

Built-in skill implementations shipped with NEXUS3.

## Overview

This package contains the concrete implementations behind
`register_builtin_skills(...)` in
[`registration.py`](/home/inc/repos/NEXUS3/nexus3/skill/builtin/registration.py).
The current public registration surface is **46 core built-in skills**.

## Package Structure

Core files:

- [`__init__.py`](/home/inc/repos/NEXUS3/nexus3/skill/builtin/__init__.py)
  - small compatibility export surface for built-in registration and selected
    `nexus_*` factories
- [`registration.py`](/home/inc/repos/NEXUS3/nexus3/skill/builtin/registration.py)
  - canonical built-in registration order and names
- [`env.py`](/home/inc/repos/NEXUS3/nexus3/skill/builtin/env.py)
  - shared environment sanitization helpers for execution-oriented skills

Implementation groups:

- File read/search: `read_file`, `tail`, `file_info`, `list_directory`,
  `glob`, `search_text`, `concat_files`, `outline`
- File write/edit: `write_file`, `edit_file`, `edit_file_batch`,
  `edit_lines`, `edit_lines_batch`, `append_file`, `regex_replace`, `patch`,
  `patch_from_file`, `copy_file`, `mkdir`, `rename`
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

## Registration Notes

- `register_builtin_skills(registry)` is the source of truth for the public
  built-in tool surface
- the package includes implementation files that are not part of the default
  registration set when they exist only for tests or helper reuse
- permission filtering happens above the package at registry/permissions
  boundaries, so registration here is broader than what every agent will see

## Public Exports

[`__init__.py`](/home/inc/repos/NEXUS3/nexus3/skill/builtin/__init__.py)
currently re-exports:

- `register_builtin_skills`
- `nexus_send_factory`
- `nexus_cancel_factory`
- `nexus_status_factory`
- `nexus_shutdown_factory`

## Testing-Only Note

- [`echo.py`](/home/inc/repos/NEXUS3/nexus3/skill/builtin/echo.py) exists for
  harness/testing use but is not registered by default

## Related Docs

- Full tool contract and parameter reference:
  [`nexus3/skill/README.md`](/home/inc/repos/NEXUS3/nexus3/skill/README.md)
- Clipboard-backed skill behavior:
  [`nexus3/clipboard/README.md`](/home/inc/repos/NEXUS3/nexus3/clipboard/README.md)
- Unified diff support used by `patch` and `patch_from_file`:
  [`nexus3/patch/README.md`](/home/inc/repos/NEXUS3/nexus3/patch/README.md)
- Session/runtime permission enforcement for tool execution:
  [`nexus3/session/README.md`](/home/inc/repos/NEXUS3/nexus3/session/README.md)
