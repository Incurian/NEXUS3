# Dependency License And Telemetry Audit (2026-03-10)

## Executive Summary

Verdict:

- **MIT compatibility:** yes, with normal third-party notice obligations.
- **Telemetry / phone-home risk:** **low**, with no evidence of unsolicited
  telemetry in the installed Python packages audited here.

High-confidence findings:

- No GPL, LGPL, AGPL, SSPL, or similar strong copyleft licenses were present
  in the tracked Python dependency surface or the installed `.venv` closure
  audited here.
- The only licenses that need more attention than plain MIT/BSD/Apache are:
  - `certifi` (`MPL-2.0`, runtime transitive)
  - `pathspec` (`MPL-2.0`, dev transitive)
  - `typing_extensions` (`PSF-2.0`, runtime + dev transitive)
  - `aiohappyeyeballs` (`PSF-2.0`, dev transitive)
- I found no analytics SDKs, no hardcoded telemetry vendors, and no
  import/startup update checks in the installed dependency sources.
- The most important non-license issue is **dependency drift**:
  - `websockets` still appears in installed editable metadata but not in the
    current repo manifest or code
  - `aiohttp` was confirmed as an intentional MCP HTTP test-server dependency
    and has now been restored to the `dev` and `ci` extras in
    [pyproject.toml](/home/inc/repos/NEXUS3/pyproject.toml)

## Scope

Included:

- tracked Python dependency manifest:
  [pyproject.toml](/home/inc/repos/NEXUS3/pyproject.toml)
- installed Python distributions under:
  `/home/inc/repos/NEXUS3/.venv/lib/python3.11/site-packages`
- runtime, dev, CI, and build dependency review
- license compatibility and notice-obligation review
- local source-level telemetry / unsolicited network behavior review

Excluded:

- untracked local editor-extension state under
  [editors](/home/inc/repos/NEXUS3/editors)
- untracked root [package-lock.json](/home/inc/repos/NEXUS3/package-lock.json),
  which is empty and not part of the committed project surface
- provider services themselves (OpenAI, Anthropic, OpenRouter, etc.) beyond the
  client libraries used locally

## Method

Local evidence:

- parsed [pyproject.toml](/home/inc/repos/NEXUS3/pyproject.toml)
- enumerated installed distributions from `.venv` via `importlib.metadata`
- inspected local `METADATA`, license classifiers, and bundled
  `LICENSE` / `COPYING` files under `*.dist-info`
- grep-reviewed installed sources for telemetry / analytics / update-check /
  phone-home patterns
- verified NEXUS's own `jsonschema` usage in
  [validation.py](/home/inc/repos/NEXUS3/nexus3/core/validation.py)
  and [base.py](/home/inc/repos/NEXUS3/nexus3/skill/base.py)

Upstream spot checks:

- official PyPI metadata pages for key direct and special-case dependencies
- official `jsonschema` documentation on remote reference retrieval
- official Pydantic docs search results around Logfire marketing

Important limitation:

- This is an engineering audit, not formal legal advice. It is good enough to
  drive packaging and policy decisions, but not a substitute for counsel if you
  plan to ship a commercial binary bundle with curated third-party notices.

## Dependency Inventory

Tracked direct dependencies from [pyproject.toml](/home/inc/repos/NEXUS3/pyproject.toml):

- runtime: `httpx`, `jsonschema`, `rich`, `prompt-toolkit`, `pydantic`,
  `python-dotenv`
- dev: `aiohttp`, `pytest`, `pytest-asyncio`, `pytest-cov`, `pytest-xdist`,
  `ruff`, `mypy`, `watchfiles`
- CI: same as dev minus `watchfiles`
- build: `hatchling`

Installed environment drift:

- installed editable
  [METADATA](/home/inc/repos/NEXUS3/.venv/lib/python3.11/site-packages/nexus3-0.1.0.dist-info/METADATA)
  still declares:
  - `websockets>=13.0` as a base requirement
  - `aiohttp>=3.9.0` as a `dev` extra
