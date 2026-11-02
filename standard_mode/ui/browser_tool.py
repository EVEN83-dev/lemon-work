# -*- coding: utf-8 -*-
"""
★ 第281章 A 阶段 · 内置 Browser 工具源 (browser_tool)
================================================
把 ui/web_browser_panel.py 的 WebBrowserPanel（已作为 Tab 6 挂载）包装成
「可调工具源」，使模型/UI 可通过 UniversalSkillRouter 发起浏览器操作：
    browser.open(url)       打开/导航到 URL
    browser.back()          后退
    browser.forward()       前进
    browser.reload()        刷新
    browser.get_html()      抓取当前页 HTML（异步 toHtml 同步化）

非冻结区：本文件位于 standard_mode/ui/。可复用 main_window 已有的
self.web_browser 实例（传入 panel=self.web_browser）避免重复创建 WebEngine。

工具源接口兼容 RuntimeEngineHub.register_tool_source：
    list_tools() -> [ {name, description, parameters} ]
    invoke_tool(name, args) -> {success, output}
"""
from __future__ import annotations

import traceback
from typing import Any, Dict, List, Optional

_log_prefix = "[BrowserToolSource]"


class BrowserToolSource:
    """WebBrowserPanel 的工具源封装。"""

    def __init__(self, panel=None):
        """
        :param panel: 已存在的 WebBrowserPanel 实例（如 main_window.web_browser）；
                      为 None 时惰性创建一个独立实例。
        """
        self._panel = panel

    # ---------------------------------------------------------- 确保面板
    def _ensure_panel(self):
        if self._panel is None:
            try:
                from ui.web_browser_panel import WebBrowserPanel
                self._panel = WebBrowserPanel()
            except Exception as e:
                print(f"{_log_prefix} 创建 WebBrowserPanel 失败: {e}")
                self._panel = False
        return self._panel

    def _get_html(self, panel) -> str:
        """同步抓取当前页 HTML（QWebEngine toHtml 是异步回调，用事件循环等待）。"""
        try:
            from PyQt5.QtCore import QEventLoop
            view = getattr(panel, "_webview", None)
            if view is None:
                return ""
            page = view.page()
            holder: Dict[str, str] = {}
            loop = QEventLoop()

            def _cb(html: str):
                holder["html"] = html
                loop.quit()

            page.toHtml(_cb)
            loop.exec_()
            return holder.get("html", "")
        except Exception as e:
            return f"[抓取HTML失败: {e}]"

    # ---------------------------------------------------------- 工具源接口
    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": "browser.open", "description": "在内置浏览器打开/导航到 URL",
             "parameters": {"type": "object", "properties": {"url": {"type": "string"}}}},
            {"name": "browser.back", "description": "浏览器后退",
             "parameters": {"type": "object", "properties": {}}},
            {"name": "browser.forward", "description": "浏览器前进",
             "parameters": {"type": "object", "properties": {}}},
            {"name": "browser.reload", "description": "浏览器刷新当前页",
             "parameters": {"type": "object", "properties": {}}},
            {"name": "browser.get_html", "description": "抓取当前页面 HTML 源码",
             "parameters": {"type": "object", "properties": {}}},
        ]

    def invoke_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        panel = self._ensure_panel()
        if panel is False or panel is None:
            return {"success": False, "output": "浏览器面板不可用"}
        try:
            if tool_name == "browser.open":
                url = args.get("url", "")
                if not url:
                    return {"success": False, "output": "缺少 url 参数"}
                panel.navigate(url)
                return {"success": True, "output": f"已导航到 {url}"}
            if tool_name == "browser.back":
                if hasattr(panel, "_go_back"):
                    panel._go_back()
                return {"success": True, "output": "已后退"}
            if tool_name == "browser.forward":
                if hasattr(panel, "_go_forward"):
                    panel._go_forward()
                return {"success": True, "output": "已前进"}
            if tool_name == "browser.reload":
                panel.reload_ignore_cache() if hasattr(panel, "reload_ignore_cache") else panel._refresh()
                return {"success": True, "output": "已刷新"}
            if tool_name == "browser.get_html":
                html = self._get_html(panel)
                return {"success": True, "output": html or "(空页面)"}
            return {"success": False, "output": f"未知 browser 工具: {tool_name}"}
        except Exception as e:
            return {"success": False, "output": f"{tool_name} 异常: {e}\n{traceback.format_exc()}"}

    # ---------------------------------------------------------- 注册进路由表
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
                    category="browser", requires_confirm=False, timeout=30)
                reg.register(sd)
                count += 1
            except Exception as e:
                print(f"{_log_prefix} 注册 {t['name']} 失败: {e}")
        print(f"{_log_prefix} 已注册 {count} 个 Browser 工具")
        return count


if __name__ == "__main__":
    # 独立验证（需 PyQt5 环境）：渲染一个浏览器工具清单
    src = BrowserToolSource()
    print("tools:", [t["name"] for t in src.list_tools()])
