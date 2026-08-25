"""Tolerant parser for Codex rollout JSONL transcripts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


SYSTEM_TAGS = (
    "environment_context",
    "turn_aborted",
    "user_instructions",
    "apps_instructions",
    "plugins_instructions",
    "skills_instructions",
    "collaboration_mode",
)
TEXT_BLOCK_TYPES = {"input_text", "output_text", "text"}


@dataclass(frozen=True)
class TranscriptEvent:
    index: int
    event_type: str
    payload: dict[str, Any]
    timestamp: str | None = None


@dataclass(frozen=True)
class Turn:
    role: str
    text: str
    index: int
    timestamp: str | None


@dataclass(frozen=True)
class Exchange:
    user_text: str
    assistant_text: str
    assistant_index: int


def read_events(path: Path) -> list[TranscriptEvent]:
    events: list[TranscriptEvent] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return events

    for index, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except (TypeError, ValueError):
            continue
        if not isinstance(raw, dict):
            continue
        payload = raw.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        events.append(
            TranscriptEvent(
                index=index,
                event_type=str(raw.get("type") or ""),
                payload=payload,
                timestamp=str(raw.get("timestamp")) if raw.get("timestamp") else None,
            )
        )
    return events


def _collect_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    chunks = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") in TEXT_BLOCK_TYPES and isinstance(block.get("text"), str):
            chunks.append(block["text"])
    return "\n".join(chunks).strip()


def _is_injected_system_turn(text: str) -> bool:
    trimmed = text.lstrip()
    return any(trimmed.startswith(f"<{tag}>") or trimmed.startswith(f"<{tag} ") for tag in SYSTEM_TAGS)


def _message_turn(event: TranscriptEvent) -> Turn | None:
    if event.event_type != "response_item" or event.payload.get("type") != "message":
        return None
    role = event.payload.get("role")
    if role not in {"user", "assistant"}:
        return None
    text = _collect_text(event.payload.get("content"))
    if not text or (role == "user" and _is_injected_system_turn(text)):
        return None
    return Turn(role=str(role), text=text, index=event.index, timestamp=event.timestamp)


def turns_from_events(events: Iterable[TranscriptEvent], cursor: int = 0) -> list[Turn]:
    turns: list[Turn] = []
    for event in events:
        if event.index <= cursor:
            continue
        turn = _message_turn(event)
        if turn is not None:
            turns.append(turn)
    return turns


def new_turns(path: Path, cursor: int) -> tuple[list[Turn], int]:
    events = read_events(path)
    next_cursor = max((event.index for event in events), default=cursor)
    return turns_from_events(events, cursor), max(cursor, next_cursor)


def latest_exchange(turns: Sequence[Turn]) -> Exchange | None:
    assistant_position = next((i for i in range(len(turns) - 1, -1, -1) if turns[i].role == "assistant"), None)
    if assistant_position is None:
        return None
    assistant = turns[assistant_position]
    user_text = ""
    for index in range(assistant_position - 1, -1, -1):
        if turns[index].role == "user":
            user_text = turns[index].text
            break
    return Exchange(user_text=user_text, assistant_text=assistant.text, assistant_index=assistant.index)