- editable install provenance is confirmed by
  [direct_url.json](/home/inc/repos/NEXUS3/.venv/lib/python3.11/site-packages/nexus3-0.1.0.dist-info/direct_url.json)

Repo-level drift interpretation:

- `websockets` looks like stale metadata. I found no references under
  `nexus3/`, `tests/`, `README.md`, `CLAUDE.md`, or `AGENTS.md`.
- `aiohttp` is intentional and not stale. It is still imported in
  [http_server.py](/home/inc/repos/NEXUS3/nexus3/mcp/test_server/http_server.py:103)
  and
  [test_mcp_client.py](/home/inc/repos/NEXUS3/tests/integration/test_mcp_client.py:298),
  and is still discussed in
  [mcp/README.md](/home/inc/repos/NEXUS3/nexus3/mcp/README.md:757). The
  manifest has now been updated to declare it in the `dev` and `ci` extras.

## License Findings

### Overall Compatibility

I found **no license that blocks NEXUS3 from being MIT-licensed**.

The current dependency set is compatible with an MIT-licensed project, but the
following obligations remain relevant:

- `MPL-2.0` components require preserving the MPL license text and keeping
  modified covered files available under MPL if you redistribute modified
  versions of those files.
- `PSF-2.0` components are permissive, but still require retaining notices and,
  for distributed derivatives, noting changes.
- Apache/BSD-style components remain compatible but should still be included in
  a third-party notices bundle if you distribute packaged artifacts.

### Runtime Closure

Runtime closure reachable from the six declared runtime roots:

```text
annotated-types           0.7.0     MIT
anyio                     4.12.1    MIT
attrs                     25.4.0    MIT
certifi                   2026.1.4  MPL-2.0
h11                       0.16.0    MIT
httpcore                  1.0.9     BSD-3-Clause
httpx                     0.28.1    BSD-3-Clause
idna                      3.11      BSD-3-Clause
jsonschema                4.26.0    MIT
jsonschema-specifications 2025.9.1  MIT
markdown-it-py            4.0.0     MIT
mdurl                     0.1.2     MIT
prompt_toolkit            3.0.52    BSD-3-Clause
pydantic                  2.12.5    MIT
pydantic_core             2.41.5    MIT
Pygments                  2.19.2    BSD-2-Clause
python-dotenv             1.2.1     BSD-3-Clause
referencing               0.37.0    MIT
rich                      14.3.2    MIT
rpds-py                   0.30.0    MIT
typing-inspection         0.4.2     MIT
typing_extensions         4.15.0    PSF-2.0
wcwidth                   0.5.3     MIT
```

Special runtime obligations:

- `certifi` is `MPL-2.0`
- `typing_extensions` is `PSF-2.0`

### Dev / Build Closure

Installed dev/test closure audited locally:

```text
aiohappyeyeballs | 2.6.1 | PSF-2.0
aiohttp          | 3.13.3 | Apache-2.0 AND MIT
aiosignal        | 1.4.0 | Apache-2.0
anyio            | 4.12.1 | MIT
attrs            | 25.4.0 | MIT
coverage         | 7.13.3 | Apache-2.0
execnet          | 2.1.2 | MIT
frozenlist       | 1.8.0 | Apache-2.0
idna             | 3.11 | BSD-3-Clause
iniconfig        | 2.3.0 | MIT
librt            | 0.7.8 | MIT
multidict        | 6.7.1 | Apache-2.0
mypy             | 1.19.1 | MIT primary; wheel also ships Apache-2.0 typeshed LICENSE
mypy_extensions  | 1.1.0 | MIT
packaging        | 26.0 | Apache-2.0 OR BSD-2-Clause
pathspec         | 1.0.4 | MPL-2.0
pluggy           | 1.6.0 | MIT
propcache        | 0.4.1 | Apache-2.0
Pygments         | 2.19.2 | BSD-2-Clause
pytest           | 9.0.2 | MIT
pytest-asyncio   | 1.3.0 | Apache-2.0
pytest-cov       | 7.0.0 | MIT
pytest-xdist     | 3.8.0 | MIT
ruff             | 0.15.0 | MIT
typing_extensions| 4.15.0 | PSF-2.0
watchfiles       | 1.1.1 | MIT
yarl             | 1.22.0 | Apache-2.0
```

