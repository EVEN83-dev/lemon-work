# -*- coding: utf-8 -*-
"""
UI Verifier -- 多模态 UI 验证闭环
===================================
生成前端代码后自动截图，用多模态模型验证渲染正确性。

流程：
  capture_screenshot() -> base64 PNG -> vision_chat() -> 判断 pass/fail
  verify_and_fix() -> 验证失败时自动修复并重验证（最多 3 轮）
"""

import base64
import json
import logging
import os
import tempfile
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_UI_VERIFY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "ui_verify"
)

_VERIFY_PROMPT = (
    "你是一个 UI 验证助手。根据用户期望和实际渲染截图，判断界面是否正确。\n\n"
    "用户期望:\n{expectation}\n\n"
    "请判断:\n"
    "1) 布局是否符合期望\n"
    "2) 有无明显错误（空白页/内容溢出/样式丢失/乱码）\n"
    "3) 文本/按钮/表单等元素是否正确显示\n\n"
    "严格回复 JSON（不要有其他文字）:\n"
    '{{"pass": true/false, "issues": ["问题1", ...], "score": 0-100}}'
)


def _ensure_dir():
    os.makedirs(_UI_VERIFY_DIR, exist_ok=True)


def _screenshot_path(tag: str = "") -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    tag_part = f"_{tag}" if tag else ""
    return os.path.join(_UI_VERIFY_DIR, f"screenshot_{ts}{tag_part}.png")


