"""Small durable JSONL outbox used by write-side hooks."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator


@dataclass(frozen=True)
class MemoryEntry:
    content: str
    metadata: dict[str, object]

    @property
    def fingerprint(self) -> str:
        raw = json.dumps(
            {"content": self.content, "metadata": self.metadata},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def as_dict(self) -> dict[str, object]:
        return {
            "fingerprint": self.fingerprint,
            "content": self.content,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "MemoryEntry | None":
        content = raw.get("content")
        metadata = raw.get("metadata")
        if not isinstance(content, str) or not content.strip() or not isinstance(metadata, dict):
            return None
        return cls(content=content, metadata=dict(metadata))


@dataclass(frozen=True)
class FlushStats:
    written: int
    failed: int
    remaining: int


class Outbox:
    """A per-session queue with deduplication and crash-safe rewrites."""

    LOCK_STALE_SECONDS = 120
    LOCK_WAIT_SECONDS = 1.0

    def __init__(self, state_dir: Path, key: str) -> None:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
        self.root = Path(state_dir).expanduser()
        self.outbox_dir = self.root / "outbox"
        self.cursor_dir = self.root / "cursors"
        self.path = self.outbox_dir / f"{digest}.jsonl"
        self.cursor_path = self.cursor_dir / f"{digest}.cursor"
        self.lock_path = self.outbox_dir / f"{digest}.lock"

    @contextmanager
    def _lock(self) -> Iterator[bool]:
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        acquired = False
        deadline = time.monotonic() + self.LOCK_WAIT_SECONDS
        while time.monotonic() < deadline:
            try:
                self.lock_path.mkdir()
                acquired = True
                break
            except FileExistsError:
                try:
                    age = time.time() - self.lock_path.stat().st_mtime
                except OSError:
                    age = 0
                if age <= self.LOCK_STALE_SECONDS:
                    break
                try:
                    self.lock_path.rmdir()
                except OSError:
                    time.sleep(0.02)
                    continue
            time.sleep(0.02)
        try:
            yield acquired
        finally:
            if acquired:
                try:
                    self.lock_path.rmdir()
                except OSError:
                    pass

    def pending(self) -> list[MemoryEntry]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            return []
        entries: list[MemoryEntry] = []
        for line in lines:
            try:
                raw = json.loads(line)
            except (TypeError, ValueError):
                continue
            if isinstance(raw, dict):
                entry = MemoryEntry.from_dict(raw)
                if entry is not None:
                    entries.append(entry)
        return entries

    def enqueue(self, entry: MemoryEntry) -> bool:
        if not entry.content.strip():
            return False
        with self._lock() as acquired:
            if not acquired:
                return False
            if entry.fingerprint in {item.fingerprint for item in self.pending()}:
                return False
            self.outbox_dir.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry.as_dict(), ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        return True

    def _write_entries(self, entries: list[MemoryEntry]) -> None:
        if not entries:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            return
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.outbox_dir, delete=False) as handle:
            temporary = Path(handle.name)
            for entry in entries:
                handle.write(json.dumps(entry.as_dict(), ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)

    def flush(self, writer: Callable[[MemoryEntry], object]) -> FlushStats:
        with self._lock() as acquired:
            if not acquired:
                pending = self.pending()
                return FlushStats(written=0, failed=0, remaining=len(pending))
            entries = self.pending()
            remaining: list[MemoryEntry] = []
            written = 0
            failed = 0
            for index, entry in enumerate(entries):
                try:
                    writer(entry)
                except Exception:
                    failed += 1
                    remaining.extend(entries[index:])
                    break
                written += 1
            self._write_entries(remaining)
            return FlushStats(written=written, failed=failed, remaining=len(remaining))

    def read_cursor(self) -> int:
        try:
            return max(0, int(self.cursor_path.read_text(encoding="utf-8").strip()))
        except (OSError, TypeError, ValueError):
            return 0

    def write_cursor(self, cursor: int) -> None:
        with self._lock() as acquired:
            if not acquired:
                return
            self.cursor_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.cursor_dir, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(str(max(0, int(cursor))))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.cursor_path)
