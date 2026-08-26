"""Compatibility handlers for Mnemosyne MCP schemas missing in 3.12.x.

Mnemosyne 3.12.x publishes 36 MCP schemas, but its ``mcp_tools`` dispatch
table contains only 28 handlers.  The bundled server therefore advertises
tools that always return ``Unknown tool``.  This module adds the eight
missing handlers at process start without modifying the user's Mnemosyne
installation.

The handlers intentionally use Mnemosyne's public stores and ``SyncEngine``;
they do not duplicate the automatic Codex hook path.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict


_PERSONA_TIERS = {"permanent", "long_term", "working"}
_TIER_ORDER = {"permanent": 0, "long_term": 1, "working": 2}


def _bank_context(mcp_tools, arguments: Dict[str, Any]):
    bank = mcp_tools._resolve_bank(arguments)
    memory = mcp_tools._create_instance(bank=bank)
    return bank, memory


def _handle_triple_end(mcp_tools, arguments: Dict[str, Any]) -> Dict[str, Any]:
    from mnemosyne.core.triples import TripleStore

    subject = str(arguments.get("subject") or "").strip()
    predicate = str(arguments.get("predicate") or "").strip()
    if not subject or not predicate:
        return {"error": "subject and predicate are required"}
    bank, memory = _bank_context(mcp_tools, arguments)
    store = TripleStore(db_path=memory.beam.db_path)
    ended = store.end(
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
        "bank": bank,
    }


def _sync_context(mcp_tools):
    from mnemosyne.core.sync import SyncEngine

    bank, memory = _bank_context(mcp_tools, {})
    engine = SyncEngine(memory)
    remote = (os.environ.get("MNEMOSYNE_SYNC_REMOTE") or "").strip()
    api_key = (os.environ.get("MNEMOSYNE_SYNC_KEY") or "").strip() or None
    return bank, engine, remote, api_key


def _sync_not_configured(bank: str, operation: str) -> Dict[str, Any]:
    return {
        "status": "not_configured",
        "operation": operation,
        "bank": bank,
        "message": "Set MNEMOSYNE_SYNC_REMOTE to enable remote synchronization.",
    }


def _handle_sync_status(mcp_tools, arguments: Dict[str, Any]) -> Dict[str, Any]:
    bank, engine, remote, _ = _sync_context(mcp_tools)
    status = engine.get_status(remote_url=remote or None)
    status.update(
        {
            "status": "ok",
            "bank": bank,
            "remote": remote or None,
            "encryption_configured": bool(os.environ.get("MNEMOSYNE_SYNC_KEY")),
        }
    )
    return status


def _handle_sync(mcp_tools, mode: str) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    def handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
        bank, engine, remote, api_key = _sync_context(mcp_tools)
        if not remote:
            return _sync_not_configured(bank, mode)
        result = engine.sync_with(remote, mode=mode, api_key=api_key)
        has_errors = bool(result.get("errors"))
        return {
            "status": "error" if has_errors else "synced",
            "operation": mode,
            "bank": bank,
            "remote": remote,
            "result": result,
        }

    return handler


def _memory_row(memory, memory_id: str):
    for table in ("working_memory", "episodic_memory"):
        row = memory.beam.conn.execute(
            f"SELECT id, session_id, content, importance, source FROM {table} WHERE id = ?",
            (memory_id,),
        ).fetchone()
        if row:
            return table, row
    return None, None


def _persona_topic(memory, memory_id: str) -> str:
    try:
        row = memory.beam.conn.execute(
            "SELECT topic FROM memoria_timelines WHERE source_memory_id = ? LIMIT 1",
            (memory_id,),
        ).fetchone()
        if row and row[0]:
            return str(row[0]).strip() or "general"
    except Exception:
        pass
    return "general"


def _handle_persona_promote(mcp_tools, arguments: Dict[str, Any]) -> Dict[str, Any]:
    memory_id = str(arguments.get("memory_id") or "").strip()
    tier = str(arguments.get("tier") or "long_term").strip()
    reason = str(arguments.get("reason") or "").strip()
    if not memory_id:
        return {"error": "memory_id is required"}
    if tier not in _PERSONA_TIERS:
        return {"error": "tier must be one of: permanent, long_term, working"}

    bank, memory = _bank_context(mcp_tools, arguments)
    table, source = _memory_row(memory, memory_id)
    if source is None:
        return {"error": "memory_not_found", "memory_id": memory_id, "bank": bank}

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
            "bank": bank,
        }

    content = str(source[2] or "").strip()
    topic = _persona_topic(memory, memory_id)
    confidence = max(0.0, min(float(source[3] or 0.5), 1.0))
    cursor = conn.execute(
        """INSERT INTO memoria_persona
           (session_id, tier, topic, content, confidence, source_memory_id, promotion_reason)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (str(source[1] or memory.session_id), tier, topic, content, confidence, memory_id, reason),
    )
    conn.commit()
    return {
        "status": "promoted",
        "persona_id": int(cursor.lastrowid),
        "memory_id": memory_id,
        "tier": tier,
        "topic": topic,
        "source_table": table,
        "bank": bank,
    }


