# -*- coding: utf-8 -*-
"""
★ 第281章 A 阶段 · Notebook 渲染/执行壳 (notebook_shell)
================================================
为 .ipynb 提供「渲染 + 执行」能力，作为 UI 侧可调工具源接入 SkillsRouter。

设计：
- 优先复用 core/skills/jupyter_notebook.py 的既有 Jupyter 执行能力（冻结区，仅 import 调用）。
- 若核心 Skill 不可用 / 无内核，则降级为「只读渲染」：解析 ipynb JSON，
  用 nbformat + nbconvert 或直接拼 HTML，保证 DoD「渲染」可用。
- 执行走 nbclient/nbconvert --execute（有 jupyter 内核时）；无内核给出明确提示。

非冻结区：本文件位于 standard_mode/ui/，不修改 core。

工具源接口兼容 RuntimeEngineHub.register_tool_source：
    list_tools() -> [ {name, description, parameters} ]
    invoke_tool(name, args) -> {success, output}
"""
from __future__ import annotations

import json
import os
import traceback
from typing import Any, Dict, List, Optional
from ui.design.tokens import Lemon

_log_prefix = "[NotebookShell]"


class NotebookShell:
    """Notebook 渲染/执行壳。"""

    def __init__(self, kernel_name: str = "python3"):
        self.kernel_name = kernel_name
        self._core_skill = None

    # ---------------------------------------------------- 连接 core skill
    def _ensure_core(self):
        if self._core_skill is not None:
            return self._core_skill
        try:
            from core.skills.jupyter_notebook import JupyterNotebookSkill
            self._core_skill = JupyterNotebookSkill()
        except Exception as e:
            print(f"{_log_prefix} 核心 Jupyter Skill 不可用，降级渲染: {e}")
            self._core_skill = False
        return self._core_skill

    # ---------------------------------------------------- 渲染
    def render(self, path: str) -> str:
        """渲染 .ipynb 为 HTML 字符串（不执行）。"""
        if not os.path.isfile(path):
            return f"<p>文件不存在: {path}</p>"
        try:
            with open(path, "r", encoding="utf-8") as f:
                nb = json.load(f)
            cells = nb.get("cells", [])
            html_parts = ["<div class='notebook'>"]
            for c in cells:
                ctype = c.get("cell_type")
                src = "".join(c.get("source", []))
                html_parts.append(self._render_cell(ctype, src, c))
            html_parts.append("</div>")
            return "\n".join(html_parts)
        except Exception as e:
            return f"<p>渲染失败: {e}</p>"

    def _render_cell(self, ctype: str, src: str, cell: dict) -> str:
        esc = src.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if ctype == "code":
            outs = cell.get("outputs", [])
            out_html = ""
            for o in outs:
                if isinstance(o, dict) and "text" in o:
                    out_html += "<pre class='nb-out'>" + o["text"].replace("<", "&lt;") + "</pre>"
                elif isinstance(o, dict) and "data" in o and "text/html" in o["data"]:
                    out_html += o["data"]["text/html"]
            return f"<div class='nb-cell nb-code'><pre class='nb-in'>&gt;&gt;&gt; {esc}</pre>{out_html}</div>"
        else:
            return f"<div class='nb-cell nb-md'>{esc}</div>"

    def render_html_page(self, path: str) -> str:
        body = self.render(path)
        return f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<style>
.notebook{{font-family:system-ui;padding:12px;}}
.nb-cell{{margin:6px 0;padding:8px;border-radius:6px;}}
.nb-code{{background:{Lemon.DARK_BG_4};color:{Lemon.DARK_TEXT_1};}}
.nb-md{{background:{Lemon.SURFACE};color:#222;}}
.nb-in{{white-space:pre-wrap;margin:0;}}
.nb-out{{white-space:pre-wrap;color:{Lemon.SYNTAX_FUNCTION};}}
</style></head><body>{body}</body></html>"""

    # ---------------------------------------------------- 执行
    def execute(self, path: str, output_path: Optional[str] = None) -> Dict[str, Any]:
        """
        执行 Notebook（走核心 Jupyter Skill 或 nbclient 降级）。
        返回 {success, output, executed_path}
        """
        if not os.path.isfile(path):
            return {"success": False, "output": f"文件不存在: {path}", "executed_path": None}
        # 1) 核心 skill 优先
        skill = self._ensure_core()
        if skill and skill is not False and hasattr(skill, "execute_notebook"):
            try:
                result = skill.execute_notebook(path, output_path=output_path,
                                                kernel_name=self.kernel_name)
                return {"success": True,
                        "output": result if isinstance(result, str) else json.dumps(result, ensure_ascii=False),
                        "executed_path": output_path or path}
            except Exception as e:
                print(f"{_log_prefix} 核心执行失败，尝试 nbclient: {e}")
        # 2) nbclient 降级
        try:
            import nbclient
            from nbformat import read, write
            nb = read(path, as_version=4)
            client = nbclient.NotebookClient(nb, kernel_name=self.kernel_name, timeout=120)
            client.execute()
            out = output_path or path.replace(".ipynb", "_executed.ipynb")
            write(nb, out)
            return {"success": True, "output": f"已执行并写出: {out}", "executed_path": out}
        except Exception as e:
            return {"success": False,
                    "output": f"执行失败（无可用内核？）: {e}\n提示：安装 `pip install nbclient jupyter` 后重试。",
                    "executed_path": None}

    # ---------------------------------------------------- 工具源接口
    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": "notebook.render", "description": "渲染 .ipynb 为 HTML（不执行）",
             "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}},
            {"name": "notebook.execute", "description": "执行 .ipynb 并写出结果",
             "parameters": {"type": "object", "properties": {
                 "path": {"type": "string"}, "output_path": {"type": "string"}}}},
        ]

    def invoke_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if tool_name == "notebook.render":
                return {"success": True, "output": self.render_html_page(args.get("path", ""))}
            if tool_name == "notebook.execute":
                return self.execute(args.get("path", ""), args.get("output_path"))
            return {"success": False, "output": f"未知 notebook 工具: {tool_name}"}
        except Exception as e:
            return {"success": False, "output": f"{tool_name} 异常: {e}\n{traceback.format_exc()}"}

    # ---------------------------------------------------- 注册进路由表
    def register_to(self, registry=None) -> int:
        try:
            from core.skills_registry import SkillDef, get_skills_registry
        except Exception as e:
            print(f"{_log_prefix} 无法导入 SkillsRegistry: {e}")
            return 0
        reg = registry or get_skills_registry()
        count = 0
        for t in self.list_tools():
            try:
                sd = SkillDef(
                    name=t["name"], description=t["description"],
                    parameters=t["parameters"],
                    handler=lambda a, _n=t["name"]: self.invoke_tool(_n, a),
                    category="notebook", requires_confirm=False, timeout=120)
                reg.register(sd)
                count += 1
            except Exception as e:
                print(f"{_log_prefix} 注册 {t['name']} 失败: {e}")
        print(f"{_log_prefix} 已注册 {count} 个 Notebook 工具")
        return count


if __name__ == "__main__":
    sh = NotebookShell()
    print("tools:", [t["name"] for t in sh.list_tools()])
    # 渲染一个不存在的文件 -> 给出错误提示（验证不崩溃）
    print(sh.render("/tmp/_not_exist.ipynb")[:80])
