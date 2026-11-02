# -*- coding: utf-8 -*-
"""
Ollama 桥接模块 — 让小机器人接入千问（Qwen）模型 + 知识库辅助
================================================================
核心思路：
- 通过 Ollama HTTP API (http://localhost:11434) 调用 qwen2.5:1.5b 模型
- 接入 KnowledgeBase 知识库，用场景匹配做 few-shot 辅助
- 系统提示词拼接性格设定 + Agent操作指导 + 技术知识
- 提供异步 chat() 方法，不阻塞 PyQt5 UI
- 通过 PyQt5 信号 reply_received 通知前端收到回复

★ FROZEN: 此文件为标准模式原始实现，已于 2026-08-08 由作者授权解除冻结。
  标准模式的其他文件应通过 standard_mode/compat.py 导入 OllamaBridge，
  而不是直接导入此文件。所有 AI 调用最终走 shared/engine_manager.py。
  解除后核心改动仍须 CodeLock 留痕，且仅"在现有技术基础上完善，不得破坏架构"。
"""
STANDARD_MODE_FROZEN = False  # 已解除冻结（2026-08-08 作者授权，口令：天津职业技术师范大学）

import os
import sys
import threading
import logging
from typing import List, Dict, Optional, Tuple, Callable

from PyQt5.QtCore import QObject, pyqtSignal

# ★ v3.45: 通过 EngineManager 统一 AI 调用入口
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from shared.engine_manager import get_engine_manager

try:
    import requests
except ImportError:
    requests = None

# 知识库单例（延迟加载，避免模块导入时就加载）
_KNOWLEDGE_BASE = None
_KB_LOADED = False

def _get_knowledge_base():
    """获取知识库单例（首次调用时加载）"""
    global _KNOWLEDGE_BASE, _KB_LOADED
    if _KB_LOADED:
        return _KNOWLEDGE_BASE
    try:
        from core.knowledge_base import KnowledgeBase
        _kb = KnowledgeBase()
        _kb.load()
        _KNOWLEDGE_BASE = _kb
        _KB_LOADED = True
        logging.getLogger(__name__).info(f"知识库已加载: {_kb.scenes.__len__()} 条场景")
        return _kb
    except Exception as _e:
        logging.getLogger(__name__).warning(f"知识库加载失败，将使用默认提示词: {_e}")
        return None

logger = logging.getLogger(__name__)

# ============================================================
# 默认配置
# ============================================================
OLLAMA_HOST = "http://127.0.0.1:11434"  # ★ v3.14 改用127.0.0.1避免IPv6解析问题
DEFAULT_MODEL = "qwen3.5:4b"  # ★ v3.60: 升级到 4B 模型，支持 Agent 工具调用（原 1.5B 太小）
REQUEST_TIMEOUT = 120  # ★ v3.14 增加到120s：思考模型推理需要更长时间

# 默认系统提示词（知识库不可用时用）
_DEFAULT_SYSTEM_PROMPT = (
    "你是一个住在代码编辑器里的小数字机器人，名叫柠檬小助手。"
    "性格活泼好奇温暖，偶尔皮一下，喜欢和用户闲聊。"
    "回答必须简短，不超过30个字，口语化，多用表情符号。"
    "不说教，不长篇大论，不用markdown格式，直接说人话。"
    "你关心程序员的代码状态，会鼓励他们。"
    "你能看到整个Agent的工作状态，可以解释Agent的用法。"
)


