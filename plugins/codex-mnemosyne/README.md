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

The automatic path imports the Mnemosyne SDK directly. MCP is optional: it is useful for explicit search, inspection, update, invalidation, deletion, diagnostics, and consolidation, but it is not required for automatic recall or capture. If no Mnemosyne MCP server is configured, the automatic path remains fully usable.

## Requirements

- Codex with plugin lifecycle hooks enabled and hook trust approved.
- Python 3.10 or newer available to the hook command.
- The selected Python environment must be able to import `mnemosyne`.
- No network service is required by this plugin. Mnemosyne decides whether its own embedding or extraction configuration uses local or remote services.

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

Restart Codex after enabling it and approve the plugin hooks. Do not replace an existing `~/.codex/hooks.json`; Codex merges plugin hooks with user hooks.

For a source checkout outside this path, the hook commands use `$PLUGIN_ROOT`, so the plugin can be moved without editing the hook file.

## Configuration

The plugin reads only its own `CODEX_MNEMOSYNE_*` variables and passes Mnemosyne's native variables through unchanged.

| Variable | Default | Meaning |
| --- | --- | --- |
| `CODEX_MNEMOSYNE_BANK` | `MNEMOSYNE_MCP_BANK`, then `default` | Mnemosyne bank. |
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

The Mnemosyne database location remains controlled by `MNEMOSYNE_DATA_DIR` and Mnemosyne's own bank resolver. The plugin never assumes a local path.

## Privacy and failure behavior

- The plugin rejects common `secret`, API key, token, password, Bearer, and private-key patterns before automatic capture.
- It never stores full tool output or Codex-injected system context.
- Context and captures are bounded; short acknowledgements are ignored.
- Hook errors are fail-open and return exit code `0`, so a missing SDK or locked database cannot block Codex.
- Failed writes remain in the local JSONL outbox and retry on a later lifecycle event.
- The outbox is plain text. Store it in a protected local directory and do not sync it publicly.

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
  | python3 bin/mnemosyne-hook.py UserPromptSubmit
```

When Mnemosyne is not installed in that Python environment, the command exits cleanly with no context output.

## Design references

The lifecycle and queue design is informed by the Codex integrations in [memX](https://github.com/NeoLi00/memX) and [codex-honcho](https://github.com/plastic-labs/codex-honcho), while using Mnemosyne's own hybrid recall, deduplication, entity/fact extraction, scope, veracity, trust tier, and sleep APIs.