Build backend:

- `hatchling` is declared in
  [pyproject.toml](/home/inc/repos/NEXUS3/pyproject.toml:63)
  but is not installed in the current `.venv`, so I could not perform the same
  local artifact audit. Upstream PyPI metadata describes it as MIT-licensed:
  <https://pypi.org/project/hatchling/>

### Ambiguous Or Metadata-Light Cases

These were resolved from bundled license files, not clean SPDX metadata:

- `prompt_toolkit`: generic `BSD License` metadata, but bundled license text is
  BSD-3-Clause
- `python-dotenv`: metadata-light, bundled text is BSD-3-Clause
- `jsonschema`, `jsonschema-specifications`, `referencing`, `rpds-py`:
  bundled `COPYING` / `LICENSE` text is MIT
- `pathspec`: classifier + bundled license resolve to `MPL-2.0`
- `ruff`: classifier + bundled license resolve to MIT
- `typing_extensions`: bundled PSF license text resolves to `PSF-2.0`
- `websockets` (installed drift package): bundled license text is BSD-3-Clause

## Telemetry And Network Behavior Findings

### Bottom Line

I found **no evidence of unsolicited telemetry or analytics** in the installed
direct or transitive Python packages reviewed here.

Specifically, source inspection found:

- no `sentry`, `segment`, `posthog`, `mixpanel`, `amplitude`, `datadog`,
  `newrelic`, or similar telemetry vendor endpoints
- no import-time or startup version-check behavior
- no hidden analytics SDK wiring in the direct runtime or dev packages

The networking-capable libraries in this environment appear to behave as normal
transport primitives:

- `httpx`
- `httpcore`
- `aiohttp`
- `websockets`
- `execnet`
- `anyio`

These can obviously open network connections when NEXUS or a caller uses them,
but I found no evidence that they phone home on their own.

### Notable Caveats

#### `jsonschema` Remote Reference Retrieval

Installed `jsonschema` contains code paths that can retrieve remote `$ref`
targets over HTTP(S):

