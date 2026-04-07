# 101 HTTP Example

Do this after the stdio example.

This example keeps the tool surface simple and changes only the transport. It
shows that NEXUS can talk to an MCP server over plain JSON-RPC HTTP `POST`
without introducing SSE or a larger framework.

The server script uses only the Python standard library. It is also
deliberately stateless: it never returns `mcp-session-id`, so the example can
stay focused on plain request/response HTTP.

In shell commands below, replace `<repo-root>` with the path to your NEXUS3
checkout.

Files:

- [hello_http_server.py](/home/inc/repos/NEXUS3/docs/references/mcp-python-examples/101-http/hello_http_server.py)
- [mcp.json](/home/inc/repos/NEXUS3/docs/references/mcp-python-examples/101-http/.nexus3/mcp.json)

Run it:

1. `cd <repo-root>/docs/references/mcp-python-examples/101-http`
2. In one terminal: `python3 hello_http_server.py`
3. In another terminal: `nexus3 --fresh`
4. In the REPL:
   - `/mcp connect hello_http --allow-all --private`
   - `/mcp tools hello_http`
5. Ask the agent: `Use the add tool to compute 41 + 1.`

If `nexus3` is not on your `PATH`, run `<repo-root>/.venv/bin/nexus3 --fresh`
in the second terminal instead.

This example listens on `http://127.0.0.1:9876/mcp`. Omit the flags if you
want to walk through the consent/share prompts manually.

If `python3` is not on your `PATH`, use the interpreter path that exists on
your machine when you start `hello_http_server.py`.

Expected MCP tools:

- `mcp_hello_http_hello`
- `mcp_hello_http_add`

Important transport lesson:

- for HTTP entries, `url` is the key NEXUS setting
- `command`, `cwd`, `env`, and `env_passthrough` are stdio-specific and usually
  do not belong in this kind of entry
- the example uses `9876` specifically so it does not collide with NEXUS's own
  default embedded RPC port `8765`

If you change the port in the server, keep `.nexus3/mcp.json` in sync.

If it fails:

- if you are running from this repo checkout and `nexus3` is not on your
  `PATH`, use `<repo-root>/.venv/bin/nexus3` or activate the repo virtualenv
  first
- keep the `python3 hello_http_server.py` terminal open while NEXUS connects
- make sure the server URL in `.nexus3/mcp.json` still matches the server's
  host, port, and `/mcp` path
- if you changed the port, avoid `8765` unless you also changed NEXUS's own
  embedded RPC port
