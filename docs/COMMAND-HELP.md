# NEXUS3 Command Help Reference

This file contains detailed help text for every REPL command. It serves as the authoritative source for per-command help.

## Implementation Intent

**IMPORTANT:** When implementing per-command help, both of these should return identical output:

```
/help save
/save --help
```

The help text should be stored in a single location (a dict mapping command names to help text) and both invocation styles should read from that same source. This prevents desync between the two help mechanisms.

**Suggested implementation:**

```python
# In repl_commands.py or a new help.py module
COMMAND_HELP: dict[str, str] = {
    "save": """...""",
    "agent": """...""",
    # etc.
}

def get_command_help(cmd_name: str) -> str | None:
    """Get help text for a command. Returns None if command unknown."""
    return COMMAND_HELP.get(cmd_name)

# In cmd_help():
async def cmd_help(ctx: CommandContext, args: str | None = None) -> CommandOutput:
    if args and args.strip():
        cmd_name = args.strip().lstrip("/")
        help_text = get_command_help(cmd_name)
        if help_text:
            return CommandOutput.success(message=help_text)
        return CommandOutput.error(f"Unknown command: {cmd_name}")
    return CommandOutput.success(message=HELP_TEXT)

# In command dispatch (check for --help before executing):
if "--help" in args or "-h" in args:
    help_text = get_command_help(cmd_name)
    if help_text:
        return CommandOutput.success(message=help_text)
```

---

## Agent Management Commands

### /agent

```
/agent [name] [--yolo|-y] [--trusted|-t] [--sandboxed|-s] [--model|-m <alias>]
```

**Description:**
Show current agent status, switch to another agent, or create and switch to a new agent.

**Arguments:**

| Argument | Description |
|----------|-------------|
| `name` | Optional. Agent name to switch to or create. If omitted, shows current agent status. |

**Flags:**

| Flag | Description |
|------|-------------|
| `--yolo`, `-y` | Create agent with YOLO permission level (no confirmations) |
| `--trusted`, `-t` | Create agent with TRUSTED permission level (confirms destructive actions) |
| `--sandboxed`, `-s` | Create agent with SANDBOXED permission level (restricted to CWD) |
| `--model`, `-m` | Specify model alias or ID for new agent |

**Behavior:**

1. **No arguments** (`/agent`): Shows detailed status of current agent including model, tokens, permissions
2. **Name only** (`/agent foo`): Switches to agent "foo" if it exists; prompts to create or restore if not
3. **Name + flags** (`/agent foo --trusted`): Creates agent with specified preset and switches to it

**Examples:**

```
/agent                          # Show current agent status
/agent analyzer                 # Switch to "analyzer" (prompts if doesn't exist)
/agent worker --sandboxed       # Create sandboxed agent and switch
/agent researcher --trusted --model gpt   # Create trusted agent with GPT model
/agent helper -t -m haiku       # Short form: trusted preset, haiku model
```

**Use Cases:**

- **Check status**: See how much context you've used, what model you're on, what permissions are active
- **Multi-agent workflows**: Create specialized agents (one for research, one for coding) and switch between them
- **Permission isolation**: Create a sandboxed agent for untrusted operations
- **Model switching**: Create agents with different models for different tasks (fast model for simple queries, powerful model for complex reasoning)

**Notes:**

- If the agent name exists as a saved session on disk, you'll be prompted to restore it
- Temp agent names (`.1`, `.2`) are auto-generated for fresh sessions
- YOLO mode is only available in interactive REPL, not via RPC

---

### /whisper

```
/whisper <agent>
```

**Description:**
Enter whisper mode, redirecting all subsequent input to the target agent until `/over` is called.

**Arguments:**

| Argument | Description |
|----------|-------------|
| `agent` | Required. Agent ID to whisper to. Must exist in the pool. |

**Examples:**

```
/whisper worker-1               # Start whispering to worker-1
```

After entering whisper mode:
```
worker-1> analyze this code     # This goes to worker-1, not your current agent
worker-1> what did you find?    # Still going to worker-1
worker-1> /over                 # Exit whisper mode
>                               # Back to original agent
```