def _handle_persona_demote(mcp_tools, arguments: Dict[str, Any]) -> Dict[str, Any]:
    try:
        persona_id = int(arguments.get("persona_id"))
    except (TypeError, ValueError):
        return {"error": "persona_id must be an integer"}
    reason = str(arguments.get("reason") or "").strip()
    bank, memory = _bank_context(mcp_tools, arguments)
    conn = memory.beam.conn
    row = conn.execute(
        "SELECT id, session_id, topic, content, source_memory_id FROM memoria_persona WHERE id = ?",
        (persona_id,),
    ).fetchone()
    if row is None:
        return {"status": "not_found", "persona_id": persona_id, "bank": bank}

    evolution = "demoted"
    if reason:
        evolution = f"demoted: {reason[:500]}"
    cursor = conn.execute(
        """INSERT INTO memoria_preferences
           (session_id, message_idx, preference, topic, evolution, context_snippet, source_memory_id)
           VALUES (?, NULL, ?, ?, ?, ?, ?)""",
        (row[1] or memory.session_id, row[3], row[2] or "general", evolution, row[3], row[4]),
    )
    conn.execute("DELETE FROM memoria_persona WHERE id = ?", (persona_id,))
    conn.commit()
    return {
        "status": "demoted",
        "persona_id": persona_id,
        "preference_id": int(cursor.lastrowid),
        "bank": bank,
    }


def _handle_persona_list(mcp_tools, arguments: Dict[str, Any]) -> Dict[str, Any]:
    tier = str(arguments.get("tier") or "").strip() or None
    topic = str(arguments.get("topic") or "").strip() or None
    if tier and tier not in _PERSONA_TIERS:
        return {"error": "tier must be one of: permanent, long_term, working"}
    bank, memory = _bank_context(mcp_tools, arguments)
    clauses = []
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
    personas = [dict(row) for row in rows]
    for item in personas:
        item["id"] = int(item["id"])
    personas.sort(key=lambda item: (_TIER_ORDER.get(item.get("tier"), 99), -int(item.get("reinforcement_count") or 0), item["id"]))
    return {"status": "ok", "count": len(personas), "personas": personas, "bank": bank}


def _handle_persona_reinforce(mcp_tools, arguments: Dict[str, Any]) -> Dict[str, Any]:
    try:
        persona_id = int(arguments.get("persona_id"))
    except (TypeError, ValueError):
        return {"error": "persona_id must be an integer"}
    bank, memory = _bank_context(mcp_tools, arguments)
    conn = memory.beam.conn
    cursor = conn.execute(
        "UPDATE memoria_persona SET reinforcement_count = COALESCE(reinforcement_count, 0) + 1, "
        "last_reinforced_at = CURRENT_TIMESTAMP WHERE id = ?",
        (persona_id,),
    )
    if cursor.rowcount < 1:
        return {"status": "not_found", "persona_id": persona_id, "bank": bank}
    conn.commit()
    row = conn.execute("SELECT reinforcement_count FROM memoria_persona WHERE id = ?", (persona_id,)).fetchone()
    return {
        "status": "reinforced",
        "persona_id": persona_id,
        "reinforcement_count": int(row[0]) if row else None,
        "bank": bank,
    }


def install() -> tuple[str, ...]:
    """Install missing dispatch entries and return the names added."""
    import mnemosyne.mcp_tools as mcp_tools

    handlers = {
        "mnemosyne_triple_end": lambda args: _handle_triple_end(mcp_tools, args),
        "mnemosyne_sync_status": lambda args: _handle_sync_status(mcp_tools, args),
        "mnemosyne_sync_push": _handle_sync(mcp_tools, "push"),
        "mnemosyne_sync_pull": _handle_sync(mcp_tools, "pull"),
        "mnemosyne_persona_promote": lambda args: _handle_persona_promote(mcp_tools, args),
        "mnemosyne_persona_demote": lambda args: _handle_persona_demote(mcp_tools, args),
        "mnemosyne_persona_list": lambda args: _handle_persona_list(mcp_tools, args),
        "mnemosyne_persona_reinforce": lambda args: _handle_persona_reinforce(mcp_tools, args),
    }
    added = []
    for name, handler in handlers.items():
        if name not in mcp_tools._TOOL_HANDLERS:
            mcp_tools._TOOL_HANDLERS[name] = handler
            added.append(name)
    return tuple(added)


__all__ = ["install"]
