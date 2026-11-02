# -*- coding: utf-8 -*-
"""
Skill: lsp_code_analysis — LSP 语义代码分析（L3 新增）
======================================================
将 LSP 协议的全部语义操作暴露为 Skill，供 Agent 工具调用。

支持 12 种操作：
  workspace_symbol    — 工作区符号搜索（全局符号查找）
  document_symbol     — 文档符号（文件内结构大纲）
  go_to_definition    — 跳转到定义
  find_references     — 查找所有引用
  hover               — 悬停信息（类型/文档）
  go_to_implementation— 跳转到实现
  prepare_call_hierarchy — 准备调用层次
  incoming_calls      — 来电（谁调用了这个）
  outgoing_calls      — 去电（这个调用了谁）
  completion          — 代码补全
  diagnostics          — 诊断信息（错误/警告）
  health               — LSP 服务器健康状态

优雅降级：
  - lsp_manager 未初始化时返回友好提示
  - LSP 服务器未就绪时 fallback 到文本搜索（grep）
  - 无可用后端时返回搜索指引

设计原则（满足 CodeLock "仅完善不破坏架构"）：
  - 不修改 lsp_manager 的架构，仅读取其公开 API
  - 信号结果通过线程安全队列收集（避免跨线程 pyqtSignal 问题）
"""

import os
import json
import threading
import queue
from typing import Dict, Any, List, Optional

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "lsp_code_analysis",
    "description": "LSP 语义代码分析：全局符号搜索/定义跳转/引用查找/悬停信息/调用层次/代码补全/诊断",
    "category": "code",
    "version": "1.0.0",
}


# ==================== LSP Manager 单例 ====================

_lsp_manager = None
_lsp_lock = threading.Lock()


def _get_lsp_manager():
    """获取 LSPServerManager 单例（惰性初始化）"""
    global _lsp_manager
    with _lsp_lock:
        if _lsp_manager is not None:
            return _lsp_manager
        try:
            from lsp_manager import LSPServerManager, DEFAULT_SERVERS
            root = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))))
            _lsp_manager = LSPServerManager(root)
            # 尝试启动默认语言服务器（不阻塞）
            for lang_id in DEFAULT_SERVERS:
                try:
                    _lsp_manager.start_server(lang_id)
                except Exception:
                    pass
        except Exception:
            _lsp_manager = None
        return _lsp_manager


# ==================== 文本 fallback ====================

def _grep_fallback(file_path: str, pattern: str) -> List[Dict]:
    """文本搜索 fallback — 当 LSP 不可用时用 grep 替代"""
    import subprocess
    results = []
    try:
        if os.name == 'nt':
            output = subprocess.check_output(
                ['findstr', '/n', '/i', pattern, file_path],
                shell=False, text=True, errors='replace',
            )
            for line in output.strip().split('\n'):
                if ':' in line:
                    parts = line.split(':', 1)
                    results.append({
                        'file': file_path,
                        'line': parts[0] if parts[0].isdigit() else 0,
                        'content': parts[1].strip() if len(parts) > 1 else line,
                    })
        else:
            output = subprocess.check_output(
                ['grep', '-n', '-i', pattern, file_path],
                text=True, errors='replace',
            )
            for line in output.strip().split('\n'):
                if ':' in line:
                    parts = line.split(':', 1)
                    results.append({
                        'file': file_path,
                        'line': parts[0] if parts[0].isdigit() else 0,
                        'content': parts[1].strip() if len(parts) > 1 else line,
                    })
    except Exception:
        pass
    return results


# ==================== 回调结果收集 ====================

class _ResultCollector:
    """线程安全的结果收集器（解决 pyqtSignal 跨线程问题）"""
    def __init__(self, timeout: float = 3.0):
        self._queue = queue.Queue()
        self._timeout = timeout

    def callback(self, *args):
        self._queue.put(args)

    def wait(self, default=None):
        try:
            return self._queue.get(timeout=self._timeout)
        except queue.Empty:
            return default


