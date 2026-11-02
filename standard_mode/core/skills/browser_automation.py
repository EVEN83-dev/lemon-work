# -*- coding: utf-8 -*-
"""
Skill: browser_automation — 浏览器自动化（v0.8.0 新增）
=====================================================
基于 Playwright（首选）或 Selenium（备选）实现浏览器自动化操作。

支持的操作：
  - open        打开页面
  - screenshot  截图（全页/元素/视口）
  - click       元素点击
  - fill        表单填写
  - extract     文本提取
  - scroll      页面滚动
  - close       关闭浏览器

优雅降级：
  - Playwright 未安装时返回提示信息（不抛异常）
  - 浏览器未启动时自动启动
  - 超时自动回收资源

人性化设计：
  - 通过 progress_callback 回调实时上报操作步骤进度
  - 截图路径在结果中明确返回，便于右侧面板内联展示
"""

import os
import time
import base64
import shutil
import threading
from typing import Dict, Any, List, Optional, Callable

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "browser_automation",
    "description": "浏览器自动化：基于 Playwright/Selenium 实现页面打开/截图/点击/表单填写/文本提取/滚动",
    "category": "browser",
    "version": "1.0.0",
}

# ==================== 后端选择 ====================

_BACKEND: str = ""          # "playwright" | "selenium" | ""
_BACKEND_CHECKED: bool = False
_BACKEND_LOCK = threading.Lock()


def _detect_backend() -> str:
    """检测可用的浏览器自动化后端（首次调用后缓存）"""
    global _BACKEND, _BACKEND_CHECKED
    with _BACKEND_LOCK:
        if _BACKEND_CHECKED:
            return _BACKEND
        _BACKEND_CHECKED = True
        # 优先 Playwright
        try:
            import playwright  # noqa: F401
            _BACKEND = "playwright"
            return _BACKEND
        except ImportError:
            pass
        # 备选 Selenium
        try:
            import selenium  # noqa: F401
            _BACKEND = "selenium"
            return _BACKEND
        except ImportError:
            pass
        _BACKEND = ""
        return ""


def get_install_hint() -> str:
    """返回安装提示信息"""
    return (
        "浏览器自动化后端未安装。\n"
        "推荐安装 Playwright：\n"
        "  pip install playwright\n"
        "  playwright install chromium\n\n"
        "或安装 Selenium（备选）：\n"
        "  pip install selenium\n"
        "  并下载对应浏览器驱动（如 chromedriver）"
    )


# ==================== 浏览器会话管理 ====================

