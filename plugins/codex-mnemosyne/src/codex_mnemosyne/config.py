"""Environment-driven configuration for the Codex Mnemosyne plugin."""

from __future__ import annotations

import os
import re
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


def _first_non_empty(env: Mapping[str, str], *names: str, default: str) -> str:
    for name in names:
        value = env.get(name, "").strip()
        if value:
            return value
    return default


def _bounded_int(env: Mapping[str, str], name: str, default: int, lower: int, upper: int) -> int:
    try:
        value = int(env.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(lower, min(upper, value))


def _bounded_float(env: Mapping[str, str], name: str, default: float, lower: float, upper: float) -> float:
    try:
        value = float(env.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(lower, min(upper, value))


def _flag(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "off", "no", "disabled"}


def _safe_slug(value: str, default: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return value.strip("-.") or default


@dataclass(frozen=True)
class Config:
    """Resolved plugin settings.

    Mnemosyne's own environment variables remain untouched. This object only
    controls the Codex integration and passes the selected bank through to the
    SDK.
    """

    bank: str
    author_id: str
    author_type: str
    scope: str
    source: str
    importance: float
    recall_top_k: int
    recall_max_chars: int
    item_max_chars: int
    capture_min_chars: int
    capture_max_chars: int
    state_dir: Path
    auto_recall: bool
    auto_capture: bool
    auto_tool_capture: bool
    extract: bool
    extract_entities: bool
    veracity: str
    trust_tier: str
    debug: bool

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        values = dict(os.environ if env is None else env)
        scope = _first_non_empty(values, "CODEX_MNEMOSYNE_SCOPE", default="global").lower()
        if scope not in {"session", "global"}:
            scope = "global"

        state_dir = Path(
            _first_non_empty(
                values,
                "CODEX_MNEMOSYNE_STATE_DIR",
                "PLUGIN_DATA",
                default=str(Path.home() / ".codex" / "mnemosyne"),
            )
        ).expanduser()

        return cls(
            bank=_first_non_empty(values, "CODEX_MNEMOSYNE_BANK", "MNEMOSYNE_MCP_BANK", default="default"),
            author_id=_first_non_empty(
                values,
                "CODEX_MNEMOSYNE_AUTHOR_ID",
                "MNEMOSYNE_AUTHOR_ID",
                default="codex",
            ),
            author_type=_first_non_empty(
                values,
                "CODEX_MNEMOSYNE_AUTHOR_TYPE",
                "MNEMOSYNE_AUTHOR_TYPE",
                default="agent",
            ),
            scope=scope,
            source=_first_non_empty(values, "CODEX_MNEMOSYNE_SOURCE", default="codex-auto"),
            importance=_bounded_float(values, "CODEX_MNEMOSYNE_IMPORTANCE", 0.4, 0.0, 1.0),
            recall_top_k=_bounded_int(values, "CODEX_MNEMOSYNE_RECALL_TOP_K", 5, 1, 20),
            recall_max_chars=_bounded_int(values, "CODEX_MNEMOSYNE_RECALL_MAX_CHARS", 6000, 512, 24000),
            item_max_chars=_bounded_int(values, "CODEX_MNEMOSYNE_ITEM_MAX_CHARS", 1500, 128, 8000),
            capture_min_chars=_bounded_int(values, "CODEX_MNEMOSYNE_CAPTURE_MIN_CHARS", 80, 10, 2000),
            capture_max_chars=_bounded_int(values, "CODEX_MNEMOSYNE_CAPTURE_MAX_CHARS", 12000, 256, 40000),
            state_dir=state_dir,
            auto_recall=_flag(values, "CODEX_MNEMOSYNE_AUTO_RECALL", True),
            auto_capture=_flag(values, "CODEX_MNEMOSYNE_AUTO_CAPTURE", True),
            auto_tool_capture=_flag(values, "CODEX_MNEMOSYNE_AUTO_TOOL_CAPTURE", True),
            extract=_flag(values, "CODEX_MNEMOSYNE_EXTRACT", False),
            extract_entities=_flag(values, "CODEX_MNEMOSYNE_EXTRACT_ENTITIES", False),
            veracity=_first_non_empty(values, "CODEX_MNEMOSYNE_VERACITY", default="unknown"),
            trust_tier=_first_non_empty(values, "CODEX_MNEMOSYNE_TRUST_TIER", default="EXTERNAL_WRITE"),
            debug=_flag(values, "CODEX_MNEMOSYNE_DEBUG", False),
        )

    def session_id(self, payload: Mapping[str, object]) -> str:
        """Return a stable, path-free session identifier."""
        raw_session = str(
            payload.get("session_id")
            or payload.get("sessionId")
            or payload.get("conversation_id")
            or payload.get("conversationId")
            or "unknown"
        )
        cwd = str(payload.get("cwd") or payload.get("projectFolder") or os.getcwd())
        project = _safe_slug(Path(cwd).name, "workspace")
        return f"{project}:{_safe_slug(raw_session, 'unknown')}"

    def project_name(self, payload: Mapping[str, object]) -> str:
        cwd = str(payload.get("cwd") or payload.get("projectFolder") or os.getcwd())
        return _safe_slug(Path(cwd).name, "workspace")

    def project_channel(self, payload: Mapping[str, object]) -> str:
        """Return a stable, non-path channel key for project-isolated recall."""
        cwd = str(payload.get("cwd") or payload.get("projectFolder") or os.getcwd())
        digest = hashlib.sha256(str(Path(cwd).expanduser().resolve()).encode("utf-8")).hexdigest()[:16]
        return f"codex-project:{digest}"
