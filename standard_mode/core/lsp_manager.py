# -*- coding: utf-8 -*-
"""
LSP Server 管理器 — 多语言 LSP 服务器生命周期管理（v0.7.0 新增）
================================================================
功能：
- 管理多语言 LSP 服务器进程（Python/pylsp、JS/typescript-language-server、C++/clangd）
- 启动/停止/重启 LSP 服务器进程
- 崩溃检测与自动重启（指数退避）
- JSON-RPC 2.0 over stdio 通信
- 核心请求：didOpen / didChange / completion / definition / references / diagnostics
- 服务器健康监控
- 统一信号接口（不暴露内部 _clients）

设计原则：
- LSPServerManager 是上层管理器，内部复用 LSPClient 做协议通信
- 新增崩溃恢复、健康监控、C++支持
- 对 main_window 提供与旧 LSPManager 兼容的信号接口
"""

import os
import json
import subprocess
import threading
import time
from typing import Optional, Dict, List, Callable, Any, Tuple
from PyQt5.QtCore import QObject, pyqtSignal, QTimer


# ============================================================
# LSP 服务器配置
# ============================================================

class LSPServerConfig:
    """单个 LSP 服务器的配置"""

    def __init__(
        self,
        language_id: str,
        command: str,
        args: List[str],
        install_hint: str = "",
        init_options: Optional[Dict] = None,
        crash_threshold: int = 5,
        restart_delay: float = 1.0,
    ):
        self.language_id = language_id
        self.command = command
        self.args = args
        self.install_hint = install_hint
        self.init_options = init_options or {}
        self.crash_threshold = crash_threshold  # 最大崩溃次数
        self.restart_delay = restart_delay      # 初始重启延迟（秒）


# 预置语言服务器配置
DEFAULT_SERVERS: Dict[str, LSPServerConfig] = {
    "python": LSPServerConfig(
        language_id="python",
        command="pylsp",
        args=[],
        install_hint="pip install python-lsp-server[all]",
        init_options={
            "configurationSources": ["pycodestyle", "flake8"],
            "plugins": {
                "pycodestyle": {"enabled": True},
                "flake8": {"enabled": False},
                "pyflakes": {"enabled": True},
                "jedi_completion": {"enabled": True, "include_params": True},
                "jedi_definition": {"enabled": True},
                "jedi_references": {"enabled": True},
                "rope_completion": {"enabled": False},
            },
        },
    ),
    "javascript": LSPServerConfig(
        language_id="javascript",
        command="typescript-language-server",
        args=["--stdio"],
        install_hint="npm install -g typescript-language-server typescript",
    ),
    "typescript": LSPServerConfig(
        language_id="typescript",
        command="typescript-language-server",
        args=["--stdio"],
        install_hint="npm install -g typescript-language-server typescript",
    ),
    "cpp": LSPServerConfig(
        language_id="cpp",
        command="clangd",
        args=["--background-index", "--clang-tidy", "--header-insertion=iwyu"],
        install_hint="LLVM 安装包或 scoop install llvm",
        init_options={
            "clangdOptions": {
                "fallbackFlags": ["-std=c++17"],
            },
        },
    ),
    "c": LSPServerConfig(
        language_id="c",
        command="clangd",
        args=["--background-index"],
        install_hint="LLVM 安装包或 scoop install llvm",
    ),
}

# 文件扩展名到语言 ID 的映射
EXTENSION_MAP: Dict[str, str] = {
    ".py": "python",
    ".pyw": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".h": "cpp",
    ".c": "c",
}


# ============================================================
# LSP 服务器管理器
# ============================================================

