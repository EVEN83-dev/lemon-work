# -*- coding: utf-8 -*-
"""H6: TrajectoryRecorder → session_memory 持久化测试"""
import unittest
from unittest.mock import MagicMock

from bridge.trajectory.trajectory_recorder import TrajectoryRecorder
from shared.tracer import TrajectoryEvent, TrajectoryEventType


class TestTrajectoryPersistence(unittest.TestCase):
    def setUp(self):
        self.memory_system = MagicMock()
        self.recorder = TrajectoryRecorder(memory_system=self.memory_system)

    def test_record_calls_memory_system_store(self):
        event = TrajectoryEvent(
            event_id="evt_001",
            session_id="sess_abc",
            event_type=TrajectoryEventType.TOOL_CALLED,
            timestamp=1700000000.0,
            data={"tool": "read_file"},
            parent_event_id="",
            agent_id="agent_1",
            agent_name="TestAgent",
        )
        self.recorder.record(event)
        self.memory_system.store.assert_called_once()
        args = self.memory_system.store.call_args
        self.assertEqual(args[0][0], "project")
        self.assertEqual(args[0][1], "trajectory:sess_abc:evt_001")
        self.assertIn("event_id", args[0][2])
        self.assertEqual(args[0][2]["event_id"], "evt_001")

    def test_record_no_memory_system_no_error(self):
        recorder = TrajectoryRecorder()
        event = TrajectoryEvent(
            event_id="evt_002",
            session_id="sess_xyz",
            event_type=TrajectoryEventType.TURN_STARTED,
            timestamp=1700000001.0,
            data={},
            parent_event_id="",
            agent_id="agent_2",
            agent_name="SoloAgent",
        )
        recorder.record(event)
        self.assertEqual(len(recorder._events), 1)

    def test_set_memory_system(self):
        recorder = TrajectoryRecorder()
        self.assertIsNone(recorder._memory_system)
        ms = MagicMock()
        recorder.set_memory_system(ms)
        self.assertIs(recorder._memory_system, ms)
        event = TrajectoryEvent(
            event_id="evt_003",
            session_id="sess_def",
            event_type=TrajectoryEventType.TOOL_COMPLETED,
            timestamp=1700000002.0,
            data={},
            parent_event_id="",
            agent_id="agent_3",
            agent_name="LateAgent",
        )
        recorder.record(event)
        ms.store.assert_called_once()

    def test_store_metadata_contains_event_type(self):
        event = TrajectoryEvent(
            event_id="evt_004",
            session_id="sess_meta",
            event_type=TrajectoryEventType.ERROR_OCCURRED,
            timestamp=1700000003.0,
            data={"error": "timeout"},
            parent_event_id="",
            agent_id="agent_4",
            agent_name="MetaAgent",
        )
        self.recorder.record(event)
        metadata = self.memory_system.store.call_args[0][3]
        self.assertIn("event_type", metadata)


if __name__ == "__main__":
    unittest.main()
