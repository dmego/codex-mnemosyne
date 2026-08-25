import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DocumentationTests(unittest.TestCase):
    def test_readmes_document_portable_setup_and_safety_boundaries(self):
        for filename in ("README.md", "README.zh-CN.md"):
            content = (ROOT / filename).read_text(encoding="utf-8")
            with self.subTest(filename=filename):
                for phrase in (
                    "SessionStart",
                    "UserPromptSubmit",
                    "Stop",
                    "CODEX_MNEMOSYNE_BANK",
                    "MNEMOSYNE_DATA_DIR",
                    "MCP",
                    "secret",
                    "fail-open",
                    "codex plugin marketplace add",
                    "plugins/codex-mnemosyne",
                ):
                    self.assertIn(phrase, content)


if __name__ == "__main__":
    unittest.main()
