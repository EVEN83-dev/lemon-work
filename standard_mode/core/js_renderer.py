# -*- coding: utf-8 -*-
"""364章 T3.4: JS渲染抓取 — Playwright/Puppeteer无头浏览器抓取"""

import json
import os
import subprocess
import tempfile
from typing import Dict, Optional


class JSRenderer:
    def __init__(self, timeout: int = 30, wait_for: str = "networkidle"):
        self.timeout = timeout
        self.wait_for = wait_for
        self._available = None

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            from playwright.sync_api import sync_playwright
            self._available = True
        except ImportError:
            self._available = False
        return self._available

    def fetch(self, url: str, selector: str = "", wait_seconds: int = 0,
              execute_js: str = "", output_format: str = "html") -> Dict:
        if not self.is_available():
            return {"success": False, "error": "Playwright未安装",
                    "output": "请执行: pip install playwright && playwright install chromium"}

        if not url:
            return {"success": False, "error": "URL为空"}

        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, timeout=self.timeout * 1000,
                          wait_until=self.wait_for)

                if wait_seconds > 0:
                    page.wait_for_timeout(wait_seconds * 1000)

                if execute_js:
                    js_result = page.evaluate(execute_js)

                if selector:
                    element = page.query_selector(selector)
                    if element:
                        content = element.inner_html() if output_format == "html" else element.inner_text()
                    else:
                        content = f"选择器 '{selector}' 未找到元素"
                else:
                    content = page.content() if output_format == "html" else page.inner_text("body")

                title = page.title()
                browser.close()

                return {
                    "success": True,
                    "output": content[:50000],
                    "title": title,
                    "url": url,
                    "format": output_format,
                }
        except Exception as e:
            return {"success": False, "error": str(e), "output": ""}

    def screenshot(self, url: str, save_path: str = "",
                   full_page: bool = False, width: int = 1280,
                   height: int = 720) -> Dict:
        if not self.is_available():
            return {"success": False, "error": "Playwright未安装"}

        if not url:
            return {"success": False, "error": "URL为空"}

        if not save_path:
            save_path = os.path.join(tempfile.gettempdir(), "js_render_screenshot.png")

        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": width, "height": height})
                page.goto(url, timeout=self.timeout * 1000)
                page.screenshot(path=save_path, full_page=full_page)
                browser.close()

            return {
                "success": True,
                "output": f"截图已保存: {save_path}",
                "save_path": save_path,
                "url": url,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