class _BrowserSession:
    """浏览器会话 — 单例，懒启动，跨操作复用"""

    def __init__(self):
        self._lock = threading.Lock()
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._selenium_driver = None
        self._last_active: float = 0.0
        self._timeout: int = 30  # 默认超时（秒）

    # ---------- 通用接口 ----------

    def ensure_started(self) -> str:
        """确保浏览器已启动，返回后端类型；失败返回错误信息"""
        backend = _detect_backend()
        if not backend:
            return get_install_hint()
        if backend == "playwright":
            err = self._ensure_playwright()
            return err or "playwright"
        return self._ensure_selenium() or "selenium"

    def get_current_url(self) -> str:
        try:
            if self._page:
                return self._page.url
            if self._selenium_driver:
                return self._selenium_driver.current_url
        except Exception:
            pass
        return ""

    # ---------- Playwright ----------

    def _ensure_playwright(self) -> str:
        with self._lock:
            if self._page and not self._page.is_closed():
                self._last_active = time.time()
                return ""
            try:
                from playwright.sync_api import sync_playwright
            except ImportError:
                return get_install_hint()
            try:
                if self._playwright is None:
                    self._playwright = sync_playwright().start()
                if self._browser is None or not self._browser.is_connected():
                    self._browser = self._playwright.chromium.launch(
                        headless=True,
                        args=["--no-sandbox", "--disable-dev-shm-usage"],
                    )
                self._context = self._browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                )
                self._context.set_default_timeout(self._timeout * 1000)
                self._page = self._context.new_page()
                self._last_active = time.time()
                return ""
            except Exception as e:
                self._cleanup_playwright()
                return f"Playwright 启动失败: {e}\n提示：是否已运行 `playwright install chromium`？"

    def _cleanup_playwright(self):
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None

    # ---------- Selenium ----------

    def _ensure_selenium(self) -> str:
        with self._lock:
            if self._selenium_driver:
                try:
                    _ = self._selenium_driver.current_url
                    self._last_active = time.time()
                    return ""
                except Exception:
                    self._cleanup_selenium()
            try:
                from selenium import webdriver
                from selenium.webdriver.chrome.options import Options
                from selenium.webdriver.chrome.service import Service
            except ImportError:
                return get_install_hint()
            try:
                options = Options()
                options.add_argument("--headless=new")
                options.add_argument("--no-sandbox")
                options.add_argument("--disable-dev-shm-usage")
                options.add_argument("--window-size=1280,800")
                # 尝试自动查找驱动（Selenium 4.6+ 内置 Selenium Manager）
                self._selenium_driver = webdriver.Chrome(options=options)
                self._selenium_driver.set_page_load_timeout(self._timeout)
                self._last_active = time.time()
                return ""
            except Exception as e:
                self._cleanup_selenium()
                return (
                    f"Selenium 启动失败: {e}\n"
                    "提示：请确保已安装 Chrome 浏览器；Selenium 4.6+ 会自动下载驱动。"
                )

    def _cleanup_selenium(self):
        try:
            if self._selenium_driver:
                self._selenium_driver.quit()
        except Exception:
            pass
        self._selenium_driver = None

    # ---------- 关闭 ----------

    def close(self):
        self._cleanup_playwright()
        self._cleanup_selenium()


# 全局会话单例
_SESSION = _BrowserSession()


# ==================== 操作实现 ====================

def _emit_progress(progress_callback: Optional[Callable], step: str, status: str = "running", detail: str = ""):
    """统一上报进度（人性化设计：右侧面板实时显示操作步骤）"""
    if progress_callback is None:
        return
    try:
        progress_callback({
            "step": step,
            "status": status,   # running / success / failed
            "detail": detail,
            "timestamp": time.time(),
        })
    except Exception:
        pass


def _op_open(url: str, wait: str = "load", progress_callback: Optional[Callable] = None) -> SkillResult:
    _emit_progress(progress_callback, f"打开页面: {url}", "running")
    backend = _SESSION.ensure_started()
    if backend.startswith(("浏览器", "Playwright", "Selenium")) or "未安装" in backend or "失败" in backend:
        _emit_progress(progress_callback, "打开页面", "failed", backend)
        return SkillResult(success=False, error=backend, data={"backend": "none"})

    try:
        if backend == "playwright":
            wait_state = {
                "load": "load",
                "domcontentloaded": "domcontentloaded",
                "networkidle": "networkidle",
            }.get(wait, "load")
            _SESSION._page.goto(url, wait_until=wait_state)
        else:  # selenium
            _SESSION._selenium_driver.get(url)

        current_url = _SESSION.get_current_url()
        title = ""
        try:
            if backend == "playwright":
                title = _SESSION._page.title()
            else:
                title = _SESSION._selenium_driver.title
        except Exception:
            pass
        _emit_progress(progress_callback, "打开页面", "success", f"已加载: {title or current_url}")
        return SkillResult(
            success=True,
            output=f"✅ 已打开页面: {current_url}\n标题: {title}",
            data={"url": current_url, "title": title, "backend": backend},
        )
    except Exception as e:
        _emit_progress(progress_callback, "打开页面", "failed", str(e))
        return SkillResult(success=False, error=f"页面打开失败: {e}", data={"backend": backend})


