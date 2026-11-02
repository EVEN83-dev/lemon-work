# -*- coding: utf-8 -*-
"""
LSP 客户端 — 语言服务器协议集成（v0.6.0 新增）
==============================================
功能：
- 启动/管理语言服务器进程（Python/JavaScript/Go）
- JSON-RPC 2.0 通信
- 代码补全、跳转定义、查找引用、诊断
- 多语言服务器并行管理
"""

import os
import json
import subprocess
import threading
import uuid
from typing import Optional, Dict, List, Callable, Any, Tuple
from PyQt5.QtCore import QObject, pyqtSignal, QProcess, QTimer


# ============================================================
# LSP 数据类型
# ============================================================

class Position:
    """位置"""
    def __init__(self, line: int, character: int):
        self.line = line
        self.character = character
    
    def to_dict(self) -> Dict:
        return {"line": self.line, "character": self.character}


class Range:
    """范围"""
    def __init__(self, start: Position, end: Position):
        self.start = start
        self.end = end
    
    def to_dict(self) -> Dict:
        return {
            "start": self.start.to_dict(),
            "end": self.end.to_dict()
        }


class Location:
    """位置（文件+范围）"""
    def __init__(self, uri: str, range: Range):
        self.uri = uri
        self.range = range
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Location':
        return cls(
            uri=data.get("uri", ""),
            range=Range(
                start=Position(data["range"]["start"]["line"], data["range"]["start"]["character"]),
                end=Position(data["range"]["end"]["line"], data["range"]["end"]["character"])
            )
        )


class Diagnostic:
    """诊断信息"""
    def __init__(self, range: Range, message: str, severity: int = 1, source: str = ""):
        self.range = range
        self.message = message
        self.severity = severity  # 1=Error, 2=Warning, 3=Information, 4=Hint
        self.source = source
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Diagnostic':
        range_data = data.get("range", {})
        return cls(
            range=Range(
                start=Position(range_data["start"]["line"], range_data["start"]["character"]),
                end=Position(range_data["end"]["line"], range_data["end"]["character"])
            ),
            message=data.get("message", ""),
            severity=data.get("severity", 1),
            source=data.get("source", "")
        )


class CompletionItem:
    """补全项"""
    def __init__(self, label: str, kind: int = 1, detail: str = "", documentation: str = "", insert_text: str = ""):
        self.label = label
        self.kind = kind  # 1=Text, 2=Method, 3=Function, 4=Constructor, 5=Field, 6=Variable, 7=Class, etc.
        self.detail = detail
        self.documentation = documentation
        self.insert_text = insert_text or label
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'CompletionItem':
        return cls(
            label=data.get("label", ""),
            kind=data.get("kind", 1),
            detail=data.get("detail", ""),
            documentation=data.get("documentation", ""),
            insert_text=data.get("insertText", "")
        )


# ============================================================
# LSP 客户端
# ============================================================