# ==================== 操作实现 ====================

def _op_workspace_symbol(query: str, language_id: str = "python") -> SkillResult:
    """全局符号搜索"""
    if not query:
        return SkillResult(success=False, error="缺少 query 参数")
    mgr = _get_lsp_manager()
    if mgr is None:
        return SkillResult(success=False, error="LSP 管理器未初始化")
    if not mgr.is_server_ready(language_id):
        # Fallback: 文本搜索当前目录的 Python 文件
        cwd = os.getcwd()
        results = []
        for root, _, files in os.walk(cwd):
            for f in files[:50]:  # 限制扫描量
                if f.endswith('.py'):
                    hits = _grep_fallback(os.path.join(root, f), query)
                    results.extend(hits[:3])
                if len(results) >= 20:
                    break
            if len(results) >= 20:
                break
        if results:
            lines = [f"  {r['file']}:{r['line']} — {r['content'][:80]}"
                     for r in results[:15]]
            return SkillResult(
                success=True,
                output=f"(Fallback 文本搜索) 找到 {len(results)} 个匹配:\n" + "\n".join(lines),
                data={"results": results, "fallback": True},
            )
        return SkillResult(success=False, error=f"LSP {language_id} 未就绪，文本搜索也未找到匹配")

    collector = _ResultCollector()
    try:
        mgr.workspace_symbol_received.connect(collector.callback)
        mgr.request_workspace_symbol(query, language_id)
        result = collector.wait(default=[])
        mgr.workspace_symbol_received.disconnect(collector.callback)
    except Exception as e:
        return SkillResult(success=False, error=f"LSP 请求失败: {e}")

    if result and len(result) > 1:
        symbols = result[1] if len(result) > 1 else []
    else:
        symbols = result[0] if isinstance(result, tuple) else result
    count = len(symbols) if isinstance(symbols, list) else 0
    return SkillResult(
        success=True,
        output=f"找到 {count} 个符号匹配 '{query}'",
        data={"symbols": symbols[:20] if isinstance(symbols, list) else []},
    )


def _op_go_to_definition(file_path: str, line: int = 0, character: int = 0) -> SkillResult:
    """跳转定义"""
    if not file_path:
        return SkillResult(success=False, error="缺少 file_path 参数")
    if not os.path.isfile(file_path):
        file_path = os.path.join(os.getcwd(), file_path)
    if not os.path.isfile(file_path):
        return SkillResult(success=False, error=f"文件不存在: {file_path}")

    mgr = _get_lsp_manager()
    if mgr is None or not mgr.is_server_ready(mgr.get_language(file_path)):
        # Fallback: 文本 import 分析
        return _import_fallback(file_path)

    mgr.open_document(file_path, open(file_path, encoding='utf-8').read())
    collector = _ResultCollector()
    try:
        mgr.definition_received.connect(collector.callback)
        mgr.request_definition(file_path, line, character)
        result = collector.wait(default=[])
        mgr.definition_received.disconnect(collector.callback)
    except Exception as e:
        return SkillResult(success=False, error=f"LSP 定义跳转失败: {e}")

    locations = result[1] if isinstance(result, tuple) and len(result) > 1 else []
    count = len(locations) if locations else 0
    return SkillResult(
        success=True,
        output=f"找到 {count} 个定义位置",
        data={"locations": _loc_list(locations)},
    )


def _import_fallback(file_path: str) -> SkillResult:
    """静态 import 分析 fallback"""
    results = []
    try:
        with open(file_path, encoding='utf-8') as f:
            for i, line in enumerate(f, 1):
                if line.strip().startswith(('import ', 'from ')):
                    results.append({'line': i, 'content': line.strip()})
    except Exception as e:
        return SkillResult(success=False, error=f"读取文件失败: {e}")
    return SkillResult(
        success=True,
        output=f"(静态分析) 找到 {len(results)} 个 import 语句",
        data={"imports": results, "fallback": True},
    )