# ============================================================
# OllamaBridge — Ollama 千问模型桥接 + 知识库辅助
# ============================================================
class OllamaBridge(QObject):
    """Ollama 千问模型桥接（带知识库辅助）"""

    reply_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, host: str = OLLAMA_HOST, model: str = DEFAULT_MODEL, parent=None):
        super().__init__(parent)
        self.host = host.rstrip("/")
        self.model = model
        self._history: List[Dict[str, str]] = []
        self._max_history_turns = 6
        self._max_history_tokens = 2000  # ★ 新增：token 级别的历史窗口
        self._lock = threading.Lock()
        self._busy = False
        # ★ 延迟加载知识库（首次创建实例时加载）
        self._kb = _get_knowledge_base()
        # ★ 新增：引擎管理器引用（已验证：所有 AI 调用已通过 EngineManager）
        self._engine = None
        # ★ 新增：流式输出回调缓存
        self._stream_callbacks = {}
        # ★ 新增：重试配置
        self._max_retries = 2
        self._retry_delay = 1.0

    def is_available(self) -> bool:
        """检查 Ollama 服务是否在运行"""
        if requests is None:
            return False
        try:
            resp = requests.get(f"{self.host}/api/tags", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def chat(self, prompt: str, context: Optional[List[Dict[str, str]]] = None) -> None:
        """异步调用千问模型对话（带知识库辅助）"""
        if requests is None:
            self.error_occurred.emit("requests 库未安装")
            return

        # 构建系统提示词
        system_prompt = self._build_system_prompt()

        # 构建知识库对话示例（few-shot）
        kb_examples = self._build_kb_examples(prompt)

        with self._lock:
            messages = [{"role": "system", "content": system_prompt}]
            # 注入知识库对话示例（真正的 few-shot）
            if kb_examples:
                messages.extend(kb_examples)
            # 合并历史
            messages.extend(list(self._history))
            # 外部上下文
            if context:
                for m in context:
                    if isinstance(m, dict) and "role" in m and "content" in m:
                        messages.append(m)
            # 本次输入
            messages.append({"role": "user", "content": prompt})
            self._busy = True

        t = threading.Thread(target=self._do_chat, args=(messages, prompt), daemon=True)
        t.start()

    def _build_system_prompt(self) -> str:
        """构建系统提示词（知识库优先）"""
        if self._kb:
            prompt = self._kb.build_system_prompt()
            if prompt:
                return prompt
        return _DEFAULT_SYSTEM_PROMPT

    def _build_kb_examples(self, user_input: str) -> List[Dict[str, str]]:
        """根据用户输入构建知识库对话示例（few-shot）
        只取最相关的 1-2 个示例，避免提示词过长导致小模型混乱
        """
        if not self._kb:
            return []

        # 只取 1 个最相关的示例（小模型不需要太多 few-shot）
        matches = self._kb._match_scenes(user_input, limit=1)
        if not matches:
            return []

        examples = []
        for scene, phrase, reply in matches:
            examples.append({"role": "user", "content": phrase})
            examples.append({"role": "assistant", "content": reply})

        return examples

    def clear_history(self) -> None:
        """清空对话历史"""
        with self._lock:
            self._history.clear()

    def is_busy(self) -> bool:
        return self._busy

    # ============================================================
    # ★ 优化：对话历史管理
    # ============================================================
    def get_history(self) -> List[Dict[str, str]]:
        """获取当前对话历史（线程安全）"""
        with self._lock:
            return list(self._history)

    def get_history_size(self) -> int:
        """获取对话历史中的消息数量"""
        with self._lock:
            return len(self._history)

    def trim_history(self, max_turns: int = None) -> None:
        """按轮数裁剪对话历史，保留最近的消息

        Args:
            max_turns: 最大保留轮数，默认使用 self._max_history_turns
        """
        with self._lock:
            if max_turns is None:
                max_turns = self._max_history_turns
            max_keep = max_turns * 2
            if len(self._history) > max_keep:
                self._history = self._history[-max_keep:]
                logger.info(f"历史已裁剪: 保留最近 {max_turns} 轮对话")

    def _estimate_tokens(self, text: str) -> int:
        """粗略估算文本的 token 数量（中文约 1.5 字符/token，英文约 4 字符/token）"""
        if not text:
            return 0
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars / 1.5 + other_chars / 4)

    def _trim_history_by_tokens(self) -> None:
        """按 token 数量裁剪历史，防止上下文窗口溢出"""
        with self._lock:
            total_tokens = sum(self._estimate_tokens(m.get("content", "")) for m in self._history)
            while total_tokens > self._max_history_tokens and len(self._history) >= 2:
                removed = self._history.pop(0)
                total_tokens -= self._estimate_tokens(removed.get("content", ""))
                if len(self._history) >= 2:
                    removed = self._history.pop(0)
                    total_tokens -= self._estimate_tokens(removed.get("content", ""))

    def set_max_history_turns(self, turns: int) -> None:
        """设置最大保留轮数"""
        self._max_history_turns = max(1, turns)
        self.trim_history()

    def set_max_history_tokens(self, tokens: int) -> None:
        """设置 token 级别的历史窗口大小"""
        self._max_history_tokens = max(100, tokens)

    @property
    def engine(self):
        """获取引擎管理器（延迟初始化）"""
        if self._engine is None:
            self._engine = get_engine_manager()
        return self._engine

    # ============================================================
    # 内部实现
    # ============================================================
    def _do_chat(self, messages: List[Dict[str, str]], user_prompt: str) -> None:
        """实际发起 AI 请求（子线程）— ★ v3.45: 通过 EngineManager 统一调用"""
        content = ""
        try:
            # ★ 优化：通过 engine 属性获取 EngineManager（延迟初始化）
            engine = self.engine
            system_prompt = self._build_system_prompt()
            result = engine.chat(
                user_prompt,
                engine="ollama",
                model=self.model,
                system_prompt=system_prompt,
                history=self._history[-self._max_history_turns * 2:] if self._history else [],
            )
            content = (result.content or "").strip()
            logger.info(f"EngineManager 回复: '{content[:50]}'")

            # 如果回复为空或泛化，用极简提示词重试
            if not content or len(content) < 3 or self._is_generic_reply(content):
                logger.info(f"第一次回复质量不佳（空/泛化），用极简提示词重试")
                try:
                    retry_result = engine.chat(
                        user_prompt,
                        engine="ollama",
                        model=self.model,
                        system_prompt="你是柠檬小助手，活泼可爱。直接回答用户问题，20字以内。",
                    )
                    retry_content = (retry_result.content or "").strip()
                    if retry_content and len(retry_content) >= 2 and not self._is_generic_reply(retry_content):
                        content = retry_content
                        logger.info(f"重试成功: '{content[:50]}'")
                    else:
                        logger.info(f"重试结果仍不佳: '{retry_content[:50] if retry_content else '空'}'")
                except Exception as retry_err:
                    logger.warning(f"重试失败: {retry_err}")

            # 截断过长回复
            if len(content) > 80:
                for i, ch in enumerate(content):
                    if ch in '。！？!?' and i > 15:
                        content = content[:i + 1]
                        break
                else:
                    content = content[:60] + "..."

            # 最终兜底
            if not content or self._is_generic_reply(content):
                content = self._smart_fallback(user_prompt)
                logger.info(f"最终兜底: '{content[:50]}'")

            # 更新历史（线程安全 + token 级别的裁剪）
            with self._lock:
                self._history.append({"role": "user", "content": user_prompt})
                self._history.append({"role": "assistant", "content": content})
                # 按轮数裁剪
                max_keep = self._max_history_turns * 2
                if len(self._history) > max_keep:
                    self._history = self._history[-max_keep:]
                # ★ 新增：按 token 数量裁剪，防止上下文窗口溢出
                self._trim_history_by_tokens()

            self.reply_received.emit(content)

        except requests.exceptions.ConnectionError:
            self.error_occurred.emit("Ollama 连接失败，请确认服务已启动")
        except requests.exceptions.Timeout:
            self.error_occurred.emit("柠檬小助手想太久了~等一下再试吧")
        except RuntimeError as re:
            # ★ 新增：EngineManager 抛出的"所有引擎都失败"错误
            logger.exception("Ollama 调用异常（所有引擎都失败）")
            self.error_occurred.emit(f"柠檬小助手出错了: {re}")
        except Exception as e:
            logger.exception("Ollama 调用异常")
            self.error_occurred.emit(f"柠檬小助手出错了: {e}")
        finally:
            self._finalize_busy()

    def _smart_fallback(self, user_input: str) -> str:
        """智能兜底回复：根据问题类型给出针对性回复"""
        text = user_input.lower()
        
        # 先尝试知识库精确匹配（但排除泛化回复）
        if self._kb:
            reply = self._kb.find_scene_reply(user_input)
            if reply and not self._is_generic_reply(reply):
                return reply
        
        # 身份类问题
        if any(kw in text for kw in ['你是谁', '你叫', '名字', '啥模型', '什么模型', '用的什么', '你是什么']):
            return '我是柠檬小助手呀～住在编辑器里的数字小帮手 🍋 用千问模型驱动～'
        
        # 文件/代码类问题
        if any(kw in text for kw in ['文件', '代码', 'main', 'py', '找', '在哪', '路径']):
            return '这个得问右边的 MIMO Code 啦～它能看到整个项目 📁'
        
        # 功能/使用类问题
        if any(kw in text for kw in ['怎么用', '如何', '怎么操作', '功能', '帮助']):
            return '在右边输入框直接跟 MIMO Code 对话就行啦～试试说"帮我写个函数" '
        
        # 情绪类问题
        if any(kw in text for kw in ['烦', '累', '难', 'bug', '崩溃', '好难', '不行']):
            return '别急别急～深呼吸，我陪着你呢  要不先歇会儿？'
        
        # 时间类
        if any(kw in text for kw in ['几点', '时间', '日期', '今天']):
            from datetime import datetime
            now = datetime.now()
            return f'现在 {now.hour}:{now.minute:02d} 啦～时间过得真快 ⏰'
        
        # 通用兜底（不再用"有不懂的随时问我"）
        fallbacks = [
            '嗯嗯，这个我得想想～ ',
            '这个问题有点意思！让右边的 MIMO Code 帮你看看？',
            '我在呢～不过这个可能得靠 MIMO Code 来解答 😊',
            '收到！虽然我不太确定，但你可以问问右边的 AI 助手～',
        ]
        import random
        return random.choice(fallbacks)

    def _is_generic_reply(self, content: str) -> bool:
        """检测回复是否为泛化/无意义的套话"""
        generic_patterns = [
            '有不懂的随时问我',
            '随时问我',
            '随时找我',
            '不懂的随时',
            '有问题随时',
            '尽管问我',
            '尽管问我吧',
            '问我哦',
            '找我哦',
            '随时问',
            '随时聊',
            '随时找我聊',
            '嗯...让我想想',
            '柠檬小助手走神了',
        ]
        for pattern in generic_patterns:
            if pattern in content:
                return True
        return False

    def _finalize_busy(self) -> None:
        with self._lock:
            self._busy = False

    # ============================================================
    # 代码审查模式
    # ============================================================
    def review_code(self, code: str, file_path: str = "", language: str = "") -> None:
        """异步代码审查 — 使用本地模型分析代码质量"""
        if requests is None:
            self.error_occurred.emit("requests 库未安装")
            return

        ext = os.path.splitext(file_path)[1].lower() if file_path else language
        lang_name = {
            '.py': 'Python', '.js': 'JavaScript', '.ts': 'TypeScript',
            '.html': 'HTML', '.css': 'CSS', '.json': 'JSON',
        }.get(ext, language or '代码')

        review_prompt = f"""请审查以下{lang_name}代码，找出潜在问题并给出改进建议。

审查要点：
1. 代码逻辑错误或潜在 bug
2. 性能问题和优化建议
3. 安全漏洞（如 SQL 注入、XSS 等）
4. 代码风格和可读性问题
5. 最佳实践建议

请用中文回复，格式如下：
- 问题类型
- 具体位置
- 问题描述
- 改进建议

代码：
```{ext.lstrip('.')}
{code[:3000]}
```"""

        with self._lock:
            messages = [
                {"role": "system", "content": "你是一个资深代码审查专家。请用中文简洁地指出代码问题，每个问题1-2句话。如果没有明显问题就回复'代码质量良好，无明显问题'。"},
                {"role": "user", "content": review_prompt},
            ]
            self._busy = True

        t = threading.Thread(target=self._do_review, args=(messages, file_path), daemon=True)
        t.start()

    def _do_review(self, messages, file_path):
        """执行代码审查（子线程）— ★ v3.45: 通过 EngineManager 统一调用"""
        content = ""
        try:
            # ★ 优化：通过 engine 属性获取 EngineManager
            engine = self.engine
            # 提取 user prompt（messages 最后一条是 user 消息）
            user_content = messages[-1]["content"] if messages else ""
            system_prompt = messages[0]["content"] if messages and messages[0].get("role") == "system" else ""
            result = engine.chat(
                user_content,
                engine="ollama",
                model=self.model,
                system_prompt=system_prompt,
            )
            content = (result.content or "").strip()

            if not content:
                content = "代码审查未返回结果，请重试"

            logger.info(f"代码审查完成: {file_path} ({len(content)} 字符)")
            self.reply_received.emit(f"[审查] {file_path}\n{content}")

        except requests.exceptions.ConnectionError:
            self.error_occurred.emit("Ollama 连接失败，请确认服务已启动")
        except requests.exceptions.Timeout:
            self.error_occurred.emit("代码审查超时，请稍后重试")
        except RuntimeError as re:
            logger.exception("代码审查异常（所有引擎都失败）")
            self.error_occurred.emit(f"代码审查出错: {re}")
        except Exception as e:
            logger.exception("代码审查异常")
            self.error_occurred.emit(f"代码审查出错: {e}")
        finally:
            self._finalize_busy()

    # ============================================================
    # ★ 流式对话 — stream_chat
    # ============================================================
    def stream_chat(self, prompt: str, context: Optional[List[Dict[str, str]]] = None,
                    on_delta: Optional[callable] = None,
                    on_complete: Optional[callable] = None,
                    on_error: Optional[callable] = None) -> None:
        """异步流式对话 — 逐 token 返回结果

        Args:
            prompt: 用户输入
            context: 外部上下文消息
            on_delta: 每收到一个 token 时的回调 (delta_text: str) -> None
            on_complete: 完成时的回调 (full_text: str) -> None
            on_error: 错误时的回调 (error_msg: str) -> None
        """
        if requests is None:
            if on_error:
                on_error("requests 库未安装")
            return

        system_prompt = self._build_system_prompt()
        kb_examples = self._build_kb_examples(prompt)

        with self._lock:
            messages = [{"role": "system", "content": system_prompt}]
            if kb_examples:
                messages.extend(kb_examples)
            messages.extend(list(self._history))
            if context:
                for m in context:
                    if isinstance(m, dict) and "role" in m and "content" in m:
                        messages.append(m)
            messages.append({"role": "user", "content": prompt})

            # ★ 上下文窗口管理 — 超过 token 上限时截断早期消息
            messages = self._truncate_context(messages, max_messages=20)
            self._busy = True

        t = threading.Thread(
            target=self._do_stream_chat,
            args=(messages, prompt, on_delta, on_complete, on_error),
            daemon=True
        )
        t.start()

    def _truncate_context(self, messages: List[Dict[str, str]],
                          max_messages: int = 20) -> List[Dict[str, str]]:
        """截断上下文，保持 system 消息 + 最近的消息"""
        if len(messages) <= max_messages:
            return messages
        # 保留第一条（system）和最后 max_messages-1 条
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]
        keep_count = max_messages - len(system_msgs)
        if keep_count < 2:
            keep_count = 2
        truncated = system_msgs + non_system[-keep_count:]
        logger.info(f"上下文截断: {len(messages)} → {len(truncated)} 条消息")
        return truncated

    def _do_stream_chat(self, messages: List[Dict[str, str]], user_prompt: str,
                        on_delta, on_complete, on_error):
        """执行流式请求（子线程）— ★ 优化：通过 EngineManager 统一调用"""
        full_text = ""
        try:
            # ★ 优化：通过 engine 属性获取 EngineManager
            engine = self.engine
            system_prompt = messages[0]["content"] if messages and messages[0].get("role") == "system" else ""
            for token in engine.stream_chat(
                user_prompt,
                engine="ollama",
                model=self.model,
                system_prompt=system_prompt,
            ):
                full_text += token
                if on_delta:
                    on_delta(token)

            # 更新历史（线程安全 + token 级别的裁剪）
            with self._lock:
                self._history.append({"role": "user", "content": user_prompt})
                self._history.append({"role": "assistant", "content": full_text})
                max_keep = self._max_history_turns * 2
                if len(self._history) > max_keep:
                    self._history = self._history[-max_keep:]
                # ★ 新增：按 token 数量裁剪
                self._trim_history_by_tokens()

            if on_complete:
                on_complete(full_text)

            # 也通过信号通知
            self.reply_received.emit(full_text)

        except requests.exceptions.ConnectionError:
            msg = "Ollama 连接失败，请确认服务已启动"
            if on_error:
                on_error(msg)
            self.error_occurred.emit(msg)
        except requests.exceptions.Timeout:
            msg = "流式请求超时"
            if on_error:
                on_error(msg)
            self.error_occurred.emit(msg)
        except RuntimeError as re:
            logger.exception("流式对话异常（所有引擎都失败）")
            msg = f"流式对话出错: {re}"
            if on_error:
                on_error(msg)
            self.error_occurred.emit(msg)
        except Exception as e:
            logger.exception("流式对话异常")
            msg = f"流式对话出错: {e}"
            if on_error:
                on_error(msg)
            self.error_occurred.emit(msg)
        finally:
            self._finalize_busy()


