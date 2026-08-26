import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "bin" / "mnemosyne-mcp"
REAL_PYTHON = Path(os.environ.get("CODEX_MNEMOSYNE_PYTHON", "/opt/anaconda3/bin/python3.12"))


class McpServerTests(unittest.TestCase):
    """Exercise the real stdio MCP process against an isolated bank."""

    @classmethod
    def setUpClass(cls):
        if not REAL_PYTHON.is_file():
            raise unittest.SkipTest(f"Mnemosyne test Python is unavailable: {REAL_PYTHON}")
        probe = subprocess.run(
            [str(REAL_PYTHON), "-c", "import mnemosyne, mcp"],
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode != 0:
            raise unittest.SkipTest("the selected Python cannot import mnemosyne and mcp")

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.env = os.environ.copy()
        self.env.update(
            {
                "CODEX_MNEMOSYNE_PYTHON": str(REAL_PYTHON),
                "MNEMOSYNE_DATA_DIR": str(root / "data"),
                "MNEMOSYNE_MCP_BANK": "default",
                "MNEMOSYNE_SHARED_DB_PATH": str(root / "shared" / "mnemosyne.db"),
            }
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def _exchange(self, requests):
        input_text = "\n".join(json.dumps(item) for item in requests) + "\n"
        process = subprocess.Popen(
            [str(LAUNCHER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=self.env,
            cwd=ROOT,
        )
        stdout, stderr = process.communicate(input=input_text, timeout=30)
        self.assertEqual(0, process.returncode, stderr)
        responses = {}
        for line in stdout.splitlines():
            payload = json.loads(line)
            if "id" in payload:
                responses[payload["id"]] = payload
        return responses

    @staticmethod
    def _tool_text(response):
        result = response.get("result", {})
        content = result.get("content", [])
        if not content:
            return {}
        return json.loads(content[0]["text"])

    def test_all_advertised_tools_are_callable_over_stdio(self):
        initialize = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "codex-mnemosyne-test", "version": "1"},
            },
        }
        first = self._exchange(
            [
                {**initialize, "id": 1},
                {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "mnemosyne_remember",
                        "arguments": {
                            "content": "stdio matrix alpha memory for Codex plugin validation",
                            "scope": "global",
                            "importance": 0.9,
                            "source": "stated",
                        },
                    },
                },
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {
                        "name": "mnemosyne_remember",
                        "arguments": {
                            "content": "stdio matrix beta memory for graph and hygiene validation",
                            "scope": "global",
                            "importance": 0.8,
                            "source": "stated",
                        },
                    },
                },
            ]
        )
        self.assertEqual("2025-06-18", first[1]["result"]["protocolVersion"])
        advertised = {tool["name"] for tool in first[2]["result"]["tools"]}
        self.assertEqual(36, len(advertised))
        alpha_id = self._tool_text(first[3])["memory_id"]
        beta_id = self._tool_text(first[4])["memory_id"]

        calls = [
            ("mnemosyne_recall", {"query": "stdio matrix alpha", "limit": 5}),
            ("mnemosyne_shared_remember", {"content": "stdio shared surface canary", "kind": "meta"}),
            ("mnemosyne_shared_recall", {"query": "shared surface canary"}),
            ("mnemosyne_shared_stats", {}),
            ("mnemosyne_shared_forget", {"memory_id": "sf_missing"}),
            ("mnemosyne_sleep", {"dry_run": True}),
            ("mnemosyne_stats", {}),
            ("mnemosyne_invalidate", {"memory_id": beta_id}),
            ("mnemosyne_validate", {"memory_id": alpha_id, "action": "attest", "bank": "private"}),
            ("mnemosyne_get", {"memory_id": alpha_id}),
            ("mnemosyne_triple_add", {"subject": "stdio-user", "predicate": "uses", "object": "mnemosyne"}),
            ("mnemosyne_triple_query", {"subject": "stdio-user", "predicate": "uses"}),
            ("mnemosyne_triple_end", {"subject": "stdio-user", "predicate": "uses"}),
            ("mnemosyne_remember_canonical", {"category": "identity", "name": "test", "body": "stdio"}),
            ("mnemosyne_recall_canonical", {"category": "identity", "name": "test"}),
            ("mnemosyne_scratchpad_write", {"content": "temporary stdio note"}),
            ("mnemosyne_scratchpad_read", {}),
            ("mnemosyne_scratchpad_clear", {}),
            ("mnemosyne_export", {"output_path": str(Path(self.tempdir.name) / "export.json")}),
            ("mnemosyne_update", {"memory_id": alpha_id, "content": "updated stdio matrix alpha memory"}),
            ("mnemosyne_forget", {"memory_id": beta_id}),
            (
                "mnemosyne_batch",
                {"operations": [{"action": "remember", "content": "batch stdio matrix memory", "scope": "global"}]},
            ),
            ("mnemosyne_import", {"input_path": str(Path(self.tempdir.name) / "export.json")}),
            ("mnemosyne_diagnose", {"dry_run": True}),
            ("mnemosyne_graph_query", {"seed_memory_id": alpha_id}),
            ("mnemosyne_graph_link", {"source_id": alpha_id, "target_id": beta_id, "relationship": "related_to"}),
            ("mnemosyne_sync_status", {}),
            ("mnemosyne_sync_push", {}),
            ("mnemosyne_sync_pull", {}),
            ("mnemosyne_persona_promote", {"memory_id": alpha_id}),
            ("mnemosyne_persona_demote", {"persona_id": 999999}),
            ("mnemosyne_persona_list", {}),
            ("mnemosyne_persona_reinforce", {"persona_id": 999999}),
            ("mnemosyne_hygiene_audit", {"limit": 50, "min_score": 0.3}),
            ("mnemosyne_hygiene_clean", {"candidates_json": "[]"}),
        ]
        requests = [{**initialize, "id": 100}]
        requests.extend(
            {
                "jsonrpc": "2.0",
                "id": 101 + index,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
            for index, (name, arguments) in enumerate(calls)
        )
        second = self._exchange(requests)
        self.assertEqual(len(calls) + 1, len(second))
        for index, (name, _) in enumerate(calls):
            response = second[101 + index]
            self.assertNotIn("Unknown tool", json.dumps(response))
            self.assertNotIn("Traceback", json.dumps(response))
            if name == "mnemosyne_sync_push":
                self.assertEqual("not_configured", self._tool_text(response)["status"])


if __name__ == "__main__":
    unittest.main()