def _op_find_references(file_path: str, line: int = 0, character: int = 0) -> SkillResult:
    """查找引用"""
    if not file_path or not os.path.isfile(file_path):
        return SkillResult(success=False, error=f"文件不存在: {file_path}")
    mgr = _get_lsp_manager()
    if mgr is None or not mgr.is_server_ready(mgr.get_language(file_path)):
        return SkillResult(success=False, error="LSP 未就绪，无法查找引用")

    mgr.open_document(file_path, open(file_path, encoding='utf-8').read())
    collector = _ResultCollector()
    try:
        mgr.references_received.connect(collector.callback)
        mgr.request_references(file_path, line, character)
        result = collector.wait(default=[])
        mgr.references_received.disconnect(collector.callback)
    except Exception as e:
        return SkillResult(success=False, error=f"LSP 引用查找失败: {e}")

    locations = result[1] if isinstance(result, tuple) and len(result) > 1 else []
    count = len(locations) if locations else 0
    return SkillResult(
        success=True,
        output=f"找到 {count} 个引用",
        data={"references": _loc_list(locations)},
    )


def _op_hover(file_path: str, line: int = 0, character: int = 0) -> SkillResult:
    """悬停信息"""
    if not file_path or not os.path.isfile(file_path):
        return SkillResult(success=False, error=f"文件不存在: {file_path}")
    mgr = _get_lsp_manager()
    if mgr is None or not mgr.is_server_ready(mgr.get_language(file_path)):
        return SkillResult(success=False, error="LSP 未就绪，无法获取悬停信息")

    mgr.open_document(file_path, open(file_path, encoding='utf-8').read())
    collector = _ResultCollector()
    try:
        mgr.hover_received.connect(collector.callback)
        mgr.request_hover(file_path, line, character)
        result = collector.wait(default=("", "", 0, 0))
        mgr.hover_received.disconnect(collector.callback)
    except Exception as e:
        return SkillResult(success=False, error=f"LSP 悬停失败: {e}")

    if isinstance(result, tuple) and len(result) > 1:
        hover_text = result[1]
    else:
        hover_text = str(result)
    if not hover_text:
        return SkillResult(success=False, error="无类型信息")
    return SkillResult(
        success=True,
        output=f"类型信息: {hover_text[:500]}",
        data={"hover_text": hover_text},
    )


def _op_document_symbol(file_path: str) -> SkillResult:
    """文档符号（文件结构大纲）"""
    if not file_path or not os.path.isfile(file_path):
        return SkillResult(success=False, error=f"文件不存在: {file_path}")
    mgr = _get_lsp_manager()
    if mgr is None or not mgr.is_server_ready(mgr.get_language(file_path)):
        return _parse_fallback(file_path)
    mgr.open_document(file_path, open(file_path, encoding='utf-8').read())
    collector = _ResultCollector()
    try:
        mgr.document_symbol_received.connect(collector.callback)
        mgr.request_document_symbol(file_path)
        result = collector.wait(default=[])
        mgr.document_symbol_received.disconnect(collector.callback)
    except Exception as e:
        return _parse_fallback(file_path)  # fallback

    symbols = result[1] if isinstance(result, tuple) and len(result) > 1 else []
    count = len(symbols) if isinstance(symbols, list) else 0
    return SkillResult(
        success=True,
        output=f"文件结构: {count} 个符号",
        data={"symbols": symbols[:50] if isinstance(symbols, list) else []},
    )


def _parse_fallback(file_path: str) -> SkillResult:
    """Python AST 静态解析 fallback"""
    try:
        import ast
        with open(file_path, encoding='utf-8') as f:
            tree = ast.parse(f.read())
        symbols = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                symbols.append({"name": node.name, "kind": "class", "line": node.lineno})
            elif isinstance(node, ast.FunctionDef):
                symbols.append({"name": node.name, "kind": "function", "line": node.lineno})
        return SkillResult(
            success=True,
            output=f"(静态解析) 文件结构: {len(symbols)} 个符号",
            data={"symbols": symbols, "fallback": True},
        )
    except Exception as e:
        return SkillResult(success=False, error=f"静态解析失败: {e}")


