"""
H-A1 Bridge: LSP Manager bridge for bridge_server context.
Wraps shared/lsp_client.LSPManager for non-Qt (headless) usage.
When Qt is available, uses real LSPManager; otherwise provides graceful fallback.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_LSP_MANAGER: Optional[Any] = None


def get_lsp_manager() -> Any:
    global _LSP_MANAGER
    if _LSP_MANAGER is None:
        _LSP_MANAGER = _create_lsp_manager()
    return _LSP_MANAGER


def _create_lsp_manager() -> Any:
    try:
        from PyQt5.QtCore import QObject
        from shared.lsp_client import LSPManager
        project_root = os.getcwd()
        manager = LSPManager(project_root)
        manager._diagnostics_cache: Dict[str, List[Dict]] = {}
        manager._completion_cache: Dict[str, List[Dict]] = {}

        def _on_diagnostics(file_path: str, diagnostics: list) -> None:
            items = []
            for d in diagnostics:
                if hasattr(d, 'to_dict'):
                    items.append(d.to_dict())
                elif isinstance(d, dict):
                    items.append(d)
                else:
                    items.append({
                        "range": {
                            "start": {"line": d.range.start.line, "character": d.range.start.character},
                            "end": {"line": d.range.end.line, "character": d.range.end.character},
                        },
                        "message": d.message,
                        "severity": d.severity,
                        "source": d.source,
                    })
            manager._diagnostics_cache[file_path] = items

        def _on_completion(file_path: str, items: list) -> None:
            result = []
            for item in items:
                if hasattr(item, 'label'):
                    result.append({
                        "label": item.label,
                        "kind": item.kind,
                        "detail": item.detail,
                        "documentation": item.documentation,
                    })
                elif isinstance(item, dict):
                    result.append(item)
            manager._completion_cache[file_path] = result

        manager.diagnostics_received.connect(_on_diagnostics)
        manager.completion_received.connect(_on_completion)
        logger.info("LSPManager (Qt) initialized with diagnostic/completion caching")
        return manager
    except ImportError:
        logger.info("PyQt5 not available, using HeadlessLSPManager fallback")
        return HeadlessLSPManager()
    except Exception as e:
        logger.warning(f"LSPManager init failed ({e}), using HeadlessLSPManager fallback")
        return HeadlessLSPManager()


class HeadlessLSPManager:
    """Fallback LSP manager when Qt is not available.
    Uses subprocess to run language servers in a limited fashion,
    or returns graceful fallback messages.
    """

    LANGUAGE_SERVERS = {
        "python": {"command": "pyright-langserver", "args": ["--stdio"]},
        "javascript": {"command": "typescript-language-server", "args": ["--stdio"]},
        "typescript": {"command": "typescript-language-server", "args": ["--stdio"]},
        "go": {"command": "gopls", "args": []},
    }

    EXT_MAP = {
        ".py": "python", ".pyw": "python",
        ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
        ".ts": "typescript", ".tsx": "typescript", ".jsx": "javascript",
        ".go": "go",
    }

    def __init__(self):
        self._clients: Dict[str, Any] = {}
        self._diagnostics_cache: Dict[str, List[Dict]] = {}
        self._completion_cache: Dict[str, List[Dict]] = {}
        self._ready: Dict[str, bool] = {}

    def get_language(self, file_path: str) -> Optional[str]:
        ext = os.path.splitext(file_path)[1].lower()
        return self.EXT_MAP.get(ext)

    def start_server(self, language_id: str) -> bool:
        if language_id not in self.LANGUAGE_SERVERS:
            logger.warning(f"No LSP config for language: {language_id}")
            return False
        config = self.LANGUAGE_SERVERS[language_id]
        cmd = config["command"]
        try:
            check_cmd = ["where", cmd] if os.name == "nt" else ["which", cmd]
            result = subprocess.run(check_cmd, capture_output=True, timeout=5)
            if result.returncode == 0:
                self._ready[language_id] = True
                logger.info(f"LSP server '{cmd}' found for {language_id}")
                return True
            else:
                self._ready[language_id] = False
                logger.info(f"LSP server '{cmd}' not installed for {language_id}")
                return False
        except Exception as e:
            self._ready[language_id] = False
            logger.debug(f"LSP check failed for {cmd}: {e}")
            return False

    def stop_server(self, language_id: str) -> None:
        self._ready.pop(language_id, None)

    def stop_all(self) -> None:
        self._ready.clear()

    def is_server_ready(self, language_id: str) -> bool:
        return self._ready.get(language_id, False)

    def open_document(self, file_path: str, content: str) -> None:
        pass

    def close_document(self, file_path: str) -> None:
        pass

    def change_document(self, file_path: str, content: str, version: int = 1) -> None:
        pass

    def request_completion(self, file_path: str, line: int, character: int) -> None:
        pass

    def request_definition(self, file_path: str, line: int, character: int) -> None:
        pass

    def request_references(self, file_path: str, line: int, character: int) -> None:
        pass

    def request_hover(self, file_path: str, line: int, character: int) -> None:
        pass
