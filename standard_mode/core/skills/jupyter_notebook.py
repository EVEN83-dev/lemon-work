# -*- coding: utf-8 -*-
"""
Skill: jupyter_notebook — Jupyter Notebook 自动化（v0.8.0 新增）
================================================================
基于 nbformat + nbclient 实现 Notebook 创建/读取/执行/单元格操作。

支持的操作：
  - create      创建空 notebook（可选初始 cells）
  - open        读取已有 .ipynb 文件
  - execute     执行 notebook（运行所有单元格）
  - add_code    插入代码单元格
  - add_markdown 插入 Markdown 单元格
  - get_output  获取执行输出
  - save        保存 notebook 到文件
  - list_cells  列出所有单元格

优雅降级：
  - nbformat 未安装时返回安装提示
  - 执行超时自动回收（避免 CellExecutionError 阻塞）
  - 单元格执行错误不中断整体流程

人性化设计：
  - 执行结果内联展示在对话中（支持 text/html + image/png base64）
  - 进度回调上报每个单元格执行状态
"""

import os
import base64
import threading
from typing import Dict, Any, List, Optional, Callable

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "jupyter_notebook",
    "description": "Jupyter Notebook 自动化：创建/读取/执行/插入单元格/获取输出（基于 nbformat + nbclient）",
    "category": "code",
    "version": "1.0.0",
}


# ==================== 依赖检测 ====================

_DEPS_CHECKED: bool = False
_DEPS_AVAILABLE: bool = False
_DEPS_LOCK = threading.Lock()


def _check_deps() -> bool:
    """检测 nbformat + nbclient 是否可用"""
    global _DEPS_CHECKED, _DEPS_AVAILABLE
    with _DEPS_LOCK:
        if _DEPS_CHECKED:
            return _DEPS_AVAILABLE
        _DEPS_CHECKED = True
        try:
            import nbformat  # noqa: F401
            import nbclient  # noqa: F401
            _DEPS_AVAILABLE = True
        except ImportError:
            _DEPS_AVAILABLE = False
        return _DEPS_AVAILABLE


def _install_hint() -> str:
    return (
        "Jupyter Notebook 依赖未安装。\n"
        "请运行：\n"
        "  pip install nbformat nbclient ipykernel\n"
        "  python -m ipykernel install --user --name python3"
    )


# ==================== Notebook 会话 ====================

class _NotebookSession:
    """Notebook 会话 — 内存中持有当前操作的 notebook 对象"""

    def __init__(self):
        self._lock = threading.Lock()
        self._nb: Any = None     # nbformat NotebookNode
        self._path: str = ""     # 当前关联文件路径

    def _ensure_nb(self) -> Optional[str]:
        """确保已加载 notebook，返回错误信息或 None"""
        with self._lock:
            if self._nb is None:
                return "未加载 notebook，请先调用 create 或 open 操作"
            return None

    def reset(self, nb: Any, path: str = ""):
        with self._lock:
            self._nb = nb
            self._path = path

    @property
    def nb(self):
        return self._nb

    @property
    def path(self):
        return self._path


_SESSION = _NotebookSession()


# ==================== 进度回调 ====================

_PROGRESS_CALLBACKS: List[Callable] = []
_PROGRESS_LOCK = threading.Lock()


def set_progress_callback(cb: Callable):
    """注册全局进度回调（UI 层调用）"""
    global _PROGRESS_CALLBACKS
    with _PROGRESS_LOCK:
        _PROGRESS_CALLBACKS = [cb]


def _emit_progress(step: str, status: str = "running", detail: str = ""):
    """广播进度事件"""
    with _PROGRESS_LOCK:
        cbs = list(_PROGRESS_CALLBACKS)
    for cb in cbs:
        try:
            cb({
                "step": step,
                "status": status,
                "detail": detail,
                "timestamp": __import__("time").time(),
            })
        except Exception:
            pass


# ==================== 操作实现 ====================

