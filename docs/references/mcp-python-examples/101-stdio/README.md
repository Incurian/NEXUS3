# 101 Stdio Example

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

If `python` is not on your `PATH`, replace it in `.nexus3/mcp.json` with the
interpreter path that exists on your machine.

Run it:

1. `cd /home/inc/repos/NEXUS3/docs/references/mcp-python-examples/101-stdio`
2. `nexus3`
3. In the REPL:
   - `/mcp connect hello_stdio --allow-all --private`
   - `/mcp tools hello_stdio`

Omit the flags if you want to walk through the consent/share prompts manually.

Expected MCP tools:

- `mcp_hello_stdio_hello`
- `mcp_hello_stdio_add`
