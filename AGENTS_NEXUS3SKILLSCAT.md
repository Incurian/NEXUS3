# AGENTS_NEXUS3SKILLSCAT.md

Full built-in skills reference.

Derived from `CLAUDE.md` Built-in Skills section, adapted for Codex usage.

Contract rule for the fixed-schema file-edit, read/search/listing, and
clipboard wrapper/info families: unexpected extra arguments now fail closed
instead of being silently dropped.

## Built-in Skills

| Skill | Parameters | Description |
|-------|------------|-------------|
| `read_file` | `path`, `offset`?, `limit`?, `start_line`?, `end_line`?, `line_numbers`? | Read UTF-8 file contents (numbered by default; raw mode available with `line_numbers=false`; invalid UTF-8 fails closed; `start_line`/`end_line` are compatibility aliases for `offset`/`limit`) |
| `tail` | `path`, `lines`? | Read last N lines of a UTF-8 text file (default: 10; invalid UTF-8 is rejected) |
| `file_info` | `path` | Get file/directory metadata (size, mtime, permissions) |
| `write_file` | `path`, `content` | Write/create UTF-8 text files (exact newline bytes; read file first) |
| `edit_file` | `path`, `old_string`, `new_string`, `replace_all`?, `edits`? | UTF-8 exact string replacement; batch edits are atomic and later edits must still match after earlier edits (read file first) |
| `edit_lines` | `path`, `start_line`, `end_line`?, `new_content`, `edits`? | Replace UTF-8 lines by number; `edits` batches are atomic, use original line numbers, and reject overlaps |
| `append_file` | `path`, `content`, `newline`? | Append UTF-8 text to a file (exact newline bytes; read file first) |
| `regex_replace` | `path`, `pattern`, `replacement`, `count`?, `ignore_case`?, `multiline`?, `dotall`? | UTF-8 pattern-based find/replace (`count >= 0`; read file first) |
| `patch` | `path`, `diff`?, `diff_file`?, `mode`?, `fidelity_mode`?, `fuzzy_threshold`?, `dry_run`? | Apply unified diffs (strict/tolerant/fuzzy modes; `target` remains a compatibility alias, hunk-only single-file diffs auto-normalize when the target is known, and `diff_file` must be UTF-8 text) |
| `copy_file` | `source`, `destination`, `overwrite`? | Copy a file to a new location |
| `mkdir` | `path` | Create directory (and parents) |
| `rename` | `source`, `destination`, `overwrite`? | Rename or move file/directory |
| `list_directory` | `path` | List directory contents |
| `glob` | `pattern`, `path`?, `exclude`? | Find files matching glob pattern (with exclusions) |
| `grep` | `pattern`, `path`, `recursive`?, `ignore_case`?, `max_matches`?, `include`?, `context`? | Search UTF-8 file contents with file filter and context lines; single-file invalid UTF-8 fails closed and directory scans skip invalid UTF-8 files |
| `concat_files` | `extensions`, `path`?, `exclude`?, `lines`?, `max_total`?, `format`?, `sort`?, `gitignore`?, `dry_run`? | Concatenate UTF-8 files by extension with token estimation (`dry_run=True` by default; real writes generate an output file and skip invalid UTF-8 inputs) |
| `outline` | `path`, `file_type`?, `language`?, `parser`?, `depth`?, `preview`?, `signatures`?, `line_numbers`?, `tokens`?, `symbol`?, `diff`?, `recursive`? | Structural outline of UTF-8 file/directory; directory mode is non-recursive, `depth` controls nested symbols within each file, invalid UTF-8 directory entries are skipped, `symbol` returns a source excerpt for files only, `file_type`/`language`/`parser` can override parser detection for files, `recursive=true` fails closed, ambiguous symbol matches fail closed, and large directory output may truncate |
| `git` | `command`, `cwd`? | Execute git commands (permission-filtered by level) |
| `bash_safe` | `command`, `timeout`?, `cwd`? | Execute shell commands (`shlex.split`, no shell operators) |
| `shell_UNSAFE` | `command`, `timeout`?, `cwd`? | Execute full shell with the detected shell family on Windows when possible (pipes work, injection-vulnerable) |
| `run_python` | `code`, `timeout`?, `cwd`? | Execute Python code |
| `sleep` | `seconds`, `label`? | Pause execution (for testing) |
| `nexus_create` | `agent_id`, `preset`?, `disable_tools`?, `cwd`?, `allowed_write_paths`?, `model`?, `initial_message`?, `wait_for_initial_response`?, `port`? | Create agent (initial message queued by default; wait flag only matters when `initial_message` is set) |
| `nexus_destroy` | `agent_id`, `port`? | Remove an agent (server keeps running) |
| `nexus_send` | `agent_id`, `content`, `port`? | Send message to an agent |
| `nexus_status` | `agent_id`, `port`? | Get agent tokens and context |
| `nexus_cancel` | `agent_id`, `request_id`, `port`? | Cancel in-progress request (`request_id` may be string or integer) |
| `nexus_shutdown` | `port`? | Shutdown the entire server |
| `copy` | `source`, `key`, `scope`?, `start_line`?, `end_line`?, `short_description`?, `tags`?, `ttl_seconds`? | Copy UTF-8 file content to clipboard |
| `cut` | `source`, `key`, `scope`?, `start_line`?, `end_line`?, `short_description`?, `tags`?, `ttl_seconds`? | Cut UTF-8 file content to clipboard (removes from source) |
| `paste` | `key`, `target`, `scope`?, `mode`?, `line_number`?, `start_line`?, `end_line`?, `marker`?, `create_if_missing`? | Paste clipboard content to a UTF-8 file |
| `clipboard_list` | `scope`?, `tags`?, `any_tags`?, `verbose`? | List clipboard entries with optional tag filtering |
| `clipboard_get` | `key`, `scope`? | Get full content of clipboard entry |
| `clipboard_update` | `key`, `scope`?, `new_key`?, `short_description`?, `content`?, `source`?, `start_line`?, `end_line`?, `ttl_seconds`? | Update clipboard entry metadata/content (`source` must be UTF-8 text) |
| `clipboard_delete` | `key`, `scope`? | Delete clipboard entry |
| `clipboard_clear` | `scope`?, `confirm`? | Clear all entries in scope |
| `clipboard_search` | `query`, `scope`?, `max_results`? | Search clipboard entries |
| `clipboard_tag` | `action`, `entry_key`?, `name`?, `scope`?, `description`? | Manage clipboard tags (list/add/remove; `create` is currently a placeholder and `delete` is not implemented) |
| `clipboard_export` | `path`, `scope`?, `tags`? | Export clipboard entries to JSON |
| `clipboard_import` | `path`, `scope`?, `conflict`?, `dry_run`? | Import clipboard entries from JSON (malformed structures rejected) |
| `gitlab_repo` | `action`, `project`?, `instance`? | Repository operations (get, list, fork, search, whoami) |
| `gitlab_issue` | `action`, `project`?, `iid`?, `title`?, `assignees`?, `assignee_username`?, `author_username`?, ... | Issue CRUD and comments; supports `me` shorthand |
| `gitlab_mr` | `action`, `project`?, `iid`?, `source_branch`?, `assignees`?, `reviewers`?, `assignee_username`?, `author_username`?, `reviewer_username`?, ... | MR operations (list/get/create/update/merge/close/diff/commits/pipelines); supports `me` shorthand |
| `gitlab_label` | `action`, `project`?, `name`?, `color`? | Label management |
| `gitlab_branch` | `action`, `project`?, `name`?, `ref`?, `push_level`?, `merge_level`?, `allow_force_push`? | Branch operations |
| `gitlab_tag` | `action`, `project`?, `name`?, `ref`?, `create_level`? | Tag operations |
| `gitlab_epic` | `action`, `group`, `iid`?, `title`?, ... | Epic management [Premium] |
| `gitlab_iteration` | `action`, `group`, `iteration_id`?, `title`?, ... | Iteration/sprint management [Premium] |
| `gitlab_milestone` | `action`, `project` OR `group`, `milestone_id`?, `title`?, ... | Milestone operations |
| `gitlab_board` | `action`, `project` OR `group`, `board_id`?, `name`?, ... | Issue board management |
| `gitlab_time` | `action`, `project`, `iid`, `target_type`, `duration`?, ... | Time tracking on issues/MRs |
| `gitlab_approval` | `action`, `project`, `iid`?, `rule_id`?, `name`?, ... | MR approvals/rules [Premium for rules] |
| `gitlab_draft` | `action`, `project`, `iid`, `draft_id`?, `body`?, ... | Draft notes for batch MR reviews |
| `gitlab_discussion` | `action`, `project`, `iid`, `target_type`, `discussion_id`?, ... | Threaded discussions on MRs/issues |
| `gitlab_pipeline` | `action`, `project`, `pipeline_id`?, `ref`?, `status`?, ... | Pipeline operations |
| `gitlab_job` | `action`, `project`, `job_id`?, `scope`?, `tail`?, ... | Job operations |
| `gitlab_artifact` | `action`, `project`, `job_id`?, `output_path`?, ... | Artifact management |
| `gitlab_variable` | `action`, `project` OR `group`, `key`?, `value`?, ... | CI/CD variable management |
| `gitlab_deploy_key` | `action`, `project`, `key_id`?, `title`?, `key`?, `can_push`? | Deploy key management |
| `gitlab_deploy_token` | `action`, `project` OR `group`, `token_id`?, `name`?, `scopes`?, ... | Deploy token management |
| `gitlab_feature_flag` | `action`, `project`, `name`?, `active`?, `strategies`?, ... | Feature flag management [Premium] |

## Notes

- `port` defaults to `8765`
- `preset` supports `trusted` and `sandboxed` via RPC (`yolo` is REPL-only)
- Clipboard scope options: `agent` (session-only), `project` (persistent), `system` (persistent)
- GitLab skills generally require TRUSTED+ and configured instance data
- Some GitLab skills require GitLab Premium

## Skill Implementation Context

The codebase skill hierarchy is documented in [AGENTS_NEXUS3ARCH.md](/home/inc/repos/NEXUS3/AGENTS_NEXUS3ARCH.md).
