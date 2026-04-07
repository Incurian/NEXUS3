# 202 Capabilities Example

Do this after the 101 examples.

This example shows the next step after a tools-only server: one Python server
that exposes tools, resources, and prompts together so you can see exactly how
NEXUS treats each surface.

Files:

- [capability_server.py](/home/inc/repos/NEXUS3/docs/references/mcp-python-examples/202-capabilities/capability_server.py)
- [inspect_capabilities.py](/home/inc/repos/NEXUS3/docs/references/mcp-python-examples/202-capabilities/inspect_capabilities.py)
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

The checked-in config uses `python3`. If that is not available on your machine,
replace it in `.nexus3/mcp.json` with the interpreter path that exists on your
machine.

Run it:

1. `cd /home/inc/repos/NEXUS3/docs/references/mcp-python-examples/202-capabilities`
2. `nexus3 --fresh`
3. In the REPL:
   - `/mcp connect capability_demo --allow-all --private`
   - `/mcp tools capability_demo`
   - `/mcp resources capability_demo`
   - `/mcp prompts capability_demo`
4. Ask the agent: `Use the customer count tool.`

Omit the flags if you want to walk through the consent/share prompts manually.

Expected:

- tools become callable NEXUS tools
- resources remain readable MCP resources
- prompts remain fetchable MCP prompts

What to look for specifically:

- `/mcp tools capability_demo` should show the two callable tools
- `/mcp resources capability_demo` should show `config://app/settings` and
  `docs://customer-table`
- `/mcp prompts capability_demo` should show `customer_summary` and
  `schema_explainer`
- the customer count tool should report `128`, proving that `args` reached the
  server

Important NEXUS behavior:

- only the tools become normal agent-callable NEXUS tools
- resources and prompts stay in the MCP connection and are not automatically
  converted into agent tools
- the current REPL gives you discovery commands for resources/prompts; the
  companion 202 guide shows the underlying `resources/read` and `prompts/get`
  methods that the MCP client layer uses

Optional deeper check:

1. `cd /home/inc/repos/NEXUS3`
2. `.venv/bin/python docs/references/mcp-python-examples/202-capabilities/inspect_capabilities.py`

That helper launches the checked-in capability example through NEXUS's Python
MCP client and proves all of these in one pass:

- `tools/list`
- `resources/list`
- `prompts/list`
- `resources/read` for `config://app/settings` and `docs://customer-table`
- `prompts/get` for `customer_summary`

If it fails:

- make sure `python3` in `.nexus3/mcp.json` is the interpreter that exists on
  your machine
- remember that resources/prompts showing up in `/mcp` but not as normal agent
  tools is expected NEXUS behavior
- if you want the agent to call resource/prompt-backed behavior directly, add a
  tool wrapper around it