def _op_create(
    cells: List[Dict[str, str]] = None,
    kernel: str = "python3",
) -> SkillResult:
    """创建新的 notebook"""
    _emit_progress("创建 Notebook", "running", f"kernel={kernel}")
    if not _check_deps():
        _emit_progress("创建 Notebook", "failed", "依赖未安装")
        return SkillResult(success=False, error=_install_hint())

    try:
        import nbformat as nbf
        from nbformat.v4 import new_notebook, new_code_cell, new_markdown_cell

        nb = new_notebook()
        nb.metadata["kernelspec"] = {
            "name": kernel,
            "display_name": "Python 3" if kernel == "python3" else kernel,
            "language": "python",
        }
        nb.metadata["language_info"] = {
            "name": "python",
            "version": "3.x",
        }

        added = 0
        for cell_spec in (cells or []):
            ctype = cell_spec.get("type", "code")
            csource = cell_spec.get("source", "")
            if ctype == "markdown":
                nb.cells.append(new_markdown_cell(csource))
            else:
                nb.cells.append(new_code_cell(csource))
            added += 1

        _SESSION.reset(nb, "")
        _emit_progress("创建 Notebook", "success", f"{added} 单元格")
        return SkillResult(
            success=True,
            output=f"✅ 已创建空 notebook（kernel={kernel}, 初始 {added} 个单元格）",
            data={"cells": len(nb.cells), "kernel": kernel},
        )
    except Exception as e:
        _emit_progress("创建 Notebook", "failed", str(e))
        return SkillResult(success=False, error=f"创建失败: {e}")


def _op_open(file_path: str) -> SkillResult:
    """打开已有 notebook"""
    _emit_progress("打开 Notebook", "running", file_path)
    if not _check_deps():
        _emit_progress("打开 Notebook", "failed", "依赖未安装")
        return SkillResult(success=False, error=_install_hint())

    if not file_path:
        return SkillResult(success=False, error="file_path 参数为空")

    path = file_path
    if not os.path.isabs(path):
        path = os.path.join(os.getcwd(), path)
    if not os.path.exists(path):
        _emit_progress("打开 Notebook", "failed", f"文件不存在: {path}")
        return SkillResult(success=False, error=f"文件不存在: {path}")

    try:
        import nbformat as nbf
        nb = nbf.read(path, as_version=4)
        _SESSION.reset(nb, path)
        code_count = sum(1 for c in nb.cells if c.cell_type == "code")
        md_count = sum(1 for c in nb.cells if c.cell_type == "markdown")
        _emit_progress("打开 Notebook", "success", f"{len(nb.cells)} 单元格")
        return SkillResult(
            success=True,
            output=f"✅ 已打开: {os.path.basename(path)}\n总单元格: {len(nb.cells)} (代码 {code_count} / Markdown {md_count})",
            data={"path": path, "cells": len(nb.cells), "code_cells": code_count, "md_cells": md_count},
        )
    except Exception as e:
        _emit_progress("打开 Notebook", "failed", str(e))
        return SkillResult(success=False, error=f"打开失败: {e}")


def _op_add_cell(cell_type: str, source: str, index: int = -1) -> SkillResult:
    """插入单元格"""
    _emit_progress(f"插入 {cell_type} 单元格", "running", f"index={index}")
    if not _check_deps():
        _emit_progress("插入单元格", "failed", "依赖未安装")
        return SkillResult(success=False, error=_install_hint())

    err = _SESSION._ensure_nb()
    if err:
        _emit_progress("插入单元格", "failed", err)
        return SkillResult(success=False, error=err)

    try:
        from nbformat.v4 import new_code_cell, new_markdown_cell
        nb = _SESSION.nb
        if cell_type == "markdown":
            cell = new_markdown_cell(source)
        else:
            cell = new_code_cell(source)

        if index < 0 or index >= len(nb.cells):
            nb.cells.append(cell)
            actual_index = len(nb.cells) - 1
        else:
            nb.cells.insert(index, cell)
            actual_index = index

        _emit_progress(f"插入 {cell_type} 单元格", "success", f"位置={actual_index}")
        return SkillResult(
            success=True,
            output=f"✅ 已在位置 {actual_index} 插入 {cell_type} 单元格",
            data={"index": actual_index, "cell_type": cell_type, "source": source[:200]},
        )
    except Exception as e:
        _emit_progress("插入单元格", "failed", str(e))
        return SkillResult(success=False, error=f"插入失败: {e}")