**Use Cases:**

- **Quick agent interaction**: Send multiple messages to another agent without formally switching
- **Supervisor pattern**: Main agent monitors while you directly instruct a worker
- **Debugging**: Interact with a subagent to understand its state

**Notes:**

- The prompt changes to show the whisper target
- Commands like `/over`, `/help`, `/quit` still work in whisper mode
- If the target agent doesn't exist, you'll be prompted to create it

---

### /over

```
/over
```

**Description:**
Exit whisper mode and return to the original agent.

**Arguments:** None

**Examples:**

```
worker-1> /over                 # Exit whisper mode
>                               # Back to original agent
```

**Use Cases:**

- End a whisper session and return to your main agent

**Notes:**

- Only works when in whisper mode
- Returns you to whichever agent you were on before entering whisper mode

---

### /list

```
/list
```

**Description:**
List all active agents in the pool with summary information.

**Arguments:** None

**Output includes:**
- Agent ID and type (temp vs named)
- Model being used
- Permission level
- Message count
- Last action timestamp
- Parent/child relationships
- Halted status (if hit iteration limit)

**Examples:**

```
/list

Active agents:
  main (named)
    model=sonnet, perm=TRUSTED, msgs=42, action=14:30:05
    cwd=/home/user/project, write=any
  worker-1 (temp)
    model=haiku, perm=SANDBOXED, msgs=12, action=14:28:30, parent=main
    cwd=/home/user/project, write=output
```

**Use Cases:**

- **Overview**: See all agents you have running
- **Resource management**: Check which agents are using context, decide which to destroy
- **Debugging**: Find stuck agents (halted status) or check parent/child relationships

---

### /create

```
/create <name> [--yolo|-y] [--trusted|-t] [--sandboxed|-s] [--model|-m <alias>]
```

**Description:**
Create a new agent without switching to it. Useful for setting up agents in the background.

**Arguments:**

| Argument | Description |
|----------|-------------|
| `name` | Required. Unique agent ID. Cannot already exist. |

**Flags:**

| Flag | Description |
|------|-------------|
| `--yolo`, `-y` | YOLO permission level |
| `--trusted`, `-t` | TRUSTED permission level (default) |
| `--sandboxed`, `-s` | SANDBOXED permission level |
| `--model`, `-m` | Model alias or ID |

**Examples:**

```
/create worker-1                      # Create with default (trusted) preset
/create analyzer --sandboxed          # Create sandboxed agent
/create fast-helper --model haiku     # Create with specific model
```

**Use Cases:**

- **Preparation**: Set up multiple agents before starting a complex workflow
- **Background workers**: Create agents that will receive messages via `/send` or `nexus_send`
- **Isolation**: Create sandboxed agents for specific tasks without switching context

**Notes:**

- Does NOT switch to the new agent (use `/agent <name>` for that)
- Agent starts with empty conversation history

---

### /destroy

```
/destroy <name>
```

**Description:**
Remove an agent from the pool. Log files are preserved on disk.

**Arguments:**

| Argument | Description |
|----------|-------------|
| `name` | Required. Agent ID to destroy. |

**Examples:**

```
/destroy worker-1                     # Remove worker-1 from pool
```

**Use Cases:**

- **Cleanup**: Remove agents you no longer need
- **Resource management**: Free up memory from agents with large contexts
- **Reset**: Destroy and recreate an agent to start fresh

**Notes:**

- Cannot destroy your current agent (switch to another first)
- Log files in `.nexus3/logs/<agent_id>/` are preserved
- Saved sessions in `~/.nexus3/sessions/` are NOT affected

---

### /send

```
/send <agent> <message>
```

**Description:**
Send a one-shot message to another agent and display the response.

**Arguments:**

| Argument | Description |
|----------|-------------|
| `agent` | Required. Target agent ID. |
| `message` | Required. Message content to send. |

**Examples:**

```
/send worker-1 summarize the file you just read
/send analyzer what patterns did you find?
```

**Use Cases:**

