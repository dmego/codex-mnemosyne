"""Small, testable boundary around the optional Mnemosyne SDK."""

from __future__ import annotations

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
        if factory is None:
            try:
                from mnemosyne import Mnemosyne as factory
            except Exception as exc:  # pragma: no cover - depends on host installation
                raise MemoryUnavailable("Mnemosyne SDK is not importable") from exc

        self._memory = factory(
            session_id=self.config.session_id(self.payload),
            bank=self.config.bank,
            author_id=self.config.author_id,
            author_type=self.config.author_type,
            channel_id=self.config.project_name(self.payload),
        )
        return self._memory

    def recall(self, query: str, top_k: int) -> list[dict[str, object]]:
        result = self._load_memory().recall(query=query, top_k=top_k)
        return [dict(item) for item in result or []]

    def get_context(self, limit: int) -> list[dict[str, object]]:
        result = self._load_memory().get_context(limit=limit)
        return [dict(item) for item in result or []]

    def remember(self, content: str, metadata: dict[str, object]) -> str | None:
        payload = dict(metadata)
        payload.setdefault("project", self.config.project_name(self.payload))
        payload.setdefault("session_id", self.config.session_id(self.payload))
        return self._load_memory().remember(
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