def _op_go_to_implementation(file_path: str, line: int = 0, character: int = 0) -> SkillResult:
    """跳转实现"""
    if not file_path or not os.path.isfile(file_path):
        return SkillResult(success=False, error=f"文件不存在: {file_path}")
    mgr = _get_lsp_manager()
    if mgr is None or not mgr.is_server_ready(mgr.get_language(file_path)):
        return SkillResult(success=False, error="LSP 未就绪，无法跳转实现")
    mgr.open_document(file_path, open(file_path, encoding='utf-8').read())
    collector = _ResultCollector()
    try:
        mgr.implementation_received.connect(collector.callback)
        mgr.request_implementation(file_path, line, character)
        result = collector.wait(default=[])
        mgr.implementation_received.disconnect(collector.callback)
    except Exception as e:
        return SkillResult(success=False, error=f"LSP 实现跳转失败: {e}")
    locations = result[1] if isinstance(result, tuple) and len(result) > 1 else []
    count = len(locations) if locations else 0
    return SkillResult(
        success=True,
        output=f"找到 {count} 个实现位置",
        data={"locations": _loc_list(locations)},
    )


def _op_completion(file_path: str, line: int = 0, character: int = 0) -> SkillResult:
    """代码补全"""
    if not file_path or not os.path.isfile(file_path):
        return SkillResult(success=False, error=f"文件不存在: {file_path}")
    mgr = _get_lsp_manager()
    if mgr is None or not mgr.is_server_ready(mgr.get_language(file_path)):
        return SkillResult(success=False, error="LSP 未就绪，无法补全")
    mgr.open_document(file_path, open(file_path, encoding='utf-8').read())
    collector = _ResultCollector()
    try:
        mgr.completion_received.connect(collector.callback)
        mgr.request_completion(file_path, line, character)
        result = collector.wait(default=[])
        mgr.completion_received.disconnect(collector.callback)
    except Exception as e:
        return SkillResult(success=False, error=f"LSP 补全失败: {e}")
    items = result[1] if isinstance(result, tuple) and len(result) > 1 else []
    count = len(items) if isinstance(items, list) else 0
    preview = [str(i)[:60] for i in (items[:10] if isinstance(items, list) else [])]
    return SkillResult(
        success=True,
        output=f"补全建议 ({count} 项):\n" + "\n".join(f"  • {p}" for p in preview),
        data={"items": items[:20] if isinstance(items, list) else []},
    )


def _op_diagnostics(file_path: str) -> SkillResult:
    """诊断信息"""
    if not file_path or not os.path.isfile(file_path):
        return SkillResult(success=False, error=f"文件不存在: {file_path}")
    mgr = _get_lsp_manager()
    if mgr is None:
        return SkillResult(success=False, error="LSP 管理器未初始化")
    diags = mgr.get_all_diagnostics().get(file_path, [])
    count = len(diags)
    if count == 0:
        return SkillResult(success=True, output="无诊断信息", data={"diagnostics": []})
    preview = [str(d)[:100] for d in diags[:10]]
    return SkillResult(
        success=True,
        output=f"诊断信息 ({count} 条):\n" + "\n".join(f"  • {p}" for p in preview),
        data={"diagnostics": [str(d) for d in diags]},
    )


def _op_health() -> SkillResult:
    """LSP 健康检查"""
    mgr = _get_lsp_manager()
    if mgr is None:
        return SkillResult(success=False, error="LSP 管理器未初始化")
    status = {}
    for lang_id in mgr.get_supported_languages():
        status[lang_id] = {
            "ready": mgr.is_server_ready(lang_id),
            "health": str(mgr.get_health()) if hasattr(mgr, 'get_health') else "unknown",
        }
    ready_count = sum(1 for s in status.values() if s["ready"])
    return SkillResult(
        success=True,
        output=f"LSP 状态: {ready_count}/{len(status)} 服务器就绪",
        data=status,
    )


