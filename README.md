# codex-mnemosyne

An open-source Codex plugin repository that packages the Mnemosyne integration as a native lifecycle plugin.

The installable plugin is under [`plugins/codex-mnemosyne`](./plugins/codex-mnemosyne). The repository root is also a Codex marketplace and contains the marketplace descriptor at [`.agents/plugins/marketplace.json`](./.agents/plugins/marketplace.json).

## Install from GitHub

```bash
codex plugin marketplace add https://github.com/dmego/codex-mnemosyne.git
codex plugin list --marketplace codex-mnemosyne --available
codex plugin add codex-mnemosyne@codex-mnemosyne
```

For local development, replace the GitHub URL with the checkout path:

```bash
codex plugin marketplace add /Users/dmego/vibeCoding/codex-mnemosyne
```

Then start a new Codex thread, enable the plugin, and review/trust its bundled hooks. The repository does not modify a user's existing `~/.codex/hooks.json`.

## Plugin contents

- Native Codex hooks for automatic `SessionStart`/`UserPromptSubmit` recall and `Stop`/`PreCompact`/`SessionEnd` capture.
- A standard-library Python SDK adapter for Mnemosyne with bounded context, secret filtering, durable outbox, and fail-open behavior.
- A bundled skill for explicit memory-management workflows.
- Optional MCP coexistence for manual deep search, correction, invalidation, deletion, diagnostics, and consolidation.

See [`plugins/codex-mnemosyne/README.md`](./plugins/codex-mnemosyne/README.md) for configuration, privacy boundaries, tests, and the automatic-vs-manual capability split.
