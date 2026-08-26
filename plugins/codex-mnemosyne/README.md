# codex-mnemosyne

Portable Codex native-plugin integration for [Mnemosyne](https://github.com/gandazgul/mnemosyne). It makes Mnemosyne participate in the Codex lifecycle instead of waiting for the model to call an MCP tool manually.

## What it does

| Hook | Behavior |
| --- | --- |
| `SessionStart` | Loads a bounded recent context block. |
| `UserPromptSubmit` | Recalls memories relevant to the current prompt and injects `additionalContext`. |
| `PostToolUse` | Queues only meaningful edit/test/build observations; read-only noise is skipped. |
| `Stop` | Captures the latest filtered user/assistant exchange and flushes the outbox. |
| `PreCompact` | Flushes transcript changes before context compaction. |
| `SessionEnd` | Performs a final capture/flush when the host provides a transcript path. |

The automatic path imports the Mnemosyne SDK directly. The plugin also bundles an optional
`mnemosyne` MCP server from `.mcp.json` for explicit memory management. Automatic recall and
capture never depend on the model deciding to call MCP; they remain usable even when the MCP
extra is not installed.

The bundled bridge exposes all 36 Mnemosyne 3.12.x tool schemas: remember/recall, batch mutations,
stats/sleep, update/invalidate/forget, import/export, diagnostics, scratchpad, canonical facts,
temporal triples, graph, shared surface, sync, persona, and hygiene. Mnemosyne 3.12.x publishes
those 36 schemas but registers only 28 dispatch handlers upstream. The bridge delegates registered
tools through Mnemosyne's public dispatcher and owns the missing/bug-fixed handlers without
modifying the user's Mnemosyne installation. Unconfigured sync returns `not_configured` instead of
claiming a successful sync.

## Requirements

- Codex with plugin lifecycle hooks enabled and hook trust approved.
- Python 3.10 or newer available to the hook command.
- The selected Python environment must be able to import `mnemosyne`.
- The same environment needs the `mcp` package to enable the bundled MCP server (automatic hooks do not need it).
- No network service is required by this plugin. Mnemosyne decides whether its own embedding or extraction configuration uses local or remote services.

The hook entrypoint (`bin/mnemosyne-hook.py`, or the `bin/mnemosyne-hook`
launcher for manual runs) selects a Python that can actually import Mnemosyne.
It checks `CODEX_MNEMOSYNE_PYTHON`, the plugin-local `.venv`, the Mnemosyne CLI
shebang, PATH Python, and common macOS Conda locations. Set the override when
you want an explicit runtime:

```bash
export CODEX_MNEMOSYNE_PYTHON=/opt/anaconda3/bin/python
```

Install Mnemosyne into that environment:

```bash
python3 -m pip install "mnemosyne-memory>=3.11.1,<4"

# Optional MCP transport dependency:
python3 -m pip install "mnemosyne-memory[mcp]>=3.11.1,<4"
```

If your Mnemosyne checkout is not published to the environment yet, install it
from its source checkout instead and keep the resulting interpreter on the
hook `PATH`. The plugin deliberately does not bundle Mnemosyne or its optional
embedding/LLM dependencies; it fails open when the SDK is unavailable.

To see exactly what Codex will use, run:

```bash
bin/mnemosyne-doctor
```

The report includes the resolved Python, Mnemosyne import path/version, bank,
state/data directories, detected SDK methods, and MCP import availability. A
missing SDK is reported explicitly by the doctor even though normal hooks
continue to fail open.

## Local plugin installation

This directory is the installable plugin source. The repository root already contains a Codex marketplace descriptor, so install the plugin from GitHub or from the checkout:

Repository source path: `plugins/codex-mnemosyne/`.

```bash
codex plugin marketplace add https://github.com/dmego/codex-mnemosyne.git
codex plugin list --marketplace codex-mnemosyne --available
codex plugin add codex-mnemosyne@codex-mnemosyne

# Or use the checkout directly:
codex plugin marketplace add /Users/dmego/vibeCoding/codex-mnemosyne
codex plugin add codex-mnemosyne@codex-mnemosyne
```

Restart Codex after enabling it and approve the plugin hooks. Start a new task
to pick up updated MCP tools. Do not replace an existing `~/.codex/hooks.json`;
Codex merges plugin hooks with user hooks. For an existing local checkout, use
the normal `read_marketplace_name.py`, `update_plugin_cachebuster.py`, and
`codex plugin add` update flow rather than editing `~/.codex/config.toml`.

For a source checkout outside this path, the hook commands use `$PLUGIN_ROOT`, so the plugin can be moved without editing the hook file.

## Configuration

The plugin reads only its own `CODEX_MNEMOSYNE_*` variables and passes Mnemosyne's native variables through unchanged.

| Variable | Default | Meaning |
| --- | --- | --- |
| `CODEX_MNEMOSYNE_BANK` | `MNEMOSYNE_MCP_BANK`, then `default` | Mnemosyne bank. |
| `CODEX_MNEMOSYNE_PYTHON` | auto-detected | Optional Python executable used by the hooks. |
| `CODEX_MNEMOSYNE_AUTHOR_ID` | `codex` | Author identity. |
| `CODEX_MNEMOSYNE_SCOPE` | `global` | `global` or `session` auto-write scope. |
| `CODEX_MNEMOSYNE_STATE_DIR` | `PLUGIN_DATA`, then `~/.codex/mnemosyne` | Hook outbox and cursor state; not the Mnemosyne database. |
| `CODEX_MNEMOSYNE_RECALL_TOP_K` | `5` | Maximum results per recall. |
| `CODEX_MNEMOSYNE_RECALL_MAX_CHARS` | `6000` | Maximum injected context size. |
| `CODEX_MNEMOSYNE_AUTO_RECALL` | `true` | Enable SessionStart/UserPromptSubmit recall. |
| `CODEX_MNEMOSYNE_AUTO_CAPTURE` | `true` | Enable Stop/PreCompact/SessionEnd capture. |
| `CODEX_MNEMOSYNE_AUTO_TOOL_CAPTURE` | `true` | Enable high-signal PostToolUse observations. |
| `CODEX_MNEMOSYNE_EXTRACT` | `false` | Pass `extract=True` to Mnemosyne for structured fact extraction. |
| `CODEX_MNEMOSYNE_EXTRACT_ENTITIES` | `false` | Pass `extract_entities=True` to Mnemosyne. |
| `CODEX_MNEMOSYNE_DIAGNOSTICS` | `false` | Write content-free lifecycle evidence to `diagnostics.jsonl` under the plugin state directory. |

The MCP server uses Mnemosyne's native `MNEMOSYNE_MCP_BANK` (falling back to
`CODEX_MNEMOSYNE_BANK`) so manual tools and automatic hooks can target the same
bank. Database paths remain controlled by `MNEMOSYNE_DATA_DIR`/`HERMES_HOME`
and Mnemosyne's bank resolver.

