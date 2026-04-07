# 101 Stdio Example

Start here if this is your first MCP server.

This is the smallest example that still teaches the NEXUS-specific pieces that
usually trip people up:

- how a stdio MCP server talks to NEXUS
- how `command`, `args`, `cwd`, `env`, and `env_passthrough` show up in a real
  `mcp.json`
- how an MCP tool named `hello` becomes the NEXUS tool
  `mcp_hello_stdio_hello`

The server script uses only the Python standard library.

Files:

- [hello_stdio_server.py](./hello_stdio_server.py)
- [mcp.json](./.nexus3/mcp.json)

This example's `mcp.json` intentionally shows more than the bare minimum:

- `command` + `args`
- `cwd`
- `env`
- `env_passthrough`
- `enabled`
- `fail_if_no_tools`

The checked-in server actually uses those config knobs:

- `--greeting-prefix` in `args` changes the greeting prefix
- `EXAMPLE_GREETING_STYLE` in `env` changes the greeting style
- `greeting_suffix.txt` is read relative to `cwd`

`env_passthrough` is included to show the safe opt-in pattern for forwarding a
host variable. The tutorial keeps tool output deterministic, so it does not
echo your `USER` value back in the greeting.

The checked-in config uses `python3`. If that is not available in your
environment, replace it in `.nexus3/mcp.json` with the interpreter path you
want NEXUS to launch.

Run it:

1. From this directory, start a clean REPL: `nexus3 --fresh`
2. In the REPL:
   - `/mcp connect hello_stdio --allow-all --private`
   - `/mcp tools hello_stdio`
3. Ask the agent: `Use the hello tool to greet Alice.`

If `nexus3` is not on your `PATH` but you are using the NEXUS3 source tree,
activate that virtualenv first or run `../../../../.venv/bin/nexus3 --fresh`
from this directory.

Omit the flags if you want to walk through the consent/share prompts manually.

If `/mcp` shows extra configured servers from global or ancestor config, ignore
them. This walkthrough only depends on `hello_stdio`.

Expected MCP tools:

- `mcp_hello_stdio_hello`
- `mcp_hello_stdio_add`

Expected greeting behavior:

- `/mcp connect hello_stdio --allow-all --private` should report
  `Connected to 'hello_stdio' (allow-all, private)`
- the greeting should include the configured prefix `Howdy`
- the greeting should include the suffix from `greeting_suffix.txt`
- the full response should read `Howdy, Alice! Welcome from the stdio example.`

Why `--fresh` is recommended here:

- it ensures you are using this folder's local `.nexus3/mcp.json`
- it avoids reusing an older session that was started from a different working
  directory

Good next tweaks:

- change `--greeting-prefix` in `.nexus3/mcp.json`
- change `EXAMPLE_GREETING_STYLE` from `friendly` to `formal`
- edit [greeting_suffix.txt](./greeting_suffix.txt)
- disconnect and reconnect after changes so NEXUS restarts the server

If it fails:

- if `nexus3` is not on your `PATH` and you are using the NEXUS3 source tree,
  use `../../../../.venv/bin/nexus3` from this directory or activate the
  source-tree virtualenv first
- make sure `python3` in `.nexus3/mcp.json` is the interpreter you expect
  NEXUS to launch
- keep JSON-RPC on stdout only; if you add debug prints, send them to stderr
- after changing tool definitions or config, reconnect so NEXUS relaunches the
  stdio subprocess
