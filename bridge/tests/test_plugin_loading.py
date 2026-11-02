# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from bridge.services.plugin_system import PluginSystemService


def test_load_from_dir_hello_world():
    svc = PluginSystemService()
    plugins_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "plugins",
    )
    loaded = svc.load_from_dir(plugins_dir)
    assert "hello_world" in loaded, f"hello_world not in {loaded}"
    ids = [p["id"] for p in svc.list_plugins()]
    assert "hello_world" in ids, f"hello_world not registered: {ids}"


def test_load_from_dir_missing_dir():
    svc = PluginSystemService()
    result = svc.load_from_dir("/nonexistent/path")
    assert result == []


def test_load_from_entry_point_no_group():
    svc = PluginSystemService()
    result = svc.load_from_entry_point(group="lemoncode.nonexistent")
    assert result == []


if __name__ == "__main__":
    test_load_from_dir_hello_world()
    test_load_from_dir_missing_dir()
    test_load_from_entry_point_no_group()
    print("ALL PLUGIN LOADING TESTS PASSED")
