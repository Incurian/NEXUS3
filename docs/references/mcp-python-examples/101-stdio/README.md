# 101 Stdio Example

Start here if this is your first MCP server.

This is the smallest example that still teaches the NEXUS-specific pieces that
usually trip people up:

- how a stdio MCP server talks to NEXUS
- how `command`, `args`, `cwd`, `env`, and `env_passthrough` show up in a real
  `mcp.json`
- how an MCP tool named `hello` becomes the NEXUS tool
  `mcp_hello_stdio_hello`

Files:

- [hello_stdio_server.py](/home/inc/repos/NEXUS3/docs/references/mcp-python-examples/101-stdio/hello_stdio_server.py)
- [mcp.json](/home/inc/repos/NEXUS3/docs/references/mcp-python-examples/101-stdio/.nexus3/mcp.json)

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

The checked-in config uses `python3`. If that is not available on your machine,
replace it in `.nexus3/mcp.json` with the interpreter path that exists on your
machine.

Run it:

1. `cd /home/inc/repos/NEXUS3/docs/references/mcp-python-examples/101-stdio`
2. `nexus3 --fresh`
3. In the REPL:
   - `/mcp connect hello_stdio --allow-all --private`
   - `/mcp tools hello_stdio`
4. Ask the agent: `Use the hello tool to greet Alice.`

Omit the flags if you want to walk through the consent/share prompts manually.

Expected MCP tools:

- `mcp_hello_stdio_hello`
- `mcp_hello_stdio_add`

Expected greeting behavior:

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
- edit [greeting_suffix.txt](/home/inc/repos/NEXUS3/docs/references/mcp-python-examples/101-stdio/greeting_suffix.txt)
- disconnect and reconnect after changes so NEXUS restarts the server
