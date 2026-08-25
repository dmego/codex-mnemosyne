"""Codex lifecycle handlers; all handlers are deliberately fail-open."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .adapter import MemoryPort
from .config import Config
from .filtering import contains_secret, should_capture
from .outbox import MemoryEntry, Outbox
from .rendering import render_memories
from .transcript import latest_exchange, new_turns


@dataclass(frozen=True)
class HookResult:
    additional_context: str | None = None


def _value(payload: Mapping[str, object], *names: str) -> object:
    for name in names:
        if payload.get(name) is not None:
            return payload[name]
    return None


def _recall(memory: MemoryPort, query: str, top_k: int) -> list[dict[str, object]]:
    try:
        return memory.recall(query, top_k)
    except Exception:
        return []


def _context(memory: MemoryPort, limit: int) -> list[dict[str, object]]:
    try:
        return memory.get_context(limit)
    except Exception:
        return []


def handle_session_start(payload: Mapping[str, object], config: Config, memory: MemoryPort) -> HookResult:
    if not config.auto_recall:
        return HookResult()
    rendered = render_memories(_context(memory, config.recall_top_k), config.recall_max_chars)
    return HookResult(rendered or None)


def handle_prompt(payload: Mapping[str, object], config: Config, memory: MemoryPort) -> HookResult:
    if not config.auto_recall:
        return HookResult()
    prompt = str(_value(payload, "prompt", "user_prompt", "userPrompt") or "").strip()
    if not prompt:
        return HookResult()
    rendered = render_memories(_recall(memory, prompt, config.recall_top_k), config.recall_max_chars)
    return HookResult(rendered or None)


READ_ONLY_COMMANDS = (
    "cd ", "ls", "pwd", "echo", "cat ", "head ", "tail ", "which ", "type ",
    "grep ", "rg ", "find ", "fd ", "wc ", "sed ", "awk ", "stat ", "file ",
    "tree ", "du ", "df ", "env", "printf ", "sort ", "uniq ", "cut ",
    "git status", "git log", "git diff", "git show", "git branch",
)
SHELL_TOOLS = {"bash", "shell", "local_shell", "exec", "exec_command"}
EDIT_MARKERS = ("apply_patch", "edit", "write", "create", "replace", "update", "insert")


def _command(tool_input: object) -> str:
    if not isinstance(tool_input, Mapping):
        return ""
    command = tool_input.get("command")
    if isinstance(command, list):
        return " ".join(str(item) for item in command)
    return str(command or "").strip()


def summarize_tool(payload: Mapping[str, object]) -> str:
    name = str(_value(payload, "tool_name", "toolName", "name") or "").strip()
    lowered = name.casefold()
    if not name or "mnemosyne" in lowered:
        return ""
    tool_input = _value(payload, "tool_input", "toolInput", "input")
    if lowered in SHELL_TOOLS or lowered.endswith("shell"):
        command = _command(tool_input)
        if not command or any(command == item.rstrip() or command.startswith(item) for item in READ_ONLY_COMMANDS):
            return ""
        summary = f"ran: {command[:240]}"
        return "" if contains_secret(summary) else summary
    if any(marker in lowered for marker in EDIT_MARKERS):
        files = []
        raw = json_like_text(tool_input)
        files.extend(match.group(1) for match in re.finditer(r"(?:File:|path[\"']?\s*[:=])\s*([^\n\"']+)", raw, re.I))
        summary = f"edited: {', '.join(files[:5])}" if files else f"used {name}"
        return "" if contains_secret(summary) else summary
    return ""


def json_like_text(value: object) -> str:
    if isinstance(value, Mapping):
        return " ".join(f"{key}: {item}" for key, item in value.items())
    return str(value or "")


def handle_post_tool(payload: Mapping[str, object], config: Config, outbox: Outbox) -> HookResult:
    if not config.auto_tool_capture:
        return HookResult()
    summary = summarize_tool(payload)
    if summary:
        outbox.enqueue(MemoryEntry(summary, {"kind": "tool", "project": config.project_name(payload)}))
    return HookResult()


def _transcript_path(payload: Mapping[str, object]) -> Path | None:
    value = _value(payload, "transcript_path", "transcriptPath")
    if not value:
        return None
    return Path(str(value)).expanduser()


def _capture_content(payload: Mapping[str, object], config: Config, assistant: str, user: str) -> str:
    project = config.project_name(payload)
    pieces = [f"Project: {project}"]
    if user and not contains_secret(user):
        pieces.append(f"Task: {user[:2000]}")
    pieces.append(f"Result: {assistant[:config.capture_max_chars]}")
    content = "\n".join(pieces)
    return content[: config.capture_max_chars]


def handle_write_event(
    event_name: str,
    payload: Mapping[str, object],
    config: Config,
    memory: MemoryPort,
    outbox: Outbox,
) -> HookResult:
    if config.auto_capture:
        path = _transcript_path(payload)
        if path is not None:
            turns, cursor = new_turns(path, outbox.read_cursor())
            exchange = latest_exchange(turns)
            if exchange and should_capture(exchange.assistant_text, config):
                content = _capture_content(payload, config, exchange.assistant_text, exchange.user_text)
                if not contains_secret(content):
                    outbox.enqueue(
                        MemoryEntry(
                            content,
                            {
                                "kind": "turn",
                                "event": event_name,
                                "project": config.project_name(payload),
                                "event_index": exchange.assistant_index,
                            },
                        )
                    )
            outbox.write_cursor(cursor)
    try:
        outbox.flush(lambda entry: memory.remember(entry.content, entry.metadata))
    except Exception:
        pass
    return HookResult()
