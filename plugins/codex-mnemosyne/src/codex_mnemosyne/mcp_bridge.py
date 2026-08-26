"""Stable MCP bridge for Mnemosyne's public tool surface.

The upstream package owns the majority of tool semantics.  This bridge keeps
the stdio transport and the compatibility handlers in the plugin, so the
plugin never mutates Mnemosyne's private ``_TOOL_HANDLERS`` table.  A small
number of handlers are implemented here because Mnemosyne 3.12.x publishes
their schemas before registering their dispatch functions.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from typing import Any, Callable, Mapping


OWN_HANDLERS = {
    "mnemosyne_triple_add",
    "mnemosyne_triple_end",
    "mnemosyne_sync_status",
    "mnemosyne_sync_push",
    "mnemosyne_sync_pull",
    "mnemosyne_persona_promote",
    "mnemosyne_persona_demote",
    "mnemosyne_persona_list",
    "mnemosyne_persona_reinforce",
    "mnemosyne_validate",
}
PERSONA_TIERS = {"permanent", "long_term", "working"}
PERSONA_ORDER = {"permanent": 0, "long_term": 1, "working": 2}


def _serialize(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    return value


def _bank(arguments: Mapping[str, Any]) -> str:
    return str(
        arguments.get("bank")
        or os.environ.get("MNEMOSYNE_MCP_BANK")
        or os.environ.get("CODEX_MNEMOSYNE_BANK")
        or "default"
    ).strip() or "default"


def _memory(arguments: Mapping[str, Any]):
    from mnemosyne.core.memory import Mnemosyne

    bank = _bank(arguments)
    session_id = str(
        arguments.get("session_id")
        or os.environ.get("MNEMOSYNE_SESSION_ID")
        or f"mcp_{bank}"
    )
    channel_id = str(
        arguments.get("channel_id")
        or os.environ.get("MNEMOSYNE_CHANNEL_ID")
        or session_id
    )
    return Mnemosyne(
        session_id=session_id,
        bank=bank,
        author_id=arguments.get("author_id") or os.environ.get("MNEMOSYNE_AUTHOR_ID"),
        author_type=arguments.get("author_type") or os.environ.get("MNEMOSYNE_AUTHOR_TYPE"),
        channel_id=channel_id,
    )


def _memory_row(memory: Any, memory_id: str):
    conn = memory.beam.conn
    for table in ("working_memory", "memories", "episodic_memory"):
        try:
            row = conn.execute(
                f"SELECT id, session_id, content, importance, source FROM {table} WHERE id = ?",
                (memory_id,),
            ).fetchone()
        except Exception:
            row = None
        if row:
            return table, row
    return None, None


def _persona_topic(memory: Any, memory_id: str) -> str:
    try:
        row = memory.beam.conn.execute(
            "SELECT topic FROM memoria_timelines WHERE source_memory_id = ? LIMIT 1",
            (memory_id,),
        ).fetchone()
    except Exception:
        row = None
    return str(row[0]).strip() if row and row[0] else "general"


def _triple_add(arguments: Mapping[str, Any]) -> dict[str, Any]:
    subject = str(arguments.get("subject") or "").strip()
    predicate = str(arguments.get("predicate") or "").strip()
    object_value = str(arguments.get("object") or "").strip()
    if not subject or not predicate or not object_value:
        return {"error": "subject, predicate, and object are required"}

    from mnemosyne.core.annotations import ANNOTATION_KINDS, AnnotationStore
    from mnemosyne.core.triples import TripleStore

    memory = _memory(arguments)
    db_path = memory.beam.db_path
    if predicate in ANNOTATION_KINDS:
        store = getattr(memory.beam, "annotations", None) or AnnotationStore(
            db_path=db_path,
            conn=memory.beam.conn,
        )
        kwargs = {
            "memory_id": subject,
            "kind": predicate,
            "value": object_value,
            "source": arguments.get("source") or "conversation",
            "confidence": arguments.get("confidence", 1.0),
        }
        if predicate == "occurred_on" and arguments.get("valid_from"):
            kwargs["valid_from"] = arguments["valid_from"]
        row_id = store.add(**kwargs)
        return {"status": "added", "annotation_id": row_id, "store": "annotations"}

    store = TripleStore(db_path=db_path)
    row_id = store.add(
        subject=subject,
        predicate=predicate,
        object=object_value,
        valid_from=arguments.get("valid_from") or None,
        valid_until=arguments.get("valid_until") or None,
        source=arguments.get("source") or "conversation",
        confidence=float(arguments.get("confidence", 1.0)),
        supersede=bool(arguments.get("supersede", True)),
    )
    return {
        "status": "added",
        "triple_id": row_id,
        "store": "triples",
        "supersede": bool(arguments.get("supersede", True)),
    }


def _triple_end(arguments: Mapping[str, Any]) -> dict[str, Any]:
    subject = str(arguments.get("subject") or "").strip()
    predicate = str(arguments.get("predicate") or "").strip()
    if not subject or not predicate:
        return {"error": "subject and predicate are required"}
    from mnemosyne.core.triples import TripleStore

    memory = _memory(arguments)
    ended = TripleStore(db_path=memory.beam.db_path).end(
        subject=subject,
        predicate=predicate,
        object=arguments.get("object") or None,
        valid_until=arguments.get("valid_until") or None,
    )
    return {
        "status": "ended",
        "ended_count": int(ended or 0),
        "subject": subject,
        "predicate": predicate,
        "bank": _bank(arguments),
    }


def _sync_context(arguments: Mapping[str, Any]):
    from mnemosyne.core.sync import SyncEngine

    memory = _memory(arguments)
    remote = str(os.environ.get("MNEMOSYNE_SYNC_REMOTE") or "").strip()
    api_key = str(os.environ.get("MNEMOSYNE_SYNC_KEY") or "").strip() or None
    return memory, SyncEngine(memory), remote, api_key


def _sync_status(arguments: Mapping[str, Any]) -> dict[str, Any]:
    memory, engine, remote, _ = _sync_context(arguments)
    result = engine.get_status(remote_url=remote or None)
    result.update(
        {
            "status": "ok",
            "bank": _bank(arguments),
            "remote": remote or None,
            "encryption_configured": bool(os.environ.get("MNEMOSYNE_SYNC_KEY")),
        }
    )
    return _serialize(result)


def _sync(arguments: Mapping[str, Any], operation: str) -> dict[str, Any]:
    memory, engine, remote, api_key = _sync_context(arguments)
    if not remote:
        return {
            "status": "not_configured",
            "operation": operation,
            "bank": _bank(arguments),
            "message": "Set MNEMOSYNE_SYNC_REMOTE to enable remote synchronization.",
        }
    result = engine.sync_with(remote, mode=operation, api_key=api_key)
    return {
        "status": "error" if result.get("errors") else "synced",
        "operation": operation,
        "bank": _bank(arguments),
        "remote": remote,
        "result": _serialize(result),
    }


def _persona_promote(arguments: Mapping[str, Any]) -> dict[str, Any]:
    memory_id = str(arguments.get("memory_id") or "").strip()
    tier = str(arguments.get("tier") or "long_term").strip()
    reason = str(arguments.get("reason") or "").strip()
    if not memory_id:
        return {"error": "memory_id is required"}
    if tier not in PERSONA_TIERS:
        return {"error": "tier must be one of: permanent, long_term, working"}
    memory = _memory(arguments)
    table, source = _memory_row(memory, memory_id)
    if source is None:
        return {"error": "memory_not_found", "memory_id": memory_id, "bank": _bank(arguments)}
    conn = memory.beam.conn
    existing = conn.execute(
        "SELECT id, tier FROM memoria_persona WHERE source_memory_id = ? ORDER BY id DESC LIMIT 1",
        (memory_id,),
    ).fetchone()
    if existing:
        if existing[1] != tier:
            conn.execute(
                "UPDATE memoria_persona SET tier = ?, promotion_reason = ? WHERE id = ?",
                (tier, reason, existing[0]),
            )
            conn.commit()
            status = "updated"
        else:
            status = "already_promoted"
        return {
            "status": status,
            "persona_id": int(existing[0]),
            "memory_id": memory_id,
            "tier": tier,
            "bank": _bank(arguments),
        }

    content = str(source[2] or "").strip()
    cursor = conn.execute(
        """INSERT INTO memoria_persona
           (session_id, tier, topic, content, confidence, source_memory_id, promotion_reason)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            str(source[1] or getattr(memory, "session_id", "default")),
            tier,
            _persona_topic(memory, memory_id),
            content,
            max(0.0, min(float(source[3] or 0.5), 1.0)),
            memory_id,
            reason,
        ),
    )
    conn.commit()
    return {
        "status": "promoted",
        "persona_id": int(cursor.lastrowid),
        "memory_id": memory_id,
        "tier": tier,
        "topic": _persona_topic(memory, memory_id),
        "source_table": table,
        "bank": _bank(arguments),
    }