Codex's documented plugin-scoped MCP table controls enablement and tool policy;
it does not reliably inject a nested `env` table into the child process. This
plugin's launchers therefore also read the following optional config file block
and merge it with process environment values (process values win):

```toml
[plugins."codex-mnemosyne@codex-mnemosyne".mcp_servers.mnemosyne.env]
MNEMOSYNE_MCP_BANK = "coding"
MNEMOSYNE_AUTHOR_ID = "codex"
```

The same block is read by lifecycle hooks and the bundled MCP bridge. A
top-level `[mcp_servers.mnemosyne.env]` block is also accepted. The resolved
source is shown by `bin/mnemosyne-doctor`.

The Mnemosyne database location remains controlled by `MNEMOSYNE_DATA_DIR` and Mnemosyne's own bank resolver. The plugin never assumes a local path.
Automatic recall is filtered by a stable hash of the current project path, so memories captured in another project are not returned by default. The path itself is never stored as a channel value.

## Privacy and failure behavior

- The plugin rejects common `secret`, API key, token, password, Bearer, and private-key patterns before automatic capture.
- It never stores full tool output or Codex-injected system context.
- Context and captures are bounded; short acknowledgements are ignored.
- Hook errors are fail-open and return exit code `0`, so a missing SDK or locked database cannot block Codex.
- Failed writes remain in the local JSONL outbox and retry on a later lifecycle event.
- Each queued write records its project channel and Mnemosyne bank; legacy entries without bank routing are held rather than written to the active bank.
- The outbox is plain text. Store it in a protected local directory and do not sync it publicly.
- When diagnostics are enabled, only event names, path-free session/project identifiers, context length, queue counts, and availability flags are recorded; prompts, responses, memory content, cwd, and secrets are never written.

## Tests

Tests use an in-memory fake Mnemosyne boundary and temporary state directories. They do not access the user's Mnemosyne database or network.

```bash
cd /Users/dmego/vibeCoding/codex-mnemosyne
PYTHONPATH=src python3 -m unittest discover -v
python3 -m compileall -q src bin
```

## Manual hook smoke test

```bash
printf '%s\n' '{"session_id":"demo","cwd":"/tmp/demo","prompt":"What do we know about the build?"}' \
  | bin/mnemosyne-hook UserPromptSubmit
```

When Mnemosyne is not installed in any discovered Python environment, the
command exits cleanly with no context output. Use `bin/mnemosyne-doctor` to
distinguish an empty bank from an unavailable SDK.

### MCP stdio smoke

The plugin's `.mcp.json` starts `./bin/mnemosyne-mcp`. The launcher selects a
Python that can import both `mnemosyne` and `mcp`, then runs Mnemosyne's native
stdio MCP server:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke","version":"1"}}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  | bin/mnemosyne-mcp
```

## Design references

The lifecycle and queue design is informed by the Codex integrations in [memX](https://github.com/NeoLi00/memX) and [codex-honcho](https://github.com/plastic-labs/codex-honcho), while using Mnemosyne's own hybrid recall, deduplication, entity/fact extraction, scope, veracity, trust tier, and sleep APIs.
