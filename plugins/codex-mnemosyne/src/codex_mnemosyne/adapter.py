"""Small, testable boundary around the optional Mnemosyne SDK."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Mapping, Protocol

from .config import Config


class MemoryPort(Protocol):
    def recall(self, query: str, top_k: int) -> list[dict[str, object]]: ...

    def get_context(self, limit: int) -> list[dict[str, object]]: ...

    def remember(self, content: str, metadata: dict[str, object]) -> str | None: ...


class MemoryUnavailable(RuntimeError):
    """Raised internally when the optional SDK cannot be loaded."""


class MnemosyneAdapter:
    """Lazy SDK adapter that keeps hook code independent from Mnemosyne internals."""

    def __init__(
        self,
        config: Config,
        payload: Mapping[str, object],
        memory_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config
        self.payload = payload
        self._memory_factory = memory_factory
        self._memory: Any | None = None

    def _load_memory(self) -> Any:
        if self._memory is not None:
            return self._memory
        factory = self._memory_factory
        self._memory = self._new_memory(
            factory,
            self.config.session_id(self.payload),
            self.config.project_channel(self.payload),
            self.config.bank,
        )
        return self._memory

    def _new_memory(
        self,
        factory: Callable[..., Any] | None,
        session_id: str,
        channel_id: str,
        bank: str,
    ) -> Any:
        if factory is None:
            try:
                from mnemosyne import Mnemosyne as factory
            except ImportError:
                try:
                    from mnemosyne.core.memory import Mnemosyne as factory
                except Exception as exc:  # pragma: no cover - depends on host installation
                    raise MemoryUnavailable("Mnemosyne SDK is not importable") from exc
            except Exception as exc:  # pragma: no cover - depends on host installation
                raise MemoryUnavailable("Mnemosyne SDK is not importable") from exc

        return factory(
            session_id=session_id,
            bank=bank,
            author_id=self.config.author_id,
            author_type=self.config.author_type,
            channel_id=channel_id,
        )

    def recall(self, query: str, top_k: int) -> list[dict[str, object]]:
        try:
            result = self._load_memory().recall(
                query=query,
                top_k=top_k,
                channel_id=self.config.project_channel(self.payload),
            )
        except TypeError as exc:
            if "channel_id" not in str(exc):
                raise
            raise MemoryUnavailable("Mnemosyne SDK lacks project channel filtering") from exc
        return [dict(item) for item in result or []]

    def get_context(self, limit: int) -> list[dict[str, object]]:
        memory = self._load_memory()
        connection = getattr(getattr(memory, "beam", None), "conn", None)
        if connection is None:
            result = memory.get_context(limit=limit)
            return [dict(item) for item in result or []]

        columns = ("id", "content", "source", "timestamp", "importance", "scope", "last_recalled")
        now = datetime.now().isoformat()
        channel_id = self.config.project_channel(self.payload)
        session_id = self.config.session_id(self.payload)
        rows = connection.execute(
            """
            SELECT id, content, source, timestamp, importance, scope, last_recalled
            FROM working_memory
            WHERE (valid_until IS NULL OR valid_until > ?)
              AND superseded_by IS NULL
              AND consolidated_at IS NULL
              AND (
                    (scope = 'global' AND (channel_id = ? OR channel_id IS NULL))
                 OR (COALESCE(scope, '') != 'global' AND session_id = ?
                     AND (channel_id = ? OR channel_id IS NULL))
              )
            ORDER BY
                CASE WHEN scope = 'global' THEN 0 ELSE 1 END,
                importance DESC,
                timestamp DESC
            LIMIT ?
            """,
            (now, channel_id, session_id, channel_id, max(0, int(limit)),),
        ).fetchall()
        return [dict(row) if hasattr(row, "keys") else dict(zip(columns, row)) for row in rows]

    def remember(self, content: str, metadata: dict[str, object]) -> str | None:
        payload = dict(metadata)
        payload.setdefault("project", self.config.project_name(self.payload))
        payload.setdefault("session_id", self.config.session_id(self.payload))
        payload.setdefault("channel_id", self.config.project_channel(self.payload))
        is_plugin_entry = payload.get("kind") in {"turn", "tool"}
        if is_plugin_entry and not payload.get("bank"):
            raise MemoryUnavailable("legacy outbox entry has no bank routing")
        target_session = str(payload["session_id"])
        target_channel = str(payload["channel_id"])
        target_bank = str(payload.get("bank") or self.config.bank)
        current_session = self.config.session_id(self.payload)
        current_channel = self.config.project_channel(self.payload)
        memory = self._load_memory()
        if (
            target_session != current_session
            or target_channel != current_channel
            or target_bank != self.config.bank
        ):
            memory = self._new_memory(
                self._memory_factory,
                target_session,
                target_channel,
                target_bank,
            )
        return memory.remember(
            content=content,
            source=self.config.source,
            importance=self.config.importance,
            metadata=payload,
            scope=self.config.scope,
            extract_entities=self.config.extract_entities,
            extract=self.config.extract,
            veracity=self.config.veracity,
            trust_tier=self.config.trust_tier,
        )


class UnavailableMemory:
    """Fail-open port used by the runner when Mnemosyne is unavailable."""

    def recall(self, query: str, top_k: int) -> list[dict[str, object]]:
        return []

    def get_context(self, limit: int) -> list[dict[str, object]]:
        return []

    def remember(self, content: str, metadata: dict[str, object]) -> str | None:
        raise MemoryUnavailable("Mnemosyne SDK is not importable")


def create_adapter(config: Config, payload: Mapping[str, object]) -> MemoryPort:
    """Create the real adapter; callers should catch ``MemoryUnavailable``."""
    return MnemosyneAdapter(config, payload)
