#!/usr/bin/env python3
"""Start the bundled, stable Mnemosyne MCP stdio bridge."""

from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))


def main() -> int:
    from codex_mnemosyne.config import apply_config_env

    # Codex plugin-scoped MCP policy does not reliably materialize nested
    # ``.env`` values in a stdio child.  Resolve the same config file the
    # lifecycle hook uses before importing Mnemosyne's dispatcher.
    apply_config_env(os.environ)
    # Keep the existing Codex-facing bank setting and the Mnemosyne MCP
    # setting interoperable.  Explicit Mnemosyne values still win.
    if not os.environ.get("MNEMOSYNE_MCP_BANK") and os.environ.get("CODEX_MNEMOSYNE_BANK"):
        os.environ["MNEMOSYNE_MCP_BANK"] = os.environ["CODEX_MNEMOSYNE_BANK"]

    try:
        from codex_mnemosyne.mcp_bridge import run_stdio
    except Exception as exc:
        print(f"codex-mnemosyne MCP unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    run_stdio()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
