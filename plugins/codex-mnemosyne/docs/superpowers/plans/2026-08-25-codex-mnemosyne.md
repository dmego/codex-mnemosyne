# codex-mnemosyne Implementation Plan

> **For agentic workers:** Implement this plan task-by-task with the test-first cycle. The repository root is a Codex marketplace; the installable plugin lives at `plugins/codex-mnemosyne/`.

**Goal:** Build a portable Codex native plugin that automatically recalls Mnemosyne context before turns and captures durable turn memory after turns without relying on model-initiated MCP calls.

**Architecture:** A Python standard-library hook runner receives Codex lifecycle JSON on stdin. It routes read hooks to a lazy Mnemosyne SDK adapter and write hooks through a deduplicating JSONL outbox, with bounded formatting, transcript filtering, and fail-open behavior. Codex MCP remains an optional manual interface outside the automatic path.

**Tech Stack:** Python 3.10+ standard library, optional Mnemosyne Python SDK at runtime, Codex `.codex-plugin/plugin.json`, Codex `hooks/hooks.json`, `unittest`.

**Spec:** `docs/superpowers/specs/2026-08-25-codex-mnemosyne-design.md`

## Global Constraints

- No production dependency beyond Python 3.10+ standard library; Mnemosyne is imported lazily at runtime.
- No hard-coded local Python path, bank, data directory, embedding endpoint, API key, or absolute project path.
- Hook failures are fail-open and must never block a Codex turn.
- Automatic recall is bounded to 5 records and 6KB by default.
- Automatic capture filters secrets, short responses, injected system text, and read-only tool noise.
- Automatic recall treats stored content as untrusted reference data and applies project-channel filtering.
- SessionStart replays pending outbox entries from earlier sessions.
- Existing user hooks are outside this repository and must not be overwritten by plugin files.
- Tests must not touch the user’s Mnemosyne database or require network access.

---

### Task 1: Runtime configuration and adapter contract

**Files:**
- Create: `src/codex_mnemosyne/config.py`
- Create: `src/codex_mnemosyne/adapter.py`
- Create: `src/codex_mnemosyne/__init__.py`
- Test: `tests/test_config_adapter.py`

**Interfaces:**
- `Config.from_env(env: Mapping[str, str] | None = None) -> Config`
- `Config.session_id(payload: Mapping[str, object]) -> str`
- `MnemosyneAdapter.recall(query: str, top_k: int) -> list[dict[str, object]]`
- `MnemosyneAdapter.get_context(limit: int) -> list[dict[str, object]]`
- `MnemosyneAdapter.remember(content: str, metadata: dict[str, object]) -> str | None`
- `create_adapter(config: Config, payload: Mapping[str, object]) -> MemoryPort`

- [ ] **Step 1: Write failing tests** for environment precedence (`CODEX_MNEMOSYNE_BANK` over `MNEMOSYNE_MCP_BANK` over `default`), bounded numeric values, stable session identity, and lazy import failure returning a safe adapter error.
- [ ] **Step 2: Run `python -m unittest tests.test_config_adapter -v` and verify the tests fail because the modules do not exist.**
- [ ] **Step 3: Implement the dataclass config and a `MemoryPort` protocol. Resolve bank, author, scope, limits, state directory, and feature flags without reading machine-specific defaults. Implement the real adapter with lazy `from mnemosyne import Mnemosyne`; pass bank, session_id, author_id, author_type, channel_id, and Mnemosyne remember options through the adapter boundary.
- [ ] **Step 4: Re-run the focused tests and verify all configuration and adapter contract tests pass.**
- [ ] **Step 5: Run `python -m compileall -q src` as a syntax checkpoint.**

### Task 2: Transcript parsing, filtering, and bounded rendering

**Files:**
- Create: `src/codex_mnemosyne/transcript.py`
- Create: `src/codex_mnemosyne/filtering.py`
- Create: `src/codex_mnemosyne/rendering.py`
- Test: `tests/test_transcript_filtering.py`

**Interfaces:**
- `read_events(path: Path) -> list[TranscriptEvent]`
- `new_turns(path: Path, cursor: int) -> tuple[list[Turn], int]`
- `latest_exchange(turns: Sequence[Turn]) -> Exchange | None`
- `should_capture(text: str, config: Config) -> bool`
- `contains_secret(text: str) -> bool`
- `render_memories(results: Sequence[Mapping[str, object]], max_chars: int) -> str`

- [ ] **Step 1: Write failing tests** with Codex-style JSONL fixtures covering user/assistant messages, malformed lines, injected `<environment_context>` and `<user_instructions>`, tool/reasoning events, cursor advancement, secret patterns, short responses, and rendering limits.
- [ ] **Step 2: Run the focused test module and verify expected failures.**
- [ ] **Step 3: Implement tolerant JSONL parsing that skips malformed/non-message events, strips injected system turns, selects the latest user/assistant exchange, and returns the next event cursor.
- [ ] **Step 4: Implement redaction predicates for credentials and bounded context rendering with stable metadata labels and no absolute paths.
- [ ] **Step 5: Re-run tests and confirm all parser/filter/renderer behavior passes.**

