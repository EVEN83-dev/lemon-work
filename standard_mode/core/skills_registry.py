# -*- coding: utf-8 -*-
"""
Skills 技能系统 — Agent 可调用的工具函数
========================================
当使用本地 Ollama 或 DeepSeek 云端引擎时，Agent 需要
通过工具调用（function calling）来执行代码、操作文件等。

每个 Skill 是一个可调用的函数，附带 JSON Schema 描述，
供大模型自动选择调用。

技能类型：
- code_executor  : 代码执行（Python/C/C++/Java 等）
- file_reader    : 文件读取
- file_writer    : 文件写入
- file_searcher  : 文件搜索（glob/grep）
- web_fetcher    : 网页内容获取
- command_runner : 系统命令执行
- project_scanner: 项目文件扫描
- knowledge_query: 知识库查询
"""

import json
import os
import re
import subprocess
import tempfile
import threading
from typing import Dict, List, Optional, Callable, Any, Tuple
from dataclasses import dataclass, field


def _coerce_json_param(value) -> str:
    """将任意类型的 JSON 参数强制转为字符串，兼容 DeepSeek 等引擎直接传数组/对象/null 的行为"""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return ""
    return str(value)


def _parse_skill_result_repr(text: str) -> Optional[Dict]:
    """解析 'SkillResult(success=..., output=..., error=..., data=...)' 字符串。
    在顶层括号深度提取关键字值，支持嵌套引号和括号。
    返回 dict{success, output, error, data} 或 None。
    """
    import ast as _ast
    text = text.strip()
    if not text.startswith("SkillResult("):
        return None
    depth = 0
    end = -1
    for i, ch in enumerate(text):
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0:
                end = i
                break
    if end < 0:
        return None
    body = text[len("SkillResult("):end]

    # 在顶层（depth=0）按 ', ' 分割关键字对
    # 需要跟踪括号和引号深度
    tokens = []
    cur = []
    pd = 0
    in_q = None
    j = 0
    while j < len(body):
        ch = body[j]
        if in_q:
            cur.append(ch)
            if ch == '\\' and j + 1 < len(body):
                j += 1
                cur.append(body[j])
            elif ch == in_q:
                in_q = None
            j += 1
            continue
        if ch in ('"', "'"):
            in_q = ch
            cur.append(ch)
            j += 1
            continue
        if ch == '(' or ch == '{' or ch == '[':
            pd += 1
            cur.append(ch)
        elif ch == ')' or ch == '}' or ch == ']':
            pd -= 1
            cur.append(ch)
        elif ch == ',' and pd == 0:
            tokens.append(''.join(cur).strip())
            cur = []
            j += 1
            continue
        else:
            cur.append(ch)
        j += 1
    if cur:
        tokens.append(''.join(cur).strip())

    # 从 tokens 中提取关键字
    result = {}
    for tok in tokens:
        eq = tok.find('=')
        if eq < 0:
            continue
        key = tok[:eq].strip()
        val = tok[eq + 1:].strip()
        if key == 'success':
            result['success'] = val == 'True'
        elif key == 'output':
            try:
                result['output'] = _ast.literal_eval(val) if val not in ('True', 'False', 'None') else val
            except Exception:
                result['output'] = val
        elif key == 'error':
            try:
                result['error'] = _ast.literal_eval(val) if val not in ('True', 'False', 'None') else val
            except Exception:
                result['error'] = val
        elif key == 'data':
            if val == 'None':
                result['data'] = None
            elif val.startswith('{'):
                try:
                    result['data'] = json.loads(val)
                except Exception:
                    try:
                        result['data'] = _ast.literal_eval(val)
                    except Exception:
                        result['data'] = None
            else:
                result['data'] = None

    if 'success' not in result or 'output' not in result or 'error' not in result:
        return None
    return result


def _unpack_nested_skill_result(result: "SkillResult", max_depth: int = 5) -> "SkillResult":
    """★ 370-2: 循环解包嵌套 SkillResult（后端根治，前端369-2防御补丁自此可移除）

    若 result.output 以 "SkillResult(" 开头，逐层解析剥到最内层。
    最内层 success=False 时，外层结果必须置为失败并把最内层 error 提到外层。
    深度上限 max_depth，解析失败保留原文（降级不抛异常）。
    """
    for _ in range(max_depth):
        out = result.output or ""
        if not isinstance(out, str) or not out.lstrip().startswith("SkillResult("):
            break
        parsed = _parse_skill_result_repr(out.lstrip())
        if parsed is None:
            break
        try:
            inner_data = parsed.get("data")
            result = SkillResult(
                success=parsed["success"],
                output=str(parsed["output"]) if parsed["output"] is not None else "",
                error=str(parsed["error"]) if parsed["error"] else (result.error or ""),
                data=inner_data if isinstance(inner_data, dict) else result.data,
            )
        except Exception:
            break
    return result


# ==================== Skills 数据模型 ====================

@dataclass
class SkillDef:
    """技能定义"""
    name: str                      # 技能名称（供模型调用）
    description: str               # 技能描述
    parameters: Dict                # JSON Schema 格式的参数定义
    handler: Callable               # 执行函数
    category: str = "general"      # 分类
    requires_confirm: bool = False  # 是否需要用户确认
    timeout: int = 30              # 超时时间（秒）
    pre_hooks: List[str] = None    # T365.8: 前置钩子函数名列表
    post_hooks: List[str] = None   # T365.8: 后置钩子函数名列表
    # 386B-4: schema 质量分层 —— 由 shared/skill_schema_overrides.apply_overrides 注入
    skip_reason: str = ""          # 非空 = 环境依赖/危险操作，从默认技能菜单剔除
    argcheck_example: Dict = None  # 参数示例（模型可见，提升一次传参成功率）


@dataclass
class SkillResult:
    """技能执行结果"""
    success: bool
    output: str = ""
    error: str = ""
    data: Any = None

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
        }


# ==================== 技能注册表 ====================

_READ_ONLY_TOOLS = frozenset([
    "read_file", "list_directory", "search_files", "grep_search", "scan_project",
    "query_knowledge_base", "web_fetch", "web_search", "search_codebase",
    "execute_code", "code_review", "math_solver", "info_debater", "math_plotter",
    "image_analyzer", "fact_checker", "deep_researcher", "arxiv_researcher",
    "super_researcher", "web_researcher", "screenshot_qa", "system_report",
    "ocr_reader", "clipboard_helper", "duplicate_finder", "translator",
    "autocheck_runner",
])


def _record_tmp_usage(name: str, success: bool):
    """★394C-1: 临时技能调用记账（成功/失败计数 → data/tmp_skills/usage.json）。

    成功 ≥3 次触发转正提名（tmp_skill_manager 内部处理，含事件通知）。
    任何异常静默吞掉——记账绝不影响技能执行主链路。
    """
    if not name.startswith("tmp_"):
        return
    try:
        from .skills import tmp_skill_manager as _tsm
    except ImportError:
        try:
            from core.skills import tmp_skill_manager as _tsm
        except Exception:
            return
    try:
        _tsm.record_usage(name, success)
    except Exception:
        pass