def _op_execute(timeout: int = 60, kernel_name: str = "python3") -> SkillResult:
    """执行 notebook 中所有代码单元格"""
    _emit_progress("执行 Notebook", "running", f"timeout={timeout}s")
    if not _check_deps():
        _emit_progress("执行 Notebook", "failed", "依赖未安装")
        return SkillResult(success=False, error=_install_hint())

    err = _SESSION._ensure_nb()
    if err:
        _emit_progress("执行 Notebook", "failed", err)
        return SkillResult(success=False, error=err)

    try:
        from nbclient import NotebookClient
        nb = _SESSION.nb
        client = NotebookClient(
            nb,
            timeout=timeout,
            kernel_name=kernel_name,
            allow_errors=True,   # 不中断整体执行
        )
        # ★ 超时保护：CellExecutionError / DeadKernelError 由 allow_errors 控制
        try:
            client.execute()
        except Exception as exec_err:
            # 超时或内核死亡 — 不中断流程，返回部分执行结果
            _emit_progress("执行 Notebook", "failed", f"执行异常: {exec_err}")
            return SkillResult(
                success=False,
                error=f"执行异常（可能超时 {timeout}s 或内核死亡）: {exec_err}",
                data={"partial": True},
            )

        # 收集执行输出
        results = _collect_outputs(nb)
        total = results["total"]
        ok = results["ok"]
        err_count = results["error"]
        _emit_progress("执行 Notebook", "success", f"{ok}/{total} 成功")
        return SkillResult(
            success=True,
            output=(
                f"✅ 执行完成：{total} 个代码单元格，{ok} 成功，{err_count} 错误\n\n"
                f"{results['preview']}"
            ),
            data={
                "total": total,
                "ok": ok,
                "error": err_count,
                "outputs": results["outputs"],
                "inline_html": results["inline_html"],  # ★ 内联 HTML 渲染数据
            },
        )
    except Exception as e:
        _emit_progress("执行 Notebook", "failed", str(e))
        return SkillResult(success=False, error=f"执行失败: {e}")


def _collect_outputs(nb) -> Dict[str, Any]:
    """收集 notebook 所有代码单元格的执行输出，并构造内联 HTML"""
    outputs = []
    inline_parts = []
    ok = 0
    err_count = 0

    for idx, cell in enumerate(nb.cells):
        if cell.cell_type != "code":
            continue
        cell_outputs = cell.get("outputs", [])
        cell_result = {
            "index": idx,
            "source": cell.source[:200],
            "outputs": [],
        }
        cell_inline = []

        for out in cell_outputs:
            out_type = out.get("output_type", "")
            if out_type == "stream":
                text = out.get("text", "")
                if isinstance(text, list):
                    text = "".join(text)
                cell_result["outputs"].append({"type": "stream", "text": text})
                cell_inline.append(
                    f'<pre style="color:Lemon.STATUS_OFFLINE;margin:2px 0;">{_escape_html(text)}</pre>'
                )
            elif out_type == "execute_result":
                data = out.get("data", {})
                if "text/plain" in data:
                    text = data["text/plain"]
                    if isinstance(text, list):
                        text = "".join(text)
                    cell_result["outputs"].append({"type": "result_text", "text": text})
                    cell_inline.append(
                        f'<pre style="color:Lemon.PLACEHOLDER;margin:2px 0;">{_escape_html(text)}</pre>'
                    )
                if "text/html" in data:
                    html = data["text/html"]
                    if isinstance(html, list):
                        html = "".join(html)
                    cell_result["outputs"].append({"type": "result_html", "html": html[:2000]})
                    cell_inline.append(f'<div>{html[:2000]}</div>')
                if "image/png" in data:
                    png_b64 = data["image/png"]
                    if isinstance(png_b64, list):
                        png_b64 = "".join(png_b64)
                    cell_result["outputs"].append({"type": "image", "length": len(png_b64)})
                    cell_inline.append(
                        f'<img src="data:image/png;base64,{png_b64}" '
                        f'style="max-width:100%;margin:4px 0;" />'
                    )
            elif out_type == "error":
                ename = out.get("ename", "")
                evalue = out.get("evalue", "")
                traceback = out.get("traceback", [])
                if isinstance(traceback, list):
                    traceback = "\n".join(traceback)
                cell_result["outputs"].append({
                    "type": "error",
                    "ename": ename,
                    "evalue": evalue,
                    "traceback": traceback[:1000],
                })
                cell_inline.append(
                    f'<pre style="color:#f85149;margin:2px 0;">{ename}: {_escape_html(evalue)}</pre>'
                )
                err_count += 1

        if not any(o.get("type") == "error" for o in cell_result["outputs"]):
            ok += 1

        outputs.append(cell_result)
        # 构造单元格 HTML 块（人性设计：内联展示）
        source_preview = _escape_html(cell.source[:120])
        inline_parts.append(
            f'<div style="margin:8px 0;padding:8px;border-left:3px solid Lemon.STATUS_RUNNING;background:Lemon.DARK_BG_1;">'
            f'<div style="color:Lemon.STATUS_RUNNING;font-size:11px;">[Cell {idx}]</div>'
            f'<pre style="color:Lemon.PLACEHOLDER;margin:4px 0;">{source_preview}</pre>'
            f'<div style="margin-top:4px;">{"".join(cell_inline)}</div>'
            f'</div>'
        )

    preview = "\n".join(
        f"[Cell {o['index']}] → {len(o['outputs'])} 输出"
        for o in outputs[:5]
    )
    inline_html = (
        '<div style="font-family:Consolas,monospace;">'
        + "".join(inline_parts)
        + '</div>'
    )

    return {
        "total": len(outputs),
        "ok": ok,
        "error": err_count,
        "outputs": outputs,
        "preview": preview,
        "inline_html": inline_html,
    }