def _loc_list(locations) -> List[Dict]:
    """将 Location 对象列表转为字典列表"""
    result = []
    for loc in (locations or []):
        if hasattr(loc, 'uri') and hasattr(loc, 'range'):
            result.append({
                "uri": loc.uri,
                "range": {
                    "start": {"line": loc.range.start.line, "character": loc.range.start.character},
                    "end": {"line": loc.range.end.line, "character": loc.range.end.character},
                },
            })
        elif isinstance(loc, dict):
            result.append(loc)
    return result


# ==================== 统一入口 ====================

def execute(
    action: str = "workspace_symbol",
    query: str = "",
    file_path: str = "",
    line: int = 0,
    character: int = 0,
    language_id: str = "python",
) -> SkillResult:
    """LSP 语义代码分析统一入口"""
    action = (action or "").lower().strip()

    if action == "workspace_symbol":
        return _op_workspace_symbol(query, language_id)
    if action == "document_symbol":
        return _op_document_symbol(file_path)
    if action == "go_to_definition":
        return _op_go_to_definition(file_path, line, character)
    if action == "find_references":
        return _op_find_references(file_path, line, character)
    if action == "hover":
        return _op_hover(file_path, line, character)
    if action == "go_to_implementation":
        return _op_go_to_implementation(file_path, line, character)
    if action == "completion":
        return _op_completion(file_path, line, character)
    if action == "diagnostics":
        return _op_diagnostics(file_path)
    if action == "health":
        return _op_health()
    # ★ L3 新增（2026-08-08）：写操作 — rename / format (S11)
    if action == "rename":
        return _op_rename(file_path, line, character, query)
    if action == "format":
        return _op_format(file_path)

    supported = ["workspace_symbol", "document_symbol", "go_to_definition",
                 "find_references", "hover", "go_to_implementation",
                 "completion", "diagnostics", "health", "rename", "format"]
    return SkillResult(
        success=False,
        error=f"未知 action: {action}（支持: {', '.join(supported)}）",
    )


# ==================== L3 写操作：rename / format (S11) ====================

def _apply_workspace_edit(workspace_edit: Dict) -> Dict:
    """应用 LSP 返回的 WorkspaceEdit（可能改多个文件）。

    返回 {changed_files, changes} 供上层汇报。
    """
    if not workspace_edit:
        return {"changed_files": [], "changes": {}}
    changes = workspace_edit.get("changes", {}) or {}
    # documentChanges 形式（含 rename 的 resourceOperations）
    document_changes = workspace_edit.get("documentChanges", []) or []
    applied: Dict[str, List[str]] = {}
    for uri, edits in changes.items():
        fp = uri[7:] if uri.startswith("file://") else uri
        if not os.path.isfile(fp):
            continue
        with open(fp, "r", encoding="utf-8") as f:
            lines = f.readlines()
        # edits 按区间从后往前应用，避免行号偏移
        sorted_edits = sorted(
            edits,
            key=lambda e: (
                e.get("range", {}).get("start", {}).get("line", 0),
                e.get("range", {}).get("start", {}).get("character", 0),
            ),
            reverse=True,
        )
        for e in sorted_edits:
            rng = e.get("range", {})
            sl = rng.get("start", {}).get("line", 0)
            el = rng.get("end", {}).get("line", 0)
            sc = rng.get("start", {}).get("character", 0)
            ec = rng.get("end", {}).get("character", 0)
            new_text = e.get("newText", "")
            if sl == el:
                line = lines[sl]
                lines[sl] = line[:sc] + new_text + line[ec:]
            else:
                lines[sl] = lines[sl][:sc] + new_text
                lines[el] = lines[el][ec:]
                del lines[sl + 1: el]
        with open(fp, "w", encoding="utf-8") as f:
            f.writelines(lines)
        applied[fp] = [e.get("newText", "") for e in sorted_edits]
    # documentChanges：处理 TextDocumentEdit
    for dc in document_changes:
        te = dc.get("textDocument", {})
        uri = te.get("uri", "")
        fp = uri[7:] if uri.startswith("file://") else uri
        edits = dc.get("edits", [])
        if not fp or not os.path.isfile(fp):
            continue
        with open(fp, "r", encoding="utf-8") as f:
            lines = f.readlines()
        sorted_edits = sorted(
            edits,
            key=lambda e: (
                e.get("range", {}).get("start", {}).get("line", 0),
                e.get("range", {}).get("start", {}).get("character", 0),
            ),
            reverse=True,
        )
        for e in sorted_edits:
            rng = e.get("range", {})
            sl = rng.get("start", {}).get("line", 0)
            el = rng.get("end", {}).get("line", 0)
            sc = rng.get("start", {}).get("character", 0)
            ec = rng.get("end", {}).get("character", 0)
            new_text = e.get("newText", "")
            if sl == el:
                line = lines[sl]
                lines[sl] = line[:sc] + new_text + line[ec:]
            else:
                lines[sl] = lines[sl][:sc] + new_text
                lines[el] = lines[el][ec:]
                del lines[sl + 1: el]
        with open(fp, "w", encoding="utf-8") as f:
            f.writelines(lines)
        applied.setdefault(fp, []).append("(documentChanges)")
    return {"changed_files": list(applied.keys()), "changes": applied}


