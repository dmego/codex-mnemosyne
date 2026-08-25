---
name: mnemosyne-memory
description: Use for manual deep Mnemosyne recall, explicit memory storage, correction, or forgetting. Automatic lifecycle hooks already perform bounded recall and turn capture.
---

# Mnemosyne memory

This plugin provides automatic memory through Codex lifecycle hooks:

- `SessionStart` loads a small recent context block.
- `UserPromptSubmit` recalls memories relevant to the current prompt.
- `Stop`, `PreCompact`, and `SessionEnd` capture filtered durable turn results.

MCP is optional in this plugin. Use the Mnemosyne MCP tools only when a
Mnemosyne MCP server is already configured and the task requires explicit
search, inspection, correction, invalidation, deletion, diagnostics, or
consolidation. Automatic hooks do not call MCP. If MCP is not configured,
automatic recall/capture still works through the SDK, while those manual deep
operations should be reported as unavailable rather than guessed. Do not save
secrets, raw credentials, full tool output, or transient progress. A memory
that is corrected should be invalidated or updated rather than duplicated.

The automatic path uses the configured Mnemosyne bank and SDK directly; it does
not depend on the model deciding to call an MCP tool. If the SDK is unavailable,
hooks fail open and pending writes remain in the local outbox for a later retry.
