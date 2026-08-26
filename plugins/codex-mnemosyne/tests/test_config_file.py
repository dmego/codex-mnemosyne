import os
import tempfile
import unittest
from pathlib import Path


class ConfigFileTests(unittest.TestCase):
    def _config_home(self, content: str):
        directory = tempfile.TemporaryDirectory()
        home = Path(directory.name)
        (home / "config.toml").write_text(content, encoding="utf-8")
        return directory, home

    def test_plugin_scoped_config_drives_hook_defaults(self):
        from codex_mnemosyne.config import Config

        holder, home = self._config_home(
            '''
[plugins."codex-mnemosyne@codex-mnemosyne".mcp_servers.mnemosyne.env]
MNEMOSYNE_MCP_BANK = "coding"
MNEMOSYNE_AUTHOR_ID = "codex"
MNEMOSYNE_AUTHOR_TYPE = "agent"
'''
        )
        try:
            config = Config.from_env({"CODEX_HOME": str(home)})
            self.assertEqual("coding", config.bank)
            self.assertEqual("codex", config.author_id)
            self.assertEqual("agent", config.author_type)
            self.assertTrue(config.config_source.endswith("config.toml"))
        finally:
            holder.cleanup()

    def test_process_environment_overrides_plugin_scoped_config(self):
        from codex_mnemosyne.config import Config

        holder, home = self._config_home(
            '''
[plugins."codex-mnemosyne@codex-mnemosyne".mcp_servers.mnemosyne.env]
MNEMOSYNE_MCP_BANK = "from-file"
'''
        )
        try:
            config = Config.from_env(
                {
                    "CODEX_HOME": str(home),
                    "CODEX_MNEMOSYNE_BANK": "from-process",
                }
            )
            self.assertEqual("from-process", config.bank)
        finally:
            holder.cleanup()

    def test_project_scoped_config_overrides_user_scoped_config(self):
        from codex_mnemosyne.config import Config

        holder, home = self._config_home(
            '''
[plugins."codex-mnemosyne@codex-mnemosyne".mcp_servers.mnemosyne.env]
MNEMOSYNE_MCP_BANK = "user-bank"
'''
        )
        project = Path(holder.name) / "project"
        (project / ".codex").mkdir(parents=True)
        (project / ".codex" / "config.toml").write_text(
            '''
[plugins."codex-mnemosyne@codex-mnemosyne".mcp_servers.mnemosyne.env]
MNEMOSYNE_MCP_BANK = "project-bank"
''',
            encoding="utf-8",
        )
        try:
            config = Config.from_env({"CODEX_HOME": str(home)}, {"cwd": str(project)})
            self.assertEqual("project-bank", config.bank)
            self.assertIn("project/.codex/config.toml", config.config_source)
        finally:
            holder.cleanup()

    def test_apply_config_env_populates_native_values_for_mcp_launcher(self):
        from codex_mnemosyne.config import apply_config_env

        holder, home = self._config_home(
            '''
[plugins."codex-mnemosyne@codex-mnemosyne".mcp_servers.mnemosyne.env]
MNEMOSYNE_MCP_BANK = "coding"
MNEMOSYNE_AUTHOR_ID = "codex"
'''
        )
        try:
            values = {"CODEX_HOME": str(home)}
            apply_config_env(values)
            self.assertEqual("coding", values["MNEMOSYNE_MCP_BANK"])
            self.assertEqual("codex", values["MNEMOSYNE_AUTHOR_ID"])
        finally:
            holder.cleanup()

    def test_diagnostics_are_opt_in_and_content_free(self):
        from codex_mnemosyne.config import Config
        from codex_mnemosyne.diagnostics import record

        with tempfile.TemporaryDirectory() as directory:
            config = Config.from_env(
                {
                    "CODEX_MNEMOSYNE_STATE_DIR": directory,
                    "CODEX_MNEMOSYNE_DIAGNOSTICS": "true",
                }
            )
            record(
                "UserPromptSubmit",
                {"session_id": "s1", "cwd": "/private/project", "prompt": "SECRET_PROMPT"},
                config,
                context_chars=123,
                enqueued=1,
            )
            output = (Path(directory) / "diagnostics.jsonl").read_text(encoding="utf-8")
            self.assertIn('"context_chars": 123', output)
            self.assertNotIn("SECRET_PROMPT", output)
            self.assertNotIn("/private/project", output)


if __name__ == "__main__":
    unittest.main()