class SkillsRegistry:
    """技能注册表 — 管理所有可用技能

    Standard-mode skills registry for the desktop (Qt) runtime path.
    This is the canonical implementation; bridge/skills/registry.py is a
    decoupled mirror that should maintain API parity with this class.
    Core methods: register, unregister, get, list_skills, execute, count.
    """

    def __init__(self):
        self._skills: Dict[str, SkillDef] = {}
        self._lock = threading.Lock()
        self._permission_mode: str = "confirm"
        # ★ 394B-1.3: 临时技能命名空间跟踪（tmp_ 前缀，会话级生命周期）
        self._temporary_names: set = set()
        # ★ T365.8: HookManager
        self._hook_manager = None
        try:
            from core.hook_manager import HookManager
            self._hook_manager = HookManager()
        except Exception:
            pass

    def register(self, skill: SkillDef):
        """注册技能"""
        with self._lock:
            self._skills[skill.name] = skill

    def unregister(self, name: str):
        """注销技能"""
        with self._lock:
            self._skills.pop(name, None)
            self._temporary_names.discard(name)

    # =========================================================
    # ★ 394B-1.3: 临时技能注册 —— 独立命名空间 + [临时] 徽章 + 会话级生命周期
    #   规范：tmp_<领域>_<功能>；菜单可见（description 徽章随既有通道透出）；
    #   与正式技能严格隔离（禁止覆盖同名正式技能）；注册表不过夜，
    #   代码落盘 data/tmp_skills/ 可显式复活（tmp_skill_manager.revive）。
    # =========================================================

    def register_temporary(self, skill: SkillDef) -> Tuple[bool, str]:
        """注册临时技能。三关验证通过后才允许调用本方法（由 skill_creator 把关）。"""
        name = skill.name or ""
        if not name.startswith("tmp_"):
            return False, f"临时技能名必须以 tmp_ 前缀命名（tmp_<领域>_<功能>）: '{name}'"
        with self._lock:
            existing = self._skills.get(name)
            if existing is not None and name not in self._temporary_names:
                return False, f"'{name}' 已被正式技能占用，临时命名空间禁止覆盖"
            if name in self._temporary_names:
                return False, f"临时技能 '{name}' 已在注册表中（如需重建请先 cleanup）"
            if not (skill.description or "").startswith("[临时]"):
                skill.description = "[临时] " + (skill.description or "")
            self._skills[name] = skill
            self._temporary_names.add(name)
        return True, (f"临时技能 '{name}' 已注册（菜单可见带[临时]徽章，"
                      f"会话结束注销，代码保留于 data/tmp_skills/）")

    def unregister_temporary(self, name: str) -> bool:
        """注销单个临时技能。"""
        with self._lock:
            if name not in self._temporary_names:
                return False
            self._skills.pop(name, None)
            self._temporary_names.discard(name)
        return True

    def cleanup_temporary(self) -> List[str]:
        """会话清理：注销全部临时技能（代码保留 data/tmp_skills/ 可复活）。"""
        with self._lock:
            names = list(self._temporary_names)
        for n in names:
            self.unregister_temporary(n)
        return names

    def is_temporary(self, name: str) -> bool:
        with self._lock:
            return name in self._temporary_names

    def list_temporary(self) -> List[str]:
        with self._lock:
            return sorted(self._temporary_names)

    def get(self, name: str) -> Optional[SkillDef]:
        """获取技能"""
        with self._lock:
            return self._skills.get(name)

    def get_skill(self, name: str) -> Optional[SkillDef]:
        """获取技能（get 的别名 —— 与 skill_market/plugin_system 命名保持一致）"""
        return self.get(name)

    def list_skills(self, category: str = "") -> List[SkillDef]:
        """列出技能"""
        with self._lock:
            if category:
                return [s for s in self._skills.values() if s.category == category]
            return list(self._skills.values())

    def get_tool_definitions(self) -> List[Dict]:
        """获取所有技能的工具定义（OpenAI function calling 格式）

        386B-4: skip_reason 非空的技能（环境依赖/危险操作）自动从菜单剔除，
        防小模型误选直调必败技能。
        """
        tools = []
        with self._lock:
            for skill in self._skills.values():
                if getattr(skill, "skip_reason", ""):
                    continue
                tools.append({
                    "type": "function",
                    "function": {
                        "name": skill.name,
                        "description": skill.description,
                        "parameters": skill.parameters,
                    },
                })
        return tools

    def execute(self, name: str, args: Dict) -> SkillResult:
        """执行技能"""
        skill = self.get(name)
        if skill is None:
            return SkillResult(success=False, error=f"技能 '{name}' 未注册")
        with self._lock:
            mode = self._permission_mode
        if mode == "readonly" and name not in _READ_ONLY_TOOLS:
            return SkillResult(
                success=False,
                error=f"[364章] 只读模式下禁止执行 '{name}'（仅允许读取/搜索类工具），"
                      f"请切换到 确认/自动 模式后重试",
            )
        # ★ v5.3: 从 _context 提取 project_root 作为运行时上下文（不再注入到 handler kwargs，
        # 因为基础文件工具的 handler 签名只接受 path/command/pattern，不接受 project_root），
        # 改为临时切换 os.chdir 让 handler 用相对路径时基于用户项目根。
        import os as _os
        import inspect as _inspect
        _call_args = dict(args) if args else {}
        _ctx = _call_args.pop("_context", None) or {}
        _project_root = _ctx.get("project_root") if isinstance(_ctx, dict) else None
        # ★第361章: session_id 透传 — 引擎侧 agent 循环注入当前会话 ID，
        #   声明了 session_id 形参的 handler（如 task_manager）据此实现会话隔离。
        _session_id = _ctx.get("session_id") if isinstance(_ctx, dict) else None
        if _session_id and "session_id" in getattr(skill.handler, "__annotations__", {}) \
                and "session_id" not in _call_args:
            try:
                _sig = _inspect.signature(skill.handler)
                if "session_id" in _sig.parameters:
                    _call_args["session_id"] = str(_session_id)
            except (TypeError, ValueError):
                pass
        _old_cwd = None
        if _project_root and _os.path.isdir(_project_root):
            try:
                _old_cwd = _os.getcwd()
                _os.chdir(_project_root)
            except Exception:
                _old_cwd = None
        try:
            # ★ T365.8: fire before hooks
            if self._hook_manager:
                try:
                    self._hook_manager.fire_before(name, args)
                except Exception:
                    pass
            result = skill.handler(**_call_args)
            # ★ T365.8: fire after hooks
            if self._hook_manager:
                try:
                    self._hook_manager.fire_after(name, result=result, args=args)
                except Exception:
                    pass
            if isinstance(result, SkillResult) or (hasattr(result, '__class__') and result.__class__.__name__ == 'SkillResult'):
                # ★ 370-2: 解包嵌套 SkillResult（根治三层repr，前端369-2防御补丁自此可移除）
                result = _unpack_nested_skill_result(result)
                if mode == "auto":
                    result.data = result.data or {}
                    if isinstance(result.data, dict):
                        result.data["_auto_mode"] = True
                _record_tmp_usage(name, bool(result.success))
                return result
            out = str(result)
            data = {"_auto_mode": True} if mode == "auto" else None
            result = SkillResult(success=True, output=out, data=data)
            # ★ 374-1: str 分支同样解包（module 技能 handler 返回 str 化嵌套 SkillResult 时从此漏出）
            result = _unpack_nested_skill_result(result)
            _record_tmp_usage(name, bool(result.success))
            return result
        except Exception as e:
            # ★ T365.8: fire error hooks
            if self._hook_manager:
                try:
                    self._hook_manager.fire_error(name, str(e), args)
                except Exception:
                    pass
            _record_tmp_usage(name, False)
            return SkillResult(success=False, error=str(e))
        finally:
            if _old_cwd is not None:
                try:
                    _os.chdir(_old_cwd)
                except Exception:
                    pass

    def count(self) -> int:
        return len(self._skills)

    def set_permission_mode(self, mode: str):
        if mode not in ("readonly", "confirm", "auto"):
            raise ValueError(f"Invalid permission_mode: {mode}")
        with self._lock:
            self._permission_mode = mode

    def get_permission_mode(self) -> str:
        with self._lock:
            return self._permission_mode

    # ★ v3.160: 热加载 + 动态注册/卸载
    def reload_skill(self, name: str, new_handler: Callable) -> bool:
        """热重载单个 Skill（不重启服务）"""
        with self._lock:
            if name in self._skills:
                self._skills[name].handler = new_handler
                return True
            return False

    def reload_category(self, category: str, new_skills: List[SkillDef]) -> int:
        """热重载整个分类的 Skill"""
        count = 0
        with self._lock:
            # 移除旧分类
            old = [n for n, s in self._skills.items() if s.category == category]
            for n in old:
                del self._skills[n]
            # 注册新分类
            for skill in new_skills:
                self._skills[skill.name] = skill
                count += 1
        return count

    def watch_skills_directory(self, directory: str, interval: float = 30.0):
        """监听 Skill 目录变化，自动热加载

        优化（★ 解决周期性 I/O 抖动）：
        - 用 mtime + size 判断变更，替代每次全量 md5 读文件（省 I/O）
        - 默认间隔从 5s 提升到 30s（显著降低磁盘抖动）
        - importlib 热加载加 0.3s 防抖（避免编辑器保存中途被半加载）

        Args:
            directory: Skill 文件目录
            interval: 检查间隔（秒，默认 30）
        """
        import hashlib

        def _mtime_size(fpath):
            try:
                st = os.stat(fpath)
                return (st.st_mtime, st.st_size)
            except Exception:
                return None

        def _watch():
            file_sig = {}  # fname -> (mtime, size)
            _last_reload = {}
            while True:
                try:
                    if os.path.exists(directory):
                        for fname in os.listdir(directory):
                            if fname.endswith(".py") and not fname.startswith("_"):
                                fpath = os.path.join(directory, fname)
                                sig = _mtime_size(fpath)
                                if sig is None:
                                    continue
                                old = file_sig.get(fname)
                                if old is None:
                                    file_sig[fname] = sig
                                    continue
                                if sig != old:
                                    file_sig[fname] = sig
                                    print(f"[SkillsRegistry] 检测到 Skill 变更: {fname}")
                                    # ★ 防抖：0.3s 后再读，避免编辑器保存中途半加载
                                    time.sleep(0.3)
                                    if _mtime_size(fpath) != sig:
                                        continue
                                    try:
                                        import importlib.util
                                        spec = importlib.util.spec_from_file_location(
                                            fname.replace(".py", ""), fpath
                                        )
                                        mod = importlib.util.module_from_spec(spec)
                                        spec.loader.exec_module(mod)
                                        if hasattr(mod, "register_skills"):
                                            mod.register_skills(self)
                                            print(f"[SkillsRegistry] Skill 热加载完成: {fname}")
                                    except Exception as e:
                                        print(f"[SkillsRegistry] 热加载失败: {fname} - {e}")
                except Exception as e:
                    print(f"[SkillsRegistry] 目录监听错误: {e}")
                time.sleep(interval)

        t = threading.Thread(target=_watch, daemon=True)
        t.start()
        print(f"[SkillsRegistry] 开始监听 Skill 目录: {directory}")

    def export_manifest(self) -> Dict:
        """导出 Skill 清单（供前端面板展示）"""
        manifest = {
            "total": self.count(),
            "categories": {},
            "skills": [],
        }
        with self._lock:
            for skill in self._skills.values():
                cat = skill.category
                manifest["categories"].setdefault(cat, 0)
                manifest["categories"][cat] += 1
                manifest["skills"].append({
                    "name": skill.name,
                    "description": skill.description,
                    "category": skill.category,
                    "requires_confirm": skill.requires_confirm,
                    "timeout": skill.timeout,
                })
        return manifest

    def get_summary(self) -> str:
        """获取技能系统摘要"""
        manifest = self.export_manifest()
        lines = [f"Skills: {manifest['total']} 个"]
        for cat, count in manifest["categories"].items():
            lines.append(f"  {cat}: {count}")
        return "\n".join(lines)


# ==================== 全局技能实例 ====================

_global_registry: Optional[SkillsRegistry] = None
_registry_lock = threading.Lock()


def get_skills_registry() -> SkillsRegistry:
    """获取全局技能注册表单例"""
    global _global_registry
    if _global_registry is None:
        with _registry_lock:
            if _global_registry is None:
                _global_registry = SkillsRegistry()
                _register_builtin_skills(_global_registry)
                # ★ 370-1: 接通 core/skills/ 模块技能注册（同名覆盖→模块真身优先）
                try:
                    from .skills import register_skills as _rs_fn
                    _n = _rs_fn(_global_registry)
                    print(f"[skills_registry] core.skills 模块注册完成: {_n} 项")
                except ImportError:
                    try:
                        from core.skills import register_skills as _rs_fn
                        _n = _rs_fn(_global_registry)
                        print(f"[skills_registry] core.skills 模块注册完成: {_n} 项")
                    except Exception as _e:
                        print(f"[skills_registry] 模块技能注册失败（回退business副本）: {_e}")
                except Exception as _e:
                    print(f"[skills_registry] 模块技能注册失败（回退business副本）: {_e}")
                # ★ 386B-4: schema 质量分层 —— 参数示例注入 + SKIP 标注（延迟导入防环）
                try:
                    from shared.skill_schema_overrides import apply_overrides
                    _n2 = apply_overrides(_global_registry)
                    print(f"[skills_registry] 386B-4 schema 分层: "
                          f"example+{_n2.get('examples', 0)} / skip+{_n2.get('skips', 0)}")
                except Exception as _e2:
                    print(f"[skills_registry] 386B-4 schema 分层失败(忽略): {_e2}")
    return _global_registry


# ==================== 内置技能实现 ====================