def _persona_demote(arguments: Mapping[str, Any]) -> dict[str, Any]:
    try:
        persona_id = int(arguments.get("persona_id"))
    except (TypeError, ValueError):
        return {"error": "persona_id must be an integer"}
    reason = str(arguments.get("reason") or "").strip()
    memory = _memory(arguments)
    conn = memory.beam.conn
    row = conn.execute(
        "SELECT id, session_id, topic, content, source_memory_id FROM memoria_persona WHERE id = ?",
        (persona_id,),
    ).fetchone()
    if row is None:
        return {"status": "not_found", "persona_id": persona_id, "bank": _bank(arguments)}
    evolution = f"demoted: {reason[:500]}" if reason else "demoted"
    cursor = conn.execute(
        """INSERT INTO memoria_preferences
           (session_id, message_idx, preference, topic, evolution, context_snippet, source_memory_id)
           VALUES (?, NULL, ?, ?, ?, ?, ?)""",
        (row[1] or memory._session_id, row[3], row[2] or "general", evolution, row[3], row[4]),
    )
    conn.execute("DELETE FROM memoria_persona WHERE id = ?", (persona_id,))
    conn.commit()
    return {
        "status": "demoted",
        "persona_id": persona_id,
        "preference_id": int(cursor.lastrowid),
        "bank": _bank(arguments),
    }


