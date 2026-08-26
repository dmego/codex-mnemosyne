import importlib.util
import unittest


HAS_MNEMOSYNE = importlib.util.find_spec("mnemosyne") is not None


@unittest.skipUnless(HAS_MNEMOSYNE, "Mnemosyne runtime is not installed in this test interpreter")
class McpBridgeContractTests(unittest.TestCase):
    def test_bridge_uses_public_dispatch_and_exposes_all_schemas(self):
        from codex_mnemosyne.mcp_bridge import McpBridge

        bridge = McpBridge()
        names = {item["name"] for item in bridge.tool_definitions()}
        self.assertEqual(36, len(names))
        self.assertIn("mnemosyne_sync_status", names)
        self.assertIn("mnemosyne_persona_promote", names)
        self.assertEqual("ok", bridge.dispatch("mnemosyne_sync_status", {}).get("status"))

    def test_missing_tool_handler_is_not_installed_into_upstream_private_table(self):
        import mnemosyne.mcp_tools as upstream
        from codex_mnemosyne.mcp_bridge import McpBridge

        before = dict(upstream._TOOL_HANDLERS)
        McpBridge().dispatch("mnemosyne_sync_status", {})
        self.assertEqual(before, dict(upstream._TOOL_HANDLERS))
        self.assertNotIn("mnemosyne_sync_status", before)


if __name__ == "__main__":
    unittest.main()