def _escape_html(text: str) -> str:
    """转义 HTML 特殊字符"""
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _op_get_output(index: int = -1) -> SkillResult:
    """获取指定单元格（或全部）的执行输出"""
    _emit_progress("获取输出", "running", f"index={index}")
    err = _SESSION._ensure_nb()
    if err:
        _emit_progress("获取输出", "failed", err)
        return SkillResult(success=False, error=err)

    try:
        nb = _SESSION.nb
        if index >= 0:
            if index >= len(nb.cells):
                _emit_progress("获取输出", "failed", "索引越界")
                return SkillResult(success=False, error=f"单元格索引 {index} 超出范围（共 {len(nb.cells)} 个）")
            cell = nb.cells[index]
            outputs_data = _collect_outputs_single(cell, index)
            _emit_progress("获取输出", "success", f"{len(outputs_data['outputs'])} 输出")
            return SkillResult(
                success=True,
                output=f"✅ 单元格 {index} 的输出:\n{outputs_data['preview']}",
                data=outputs_data,
            )
        # 全部输出
        results = _collect_outputs(nb)
        _emit_progress("获取输出", "success", f"{results['total']} 单元格")
        return SkillResult(
            success=True,
            output=f"✅ 所有单元格输出:\n{results['preview']}",
            data=results,
        )
    except Exception as e:
        _emit_progress("获取输出", "failed", str(e))
        return SkillResult(success=False, error=f"获取输出失败: {e}")


def _collect_outputs_single(cell, index: int) -> Dict[str, Any]:
    """收集单个单元格的输出"""
    if cell.cell_type != "code":
        return {"index": index, "outputs": [], "preview": f"[Cell {index}] 非代码单元格"}
    fake_nb = type("FakeNB", (), {"cells": [cell]})()
    return _collect_outputs(fake_nb)


def _op_save(file_path: str = "") -> SkillResult:
    """保存 notebook 到文件"""
    _emit_progress("保存 Notebook", "running", file_path or _SESSION.path)
    err = _SESSION._ensure_nb()
    if err:
        _emit_progress("保存 Notebook", "failed", err)
        return SkillResult(success=False, error=err)

    path = file_path or _SESSION.path
    if not path:
        return SkillResult(success=False, error="未指定保存路径，请提供 file_path")
    if not os.path.isabs(path):
        path = os.path.join(os.getcwd(), path)
    if not path.endswith(".ipynb"):
        path += ".ipynb"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    try:
        import nbformat as nbf
        nbf.write(_SESSION.nb, path)
        _SESSION._path = path
        size = os.path.getsize(path)
        _emit_progress("保存 Notebook", "success", f"{size}B")
        return SkillResult(
            success=True,
            output=f"✅ 已保存: {path}（{size} 字节）",
            data={"path": path, "size": size},
        )
    except Exception as e:
        _emit_progress("保存 Notebook", "failed", str(e))
        return SkillResult(success=False, error=f"保存失败: {e}")


