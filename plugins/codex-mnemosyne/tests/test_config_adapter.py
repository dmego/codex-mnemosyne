import os
import unittest
from pathlib import Path


class ConfigTests(unittest.TestCase):
    def test_bank_precedence_is_plugin_then_mcp_then_default(self):
        from codex_mnemosyne.config import Config

        config = Config.from_env(
            {
                "CODEX_MNEMOSYNE_BANK": "plugin-bank",
                "MNEMOSYNE_MCP_BANK": "mcp-bank",
            }
        )
        self.assertEqual("plugin-bank", config.bank)

        config = Config.from_env({"MNEMOSYNE_MCP_BANK": "mcp-bank"})
        self.assertEqual("mcp-bank", config.bank)
        self.assertEqual("default", Config.from_env({}).bank)

    def test_author_identity_accepts_plugin_override_then_mnemosyne_native_env(self):
        from codex_mnemosyne.config import Config

        config = Config.from_env(
            {
                "MNEMOSYNE_AUTHOR_ID": "native-agent",
                "MNEMOSYNE_AUTHOR_TYPE": "native-type",
            }
        )
        self.assertEqual("native-agent", config.author_id)
        self.assertEqual("native-type", config.author_type)

        config = Config.from_env(
            {
                "CODEX_MNEMOSYNE_AUTHOR_ID": "plugin-agent",
                "MNEMOSYNE_AUTHOR_ID": "native-agent",
            }
        )
        self.assertEqual("plugin-agent", config.author_id)

    def test_limits_are_clamped_and_invalid_values_use_defaults(self):
        from codex_mnemosyne.config import Config

        config = Config.from_env(
            {
                "CODEX_MNEMOSYNE_RECALL_TOP_K": "999",
                "CODEX_MNEMOSYNE_RECALL_MAX_CHARS": "-2",
                "CODEX_MNEMOSYNE_CAPTURE_MIN_CHARS": "not-a-number",
            }
        )
        self.assertEqual(20, config.recall_top_k)
        self.assertEqual(512, config.recall_max_chars)
        self.assertEqual(80, config.capture_min_chars)

    def test_session_id_is_stable_without_leaking_absolute_cwd(self):
        from codex_mnemosyne.config import Config

        config = Config.from_env({"CODEX_MNEMOSYNE_STATE_DIR": "/tmp/memory-state"})
        payload = {"session_id": "session-123", "cwd": "/private/workspaces/example"}

        self.assertEqual(config.session_id(payload), config.session_id(payload))
        self.assertEqual("example:session-123", config.session_id(payload))
        self.assertNotIn("/private/workspaces", config.session_id(payload))
        self.assertEqual(Path("/tmp/memory-state"), config.state_dir)

    def test_plugin_data_is_the_portable_state_fallback(self):
        from codex_mnemosyne.config import Config

        config = Config.from_env({"PLUGIN_DATA": "/portable/plugin-data"})
        self.assertEqual(Path("/portable/plugin-data"), config.state_dir)

    def test_boolean_flags_accept_common_false_values(self):
        from codex_mnemosyne.config import Config

        config = Config.from_env(
            {
                "CODEX_MNEMOSYNE_AUTO_RECALL": "off",
                "CODEX_MNEMOSYNE_AUTO_CAPTURE": "0",
                "CODEX_MNEMOSYNE_EXTRACT": "false",
            }
        )
        self.assertFalse(config.auto_recall)
        self.assertFalse(config.auto_capture)
        self.assertFalse(config.extract)