class UIVerifier:
    """多模态 UI 验证器"""

    def __init__(self, engine_manager=None):
        self._engine_manager = engine_manager

    def _get_engine_manager(self):
        if self._engine_manager is not None:
            return self._engine_manager
        from shared.engine_manager import get_engine_manager
        self._engine_manager = get_engine_manager()
        return self._engine_manager

    def capture_screenshot(self, url_or_html: str, timeout: int = 30) -> Optional[str]:
        """截图并返回 PNG 文件路径

        Args:
            url_or_html: http(s) URL / HTML 字符串 / 本地 HTML 文件路径
            timeout: 截图超时秒数

        Returns:
            PNG 文件路径，失败返回 None
        """
        _ensure_dir()
        try:
            from core.screenshot_tool import capture, capture_html
        except ImportError:
            logger.info("[UIVerifier] screenshot_tool 不可用，跳过截图")
            return None

        output = _screenshot_path("capture")

        if url_or_html.startswith(("http://", "https://")):
            ok = capture(url_or_html, output)
            return output if ok else None

        if os.path.isfile(url_or_html):
            ok = capture_html(url_or_html, output)
            return output if ok else None

        if "<" in url_or_html and ">" in url_or_html:
            tmp_dir = os.path.join(_UI_VERIFY_DIR, "tmp")
            os.makedirs(tmp_dir, exist_ok=True)
            tmp_html = os.path.join(tmp_dir, f"verify_{int(time.time())}.html")
            try:
                with open(tmp_html, "w", encoding="utf-8") as f:
                    f.write(url_or_html)
                ok = capture_html(tmp_html, output)
                return output if ok else None
            except Exception as e:
                logger.warning(f"[UIVerifier] 写临时 HTML 失败: {e}")
                return None

        logger.warning(f"[UIVerifier] 无法识别输入类型: {url_or_html[:80]}")
        return None

    def verify(self, html_path_or_url: str, expectation: str,
               model: str = "") -> Dict:
        """验证 UI 渲染是否正确

        Args:
            html_path_or_url: HTML 文件路径 / URL / HTML 字符串
            expectation: 用户对界面的期望描述
            model: 多模态模型名（留空自动检测）

        Returns:
            {"pass": bool, "issues": List[str], "score": int, "screenshot": str}
        """
        screenshot_path = self.capture_screenshot(html_path_or_url)
        if not screenshot_path:
            return {
                "pass": False,
                "issues": ["截图失败（playwright 不可用或页面无法加载）"],
                "score": 0,
                "screenshot": "",
            }

        image_b64 = self._load_image_base64(screenshot_path)
        if not image_b64:
            return {
                "pass": False,
                "issues": ["截图文件读取失败"],
                "score": 0,
                "screenshot": screenshot_path,
            }

        prompt = _VERIFY_PROMPT.format(expectation=expectation[:1000])

        try:
            engine_mgr = self._get_engine_manager()
            if hasattr(engine_mgr, "vision_chat"):
                response = engine_mgr.vision_chat(
                    prompt, [screenshot_path], model=model
                )
            else:
                response = self._fallback_vision_chat(prompt, image_b64, model)

            result = self._parse_verify_response(response)
            result["screenshot"] = screenshot_path
            return result

        except Exception as e:
            logger.warning(f"[UIVerifier] vision_chat 失败: {e}")
            return {
                "pass": False,
                "issues": [f"多模态验证失败: {e}"],
                "score": 0,
                "screenshot": screenshot_path,
            }

    def verify_and_fix(self, html: str, expectation: str,
                       max_fix_rounds: int = 3) -> Dict:
        """验证 + 自动修复闭环

        流程: verify -> fail -> agent_chat 修复 -> re-verify -> ...
        最多 max_fix_rounds 轮修复。

        Returns:
            {"html": str, "pass": bool, "score": int, "iterations": int,
             "issues": List[str], "screenshot": str}
        """
        current_html = html
        last_result = None

        for round_idx in range(max_fix_rounds + 1):
            verify_result = self.verify(current_html, expectation)
            last_result = verify_result

            if verify_result.get("pass"):
                logger.info(f"[UIVerifier] 第 {round_idx + 1} 轮验证通过, score={verify_result.get('score')}")
                return {
                    "html": current_html,
                    "pass": True,
                    "score": verify_result.get("score", 100),
                    "iterations": round_idx + 1,
                    "issues": [],
                    "screenshot": verify_result.get("screenshot", ""),
                }

            issues = verify_result.get("issues", [])
            if round_idx >= max_fix_rounds:
                logger.info(f"[UIVerifier] 达到最大修复轮数 {max_fix_rounds}，停止")
                break

            logger.info(f"[UIVerifier] 第 {round_idx + 1} 轮验证失败: {issues}")

            fix_prompt = (
                f"以下 HTML 渲染后存在问题，请修复:\n\n"
                f"期望效果: {expectation}\n\n"
                f"问题列表: {'; '.join(issues)}\n\n"
                f"原始 HTML:\n```html\n{current_html[:3000]}\n```\n\n"
                f"请输出修复后的完整 HTML（不要解释，只输出 HTML 代码）:"
            )

            try:
                engine_mgr = self._get_engine_manager()
                fix_result = engine_mgr.agent_chat(
                    fix_prompt,
                    engine="ollama",
                    max_iterations=5,
                )
                fixed = fix_result.get("content", "")
                if fixed and "<" in fixed and ">" in fixed:
                    current_html = self._extract_html(fixed)
                else:
                    logger.info("[UIVerifier] 修复输出不含 HTML，保持原样")
            except Exception as e:
                logger.warning(f"[UIVerifier] 修复异常: {e}")

        return {
            "html": current_html,
            "pass": False,
            "score": last_result.get("score", 0) if last_result else 0,
            "iterations": max_fix_rounds + 1,
            "issues": last_result.get("issues", ["验证未通过"]) if last_result else ["验证未通过"],
            "screenshot": last_result.get("screenshot", "") if last_result else "",
        }

    def _fallback_vision_chat(self, prompt: str, image_b64: str,
                              model: str = "") -> str:
        """降级方案: 用 engine_manager.chat + images 参数"""
        engine_mgr = self._get_engine_manager()
        if not engine_mgr._engines:
            engine_mgr.initialize()

        messages = [
            {"role": "user", "content": prompt, "images": [image_b64]}
        ]

        engine = engine_mgr._engines.get("ollama")
        if not engine:
            for e in engine_mgr._engines.values():
                engine = e
                break
        if not engine:
            return '{"pass": false, "issues": ["无可用引擎"], "score": 0}'

        try:
            return engine.chat(messages)
        except Exception as e:
            logger.warning(f"[UIVerifier] fallback chat 失败: {e}")
            return '{"pass": false, "issues": ["chat调用失败"], "score": 0}'

    @staticmethod
    def _load_image_base64(path: str) -> str:
        try:
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            logger.warning(f"[UIVerifier] 读取截图失败: {e}")
            return ""

    @staticmethod
    def _parse_verify_response(response: str) -> Dict:
        try:
            text = response.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1])
            result = json.loads(text)
            if "pass" in result:
                return {
                    "pass": bool(result["pass"]),
                    "issues": result.get("issues", []),
                    "score": result.get("score", 0),
                }
        except (json.JSONDecodeError, ValueError):
            pass

        lower = response.lower()
        if any(w in lower for w in ["true", "通过", "正确", "符合"]):
            return {"pass": True, "issues": [], "score": 80}
        return {"pass": False, "issues": ["无法解析验证结果"], "score": 0}

    @staticmethod
    def _extract_html(text: str) -> str:
        if "```html" in text:
            parts = text.split("```html")
            if len(parts) > 1:
                after = parts[1].split("```")
                if after:
                    return after[0].strip()
        if "```" in text:
            parts = text.split("```")
            if len(parts) > 1:
                candidate = parts[1].strip()
                if candidate.startswith("<"):
                    return candidate
        if text.strip().startswith("<"):
            return text.strip()
        return text
