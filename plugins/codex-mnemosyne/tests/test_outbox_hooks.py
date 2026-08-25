import json
import tempfile
import unittest
from pathlib import Path


class FakeMemory:
    def __init__(self, results=None, context=None, failure=False):
        self.results = results or []
        self.context = context or []
        self.failure = failure
        self.recall_queries = []
        self.remembered = []

    def recall(self, query, top_k):
        if self.failure:
            raise RuntimeError("recall unavailable")
        self.recall_queries.append((query, top_k))
        return self.results

    def get_context(self, limit):
        if self.failure:
            raise RuntimeError("context unavailable")
        return self.context

    def remember(self, content, metadata):
        if self.failure:
            raise RuntimeError("write unavailable")
        self.remembered.append((content, metadata))
        return "stored-id"


class OutboxTests(unittest.TestCase):
    def test_duplicate_entries_are_not_appended_and_failed_writes_are_retained(self):
        from codex_mnemosyne.outbox import MemoryEntry, Outbox

        with tempfile.TemporaryDirectory() as directory:
            outbox = Outbox(Path(directory), "session-key")
            entry = MemoryEntry("same content", {"kind": "turn"})
            self.assertTrue(outbox.enqueue(entry))
            self.assertFalse(outbox.enqueue(entry))

            failed = outbox.flush(lambda _: (_ for _ in ()).throw(RuntimeError("offline")))
            self.assertEqual(0, failed.written)
            self.assertEqual(1, failed.remaining)

            written = outbox.flush(lambda _: "id")
            self.assertEqual(1, written.written)
            self.assertEqual(0, written.remaining)

    def test_cursor_is_stored_separately_from_pending_memory(self):
        from codex_mnemosyne.outbox import Outbox

        with tempfile.TemporaryDirectory() as directory:
            outbox = Outbox(Path(directory), "session-key")
            self.assertEqual(0, outbox.read_cursor())
            outbox.write_cursor(17)
            self.assertEqual(17, outbox.read_cursor())

    def test_flush_retries_pending_entries_from_other_sessions(self):
        from codex_mnemosyne.outbox import MemoryEntry, Outbox

        with tempfile.TemporaryDirectory() as directory:
            first = Outbox(Path(directory), "first-session")
            second = Outbox(Path(directory), "second-session")
            first.enqueue(MemoryEntry("first", {"kind": "turn"}))
            second.enqueue(MemoryEntry("second", {"kind": "turn"}))
            written = []

            stats = second.flush(lambda entry: written.append(entry.content))

            self.assertEqual(2, stats.written)
            self.assertEqual(["first", "second"], sorted(written))
            self.assertEqual([], first.pending())
            self.assertEqual([], second.pending())


class HookTests(unittest.TestCase):
    def _config(self, directory):
        from codex_mnemosyne.config import Config

        return Config.from_env(
            {
                "CODEX_MNEMOSYNE_STATE_DIR": directory,
                "CODEX_MNEMOSYNE_CAPTURE_MIN_CHARS": "10",
                "CODEX_MNEMOSYNE_RECALL_MAX_CHARS": "200",
            }
        )

    def _transcript(self, directory):
        path = Path(directory) / "rollout.jsonl"
        events = [
            {
                "type": "response_item",
                "payload": {"type": "message", "role": "user", "content": "Fix the flaky test"},
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": "The flaky test now uses a deterministic clock and the focused test passes.",
                },
            },
        ]
        path.write_text("\n".join(json.dumps(item) for item in events) + "\n", encoding="utf-8")
        return path

    def test_session_start_and_prompt_return_bounded_context(self):
        from codex_mnemosyne.hooks import handle_prompt, handle_session_start

        with tempfile.TemporaryDirectory() as directory:
            config = self._config(directory)
            memory = FakeMemory(
                results=[{"content": "prompt memory", "source": "test"}],
                context=[{"content": "recent memory", "source": "test"}],
            )
            payload = {"session_id": "s1", "cwd": "/work/app", "prompt": "What about the test?"}
            start = handle_session_start(payload, config, memory)
            prompt = handle_prompt(payload, config, memory)

            self.assertIn("recent memory", start.additional_context)
            self.assertIn("prompt memory", prompt.additional_context)
            self.assertEqual(("What about the test?", 5), memory.recall_queries[0])

    def test_post_tool_filters_read_only_and_mnemosyne_calls(self):
        from codex_mnemosyne.hooks import handle_post_tool
        from codex_mnemosyne.outbox import Outbox

        with tempfile.TemporaryDirectory() as directory:
            config = self._config(directory)
            outbox = Outbox(Path(directory), "session-key")
            handle_post_tool(
                {"tool_name": "shell", "tool_input": {"command": "ls -la"}},
                config,
                outbox,
            )
            handle_post_tool(
                {"tool_name": "shell", "tool_input": {"command": "pytest -q"}},
                config,
                outbox,
            )
            handle_post_tool(
                {"tool_name": "exec_command", "tool_input": {"cmd": "npm test"}},
                config,
                outbox,
            )
            handle_post_tool(
                {"tool_name": "mcp__mnemosyne__mnemosyne_recall", "tool_input": {}},
                config,
                outbox,
            )
            self.assertEqual(2, len(outbox.pending()))
            self.assertIn("pytest -q", outbox.pending()[0].content)
            self.assertIn("npm test", outbox.pending()[1].content)

    def test_stop_captures_transcript_once_and_flushes(self):
        from codex_mnemosyne.hooks import handle_write_event
        from codex_mnemosyne.outbox import Outbox

        with tempfile.TemporaryDirectory() as directory:
            config = self._config(directory)
            transcript = self._transcript(directory)
            payload = {
                "session_id": "s1",
                "cwd": "/work/app",
                "transcript_path": str(transcript),
            }
            memory = FakeMemory()
            outbox = Outbox(Path(directory), "app-s1")

            handle_write_event("Stop", payload, config, memory, outbox)
            handle_write_event("Stop", payload, config, memory, outbox)

            self.assertEqual(1, len(memory.remembered))
            self.assertIn("deterministic clock", memory.remembered[0][0])
            self.assertEqual(2, outbox.read_cursor())

    def test_hook_failures_are_empty_and_do_not_escape(self):
        from codex_mnemosyne.hooks import handle_prompt, handle_session_start

        with tempfile.TemporaryDirectory() as directory:
            config = self._config(directory)
            memory = FakeMemory(failure=True)
            payload = {"session_id": "s1", "prompt": "query"}
            self.assertIsNone(handle_prompt(payload, config, memory).additional_context)
            self.assertIsNone(handle_session_start(payload, config, memory).additional_context)


if __name__ == "__main__":
    unittest.main()