def _op_screenshot(
    output_path: str = "",
    full_page: bool = True,
    selector: str = "",
    progress_callback: Optional[Callable] = None,
) -> SkillResult:
    _emit_progress(progress_callback, "截图", "running", f"full_page={full_page}")
    backend = _SESSION.ensure_started()
    if backend.startswith(("浏览器", "Playwright", "Selenium")) or "未安装" in backend or "失败" in backend:
        _emit_progress(progress_callback, "截图", "failed", backend)
        return SkillResult(success=False, error=backend)

    if not output_path:
        output_path = os.path.join(
            os.getcwd(), f"screenshot_{int(time.time())}.png"
        )
    if not os.path.isabs(output_path):
        output_path = os.path.join(os.getcwd(), output_path)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    try:
        if backend == "playwright":
            if selector:
                element = _SESSION._page.query_selector(selector)
                if not element:
                    _emit_progress(progress_callback, "截图", "failed", f"未找到元素: {selector}")
                    return SkillResult(success=False, error=f"未找到元素: {selector}")
                element.screenshot(path=output_path)
            else:
                _SESSION._page.screenshot(path=output_path, full_page=full_page)
        else:  # selenium
            from selenium.webdriver.common.by import By
            if selector:
                el = _SESSION._selenium_driver.find_element(By.CSS_SELECTOR, selector)
                el.screenshot(output_path)
            else:
                _SESSION._selenium_driver.save_screenshot(output_path)

        size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
        _emit_progress(progress_callback, "截图", "success", f"已保存: {output_path} ({size}B)")
        return SkillResult(
            success=True,
            output=f"✅ 截图已保存: {output_path}（{size} 字节）",
            data={"path": output_path, "size": size, "backend": backend},
        )
    except Exception as e:
        _emit_progress(progress_callback, "截图", "failed", str(e))
        return SkillResult(success=False, error=f"截图失败: {e}")


def _op_click(selector: str, wait: int = 5, progress_callback: Optional[Callable] = None) -> SkillResult:
    _emit_progress(progress_callback, f"点击元素: {selector}", "running")
    backend = _SESSION.ensure_started()
    if backend.startswith(("浏览器", "Playwright", "Selenium")) or "未安装" in backend or "失败" in backend:
        _emit_progress(progress_callback, "点击", "failed", backend)
        return SkillResult(success=False, error=backend)

    try:
        if backend == "playwright":
            _SESSION._page.wait_for_selector(selector, timeout=wait * 1000)
            _SESSION._page.click(selector)
        else:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            WebDriverWait(_SESSION._selenium_driver, wait).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
            ).click()
        _emit_progress(progress_callback, "点击元素", "success", selector)
        return SkillResult(
            success=True,
            output=f"✅ 已点击元素: {selector}",
            data={"selector": selector, "backend": backend},
        )
    except Exception as e:
        _emit_progress(progress_callback, "点击元素", "failed", str(e))
        return SkillResult(success=False, error=f"点击失败: {e}")


def _op_fill(selector: str, value: str, progress_callback: Optional[Callable] = None) -> SkillResult:
    _emit_progress(progress_callback, f"填写表单: {selector}", "running", f"value={value[:30]}")
    backend = _SESSION.ensure_started()
    if backend.startswith(("浏览器", "Playwright", "Selenium")) or "未安装" in backend or "失败" in backend:
        _emit_progress(progress_callback, "填写表单", "failed", backend)
        return SkillResult(success=False, error=backend)

    try:
        if backend == "playwright":
            _SESSION._page.fill(selector, value)
        else:
            from selenium.webdriver.common.by import By
            el = _SESSION._selenium_driver.find_element(By.CSS_SELECTOR, selector)
            el.clear()
            el.send_keys(value)
        _emit_progress(progress_callback, "填写表单", "success", selector)
        return SkillResult(
            success=True,
            output=f"✅ 已填写 '{value[:30]}...' 到 {selector}",
            data={"selector": selector, "value": value, "backend": backend},
        )
    except Exception as e:
        _emit_progress(progress_callback, "填写表单", "failed", str(e))
        return SkillResult(success=False, error=f"表单填写失败: {e}")


