# MCP Python Example Projects

These folders are the hands-on companion to the Python MCP guides for NEXUS3.

Use them when you want two things at once:

- a gentle, runnable first example
- a NEXUS-specific reference for what `mcp.json`, `/mcp connect`, and MCP
  capability surfaces actually look like in practice

They are comprehensive for NEXUS's MCP integration path, not for the broader
Python MCP SDK/framework ecosystem. The examples intentionally hand-roll the
protocol with the Python standard library so the NEXUS-specific transport,
config, and REPL behavior stays visible.

## What You Need

- a working `python3` on your `PATH` for the checked-in example servers
- a runnable `nexus3` CLI for the REPL walkthroughs:
  - if `nexus3` is already on your `PATH`, use that
  - if you are working from the NEXUS3 source tree, activate that virtualenv
    before you `cd` into an example directory
- a NEXUS3 source tree plus `.venv` if you want to use the optional
  NEXUS-client inspection helper in the 202 example
- no extra Python MCP package is required for the checked-in example servers;
  they use only the Python standard library

## Recommended order

1. Start with
   [101-stdio](./101-stdio/README.md).
   It is the smallest local server and the easiest path to a first success.
2. Then try
   [101-http](./101-http/README.md).
   It keeps the same tool surface but changes the transport to HTTP.
3. Finish with
   [202-capabilities](./202-capabilities/README.md).
   It adds resources and prompts so you can see how NEXUS treats each MCP
   surface differently, and it includes an optional deeper check that exercises
   `resources/read` and `prompts/get` through NEXUS's own Python MCP client.

## What Is In Each Example

Each example is a small standalone project:

- the server code lives at the top level
- the NEXUS MCP config lives in the hidden directory `./.nexus3/mcp.json`
- the folder is meant to be launched directly, not copied piecemeal

That means the normal workflow is:

1. `cd` into one example directory
2. start a clean REPL with `nexus3 --fresh`
3. connect the configured server from the REPL
4. inspect the exposed tools, resources, or prompts

If you are using the NEXUS3 source tree rather than an installed `nexus3`
command, activate that virtualenv first.

Using `--fresh` matters for tutorials because it avoids confusion from an older
session that was started in a different directory with different MCP config.

If you run `/mcp` first and see extra configured servers, that is normal.
NEXUS merges MCP config from global, ancestor, and local layers. For this
bundle, the example-specific server names are `hello_stdio`, `hello_http`, and
`capability_demo`.

## NEXUS-Specific Notes

- These examples assume you start NEXUS from the example directory itself.
  The local `./.nexus3/mcp.json` file is then the active project-local MCP
  layer.
- The stdio examples use `cwd: "."` on purpose so you can see how relative
  files like `greeting_suffix.txt` and `customer_table.md` resolve.
- The stdio examples default to `python3`, which is a stronger default for
  Linux, macOS, and WSL. If your interpreter lives somewhere else, replace the
  command in `mcp.json` with the interpreter path available in your
  environment.
- Only MCP tools become callable agent tools in NEXUS. Resources and prompts
  remain MCP-native surfaces that you inspect separately with `/mcp resources`
  and `/mcp prompts`.
- The current REPL is a discovery surface for resources and prompts. If you
  want to exercise `resources/read` or `prompts/get` directly, use the optional
  helper in the 202 example from a NEXUS3 source tree.

## Companion Guides

The full walkthrough docs are mirrored alongside these examples so the example
bundle is self-contained:

- [MCP-SERVER-PYTHON-101.md](./MCP-SERVER-PYTHON-101.md)
- [MCP-SERVER-PYTHON-202.md](./MCP-SERVER-PYTHON-202.md)
- [TOOL-SURFACE-DESIGN-GUIDELINES.md](./TOOL-SURFACE-DESIGN-GUIDELINES.md)

If you are already reading the main repo docs, the canonical copies also live
under [docs/references/](../).