- local installed source:
  [validators.py#L108](/home/inc/repos/NEXUS3/.venv/lib/python3.11/site-packages/jsonschema/validators.py#L108)
- official docs:
  <https://python-jsonschema.readthedocs.io/en/v4.18.6/referencing/>
  and
  <https://python-jsonschema.readthedocs.io/en/v4.25.1/_modules/jsonschema/validators/>

Important nuance:

- this is **not telemetry**
- it is **conditional outbound retrieval based on schema content**
- for current NEXUS usage, it appears **theoretical rather than active**

Why it looks theoretical here:

- NEXUS calls `jsonschema.validate()` against local in-memory schema dicts in
  [validation.py](/home/inc/repos/NEXUS3/nexus3/core/validation.py:115),
  [base.py](/home/inc/repos/NEXUS3/nexus3/skill/base.py:116),
  and [base.py](/home/inc/repos/NEXUS3/nexus3/skill/base.py:222)
- I found no repo use of `RefResolver`, custom remote registries, or remote
  `$ref` handling in NEXUS code

#### `pytest --pastebin`

Installed `pytest` contains an opt-in pastebin uploader, but it is only used
when the user explicitly passes `--pastebin`:

- local installed source:
  [pastebin.py#L24](/home/inc/repos/NEXUS3/.venv/lib/python3.11/site-packages/_pytest/pastebin.py#L24)
  and
  [pastebin.py#L67](/home/inc/repos/NEXUS3/.venv/lib/python3.11/site-packages/_pytest/pastebin.py#L67)

This is explicit user-triggered behavior, not unsolicited phone-home behavior.

#### `Pygments` Maintainer Update Helpers

Installed `Pygments` ships helper scripts that fetch upstream data, but they
sit behind `if __name__ == "__main__"` paths and are not part of normal runtime
behavior:

- [_mysql_builtins.py#L1234](/home/inc/repos/NEXUS3/.venv/lib/python3.11/site-packages/pygments/lexers/_mysql_builtins.py#L1234)
- [_postgres_builtins.py#L630](/home/inc/repos/NEXUS3/.venv/lib/python3.11/site-packages/pygments/lexers/_postgres_builtins.py#L630)
- [_lua_builtins.py#L177](/home/inc/repos/NEXUS3/.venv/lib/python3.11/site-packages/pygments/lexers/_lua_builtins.py#L177)

#### `execnet` Transport Primitives

`execnet` supports explicit `ssh=` and `socket=` gateways:

- [multi.py#L126](/home/inc/repos/NEXUS3/.venv/lib/python3.11/site-packages/execnet/multi.py#L126)
- [gateway_socket.py#L99](/home/inc/repos/NEXUS3/.venv/lib/python3.11/site-packages/execnet/gateway_socket.py#L99)

This is explicit transport functionality, not hidden telemetry.

#### Pydantic / Logfire

Official Pydantic docs currently promote Logfire as a separate monitoring
product:

- <https://docs.pydantic.dev/latest/>

However, local source inspection of the installed `pydantic` and
`pydantic_core` packages found no telemetry or `logfire` hooks in the package
code currently installed in this `.venv`.

## Risk Assessment

### License Risk

- **Compatibility risk:** low
- **Notice / compliance risk:** medium-low

Why:

- MIT licensing for NEXUS3 is fine with the current set
- the real work is administrative:
  - preserve third-party license texts
  - do not forget MPL/PSF obligations when redistributing bundled artifacts
  - if you ship binaries, wheels, or app bundles, include a third-party notices
    file

### Telemetry Risk

- **Telemetry / analytics risk:** low
- **Unexpected outbound network risk:** low overall

Primary caveat:

- `jsonschema` can retrieve remote schemas if used that way, but current NEXUS
  usage does not appear to trigger that path

## Recommended Actions

1. Refresh the editable environment later.
   - Reinstall the editable environment or recreate `.venv` so installed
     `nexus3` metadata matches the current
     [pyproject.toml](/home/inc/repos/NEXUS3/pyproject.toml).
   - This is intentionally deferred for now; the audit only records the
     mismatch and the follow-up.

2. Keep `websockets` out unless it returns to actual code use.
   - Right now it looks like stale installed metadata rather than a real active
     dependency.

3. Add a third-party notices file before broader distribution.
   - Include at least MPL, PSF, Apache, BSD, and MIT texts/references for the
     shipped dependency set.

4. Treat remote JSON Schema references as disallowed unless explicitly needed.
   - Current code already appears to stay on local inline schemas; keep it that
      way.

## Upstream Sources Checked

- `httpx` PyPI: <https://pypi.org/project/httpx/>
- `jsonschema` PyPI: <https://pypi.org/project/jsonschema/>
- `rich` PyPI: <https://pypi.org/project/rich/>
- `prompt-toolkit` PyPI: <https://pypi.org/project/prompt-toolkit/>
- `python-dotenv` PyPI: <https://pypi.org/project/python-dotenv/>
- `certifi` PyPI: <https://pypi.org/project/certifi/>
- `pathspec` PyPI: <https://pypi.org/project/pathspec/>
- `pytest-asyncio` PyPI: <https://pypi.org/project/pytest-asyncio/>
- `hatchling` PyPI: <https://pypi.org/project/hatchling/>
- `jsonschema` remote retrieval docs:
  <https://python-jsonschema.readthedocs.io/en/v4.18.6/referencing/>
- `jsonschema` validator source docs:
  <https://python-jsonschema.readthedocs.io/en/v4.25.1/_modules/jsonschema/validators/>
- Pydantic docs:
  <https://docs.pydantic.dev/latest/>