def _op_extract(
    selector: str = "",
    attribute: str = "",
    progress_callback: Optional[Callable] = None,
) -> SkillResult:
    _emit_progress(progress_callback, "提取文本", "running", selector or "全页")
    backend = _SESSION.ensure_started()
    if backend.startswith(("浏览器", "Playwright", "Selenium")) or "未安装" in backend or "失败" in backend:
        _emit_progress(progress_callback, "提取文本", "failed", backend)
        return SkillResult(success=False, error=backend)

    try:
        if backend == "playwright":
            if selector:
                el = _SESSION._page.query_selector(selector)
                if not el:
                    _emit_progress(progress_callback, "提取文本", "failed", f"未找到: {selector}")
                    return SkillResult(success=False, error=f"未找到元素: {selector}")
                text = el.get_attribute(attribute) if attribute else el.inner_text()
            else:
                text = _SESSION._page.inner_text("body")
        else:
            from selenium.webdriver.common.by import By
            if selector:
                el = _SESSION._selenium_driver.find_element(By.CSS_SELECTOR, selector)
                text = el.get_attribute(attribute) if attribute else el.text
            else:
                text = _SESSION._selenium_driver.find_element(By.TAG_NAME, "body").text

        text = text or ""
        preview = text[:500] + ("..." if len(text) > 500 else "")
        _emit_progress(progress_callback, "提取文本", "success", f"{len(text)} 字符")
        return SkillResult(
            success=True,
            output=f"✅ 提取到 {len(text)} 字符文本:\n{preview}",
            data={"text": text, "length": len(text), "backend": backend},
        )
    except Exception as e:
        _emit_progress(progress_callback, "提取文本", "failed", str(e))
        return SkillResult(success=False, error=f"文本提取失败: {e}")


def _op_scroll(
    x: int = 0,
    y: int = 800,
    selector: str = "",
    progress_callback: Optional[Callable] = None,
) -> SkillResult:
    _emit_progress(progress_callback, "滚动页面", "running", f"y={y}")
    backend = _SESSION.ensure_started()
    if backend.startswith(("浏览器", "Playwright", "Selenium")) or "未安装" in backend or "失败" in backend:
        _emit_progress(progress_callback, "滚动页面", "failed", backend)
        return SkillResult(success=False, error=backend)

    try:
        if backend == "playwright":
            if selector:
                _SESSION._page.eval_on_selector(
                    selector,
                    "(el, args) => el.scrollBy(args.x, args.y)",
                    {"x": x, "y": y},
                )
            else:
                _SESSION._page.evaluate(f"window.scrollBy({x}, {y})")
        else:
            script = f"window.scrollBy({x}, {y})"
            if selector:
                from selenium.webdriver.common.by import By
                el = _SESSION._selenium_driver.find_element(By.CSS_SELECTOR, selector)
                _SESSION._selenium_driver.execute_script(
                    "arguments[0].scrollBy(arguments[1], arguments[2]);", el, x, y
                )
            else:
                _SESSION._selenium_driver.execute_script(script)
        _emit_progress(progress_callback, "滚动页面", "success", f"y={y}")
        return SkillResult(
            success=True,
            output=f"✅ 已滚动 ({x}, {y})",
            data={"x": x, "y": y, "backend": backend},
        )
    except Exception as e:
        _emit_progress(progress_callback, "滚动页面", "failed", str(e))
        return SkillResult(success=False, error=f"滚动失败: {e}")


def _op_close(progress_callback: Optional[Callable] = None) -> SkillResult:
    _emit_progress(progress_callback, "关闭浏览器", "running")
    try:
        _SESSION.close()
        _emit_progress(progress_callback, "关闭浏览器", "success")
        return SkillResult(success=True, output="✅ 浏览器已关闭")
    except Exception as e:
        _emit_progress(progress_callback, "关闭浏览器", "failed", str(e))
        return SkillResult(success=False, error=f"关闭失败: {e}")


# ==================== 统一入口 ====================

# 进度回调注册表（供 UI 层订阅）
_PROGRESS_CALLBACKS: List[Callable] = []
_PROGRESS_LOCK = threading.Lock()


def set_progress_callback(cb: Callable):
    """注册全局进度回调（UI 层调用）"""
    global _PROGRESS_CALLBACKS
    with _PROGRESS_LOCK:
        _PROGRESS_CALLBACKS = [cb]


def _broadcast_progress(event: Dict[str, Any]):
    """广播进度事件到所有注册的回调"""
    with _PROGRESS_LOCK:
        cbs = list(_PROGRESS_CALLBACKS)
    for cb in cbs:
        try:
            cb(event)
        except Exception:
            pass