def _register_builtin_skills(registry: SkillsRegistry):
    """注册所有内置技能"""

    # ---- 1. 代码执行 ----
    def _handle_code_execute(code: str = "", language: str = "python",
                                  sandbox: bool = False) -> SkillResult:
        """执行代码并返回结果
        
        ★ T365.12: sandbox=True 时使用 DockerSandbox 容器化执行
        """
        if not code.strip():
            return SkillResult(success=False, error="代码为空")

        # ★ T365.12: Docker沙箱执行路径
        if sandbox:
            try:
                from core.docker_sandbox import DockerSandbox
                ds = DockerSandbox()
                if not ds.is_available():
                    return SkillResult(success=False, error="sandbox模式需要Docker，但Docker未安装或未启动")
                result = ds.execute(code, language=language)
                if result.get("success"):
                    return SkillResult(success=True, output=result.get("output", "(无输出)"),
                                       error=result.get("error", ""))
                return SkillResult(success=False, error=result.get("error", "执行失败"),
                                   output=result.get("output", ""))
            except Exception as e:
                return SkillResult(success=False, error=f"沙箱执行失败: {e}")

        ext_map = {
            "python": ".py", "py": ".py",
            "javascript": ".js", "js": ".js",
            "typescript": ".ts", "ts": ".ts",
            "bash": ".sh", "sh": ".sh",
            "powershell": ".ps1", "ps1": ".ps1",
            "c": ".c", "cpp": ".cpp", "c++": ".cpp",
            "java": ".java", "go": ".go",
            "ruby": ".rb", "rb": ".rb",
            "php": ".php", "perl": ".pl",
            "lua": ".lua", "r": ".R",
        }

        cmd_map = {
            "python": ["python", "{file}"],
            "py": ["python", "{file}"],
            "javascript": ["node", "{file}"],
            "js": ["node", "{file}"],
            "typescript": ["npx", "ts-node", "{file}"],
            "ts": ["npx", "ts-node", "{file}"],
            "bash": ["bash", "{file}"],
            "sh": ["bash", "{file}"],
            "powershell": ["powershell", "-File", "{file}"],
            "ps1": ["powershell", "-File", "{file}"],
            "c": ["gcc", "{file}", "-o", "{file}.out", "&&", "{file}.out"],
            "cpp": ["g++", "{file}", "-o", "{file}.out", "&&", "{file}.out"],
            "c++": ["g++", "{file}", "-o", "{file}.out", "&&", "{file}.out"],
            "java": ["java", "{file}"],
            "go": ["go", "run", "{file}"],
            "ruby": ["ruby", "{file}"],
            "rb": ["ruby", "{file}"],
            "php": ["php", "{file}"],
            "perl": ["perl", "{file}"],
            "lua": ["lua", "{file}"],
            "r": ["Rscript", "{file}"],
        }

        ext = ext_map.get(language.lower(), ".py")
        cmd_template = cmd_map.get(language.lower(), ["python", "{file}"])

        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=ext, delete=False, encoding="utf-8"
            ) as f:
                f.write(code)
                temp_path = f.name

            # 构建命令
            cmd = [c.replace("{file}", temp_path) for c in cmd_template]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                cwd=os.path.dirname(temp_path),
            )

            # 清理临时文件
            try:
                os.unlink(temp_path)
                if language in ("c", "cpp", "c++"):
                    out_file = temp_path + ".out"
                    if os.path.exists(out_file):
                        os.unlink(out_file)
            except Exception:
                pass

            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                if output:
                    output += "\n"
                output += result.stderr

            return SkillResult(
                success=result.returncode == 0,
                output=output or "(无输出)",
                error=result.stderr if result.returncode != 0 else "",
            )

        except subprocess.TimeoutExpired:
            return SkillResult(success=False, error="代码执行超时（30秒）")
        except FileNotFoundError as e:
            return SkillResult(
                success=False,
                error=f"编译器/解释器未找到: {e}。请确保已安装相应运行环境",
            )
        except Exception as e:
            return SkillResult(success=False, error=f"代码执行失败: {e}")

    registry.register(SkillDef(
        name="execute_code",
        description="执行指定语言的代码并返回运行结果。支持 Python/JavaScript/TypeScript/Bash/C/C++/Java/Go/Ruby 等",
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "要执行的代码"},
                "language": {
                    "type": "string",
                    "description": "代码语言",
                    "enum": ["python", "javascript", "typescript", "bash", "c", "cpp", "java", "go", "ruby", "php", "lua", "r"],
                },
                "sandbox": {"type": "boolean", "description": "T365.12: 是否使用Docker沙箱隔离执行", "default": False},
            },
            "required": ["code", "language"],
        },
        handler=_handle_code_execute,
        category="code",
        # ★389M-4: 注册为高危（执行层确认门原在高危清单内，注册表未标 →
        #   以注册表为真源后会失去确认门，属安全退步，故在真源侧补齐）
        requires_confirm=True,
    ))

    # ---- 2. 文件读取 ----
    _READ_FILE_HARD_CAP = 400  # ★391B-1: 单次读取硬上限（防模型传 max_lines=100000 整吞上下文）

    def _handle_read_file(file_path: str = "", max_lines: int = 200, offset: int = 1, project_root: str = None) -> SkillResult:
        """读取文件内容

        ★ v5.1: project_root 为用户在指令中显式指定的项目根目录（来自 EngineManager 注入的
        _context），相对路径优先基于 project_root 解析，从而能跨目录读取用户项目。
        ★391B-1: offset（1-based 起始行）支持分块续读 —— 大文件先读前 200 行判断相关性，
        相关段再用 offset 精读，避免整吞大文件撑爆上下文。
        """
        if not file_path:
            return SkillResult(success=False, error="文件路径为空")
        try:
            path = file_path
            if not os.path.isabs(path):
                base = project_root if project_root else os.getcwd()
                path = os.path.join(base, path)
            if not os.path.exists(path):
                return SkillResult(success=False, error=f"文件不存在: {path}")
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            total_lines = len(lines)
            # ★391B-1: 参数净化 —— offset 从 1 起；max_lines 硬上限 400
            try:
                offset = max(1, int(offset))
            except Exception:
                offset = 1
            try:
                max_lines = max(1, min(int(max_lines), _READ_FILE_HARD_CAP))
            except Exception:
                max_lines = 200
            _start = offset - 1
            _seg = lines[_start:_start + max_lines]
            _end = _start + len(_seg)
            if _end < total_lines:
                content = "".join(_seg)
                content += (f"\n... (共 {total_lines} 行，当前显示第 {offset}-{_end} 行；"
                            f"如需续读请用 offset={_end + 1}，如需读指定段用 offset+max_lines 组合)")
            elif offset > 1:
                content = "".join(_seg)
                content += f"\n... (共 {total_lines} 行，当前显示第 {offset}-{_end} 行，已到文件末尾)"
            else:
                content = "".join(_seg)
            return SkillResult(
                success=True,
                output=f"文件: {file_path} ({total_lines} 行)\n```\n{content}\n```",
                data={"path": file_path, "content": content, "lines": total_lines,
                      "offset": offset, "shown": len(_seg)},
            )
        except Exception as e:
            return SkillResult(success=False, error=f"文件读取失败: {e}")

    registry.register(SkillDef(
        name="read_file",
        description="读取文件内容（默认前200行，max_lines≤400），支持 offset 分块续读大文件",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "文件的路径"},
                "max_lines": {"type": "integer", "description": "本次读取行数，默认200，上限400"},
                "offset": {"type": "integer", "description": "起始行号（从1起），续读大文件时传上次返回的 offset 建议值"},
            },
            "required": ["file_path"],
        },
        handler=_handle_read_file,
        category="file",
    ))

    # ---- 3. 文件写入 ----
    def _handle_write_file(file_path: str = "", content: str = "", project_root: str = None) -> SkillResult:
        """写入文件

        ★ v5.1: project_root 同 _handle_read_file，使写入也落到用户指定项目根。
        """
        if not file_path:
            return SkillResult(success=False, error="文件路径为空")
        try:
            path = file_path
            if not os.path.isabs(path):
                base = project_root if project_root else os.getcwd()
                path = os.path.join(base, path)
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return SkillResult(
                success=True,
                output=f"文件 {file_path} 写入成功（{len(content)} 字符）",
            )
        except Exception as e:
            return SkillResult(success=False, error=f"文件写入失败: {e}")

    registry.register(SkillDef(
        name="write_file",
        description="写入文件内容（会覆盖已有文件），支持相对路径和绝对路径",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "文件内容"},
            },
            "required": ["file_path", "content"],
        },
        handler=_handle_write_file,
        category="file",
        requires_confirm=True,
    ))

    # ---- 4. 文件搜索 ----
    def _handle_search_files(pattern: str = "", path: str = "") -> SkillResult:
        """搜索文件"""
        if not pattern:
            return SkillResult(success=False, error="搜索模式为空")
        try:
            search_path = path or os.getcwd()
            # 使用 glob 模式搜索
            from pathlib import Path
            matches = list(Path(search_path).rglob(pattern))
            max_results = 50
            results = [str(m.relative_to(search_path)) for m in matches[:max_results]]
            return SkillResult(
                success=True,
                output=f"找到 {len(matches)} 个匹配文件:\n" + "\n".join(f"  - {r}" for r in results),
                data={"files": results, "total": len(matches)},
            )
        except Exception as e:
            return SkillResult(success=False, error=f"文件搜索失败: {e}")

    registry.register(SkillDef(
        name="search_files",
        description="使用 glob 模式搜索项目文件，如 *.py 搜索所有 Python 文件",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "搜索模式（glob 格式，如 *.py, **/*.txt）"},
                "path": {"type": "string", "description": "搜索目录（可选，默认当前项目目录）"},
            },
            "required": ["pattern"],
        },
        handler=_handle_search_files,
        category="file",
    ))

    # ---- 4.5. 列出目录 ----
    def _handle_list_directory(path: str = "") -> SkillResult:
        """列出目录内容"""
        try:
            target = path or os.getcwd()
            if not os.path.isabs(target):
                target = os.path.join(os.getcwd(), target)
            if not os.path.isdir(target):
                return SkillResult(success=False, error=f"不是目录: {target}")
            items = os.listdir(target)
            dirs = []
            files = []
            for item in sorted(items):
                full = os.path.join(target, item)
                if os.path.isdir(full):
                    dirs.append(f"{item}/")
                else:
                    size = os.path.getsize(full)
                    if size > 1024 * 1024:
                        size_str = f"{size/1024/1024:.1f}MB"
                    elif size > 1024:
                        size_str = f"{size/1024:.1f}KB"
                    else:
                        size_str = f"{size}B"
                    files.append(f"{item} ({size_str})")
            parts = [f"目录: {target}"]
            if dirs:
                parts.append("子目录:\n  " + "\n  ".join(dirs[:20]))
            if files:
                parts.append("文件:\n  " + "\n  ".join(files[:30]))
            return SkillResult(success=True, output="\n".join(parts))
        except Exception as e:
            return SkillResult(success=False, error=f"列出目录失败: {e}")

    registry.register(SkillDef(
        name="list_directory",
        description="列出目录内容，显示文件和子目录（含大小）",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目录路径（可选，默认当前目录）"},
            },
        },
        handler=_handle_list_directory,
        category="file",
    ))

    # ---- 5. 内容搜索（grep） ----
    def _handle_grep(pattern: str = "", path: str = "", file_pattern: str = "", project_root: str = None) -> SkillResult:
        """在文件中搜索文本内容

        ★ v3.66: 新增 file_pattern 参数支持文件类型过滤（如 *.py"）
        ★ v3.67: 当指定 path 未找到匹配时，自动扩大到项目根目录（提升召回率）
        ★ v5.1: project_root 为用户指定项目根（来自 EngineManager 注入），
        当 path 为空或相对路径时优先以其为基准，从而能搜索用户指定项目。
        """
        if not pattern:
            return SkillResult(success=False, error="搜索模式为空")
        try:
            import fnmatch

            def _do_search(search_path: str, max_results: int = 30) -> list:
                """在指定路径下搜索"""
                matches = []
                for root, dirs, files in os.walk(search_path):
                    # 跳过忽略目录
                    dirs[:] = [d for d in dirs if not d.startswith((".", "_", "node_modules", "venv", "__pycache__"))]
                    for f in files:
                        if len(matches) >= max_results:
                            break
                        # ★ v3.66: 文件类型过滤
                        if file_pattern and not fnmatch.fnmatch(f, file_pattern):
                            continue
                        fpath = os.path.join(root, f)
                        try:
                            with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                                for i, line in enumerate(fh, 1):
                                    if pattern in line:
                                        rel = os.path.relpath(fpath, search_path)
                                        matches.append(f"{rel}:{i}: {line.strip()[:100]}")
                                        if len(matches) >= max_results:
                                            break
                        except Exception:
                            continue
                return matches

            search_path = path or (project_root or os.getcwd())
            # ★ v5.1: 相对 path 优先基于 project_root 解析
            if path and not os.path.isabs(path) and project_root:
                _abs = os.path.join(project_root, path)
                if os.path.exists(_abs):
                    search_path = _abs
            matches = _do_search(search_path)

            # ★ v3.67: 当指定 path 未找到匹配时，自动扩大到项目根目录
            if not matches and path:
                # 找到项目根目录（含 .git 或带 main.py 的目录）
                project_root = os.getcwd()
                # 向上查找 .git 标记
                cur = os.path.abspath(search_path)
                for _ in range(5):
                    if os.path.exists(os.path.join(cur, ".git")) or os.path.exists(os.path.join(cur, "README.md")):
                        project_root = cur
                        break
                    parent = os.path.dirname(cur)
                    if parent == cur:
                        break
                    cur = parent
                if os.path.abspath(project_root) != os.path.abspath(search_path):
                    expanded_matches = _do_search(project_root)
                    if expanded_matches:
                        return SkillResult(
                            success=True,
                            output=(
                                f"搜索 '{pattern}' 在 '{path}' 未找到，已自动扩大到项目根目录找到 "
                                f"{len(expanded_matches)} 个匹配:\n"
                                + "\n".join(f"  {m}" for m in expanded_matches)
                            ),
                            data={
                                "matches": expanded_matches,
                                "count": len(expanded_matches),
                                "expanded_search": True,
                                "original_path": path,
                                "expanded_to": project_root,
                            },
                        )

            return SkillResult(
                success=True,
                output=f"搜索 '{pattern}' 找到 {len(matches)} 个匹配:\n" + "\n".join(f"  {m}" for m in matches) if matches else f"搜索 '{pattern}': 未找到匹配",
                data={"matches": matches, "count": len(matches)},
            )
        except Exception as e:
            return SkillResult(success=False, error=f"搜索失败: {e}")

    registry.register(SkillDef(
        name="grep_search",
        description="在项目文件中搜索文本内容，返回匹配的文件路径和行号",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "要搜索的文本"},
                "path": {"type": "string", "description": "搜索目录（可选）"},
                "file_pattern": {"type": "string", "description": "文件名过滤模式（如 *.py），可选"},
            },
            "required": ["pattern"],
        },
        handler=_handle_grep,
        category="file",
    ))

    # ---- 6. 项目扫描 ----
    def _handle_scan_project(path: str = "", project_root: str = None) -> SkillResult:
        """扫描项目文件结构

        ★ v5.1: project_root 为用户指定项目根；当 path 为空时优先扫描 project_root。
        """
        try:
            scan_path = path or (project_root or os.getcwd())
            if path and not os.path.isabs(path) and project_root and os.path.exists(os.path.join(project_root, path)):
                scan_path = os.path.join(project_root, path)
            ignore = {".git", "__pycache__", ".venv", "venv", "node_modules",
                       ".idea", ".vscode", "__pycache__", "*.pyc"}
            files = []
            dirs = []
            for root, dlist, flist in os.walk(scan_path):
                dlist[:] = [d for d in dlist if d not in ignore]
                for d in dlist:
                    dirs.append(os.path.relpath(os.path.join(root, d), scan_path))
                for f in flist:
                    if any(f.endswith(ext) for ext in (".pyc",)):
                        continue
                    files.append(os.path.relpath(os.path.join(root, f), scan_path))
            return SkillResult(
                success=True,
                output=f"项目扫描完成: {len(files)} 个文件, {len(dirs)} 个目录",
                data={"files": files[:100], "directories": dirs[:50], "total_files": len(files)},
            )
        except Exception as e:
            return SkillResult(success=False, error=f"项目扫描失败: {e}")

    registry.register(SkillDef(
        name="scan_project",
        description="扫描项目目录结构，返回文件和目录列表",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "项目路径（可选，默认当前目录）"},
            },
        },
        handler=_handle_scan_project,
        category="project",
    ))

    # ---- 7. 知识库查询 ----
    def _handle_query_knowledge(query: str = "") -> SkillResult:
        """查询知识库"""
        if not query:
            return SkillResult(success=False, error="查询内容为空")
        try:
            from core.knowledge_base import KnowledgeBase
            kb = KnowledgeBase()
            kb.load()
            matches = kb._match_scenes(query, limit=3)
            if matches:
                results = [{"scene": s, "phrase": p, "reply": r} for s, p, r in matches]
                return SkillResult(
                    success=True,
                    output=f"找到 {len(matches)} 条相关知识",
                    data={"results": results},
                )
            return SkillResult(success=True, output="未找到相关知识", data={"results": []})
        except Exception as e:
            return SkillResult(success=False, error=f"知识库查询失败: {e}")

    registry.register(SkillDef(
        name="query_knowledge_base",
        description="查询 Agent 知识库，获取 Agent 操作指南和技术知识",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "查询内容"},
            },
            "required": ["query"],
        },
        handler=_handle_query_knowledge,
        category="knowledge",
    ))

    # ---- 8. 网页抓取 ----
    def _handle_web_fetch(url: str = "") -> SkillResult:
        """获取网页内容

        ★ v3.66: 优先用 requests，回退到 urllib（标准库）
        """
        if not url:
            return SkillResult(success=False, error="URL 为空")
        try:
            # ★ v3.66: 优先 requests，回退 urllib
            try:
                import requests as req
                resp = req.get(url, timeout=15, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                })
                if resp.status_code == 200:
                    text = resp.text[:5000]
                    return SkillResult(
                        success=True,
                        output=f"网页获取成功: {len(resp.text)} 字符（显示前 5000）",
                        data={"content": text, "url": url, "status": resp.status_code},
                    )
                return SkillResult(success=False, error=f"HTTP {resp.status_code}")
            except ImportError:
                # 回退到 urllib（标准库）
                import urllib.request
                import urllib.error
                req_obj = urllib.request.Request(url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                })
                with urllib.request.urlopen(req_obj, timeout=15) as resp:
                    status = resp.getcode()
                    if status == 200:
                        raw = resp.read()
                        try:
                            text = raw.decode("utf-8", errors="replace")[:5000]
                        except Exception:
                            text = raw.decode("gbk", errors="replace")[:5000]
                        return SkillResult(
                            success=True,
                            output=f"网页获取成功(urllib): {len(raw)} 字节（显示前 5000）",
                            data={"content": text, "url": url, "status": status},
                        )
                    return SkillResult(success=False, error=f"HTTP {status}")
        except Exception as e:
            return SkillResult(success=False, error=f"网页获取失败: {e}")

    registry.register(SkillDef(
        name="web_fetch",
        description="获取网页内容，适合获取文档、API 文档等",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "网页 URL"},
            },
            "required": ["url"],
        },
        handler=_handle_web_fetch,
        category="web",
    ))

    # ---- 9. 命令执行（沙盒） ----
    def _handle_run_command(command: str = "", timeout: int = 30) -> SkillResult:
        """执行系统命令（沙盒模式）"""
        if not command:
            return SkillResult(success=False, error="命令为空")
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            return SkillResult(
                success=result.returncode == 0,
                output=result.stdout or "(无输出)",
                error=result.stderr if result.returncode != 0 else "",
            )
        except subprocess.TimeoutExpired:
            return SkillResult(success=False, error=f"命令执行超时（{timeout}秒）")
        except Exception as e:
            return SkillResult(success=False, error=f"命令执行失败: {e}")

    registry.register(SkillDef(
        name="run_command",
        description="在沙盒环境中执行系统命令（谨慎使用）",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的命令"},
                "timeout": {"type": "integer", "description": "超时时间（秒）", "default": 30},
            },
            "required": ["command"],
        },
        handler=_handle_run_command,
        category="system",
        requires_confirm=True,
        timeout=60,
    ))

    # ---- 11. 文件编辑（精确字符串替换） ----
    def _handle_edit_file(
        file_path: str = "",
        old_string: str = "",
        new_string: str = "",
        replace_all: bool = False,
    ) -> SkillResult:
        """编辑文件 — 精确字符串替换"""
        if not file_path:
            return SkillResult(success=False, error="文件路径为空")
        if not old_string:
            return SkillResult(success=False, error="old_string 参数为空")

        try:
            path = file_path
            if not os.path.isabs(path):
                path = os.path.join(os.getcwd(), path)
            if not os.path.exists(path):
                return SkillResult(success=False, error=f"文件不存在: {path}")

            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            if old_string not in content:
                return SkillResult(
                    success=False,
                    error=f"未找到匹配字符串: {old_string[:80]}...",
                )

            count = content.count(old_string)
            if count > 1 and not replace_all:
                return SkillResult(
                    success=False,
                    error=f"找到 {count} 处匹配，请设置 replace_all=true 或提供更精确的上下文",
                )

            new_content = content.replace(old_string, new_string) if replace_all else content.replace(old_string, new_string, 1)

            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)

            replaced = count if replace_all else 1
            return SkillResult(
                success=True,
                output=f"文件 {file_path} 编辑成功（替换 {replaced} 处）",
                data={"path": file_path, "replaced": replaced},
            )
        except Exception as e:
            return SkillResult(success=False, error=f"文件编辑失败: {e}")

    registry.register(SkillDef(
        name="edit_file",
        description="精确编辑文件：查找并替换指定字符串。支持单次替换和全部替换。",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "文件路径"},
                "old_string": {"type": "string", "description": "要替换的原始字符串"},
                "new_string": {"type": "string", "description": "替换后的新字符串"},
                "replace_all": {"type": "boolean", "description": "是否替换所有匹配项", "default": False},
            },
            "required": ["file_path", "old_string", "new_string"],
        },
        handler=_handle_edit_file,
        category="file",
        requires_confirm=True,
    ))

    # ---- 12. 文件删除 ----
    def _handle_delete_file(file_paths: str = "", file_path: str = "") -> SkillResult:
        """删除文件（支持多文件，逗号分隔）

        ★ v3.66: 同时接受 file_path（单数）和 file_paths（复数），提升兼容性
        """
        # ★ v3.66: 兼容单数形式
        actual_paths = file_paths or file_path
        if not actual_paths:
            return SkillResult(success=False, error="文件路径为空")

        paths = [p.strip() for p in actual_paths.split(',') if p.strip()]
        results = []
        deleted = 0
        failed = 0

        for fp in paths:
            path = fp
            if not os.path.isabs(path):
                path = os.path.join(os.getcwd(), path)
            try:
                if os.path.isfile(path):
                    os.unlink(path)
                    results.append(f"✓ 已删除: {fp}")
                    deleted += 1
                elif os.path.isdir(path):
                    results.append(f"✗ 是目录，跳过: {fp}")
                    failed += 1
                else:
                    results.append(f"✗ 不存在: {fp}")
                    failed += 1
            except Exception as e:
                results.append(f"✗ 删除失败 {fp}: {e}")
                failed += 1

        return SkillResult(
            success=failed == 0,
            output=f"删除完成: {deleted} 成功, {failed} 失败\n" + "\n".join(results),
            error=f"{failed} 个文件删除失败" if failed > 0 else "",
            data={"deleted": deleted, "failed": failed, "results": results},
        )

    registry.register(SkillDef(
        name="delete_file",
        description="删除文件（支持多文件，逗号分隔）。不会删除目录。",
        parameters={
            "type": "object",
            "properties": {
                "file_paths": {"type": "string", "description": "文件路径（多个用逗号分隔）"},
                "file_path": {"type": "string", "description": "单个文件路径（与 file_paths 任选其一）"},
            },
            "required": [],
        },
        handler=_handle_delete_file,
        category="file",
        requires_confirm=True,
    ))

    # ---- 13. 语义代码搜索 ----
    def _handle_search_codebase(
        information_request: str = "",
        target_directories: str = "",
        query: str = "",
    ) -> SkillResult:
        """语义代码搜索 — 基于关键词的代码搜索

        ★ v3.66: 同时接受 query 作为 information_request 的别名
        """
        # ★ v3.66: 兼容 query 参数
        information_request = information_request or query
        if not information_request:
            return SkillResult(success=False, error="information_request 参数为空")

        # 从查询中提取关键词
        keywords = re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*|[a-zA-Z]+', information_request)
        # 过滤常见词
        stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'to', 'of', 'in', 'on', 'at', 'for', 'with', 'and', 'or', 'not', 'this', 'that', 'it', 'we', 'you', 'they', 'where', 'how', 'what', 'when', 'which', 'who', 'whom'}
        keywords = [k for k in keywords if k.lower() not in stop_words and len(k) >= 2]

        if not keywords:
            return SkillResult(success=False, error="无法从查询中提取有效关键词")

        # 搜索目录
        search_dirs = [d.strip() for d in target_directories.split(',') if d.strip()] if target_directories else [os.getcwd()]
        if not search_dirs:
            search_dirs = [os.getcwd()]

        results = []
        import subprocess as _sp

        for directory in search_dirs:
            if not os.path.isdir(directory):
                continue
            try:
                # 使用 grep 搜索 Python 文件
                for kw in keywords[:3]:  # 限制搜索关键词数量
                    cmd = ['grep', '-rn', '-l', '--include=*.py', kw, directory]
                    try:
                        proc = _sp.run(cmd, capture_output=True, text=True,
                                         encoding="utf-8", errors="replace", timeout=10)
                        if proc.stdout:
                            for line in proc.stdout.strip().split('\n'):
                                if line and line not in results:
                                    results.append(line)
                    except Exception:
                        pass
            except Exception:
                pass

        # 如果没有 grep 结果，使用 glob 回退
        if not results:
            from pathlib import Path as _Path
            for directory in search_dirs:
                if not os.path.isdir(directory):
                    continue
                for kw in keywords[:3]:
                    pattern = f"**/*{kw}*.py"
                    try:
                        matches = list(_Path(directory).rglob(f"*{kw}*.py"))
                        for m in matches[:20]:
                            results.append(str(m))
                    except Exception:
                        pass

        if not results:
            return SkillResult(
                success=True,
                output=f"未找到与 '{information_request}' 相关的代码文件",
                data={"keywords": keywords, "matches": []},
            )

        return SkillResult(
            success=True,
            output=f"找到 {len(results)} 个相关文件:\n" + "\n".join(f"  - {r}" for r in results[:30]),
            data={"keywords": keywords, "matches": results[:30], "total": len(results)},
        )

    registry.register(SkillDef(
        name="search_codebase",
        description="语义代码搜索：根据自然语言描述搜索代码库中的相关文件和代码。",
        parameters={
            "type": "object",
            "properties": {
                "information_request": {"type": "string", "description": "自然语言搜索描述"},
                "target_directories": {"type": "string", "description": "目标目录（逗号分隔，默认当前目录）"},
            },
            "required": ["information_request"],
        },
        handler=_handle_search_codebase,
        category="file",
    ))

    # ---- 14. 网页搜索 ----
    def _handle_web_search(query: str = "", num: int = 5) -> SkillResult:
        """网页搜索

        ★ v3.66: 优先用 requests，回退到 urllib（标准库）
        ★ v3.66: DuckDuckGo 国内不可达时回退到 Bing
        ★ v3.67: 重写 — 优先 Bing（国内稳定），DuckDuckGo 作为备选；统一 requests/urllib 双路径
        """
        if not query:
            return SkillResult(success=False, error="搜索关键词为空")

        import re as _re
        import urllib.parse
        import urllib.request

        UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

        def _http_get(url: str, timeout: int = 15) -> tuple:
            """统一 HTTP GET，返回 (status, text)。优先 requests，回退 urllib。"""
            try:
                import requests as req
                resp = req.get(url, timeout=timeout, headers={"User-Agent": UA})
                return resp.status_code, resp.text
            except ImportError:
                req_obj = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req_obj, timeout=timeout) as resp:
                    raw = resp.read()
                    try:
                        return resp.getcode(), raw.decode("utf-8", errors="replace")
                    except Exception:
                        return resp.getcode(), raw.decode("gbk", errors="replace")

        def _parse_bing(html: str, max_results: int) -> list:
            """解析 Bing 搜索结果
            ★ v3.67: 适配 Bing 新版 HTML 结构
            ★ v3.68: 修正标题提取 — 优先 <h2><a> 真实标题，cite 仅作 URL 回退
            - 标题: <h2><a href="URL">TITLE</a></h2>（真实标题）
            - 链接: h2>a 的 href（优先），回退 <a class="tilk"> 或 cite
            - 摘要: <p class="b_lineclamp2">SNIPPET</p>
            """
            results = []
            # 按块分割 b_algo
            algo_blocks = _re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', html, _re.DOTALL)

            for block in algo_blocks:
                if len(results) >= max_results:
                    break

                # ★ v3.68: 优先从 <h2><a> 提取标题和 URL（真实标题位置）
                title = ""
                url = ""
                h2_match = _re.search(r'<h2[^>]*>(.*?)</h2>', block, _re.DOTALL)
                if h2_match:
                    h2_inner = h2_match.group(1)
                    a_match = _re.search(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', h2_inner, _re.DOTALL)
                    if a_match:
                        url = a_match.group(1)
                        title = _re.sub(r'<[^>]+>', '', a_match.group(2)).strip()

                # URL 回退: tilk 类链接 → 外部链接
                if not url:
                    tilk_match = _re.search(r'<a[^>]*class="tilk"[^>]*href="([^"]+)"', block)
                    if tilk_match:
                        url = tilk_match.group(1)
                if not url:
                    ext_links = _re.findall(r'href="(https?://(?!www\.bing\.com|r\.bing\.com|go\.microsoft\.com|www\.microsoft\.com)[^"]+)"', block)
                    if ext_links:
                        url = ext_links[0]

                if not url:
                    continue

                # 提取摘要（b_lineclamp2 或 b_caption 中的 p）
                snippet = ""
                snippet_match = _re.search(r'<p class="b_lineclamp[12]"[^>]*>(.*?)</p>', block, _re.DOTALL)
                if snippet_match:
                    snippet = _re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip()
                else:
                    # 回退：b_caption 中的 p
                    cap_match = _re.search(r'<div class="b_caption"[^>]*>.*?<p[^>]*>(.*?)</p>', block, _re.DOTALL)
                    if cap_match:
                        snippet = _re.sub(r'<[^>]+>', '', cap_match.group(1)).strip()
                snippet = _clean_html_entities(snippet)

                # 标题回退: cite（去掉 › 分隔）→ snippet 前 50 字
                if not title:
                    cite_match = _re.search(r'<cite[^>]*>(.*?)</cite>', block, _re.DOTALL)
                    if cite_match:
                        cite_text = _re.sub(r'<[^>]+>', '', cite_match.group(1)).strip()
                        # cite 是 URL 路径，最后一段作为标题回退
                        title = cite_text.split('›')[-1].strip()
                title = _clean_html_entities(title)

                if not title and snippet:
                    title = snippet[:50] + ('...' if len(snippet) > 50 else '')

                if title or snippet:
                    results.append({
                        "title": title or "(无标题)",
                        "snippet": snippet[:200],
                        "url": url,
                    })

            return results

        def _parse_duckduckgo(html: str, max_results: int) -> list:
            """解析 DuckDuckGo HTML 搜索结果"""
            results = []
            # DDG 格式: <a class="result__a" href="URL">TITLE</a> ... <a class="result__snippet">SNIPPET</a>
            pattern = r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?<a[^>]*class="result__snippet"[^>]*>(.*?)</a>'
            for match in _re.finditer(pattern, html, _re.DOTALL):
                url = match.group(1)
                title = _re.sub(r'<[^>]+>', '', match.group(2)).strip()
                snippet = _re.sub(r'<[^>]+>', '', match.group(3)).strip()
                # 清理 DDG 重定向 URL
                if url.startswith("//"):
                    url = "https:" + url
                elif url.startswith("/"):
                    url = "https://duckduckgo.com" + url
                elif url.startswith("uddg="):
                    url = urllib.parse.unquote(url[5:])
                if title:
                    results.append({"title": title, "snippet": snippet[:200], "url": url})
                if len(results) >= max_results:
                    break
            return results

        def _clean_html_entities(text: str) -> str:
            """清理常见 HTML 实体"""
            if not text:
                return ""
            entities = {
                "&ensp;": " ", "&emsp;": " ", "&nbsp;": " ",
                "&#0183;": "·", "&middot;": "·", "&amp;": "&",
                "&lt;": "<", "&gt;": ">", "&quot;": '"',
                "&#39;": "'", "&apos;": "'",
            }
            for k, v in entities.items():
                text = text.replace(k, v)
            # 清理多余空白
            text = _re.sub(r'\s+', ' ', text).strip()
            return text

        try:
            # ★ v3.67: 优先 Bing（国内稳定），失败回退 DuckDuckGo
            results = []
            search_engine = ""

            # 1. 尝试 Bing
            try:
                bing_url = f"https://www.bing.com/search?q={urllib.parse.quote(query)}"
                status, html_text = _http_get(bing_url, timeout=10)
                if status == 200:
                    results = _parse_bing(html_text, num)
                    if results:
                        search_engine = "Bing"
            except Exception as e_bing:
                # Bing 失败，继续尝试 DuckDuckGo
                pass

            # 2. Bing 无结果 → 尝试 DuckDuckGo
            if not results:
                try:
                    ddg_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
                    status, html_text = _http_get(ddg_url, timeout=10)
                    if status == 200:
                        results = _parse_duckduckgo(html_text, num)
                        if results:
                            search_engine = "DuckDuckGo"
                except Exception as e_ddg:
                    pass

            if not results:
                return SkillResult(
                    success=True,
                    output=f"搜索 '{query}': 未找到结果（Bing 和 DuckDuckGo 均无结果或不可达）",
                    data={"query": query, "results": [], "engine": "none"},
                )

            output_parts = [f"搜索 '{query}'（via {search_engine}）找到 {len(results)} 个结果:"]
            for i, r in enumerate(results, 1):
                output_parts.append(f"\n{i}. {r.get('title', '无标题')}")
                if r.get('snippet'):
                    output_parts.append(f"   {r['snippet'][:200]}")
                if r.get('url'):
                    output_parts.append(f"   {r['url']}")

            return SkillResult(
                success=True,
                output="\n".join(output_parts),
                data={"query": query, "results": results, "engine": search_engine},
            )
        except Exception as e:
            return SkillResult(success=False, error=f"网页搜索失败: {e}")

    registry.register(SkillDef(
        name="web_search",
        description="网页搜索：优先 Bing，回退 DuckDuckGo。返回标题、摘要和链接（国内可用）",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "num": {"type": "integer", "description": "返回结果数量（默认5）", "default": 5},
            },
            "required": ["query"],
        },
        handler=_handle_web_search,
        category="web",
    ))

    # ---- 15. 任务管理（todo_write） ----
    _todo_store = {}

    def _handle_todo_write(todos: str = "", merge: bool = False) -> SkillResult:
        """任务管理 — 创建/更新任务列表"""
        todos = _coerce_json_param(todos)
        if not todos:
            return SkillResult(success=False, error="todos 参数为空")

        try:
            todo_list = json.loads(todos)
        except (json.JSONDecodeError, TypeError):
            return SkillResult(success=False, error="todos 参数格式错误，需要 JSON 数组")

        if not isinstance(todo_list, list):
            return SkillResult(success=False, error="todos 必须是 JSON 数组")

        if merge:
            # 合并模式：更新已有任务
            for item in todo_list:
                tid = item.get("id", "")
                if tid and tid in _todo_store:
                    _todo_store[tid].update(item)
                elif tid:
                    _todo_store[tid] = item
        else:
            # 替换模式
            _todo_store.clear()
            for item in todo_list:
                tid = item.get("id", str(len(_todo_store)))
                _todo_store[tid] = item

        # 统计状态
        status_count = {}
        for item in _todo_store.values():
            status = item.get("status", "pending")
            status_count[status] = status_count.get(status, 0) + 1

        output_parts = [f"任务列表更新完成 ({len(_todo_store)} 项)"]
        output_parts.append(f"  已完成: {status_count.get('completed', 0)}")
        output_parts.append(f"  进行中: {status_count.get('in_progress', 0)}")
        output_parts.append(f"  待处理: {status_count.get('pending', 0)}")
        output_parts.append("")

        for item in _todo_store.values():
            status_icon = {"completed": "✓", "in_progress": "→", "pending": "○"}.get(item.get("status", ""), "?")
            output_parts.append(f"  {status_icon} [{item.get('status', 'pending')}] {item.get('content', item.get('id', ''))}")

        return SkillResult(
            success=True,
            output="\n".join(output_parts),
            data={"todos": list(_todo_store.values()), "total": len(_todo_store), "status_count": status_count},
        )

    registry.register(SkillDef(
        name="todo_write",
        description="任务管理：创建/更新任务列表，支持合并和替换模式",
        parameters={
            "type": "object",
            "properties": {
                "todos": {"type": "string", "description": "任务 JSON 数组 [{\"id\":\"1\",\"content\":\"...\",\"status\":\"pending\"}]。可直接传数组，也可传 JSON 字符串"},
                "merge": {"type": "boolean", "description": "是否合并到现有任务列表（默认替换）", "default": False},
            },
            "required": ["todos"],
        },
        handler=_handle_todo_write,
        category="system",
    ))

    # ---- 15.5 记忆更新（v3.64 新增，参考 MiMo Code MEMORY.md） ----
    def _handle_update_memory(
        action: str = "append",
        section: str = "用户偏好",
        content: str = "",
    ) -> SkillResult:
        """★ v3.64: 更新项目持久化记忆（MEMORY.md）

        Args:
            action: append=追加记录 / clear=清空章节 / reload=重新加载
            section: 章节名（用户偏好/项目约束/关键决策/教训总结）
            content: 记录内容（append 时必填）
        """
        try:
            import importlib.util, os as _os
            _lemon_root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
            mem_path = _os.path.join(_lemon_root, "core", "memory_manager.py")
            if not _os.path.exists(mem_path):
                return SkillResult(success=False, error="memory_manager 模块不存在")

            spec = importlib.util.spec_from_file_location("memory_manager", mem_path)
            mem_mod = importlib.util.module_from_spec(spec)
            import sys as _sys
            if "memory_manager" not in _sys.modules:
                _sys.modules["memory_manager"] = mem_mod
            spec.loader.exec_module(mem_mod)

            mem_mgr = mem_mod.get_memory_manager()

            if action == "append":
                if not content:
                    return SkillResult(success=False, error="append 操作需要 content 参数")
                ok = mem_mgr.append(section, content)
                if ok:
                    return SkillResult(
                        success=True,
                        output=f"已追加记忆到 [{section}]: {content[:80]}",
                        data={"section": section, "content": content},
                    )
                return SkillResult(success=False, error="追加记忆失败")
            elif action == "clear":
                ok = mem_mgr.clear_section(section)
                if ok:
                    return SkillResult(success=True, output=f"已清空章节: {section}")
                return SkillResult(success=False, error="清空章节失败")
            elif action == "reload":
                mem_mgr.load_memory(force_reload=True)
                return SkillResult(success=True, output="记忆已重新加载")
            else:
                return SkillResult(success=False, error=f"未知 action: {action}（支持 append/clear/reload）")
        except Exception as e:
            return SkillResult(success=False, error=f"更新记忆失败: {e}")

    registry.register(SkillDef(
        name="update_memory",
        description="★ v3.64 更新项目持久化记忆（MEMORY.md）：追加用户偏好、项目约束、关键决策、教训总结等，跨会话保留。",
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["append", "clear", "reload"],
                    "description": "操作类型：append=追加 / clear=清空章节 / reload=重新加载",
                    "default": "append",
                },
                "section": {
                    "type": "string",
                    "enum": ["用户偏好", "项目约束", "关键决策", "教训总结"],
                    "description": "记忆章节名",
                    "default": "用户偏好",
                },
                "content": {"type": "string", "description": "记忆内容（append 时必填）"},
            },
            "required": ["action"],
        },
        handler=_handle_update_memory,
        category="system",
    ))

    # ---- 16. 检查命令状态 ----
    _command_store = {}

    def _handle_check_command_status(
        command_id: str = "",
    ) -> SkillResult:
        """检查异步命令的执行状态"""
        if not command_id:
            # 列出所有已知命令
            if not _command_store:
                return SkillResult(success=True, output="没有正在运行的命令", data={"commands": {}})
            output_parts = ["已知命令:"]
            for cid, info in _command_store.items():
                status = info.get("status", "unknown")
                cmd = info.get("command", "")[:50]
                output_parts.append(f"  [{status}] {cid}: {cmd}")
            return SkillResult(
                success=True,
                output="\n".join(output_parts),
                data={"commands": _command_store},
            )

        info = _command_store.get(command_id)
        if info is None:
            return SkillResult(success=False, error=f"命令 '{command_id}' 未找到")

        return SkillResult(
            success=True,
            output=f"命令 '{command_id}': 状态={info.get('status', 'unknown')}",
            data=info,
        )

    registry.register(SkillDef(
        name="check_command_status",
        description="检查异步命令的执行状态，不提供 command_id 时列出所有已知命令",
        parameters={
            "type": "object",
            "properties": {
                "command_id": {"type": "string", "description": "命令 ID（可选，不提供则列出所有命令）"},
            },
        },
        handler=_handle_check_command_status,
        category="system",
    ))

    # ---- 17. 停止命令 ----
    def _handle_stop_command(command_id: str = "") -> SkillResult:
        """停止正在运行的命令"""
        if not command_id:
            return SkillResult(success=False, error="请提供 command_id 参数")

        info = _command_store.get(command_id)
        if info is None:
            return SkillResult(success=False, error=f"命令 '{command_id}' 未找到")

        # 尝试终止进程
        process = info.get("_process")
        if process:
            try:
                process.terminate()
                process.wait(timeout=5)
                info["status"] = "stopped"
                info["exit_code"] = -1
            except Exception:
                try:
                    process.kill()
                    info["status"] = "killed"
                    info["exit_code"] = -9
                except Exception as e:
                    return SkillResult(success=False, error=f"无法停止命令: {e}")
        else:
            info["status"] = "stopped"

        return SkillResult(
            success=True,
            output=f"命令 '{command_id}' 已停止",
            data=info,
        )

    registry.register(SkillDef(
        name="stop_command",
        description="停止正在运行的异步命令",
        parameters={
            "type": "object",
            "properties": {
                "command_id": {"type": "string", "description": "要停止的命令 ID"},
            },
            "required": ["command_id"],
        },
        handler=_handle_stop_command,
        category="system",
        requires_confirm=True,
    ))

    # ---- 18. MultiEdit — 多文件原子编辑（v0.8.0 新增） ----
    def _handle_multi_edit(
        edits: str = "",
        atomic: bool = True,
    ) -> SkillResult:
        """多文件原子编辑 — 一次修改多个文件

        Args:
            edits: JSON 数组字符串，每项格式：
                {
                    "file_path": "...",
                    "old_string": "...",
                    "new_string": "...",
                    "replace_all": false  // 可选
                }
            atomic: 是否原子性（全部成功或全部回滚），默认 True
        """
        edits = _coerce_json_param(edits)
        if not edits:
            return SkillResult(success=False, error="edits 参数为空")

        try:
            import json as _json
            edit_list = _json.loads(edits)
        except (_json.JSONDecodeError, TypeError) as e:
            return SkillResult(success=False, error=f"edits 参数 JSON 解析失败: {e}")

        if not isinstance(edit_list, list) or not edit_list:
            return SkillResult(success=False, error="edits 必须是非空 JSON 数组")

        # 预校验：所有文件必须存在 + old_string 必须匹配
        # 同时备份原始内容（用于回滚）
        backups: List[tuple] = []  # [(path, original_content)]
        validation_errors: List[str] = []

        for i, edit in enumerate(edit_list):
            if not isinstance(edit, dict):
                validation_errors.append(f"[{i}] 编辑项必须是 JSON 对象")
                continue
            file_path = edit.get("file_path", "")
            old_string = edit.get("old_string", "")
            new_string = edit.get("new_string", "")
            replace_all = bool(edit.get("replace_all", False))

            if not file_path:
                validation_errors.append(f"[{i}] 缺少 file_path")
                continue
            if not old_string:
                validation_errors.append(f"[{i}] 缺少 old_string")
                continue

            path = file_path
            if not os.path.isabs(path):
                path = os.path.join(os.getcwd(), path)
            if not os.path.exists(path):
                validation_errors.append(f"[{i}] 文件不存在: {file_path}")
                continue

            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except Exception as e:
                validation_errors.append(f"[{i}] 读取失败 {file_path}: {e}")
                continue

            if old_string not in content:
                validation_errors.append(f"[{i}] 未找到匹配字符串 in {file_path}: {old_string[:60]}...")
                continue

            count = content.count(old_string)
            if count > 1 and not replace_all:
                validation_errors.append(
                    f"[{i}] {file_path} 中找到 {count} 处匹配，请设置 replace_all=true 或提供更精确上下文"
                )
                continue

            # 记录备份（只记录首次出现的文件）
            already = any(bp == path for bp, _ in backups)
            if not already:
                backups.append((path, content))

        if validation_errors:
            return SkillResult(
                success=False,
                error=f"预校验失败（{len(validation_errors)} 项）:\n" + "\n".join(validation_errors),
                data={"errors": validation_errors, "total": len(edit_list)},
            )

        # 执行修改
        applied: List[Dict] = []
        try:
            for i, edit in enumerate(edit_list):
                file_path = edit["file_path"]
                old_string = edit["old_string"]
                new_string = edit.get("new_string", "")
                replace_all = bool(edit.get("replace_all", False))

                path = file_path
                if not os.path.isabs(path):
                    path = os.path.join(os.getcwd(), path)

                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()

                replaced = content.count(old_string) if replace_all else 1
                new_content = (
                    content.replace(old_string, new_string) if replace_all
                    else content.replace(old_string, new_string, 1)
                )

                with open(path, "w", encoding="utf-8") as f:
                    f.write(new_content)

                applied.append({
                    "index": i,
                    "file_path": file_path,
                    "replaced": replaced,
                })
        except Exception as e:
            # 原子性：回滚所有已修改的文件
            if atomic:
                rollback_count = 0
                for path, original in backups:
                    try:
                        with open(path, "w", encoding="utf-8") as f:
                            f.write(original)
                        rollback_count += 1
                    except Exception:
                        pass
                return SkillResult(
                    success=False,
                    error=f"修改过程中出错: {e}（已回滚 {rollback_count}/{len(backups)} 个文件）",
                    data={"applied_before_failure": len(applied), "rolled_back": rollback_count},
                )
            # 非原子性：返回部分成功
            return SkillResult(
                success=False,
                error=f"修改过程中出错: {e}（已成功 {len(applied)} 项）",
                data={"applied": applied, "failed_at": i},
            )

        return SkillResult(
            success=True,
            output=(
                f"✅ 多文件编辑成功：共 {len(applied)} 项修改，涉及 "
                f"{len(set(a['file_path'] for a in applied))} 个文件\n"
                + "\n".join(
                    f"  [{a['index']}] {a['file_path']} (替换 {a['replaced']} 处)"
                    for a in applied
                )
            ),
            data={
                "applied": applied,
                "total": len(applied),
                "files_affected": list(set(a["file_path"] for a in applied)),
                "atomic": atomic,
            },
        )

    registry.register(SkillDef(
        name="multi_edit",
        description=(
            "多文件原子编辑：一次修改多个文件，每个编辑项包含 file_path/old_string/new_string/replace_all。"
            "atomic=true（默认）时，预校验失败或修改过程出错会自动回滚所有已修改文件，保证全部成功或全部不变。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "edits": {
                    "type": "string",
                    "description": (
                        "编辑项 JSON 数组字符串，每项格式："
                        '{"file_path":"...","old_string":"...","new_string":"...","replace_all":false}。'
                        "可直接传数组，也可传 JSON 字符串"
                    ),
                },
                "atomic": {
                    "type": "boolean",
                    "description": "是否原子性（全部成功或全部回滚），默认 true",
                    "default": True,
                },
            },
            "required": ["edits"],
        },
        handler=_handle_multi_edit,
        category="file",
        requires_confirm=True,
        timeout=60,
    ))

    # ---- 19. 注册 v0.8.0 新增 Skills（浏览器自动化 + Jupyter Notebook） ----
    _register_v080_skills(registry)

    # ---- 19.2 注册 v0.9.0 新增 Skills（Git + 包管理） ----
    _register_v090_skills(registry)

    # ---- 19.3 注册 v1.0.0 MIEMIE分身 Skills（miemie_clone_analyze） ----
    _register_v100_skills(registry)

    # ---- 19.5 task_manager — 任务依赖管理（v0.9.0 新增，扩展自 todo_write） ----
    def _handle_task_manager(
        action: str = "list",
        tasks: str = "",
        task_id: str = "",
        content: str = "",
        status: str = "",
        priority: str = "medium",
        depends_on: str = "",
        merge: bool = False,
        session_id: str = "",
    ) -> SkillResult:
        """任务依赖管理 — 扩展自 todo_write

        Args:
            action: 操作类型 list/add/update/remove/transition/graph/topo/clear/import
            tasks: JSON 数组字符串（import/list 时使用）
            task_id: 任务 ID
            content: 任务内容
            status: 任务状态（pending/in_progress/completed/failed/blocked/cancelled）
            priority: 优先级（high/medium/low）
            depends_on: 依赖任务 ID 列表，逗号分隔（如 "A,B,C"）
            merge: import 时是否合并而非替换
            session_id: 会话 ID（由引擎从运行上下文隐式注入，不进模型参数 schema；
                ★第361章 据此实现每会话独立任务列表）
        """
        from core.task_manager import (
            TaskManager, Task, TaskStatus, get_task_manager,
        )

        tm = get_task_manager(session_id or "default")

        if action == "list":
            task_list = tm.export_to_list()
            return SkillResult(
                success=True,
                output=f"共 {len(task_list)} 个任务",
                data={"tasks": task_list, "total": len(task_list)},
            )

        if action == "import":
            tasks = _coerce_json_param(tasks)
            if not tasks:
                return SkillResult(success=False, error="tasks 参数为空")
            try:
                task_list = json.loads(tasks)
            except (json.JSONDecodeError, TypeError) as e:
                return SkillResult(success=False, error=f"tasks JSON 解析失败: {e}")
            count = tm.load_from_list(task_list, merge=merge)
            return SkillResult(
                success=True,
                output=f"✅ 已{'合并' if merge else '导入'} {count} 个任务",
                data={"count": count, "total": len(tm.list_tasks())},
            )

        if action == "add":
            if not task_id:
                task_id = str(len(tm.list_tasks()) + 1)
            dep_list = [d.strip() for d in depends_on.split(",") if d.strip()] if depends_on else []
            task = Task(
                id=task_id,
                content=content,
                priority=priority,
                depends_on=dep_list,
            )
            ok = tm.add_task(task)
            if not ok:
                return SkillResult(success=False, error=f"任务已存在: {task_id}")
            return SkillResult(
                success=True,
                output=f"✅ 已添加任务 {task_id}（依赖: {depends_on or '无'}）",
                data=task.to_dict(),
            )

        if action == "update":
            task = tm.get_task(task_id)
            if not task:
                return SkillResult(success=False, error=f"任务不存在: {task_id}")
            if content:
                task.content = content
            if priority:
                task.priority = priority
            if depends_on:
                task.depends_on = [d.strip() for d in depends_on.split(",") if d.strip()]
            return SkillResult(
                success=True,
                output=f"✅ 已更新任务 {task_id}",
                data=task.to_dict(),
            )

        if action == "remove":
            ok = tm.remove_task(task_id)
            return SkillResult(
                success=ok,
                output=f"✅ 已删除任务 {task_id}" if ok else f"任务不存在: {task_id}",
            )

        if action == "transition":
            # 状态映射：todo_write 的 in_progress → running
            status_map = {
                "pending": TaskStatus.PENDING,
                "in_progress": TaskStatus.RUNNING,
                "completed": TaskStatus.COMPLETED,
                "failed": TaskStatus.FAILED,
                "blocked": TaskStatus.BLOCKED,
                "cancelled": TaskStatus.CANCELLED,
            }
            target_status = status_map.get(status)
            if not target_status:
                return SkillResult(
                    success=False,
                    error=f"未知状态: {status}（支持: pending/in_progress/completed/failed/blocked/cancelled）",
                )
            ok, msg = tm.transition(task_id, target_status)
            task = tm.get_task(task_id)
            return SkillResult(
                success=ok,
                output=f"✅ {msg}" if ok else f"❌ {msg}",
                data=task.to_dict() if task else None,
            )

        if action == "can_run":
            ok, reason = tm.can_run(task_id)
            return SkillResult(
                success=True,
                output=f"任务 {task_id} {'可执行' if ok else '被阻塞'}: {reason}",
                data={"can_run": ok, "reason": reason},
            )

        if action == "graph":
            ascii_graph = tm.render_ascii_graph()
            html_graph = tm.render_html_graph()
            return SkillResult(
                success=True,
                output=f"任务依赖图:\n{ascii_graph}",
                data={
                    "ascii": ascii_graph,
                    "html": html_graph,
                    "inline_html": html_graph,
                },
            )

        if action == "topo":
            sorted_ids, cyclic = tm.topological_sort()
            return SkillResult(
                success=True,
                output=f"拓扑排序: {' → '.join(sorted_ids)}" + (
                    f"\n⚠ 循环依赖: {', '.join(cyclic)}" if cyclic else ""
                ),
                data={
                    "order": sorted_ids,
                    "cyclic": cyclic,
                    "has_cycle": len(cyclic) > 0,
                },
            )

        if action == "summary":
            summary = tm.get_summary()
            return SkillResult(
                success=True,
                output=f"任务统计: {summary['total']} 个任务\n"
                       + "\n".join(f"  {k}: {v}" for k, v in summary["status"].items()),
                data=summary,
            )

        if action == "clear":
            tm.clear()
            return SkillResult(success=True, output="✅ 已清空所有任务")

        return SkillResult(
            success=False,
            error=f"未知 action: {action}（支持: list/import/add/update/remove/transition/can_run/graph/topo/summary/clear）",
        )

    registry.register(SkillDef(
        name="task_manager",
        description=(
            "任务依赖管理：支持任务依赖（A depends on B）、状态机（pending→running→completed/failed/blocked）、"
            "依赖未完成时阻塞、拓扑排序、依赖关系图。扩展自 todo_write，完全兼容。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "操作类型",
                    "enum": [
                        "list", "import", "add", "update", "remove",
                        "transition", "can_run", "graph", "topo", "summary", "clear",
                    ],
                },
                "tasks": {
                    "type": "string",
                    "description": "import 时的任务 JSON 数组：[{\"id\":\"A\",\"content\":\"...\",\"depends_on\":[\"B\"]}]。可直接传数组，也可传 JSON 字符串",
                },
                "task_id": {"type": "string", "description": "任务 ID"},
                "content": {"type": "string", "description": "任务内容"},
                "status": {
                    "type": "string",
                    "description": "任务状态（transition 操作使用）",
                    "enum": ["pending", "in_progress", "completed", "failed", "blocked", "cancelled"],
                },
                "priority": {
                    "type": "string",
                    "description": "优先级",
                    "enum": ["high", "medium", "low"],
                    "default": "medium",
                },
                "depends_on": {
                    "type": "string",
                    "description": "依赖任务 ID 列表，逗号分隔（如 'A,B,C'）",
                },
                "merge": {
                    "type": "boolean",
                    "description": "import 时是否合并而非替换",
                    "default": False,
                },
            },
            "required": ["action"],
        },
        handler=_handle_task_manager,
        category="planning",
        requires_confirm=False,
        timeout=30,
    ))

    # ---- 20. 注册业务 Skills（蒸馏自 MiMo Code） ----
    _register_business_skills(registry)

    # ---- 21. ★ v3.71: 注册增强版办公 Skills（覆盖 business_skills 中的旧版本） ----
    _register_v371_skills(registry)

    # ---- 22. ★ v1.1.0: 批量接入 11 个未集成 Skill ----
    _register_v110_skills(registry)

    # ---- 23. T366.4→381A-2: spawn_subagent 真执行体 ----
    def _handle_spawn_subagent(goal: str = "", tools_whitelist: list = None,
                               max_rounds: int = 10) -> SkillResult:
        if not goal:
            return SkillResult(success=False, error="goal 参数必填")
        if tools_whitelist and "spawn_subagent" in tools_whitelist:
            return SkillResult(success=False, error="tools_whitelist 禁止包含 spawn_subagent（防递归）")
        if max_rounds > 30:
            return SkillResult(success=False, error="max_rounds 上限30，防止失控")
        try:
            from shared.engine_manager import get_engine_manager
            mgr = get_engine_manager()
            tid = mgr.spawn_subagent("subagent", goal, max_iterations=min(max_rounds, 10))
            if tid:
                # ★ 381A-2: 真实后台执行体，非登记型空壳
                #   等待子代理完成（最多 120s），回传真实结果摘要
                import time as _t
                _wait_start = _t.time()
                _timeout = 120
                while _t.time() - _wait_start < _timeout:
                    _result = mgr.get_subagent_result(tid)
                    if _result and _result.get("status") != "running":
                        break
                    _t.sleep(1)
                _result = mgr.get_subagent_result(tid)
                if not _result:
                    return SkillResult(success=False, error="子代理结果查询失败")
                _status = _result.get("status", "unknown")
                if _status == "completed":
                    return SkillResult(success=True,
                                       output=(f"子代理已完成 (task_id={tid})\n"
                                               f"结果摘要: {_result.get('content', '(无输出)')[:300]}"),
                                       data={"task_id": tid, "goal": goal[:100],
                                             "tools_whitelist": tools_whitelist or [],
                                             "max_rounds": max_rounds,
                                             "execution": "real",
                                             "iterations": _result.get("iterations", 0),
                                             "status": "completed"})
                elif _status == "timeout":
                    return SkillResult(success=False,
                                       output=f"子代理已超时 (task_id={tid}, 超过{_timeout}s)",
                                       data={"task_id": tid, "status": "timeout"})
                elif _status == "failed":
                    return SkillResult(success=False,
                                       output=f"子代理执行失败 (task_id={tid}): {_result.get('error', '')[:200]}",
                                       data={"task_id": tid, "status": "failed",
                                             "error": _result.get("error", "")[:200]})
                else:
                    return SkillResult(success=True,
                                       output=f"子代理运行中 (task_id={tid}), 超时前未完成",
                                       data={"task_id": tid, "status": "running"})
            return SkillResult(success=False, error="子代理启动失败：并发已满（上限2），请稍后重试")
        except Exception as e:
            return SkillResult(success=False, error=f"子代理启动异常: {e}")

    registry.register(SkillDef(
        name="spawn_subagent",
        description="将子任务委派给独立上下文的子代理。适用于需要隔离执行的复杂子任务，如批量扫描、独立验证等。",
        parameters={
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "子代理的任务目标（必填）"},
                "tools_whitelist": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "允许子代理使用的工具白名单（禁止包含spawn_subagent自身）",
                },
                "max_rounds": {"type": "integer", "description": "子代理最大执行轮数（上限30）", "default": 10},
            },
            "required": ["goal", "tools_whitelist"],
        },
        handler=_handle_spawn_subagent,
        category="orchestration",
        requires_confirm=True,
        timeout=300,
    ))