- **Quick queries**: Ask another agent a question without switching
- **Coordination**: Send instructions to worker agents
- **Checking progress**: Ask a long-running agent for status

**Notes:**

- This is synchronous - waits for the full response
- For ongoing conversations, use `/whisper` or `/agent` to switch
- The message is attributed with your current agent as the source

---

### /status

```
/status [agent] [--tools] [--tokens] [-a|--all]
```

**Description:**
Get comprehensive status information about an agent.

**Arguments:**

| Argument | Description |
|----------|-------------|
| `agent` | Optional. Agent ID to check. Defaults to current agent. |

**Flags:**

| Flag | Description |
|------|-------------|
| `--tools` | Include full list of available tools |
| `--tokens` | Include detailed token breakdown (system, tools, messages) |
| `-a`, `--all` | Include both tools and tokens (equivalent to `--tools --tokens`) |

**Examples:**

```
/status                         # Current agent, basic info
/status worker-1                # Check another agent
/status --tokens                # Current agent with token breakdown
/status worker-1 --tools        # Another agent with tool list
/status -a                      # Everything
```

**Output includes:**
- Agent ID, type, creation time
- Model info (ID, alias, context window, provider)
- Permission level and preset
- Context usage (total/available/remaining tokens)
- Message count
- Working directory and write paths
- Disabled tools
- MCP servers connected
- Compaction settings
- Parent/child relationships

**Use Cases:**

- **Context monitoring**: Check if you're approaching token limits
- **Debugging**: Verify an agent has the expected tools and permissions
- **Planning**: Check available context before sending large prompts

---

### /cancel

```
/cancel [agent]
```

**Description:**
Cancel an in-progress request. Also works via ESC key during streaming.

**Arguments:**

| Argument | Description |
|----------|-------------|
| `agent` | Optional. Agent ID. Defaults to current agent. |

**Examples:**

```
/cancel                         # Cancel current agent's request
/cancel worker-1                # Cancel another agent's request
```

**Use Cases:**

- **Abort**: Stop a long-running response you no longer need
- **Mistake**: Cancel if you sent the wrong message
- **Stuck agent**: Interrupt an agent in an infinite tool loop

**Notes:**

- Pressing ESC during streaming has the same effect for current agent
- Cancellation is cooperative - the agent stops at the next yield point

---

## Session Management Commands

### /save

```
/save [name]
```

**Description:**
Save the current agent's session to disk for later restoration.

**Arguments:**

| Argument | Description |
|----------|-------------|
| `name` | Optional. Name to save as. Defaults to current agent ID. |

**What gets saved:**
- Full message history
- System prompt content and path
- Working directory
- Permission preset and disabled tools
- Model alias
- Token usage snapshot
- Creation timestamp

**Examples:**

```
/save                           # Save with current agent name
/save my-project                # Save as "my-project"
/save research-session          # Save as "research-session"
```

**Use Cases:**

- **Persistence**: Save work before closing the REPL
- **Checkpointing**: Save progress before risky operations
- **Sharing**: Save a session to continue on another machine
- **Archiving**: Keep a record of important conversations

**Notes:**

- Cannot save with temp names (`.1`, `.2`) - must provide a real name
- Saves to `~/.nexus3/sessions/{name}.json`
- Overwrites if name already exists (no confirmation currently)
- Session is also auto-saved to `last-session.json` on exit for `--resume`

**File location:** `~/.nexus3/sessions/{name}.json`

---

### /clone

```
/clone <src> <dest>
```

**Description:**
Clone an active agent or saved session to a new name.

**Arguments:**

| Argument | Description |
|----------|-------------|
| `src` | Required. Source agent ID or saved session name. |
| `dest` | Required. Destination name. Must not already exist. |

**Behavior:**
1. If `src` is an active agent: Creates new agent with copied messages and system prompt
2. If `src` is a saved session: Copies the session file with new name

**Examples:**

```
/clone main backup              # Clone active agent "main" to "backup"
/clone my-project experiment    # Clone saved session to try something different
```

**Use Cases:**

- **Backup**: Clone before making risky changes
- **Branching**: Try different approaches from the same starting point
- **Templates**: Clone a well-configured agent as a starting point

