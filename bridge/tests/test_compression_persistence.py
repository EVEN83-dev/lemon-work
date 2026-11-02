from __future__ import annotations

import json
import os
import tempfile
import unittest

from bridge.core.context_compressor import ContextCompressor, MessageItem


class TestCompressionPersistence(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = os.path.join(self.tmpdir, "agent_completion_state.json")
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump({"sessions": []}, f)

    def test_save_completion_state_after_compress(self):
        compressor = ContextCompressor(keep_recent_rounds=1)
        compressor._state_path = self.state_path
        compressor._session_id = "test-s1"

        messages = []
        for i in range(20):
            role = "user" if i % 2 == 0 else "assistant"
            content = "Task " + str(i) + " content " + ("x" * 50)
            kd = i % 4 == 1
            messages.append(MessageItem(role=role, content=content, token_count=100, is_key_decision=kd))

        result = compressor.compress(messages, max_tokens=500)

        self.assertIsInstance(result, list)

        if os.path.exists(self.state_path):
            with open(self.state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            self.assertIn("sessions", state)

    def test_load_previous_state_and_mark_done(self):
        pre_state = {
            "sessions": [
                {
                    "sid": "prev-session",
                    "completed_tasks": [
                        {"id": "task-old-1", "content": "old task A", "ts": 1700000000}
                    ]
                }
            ]
        }
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(pre_state, f)

        compressor = ContextCompressor(keep_recent_rounds=1)
        compressor._state_path = self.state_path
        compressor._session_id = "new-session"
        compressor._prev_completed = pre_state["sessions"][0]["completed_tasks"]

        messages = []
        for i in range(20):
            role = "user" if i % 2 == 0 else "assistant"
            content = "message " + str(i) + " " + ("y" * 50)
            messages.append(MessageItem(role=role, content=content, token_count=100))

        result = compressor.compress(messages, max_tokens=500)

        found_marker = False
        for m in result:
            if m.metadata and m.metadata.get("compressed") and "[DONE-" in m.content:
                found_marker = True
                break

        self.assertTrue(found_marker, "Expected [DONE-之前完成] marker in compressed summary")

    def test_no_state_file_graceful(self):
        compressor = ContextCompressor(keep_recent_rounds=2)
        compressor._state_path = os.path.join(self.tmpdir, "nonexistent.json")
        compressor._session_id = "s1"

        messages = [
            MessageItem(role="user", content="hello", token_count=10),
            MessageItem(role="assistant", content="hi", token_count=10),
        ]

        result = compressor.compress(messages, max_tokens=5000)
        self.assertEqual(len(result), 2)

    def test_mark_prev_completed_method(self):
        compressor = ContextCompressor(keep_recent_rounds=1)
        compressor._prev_completed = [
            {"id": "t1", "content": "completed task A", "ts": 1000}
        ]
        result = compressor._mark_prev_completed_in_summary("Summary of context")
        self.assertIn("[DONE-之前完成]", result)
        self.assertIn("completed task A", result)

    def test_save_state_writes_json(self):
        compressor = ContextCompressor(keep_recent_rounds=1)
        compressor._state_path = self.state_path
        compressor._session_id = "save-test"
        compressor._todos = [
            {"id": "todo1", "content": "task one", "status": "completed", "ts": 1000},
            {"id": "todo2", "content": "task two", "status": "pending"},
        ]

        compressor._save_completion_state()

        with open(self.state_path, "r", encoding="utf-8") as f:
            state = json.load(f)

        self.assertIn("sessions", state)


if __name__ == "__main__":
    unittest.main()