def _register_v080_skills(registry: SkillsRegistry):
    """注册 v0.8.0 新增 Skills：浏览器自动化 + Jupyter Notebook"""
    try:
        from skills import browser_automation, jupyter_notebook
        browser_automation.register(registry)
        jupyter_notebook.register(registry)
        print(f"[skills_registry] 已注册 v0.8.0 新增 2 个 Skill（browser_automation + jupyter_notebook）")
    except Exception as e:
        print(f"[skills_registry] v0.8.0 Skill 注册失败: {e}")


def _register_v090_skills(registry: SkillsRegistry):
    """注册 v0.9.0 新增 Skills：Git + 包管理"""
    try:
        from skills import git_skill, package_manager
        git_skill.register(registry)
        package_manager.register(registry)
        print(f"[skills_registry] 已注册 v0.9.0 新增 2 个 Skill（git_skill + package_manager）")
    except Exception as e:
        print(f"[skills_registry] v0.9.0 Skill 注册失败: {e}")


def _register_v100_skills(registry: SkillsRegistry):
    """注册 v1.0.0 MIEMIE分身 Skills：miemie_clone_analyze"""
    try:
        # 动态导入 miemie 模块（兼容不同 sys.path）
        import sys as _sys
        import os as _os
        _mimi_dir = _os.path.normpath(_os.path.join(
            _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
            "miemie"
        ))
        if _mimi_dir not in _sys.path:
            _sys.path.insert(0, _mimi_dir)
        from code_clone import CodeCloneAnalyzer

        analyzer = CodeCloneAnalyzer()

        def _handle_miemie_clone_analyze(
            target: str = "",
            recursive: bool = False,
            max_files: int = 100,
            output_format: str = "json",
        ) -> SkillResult:
            """MIEMIE代码分身分析 — 分析代码风格，生成开发者画像

            Args:
                target: 目标文件或目录路径
                recursive: 目录递归分析（仅目录有效）
                max_files: 目录分析时最多扫描的文件数
                output_format: 输出格式 json / summary
            """
            if not target:
                return SkillResult(success=False, error="target 参数为空")
            if not os.path.exists(target):
                return SkillResult(success=False, error=f"路径不存在: {target}")
            try:
                if os.path.isdir(target):
                    pattern = "*.py"  # 默认 Python
                    profile = analyzer.analyze_directory(
                        target, pattern=pattern, max_files=max_files
                    )
                else:
                    profile = analyzer.analyze_file(target)
                if output_format == "summary":
                    return SkillResult(
                        success=True,
                        output=profile.summary,
                        data=profile.to_dict(),
                    )
                # 默认 json
                return SkillResult(
                    success=True,
                    output=profile.to_json(),
                    data=profile.to_dict(),
                )
            except Exception as e:
                import traceback as _tb
                return SkillResult(
                    success=False,
                    error=f"代码分身分析失败: {e}",
                    output=_tb.format_exc(),
                )

        registry.register(SkillDef(
            name="miemie_clone_analyze",
            description=(
                "MIEMIE代码分身分析：分析指定文件或目录的代码风格，生成开发者画像。"
                "包括命名风格、缩进偏好、注释密度、函数长度、设计模式、错误处理。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "目标文件或目录的绝对路径",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "目录递归分析（仅目录有效，默认 false）",
                        "default": False,
                    },
                    "max_files": {
                        "type": "integer",
                        "description": "目录分析时最多扫描的文件数（默认 100）",
                        "default": 100,
                    },
                    "output_format": {
                        "type": "string",
                        "enum": ["json", "summary"],
                        "description": "输出格式：json（完整画像）/ summary（摘要）",
                        "default": "json",
                    },
                },
                "required": ["target"],
            },
            handler=_handle_miemie_clone_analyze,
            category="miemie",
            requires_confirm=False,
            timeout=60,
        ))
        print(f"[skills_registry] 已注册 v1.0.0 MIEMIE分身 Skill（miemie_clone_analyze）")
    except Exception as e:
        print(f"[skills_registry] v1.0.0 MIEMIE分身 Skill 注册失败: {e}")