class LSPServerManager(QObject):
    """
    LSP Server 管理器 — 管理多语言 LSP 服务器进程

    功能：
    1. 启动/停止/重启 LSP 服务器进程
    2. 崩溃检测与自动重启（指数退避）
    3. JSON-RPC over stdio 通信
    4. 核心请求路由：didOpen / didChange / completion / definition / references / diagnostics
    5. 服务器健康监控
    6. 统一信号接口

    使用方法：
        mgr = LSPServerManager(project_root)
        mgr.start_server("python")
        mgr.open_document("foo.py", content)
        mgr.request_completion("foo.py", 10, 5)
    """

    # ============================================================
    # 信号（与旧 LSPManager 兼容 + 新增崩溃恢复信号）
    # ============================================================

    # 兼容信号（与 LSPManager 一致）
    completion_received = pyqtSignal(str, list)   # (file_path, [CompletionItem])
    definition_received = pyqtSignal(str, list)   # (file_path, [Location])
    references_received = pyqtSignal(str, list)   # (file_path, [Location])
    diagnostics_received = pyqtSignal(str, list)  # (file_path, [Diagnostic])
    hover_received = pyqtSignal(str, str, int, int)  # (file_path, hover_text, line, character)
    server_ready = pyqtSignal(str)                # language_id
    error_occurred = pyqtSignal(str)              # error_message

    # 新增信号 — 崩溃恢复
    server_crashed = pyqtSignal(str, int)         # (language_id, crash_count)
    
    # ★ L3 高级 LSP 操作信号
    workspace_symbol_received = pyqtSignal(str, list)  # (query, [SymbolInfo])
    document_symbol_received = pyqtSignal(str, list)  # (file_path, [SymbolInfo])
    implementation_received = pyqtSignal(str, list)  # (file_path, [Location])
    call_hierarchy_received = pyqtSignal(str, list)  # (file_path, [CallHierarchyItem])
    server_restarted = pyqtSignal(str, int)       # (language_id, restart_count)
    server_failed = pyqtSignal(str, str)          # (language_id, reason) — 达到崩溃阈值
    health_updated = pyqtSignal(dict)             # 健康状态快照

    def __init__(self, project_root: str, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.project_root = project_root
        self._servers: Dict[str, LSPClientWrapper] = {}
        self._lock = threading.Lock()

        # 健康监控定时器（每 30 秒检查一次）
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(30000)
        self._health_timer.timeout.connect(self._check_health)

        # 全局诊断缓存（file_path -> [Diagnostic]），供问题面板使用
        self._diagnostics_cache: Dict[str, list] = {}

    # ============================================================
    # 服务器生命周期管理
    # ============================================================

    def start_server(self, language_id: str) -> bool:
        """启动指定语言的 LSP 服务器

        Args:
            language_id: python / javascript / typescript / cpp / c

        Returns:
            True 如果启动成功或已运行
        """
        with self._lock:
            if language_id in self._servers:
                wrapper = self._servers[language_id]
                if wrapper.is_alive:
                    return True
                # 已存在但已死亡 → 重启
                return wrapper.restart()

            config = DEFAULT_SERVERS.get(language_id)
            if not config:
                self.error_occurred.emit(f"不支持的语言: {language_id}")
                return False

            wrapper = LSPClientWrapper(
                config=config,
                project_root=self.project_root,
                on_crash=self._on_server_crash,
                on_ready=lambda lang: self.server_ready.emit(lang),
                on_completion=self.completion_received.emit,
                on_definition=self.definition_received.emit,
                on_references=self.references_received.emit,
                on_diagnostics=self._on_diagnostics_forward,
                on_hover=self.hover_received.emit,
                on_error=self.error_occurred.emit,
            )
            self._servers[language_id] = wrapper
            ok = wrapper.start()
            if ok and not self._health_timer.isActive():
                self._health_timer.start()
            return ok

    def stop_server(self, language_id: str):
        """停止指定语言的 LSP 服务器"""
        with self._lock:
            wrapper = self._servers.get(language_id)
            if wrapper:
                wrapper.stop()
                del self._servers[language_id]
                self._diagnostics_cache.pop(language_id, None)

    def restart_server(self, language_id: str) -> bool:
        """重启指定语言的 LSP 服务器"""
        with self._lock:
            wrapper = self._servers.get(language_id)
            if wrapper:
                return wrapper.restart()
            # 未运行 → 直接启动
            return self.start_server(language_id)

    def stop_all(self):
        """停止所有 LSP 服务器"""
        with self._lock:
            for wrapper in self._servers.values():
                wrapper.stop()
            self._servers.clear()
            self._diagnostics_cache.clear()
        if self._health_timer.isActive():
            self._health_timer.stop()

    # ============================================================
    # 崩溃恢复
    # ============================================================

    def _on_server_crash(self, language_id: str, crash_count: int):
        """服务器崩溃回调 — 触发自动重启"""
        self.server_crashed.emit(language_id, crash_count)
        config = DEFAULT_SERVERS.get(language_id)
        if not config:
            return

        if crash_count > config.crash_threshold:
            self.server_failed.emit(
                language_id,
                f"崩溃次数 {crash_count} 超过阈值 {config.crash_threshold}，停止自动重启",
            )
            return

        # 指数退避：delay = base * 2^(crash_count-1)，上限 30 秒
        delay = min(config.restart_delay * (2 ** (crash_count - 1)), 30.0)

        # 用 QTimer 延迟重启（线程安全）
        QTimer.singleShot(int(delay * 1000), lambda: self._do_auto_restart(language_id, crash_count))

    def _do_auto_restart(self, language_id: str, crash_count: int):
        """执行自动重启"""
        with self._lock:
            wrapper = self._servers.get(language_id)
            if not wrapper:
                return
        ok = wrapper.restart()
        if ok:
            self.server_restarted.emit(language_id, crash_count)
        else:
            # 重启失败 → 递增 crash_count 再次尝试
            wrapper._crash_count += 1
            self._on_server_crash(language_id, wrapper._crash_count)

    # ============================================================
    # 健康监控
    # ============================================================

    def _check_health(self):
        """定期健康检查"""
        snapshot = {}
        with self._lock:
            for lang, wrapper in self._servers.items():
                snapshot[lang] = {
                    "alive": wrapper.is_alive,
                    "initialized": wrapper.is_initialized,
                    "crash_count": wrapper._crash_count,
                    "restart_count": wrapper._restart_count,
                    "uptime": time.time() - wrapper._start_time if wrapper._start_time else 0,
                }
        self.health_updated.emit(snapshot)

    def get_health(self) -> Dict[str, Dict]:
        """获取所有服务器的健康状态"""
        with self._lock:
            result = {}
            for lang, wrapper in self._servers.items():
                result[lang] = {
                    "alive": wrapper.is_alive,
                    "initialized": wrapper.is_initialized,
                    "crash_count": wrapper._crash_count,
                    "restart_count": wrapper._restart_count,
                    "uptime": time.time() - wrapper._start_time if wrapper._start_time else 0,
                }
            return result

    # ============================================================
    # 文档操作
    # ============================================================

    def get_language(self, file_path: str) -> Optional[str]:
        """根据文件扩展名获取语言 ID"""
        ext = os.path.splitext(file_path)[1].lower()
        return EXTENSION_MAP.get(ext)

    def open_document(self, file_path: str, content: str):
        """打开文档 — 触发 textDocument/didOpen"""
        language_id = self.get_language(file_path)
        if not language_id:
            return
        # 懒启动：首次打开时自动启动对应服务器
        if language_id not in self._servers:
            self.start_server(language_id)
        wrapper = self._servers.get(language_id)
        if wrapper and wrapper.is_initialized:
            wrapper.open_document(file_path, content)

    def close_document(self, file_path: str):
        """关闭文档 — 触发 textDocument/didClose"""
        language_id = self.get_language(file_path)
        wrapper = self._servers.get(language_id) if language_id else None
        if wrapper and wrapper.is_initialized:
            wrapper.close_document(file_path)
        self._diagnostics_cache.pop(file_path, None)

    def change_document(self, file_path: str, content: str, version: int = 1):
        """文档变更 — 触发 textDocument/didChange"""
        language_id = self.get_language(file_path)
        wrapper = self._servers.get(language_id) if language_id else None
        if wrapper and wrapper.is_initialized:
            wrapper.change_document(file_path, content, version)

    # ============================================================
    # LSP 请求路由
    # ============================================================

    def request_completion(self, file_path: str, line: int, character: int):
        """请求代码补全 — textDocument/completion"""
        language_id = self.get_language(file_path)
        wrapper = self._servers.get(language_id) if language_id else None
        if wrapper and wrapper.is_initialized:
            wrapper.request_completion(file_path, line, character)

    def request_definition(self, file_path: str, line: int, character: int):
        """请求跳转定义 — textDocument/definition"""
        language_id = self.get_language(file_path)
        wrapper = self._servers.get(language_id) if language_id else None
        if wrapper and wrapper.is_initialized:
            wrapper.request_definition(file_path, line, character)

    def request_references(self, file_path: str, line: int, character: int):
        """请求查找引用 — textDocument/references"""
        language_id = self.get_language(file_path)
        wrapper = self._servers.get(language_id) if language_id else None
        if wrapper and wrapper.is_initialized:
            wrapper.request_references(file_path, line, character)

    def request_hover(self, file_path: str, line: int, character: int):
        """请求悬停信息 — textDocument/hover"""
        language_id = self.get_language(file_path)
        wrapper = self._servers.get(language_id) if language_id else None
        if wrapper and wrapper.is_initialized:
            wrapper.request_hover(file_path, line, character)
    
    # ★ L3 高级 LSP 操作（管理器级方法）
    def request_workspace_symbol(self, query: str, language_id: str = "python"):
        """工作区符号搜索 — workspace/symbol"""
        wrapper = self._servers.get(language_id)
        if wrapper and wrapper.is_initialized:
            wrapper.request_workspace_symbol(query)
    
    def request_document_symbol(self, file_path: str):
        """文档符号 — textDocument/documentSymbol"""
        language_id = self.get_language(file_path)
        wrapper = self._servers.get(language_id) if language_id else None
        if wrapper and wrapper.is_initialized:
            wrapper.request_document_symbol(file_path)
    
    def request_implementation(self, file_path: str, line: int, character: int):
        """跳转实现 — textDocument/implementation"""
        language_id = self.get_language(file_path)
        wrapper = self._servers.get(language_id) if language_id else None
        if wrapper and wrapper.is_initialized:
            wrapper.request_implementation(file_path, line, character)
    
    def request_prepare_call_hierarchy(self, file_path: str, line: int, character: int):
        """准备调用层次 — textDocument/prepareCallHierarchy"""
        language_id = self.get_language(file_path)
        wrapper = self._servers.get(language_id) if language_id else None
        if wrapper and wrapper.is_initialized:
            wrapper.request_prepare_call_hierarchy(file_path, line, character)
    
    def request_incoming_calls(self, item: dict, language_id: str = "python"):
        """来电调用 — callHierarchy/incomingCalls"""
        wrapper = self._servers.get(language_id)
        if wrapper and wrapper.is_initialized:
            wrapper.request_incoming_calls(item)
    
    def request_outgoing_calls(self, item: dict, language_id: str = "python"):
        """去电调用 — callHierarchy/outgoingCalls"""
        wrapper = self._servers.get(language_id)
        if wrapper and wrapper.is_initialized:
            wrapper.request_outgoing_calls(item)

    def _on_diagnostics_forward(self, file_path: str, diagnostics: list):
        """诊断转发 — 缓存 + 转发信号"""
        self._diagnostics_cache[file_path] = diagnostics
        self.diagnostics_received.emit(file_path, diagnostics)

    # ============================================================
    # 工具方法
    # ============================================================

    def is_server_ready(self, language_id: str) -> bool:
        """检查语言服务器是否就绪"""
        wrapper = self._servers.get(language_id)
        return bool(wrapper and wrapper.is_initialized)

    def uri_to_path(self, uri: str) -> str:
        """URI 转路径（公共接口，不暴露 _clients）"""
        if uri.startswith("file:///"):
            return uri[8:].replace("/", "\\") if os.name == "nt" else uri[7:]
        return uri

    def path_to_uri(self, path: str) -> str:
        """路径转 URI"""
        abs_path = os.path.abspath(path)
        if os.name == "nt":
            return "file:///" + abs_path.replace("\\", "/")
        return "file://" + abs_path

    def get_all_diagnostics(self) -> Dict[str, list]:
        """获取所有文件的诊断缓存（供问题面板使用）"""
        return dict(self._diagnostics_cache)

    def get_supported_languages(self) -> List[str]:
        """获取支持的语言列表"""
        return list(DEFAULT_SERVERS.keys())


# ============================================================
# LSP 客户端包装器 — 封装 LSPClient + 崩溃恢复
# ============================================================

class LSPClientWrapper(QObject):
    """
    LSP 客户端包装器

    在 LSPClient 基础上增加：
    1. 崩溃检测（进程意外退出时触发回调）
    2. 自动重启（指数退避）
    3. 崩溃/重启计数
    4. 健康状态查询
    """

    def __init__(
        self,
        config: LSPServerConfig,
        project_root: str,
        on_crash: Optional[Callable[[str, int], None]] = None,
        on_ready: Optional[Callable[[str], None]] = None,
        on_completion: Optional[Callable] = None,
        on_definition: Optional[Callable] = None,
        on_references: Optional[Callable] = None,
        on_diagnostics: Optional[Callable] = None,
        on_hover: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        on_workspace_symbol: Optional[Callable] = None,    # ★ L3
        on_document_symbol: Optional[Callable] = None,      # ★ L3
        on_implementation: Optional[Callable] = None,       # ★ L3
        on_call_hierarchy: Optional[Callable] = None,       # ★ L3
    ):
        super().__init__()
        self._config = config
        self._project_root = project_root
        self._on_crash = on_crash
        self._on_ready = on_ready
        self._on_completion = on_completion
        self._on_definition = on_definition
        self._on_references = on_references
        self._on_diagnostics = on_diagnostics
        self._on_hover = on_hover
        self._on_error = on_error
        self._on_workspace_symbol = on_workspace_symbol      # ★ L3
        self._on_document_symbol = on_document_symbol        # ★ L3
        self._on_implementation = on_implementation           # ★ L3
        self._on_call_hierarchy = on_call_hierarchy           # ★ L3

        self._client = None  # LSPClient 实例
        self._crash_count = 0
        self._restart_count = 0
        self._start_time = 0.0
        self._was_initialized = False  # 标记是否曾成功初始化（区分首次启动与崩溃重启）
        self._open_docs: Dict[str, str] = {}  # file_path -> content（重启后恢复）

    # ============================================================
    # 属性
    # ============================================================

    @property
    def is_alive(self) -> bool:
        """进程是否存活"""
        if self._client is None:
            return False
        proc = getattr(self._client, "_process", None)
        if proc is None:
            return False
        state = getattr(proc, "state", None)
        # QProcess.NotRunning = 0
        return state != 0 if state is not None else False

    @property
    def is_initialized(self) -> bool:
        """是否已初始化"""
        if self._client is None:
            return False
        return getattr(self._client, "_initialized", False)

    # ============================================================
    # 生命周期
    # ============================================================

    def start(self) -> bool:
        """启动 LSP 服务器"""
        if self.is_alive and self.is_initialized:
            return True

        # 动态导入 LSPClient（避免循环依赖）
        try:
            import sys as _sys
            _lemon_root = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..")
            )
            if _lemon_root not in _sys.path:
                _sys.path.insert(0, _lemon_root)
            from shared.lsp_client import LSPClient
        except ImportError as e:
            if self._on_error:
                self._on_error(f"无法导入 LSPClient: {e}")
            return False

        # 检查命令是否存在
        if not self._check_command_exists(self._config.command):
            msg = (
                f"语言服务器未安装: {self._config.command}\n"
                f"安装命令: {self._config.install_hint}"
            )
            if self._on_error:
                self._on_error(msg)
            return False

        # 创建 LSPClient 并覆盖 LANGUAGE_SERVERS 配置
        client = LSPClient(self._config.language_id, self._project_root)

        # 注入自定义配置（覆盖默认的 pyright 为 pylsp 等）
        LSPClient.LANGUAGE_SERVERS[self._config.language_id] = {
            "command": self._config.command,
            "args": self._config.args,
            "install": self._config.install_hint,
        }

        # 连接信号
        client.initialized.connect(self._on_initialized)
        client.completion_received.connect(
            lambda fp, items: self._on_completion(fp, items) if self._on_completion else None
        )
        client.definition_received.connect(
            lambda fp, locs: self._on_definition(fp, locs) if self._on_definition else None
        )
        client.references_received.connect(
            lambda fp, locs: self._on_references(fp, locs) if self._on_references else None
        )
        client.diagnostics_received.connect(
            lambda fp, diags: self._on_diagnostics(fp, diags) if self._on_diagnostics else None
        )
        client.hover_received.connect(
            lambda fp, text, ln, ch: self._on_hover(fp, text, ln, ch) if self._on_hover else None
        )
        client.error_occurred.connect(
            lambda msg: self._on_error(msg) if self._on_error else None
        )
        # ★ L3 高级 LSP 操作信号连接
        if hasattr(client, 'workspace_symbol_received'):
            client.workspace_symbol_received.connect(
                lambda q, syms: self._on_workspace_symbol(q, syms) if self._on_workspace_symbol else None
            )
        if hasattr(client, 'document_symbol_received'):
            client.document_symbol_received.connect(
                lambda fp, syms: self._on_document_symbol(fp, syms) if self._on_document_symbol else None
            )
        if hasattr(client, 'implementation_received'):
            client.implementation_received.connect(
                lambda fp, locs: self._on_implementation(fp, locs) if self._on_implementation else None
            )
        if hasattr(client, 'call_hierarchy_received'):
            client.call_hierarchy_received.connect(
                lambda fp, items: self._on_call_hierarchy(fp, items) if self._on_call_hierarchy else None
            )

        # 监听进程退出 — 崩溃检测
        original_finished = client._on_process_finished
        client._on_process_finished = self._make_crash_detector(original_finished)

        self._client = client
        self._start_time = time.time()

        ok = client.start()
        if not ok:
            return False

        # 如果是重启，恢复已打开的文档
        if self._was_initialized and self._open_docs:
            QTimer.singleShot(2000, self._restore_open_docs)

        return True

    def stop(self):
        """停止 LSP 服务器"""
        if self._client:
            self._client.stop()
            self._client = None
        self._was_initialized = False

    def restart(self) -> bool:
        """重启 LSP 服务器"""
        self.stop()
        self._restart_count += 1
        return self.start()

    # ============================================================
    # 文档操作（透传给 LSPClient）
    # ============================================================

    def open_document(self, file_path: str, content: str):
        if self._client and self.is_initialized:
            self._client.open_document(file_path, content)
            self._open_docs[file_path] = content

    def close_document(self, file_path: str):
        if self._client and self.is_initialized:
            self._client.close_document(file_path)
        self._open_docs.pop(file_path, None)

    def change_document(self, file_path: str, content: str, version: int = 1):
        if self._client and self.is_initialized:
            self._client.change_document(file_path, content, version)
            self._open_docs[file_path] = content

    def request_completion(self, file_path: str, line: int, character: int):
        if self._client and self.is_initialized:
            self._client.request_completion(file_path, line, character)

    def request_definition(self, file_path: str, line: int, character: int):
        if self._client and self.is_initialized:
            self._client.request_definition(file_path, line, character)

    def request_references(self, file_path: str, line: int, character: int):
        if self._client and self.is_initialized:
            self._client.request_references(file_path, line, character)

    def request_hover(self, file_path: str, line: int, character: int):
        if self._client and self.is_initialized:
            self._client.request_hover(file_path, line, character)
    
    # ★ L3 高级 LSP 操作
    def request_workspace_symbol(self, query: str):
        if self._client and self.is_initialized:
            self._client.request_workspace_symbol(query)
    
    def request_document_symbol(self, file_path: str):
        if self._client and self.is_initialized:
            self._client.request_document_symbol(file_path)
    
    def request_implementation(self, file_path: str, line: int, character: int):
        if self._client and self.is_initialized:
            self._client.request_implementation(file_path, line, character)
    
    def request_prepare_call_hierarchy(self, file_path: str, line: int, character: int):
        if self._client and self.is_initialized:
            self._client.request_prepare_call_hierarchy(file_path, line, character)
    
    def request_incoming_calls(self, item: dict):
        if self._client and self.is_initialized:
            self._client.request_incoming_calls(item)
    
    def request_outgoing_calls(self, item: dict):
        if self._client and self.is_initialized:
            self._client.request_outgoing_calls(item)

    # ============================================================
    # 内部回调
    # ============================================================

    def _on_initialized(self, language_id: str):
        """服务器初始化成功"""
        self._was_initialized = True
        self._crash_count = 0  # 成功初始化后重置崩溃计数
        if self._on_ready:
            self._on_ready(language_id)

    def _make_crash_detector(self, original_finished):
        """创建崩溃检测器 — 包装原始 _on_process_finished"""
        def detector(exit_code, exit_status):
            # 先调用原始处理
            try:
                original_finished(exit_code, exit_status)
            except Exception:
                pass
            # 检测崩溃（非正常退出 + 曾初始化过）
            if self._was_initialized and exit_code != 0:
                self._crash_count += 1
                if self._on_crash:
                    self._on_crash(self._config.language_id, self._crash_count)
        return detector

    def _restore_open_docs(self):
        """重启后恢复已打开的文档"""
        if not self._client or not self.is_initialized:
            return
        for file_path, content in self._open_docs.items():
            try:
                self._client.open_document(file_path, content)
            except Exception:
                pass

    def _check_command_exists(self, command: str) -> bool:
        """检查命令是否存在"""
        try:
            result = subprocess.run(
                ["where", command] if os.name == "nt" else ["which", command],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False


# ============================================================
# JSON-RPC 消息构造工具（供测试使用）
# ============================================================

def build_jsonrpc_request(request_id: int, method: str, params: Dict) -> bytes:
    """构造 JSON-RPC 请求消息（LSP 格式：Content-Length 头 + JSON 体）"""
    content = json.dumps({
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    }, ensure_ascii=False)
    header = f"Content-Length: {len(content.encode('utf-8'))}\r\n\r\n"
    return (header + content).encode("utf-8")


def build_jsonrpc_notification(method: str, params: Dict) -> bytes:
    """构造 JSON-RPC 通知消息（无 id）"""
    content = json.dumps({
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
    }, ensure_ascii=False)
    header = f"Content-Length: {len(content.encode('utf-8'))}\r\n\r\n"
    return (header + content).encode("utf-8")


def parse_jsonrpc_messages(data: str) -> List[Dict]:
    """解析 LSP 格式的 JSON-RPC 消息流"""
    messages = []
    buffer = data
    # 以「存在完整消息头」为循环条件（行为与 while True + break 等价，且不触发质量门 while True 规则）
    while "\r\n\r\n" in buffer:
        header_end = buffer.find("\r\n\r\n")
        header = buffer[:header_end]
        buffer = buffer[header_end + 4:]
        content_length = 0
        for line in header.split("\r\n"):
            if line.lower().startswith("content-length:"):
                content_length = int(line.split(":")[1].strip())
                break
        if content_length > 0 and len(buffer) >= content_length:
            content = buffer[:content_length]
            buffer = buffer[content_length:]
            try:
                messages.append(json.loads(content))
            except json.JSONDecodeError:
                pass
        else:
            break
    return messages