def _persona_list(arguments: Mapping[str, Any]) -> dict[str, Any]:
    tier = str(arguments.get("tier") or "").strip() or None
    topic = str(arguments.get("topic") or "").strip() or None
    if tier and tier not in PERSONA_TIERS:
        return {"error": "tier must be one of: permanent, long_term, working"}
    memory = _memory(arguments)
    clauses: list[str] = []
    params: list[Any] = []
    if tier:
        clauses.append("tier = ?")
        params.append(tier)
    if topic:
        clauses.append("topic = ?")
        params.append(topic)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = memory.beam.conn.execute(
        "SELECT id, session_id, tier, topic, content, confidence, source_memory_id, "
        "created_at, last_reinforced_at, reinforcement_count, promotion_reason "
        f"FROM memoria_persona{where} ORDER BY reinforcement_count DESC, id ASC",
        params,
    ).fetchall()
    personas = [_serialize(dict(row)) for row in rows]
    personas.sort(
        key=lambda item: (
            PERSONA_ORDER.get(str(item.get("tier")), 99),
            -int(item.get("reinforcement_count") or 0),
            int(item.get("id") or 0),
        )
    )
    return {"status": "ok", "count": len(personas), "personas": personas, "bank": _bank(arguments)}


def _persona_reinforce(arguments: Mapping[str, Any]) -> dict[str, Any]:
    try:
        persona_id = int(arguments.get("persona_id"))
    except (TypeError, ValueError):
        return {"error": "persona_id must be an integer"}
    memory = _memory(arguments)
    cursor = memory.beam.conn.execute(
        "UPDATE memoria_persona SET reinforcement_count = COALESCE(reinforcement_count, 0) + 1, "
        "last_reinforced_at = CURRENT_TIMESTAMP WHERE id = ?",
        (persona_id,),
    )
    if cursor.rowcount < 1:
        return {"status": "not_found", "persona_id": persona_id, "bank": _bank(arguments)}
    memory.beam.conn.commit()
    row = memory.beam.conn.execute(
        "SELECT reinforcement_count FROM memoria_persona WHERE id = ?", (persona_id,)
    ).fetchone()
    return {
        "status": "reinforced",
        "persona_id": persona_id,
        "reinforcement_count": int(row[0]) if row else None,
        "bank": _bank(arguments),
    }


