import importlib.util
import unittest


HAS_MNEMOSYNE = importlib.util.find_spec("mnemosyne") is not None


@unittest.skipUnless(HAS_MNEMOSYNE, "Mnemosyne runtime is not installed in this test interpreter")
class McpBridgeContractTests(unittest.TestCase):
    def test_bridge_advertises_every_schema_it_can_dispatch(self):
        from codex_mnemosyne.mcp_bridge import McpBridge, OWN_HANDLERS

        bridge = McpBridge()
        names = [item["name"] for item in bridge.tool_definitions()]

        # A core upgrade must never silently shrink the surface: every handler
        # this bridge owns has to stay advertised (Mnemosyne 4.0 narrowed
        # upstream get_tool_definitions(), which used to drop these 8).
        self.assertTrue(OWN_HANDLERS <= set(names), sorted(OWN_HANDLERS - set(names)))
        self.assertIn("mnemosyne_sync_status", names)
        self.assertIn("mnemosyne_persona_promote", names)
        self.assertIn("mnemosyne_triple_end", names)

        # And nothing advertised may be undispatchable -- that is exactly the
        # regression that made 3.12.x advertise schemas with no handler.
        for name in names:
            try:
                bridge.dispatch(name, {})
            except ValueError as exc:
                self.assertNotIn("Unknown tool", str(exc), f"{name} advertised but not dispatchable")

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
