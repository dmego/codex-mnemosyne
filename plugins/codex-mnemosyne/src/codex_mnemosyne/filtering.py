"""Low-noise and credential safety filters for automatic capture."""

from __future__ import annotations

import re

from .config import Config


SECRET_PATTERNS = (
    re.compile(r"(?:api[_-]?key|token|password|secret|client_secret)\s*[:=]\s*\S+", re.I),
    re.compile(r"--(?:api[_-]?key|token|password|secret|client[_-]?secret)(?:=|\s+)\S+", re.I),
    re.compile(r"\b[A-Z][A-Z0-9_]*(?:KEY|TOKEN|PASSWORD|SECRET|COOKIE|AUTH)[A-Z0-9_]*\s*=\s*\S+\b"),
    re.compile(r"(?:authorization|proxy-authorization)\s*[:=]\s*(?:bearer|basic)\s+\S+", re.I),
    re.compile(r"(?:cookie|set-cookie)\s*[:=]\s*\S+", re.I),
    re.compile(r"https?://[^\s/@:]+:[^\s/@]+@", re.I),
    re.compile(r"\b(?:gh[pousr]_|github_pat_|xox[baprs]-|npm_)[A-Za-z0-9_-]{8,}\b", re.I),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
)

PROMPT_INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?\b", re.I),
    re.compile(r"\b(?:system|developer)\s+message\s*[:：]", re.I),
    re.compile(r"\bdo\s+not\s+(?:tell|show)\s+the\s+user\b", re.I),
    re.compile(r"\bexecute\s+(?:this|the\s+following)\s+command\b", re.I),
)


def contains_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def contains_prompt_injection(text: str) -> bool:
    return any(pattern.search(text) for pattern in PROMPT_INJECTION_PATTERNS)


def should_capture(text: str, config: Config) -> bool:
    candidate = text.strip()
    if len(candidate) < config.capture_min_chars:
        return False
    if contains_secret(candidate):
        return False
    if contains_prompt_injection(candidate):
        return False
    lowered = candidate.casefold()
    if lowered in {"ok", "okay", "done", "sure", "thanks", "got it", "continue"}:
        return False
    return True
