# 101 HTTP Example

Files:

- [hello_http_server.py](/home/inc/repos/NEXUS3/docs/references/mcp-python-examples/101-http/hello_http_server.py)
- [mcp.json](/home/inc/repos/NEXUS3/docs/references/mcp-python-examples/101-http/.nexus3/mcp.json)

Run it:

1. `cd /home/inc/repos/NEXUS3/docs/references/mcp-python-examples/101-http`
2. In one terminal: `python hello_http_server.py`
3. In another terminal: `nexus3`
4. In the REPL:
   - `/mcp connect hello_http --allow-all --private`
   - `/mcp tools hello_http`

This example listens on `http://127.0.0.1:8765/mcp`. Omit the flags if you
want to walk through the consent/share prompts manually.

If `python` is not on your `PATH`, use the interpreter path that exists on your
machine when you start `hello_http_server.py`.

Expected MCP tools:

- `mcp_hello_http_hello`
- `mcp_hello_http_add`