def _op_embed(
    url: str,
    width: str = "100%",
    height: str = "480px",
    progress_callback: Optional[Callable] = None,
) -> SkillResult:
    _emit_progress(progress_callback, "嵌入页面", "running", url)
    if not url:
        _emit_progress(progress_callback, "嵌入页面", "failed", "缺少URL")
        return SkillResult(success=False, error="embed 操作需要 url 参数")
    try:
        import html as html_mod
        escaped_url = html_mod.escape(url, quote=True)
        embed_html = (
            '<div class="web-embed">'
            '<div class="web-embed-bar">'
            '<span class="web-embed-url">' + escaped_url + '</span>'
            '<span class="web-embed-btn" onclick="window._callPython(\'webEmbedAction\',\'refresh:' + escaped_url + '\')">&#x21BB;</span>'
            '<span class="web-embed-btn" onclick="window._callPython(\'webEmbedAction\',\'screenshot:' + escaped_url + '\')">&#x1F4F7;</span>'
            '<span class="web-embed-btn" onclick="window._callPython(\'webEmbedAction\',\'extract:' + escaped_url + '\')">&#x1F4CB;</span>'
            '</div>'
            '<iframe class="web-embed-frame" src="' + escaped_url + '" '
            'sandbox="allow-scripts allow-same-origin allow-forms allow-popups" '
            'style="width:' + width + ';height:' + height + ';" '
            'loading="lazy" referrerpolicy="no-referrer"></iframe>'
            '</div>'
        )
        import base64
        encoded = base64.b64encode(embed_html.encode("utf-8")).decode("ascii")
        _emit_progress(progress_callback, "嵌入页面", "success", url)
        return SkillResult(
            success=True,
            output="__WEB_EMBED__:" + encoded,
            data={"url": url, "embed": True},
        )
    except Exception as e:
        _emit_progress(progress_callback, "嵌入页面", "failed", str(e))
        return SkillResult(success=False, error=f"嵌入失败: {e}")


def _op_screenshot_b64(
    url: str = "",
    progress_callback: Optional[Callable] = None,
) -> SkillResult:
    if url:
        open_result = _op_open(url, progress_callback=progress_callback)
        if not open_result.success:
            return open_result
    backend = _detect_backend()
    if not backend:
        return SkillResult(success=False, error=get_install_hint())
    try:
        if backend == "playwright":
            _SESSION.ensure_started()
            b64 = _SESSION._page.screenshot(type="png", full_page=False)
            if isinstance(b64, bytes):
                b64_str = base64.b64encode(b64).decode("ascii")
            else:
                b64_str = str(b64)
        else:
            _SESSION.ensure_started()
            png = _SESSION._selenium_driver.get_screenshot_as_png()
            b64_str = base64.b64encode(png).decode("ascii")
        _emit_progress(progress_callback, "截图(base64)", "success")
        return SkillResult(
            success=True,
            output="__IMAGE__:data:image/png;base64," + b64_str,
            data={"format": "png_base64", "backend": backend},
        )
    except Exception as e:
        _emit_progress(progress_callback, "截图(base64)", "failed", str(e))
        return SkillResult(success=False, error=f"截图失败: {e}")


def _op_extract_url(
    url: str,
    selector: str = "",
    progress_callback: Optional[Callable] = None,
) -> SkillResult:
    if url:
        open_result = _op_open(url, wait="domcontentloaded", progress_callback=progress_callback)
        if not open_result.success:
            return open_result
    return _op_extract(selector=selector, progress_callback=progress_callback)