class AdapterTests(unittest.TestCase):
    def test_adapter_maps_recall_and_remember_to_mnemosyne(self):
        from codex_mnemosyne.adapter import MemoryUnavailable, MnemosyneAdapter
        from codex_mnemosyne.config import Config

        class FakeMnemosyne:
            instances = []

            def __init__(self, **kwargs):
                self.init_kwargs = kwargs
                self.calls = []
                self.instances.append(self)

            def recall(self, **kwargs):
                self.calls.append(("recall", kwargs))
                return [{"content": "remembered"}]

            def get_context(self, **kwargs):
                self.calls.append(("get_context", kwargs))
                return [{"content": "recent"}]

            def remember(self, **kwargs):
                self.calls.append(("remember", kwargs))
                return "memory-id"

        config = Config.from_env(
            {
                "CODEX_MNEMOSYNE_BANK": "portable",
                "CODEX_MNEMOSYNE_AUTHOR_ID": "agent",
            }
        )
        adapter = MnemosyneAdapter(
            config,
            {"session_id": "s1", "cwd": "/work/demo"},
            memory_factory=FakeMnemosyne,
        )

        self.assertEqual([{ "content": "remembered" }], adapter.recall("query", 3))
        self.assertEqual([{ "content": "recent" }], adapter.get_context(2))
        self.assertEqual("memory-id", adapter.remember("content", {"kind": "test"}))

        memory = FakeMnemosyne.instances[0]
        self.assertEqual("portable", memory.init_kwargs["bank"])
        self.assertEqual("agent", memory.init_kwargs["author_id"])
        self.assertEqual("demo:s1", memory.init_kwargs["session_id"])
        self.assertEqual(config.project_channel({"cwd": "/work/demo", "session_id": "s1"}), memory.init_kwargs["channel_id"])
        self.assertEqual(config.project_channel({"cwd": "/work/demo", "session_id": "s1"}), memory.calls[0][1]["channel_id"])
        self.assertEqual("recall", memory.calls[0][0])
        self.assertEqual("remember", memory.calls[2][0])
        self.assertEqual("codex-auto", memory.calls[2][1]["source"])

        adapter.remember(
            "old session content",
            {
                "kind": "turn",
                "session_id": "old-session",
                "channel_id": "old-channel",
                "bank": "portable",
            },
        )
        old_memory = FakeMnemosyne.instances[-1]
        self.assertEqual("old-session", old_memory.init_kwargs["session_id"])
        self.assertEqual("old-channel", old_memory.init_kwargs["channel_id"])
        self.assertEqual("portable", old_memory.init_kwargs["bank"])

        adapter.remember(
            "other bank content",
            {
                "kind": "turn",
                "session_id": "s1",
                "channel_id": config.project_channel({"cwd": "/work/demo", "session_id": "s1"}),
                "bank": "other-bank",
            },
        )
        self.assertEqual("other-bank", FakeMnemosyne.instances[-1].init_kwargs["bank"])

        with self.assertRaises(MemoryUnavailable):
            adapter.remember("unroutable legacy content", {"kind": "turn"})

    def test_get_context_filters_project_channel_before_injection(self):
        import sqlite3
        from types import SimpleNamespace

        from codex_mnemosyne.adapter import MnemosyneAdapter
        from codex_mnemosyne.config import Config

        class FakeMnemosyne:
            def __init__(self, **kwargs):
                connection = sqlite3.connect(":memory:")
                connection.row_factory = sqlite3.Row
                connection.execute(
                    """
                    CREATE TABLE working_memory (
                        id TEXT PRIMARY KEY,
                        content TEXT NOT NULL,
                        source TEXT,
                        timestamp TEXT,
                        importance REAL,
                        scope TEXT,
                        last_recalled TEXT,
                        valid_until TEXT,
                        superseded_by TEXT,
                        consolidated_at TEXT,
                        session_id TEXT,
                        channel_id TEXT,
                        recall_count INTEGER DEFAULT 0
                    )
                    """
                )
                self.beam = SimpleNamespace(conn=connection)
                self.channel_id = kwargs["channel_id"]
                self.session_id = kwargs["session_id"]

            def get_context(self, **kwargs):
                raise AssertionError("unfiltered SDK context path was used")

        config = Config.from_env({"CODEX_MNEMOSYNE_BANK": "portable"})
        payload = {"session_id": "s1", "cwd": "/work/demo"}
        channel = config.project_channel(payload)
        adapter = MnemosyneAdapter(config, payload, memory_factory=FakeMnemosyne)
        memory = adapter._load_memory()
        memory.beam.conn.executemany(
            """
            INSERT INTO working_memory
              (id, content, source, timestamp, importance, scope, session_id, channel_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("matching", "same project memory", "test", "2026-01-02", 0.9, "global", "old", channel),
                ("other", "other project memory", "test", "2026-01-03", 1.0, "global", "old", "codex-project:other"),
            ],
        )
        memory.beam.conn.commit()

        context = adapter.get_context(5)

        self.assertEqual(["matching"], [item["id"] for item in context])


if __name__ == "__main__":
    unittest.main()
