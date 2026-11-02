# -*- coding: utf-8 -*-
"""
Agent 容器 — 管理 MIMO Code 后端 + 文件变更监控 + Diff 计算 + 结果分发
架构：
  用户输入 → AgentContainer → MIMO Code (小米AI) → 处理 → AgentContainer → UI面板
新功能：
  - 文件快照 → Diff 计算（增加/删除/修改）
  - 思考过程解析（Thinking blocks）
  - 工具调用解析
"""

import os
import re
import difflib
from PyQt5.QtCore import QObject, QProcess, pyqtSignal, QFileSystemWatcher

# ============================================================
# 小米AI MIMO Code 路径配置
# ============================================================
_XIAOMI_AI = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "小米AI")
_MIMO_NODE_GLOBAL = os.path.join(_XIAOMI_AI, "node_global")
MIMO_EXE_XIAOMI = os.path.join(_MIMO_NODE_GLOBAL, "node_modules", "@mimo-ai", "mimocode-windows-x64", "bin", "mimo.exe")

XDG_DIRS_XIAOMI = {
    'XDG_CACHE_HOME': os.path.join(_MIMO_NODE_GLOBAL, 'cache'),
    'XDG_DATA_HOME': os.path.join(_MIMO_NODE_GLOBAL, 'data'),
    'XDG_STATE_HOME': os.path.join(_MIMO_NODE_GLOBAL, 'state'),
    'XDG_CONFIG_HOME': os.path.join(_MIMO_NODE_GLOBAL, 'config'),
}

ANSI_COLORS = {
    '30': 'Lemon.SYNTAX_COMMENT', '31': 'Lemon.ACCENT_RED', '32': 'Lemon.ACCENT_GREEN', '33': 'Lemon.STATUS_WARNING',
    '34': 'Lemon.ACCENT_BLUE', '35': 'Lemon.ACCENT_PURPLE', '36': 'Lemon.STATUS_RUNNING', '37': 'Lemon.PLACEHOLDER',
    '90': 'Lemon.SECONDARY', '91': 'Lemon.ACCENT_RED', '92': 'Lemon.ACCENT_GREEN', '93': 'Lemon.DARK_YELLOW_LIGHT',
    '94': 'Lemon.ACCENT_BLUE', '95': 'Lemon.ACCENT_PINK', '96': 'Lemon.STATUS_RUNNING', '97': 'Lemon.SURFACE',
}

EXCLUDE_DIRS = {'.git', '.venv', 'venv', '__pycache__', '.mimocode', 'cache', 'data', 'state', 'config', 'node_modules', '.idea', 'bin'}


def parse_ansi_to_html(text):
    parts = re.split(r'\033\[(\d+(?:;\d+)*)m', text)
    result = []
    i = 0
    while i < len(parts):
        if i + 1 < len(parts) and parts[i + 1]:
            codes = parts[i + 1].split(';')
            color = 'Lemon.PLACEHOLDER'
            bold = False
            for code in codes:
                if code == '0':
                    color = 'Lemon.PLACEHOLDER'; bold = False
                elif code in ANSI_COLORS:
                    color = ANSI_COLORS[code]
                elif code == '1':
                    bold = True
            escaped = parts[i].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            style = f'color:{color};'
            if bold:
                style += 'font-weight:bold;'
            result.append(f'<span style="{style}">{escaped}</span>')
            i += 2
        else:
            escaped = parts[i].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            result.append(escaped)
            i += 1
    return ''.join(result)


def compute_diff(old_text, new_text):
    """计算行级 diff，返回 (type, line) 列表"""
    old_lines = old_text.splitlines(keepends=True) if old_text else []
    new_lines = new_text.splitlines(keepends=True) if new_text else []
    diff = list(difflib.ndiff(old_lines, new_lines))
    result = []
    for d in diff:
        if d.startswith('  '):
            result.append(('same', d[2:].rstrip('\n')))
        elif d.startswith('- '):
            result.append(('remove', d[2:].rstrip('\n')))
        elif d.startswith('+ '):
            result.append(('add', d[2:].rstrip('\n')))
        elif d.startswith('? '):
            continue
    return result


