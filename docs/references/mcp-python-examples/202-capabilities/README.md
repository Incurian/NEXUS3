# 202 Capabilities Example

Files:

- [capability_server.py](/home/inc/repos/NEXUS3/docs/references/mcp-python-examples/202-capabilities/capability_server.py)
- [mcp.json](/home/inc/repos/NEXUS3/docs/references/mcp-python-examples/202-capabilities/.nexus3/mcp.json)

This example's `mcp.json` shows the fuller stdio-oriented config surface:

- `command` + `args`
- `cwd`
- `env`
- `env_passthrough`
- `enabled`
- `fail_if_no_tools`

The checked-in server uses those values in real behavior:

- `--customer-count` in `args` drives the `get_customer_count` tool
- `CAPABILITY_EXAMPLE_MODE` and `CAPABILITY_ENVIRONMENT` in `env` show up in
  the settings resource
- `customer_table.md` is read relative to `cwd`

If `python` is not on your `PATH`, replace it in `.nexus3/mcp.json` with the
interpreter path that exists on your machine.

Run it:

1. `cd /home/inc/repos/NEXUS3/docs/references/mcp-python-examples/202-capabilities`
2. `nexus3`
3. In the REPL:
   - `/mcp connect capability_demo --allow-all --private`
   - `/mcp tools capability_demo`
   - `/mcp resources capability_demo`
   - `/mcp prompts capability_demo`

Omit the flags if you want to walk through the consent/share prompts manually.

Expected:

- tools become callable NEXUS tools
- resources remain readable MCP resources
- prompts remain fetchable MCP prompts
