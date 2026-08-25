#!/usr/bin/env python3
"""Codex hook entrypoint for codex-mnemosyne.

The runner intentionally has a zero-error contract: an unavailable optional
SDK or malformed hook payload must never block the host agent.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from codex_mnemosyne.adapter import MemoryUnavailable, UnavailableMemory, create_adapter
from codex_mnemosyne.config import Config
from codex_mnemosyne.hooks import (
    handle_post_tool,
    handle_prompt,
    handle_session_start,
    handle_write_event,
)
from codex_mnemosyne.outbox import Outbox


RECALL_EVENTS = {"SessionStart", "UserPromptSubmit"}
WRITE_EVENTS = {"Stop", "PreCompact", "SessionEnd"}


def _read_payload() -> dict[str, Any]:
    try:
        raw = sys.stdin.read()
        value = json.loads(raw) if raw.strip() else {}
        return value if isinstance(value, dict) else {}
    except (OSError, TypeError, ValueError):
        return {}


def _memory(config: Config, payload: dict[str, Any]):
    try:
        return create_adapter(config, payload)
    except Exception:
        return UnavailableMemory()


def _run(event: str, payload: dict[str, Any]) -> str | None:
    config = Config.from_env()
    memory = _memory(config, payload)
    if event == "SessionStart":
        _flush_pending(config, payload, memory)
        return handle_session_start(payload, config, memory).additional_context
    if event == "UserPromptSubmit":
        return handle_prompt(payload, config, memory).additional_context
    if event == "PostToolUse":
        outbox = Outbox(config.state_dir, config.session_id(payload))
        handle_post_tool(payload, config, outbox)
        return None
    if event in WRITE_EVENTS:
        outbox = Outbox(config.state_dir, config.session_id(payload))
        handle_write_event(event, payload, config, memory, outbox)
    return None


def _flush_pending(config: Config, payload: dict[str, Any], memory) -> None:
    outbox = Outbox(config.state_dir, config.session_id(payload))
    try:
        outbox.flush(lambda entry: memory.remember(entry.content, entry.metadata))
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    event = args[0] if args else ""
    if event not in RECALL_EVENTS | {"PostToolUse"} | WRITE_EVENTS:
        return 0
    payload = _read_payload()
    try:
        context = _run(event, payload)
        if context and event in RECALL_EVENTS:
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": event,
                            "additionalContext": context,
                        }
                    },
                    ensure_ascii=False,
                )
            )
    except Exception as exc:  # pragma: no cover - final host safety boundary
        if Config.from_env().debug:
            print(f"codex-mnemosyne hook ignored: {type(exc).__name__}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
