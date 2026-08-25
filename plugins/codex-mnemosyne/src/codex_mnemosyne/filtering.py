"""Low-noise and credential safety filters for automatic capture."""

from __future__ import annotations

import re

from .config import Config


SECRET_PATTERNS = (
    re.compile(r"(?:api[_-]?key|token|password|secret|client_secret)\s*[:=]\s*\S+", re.I),
    re.compile(r"--(?:api[_-]?key|token|password|secret|client[_-]?secret)(?:=|\s+)\S+", re.I),
    re.compile(r"\b[A-Z][A-Z0-9_]*(?:KEY|TOKEN|PASSWORD|SECRET)\s*=\s*\S+\b"),
    re.compile(r"(?:authorization|proxy-authorization)\s*[:=]\s*bearer\s+\S+", re.I),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
)


def contains_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def should_capture(text: str, config: Config) -> bool:
    candidate = text.strip()
    if len(candidate) < config.capture_min_chars:
        return False
    if contains_secret(candidate):
        return False
    lowered = candidate.casefold()
    if lowered in {"ok", "okay", "done", "sure", "thanks", "got it", "continue"}:
        return False
    return True
