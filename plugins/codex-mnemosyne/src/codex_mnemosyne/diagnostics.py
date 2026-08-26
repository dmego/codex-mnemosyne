"""Opt-in, content-free diagnostics for proving lifecycle hook execution."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from .config import Config


def record(
    event: str,
    payload: Mapping[str, object],
    config: Config,
    *,
    context_chars: int = 0,
    enqueued: int = 0,
    flushed: int = 0,
    remaining: int = 0,
    memory_available: bool = True,
    error: str | None = None,
) -> None:
    """Append one redacted lifecycle fact when diagnostics are enabled.

    The file deliberately contains no prompt, response, memory content,
    absolute cwd, token, or exception text.  It is intended for local A/B
    verification that Codex invoked a hook and received a context length.
    """
    if not config.diagnostics:
        return
    try:
        config.state_dir.mkdir(parents=True, exist_ok=True)
        item = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "session_id": config.session_id(payload),
            "project": config.project_name(payload),
            "context_chars": max(0, int(context_chars)),
            "enqueued": max(0, int(enqueued)),
            "flushed": max(0, int(flushed)),
            "remaining": max(0, int(remaining)),
            "memory_available": bool(memory_available),
        }
        if error:
            item["error_type"] = str(error).split(":", 1)[0][:80]
        path = config.state_dir / "diagnostics.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except (OSError, TypeError, ValueError):
        return