def _register_business_skills(registry: SkillsRegistry):
    """注册业务 Skills（蒸馏自 MiMo Code，TypeScript → Python 翻译）"""
    try:
        # 动态导入 business_skills 模块（避免循环引用）
        import importlib
        import importlib.util  # ★ S8: 显式导入子模块，否则 importlib.util 不可用导致业务 Skill 注册失败
        import os as _os
        _path = _os.path.dirname(_os.path.abspath(__file__))
        if _path not in __import__('sys').path:
            __import__('sys').path.insert(0, _path)
        # 当前目录即为 core 包，直接导入 business_skills
        spec = importlib.util.find_spec('business_skills')
        if spec is None:
            print("[skills_registry] business_skills 模块未找到，跳过业务技能注册")
            return
        business_skills = importlib.import_module('business_skills')
        count = business_skills.register_business_skills(registry)
        print(f"[skills_registry] 已注册 {count} 个业务技能")
    except Exception as e:
        print(f"[skills_registry] 业务技能注册失败: {e}")


def _register_v371_skills(registry: SkillsRegistry):
    """★ v3.71: 注册增强版办公 Skills

    覆盖 business_skills 中的旧版本：
    - office_generator: PPT 多布局+配色+图表 / Excel 样式+斑马纹+冻结
    - academic_writer: IEEE/GB-T7714 引用格式 + BibTeX + 双栏
    - pdf_reader: 新增 PDF 读取与解析
    """
    import importlib
    import sys as _sys
    try:
        skills_dir = os.path.join(os.path.dirname(__file__), 'skills')
        if skills_dir not in _sys.path:
            _sys.path.insert(0, skills_dir)

        count = 0
        for mod_name in ['office_generator', 'academic_writer', 'pdf_reader']:
            try:
                mod = importlib.import_module(mod_name)
                if hasattr(mod, 'register'):
                    mod.register(registry)
                    count += 1
            except Exception as e:
                print(f"[skills_registry] v3.71 注册 {mod_name} 失败: {e}")
        print(f"[skills_registry] v3.71 已注册/覆盖 {count} 个增强办公 Skill")
    except Exception as e:
        print(f"[skills_registry] v3.71 Skill 注册失败: {e}")


