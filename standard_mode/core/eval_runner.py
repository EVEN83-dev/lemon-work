# -*- coding: utf-8 -*-
"""364章 T5.2: 评测集 — 标准化测试用例运行器"""

import json
import os
import shutil
import tempfile
import time
from typing import Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class EvalCase:
    case_id: str
    category: str
    prompt: str
    expected_keywords: List[str] = field(default_factory=list)
    expected_tools: List[str] = field(default_factory=list)
    timeout: int = 60
    difficulty: str = "medium"
    target_tool: str = ""
    target_args: Dict = field(default_factory=dict)


@dataclass
class EvalResult:
    case_id: str
    passed: bool
    score: float
    response: str = ""
    tools_used: List[str] = field(default_factory=list)
    duration: float = 0.0
    error: str = ""


_FILE_CATEGORIES = {"file", "system", "pc_tool"}


class EvalRunner:
    def __init__(self, eval_dir: str = ""):
        if not eval_dir:
            eval_dir = os.path.join(os.getcwd(), "data", "evals")
        self.eval_dir = os.path.expanduser(eval_dir)
        os.makedirs(self.eval_dir, exist_ok=True)
        self._cases: Dict[str, EvalCase] = {}
        self._results: List[EvalResult] = []
        self._registry = None

    def _get_registry(self):
        if self._registry is not None:
            return self._registry
        try:
            sys_path = os.path.join(os.path.dirname(__file__), '..')
            if sys_path not in os.sys.path:
                os.sys.path.insert(0, sys_path)
            from skills_registry import SkillsRegistry, _register_builtin_skills
            self._registry = SkillsRegistry()
            _register_builtin_skills(self._registry)
        except Exception:
            self._registry = None
        return self._registry

    def add_case(self, case: EvalCase):
        self._cases[case.case_id] = case

    def load_cases(self, json_path: str) -> int:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        count = 0
        for item in data:
            case = EvalCase(
                case_id=item.get("id", f"case_{count}"),
                category=item.get("category", "general"),
                prompt=item.get("prompt", ""),
                expected_keywords=item.get("expected_keywords", []),
                expected_tools=item.get("expected_tools", []),
                timeout=item.get("timeout", 60),
                difficulty=item.get("difficulty", "medium"),
                target_tool=item.get("target_tool", ""),
                target_args=item.get("target_args", {}),
            )
            self._cases[case.case_id] = case
            count += 1
        return count

    def run_eval(self, case_id: str, response_fn=None,
                 tools_used: List[str] = None) -> EvalResult:
        case = self._cases.get(case_id)
        if not case:
            return EvalResult(case_id=case_id, passed=False, score=0, error="Case not found")

        start = time.time()
        response = ""
        actual_tools_used = []

        # ★ T366.2: target_tool → 直接调 registry.execute
        if case.target_tool:
            registry = self._get_registry()
            if not registry:
                return EvalResult(case_id=case_id, passed=False, score=0,
                                  error="SkillsRegistry not available")
            args = dict(case.target_args)
            # ★ T366.2: 文件类用例在临时工作区执行
            is_file_case = case.category in _FILE_CATEGORIES
            tmp_dir = None
            if is_file_case:
                tmp_dir = tempfile.mkdtemp(prefix="eval_")
                for k, v in args.items():
                    if isinstance(v, str) and ("file_path" in k or "path" in k or "directory" in k or "dir" in k):
                        args[k] = os.path.join(tmp_dir, v.replace("/", os.sep).replace("\\", os.sep))
            try:
                result = registry.execute(case.target_tool, args)
                response = (result.output or "") + (result.error or "")
                actual_tools_used = [case.target_tool]
                if not result.success:
                    response += f" [ERROR: {result.error}]"
            except Exception as e:
                response = f"执行异常: {e}"
            finally:
                if tmp_dir:
                    try:
                        shutil.rmtree(tmp_dir, ignore_errors=True)
                    except Exception:
                        pass
        elif response_fn:
            try:
                response = response_fn(case.prompt)
            except Exception as e:
                return EvalResult(case_id=case_id, passed=False, score=0,
                                  error=str(e), duration=time.time() - start)

        duration = time.time() - start
        score = 0.0
        max_score = 0.0

        if case.expected_keywords:
            max_score += len(case.expected_keywords)
            response_lower = response.lower() if response else ""
            for kw in case.expected_keywords:
                if kw.lower() in response_lower:
                    score += 1.0

        used = actual_tools_used or tools_used or []
        if case.expected_tools:
            max_score += len(case.expected_tools)
            for tool in case.expected_tools:
                if tool in used:
                    score += 1.0

        if max_score == 0:
            passed = bool(response)
            score = 1.0 if passed else 0.0
        else:
            passed = score / max_score >= 0.5

        result = EvalResult(
            case_id=case_id, passed=passed, score=score,
            response=response[:500], tools_used=used,
            duration=duration,
        )
        self._results.append(result)
        return result

    def run_all(self, response_fn=None) -> Dict:
        results = []
        for case_id in self._cases:
            r = self.run_eval(case_id, response_fn)
            results.append(r)

        passed = sum(1 for r in results if r.passed)
        total = len(results)
        avg_score = sum(r.score for r in results) / max(total, 1)
        avg_duration = sum(r.duration for r in results) / max(total, 1)

        by_category = {}
        for r in results:
            cat = self._cases[r.case_id].category
            by_category.setdefault(cat, {"passed": 0, "total": 0, "score": 0.0})
            by_category[cat]["total"] += 1
            by_category[cat]["score"] += r.score
            if r.passed:
                by_category[cat]["passed"] += 1

        return {
            "total": total,
            "passed": passed,
            "pass_rate": round(passed / max(total, 1), 3),
            "avg_score": round(avg_score, 3),
            "avg_duration": round(avg_duration, 2),
            "by_category": by_category,
        }

    def save_results(self, path: str = ""):
        if not path:
            path = os.path.join(self.eval_dir, "eval_results.json")
        data = [{
            "case_id": r.case_id, "passed": r.passed, "score": r.score,
            "duration": r.duration, "tools_used": r.tools_used,
            "error": r.error,
        } for r in self._results]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_builtin_cases(self) -> int:
        """T365.16: 加载内置20用例评测集"""
        builtin_path = os.path.join(
            os.path.dirname(__file__), '..', '..', 'data', 'evals', 'eval_cases.json')
        builtin_path = os.path.normpath(builtin_path)
        if os.path.isfile(builtin_path):
            return self.load_cases(builtin_path)
        return 0


def main():
    """T365.16: 评测集CLI入口"""
    import sys
    runner = EvalRunner()
    count = runner.load_builtin_cases()
    print(f"已加载 {count} 个评测用例")

    if len(sys.argv) > 1 and sys.argv[1] == "--run":
        print("运行评测集...")
        summary = runner.run_all()
        print(f"总计: {summary['total']}, 通过: {summary['passed']}, "
              f"通过率: {summary['pass_rate']}, 平均分: {summary['avg_score']}")
        for cat, info in summary.get('by_category', {}).items():
            print(f"  {cat}: {info['passed']}/{info['total']}")
        runner.save_results()
        print("结果已保存到 data/evals/eval_results.json")
    elif len(sys.argv) > 1 and sys.argv[1] == "--list":
        for cid, case in runner._cases.items():
            print(f"  {cid}: [{case.category}] {case.prompt[:40]}... "
                  f"(难度={case.difficulty}, 工具={case.expected_tools})")
    else:
        print("Usage: python -m core.eval_runner [--list|--run]")


if __name__ == "__main__":
    main()