def parse_mimo_changes(text):
    """从 MIMO Code 输出中解析文件变更"""
    changes = []
    patterns = [
        r'(?:创建|create|write|wrote|created)\s+(?:文件\s*)?[`"\']?([^\s`"\'\n]+\.(?:py|js|ts|json|yaml|yml|html|css|md|txt))[`"\']?',
        r'(?:修改|update|modify|edit|changed|updated)\s+(?:文件\s*)?[`"\']?([^\s`"\'\n]+\.(?:py|js|ts|json|yaml|yml|html|css|md|txt))[`"\']?',
        r'(?:删除|delete|remove|deleted)\s+(?:文件\s*)?[`"\']?([^\s`"\'\n]+\.(?:py|js|ts|json|yaml|yml|html|css|md|txt))[`"\']?',
        r'\$\s*(?:cat|echo|touch|mkdir|write|tee)\s+.*?[>\|]\s*([^\s\n]+\.(?:py|js|ts|json|yaml|yml|html|css|md|txt))',
        r'File\s+(?:written|created|modified|changed):\s*[`"\']?([^\s`"\'\n]+\.(?:py|js|ts|json|yaml|yml|html|css|md|txt))[`"\']?',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            filename = match.group(1).strip()
            if filename not in [c['path'] for c in changes]:
                changes.append({'path': filename, 'status': 'modified'})
    return changes


def classify_output(text):
    """将 MIMO Code 输出分类为：思考 / 工具调用 / 普通输出"""
    blocks = []
    lines = text.split('\n')
    current_type = 'normal'
    current_lines = []

    for line in lines:
        ls = line.strip()
        # 检测思考块
        if re.search(r'🤔|thinking|thought|思考|分析', ls, re.IGNORECASE) and not ls.startswith('$'):
            if current_lines:
                blocks.append({'type': current_type, 'text': '\n'.join(current_lines)})
            current_type = 'thinking'
            current_lines = [line]
        # 检测工具调用
        elif ls.startswith('$ '):
            if current_lines:
                blocks.append({'type': current_type, 'text': '\n'.join(current_lines)})
            current_type = 'tool'
            current_lines = [line]
        # 检测构建模式
        elif re.search(r'>\s*build|>?\s*mimo-auto', ls, re.IGNORECASE):
            if current_lines:
                blocks.append({'type': current_type, 'text': '\n'.join(current_lines)})
            current_type = 'mode'
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        blocks.append({'type': current_type, 'text': '\n'.join(current_lines)})

    return blocks


class AgentContainer(QObject):
    """管理 MIMO Code 后端 + 文件监控 + Diff 计算 + 结果分发"""

    output_received = pyqtSignal(str)          # 原始输出 (HTML)
    thinking_received = pyqtSignal(str)         # 思考过程 (HTML)
    tool_output_received = pyqtSignal(str)      # 工具输出 (HTML)
    task_started = pyqtSignal(str)
    task_finished = pyqtSignal(int)
    files_changed = pyqtSignal(list)            # 文件变更列表
    diff_computed = pyqtSignal(str, str, list)  # (file_path, new_content, diff_lines)
    file_content_changed = pyqtSignal(str)

    def __init__(self, project_path=None):
        super().__init__()
        self.project_path = project_path or os.getcwd()
        self._process = None
        self._output_buffer = ""
        self._file_snapshots = {}  # {rel_path: content} 任务前快照
        self._watcher = None
        self._setup_watcher()

    def _setup_watcher(self):
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._on_dir_changed)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._watch_project()

    def _watch_project(self):
        try:
            self._watcher.addPath(self.project_path)
            for root, dirs, files in os.walk(self.project_path):
                dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
                for f in files:
                    fp = os.path.join(root, f)
                    self._watcher.addPath(fp)
        except Exception:
            pass

    def _on_dir_changed(self, path):
        self._watch_project()

    def _on_file_changed(self, path):
        rel = os.path.relpath(path, self.project_path)
        self.file_content_changed.emit(rel)

    def set_project_path(self, path):
        self.project_path = path
        self._watch_project()

    def _snapshot_files(self):
        """快照所有项目文件（用于 Diff 对比）"""
        self._file_snapshots = {}
        for root, dirs, files in os.walk(self.project_path):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for f in files:
                fp = os.path.join(root, f)
                rel = os.path.relpath(fp, self.project_path)
                try:
                    with open(fp, 'r', encoding='utf-8', errors='replace') as fh:
                        self._file_snapshots[rel] = fh.read()
                except Exception:
                    pass

    def _compute_diffs(self):
        """计算所有变更文件的 diff"""
        for root, dirs, files in os.walk(self.project_path):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for f in files:
                fp = os.path.join(root, f)
                rel = os.path.relpath(fp, self.project_path)
                old_content = self._file_snapshots.get(rel, '')
                try:
                    with open(fp, 'r', encoding='utf-8', errors='replace') as fh:
                        new_content = fh.read()
                except Exception:
                    continue
                if old_content != new_content:
                    diff_lines = compute_diff(old_content, new_content)
                    self.diff_computed.emit(rel, new_content, diff_lines)
        # ★ 清除快照释放内存
        self._file_snapshots.clear()

    def execute(self, command):
        if self._process and self._process.state() != QProcess.NotRunning:
            self._process.kill()
            self._process.waitForFinished(2000)

        self._snapshot_files()
        self._output_buffer = ""
        self.task_started.emit(command)

        self._process = QProcess(self)
        self._process.setWorkingDirectory(self.project_path)
        # 关键：使用 SeparateChannels，stdin 可写入
        self._process.setProcessChannelMode(QProcess.SeparateChannels)

        env = self._process.processEnvironment()
        for key, val in XDG_DIRS_XIAOMI.items():
            env.insert(key, val)
            os.makedirs(os.path.join(val, 'mimocode'), exist_ok=True)
        self._process.setProcessEnvironment(env)

        self._process.readyReadStandardOutput.connect(self._on_stdout)
        self._process.readyReadStandardError.connect(self._on_stderr)
        self._process.finished.connect(self._on_finished)

        args = ["run", "--dangerously-skip-permissions", "--thinking", command]
        self._process.start(MIMO_EXE_XIAOMI, args)

        # 关键：写入 stdin 然后关闭写入通道，模拟 echo "y" | mimo run
        self._process.write(b"y\n")
        self._process.closeWriteChannel()

    def execute_raw(self, command):
        if self._process and self._process.state() != QProcess.NotRunning:
            self._process.kill()
            self._process.waitForFinished(2000)

        self._snapshot_files()
        self._output_buffer = ""
        self.task_started.emit(command)

        self._process = QProcess(self)
        self._process.setWorkingDirectory(self.project_path)
        self._process.setProcessChannelMode(QProcess.MergedChannels)

        env = self._process.processEnvironment()
        for key, val in XDG_DIRS_XIAOMI.items():
            env.insert(key, val)
        self._process.setProcessEnvironment(env)

        self._process.readyReadStandardOutput.connect(self._on_stdout)
        self._process.finished.connect(self._on_finished)

        args = command.split()
        self._process.start(MIMO_EXE_XIAOMI, args)

    def _on_stdout(self):
        if self._process:
            data = self._process.readAllStandardOutput().data().decode("utf-8", errors="replace")
            self._output_buffer += data

            # 分类输出
            blocks = classify_output(data)
            for block in blocks:
                html = parse_ansi_to_html(block['text'])
                self.output_received.emit(html)
                if block['type'] == 'thinking':
                    self.thinking_received.emit(html)
                elif block['type'] == 'tool':
                    self.tool_output_received.emit(html)

    def _on_stderr(self):
        """stderr 输出（日志等）也当作普通输出处理"""
        if self._process:
            data = self._process.readAllStandardError().data().decode("utf-8", errors="replace")
            self._output_buffer += data
            blocks = classify_output(data)
            for block in blocks:
                html = parse_ansi_to_html(block['text'])
                self.output_received.emit(html)
                if block['type'] == 'thinking':
                    self.thinking_received.emit(html)
                elif block['type'] == 'tool':
                    self.tool_output_received.emit(html)

    def _on_finished(self, code, status):
        self.task_finished.emit(code)

        if code == 0 and self._output_buffer:
            self._compute_diffs()
            changes = parse_mimo_changes(self._output_buffer)
            if changes:
                self.files_changed.emit(changes)

        self._output_buffer = ""

    def is_running(self):
        return self._process and self._process.state() == QProcess.Running

    def cancel(self):
        if self._process and self._process.state() == QProcess.Running:
            self._process.kill()
            self._process.waitForFinished(2000)

    def get_mimo_path(self):
        return MIMO_EXE_XIAOMI

    def get_xdg_dirs(self):
        return XDG_DIRS_XIAOMI