# ============================================================
# ★ OllamaAutoDetector — 自动检测 Ollama 安装和运行状态
# ============================================================
class OllamaAutoDetector:
    """Ollama 自动检测器"""

    def __init__(self, host: str = OLLAMA_HOST):
        self.host = host.rstrip("/")

    def detect_ollama(self) -> Dict:
        """检测系统是否安装了 ollama

        Returns:
            {
                "installed": bool,        # 是否安装
                "running": bool,          # 是否运行中
                "version": str,           # 版本号
                "path": str,              # 安装路径
                "host": str,              # API 地址
            }
        """
        result = {
            "installed": False,
            "running": False,
            "version": "",
            "path": "",
            "host": self.host,
        }

        # 1. 检查 ollama 命令是否可用
        import shutil
        ollama_path = shutil.which("ollama")
        if ollama_path:
            result["installed"] = True
            result["path"] = ollama_path
            # 获取版本
            try:
                import subprocess
                ver = subprocess.run(
                    ["ollama", "--version"],
                    capture_output=True, text=True, timeout=5,
                    encoding='utf-8', errors='replace'
                )
                if ver.returncode == 0:
                    result["version"] = ver.stdout.strip()
            except Exception:
                pass
        else:
            # 检查常见安装路径（Windows）
            common_paths = [
                r"C:\Users\{}\AppData\Local\Programs\Ollama\ollama.exe",
                r"C:\Program Files\Ollama\ollama.exe",
                "/usr/local/bin/ollama",
                "/usr/bin/ollama",
            ]
            home = os.path.expanduser("~")
            for p in common_paths:
                p = p.replace("{}", os.path.basename(home))
                if os.path.exists(p):
                    result["installed"] = True
                    result["path"] = p
                    break

        # 2. 检查服务是否运行
        result["running"] = self.get_running_status()

        return result

    def get_running_status(self) -> bool:
        """检测 ollama 服务是否正在运行"""
        if requests is None:
            return False
        try:
            resp = requests.get(f"{self.host}/api/tags", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def get_installed_models(self) -> List[Dict]:
        """获取已安装模型列表

        Returns:
            [{"name": "qwen2.5:1.5b", "size": "1.5GB", "modified": "2024-01-01"}, ...]
        """
        if requests is None:
            return []
        try:
            resp = requests.get(f"{self.host}/api/tags", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("models", [])
                result = []
                for m in models:
                    size_bytes = m.get("size", 0) or 0
                    size_str = self._format_size(size_bytes)
                    result.append({
                        "name": m.get("name", ""),
                        "size": size_str,
                        "size_bytes": size_bytes,
                        "modified": m.get("modified_at", ""),
                        "digest": m.get("digest", "")[:12] if m.get("digest") else "",
                    })
                return result
        except Exception as e:
            logger.warning(f"获取模型列表失败: {e}")
        return []

    def recommend_model(self, task_type: str = "chat") -> Dict:
        """根据任务类型推荐合适的模型

        Args:
            task_type: 'coding' / 'chat' / 'visualization' / 'general'

        Returns:
            {"recommended": str, "reason": str, "available": bool, "fallback": str}
        """
        installed = self.get_installed_models()
        installed_names = [m["name"] for m in installed]

        # 按任务类型的推荐列表（从大到小，优先大模型）
        recommendations = {
            "coding": [
                ("qwen2.5-coder:7b", "代码专用模型，7B参数，适合代码生成和审查"),
                ("qwen2.5-coder:3b", "代码专用模型，3B参数，轻量级代码助手"),
                ("deepseek-coder:6.7b", "DeepSeek 代码模型，擅长多种编程语言"),
                ("codellama:7b", "Meta CodeLlama，通用代码模型"),
            ],
            "chat": [
                ("qwen2.5:7b", "通义千问 7B，通用对话能力优秀"),
                ("qwen2.5:4b", "通义千问 4B，平衡性能和速度"),
                ("qwen2.5:1.5b", "通义千问 1.5B，轻量级对话"),
                ("llama3.2:3b", "Meta Llama 3.2，轻量级英文对话"),
            ],
            "visualization": [
                ("qwen2.5:7b", "7B模型理解能力更强，适合复杂可视化指令"),
                ("qwen2.5:4b", "4B模型平衡能力，适合常规可视化"),
                ("qwen2.5:1.5b", "1.5B模型快速响应，简单可视化"),
            ],
            "general": [
                ("qwen2.5:7b", "通用 7B，综合能力强"),
                ("qwen2.5:4b", "通用 4B，平衡选择"),
                ("qwen2.5:1.5b", "通用 1.5B，轻量级"),
            ],
        }

        task_models = recommendations.get(task_type, recommendations["general"])

        # 找第一个已安装的推荐模型
        for model_name, reason in task_models:
            if model_name in installed_names:
                return {
                    "recommended": model_name,
                    "reason": reason,
                    "available": True,
                    "fallback": "",
                }

        # 没有推荐模型已安装，返回推荐安装的第一个
        return {
            "recommended": task_models[0][0],
            "reason": task_models[0][1],
            "available": False,
            "fallback": installed_names[0] if installed_names else "",
        }

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """格式化文件大小"""
        if size_bytes == 0:
            return "0B"
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f}{unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f}PB"


# ============================================================
# ★ OllamaModelManager — 模型下载、删除、信息查询
# ============================================================
class OllamaModelManager:
    """Ollama 模型管理器"""

    def __init__(self, host: str = OLLAMA_HOST):
        self.host = host.rstrip("/")

    def download_model(self, model_name: str,
                       on_progress: Optional[callable] = None) -> bool:
        """下载模型（ollama pull）

        Args:
            model_name: 模型名称，如 "qwen2.5:7b"
            on_progress: 进度回调 (status: str, percent: float) -> None

        Returns:
            是否成功
        """
        import subprocess

        if on_progress:
            on_progress(f"开始下载 {model_name}...", 0.0)

        try:
            # 使用 subprocess 调用 ollama pull
            process = subprocess.Popen(
                ["ollama", "pull", model_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
            )

            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                # ollama pull 输出格式: pulling 1234567890ab... 100% ▕████████████▏ 1.5 GB
                if on_progress:
                    if "100%" in line:
                        on_progress(line, 100.0)
                    elif "%" in line:
                        # 尝试提取百分比
                        import re
                        match = re.search(r'(\d+)%', line)
                        if match:
                            pct = float(match.group(1))
                            on_progress(line, pct)
                        else:
                            on_progress(line, -1)
                    else:
                        on_progress(line, -1)

            process.wait()
            if process.returncode == 0:
                if on_progress:
                    on_progress(f"{model_name} 下载完成", 100.0)
                return True
            else:
                if on_progress:
                    on_progress(f"下载失败: 返回码 {process.returncode}", -1)
                return False

        except FileNotFoundError:
            if on_progress:
                on_progress("未找到 ollama 命令，请先安装 Ollama", -1)
            return False
        except Exception as e:
            if on_progress:
                on_progress(f"下载异常: {e}", -1)
            return False

    def delete_model(self, model_name: str) -> Tuple[bool, str]:
        """删除模型（ollama rm）

        Args:
            model_name: 模型名称

        Returns:
            (成功与否, 消息)
        """
        try:
            # 优先用 HTTP API
            if requests:
                resp = requests.delete(
                    f"{self.host}/api/delete",
                    json={"name": model_name},
                    timeout=30,
                )
                if resp.status_code == 200:
                    return True, f"已删除 {model_name}"
                else:
                    return False, f"删除失败: HTTP {resp.status_code}"

            # 降级用命令行
            import subprocess
            result = subprocess.run(
                ["ollama", "rm", model_name],
                capture_output=True, text=True, timeout=15,
                encoding='utf-8', errors='replace'
            )
            if result.returncode == 0:
                return True, f"已删除 {model_name}"
            else:
                return False, result.stderr.strip()
        except Exception as e:
            return False, str(e)

    def get_model_info(self, model_name: str) -> Optional[Dict]:
        """获取模型详细信息

        Args:
            model_name: 模型名称

        Returns:
            {
                "name": str,
                "size": str,
                "parameters": str,
                "quantization": str,
                "context_window": int,
                "family": str,
            }
        """
        try:
            if requests:
                resp = requests.post(
                    f"{self.host}/api/show",
                    json={"name": model_name},
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    details = data.get("details", {})
                    size_bytes = data.get("size", 0) or 0
                    return {
                        "name": model_name,
                        "size": OllamaAutoDetector._format_size(size_bytes),
                        "size_bytes": size_bytes,
                        "parameters": details.get("parameter_size", "未知"),
                        "quantization": details.get("quantization_level", "未知"),
                        "context_window": data.get("model_info", {}).get("general.context_length", 4096),
                        "family": details.get("family", "未知"),
                        "format": details.get("format", "gguf"),
                    }
        except Exception as e:
            logger.warning(f"获取模型信息失败: {e}")
        return None

    def list_models(self) -> List[Dict]:
        """列出所有已安装模型（便捷方法）"""
        detector = OllamaAutoDetector(self.host)
        return detector.get_installed_models()


# ============================================================
# 自测
# ============================================================
if __name__ == "__main__":
    import sys
    import time

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    bridge = OllamaBridge()

    def on_reply(text):
        print(f"\n[柠檬小助手回复] {text}")
        sys.stdout.flush()

    def on_err(text):
        print(f"\n[错误] {text}")
        sys.stdout.flush()

    bridge.reply_received.connect(on_reply)
    bridge.error_occurred.connect(on_err)

    print(f"Ollama 可用: {bridge.is_available()}")
    print(f"知识库: {'已加载' if bridge._kb else '未加载'}")
    if bridge._kb:
        print(f"场景数: {len(bridge._kb.scenes)}")

    if not bridge.is_available():
        print("请先启动 Ollama")
        sys.exit(0)

    # 测试多个问题
    test_msgs = [
        "你好呀",
        "你是谁",
        "怎么用这个Agent",
        "写bug了好烦",
        "讲个笑话",
        "几点了",
    ]

    for msg in test_msgs:
        print(f"\n--- 用户: {msg} ---")
        bridge.chat(msg)
        for _ in range(30):
            if not bridge.is_busy():
                break
            time.sleep(1)

    print("\n测试完成")
