#!/usr/bin/env python3
"""Codex hook entrypoint for codex-mnemosyne.

The runner intentionally has a zero-error contract: an unavailable optional
SDK or malformed hook payload must never block the host agent.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"


def _reexec_with_importable_sdk() -> None:
    """Keep old cached hook commands working after a Python environment split."""
    if os.environ.get("CODEX_MNEMOSYNE_REEXEC") == "1":
        return
    try:
        import mnemosyne  # noqa: F401
        return
    except Exception:
        pass

    resolver = ROOT / "bin" / "mnemosyne-resolve-python"
    if not resolver.is_file():
        return
    try:
        result = subprocess.run(
            [str(resolver)],
            check=False,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return
    python_path = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    if not python_path or Path(python_path).resolve() == Path(sys.executable).resolve():
        return
    environment = os.environ.copy()
    environment["CODEX_MNEMOSYNE_REEXEC"] = "1"
    os.execve(python_path, [python_path, __file__, *sys.argv[1:]], environment)


_reexec_with_importable_sdk()
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from codex_mnemosyne.adapter import UnavailableMemory, create_adapter
from codex_mnemosyne.config import Config, apply_config_env
from codex_mnemosyne.diagnostics import record as record_diagnostic
from codex_mnemosyne.hooks import (
    HookResult,
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


def _run(event: str, payload: dict[str, Any]):
    # Project-scoped Codex config is resolved from the hook payload's cwd.
    apply_config_env(os.environ, payload)
    config = Config.from_env(os.environ, payload)
    memory = _memory(config, payload)
    if event == "SessionStart":
        flushed = _flush_pending(config, payload, memory)
        result = handle_session_start(payload, config, memory)
        return HookResult(
            result.additional_context,
            result.enqueued,
            result.flushed + flushed[0],
            flushed[1],
        ), config, memory
    if event == "UserPromptSubmit":
        return handle_prompt(payload, config, memory), config, memory
    if event == "PostToolUse":
        outbox = Outbox(config.state_dir, config.session_id(payload))
        return handle_post_tool(payload, config, outbox), config, memory
    if event in WRITE_EVENTS:
        outbox = Outbox(config.state_dir, config.session_id(payload))
        return handle_write_event(event, payload, config, memory, outbox), config, memory
    return HookResult(), config, memory


def _flush_pending(config: Config, payload: dict[str, Any], memory) -> tuple[int, int]:
    outbox = Outbox(config.state_dir, config.session_id(payload))
    try:
        stats = outbox.flush(lambda entry: memory.remember(entry.content, entry.metadata))
        return stats.written, stats.remaining
    except Exception:
        return 0, len(outbox.pending())


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    event = args[0] if args else ""
    if event not in RECALL_EVENTS | {"PostToolUse"} | WRITE_EVENTS:
        return 0
    payload = _read_payload()
    try:
        result, config, memory = _run(event, payload)
        record_diagnostic(
            event,
            payload,
            config,
            context_chars=len(result.additional_context or ""),
            enqueued=result.enqueued,
            flushed=result.flushed,
            remaining=result.remaining,
            memory_available=not isinstance(memory, UnavailableMemory),
        )
        if result.additional_context and event in RECALL_EVENTS:
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": event,
                            "additionalContext": result.additional_context,
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
