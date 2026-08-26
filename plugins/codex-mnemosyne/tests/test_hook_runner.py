import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "bin" / "mnemosyne-hook.py"


class HookRunnerTests(unittest.TestCase):
    def _run(self, event, payload, fake=True, extra_env=None):
        with tempfile.TemporaryDirectory() as directory:
            environment = os.environ.copy()
            environment["PYTHONPATH"] = f"{ROOT / 'src'}:{directory}"
            environment["CODEX_MNEMOSYNE_STATE_DIR"] = directory
            if fake:
                Path(directory, "mnemosyne.py").write_text(
                    textwrap.dedent(
                        """
                        class Mnemosyne:
                            def __init__(self, **kwargs):
                                self.kwargs = kwargs
                            def get_context(self, limit=5):
                                return [{"content": "session context", "source": "fixture"}]
                            def recall(self, query, top_k=5, **kwargs):
                                return [{"content": "prompt context: " + query, "source": "fixture"}]
                            def remember(self, **kwargs):
                                return "fixture-id"
                        """
                    ),
                    encoding="utf-8",
                )
            if extra_env:
                environment.update(extra_env)
            return subprocess.run(
                [sys.executable, str(RUNNER), event],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                env=environment,
                cwd=ROOT,
                check=False,
            )

    def test_hook_reads_plugin_scoped_codex_config_without_process_env(self):
        with tempfile.TemporaryDirectory() as directory:
            config_home = Path(directory) / "codex-home"
            config_home.mkdir()
            (config_home / "config.toml").write_text(
                '''
[plugins."codex-mnemosyne@codex-mnemosyne".mcp_servers.mnemosyne.env]
MNEMOSYNE_MCP_BANK = "config-bank"
MNEMOSYNE_AUTHOR_ID = "config-author"
''',
                encoding="utf-8",
            )
            fake_module = Path(directory, "mnemosyne.py")
            fake_module.write_text(
                textwrap.dedent(
                    """
                    class Mnemosyne:
                        def __init__(self, **kwargs):
                            self.kwargs = kwargs
                        def get_context(self, limit=5):
                            return [{"content": "bank=" + self.kwargs["bank"] + "; author=" + self.kwargs["author_id"]}]
                        def recall(self, query, top_k=5, **kwargs):
                            return []
                        def remember(self, **kwargs):
                            return "fixture-id"
                    """
                ),
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment["PYTHONPATH"] = f"{ROOT / 'src'}:{directory}"
            environment["CODEX_MNEMOSYNE_STATE_DIR"] = directory
            environment["CODEX_HOME"] = str(config_home)
            environment.pop("CODEX_MNEMOSYNE_BANK", None)
            environment.pop("MNEMOSYNE_MCP_BANK", None)
            result = subprocess.run(
                [sys.executable, str(RUNNER), "SessionStart"],
                input=json.dumps({"session_id": "s1", "cwd": "/work/app"}),
                text=True,
                capture_output=True,
                env=environment,
                cwd=ROOT,
                check=False,
            )
            self.assertEqual(0, result.returncode)
            self.assertIn("bank=config-bank", result.stdout)
            self.assertIn("author=config-author", result.stdout)

    def test_session_start_emits_codex_additional_context(self):
        result = self._run("SessionStart", {"session_id": "s1", "cwd": "/work/app"})

        self.assertEqual(0, result.returncode)
        output = json.loads(result.stdout)
        self.assertEqual("SessionStart", output["hookSpecificOutput"]["hookEventName"])
        self.assertIn("session context", output["hookSpecificOutput"]["additionalContext"])

    def test_prompt_hook_emits_prompt_specific_context(self):
        result = self._run(
            "UserPromptSubmit",
            {"session_id": "s1", "cwd": "/work/app", "prompt": "how do I fix it"},
        )

        self.assertEqual(0, result.returncode)
        output = json.loads(result.stdout)
        self.assertEqual("UserPromptSubmit", output["hookSpecificOutput"]["hookEventName"])
        self.assertIn("how do I fix it", output["hookSpecificOutput"]["additionalContext"])

    def test_write_hook_is_silent_and_unknown_or_malformed_input_is_fail_open(self):
        stop = self._run("Stop", {"session_id": "s1", "cwd": "/work/app"})
        malformed = subprocess.run(
            [sys.executable, str(RUNNER), "UnknownEvent"],
            input="not-json",
            text=True,
            capture_output=True,
            cwd=ROOT,
            check=False,
        )

        self.assertEqual(0, stop.returncode)
        self.assertEqual("", stop.stdout)
        self.assertEqual(0, malformed.returncode)
        self.assertEqual("", malformed.stdout)

    def test_opt_in_diagnostics_prove_context_and_write_hook_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = os.environ.copy()
            environment["PYTHONPATH"] = f"{ROOT / 'src'}:{directory}"
            environment["CODEX_MNEMOSYNE_STATE_DIR"] = directory
            environment["CODEX_MNEMOSYNE_DIAGNOSTICS"] = "true"
            Path(directory, "mnemosyne.py").write_text(
                textwrap.dedent(
                    """
                    class Mnemosyne:
                        def __init__(self, **kwargs):
                            pass
                        def get_context(self, limit=5):
                            return [{"content": "diagnostic context"}]
                        def recall(self, query, top_k=5, **kwargs):
                            return []
                        def remember(self, **kwargs):
                            return "fixture-id"
                    """
                ),
                encoding="utf-8",
            )
            prompt = subprocess.run(
                [sys.executable, str(RUNNER), "SessionStart"],
                input=json.dumps({"session_id": "s1", "cwd": "/private/project"}),
                text=True,
                capture_output=True,
                env=environment,
                cwd=ROOT,
                check=False,
            )
            stop = subprocess.run(
                [sys.executable, str(RUNNER), "Stop"],
                input=json.dumps({"session_id": "s1", "cwd": "/private/project"}),
                text=True,
                capture_output=True,
                env=environment,
                cwd=ROOT,
                check=False,
            )
            self.assertEqual(0, prompt.returncode)
            self.assertEqual(0, stop.returncode)
            records = (Path(directory) / "diagnostics.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(2, len(records))
            self.assertIn('"context_chars": 0', records[1])
            self.assertNotIn("/private/project", "\n".join(records))

    def test_missing_mnemosyne_does_not_fail_the_hook(self):
        result = self._run(
            "UserPromptSubmit",
            {"session_id": "s1", "prompt": "query"},
            fake=False,
            extra_env={"PYTHONPATH": str(ROOT / "src")},
        )

        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_plugin_manifests_are_valid_json(self):
        manifests = [
            ROOT / ".codex-plugin" / "plugin.json",
            ROOT / "hooks" / "hooks.json",
        ]
        for path in manifests:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
