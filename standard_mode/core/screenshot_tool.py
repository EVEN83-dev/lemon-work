# -*- coding: utf-8 -*-
"""
Screenshot Tool -- Playwright 截图封装
========================================
隔离 playwright 依赖，无 playwright 时优雅降级返回 False。
"""

import logging
import os
import time

logger = logging.getLogger(__name__)

_PLAYWRIGHT_AVAILABLE = None


def _check_playwright() -> bool:
    global _PLAYWRIGHT_AVAILABLE
    if _PLAYWRIGHT_AVAILABLE is None:
        try:
            from playwright.sync_api import sync_playwright
            _PLAYWRIGHT_AVAILABLE = True
        except ImportError:
            _PLAYWRIGHT_AVAILABLE = False
            logger.info("[ScreenshotTool] playwright 未安装，截图功能降级")
    return _PLAYWRIGHT_AVAILABLE


def capture(url: str, output: str, width: int = 1280, height: int = 800) -> bool:
    """对 URL 截图，保存 PNG 到 output 路径

    Args:
        url: http(s) URL
        output: 输出 PNG 文件路径
        width: 视口宽度
        height: 视口高度

    Returns:
        True=截图成功，False=失败或 playwright 不可用
    """
    if not _check_playwright():
        logger.info("[ScreenshotTool] playwright 不可用，跳过截图")
        return False

    try:
        from playwright.sync_api import sync_playwright
        os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(url, timeout=30000, wait_until="networkidle")
            time.sleep(0.5)
            page.screenshot(path=output, full_page=False)
            browser.close()
        logger.info(f"[ScreenshotTool] 截图成功: {output}")
        return True
    except Exception as e:
        logger.warning(f"[ScreenshotTool] 截图失败: {e}")
        return False


def capture_html(html_path: str, output: str, width: int = 1280, height: int = 800) -> bool:
    """对本地 HTML 文件截图

    Args:
        html_path: 本地 HTML 文件绝对路径
        output: 输出 PNG 文件路径
        width: 视口宽度
        height: 视口高度

    Returns:
        True=截图成功
    """
    if not os.path.isfile(html_path):
        logger.warning(f"[ScreenshotTool] HTML 文件不存在: {html_path}")
        return False
    abs_path = os.path.abspath(html_path)
    file_url = f"file:///{abs_path.replace(os.sep, '/')}"
    return capture(file_url, output, width, height)