def _register_v110_skills(registry: SkillsRegistry):
    """★ v1.1.0: 批量接入 11 个未集成 Skill"""
    import importlib
    import sys as _sys
    skills_dir = os.path.join(os.path.dirname(__file__), 'skills')
    if skills_dir not in _sys.path:
        _sys.path.insert(0, skills_dir)

    _v110_modules = [
        ('docker_skill', 'docker_skill', 'register'),
        ('ssh_skill', 'ssh_skill', 'register'),
        ('mcp_bridge', 'mcp_bridge', 'register'),
        ('security_auditor', 'security_auditor', 'register'),
        ('skill_creator', 'skill_creator', 'register'),
        ('self_documenter', 'self_documenter', 'register'),
        ('terminal_run_skill', 'terminal_run_skill', 'register_terminal_run_skill'),
        ('lsp_code_analysis', 'lsp_code_analysis', 'register'),
        ('requirement_amplifier', 'requirement_amplifier', 'register'),
        ('modern_python_toolchain', 'modern_python_toolchain', 'register'),
        ('design_blueprint', 'design_blueprint', 'register'),
    ]

    count = 0
    for label, mod_name, reg_fn in _v110_modules:
        try:
            mod = importlib.import_module(mod_name)
            fn = getattr(mod, reg_fn, None)
            if fn is None:
                print(f"[skills_registry] v1.1.0 {label}: 未找到 {reg_fn}() 函数，跳过")
                continue
            fn(registry)
            count += 1
        except Exception as e:
            print(f"[skills_registry] v1.1.0 注册 {label} 失败: {e}")
    print(f"[skills_registry] v1.1.0 已注册 {count}/{len(_v110_modules)} 个 Skill")