def _surface_beam():
    from pathlib import Path

    from mnemosyne.core.beam import BeamMemory

    home = Path(os.environ.get("MNEMOSYNE_HOME") or Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")) / "mnemosyne")
    path = Path(os.environ.get("MNEMOSYNE_SHARED_DB_PATH") or home / "data" / "shared" / "mnemosyne.db").expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    return BeamMemory(session_id="mcp_shared_surface", db_path=path)


def _validate(arguments: Mapping[str, Any]) -> dict[str, Any]:
    memory_id = str(arguments.get("memory_id") or "").strip()
    action = str(arguments.get("action") or "").strip()
    bank = str(arguments.get("bank") or "private").strip()
    validator = str(arguments.get("validator") or os.environ.get("MNEMOSYNE_AUTHOR_ID") or "mcp").strip()
    new_content = str(arguments.get("new_content") or "")
    note = str(arguments.get("note") or "")
    if not memory_id:
        return {"error": "memory_id is required"}
    if action not in {"attest", "update", "invalidate", "delete"}:
        return {"error": f"unknown action: {action}"}
    if bank not in {"private", "surface"}:
        return {"error": f"unknown bank: {bank}"}
    if action == "update" and not new_content.strip():
        return {"error": "new_content is required for action='update'"}

    target = _surface_beam() if bank == "surface" else _memory({}).beam
    conn = target.conn
    row = conn.execute(
        "SELECT id, author_id, content FROM working_memory WHERE id = ?", (memory_id,)
    ).fetchone()
    if row is None:
        return {"error": "memory_not_found", "memory_id": memory_id, "bank": bank}
    previous = str(row[2] or "")
    try:
        if action == "delete":
            conn.execute("DELETE FROM working_memory WHERE id = ?", (memory_id,))
        elif action == "update":
            conn.execute(
                "UPDATE working_memory SET content = ?, validator = ?, "
                "validated_at = CURRENT_TIMESTAMP, validation_count = "
                "COALESCE(validation_count, 0) + 1 WHERE id = ?",
                (new_content, validator, memory_id),
            )
        elif action == "invalidate":
            conn.execute(
                "UPDATE working_memory SET valid_until = CURRENT_TIMESTAMP, validator = ?, "
                "validated_at = CURRENT_TIMESTAMP, validation_count = "
                "COALESCE(validation_count, 0) + 1 WHERE id = ?",
                (validator, memory_id),
            )
        else:
            conn.execute(
                "UPDATE working_memory SET validator = ?, validated_at = CURRENT_TIMESTAMP, "
                "validation_count = COALESCE(validation_count, 0) + 1 WHERE id = ?",
                (validator, memory_id),
            )
        conn.execute(
            "INSERT INTO memory_validations (memory_id, validator, action, new_content, note) "
            "VALUES (?, ?, ?, ?, ?)",
            (memory_id, validator, action, new_content if action == "update" else None, note or None),
        )
        conn.commit()
    except Exception as exc:
        return {"error": "validation_failed", "reason": str(exc), "memory_id": memory_id}
    return {
        "status": f"validation_{action}",
        "memory_id": memory_id,
        "bank": bank,
        "validator": validator,
        "author_id": row[1],
        "previous_content": previous[:200],
    }


class McpBridge:
    """Dispatch Mnemosyne tools without altering upstream global state."""

    def __init__(self, upstream_dispatch: Callable[[str, dict[str, Any]], Any] | None = None) -> None:
        self._upstream_dispatch = upstream_dispatch

    def tool_definitions(self) -> list[dict[str, Any]]:
        from mnemosyne.mcp_tools import get_tool_definitions

        return [dict(item) for item in get_tool_definitions()]

    def dispatch(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        values = dict(arguments or {})
        own: dict[str, Callable[[Mapping[str, Any]], dict[str, Any]]] = {
            "mnemosyne_triple_add": _triple_add,
            "mnemosyne_triple_end": _triple_end,
            "mnemosyne_sync_status": _sync_status,
            "mnemosyne_sync_push": lambda args: _sync(args, "push"),
            "mnemosyne_sync_pull": lambda args: _sync(args, "pull"),
            "mnemosyne_persona_promote": _persona_promote,
            "mnemosyne_persona_demote": _persona_demote,
            "mnemosyne_persona_list": _persona_list,
            "mnemosyne_persona_reinforce": _persona_reinforce,
            "mnemosyne_validate": _validate,
        }
        if name in own:
            return _serialize(own[name](values))

        dispatch = self._upstream_dispatch
        if dispatch is None:
            from mnemosyne.mcp_tools import handle_tool_call

            dispatch = handle_tool_call
        try:
            return _serialize(dispatch(name, values))
        except ValueError as exc:
            return {"status": "error", "message": str(exc), "tool": name}
        except Exception as exc:
            return {"status": "error", "message": f"{type(exc).__name__}: {exc}", "tool": name}


async def _run_stdio() -> None:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool

    bridge = McpBridge()
    server = Server("codex-mnemosyne")

    @server.list_tools()
    async def list_tools():
        return [Tool(**item) for item in bridge.tool_definitions()]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]):
        result = bridge.dispatch(name, arguments)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def run_stdio() -> None:
    asyncio.run(_run_stdio())


__all__ = ["McpBridge", "run_stdio"]
