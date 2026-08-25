"""Bounded, model-facing rendering for recalled memories."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


HEADER = "[Mnemosyne memory]"
ITEM_LIMIT = 1500


def _content(item: Mapping[str, object]) -> str:
    value = item.get("content") or item.get("text") or ""
    return str(value).strip()


def render_memories(results: Sequence[Mapping[str, object]], max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    usable = [_content(item) for item in results if _content(item)]
    if not usable:
        return ""
    output = HEADER[:max_chars]
    if len(output) >= max_chars:
        return output

    for item in results:
        content = _content(item)
        if not content:
            continue
        content = content[:ITEM_LIMIT]
        source = str(item.get("source") or "").strip()
        label = f" ({source})" if source else ""
        line = f"- {label} {content}".replace("  ", " ")
        remaining = max_chars - len(output) - 1
        if remaining <= 0:
            break
        if len(line) > remaining:
            line = line[: max(0, remaining - 1)] + "…" if remaining > 1 else line[:remaining]
        output += "\n" + line
        if len(output) >= max_chars:
            break
    return output
