#!/usr/bin/env python3
"""Report the runtime selected for the automatic Mnemosyne hooks."""

from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from codex_mnemosyne.config import Config


CAPABILITIES = (
    "remember",
    "recall",
    "get_context",
    "get_all_memories",
    "get",
    "update",
    "forget",
    "invalidate",
    "get_stats",
    "sleep",
    "export_to_file",
    "import_from_file",
    "reindex_vectors",
    "scratchpad_write",
    "scratchpad_read",
    "scratchpad_clear",
    "sync_to",
    "sync_from",
)


def _version(module: object) -> str | None:
    value = getattr(module, "__version__", None)
    if value:
        return str(value)
    for distribution in ("mnemosyne-memory", "mnemosyne"):
        try:
            return importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            continue
    return None


def build_report() -> dict[str, object]:
    config = Config.from_env()
    report: dict[str, object] = {
        "python": sys.executable,
        "python_version": platform.python_version(),
        "bank": config.bank,
        "author_id": config.author_id,
        "config_source": config.config_source or None,
        "state_dir": str(config.state_dir),
        "mnemosyne_data_dir": os.environ.get("MNEMOSYNE_DATA_DIR") or None,
        "sdk_importable": False,
        "mnemosyne_import": None,
        "mnemosyne_version": None,
        "mcp_importable": False,
        "capabilities": [],
        "mcp_tool_schema_count": 0,
    }
    try:
        import mnemosyne
    except Exception as exc:  # pragma: no cover - depends on host runtime
        report["error"] = f"{type(exc).__name__}: {exc}"
        return report

    factory = getattr(mnemosyne, "Mnemosyne", None)
    report["sdk_importable"] = factory is not None
    report["mnemosyne_import"] = getattr(mnemosyne, "__file__", None)
    report["mnemosyne_version"] = _version(mnemosyne)
    try:
        import mcp  # noqa: F401
    except Exception:
        report["mcp_importable"] = False
    else:
        report["mcp_importable"] = True
        try:
            from codex_mnemosyne.mcp_bridge import McpBridge

            report["mcp_tool_schema_count"] = len(McpBridge().tool_definitions())
        except Exception:
            report["mcp_tool_schema_count"] = 0
    if factory is not None:
        report["capabilities"] = [name for name in CAPABILITIES if hasattr(factory, name)]
    return report


def main() -> int:
    report = build_report()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["sdk_importable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