**Notes:**

- Checks active agents first, then saved sessions
- Destination must not already exist (as agent or saved session)

---

### /rename

```
/rename <old> <new>
```

**Description:**
Rename an active agent or saved session.

**Arguments:**

| Argument | Description |
|----------|-------------|
| `old` | Required. Current name. |
| `new` | Required. New name. Must not already exist. |

**Behavior:**
1. If `old` is an active agent: Creates new agent, copies state, destroys old
2. If `old` is a saved session: Renames the file and updates internal agent_id

**Examples:**

```
/rename .1 my-project           # Give a temp session a real name
/rename old-name new-name       # Rename a saved session
```

**Use Cases:**

- **Naming temp sessions**: Convert `.1` to a meaningful name before saving
- **Organization**: Rename sessions to better reflect their content
- **Cleanup**: Standardize naming conventions

**Notes:**

- If renaming the current agent, you remain on the new name
- For active agents, this is implemented as create-copy-destroy

---

### /delete

```
/delete <name>
```

**Description:**
Delete a saved session from disk. Does NOT affect active agents.

**Arguments:**

| Argument | Description |
|----------|-------------|
| `name` | Required. Saved session name to delete. |

**Examples:**

```
/delete old-project             # Remove saved session
/delete test-session            # Clean up test data
```

**Use Cases:**

- **Cleanup**: Remove sessions you no longer need
- **Privacy**: Delete sessions containing sensitive information
- **Space**: Free up disk space from old sessions

**Notes:**

