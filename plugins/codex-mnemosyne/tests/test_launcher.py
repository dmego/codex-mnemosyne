import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "bin" / "mnemosyne-hook"
DOCTOR = ROOT / "bin" / "mnemosyne-doctor"


class LauncherTests(unittest.TestCase):
    def _environment(self, directory, module=True):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = f"{ROOT / 'src'}:{directory}"
        environment["CODEX_MNEMOSYNE_STATE_DIR"] = directory
        if module:
            Path(directory, "mnemosyne.py").write_text(
                textwrap.dedent(
                    """
                    __version__ = "fixture"

                    class Mnemosyne:
                        def __init__(self, **kwargs):
                            self.kwargs = kwargs

                        def get_context(self, limit=5):
                            return [{"content": "launcher context", "source": "fixture"}]

                        def recall(self, query, top_k=5, **kwargs):
                            return [{"content": query, "source": "fixture"}]

                        def remember(self, **kwargs):
                            return "fixture-id"
                    """
                ),
                encoding="utf-8",
            )
        return environment

    def test_launcher_uses_explicit_python_override(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = self._environment(directory)
            environment["CODEX_MNEMOSYNE_PYTHON"] = sys.executable
            result = subprocess.run(
                [str(LAUNCHER), "SessionStart"],
                input=json.dumps({"session_id": "s1", "cwd": "/work/app"}),
                text=True,
                capture_output=True,
                env=environment,
                cwd=ROOT,
                check=False,
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("launcher context", result.stdout)
            self.assertEqual("", result.stderr)

    def test_resolver_prefers_plugin_local_venv_without_override(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin_root = Path(directory) / "plugin"
            python_path = plugin_root / ".venv" / "bin" / "python"
            python_path.parent.mkdir(parents=True)
            python_path.symlink_to(sys.executable)
            environment = self._environment(directory)
            environment.pop("CODEX_MNEMOSYNE_PYTHON", None)
            environment["PLUGIN_ROOT"] = str(plugin_root)
            environment["PATH"] = "/usr/bin:/bin"
            result = subprocess.run(
                [str(ROOT / "bin" / "mnemosyne-resolve-python")],
                text=True,
                capture_output=True,
                env=environment,
                cwd=ROOT,
                check=False,
            )

            self.assertEqual(0, result.returncode)
            self.assertEqual(str(python_path), result.stdout.strip())
            self.assertEqual("", result.stderr)

    def test_doctor_reports_resolved_python_and_sdk(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = self._environment(directory)
            environment["CODEX_MNEMOSYNE_PYTHON"] = sys.executable
            result = subprocess.run(
                [str(DOCTOR)],
                text=True,
                capture_output=True,
                env=environment,
                cwd=ROOT,
                check=False,
            )

            self.assertEqual(0, result.returncode)
            report = json.loads(result.stdout)
            self.assertEqual(sys.executable, report["python"])
            self.assertTrue(report["sdk_importable"])
            self.assertEqual("fixture", report["mnemosyne_version"])
            self.assertIn("remember", report["capabilities"])

    def test_hook_manifest_keeps_compatible_python_entrypoint(self):
        manifest = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        commands = [
            hook["command"]
            for groups in manifest["hooks"].values()
            for group in groups
            for hook in group["hooks"]
        ]
        self.assertTrue(commands)
        self.assertTrue(all("python3" in command for command in commands))
        self.assertTrue(all("mnemosyne-hook.py" in command for command in commands))


if __name__ == "__main__":
    unittest.main()