def _op_list_cells() -> SkillResult:
    """列出所有单元格"""
    err = _SESSION._ensure_nb()
    if err:
        return SkillResult(success=False, error=err)
    try:
        nb = _SESSION.nb
        lines = []
        for i, cell in enumerate(nb.cells):
            ctype = cell.cell_type
            preview = (cell.source or "").strip().split("\n")[0][:80]
            icon = "📝" if ctype == "markdown" else "⚡"
            lines.append(f"  {icon} [{i}] {ctype}: {preview}")
        return SkillResult(
            success=True,
            output=f"共 {len(nb.cells)} 个单元格:\n" + "\n".join(lines),
            data={
                "total": len(nb.cells),
                "cells": [
                    {"index": i, "type": c.cell_type, "source": (c.source or "")[:200]}
                    for i, c in enumerate(nb.cells)
                ],
            },
        )
    except Exception as e:
        return SkillResult(success=False, error=f"列出单元格失败: {e}")


# ==================== 统一入口 ====================

def execute(
    action: str = "create",
    file_path: str = "",
    cells: str = "",
    cell_type: str = "code",
    source: str = "",
    index: int = -1,
    timeout: int = 60,
    kernel: str = "python3",
) -> SkillResult:
    """Jupyter Notebook 自动化统一入口

    Args:
        action: 操作类型 create/open/execute/add_code/add_markdown/get_output/save/list_cells
        file_path: open/save 的文件路径
        cells: create 时的初始单元格 JSON（[{"type":"code","source":"print(1)"}]）
        cell_type: add_* 操作的单元格类型
        source: add_* 操作的单元格内容
        index: add_*/get_output 的单元格索引（-1 表示末尾/全部）
        timeout: execute 超时（秒）
        kernel: 内核名称
    """
    action = (action or "").lower().strip()

    if action == "create":
        cell_list = []
        if cells:
            import json
            try:
                cell_list = json.loads(cells)
            except Exception:
                return SkillResult(success=False, error="cells 参数需要 JSON 数组格式")
        return _op_create(cells=cell_list, kernel=kernel)

    if action == "open":
        if not file_path:
            return SkillResult(success=False, error="open 操作需要 file_path 参数")
        return _op_open(file_path)

    if action == "execute":
        return _op_execute(timeout=timeout, kernel_name=kernel)

    if action in ("add_code", "add_markdown"):
        ctype = "code" if action == "add_code" else "markdown"
        if not source:
            return SkillResult(success=False, error=f"{action} 操作需要 source 参数")
        return _op_add_cell(cell_type=ctype, source=source, index=index)

    if action == "get_output":
        return _op_get_output(index=index)

    if action == "save":
        return _op_save(file_path)

    if action == "list_cells":
        return _op_list_cells()

    return SkillResult(
        success=False,
        error=f"未知 action: {action}（支持: create/open/execute/add_code/add_markdown/get_output/save/list_cells）",
    )


def register(registry) -> None:
    """向 SkillsRegistry 注册 jupyter_notebook Skill"""
    registry.register(SkillDef(
        name="jupyter_notebook",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "操作类型",
                    "enum": [
                        "create", "open", "execute",
                        "add_code", "add_markdown",
                        "get_output", "save", "list_cells",
                    ],
                },
                "file_path": {"type": "string", "description": "open/save 的 .ipynb 文件路径"},
                "cells": {
                    "type": "string",
                    "description": "create 时的初始单元格 JSON 数组：[{\"type\":\"code/markdown\",\"source\":\"...\"}]",
                },
                "cell_type": {
                    "type": "string",
                    "description": "单元格类型（add_* 操作使用）",
                    "enum": ["code", "markdown"],
                    "default": "code",
                },
                "source": {"type": "string", "description": "add_* 操作的单元格内容"},
                "index": {
                    "type": "integer",
                    "description": "add_*/get_output 的单元格索引（-1 表示末尾/全部）",
                    "default": -1,
                },
                "timeout": {
                    "type": "integer",
                    "description": "execute 操作超时（秒，5-300）",
                    "default": 60,
                },
                "kernel": {
                    "type": "string",
                    "description": "Jupyter 内核名称",
                    "default": "python3",
                },
            },
            "required": ["action"],
        },
        handler=execute,
        category=METADATA["category"],
        requires_confirm=False,
        timeout=300,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA


def is_available() -> bool:
    """检测 Jupyter 依赖是否可用"""
    return _check_deps()