def execute(
    action: str = "open",
    url: str = "",
    selector: str = "",
    value: str = "",
    output_path: str = "",
    attribute: str = "",
    full_page: bool = True,
    wait: str = "load",
    embed: bool = False,
    width: str = "100%",
    height: str = "480px",
    x: int = 0,
    y: int = 800,
    timeout: int = 30,
) -> SkillResult:
    """浏览器自动化统一入口

    Args:
        action: 操作类型 open/screenshot/click/fill/extract/scroll/close/embed/screenshot_b64/extract_url
        url:    open/embed 操作的 URL
        selector: click/fill/extract 的 CSS 选择器
        value:  fill 的值
        output_path: screenshot 保存路径
        attribute: extract 提取属性（默认提取文本）
        full_page: screenshot 是否全页
        wait:   open 等待策略 load/domcontentloaded/networkidle
        embed:  open 时是否返回可交互iframe嵌入
        width:  embed 宽度
        height: embed 高度
        x, y:   scroll 偏移
        timeout: 操作超时（秒）
    """
    progress_cb = _broadcast_progress
    _SESSION._timeout = max(5, min(timeout, 120))

    action = (action or "").lower().strip()
    if action == "open":
        if not url:
            return SkillResult(success=False, error="open 操作需要 url 参数")
        if embed:
            return _op_embed(url, width=width, height=height, progress_callback=progress_cb)
        return _op_open(url, wait=wait, progress_callback=progress_cb)
    if action == "embed":
        return _op_embed(url, width=width, height=height, progress_callback=progress_cb)
    if action == "screenshot":
        return _op_screenshot(output_path=output_path, full_page=full_page, selector=selector, progress_callback=progress_cb)
    if action == "screenshot_b64":
        return _op_screenshot_b64(url=url, progress_callback=progress_cb)
    if action == "click":
        if not selector:
            return SkillResult(success=False, error="click 操作需要 selector 参数")
        return _op_click(selector, wait=min(timeout, 10), progress_callback=progress_cb)
    if action == "fill":
        if not selector:
            return SkillResult(success=False, error="fill 操作需要 selector 参数")
        return _op_fill(selector, value, progress_callback=progress_cb)
    if action == "extract":
        return _op_extract(selector=selector, attribute=attribute, progress_callback=progress_cb)
    if action == "extract_url":
        return _op_extract_url(url=url, selector=selector, progress_callback=progress_cb)
    if action == "scroll":
        return _op_scroll(x=x, y=y, selector=selector, progress_callback=progress_cb)
    if action == "close":
        return _op_close(progress_callback=progress_cb)
    return SkillResult(success=False, error=f"未知 action: {action}（支持: open/embed/screenshot/screenshot_b64/click/fill/extract/extract_url/scroll/close）")


def register(registry) -> None:
    """向 SkillsRegistry 注册 browser_automation Skill"""
    registry.register(SkillDef(
        name="browser_automation",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "操作类型",
                    "enum": ["open", "embed", "screenshot", "screenshot_b64", "click", "fill", "extract", "extract_url", "scroll", "close"],
                },
                "url": {"type": "string", "description": "open/embed 操作的页面 URL"},
                "selector": {"type": "string", "description": "CSS 选择器（click/fill/extract/scroll 可选）"},
                "value": {"type": "string", "description": "fill 操作的输入值"},
                "output_path": {"type": "string", "description": "screenshot 保存路径（默认当前目录 screenshot_<时间戳>.png）"},
                "attribute": {"type": "string", "description": "extract 提取属性名（默认提取 innerText）"},
                "full_page": {"type": "boolean", "description": "screenshot 是否全页截图", "default": True},
                "wait": {
                    "type": "string",
                    "description": "open 等待策略",
                    "enum": ["load", "domcontentloaded", "networkidle"],
                    "default": "load",
                },
                "embed": {"type": "boolean", "description": "open 时是否返回可交互iframe嵌入", "default": False},
                "width": {"type": "string", "description": "embed 宽度", "default": "100%"},
                "height": {"type": "string", "description": "embed 高度", "default": "480px"},
                "x": {"type": "integer", "description": "scroll 水平偏移", "default": 0},
                "y": {"type": "integer", "description": "scroll 垂直偏移", "default": 800},
                "timeout": {"type": "integer", "description": "操作超时（秒，5-120）", "default": 30},
            },
            "required": ["action"],
        },
        handler=execute,
        category=METADATA["category"],
        requires_confirm=False,
        timeout=120,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA


def is_available() -> bool:
    """检测浏览器自动化后端是否可用"""
    return _detect_backend() != ""


def get_backend() -> str:
    """获取当前后端类型（playwright / selenium / 空字符串）"""
    return _detect_backend()