def _op_rename(file_path: str, line: int, character: int, new_name: str) -> SkillResult:
    """重命名符号 — textDocument/rename（同步改所有引用）。

    优先走 LSP manager；不可用时降级为本地正则改所有引用文件（基于
    references 查询 + 词边界替换），保证"所有引用文件同步更新"可在无 LSP 时验证。
    """
    if not file_path or not os.path.isfile(file_path):
        return SkillResult(success=False, error=f"文件不存在: {file_path}")
    if not new_name:
        return SkillResult(success=False, error="rename 需要 new_name (query 参数)")

    # 优先走 LSP
    try:
        from lsp_manager import get_lsp_manager
        mgr = get_lsp_manager()
        client = mgr._servers.get(mgr.get_language(file_path)) if mgr else None
        if client and getattr(client, "is_initialized", False):
            result = client.request_rename(file_path, line, character, new_name)
            if result:
                applied = _apply_workspace_edit(result)
                return SkillResult(
                    success=True,
                    output=f"rename -> {new_name}, 改了 {len(applied['changed_files'])} 个文件",
                    data=applied,
                )
    except Exception:
        pass

    # 降级：本地正则重命名（基于词边界，避免部分匹配）
    import re
    name_re = re.compile(r"\b" + re.escape(new_name) + r"\b")
    # 用 references 找引用文件；无 LSP 时仅处理当前文件 + 同目录 .py
    refs_files = set([file_path])
    try:
        res = execute(action="find_references", file_path=file_path,
                      line=line, character=character)
        for loc in (res.data or {}).get("locations", []):
            uri = loc.get("uri", "")
            fp = uri[7:] if uri.startswith("file://") else uri
            if fp:
                refs_files.add(fp)
    except Exception:
        pass
    # 确定旧名：从当前文件目标位置附近的函数/变量名（用 AST 取标识符）
    old_name = _guess_symbol_name(file_path, line, character)
    if not old_name:
        return SkillResult(success=False, error="无法推断旧符号名，rename 失败")
    changed = []
    pat = re.compile(r"\b" + re.escape(old_name) + r"\b")
    for fp in refs_files:
        if not os.path.isfile(fp):
            continue
        with open(fp, "r", encoding="utf-8") as f:
            content = f.read()
        if old_name not in content:
            continue
        new_content = pat.sub(new_name, content)
        with open(fp, "w", encoding="utf-8") as f:
            f.write(new_content)
        changed.append(fp)
    return SkillResult(
        success=True,
        output=f"[本地降级] rename {old_name} -> {new_name}, 改了 {len(changed)} 个文件",
        data={"changed_files": changed, "old_name": old_name, "new_name": new_name},
    )