# ==================== 工具函数 ====================

def get_tool_definitions_for_engine(engine_type: str) -> List[Dict]:
    """
    根据引擎类型返回适合的工具定义列表
    
    Ollama 和 DeepSeek 都支持 OpenAI 格式的 function calling，
    但 DeepSeek 支持更复杂的工具定义。
    """
    registry = get_skills_registry()
    tools = registry.get_tool_definitions()

    if engine_type == "ollama":
        # Ollama 对工具定义支持有限，简化参数
        for tool in tools:
            func = tool.get("function", {})
            params = func.get("parameters", {})
            props = params.get("properties", {})
            # 确保所有属性都有描述
            for key, prop in props.items():
                if isinstance(prop, dict) and "description" not in prop:
                    prop["description"] = key
    return tools


def summarize_skills() -> str:
    """生成技能摘要文本（供系统提示词使用）"""
    registry = get_skills_registry()
    skills = registry.list_skills()
    lines = ["可用工具:", "--------"]
    for s in skills:
        lines.append(f"- {s.name}: {s.description}")
    return "\n".join(lines)


def get_confirm_required_tools() -> set:
    """389M-4: 返回注册表中 requires_confirm=True 的技能名集合。

    用途：作为「高危技能二次确认门」的唯一真源——engine_manager 启动时据此
    动态构建 _HIGH_RISK_TOOLS，避免执行层清单与注册表双源漂移（385A-3 背景：
    执行层 6 个 vs 注册表 7 处，拦截存在缝隙）。
    """
    registry = get_skills_registry()
    return {s.name for s in registry.list_skills() if getattr(s, "requires_confirm", False)}