class LSPClient(QObject):
    """
    LSP 客户端 — 与语言服务器通信
    
    支持的语言：
    - Python: pyright / pylance
    - JavaScript/TypeScript: typescript-language-server
    - Go: gopls
    """
    
    # 信号
    initialized = pyqtSignal(str)  # language_id
    completion_received = pyqtSignal(str, list)  # (file_path, [CompletionItem])
    definition_received = pyqtSignal(str, list)  # (file_path, [Location])
    references_received = pyqtSignal(str, list)  # (file_path, [Location])
    diagnostics_received = pyqtSignal(str, list)  # (file_path, [Diagnostic])
    hover_received = pyqtSignal(str, str, int, int)  # (file_path, hover_text, line, character)
    error_occurred = pyqtSignal(str)  # error_message
    # ★ L3 高级 LSP 操作信号
    workspace_symbol_received = pyqtSignal(str, list)  # (query, [SymbolInfo])
    document_symbol_received = pyqtSignal(str, list)  # (file_path, [SymbolInfo])
    implementation_received = pyqtSignal(str, list)  # (file_path, [Location])
    call_hierarchy_received = pyqtSignal(str, list)  # (file_path, [CallHierarchyItem])
    
    # 语言服务器配置
    LANGUAGE_SERVERS = {
        "python": {
            "command": "pyright-langserver",
            "args": ["--stdio"],
            "install": "pip install pyright",
        },
        "javascript": {
            "command": "typescript-language-server",
            "args": ["--stdio"],
            "install": "npm install -g typescript-language-server typescript",
        },
        "typescript": {
            "command": "typescript-language-server",
            "args": ["--stdio"],
            "install": "npm install -g typescript-language-server typescript",
        },
        "go": {
            "command": "gopls",
            "args": [],
            "install": "go install golang.org/x/tools/gopls@latest",
        },
    }
    
    def __init__(self, language_id: str, project_root: str):
        super().__init__()
        self.language_id = language_id
        self.project_root = project_root
        self._process: Optional[QProcess] = None
        self._request_id = 0
        self._pending_requests: Dict[int, Tuple[str, Callable]] = {}
        self._buffer = ""
        self._content_length = 0
        self._initialized = False
        self._capabilities: Dict = {}
        
    @property
    def is_initialized(self) -> bool:
        return self._initialized
    
    @property
    def capabilities(self) -> Dict:
        return self._capabilities
    
    def start(self) -> bool:
        """启动语言服务器"""
        if self.language_id not in self.LANGUAGE_SERVERS:
            self.error_occurred.emit(f"不支持的语言: {self.language_id}")
            return False
        
        config = self.LANGUAGE_SERVERS[self.language_id]
        command = config["command"]
        args = config["args"]
        
        # 检查命令是否存在
        if not self._check_command_exists(command):
            self.error_occurred.emit(f"语言服务器未安装: {command}\n安装命令: {config['install']}")
            return False
        
        # 启动进程
        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.MergedChannels)
        self._process.readyRead.connect(self._on_data_received)
        self._process.errorOccurred.connect(self._on_process_error)
        self._process.finished.connect(self._on_process_finished)
        
        self._process.start(command, args)
        
        if not self._process.waitForStarted(5000):
            self.error_occurred.emit(f"无法启动语言服务器: {command}")
            return False
        
        # 发送初始化请求
        self._send_initialize()
        
        return True
    
    def stop(self):
        """停止语言服务器"""
        if self._process:
            self._send_request("shutdown", {})
            self._send_notification("exit", {})
            self._process.kill()
            self._process.waitForFinished(3000)
            self._process = None
            self._initialized = False
    
    def _check_command_exists(self, command: str) -> bool:
        """检查命令是否存在"""
        try:
            result = subprocess.run(
                ["where", command] if os.name == "nt" else ["which", command],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False
    
    # ============================================================
    # JSON-RPC 通信
    # ============================================================
    
    def _send_request(self, method: str, params: Dict, callback: Callable = None) -> int:
        """发送请求"""
        self._request_id += 1
        request_id = self._request_id
        
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params
        }
        
        if callback:
            self._pending_requests[request_id] = (method, callback)
        
        self._send_message(request)
        return request_id
    
    def _send_notification(self, method: str, params: Dict):
        """发送通知（无响应）"""
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        self._send_message(notification)
    
    def _send_message(self, message: Dict):
        """发送消息到语言服务器"""
        content = json.dumps(message, ensure_ascii=False)
        header = f"Content-Length: {len(content.encode('utf-8'))}\r\n\r\n"
        
        if self._process:
            self._process.write((header + content).encode('utf-8'))
    
    def _on_data_received(self):
        """接收语言服务器数据"""
        if not self._process:
            return
        
        data = self._process.readAll().data().decode('utf-8', errors='replace')
        self._buffer += data
        
        while True:
            # 解析头部
            if self._content_length == 0:
                header_end = self._buffer.find('\r\n\r\n')
                if header_end == -1:
                    break
                
                header = self._buffer[:header_end]
                self._buffer = self._buffer[header_end + 4:]
                
                # 提取 Content-Length
                for line in header.split('\r\n'):
                    if line.lower().startswith('content-length:'):
                        self._content_length = int(line.split(':')[1].strip())
                        break
            
            # 解析内容
            if self._content_length > 0 and len(self._buffer) >= self._content_length:
                content = self._buffer[:self._content_length]
                self._buffer = self._buffer[self._content_length:]
                self._content_length = 0
                
                try:
                    message = json.loads(content)
                    self._handle_message(message)
                except json.JSONDecodeError as e:
                    self.error_occurred.emit(f"JSON解析错误: {e}")
    
    def _handle_message(self, message: Dict):
        """处理语言服务器消息"""
        # 响应
        if "id" in message:
            request_id = message["id"]
            if request_id in self._pending_requests:
                method, callback = self._pending_requests.pop(request_id)
                if callback and "result" in message:
                    callback(message["result"])
                elif "error" in message:
                    self.error_occurred.emit(f"LSP错误: {message['error']}")
        
        # 通知
        elif "method" in message:
            method = message["method"]
            params = message.get("params", {})
            
            if method == "textDocument/publishDiagnostics":
                self._handle_diagnostics(params)
    
    # ============================================================
    # LSP 请求
    # ============================================================
    
    def _send_initialize(self):
        """发送初始化请求"""
        params = {
            "processId": os.getpid(),
            "rootUri": self._path_to_uri(self.project_root),
            "capabilities": {
                "textDocument": {
                    "completion": {
                        "completionItem": {
                            "snippetSupport": True,
                            "documentationFormat": ["markdown", "plaintext"]
                        }
                    },
                    "definition": {"linkSupport": True},
                    "references": {},
                    "hover": {
                        "contentFormat": ["markdown", "plaintext"]
                    },
                    "publishDiagnostics": {
                        "relatedInformation": True
                    }
                }
            }
        }
        
        self._send_request("initialize", params, self._on_initialize_response)
    
    def _on_initialize_response(self, result: Dict):
        """初始化响应处理"""
        self._capabilities = result.get("capabilities", {})
        self._initialized = True
        self.initialized.emit(self.language_id)
        
        # 发送 initialized 通知
        self._send_notification("initialized", {})
    
    def open_document(self, file_path: str, content: str):
        """打开文档"""
        self._send_notification("textDocument/didOpen", {
            "textDocument": {
                "uri": self._path_to_uri(file_path),
                "languageId": self.language_id,
                "version": 1,
                "text": content
            }
        })
    
    def close_document(self, file_path: str):
        """关闭文档"""
        self._send_notification("textDocument/didClose", {
            "textDocument": {
                "uri": self._path_to_uri(file_path)
            }
        })
    
    def change_document(self, file_path: str, content: str, version: int):
        """文档变更"""
        self._send_notification("textDocument/didChange", {
            "textDocument": {
                "uri": self._path_to_uri(file_path),
                "version": version
            },
            "contentChanges": [{"text": content}]
        })
    
    def request_completion(self, file_path: str, line: int, character: int):
        """请求代码补全"""
        self._send_request("textDocument/completion", {
            "textDocument": {"uri": self._path_to_uri(file_path)},
            "position": {"line": line, "character": character}
        }, lambda result: self._on_completion_response(file_path, result))
    
    def _on_completion_response(self, file_path: str, result: Any):
        """补全响应处理"""
        items = []
        if isinstance(result, dict):
            item_list = result.get("items", [])
        elif isinstance(result, list):
            item_list = result
        else:
            item_list = []
        
        for item in item_list:
            items.append(CompletionItem.from_dict(item))
        
        self.completion_received.emit(file_path, items)
    
    def request_definition(self, file_path: str, line: int, character: int):
        """请求跳转定义"""
        self._send_request("textDocument/definition", {
            "textDocument": {"uri": self._path_to_uri(file_path)},
            "position": {"line": line, "character": character}
        }, lambda result: self._on_definition_response(file_path, result))
    
    def _on_definition_response(self, file_path: str, result: Any):
        """定义响应处理"""
        locations = []
        if isinstance(result, list):
            for loc in result:
                locations.append(Location.from_dict(loc))
        elif isinstance(result, dict):
            locations.append(Location.from_dict(result))
        
        self.definition_received.emit(file_path, locations)
    
    def request_references(self, file_path: str, line: int, character: int):
        """请求查找引用"""
        self._send_request("textDocument/references", {
            "textDocument": {"uri": self._path_to_uri(file_path)},
            "position": {"line": line, "character": character},
            "context": {"includeDeclaration": True}
        }, lambda result: self._on_references_response(file_path, result))
    
    def _on_references_response(self, file_path: str, result: Any):
        """引用响应处理"""
        locations = []
        if isinstance(result, list):
            for loc in result:
                locations.append(Location.from_dict(loc))
        
        self.references_received.emit(file_path, locations)
    
    def request_hover(self, file_path: str, line: int, character: int):
        """请求悬停信息"""
        self._send_request("textDocument/hover", {
            "textDocument": {"uri": self._path_to_uri(file_path)},
            "position": {"line": line, "character": character}
        }, lambda result: self._on_hover_response(file_path, line, character, result))
    
    def _on_hover_response(self, file_path: str, line: int, character: int, result: Any):
        """悬停响应处理"""
        hover_text = ""
        if result:
            contents = result.get("contents", "")
            if isinstance(contents, str):
                hover_text = contents
            elif isinstance(contents, list):
                hover_text = "\n".join(
                    c.get("value", "") if isinstance(c, dict) else str(c)
                    for c in contents
                )
            elif isinstance(contents, dict):
                hover_text = contents.get("value", "")
        
        self.hover_received.emit(file_path, hover_text, line, character)
    
    def _handle_diagnostics(self, params: Dict):
        """处理诊断通知"""
        uri = params.get("uri", "")
        file_path = self._uri_to_path(uri)
        
        diagnostics = []
        for diag in params.get("diagnostics", []):
            diagnostics.append(Diagnostic.from_dict(diag))
        
        self.diagnostics_received.emit(file_path, diagnostics)
    
    # ============================================================
    # ★ L3 高级 LSP 操作
    # ============================================================
    
    def request_workspace_symbol(self, query: str):
        """工作区符号搜索（workspace/symbol）"""
        self._send_request("workspace/symbol", {"query": query},
                           lambda r: self._on_workspace_symbol_response(query, r))
    
    def _on_workspace_symbol_response(self, query: str, result: Any):
        symbols = []
        if isinstance(result, list):
            for item in result:
                if isinstance(item, dict):
                    symbols.append({
                        "name": item.get("name", ""),
                        "kind": item.get("kind", 0),
                        "location": item.get("location", {}),
                        "containerName": item.get("containerName", ""),
                    })
        self.workspace_symbol_received.emit(query, symbols)
    
    def request_document_symbol(self, file_path: str):
        """文档符号（textDocument/documentSymbol）"""
        self._send_request("textDocument/documentSymbol", {
            "textDocument": {"uri": self._path_to_uri(file_path)}
        }, lambda r: self._on_document_symbol_response(file_path, r))
    
    def _on_document_symbol_response(self, file_path: str, result: Any):
        symbols = []
        if isinstance(result, list):
            for item in result:
                if isinstance(item, dict):
                    symbols.append({
                        "name": item.get("name", ""),
                        "kind": item.get("kind", 0),
                        "range": item.get("range", {}),
                        "selectionRange": item.get("selectionRange", {}),
                        "children": item.get("children", []),
                    })
        self.document_symbol_received.emit(file_path, symbols)
    
    def request_implementation(self, file_path: str, line: int, character: int):
        """跳转实现（textDocument/implementation）"""
        self._send_request("textDocument/implementation", {
            "textDocument": {"uri": self._path_to_uri(file_path)},
            "position": {"line": line, "character": character}
        }, lambda r: self._on_implementation_response(file_path, r))
    
    def _on_implementation_response(self, file_path: str, result: Any):
        locations = []
        if isinstance(result, list):
            for loc in result:
                if isinstance(loc, dict):
                    locations.append(Location.from_dict(loc))
        self.implementation_received.emit(file_path, locations)
    
    def request_prepare_call_hierarchy(self, file_path: str, line: int, character: int):
        """准备调用层次（textDocument/prepareCallHierarchy）"""
        self._send_request("textDocument/prepareCallHierarchy", {
            "textDocument": {"uri": self._path_to_uri(file_path)},
            "position": {"line": line, "character": character}
        }, lambda r: self._on_call_hierarchy_response(file_path, r))
    
    def request_incoming_calls(self, item: dict):
        """来电调用（callHierarchy/incomingCalls）"""
        self._send_request("callHierarchy/incomingCalls", {"item": item},
                           lambda r: self._on_call_hierarchy_response("incoming", r))
    
    def request_outgoing_calls(self, item: dict):
        """去电调用（callHierarchy/outgoingCalls）"""
        self._send_request("callHierarchy/outgoingCalls", {"item": item},
                           lambda r: self._on_call_hierarchy_response("outgoing", r))
    
    def _on_call_hierarchy_response(self, file_path: str, result: Any):
        items = []
        if isinstance(result, list):
            items = result
        self.call_hierarchy_received.emit(file_path, items)
    
    # ============================================================
    # 工具方法
    # ============================================================
    
    def _path_to_uri(self, path: str) -> str:
        """路径转URI"""
        abs_path = os.path.abspath(path)
        if os.name == 'nt':
            return "file:///" + abs_path.replace("\\", "/")
        return "file://" + abs_path
    
    def _uri_to_path(self, uri: str) -> str:
        """URI转路径"""
        if uri.startswith("file:///"):
            return uri[8:].replace("/", "\\") if os.name == 'nt' else uri[7:]
        return uri
    
    def _on_process_error(self, error):
        """进程错误处理"""
        self.error_occurred.emit(f"语言服务器错误: {error}")
    
    def _on_process_finished(self, exit_code, exit_status):
        """进程结束处理"""
        self._initialized = False


