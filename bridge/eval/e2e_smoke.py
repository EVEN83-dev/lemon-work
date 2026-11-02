# -*- coding: utf-8 -*-
"""
C5：端到端串联冒烟测试
======================
ToolRegistry → MemorySystem(semantic) → ReflectionLoop → 全链路断言
"""

import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from bridge.tools.tool_def import ToolRegistry, ToolContext
from bridge.core.memory_system import MemorySystem
from bridge.core.reflection import ReflectionLoop


def run_e2e_smoke():
    tmp_dir = tempfile.mkdtemp(prefix="c5_smoke_")
    refl_dir = os.path.join(tmp_dir, "reflections")
    ctx = ToolContext(session_id="e2e_smoke")

    # 1. ToolRegistry (含 first_party_tools 自动注册)
    registry = ToolRegistry()
    tools = registry.list()
    assert len(tools) >= 6, f"Expected >=6 tools, got {len(tools)}"
    print(f"[1/5] ToolRegistry: {len(tools)} tools registered")

    # 2. MemorySystem + semantic embedding
    mem = MemorySystem(session_id="e2e_smoke", user_id="smoke_user", project_path=tmp_dir)
    mem.store("session", "test_file_content", "API endpoint at /v1/chat handles POST requests")
    mem.store("session", "test_db_info", "Database migration using Alembic for schema changes")
    results = mem.search("接口定义", limit=5)
    assert len(results) > 0, "Semantic memory search should return results"
    print(f"[2/5] MemorySystem: semantic search returned {len(results)} results")

    # 3. read_file + store result
    test_file = os.path.join(tmp_dir, "sample.txt")
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("Line 1: Hello e2e smoke test\nLine 2: API endpoint /v2/data\nLine 3: done\n")

    read_result = registry.execute_tool("read_file", {"path": test_file}, ctx)
    assert read_result.success, f"read_file failed: {read_result.error}"
    assert "Hello e2e" in read_result.output, "read_file must return real text"
    print(f"[3/5] read_file: success, {len(read_result.output)} chars")

    mem.store("session", "read_result", read_result.output[:500])
    recall = mem.search("e2e smoke", limit=3)
    assert len(recall) > 0, "Memory should recall stored read result"
    print(f"[3b/5] Memory recall: {len(recall)} results for 'e2e smoke'")

    # 4. ReflectionLoop
    loop = ReflectionLoop(output_dir=refl_dir)
    refl = loop.reflect(
        session_id="e2e_smoke",
        task_description="E2E smoke test: read file + store in memory",
        tool_calls=[{"skill_name": "read_file", "args": {"path": test_file}}],
        tool_results=[read_result.output[:200]],
        final_output="Successfully read file and stored in memory",
    )
    assert refl.overall_score > 0, "Reflection should have positive score"

    import glob
    md_files = glob.glob(os.path.join(refl_dir, "critique_*.md"))
    assert len(md_files) >= 1, "Must generate critique_*.md"
    print(f"[4/5] Reflection: score={refl.overall_score:.2f}, critiques={len(refl.critiques)}")

    # 5. Export trajectory
    trajectory = {
        "session_id": "e2e_smoke",
        "tool_calls": [{"name": "read_file", "success": True}],
        "memory_results": len(results),
        "reflection_score": refl.overall_score,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    traj_path = os.path.join(tmp_dir, "trajectory.json")
    with open(traj_path, "w", encoding="utf-8") as f:
        json.dump(trajectory, f, ensure_ascii=False, indent=2)
    assert os.path.exists(traj_path), "trajectory.json must exist"
    print(f"[5/5] Trajectory exported: {traj_path}")

    print("\nE2E SMOKE: ALL 4 ASSERTIONS PASSED")
    return True


def run_all() -> dict:
    passed = 0
    total = 5
    errors = []
    try:
        run_e2e_smoke()
        passed = total
    except AssertionError as e:
        errors.append(str(e))
        passed = max(0, passed)
    except Exception as e:
        errors.append(str(e))
    score = passed / total if total > 0 else 0.0
    return {"score": score, "passed": passed, "total": total, "errors": errors}


if __name__ == "__main__":
    run_e2e_smoke()