- Only deletes from `~/.nexus3/sessions/`, not active agents
- Use `/destroy` to remove active agents
- Cannot delete temp names (they're not saved as named sessions)
- No confirmation prompt - deletion is immediate

**File location:** Deletes `~/.nexus3/sessions/{name}.json`

---

## Configuration Commands

### /cwd

```
/cwd [path]
```

**Description:**
Show or change the working directory for the current agent.

**Arguments:**

| Argument | Description |
|----------|-------------|
| `path` | Optional. New working directory. If omitted, shows current. |

**Examples:**

```
/cwd                            # Show current working directory
/cwd /home/user/project         # Change to absolute path
/cwd ~/repos/myapp              # Tilde expansion supported
/cwd ../other-project           # Relative paths work too
```

**Use Cases:**

- **Project switching**: Change context to a different project
- **Sandboxing**: Set CWD to limit where sandboxed agents can operate
- **Verification**: Check what directory tools will operate in

**Notes:**

- Each agent has its own CWD (not shared)
- Sandboxed agents can only change CWD within their allowed paths
- Path must exist and be a directory
- Symlinks are rejected (security measure)

---

### /model

```
/model [name]
```

**Description:**
Show current model or switch to a different model.

**Arguments:**

| Argument | Description |
|----------|-------------|
| `name` | Optional. Model alias or full ID. If omitted, shows current model. |

**Examples:**

```
/model                          # Show current model info
/model haiku                    # Switch to haiku (by alias)
/model gpt                      # Switch to GPT (by alias)
/model anthropic/claude-sonnet-4  # Switch by full model ID
```

**Output (no args):**
```
Model: anthropic/claude-sonnet-4 (alias: sonnet)
Context window: 200,000 tokens
Reasoning: disabled
```

**Use Cases:**

- **Cost optimization**: Switch to cheaper model for simple tasks
- **Capability matching**: Use powerful model for complex reasoning
- **Speed**: Use fast model for quick iterations
- **Context needs**: Switch to model with larger context window

**Notes:**

- Model aliases are defined in your `config.json`
- If current context exceeds new model's limit, you'll be prompted to `/compact` first
- Model choice is persisted when you `/save` the session

---

### /permissions

```
/permissions [preset] [--disable <tool>] [--enable <tool>] [--list-tools]
```

**Description:**
Show or modify permission level for the current agent.

**Arguments:**

| Argument | Description |
|----------|-------------|
| `preset` | Optional. Change to this preset (yolo/trusted/sandboxed). |

**Flags:**

| Flag | Description |
|------|-------------|
| `--disable <tool>` | Disable a specific tool |
| `--enable <tool>` | Re-enable a previously disabled tool |
| `--list-tools` | Show all tools with their enabled/disabled status |

**Presets:**

| Preset | Description |
|--------|-------------|
| `yolo` | Full access, no confirmations (REPL-only) |
| `trusted` | Confirmations for destructive actions |
| `sandboxed` | Restricted to CWD, no network, no agent management |

**Examples:**

```
/permissions                    # Show current permissions
/permissions trusted            # Switch to trusted preset
/permissions --disable shell_UNSAFE  # Disable dangerous tool
/permissions --enable write_file     # Re-enable a tool
/permissions --list-tools       # See all tools and their status
```

**Use Cases:**

- **Security**: Downgrade permissions before running untrusted code
- **Convenience**: Upgrade to yolo for rapid iteration (careful!)
- **Fine-tuning**: Disable specific tools you don't want the agent using
- **Debugging**: Check what tools are available/disabled

**Notes:**

- Cannot exceed your ceiling (e.g., if parent was trusted, can't go to yolo)
- Disabling a tool removes it from the LLM's view entirely
- Changes take effect immediately for subsequent tool calls

---

### /prompt

```
/prompt [file]
```

**Description:**
Show or set the system prompt for the current agent.

**Arguments:**

| Argument | Description |
|----------|-------------|
| `file` | Optional. Path to prompt file. If omitted, shows current prompt preview. |

**Examples:**

```
/prompt                         # Show current system prompt (truncated preview)
/prompt ~/prompts/coding.md     # Load prompt from file
/prompt ./NEXUS.md              # Load project-specific prompt
```

**Use Cases:**

- **Verification**: Check what instructions the agent is operating under
- **Customization**: Load a specialized prompt for specific tasks
- **Debugging**: Verify the prompt loaded correctly

**Notes:**

- Shows first 200 characters as preview
- Loading a new prompt replaces the entire system prompt
- Symlinks are rejected (security measure)
- System prompt is included in session saves

---

### /compact

```
/compact
```

**Description:**
Force context compaction, summarizing older messages to reclaim token space.

**Arguments:** None

**Examples:**

```
/compact                        # Force compaction now
```

**Output:**
```
Compacted: 85,000 -> 25,000 tokens
```

Or if nothing to compact:
```
Nothing to compact - all 12 messages (8,500 tokens) fit within preserve budget (50,000 tokens, 25% of available)
```

**Use Cases:**

- **Reclaim space**: Free up tokens when approaching context limit
- **Before model switch**: Reduce context to fit in smaller model's window
- **Long sessions**: Periodically compact to keep sessions manageable
- **System prompt update**: Compaction reloads NEXUS.md, picking up changes

**Notes:**

- Uses a separate (usually cheaper/faster) model for summarization
- Preserves recent messages verbatim (configurable ratio)
- Automatic compaction triggers at 90% capacity (configurable)
- Summary includes timestamp for temporal awareness

---

## MCP Commands

### /mcp

```
/mcp
/mcp connect <name> [--allow-all] [--per-tool] [--shared] [--private]
/mcp disconnect <name>
/mcp tools [server]
```

**Description:**
Manage Model Context Protocol (MCP) server connections for external tools.

**Subcommands:**

#### /mcp (no args)

List configured and connected MCP servers.

**Example:**
```
/mcp

MCP Servers:

Configured:
  filesystem [connected]
  github [disconnected]
  database [connected, not visible]

Connected (visible to you): 1
  filesystem: 5 tools (shared)
```

#### /mcp connect

```
/mcp connect <name> [--allow-all] [--per-tool] [--shared] [--private]
```

Connect to a configured MCP server.

**Arguments:**

| Argument | Description |
|----------|-------------|
| `name` | Required. Server name from config. |

**Flags:**

| Flag | Description |
|------|-------------|
| `--allow-all` | Skip consent prompt, allow all tools from this server |
| `--per-tool` | Skip consent prompt, require confirmation for each tool use |
| `--shared` | Skip sharing prompt, share connection with all agents |
| `--private` | Skip sharing prompt, keep connection private to this agent |

**Examples:**

```
/mcp connect filesystem                    # Interactive prompts
/mcp connect github --allow-all --shared   # Allow all, share with agents
/mcp connect database --per-tool --private # Confirm each use, private
```

**Use Cases:**

- **Extended capabilities**: Add filesystem, database, API tools
- **Automation**: Use flags to skip interactive prompts in scripts
- **Multi-agent**: Share connections so all agents can use the tools

#### /mcp disconnect

```
/mcp disconnect <name>
```

Disconnect from an MCP server.

**Arguments:**

| Argument | Description |
|----------|-------------|
| `name` | Required. Server name to disconnect. |

**Examples:**

```
/mcp disconnect filesystem
```

**Notes:**

- Only the connection owner can disconnect
- Shared connections: disconnecting removes access for all agents

#### /mcp tools

```
/mcp tools [server]
```

List available MCP tools.

**Arguments:**

| Argument | Description |
|----------|-------------|
| `server` | Optional. Filter to specific server. If omitted, shows all. |

**Examples:**

```
/mcp tools                      # All MCP tools
/mcp tools filesystem           # Only filesystem server tools
```

**Use Cases:**

- **Discovery**: See what tools an MCP server provides
- **Verification**: Confirm tools are available after connecting

---

## Initialization Commands

### /init

```
/init [--force|-f] [--global|-g]
```

**Description:**
Initialize NEXUS3 configuration directory with templates.

**Flags:**

| Flag | Description |
|------|-------------|
| `--force`, `-f` | Overwrite existing configuration files |
| `--global`, `-g` | Initialize `~/.nexus3/` instead of local `./.nexus3/` |

**Examples:**

```
/init                           # Create ./.nexus3/ with templates
/init --force                   # Overwrite existing local config
/init --global                  # Initialize ~/.nexus3/
/init --global --force          # Overwrite existing global config
```

**Created files (local):**
```
./.nexus3/
├── NEXUS.md       # Project-specific system prompt template
├── config.json    # Project configuration overrides
└── mcp.json       # Project MCP server definitions
```

**Created files (global):**
```
~/.nexus3/
├── NEXUS.md       # Personal system prompt
├── config.json    # Global configuration
├── mcp.json       # Global MCP servers
└── sessions/      # Saved sessions directory
```

**Use Cases:**

- **New project**: Initialize local config for project-specific settings
- **First-time setup**: Initialize global config on a new machine
- **Reset**: Use `--force` to restore defaults

**Notes:**

- Local config overrides global config
- Won't overwrite existing files without `--force`
- CLI equivalent: `nexus3 --init-global` and `nexus3 --init-global-force`

---

## REPL Control Commands

### /help

```
/help [command]
```

**Description:**
Display help information.

**Arguments:**

| Argument | Description |
|----------|-------------|
| `command` | Optional. Specific command to get help for. |

**Examples:**

```
/help                           # Show all commands overview
/help save                      # Detailed help for /save (NOT YET IMPLEMENTED)
```

**Notes:**

- Per-command help (`/help <command>`) is planned but not yet implemented
- See COMMAND-HELP.md for detailed per-command documentation

---

### /clear

```
/clear
```

**Description:**
Clear the terminal display. Conversation context is preserved.

**Arguments:** None

**Examples:**

```
/clear                          # Clear screen
```

**Use Cases:**

- **Declutter**: Clean up after long conversations
- **Focus**: Start fresh visually without losing context
- **Screenshots**: Clear before capturing output

**Notes:**

- Only clears display, not conversation history
- Tokens used remain the same

---

### /quit

```
/quit
/exit
/q
```

**Description:**
Exit the REPL. All three forms are equivalent.

**Arguments:** None

**Examples:**

```
/quit                           # Exit REPL
/exit                           # Same as /quit
/q                              # Short form
```

**Notes:**

- Current session is auto-saved to `~/.nexus3/last-session.json` for `--resume`
- Active agents are destroyed (but saved sessions persist)
- Ctrl+D also exits

---

## Keyboard Shortcuts

| Key | Action | Context |
|-----|--------|---------|
| `ESC` | Cancel in-progress request | During streaming response |
| `Ctrl+C` | Interrupt current input | While typing |
| `Ctrl+D` | Exit REPL | At empty prompt |

---

## Testing Requirements

When implementing per-command help, include tests that verify:

### 1. Main Help Completeness

```python
def test_main_help_lists_all_commands():
    """Every implemented command should appear in HELP_TEXT."""
    implemented_commands = {
        "agent", "whisper", "over", "list", "create", "destroy",
        "send", "status", "cancel", "save", "clone", "rename",
        "delete", "cwd", "model", "permissions", "prompt", "compact",
        "mcp", "init", "help", "clear", "quit", "exit", "q"
    }
    for cmd in implemented_commands:
        assert f"/{cmd}" in HELP_TEXT or cmd in HELP_TEXT
```

### 2. Per-Command Help Completeness

```python
def test_command_help_documents_all_flags():
    """Each command's help should document all its flags."""
    # Example for /agent
    agent_help = get_command_help("agent")
    assert "--yolo" in agent_help
    assert "--trusted" in agent_help
    assert "--sandboxed" in agent_help
    assert "--model" in agent_help
    assert "-y" in agent_help  # Short forms too
    assert "-t" in agent_help
    assert "-s" in agent_help
    assert "-m" in agent_help
```

### 3. Help Mechanism Equivalence

```python
def test_help_cmd_equals_cmd_help():
    """Both help invocation styles should return identical text."""
    for cmd in COMMAND_HELP.keys():
        via_help_cmd = get_command_help(cmd)
        # Simulate --help flag handling
        via_flag = get_command_help(cmd)
        assert via_help_cmd == via_flag
```

### 4. No Orphan Commands

```python
def test_no_orphan_commands():
    """Every command in COMMAND_HELP should be a real command."""
    from nexus3.cli.repl_commands import (
        cmd_agent, cmd_whisper, cmd_over, # ... etc
    )
    for cmd_name in COMMAND_HELP.keys():
        # Verify the command function exists
        assert hasattr(repl_commands, f"cmd_{cmd_name}") or cmd_name in ALIASES
```

### 5. Examples Are Valid

```python
def test_help_examples_are_syntactically_valid():
    """Examples in help text should be parseable."""
    for cmd_name, help_text in COMMAND_HELP.items():
        # Extract examples (lines starting with /)
        examples = re.findall(r'^/\S+.*$', help_text, re.MULTILINE)
        for example in examples:
            # Should not raise parsing errors
            parse_command(example)
```

---

## Appendix: Command Quick Reference

| Command | Arguments | Description |
|---------|-----------|-------------|
| `/agent` | `[name] [flags]` | Show status / switch / create agent |
| `/whisper` | `<agent>` | Enter whisper mode |
| `/over` | | Exit whisper mode |
| `/list` | | List all agents |
| `/create` | `<name> [flags]` | Create agent without switching |
| `/destroy` | `<name>` | Remove agent |
| `/send` | `<agent> <msg>` | One-shot message |
| `/status` | `[agent] [flags]` | Agent status |
| `/cancel` | `[agent]` | Cancel request |
| `/save` | `[name]` | Save session |
| `/clone` | `<src> <dest>` | Clone agent/session |
| `/rename` | `<old> <new>` | Rename agent/session |
| `/delete` | `<name>` | Delete saved session |
| `/cwd` | `[path]` | Show/set working directory |
| `/model` | `[name]` | Show/switch model |
| `/permissions` | `[preset] [flags]` | Show/modify permissions |
| `/prompt` | `[file]` | Show/set system prompt |
| `/compact` | | Force compaction |
| `/mcp` | `[subcommand]` | MCP server management |
| `/init` | `[flags]` | Initialize config |
| `/help` | `[command]` | Show help |
| `/clear` | | Clear display |
| `/quit` | | Exit REPL |

---

*Last updated: 2026-01-22*