### Task 3: Durable outbox and hook orchestration

**Files:**
- Create: `src/codex_mnemosyne/outbox.py`
- Create: `src/codex_mnemosyne/hooks.py`
- Test: `tests/test_outbox_hooks.py`

**Interfaces:**
- `Outbox(state_dir: Path, key: str)`
- `Outbox.enqueue(entry: MemoryEntry) -> bool`
- `Outbox.flush(writer: Callable[[MemoryEntry], object]) -> FlushStats`
- `handle_session_start(payload, config, memory) -> HookResult`
- `handle_prompt(payload, config, memory) -> HookResult`
- `handle_post_tool(payload, config, outbox) -> HookResult`
- `handle_write_event(event_name, payload, config, memory, outbox) -> HookResult`
- `HookResult.additional_context: str | None`

- [ ] **Step 1: Write failing tests** for exact-content deduplication, atomic JSONL append, failed writer retention, successful flush removal, high-signal tool summaries, skipping Mnemosyne self-calls, prompt recall injection, transcript capture only once per cursor, and fail-open behavior when the adapter raises.
- [ ] **Step 2: Run the focused tests and verify they fail for missing outbox/orchestration behavior.**
- [ ] **Step 3: Implement the outbox with a hash key, atomic rewrite after successful writes, lock directory with stale-lock recovery, and compact JSON entries. Implement hook handlers that never print diagnostics to stdout.
- [ ] **Step 4: Implement SessionStart `get_context`, UserPromptSubmit `recall`, PostToolUse observation enqueue, and Stop/PreCompact/SessionEnd transcript enqueue plus flush. Use configured `scope`, `source`, `importance`, `extract`, `extract_entities`, `veracity`, and `trust_tier` values.
- [ ] **Step 5: Re-run tests and verify all orchestration branches pass, including the failure paths.**

### Task 4: Codex plugin packaging and executable hook runner

**Files:**
- Create: `.codex-plugin/plugin.json`
- Create: `hooks/hooks.json`
- Create: `bin/mnemosyne-hook.py`
- Create: `skills/mnemosyne-memory/SKILL.md`
- Test: `tests/test_hook_runner.py`

**Interfaces:**
- CLI: `python bin/mnemosyne-hook.py <SessionStart|UserPromptSubmit|PostToolUse|Stop|PreCompact|SessionEnd>`
- stdin: one Codex hook JSON object
- stdout for recall events: `{"hookSpecificOutput":{"hookEventName":"...","additionalContext":"..."}}`
- stdout for write/observe events: empty
- exit code: always `0` for malformed input, missing SDK, or runtime errors

- [ ] **Step 1: Write failing subprocess tests** for SessionStart/UserPromptSubmit JSON output, empty output for write hooks, malformed stdin, unknown event, and exit-zero fail-open behavior using a fake adapter mode.
- [ ] **Step 2: Run the runner tests and verify the expected failures.**
- [ ] **Step 3: Implement the runner’s `sys.path` setup, stdin decoding, event dispatch, JSON output contract, and exception boundary. Keep all logs on stderr and only when explicitly enabled.
- [ ] **Step 4: Add the native manifest and hook mappings using `$PLUGIN_ROOT`, `${PLUGIN_ROOT}` Windows commands, timeouts, and status messages only for recall events. Add the skill with manual deep-recall/store guidance and automatic-hook behavior.
- [ ] **Step 5: Re-run subprocess tests and validate JSON manifests with Python’s JSON parser.**

### Task 5: Documentation, install/config guidance, and full verification

**Files:**
- Create: `README.md`
- Create: `README.zh-CN.md`
- Create: `pyproject.toml`
- Create: `tests/__init__.py`
- Modify: `docs/superpowers/specs/2026-08-25-codex-mnemosyne-design.md` only if verification finds a design mismatch

- [ ] **Step 1: Write a documentation smoke test** that checks the README contains portable installation, required runtime, configuration precedence, bank/data directory behavior, privacy boundaries, hook trust/restart guidance, and manual MCP coexistence.
- [ ] **Step 2: Run the documentation test and verify it fails before the README exists.**
- [ ] **Step 3: Implement README files with local marketplace/plugin installation examples, environment variable table, event matrix, failure behavior, troubleshooting, and a note that no real database is touched by tests.
- [ ] **Step 4: Add `pyproject.toml` with Python floor, package discovery, and unittest/pytest-compatible test configuration without runtime dependencies.
- [ ] **Step 5: Run the complete verification set:** `python -m unittest discover -v`, `python -m compileall -q src bin`, JSON parse for both manifests, shell-level hook smoke tests with fake adapter, and a dry-run configuration report that never prints secret values.
- [ ] **Step 6: Review the full tree, run `git diff --check` if a repository is present, and compare every acceptance criterion in the design document against fresh command output before reporting completion.**