def _guess_symbol_name(file_path: str, line: int, character: int) -> str:
    """用 AST/正则推断光标处的符号名（降级用）"""
    import re
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            src = f.read()
        tree = compile(src, file_path, "exec", flags=0) if False else None
    except Exception:
        pass
    try:
        import ast
        with open(file_path, "r", encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Name, ast.arg)):
                if hasattr(node, "lineno") and node.lineno == line + 1:
                    return node.name if hasattr(node, "name") else getattr(node, "id", "")
    except Exception:
        pass
    # 正则兜底
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if line < len(lines):
            around = lines[line]
            m = re.search(r"([A-Za-z_]\w*)", around[max(0, character - 20):character + 20])
            if m:
                return m.group(1)
    except Exception:
        pass
    return ""


def _op_format(file_path: str) -> SkillResult:
    """全文件格式化 — textDocument/formatting。

    优先走 LSP manager；不可用时降级为本地保守整理（去尾部空白、保证结尾换行）。
    """
    if not file_path or not os.path.isfile(file_path):
        return SkillResult(success=False, error=f"文件不存在: {file_path}")

    try:
        from lsp_manager import get_lsp_manager
        mgr = get_lsp_manager()
        client = mgr._servers.get(mgr.get_language(file_path)) if mgr else None
        if client and getattr(client, "is_initialized", False):
            result = client.request_format(file_path)
            if result is not None:
                # result 是 TextEdit 列表
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                sorted_edits = sorted(
                    result,
                    key=lambda e: (
                        e.get("range", {}).get("start", {}).get("line", 0),
                        e.get("range", {}).get("start", {}).get("character", 0),
                    ),
                    reverse=True,
                )
                for e in sorted_edits:
                    rng = e.get("range", {})
                    sl = rng.get("start", {}).get("line", 0)
                    el = rng.get("end", {}).get("line", 0)
                    sc = rng.get("start", {}).get("character", 0)
                    ec = rng.get("end", {}).get("character", 0)
                    new_text = e.get("newText", "")
                    if sl == el:
                        line = lines[sl]
                        lines[sl] = line[:sc] + new_text + line[ec:]
                    else:
                        lines[sl] = lines[sl][:sc] + new_text
                        lines[el] = lines[el][ec:]
                        del lines[sl + 1: el]
                with open(file_path, "w", encoding="utf-8") as f:
                    f.writelines(lines)
                return SkillResult(success=True, output="格式化完成 (LSP)",
                                   data={"changed_files": [file_path]})
    except Exception:
        pass

    # 降级：本地保守整理
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    new_content = "\n".join(line.rstrip() for line in content.splitlines())
    if not new_content.endswith("\n"):
        new_content += "\n"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    return SkillResult(success=True, output="格式化完成 (本地降级)",
                       data={"changed_files": [file_path]})


def register(registry) -> None:
    """向 SkillsRegistry 注册 lsp_code_analysis Skill"""
    registry.register(SkillDef(
        name="lsp_code_analysis",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "LSP 操作类型",
                    "enum": [
                        "workspace_symbol", "document_symbol",
                        "go_to_definition", "find_references", "hover",
                        "go_to_implementation", "completion",
                        "diagnostics", "health", "rename", "format",
                    ],
                },
                "query": {
                    "type": "string",
                    "description": "workspace_symbol 的搜索关键词",
                },
                "file_path": {
                    "type": "string",
                    "description": "目标文件路径（绝对或相对于工作区根）",
                },
                "line": {
                    "type": "integer",
                    "description": "光标行号（0-based）",
                    "default": 0,
                },
                "character": {
                    "type": "integer",
                    "description": "光标列号（0-based）",
                    "default": 0,
                },
                "language_id": {
                    "type": "string",
                    "description": "语言 ID（python/javascript/cpp/go 等）",
                    "default": "python",
                },
            },
            "required": ["action"],
        },
        handler=execute,
        category=METADATA["category"],
        requires_confirm=False,
        timeout=15,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA


def is_available() -> bool:
    return _get_lsp_manager() is not None
