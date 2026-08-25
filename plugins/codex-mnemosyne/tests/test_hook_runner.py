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
                            def recall(self, query, top_k=5):
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