# ============================================================
# LSP 管理器
# ============================================================

class LSPManager(QObject):
    """
    LSP 管理器 — 管理多个语言服务器
    
    功能：
    - 自动启动/停止语言服务器
    - 根据文件类型路由请求
    - 统一信号接口
    """
    
    # 信号（转发自各个LSPClient）
    completion_received = pyqtSignal(str, list)
    definition_received = pyqtSignal(str, list)
    references_received = pyqtSignal(str, list)
    diagnostics_received = pyqtSignal(str, list)
    hover_received = pyqtSignal(str, str, int, int)
    server_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    
    # 文件扩展名到语言的映射
    LANGUAGE_MAP = {
        ".py": "python",
        ".pyw": "python",
        ".js": "javascript",
        ".mjs": "javascript",
        ".cjs": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".jsx": "javascript",
        ".go": "go",
    }
    
    def __init__(self, project_root: str):
        super().__init__()
        self.project_root = project_root
        self._clients: Dict[str, LSPClient] = {}
        self._lock = threading.Lock()
        self._diagnostics_cache: Dict[str, list] = {}
        self.diagnostics_received.connect(self._cache_diagnostics)

    def _cache_diagnostics(self, file_path: str, diagnostics: list):
        self._diagnostics_cache[file_path] = diagnostics

    def get_diagnostics(self, file_path: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取缓存的诊断结果，file_path为None时返回所有文件的诊断"""
        if file_path:
            diags = self._diagnostics_cache.get(file_path, [])
        else:
            diags = []
            for fp, dlist in self._diagnostics_cache.items():
                for d in dlist:
                    if hasattr(d, 'to_dict'):
                        entry = d.to_dict()
                        entry["file"] = fp
                        diags.append(entry)
                    elif isinstance(d, dict):
                        d["file"] = fp
                        diags.append(d)
        result = []
        for d in diags[:20]:
            if hasattr(d, 'to_dict'):
                result.append(d.to_dict())
            elif isinstance(d, dict):
                result.append(d)
            else:
                result.append({"message": str(d)})
        return result
    
    def get_language(self, file_path: str) -> Optional[str]:
        """根据文件扩展名获取语言"""
        ext = os.path.splitext(file_path)[1].lower()
        return self.LANGUAGE_MAP.get(ext)
    
    def start_server(self, language_id: str) -> bool:
        """启动语言服务器"""
        with self._lock:
            if language_id in self._clients:
                return self._clients[language_id].is_initialized
            
            client = LSPClient(language_id, self.project_root)
            
            # 连接信号
            client.initialized.connect(lambda: self.server_ready.emit(language_id))
            client.completion_received.connect(self.completion_received.emit)
            client.definition_received.connect(self.definition_received.emit)
            client.references_received.connect(self.references_received.emit)
            client.diagnostics_received.connect(self.diagnostics_received.emit)
            client.hover_received.connect(self.hover_received.emit)
            client.error_occurred.connect(self.error_occurred.emit)
            
            self._clients[language_id] = client
            return client.start()
    
    def stop_server(self, language_id: str):
        """停止语言服务器"""
        with self._lock:
            if language_id in self._clients:
                self._clients[language_id].stop()
                del self._clients[language_id]
    
    def stop_all(self):
        """停止所有语言服务器"""
        with self._lock:
            for client in self._clients.values():
                client.stop()
            self._clients.clear()
    
    def open_document(self, file_path: str, content: str):
        """打开文档"""
        language_id = self.get_language(file_path)
        if not language_id:
            return
        
        if language_id not in self._clients:
            self.start_server(language_id)
        
        if language_id in self._clients:
            self._clients[language_id].open_document(file_path, content)
    
    def close_document(self, file_path: str):
        """关闭文档"""
        language_id = self.get_language(file_path)
        if language_id and language_id in self._clients:
            self._clients[language_id].close_document(file_path)
    
    def change_document(self, file_path: str, content: str, version: int = 1):
        """文档变更"""
        language_id = self.get_language(file_path)
        if language_id and language_id in self._clients:
            self._clients[language_id].change_document(file_path, content, version)
    
    def request_completion(self, file_path: str, line: int, character: int):
        """请求代码补全"""
        language_id = self.get_language(file_path)
        if language_id and language_id in self._clients:
            self._clients[language_id].request_completion(file_path, line, character)
    
    def request_definition(self, file_path: str, line: int, character: int):
        """请求跳转定义"""
        language_id = self.get_language(file_path)
        if language_id and language_id in self._clients:
            self._clients[language_id].request_definition(file_path, line, character)
    
    def request_references(self, file_path: str, line: int, character: int):
        """请求查找引用"""
        language_id = self.get_language(file_path)
        if language_id and language_id in self._clients:
            self._clients[language_id].request_references(file_path, line, character)
    
    def request_hover(self, file_path: str, line: int, character: int):
        """请求悬停信息"""
        language_id = self.get_language(file_path)
        if language_id and language_id in self._clients:
            self._clients[language_id].request_hover(file_path, line, character)
    
    def is_server_ready(self, language_id: str) -> bool:
        """检查语言服务器是否就绪"""
        return language_id in self._clients and self._clients[language_id].is_initialized