import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REAL_PYTHON = Path(os.environ.get("CODEX_MNEMOSYNE_PYTHON", "/opt/anaconda3/bin/python3.12"))


class McpFunctionMatrixTests(unittest.TestCase):
    """Positive semantic coverage for every advertised Mnemosyne tool."""

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

    def test_all_tools_have_positive_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            script = textwrap.dedent(
                """
                import json, os
                from pathlib import Path
                from codex_mnemosyne.mcp_bridge import McpBridge

                root = Path(os.environ["MATRIX_ROOT"])
                bridge = McpBridge()
                assert len(bridge.tool_definitions()) == 36

                def call(name, args=None):
                    result = bridge.dispatch(name, args or {})
                    assert "Traceback" not in json.dumps(result)
                    return result

                alpha = call("mnemosyne_remember", {
                    "content": "MATRIX_ALPHA durable memory for complete Mnemosyne coverage",
                    "scope": "global", "importance": 0.9, "source": "stated",
                })
                beta = call("mnemosyne_remember", {
                    "content": "MATRIX_BETA durable memory for mutation coverage",
                    "scope": "global", "importance": 0.8, "source": "stated",
                })
                alpha_id, beta_id = alpha["memory_id"], beta["memory_id"]
                recalled = call("mnemosyne_recall", {
                    "query": "MATRIX_ALPHA", "limit": 5, "explain": True,
                })
                assert recalled["count"] >= 1 and "results" in recalled and "explain" in recalled

                shared = call("mnemosyne_shared_remember", {
                    "content": "MATRIX_SHARED stable workflow preference", "kind": "preference",
                })
                shared_id = shared["memory_id"]
                assert call("mnemosyne_shared_recall", {"query": "MATRIX_SHARED"})["count"] >= 1
                assert call("mnemosyne_shared_stats", {})["working"]["total"] >= 1
                assert call("mnemosyne_validate", {
                    "memory_id": shared_id, "action": "attest", "bank": "surface", "validator": "codex",
                })["status"] == "validation_attest"
                assert call("mnemosyne_shared_forget", {"memory_id": shared_id})["status"] == "deleted"

                assert call("mnemosyne_sleep", {"dry_run": True})["status"] in {"no_op", "dry_run", "consolidated"}
                assert call("mnemosyne_stats", {})["stats"]["total_memories"] >= 2
                assert call("mnemosyne_get", {"memory_id": alpha_id})["status"] == "ok"
                assert call("mnemosyne_update", {
                    "memory_id": alpha_id, "content": "MATRIX_ALPHA updated durable memory", "importance": 0.7,
                })["status"] == "updated"
                assert call("mnemosyne_validate", {
                    "memory_id": alpha_id, "action": "attest", "bank": "private", "validator": "codex",
                })["status"] == "validation_attest"

                call("mnemosyne_triple_add", {
                    "subject": "matrix-user", "predicate": "speaks", "object": "English",
                })
                call("mnemosyne_triple_add", {
                    "subject": "matrix-user", "predicate": "speaks", "object": "Spanish", "supersede": False,
                })
                triples = call("mnemosyne_triple_query", {"subject": "matrix-user", "predicate": "speaks"})
                assert triples["results_count"] == 2
                assert call("mnemosyne_triple_end", {
                    "subject": "matrix-user", "predicate": "speaks", "object": "English",
                })["ended_count"] == 1

                call("mnemosyne_remember_canonical", {
                    "category": "identity", "name": "matrix", "body": "v1",
                })
                call("mnemosyne_remember_canonical", {
                    "category": "identity", "name": "matrix", "body": "v2",
                })
                assert call("mnemosyne_recall_canonical", {
                    "category": "identity", "name": "matrix",
                })["result"]["body"] == "v2"
                assert call("mnemosyne_recall_canonical", {
                    "category": "identity", "name": "matrix", "include_history": True,
                })["results_count"] == 2

                call("mnemosyne_scratchpad_write", {"content": "MATRIX_SCRATCHPAD"})
                assert call("mnemosyne_scratchpad_read", {})["entries_count"] == 1
                assert call("mnemosyne_scratchpad_clear", {})["status"] == "cleared"

                export_path = root / "export.json"
                assert call("mnemosyne_export", {"output_path": str(export_path)})["status"] == "exported"
                assert export_path.is_file()
                assert call("mnemosyne_import", {"input_path": str(export_path)})["status"] == "imported"

                batch = call("mnemosyne_batch", {"operations": [{
                    "action": "remember", "content": "MATRIX_BATCH durable memory", "scope": "global",
                }]})
                assert batch["status"] == "ok" and batch["operations_count"] == 1
                failed_batch = call("mnemosyne_batch", {"operations": [
                    {"action": "remember", "content": "ROLLBACK_SHOULD_NOT_PERSIST_9182", "scope": "global"},
                    {"action": "forget", "memory_id": "missing-for-rollback"},
                ]})
                assert failed_batch["status"] in {"error", "validation_error"}
                assert call("mnemosyne_recall", {"query": "ROLLBACK_SHOULD_NOT_PERSIST_9182", "limit": 5})["count"] == 0

                assert call("mnemosyne_graph_link", {
                    "source_id": alpha_id, "target_id": beta_id, "relationship": "related_to", "weight": 0.9,
                })["status"] == "linked"
                assert call("mnemosyne_graph_query", {
                    "seed_memory_id": alpha_id, "max_hops": 2,
                })["count"] >= 1
                diagnose = call("mnemosyne_diagnose", {"dry_run": True, "repair_vec_working": True})
                assert "checks_total" in diagnose or "status" in diagnose

                assert call("mnemosyne_sync_status", {})["status"] == "ok"
                assert call("mnemosyne_sync_push", {})["status"] == "not_configured"
                assert call("mnemosyne_sync_pull", {})["status"] == "not_configured"

                persona = call("mnemosyne_persona_promote", {
                    "memory_id": alpha_id, "tier": "long_term", "reason": "matrix",
                })
                persona_id = persona["persona_id"]
                assert call("mnemosyne_persona_list", {})["count"] == 1
                assert call("mnemosyne_persona_reinforce", {"persona_id": persona_id})["status"] == "reinforced"
                assert call("mnemosyne_persona_demote", {"persona_id": persona_id})["status"] == "demoted"

                audit = call("mnemosyne_hygiene_audit", {"limit": 100, "min_score": 0.3})
                assert audit["status"] == "audited"
                candidate = json.dumps([{
                    "memory_id": alpha_id, "table_name": "working_memory", "content_preview": "matrix",
                    "noise_score": 0.4, "noise_reasons": ["matrix test"], "secret_flags": [],
                    "importance": 0.7, "source": "stated", "timestamp": "", "suggested_action": "flag",
                    "content_length": 10,
                }])
                assert call("mnemosyne_hygiene_clean", {
                    "candidates_json": candidate, "action": "flag", "confirm": False,
                })["status"] == "dry_run"
                assert call("mnemosyne_hygiene_clean", {
                    "candidates_json": candidate, "action": "flag", "confirm": True,
                })["status"] == "applied"
                assert call("mnemosyne_hygiene_clean", {"candidates_json": "[]"})["status"] == "dry_run"

                assert call("mnemosyne_invalidate", {"memory_id": beta_id})["status"] == "invalidated"
                assert call("mnemosyne_forget", {"memory_id": beta_id})["status"] == "deleted"
                assert call("mnemosyne_get", {"memory_id": beta_id})["status"] == "not_found"

                print(json.dumps({"status": "ok", "tools": 36}))
                """
            )
            environment = os.environ.copy()
            environment.update(
                {
                    "PYTHONPATH": str(ROOT / "src"),
                    "MATRIX_ROOT": directory,
                    "MNEMOSYNE_DATA_DIR": str(Path(directory) / "data"),
                    "MNEMOSYNE_HOME": str(Path(directory) / "home"),
                    "HERMES_HOME": str(Path(directory) / "hermes"),
                    "MNEMOSYNE_MCP_BANK": "coding",
                    "MNEMOSYNE_AUTHOR_ID": "codex",
                    "MNEMOSYNE_SHARED_DB_PATH": str(Path(directory) / "shared" / "mnemosyne.db"),
                }
            )
            result = subprocess.run(
                [str(REAL_PYTHON), "-c", script],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=90,
            )
            self.assertEqual(0, result.returncode, result.stderr + "\n" + result.stdout)
            self.assertEqual({"status": "ok", "tools": 36}, json.loads(result.stdout.strip().splitlines()[-1]))


if __name__ == "__main__":
    unittest.main()
