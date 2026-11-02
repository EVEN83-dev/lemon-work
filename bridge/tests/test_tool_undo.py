# -*- coding: utf-8 -*-
"""C6 — undo_tool 本地撤销验证"""
import os
import tempfile

from bridge.tools.builtin_tools import (
    _write_file, _edit_file, undo_last, _list_snapshots,
)
from bridge.tools.tool_def import ToolContext


def _ctx():
    return ToolContext()


def test_undo_overwrite():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "a.txt")
    _write_file({"path": p, "content": "v1\n"}, _ctx())
    _write_file({"path": p, "content": "v2\n"}, _ctx())
    assert open(p).read() == "v2\n"
    r = undo_last(n=1)
    assert r.success, r.error
    assert open(p).read() == "v1\n", "should restore previous content"


def test_undo_edit():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "b.txt")
    _write_file({"path": p, "content": "hello world\n"}, _ctx())
    _edit_file({"path": p, "mode": "string",
                "old_string": "world", "new_string": "earth"}, _ctx())
    assert open(p).read() == "hello earth\n"
    undo_last(n=1)
    assert open(p).read() == "hello world\n"


def test_undo_created_file():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "new.txt")
    _write_file({"path": p, "content": "x\n"}, _ctx())
    assert os.path.exists(p)
    undo_last(n=1)
    assert not os.path.exists(p), "created file should be removed on undo"


def test_history_grows():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "c.txt")
    _write_file({"path": p, "content": "1\n"}, _ctx())
    _write_file({"path": p, "content": "2\n"}, _ctx())
    snaps = _list_snapshots()
    assert len(snaps) >= 2, f"expected >=2 snapshots, got {len(snaps)}"


if __name__ == "__main__":
    test_undo_overwrite()
    test_undo_edit()
    test_undo_created_file()
    test_history_grows()
    print("ALL C6 TESTS PASSED")
