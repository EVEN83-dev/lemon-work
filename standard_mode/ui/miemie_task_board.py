# -*- coding: utf-8 -*-
"""标准模式侧「咩咩任务看板」面板（ui 层，不触碰 standard_mode/core）。

职责：
- 总指挥派发按钮：POST /api/dispatch 下发 tool:web_fetch 给咩咩（复用 miemie/dispatch.py）。
- 看板展示：task_id / 状态 / 最新 token / 流式摘要（★ M16: SSE 长连接实时消费）。
- 任务列表：GET /api/tasks 刷新历史派发。

★ M16: 用 QNetworkAccessManager 消费 GET /api/task/<id>/stream 的 SSE 实时流，
token 事件逐 token 追加到显示区，done 事件结束连接；心跳 ping 行忽略；
SSE 断线自动重连（最多 3 次），仍失败退回 QTimer 轮询 /api/task/<id> 兜底。
保留既有「自动滚动到底部」「复制完整回复」开关功能。

结构类请求（/api/dispatch、/api/tasks）走标准库 urllib；流式请求走 Qt 网络栈。
"""
import json
import urllib.request

from PyQt5.QtCore import QTimer, QUrl
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt5.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit,
    QVBoxLayout, QWidget,
)
from ui.design.tokens import Lemon


def parse_sse_events(buffer: str):
    """解析 SSE 文本缓冲，返回 (events, remaining_buffer)。

    - 事件以 `data: {...}\\n\\n` 为帧（空行分隔）；`\\n` 换行边界宽松处理。
    - 心跳 ping / 注释行 / 未知行静默忽略。
    - remaining 是尚未凑齐一帧的尾部字节，下一次继续拼接。
    独立成纯函数便于离屏单测。
    """
    events = []
    remaining = buffer
    # 按空行（\n\n 或 \r\n\r\n）切帧
    while True:
        idx = remaining.find("\n\n")
        if idx < 0:
            idx2 = remaining.find("\r\n\r\n")
            if idx2 < 0:
                break
            frame, _, rest = remaining.partition("\r\n\r\n")
        else:
            frame, _, rest = remaining.partition("\n\n")
        remaining = rest
        for line in frame.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload:
                continue
            try:
                obj = json.loads(payload)
            except (ValueError, TypeError):
                continue
            if isinstance(obj, dict):
                events.append(obj)
    return events, remaining


class MiemieTaskBoard(QWidget):
    def __init__(self, api_host="127.0.0.1", api_port=7780, parent=None):
        super().__init__(parent)
        self._host = api_host
        self._port = api_port
        self._current_task = None
        self._poll_ms = 250

        # ★ M16: SSE 网络栈 + 重连状态
        self._sse_nam = QNetworkAccessManager(self)
        self._sse_reply = None
        self._sse_buffer = ""
        self._sse_retries = 0
        self._sse_max_retries = 3
        self._sse_on = False  # 当前是否处于 SSE 长连接模式（决定是否走轮询）
        # ★ 403T-4: 占位引用（init 下方构建 QLabel，此处仅做安全哨兵）
        self._placeholder = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ---- 顶部：总指挥派发 ----
        head = QHBoxLayout()
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText(
            "要抓取的网页 URL（如 https://example.com）"
        )
        self._url_edit.setText("https://example.com")
        self._dispatch_btn = QPushButton("总指挥派发 web_fetch")
        self._dispatch_btn.setToolTip("点此由总指挥向咩咩派发 tool:web_fetch 任务")
        self._dispatch_btn.clicked.connect(self.dispatch_web_fetch)
        head.addWidget(QLabel("URL:"))
        head.addWidget(self._url_edit, 1)
        head.addWidget(self._dispatch_btn)
        root.addLayout(head)

        # ---- 状态行 ----
        self._status_label = QLabel("状态：待命（点上方按钮派发）")
        self._status_label.setStyleSheet(f"color:{Lemon.BRAND_ORANGE};")
        root.addWidget(self._status_label)

        # ---- 占位提示（403T-4 Fix2: SSE 外部依赖占位，在流式摘要区上方） ----
        self._placeholder = QLabel(
            "🐑 咩咩任务看板 \u00b7 正在连接 127.0.0.1:7780 \u2026 "
            "请在 PowerShell 运行 `miemie` 启动本地引擎；启动后 5 秒内自动重连。"
        )
        self._placeholder.setObjectName("miemie_placeholder")
        self._placeholder.setStyleSheet(
            f"color:{Lemon.DARK_TEXT_3}; padding:12px; font-size:13px;"
        )
        self._placeholder.setWordWrap(True)
        root.addWidget(self._placeholder)
        # ★ 5 秒单次/周期重试定时器（不无限快速循环）
        self._retry_timer = QTimer(self)
        self._retry_timer.setInterval(5000)
        self._retry_timer.timeout.connect(self._retry_connect)
        self._retry_timer.start()

        # ---- 流式摘要 ----
        self._summary = QTextEdit()
        self._summary.setReadOnly(True)
        self._summary.setPlaceholderText("咩咩的流式摘要将在此实时显示……")
        root.addWidget(self._summary, 1)

        # ---- 工具栏：复制完整回复 + 自动滚动开关 ----
        tool_row = QHBoxLayout()
        self._copy_btn = QPushButton("复制完整回复")
        self._copy_btn.setToolTip("把上方流式摘要的完整回复复制到剪贴板")
        self._copy_btn.clicked.connect(self.copy_full_reply)
        self._auto_scroll = QCheckBox("自动滚动到底部")
        self._auto_scroll.setChecked(True)
        tool_row.addWidget(self._copy_btn)
        tool_row.addStretch(1)
        tool_row.addWidget(self._auto_scroll)
        root.addLayout(tool_row)

        # ---- 任务列表 ----
        self._list = QTextEdit()
        self._list.setReadOnly(True)
        self._list.setMaximumHeight(120)
        root.addWidget(QLabel("历史派发："))
        root.addWidget(self._list)

        # ---- 占位隐藏标记：任意一次网络成功后不再显示 ----
        self._ever_connected = False

        # ---- 轮询定时器（★ M16: 仅作为 SSE 断线后的降级兜底） ----
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

    # ---------------- HTTP 封装（urllib，零跨包依赖） ----------------
    def _post(self, path, payload):
        url = f"http://{self._host}:{self._port}{path}"
        try:
            req = urllib.request.Request(
                url, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    def _get(self, path):
        url = f"http://{self._host}:{self._port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            return None

    # ---------------- 交互 ----------------
    def dispatch_web_fetch(self):
        url = self._url_edit.text().strip()
        if not url:
            self._status_label.setText("状态：请先填写 URL")
            return
        self._summary.clear()
        resp = self._post(
            "/api/dispatch",
            {"command": "tool:web_fetch", "args": {"url": url}, "source": "standard"},
        )
        if "task_id" in resp:
            self._current_task = resp["task_id"]
            self._status_label.setText(
                "已派发 task_id=%s · 来源=%s · 状态=%s · 正在真实抓取+流式生成摘要…"
                % (resp["task_id"], resp.get("source", "standard"), resp.get("status"))
            )
            # ★ M16: 优先 SSE 长连接实时消费；断线自动重连（≤3 次），
            #   仍失败再退回 QTimer 轮询兜底。
            self._timer.stop()
            self._sse_buffer = ""
            self._sse_retries = 0
            self._sse_on = True
            self._open_sse()
            self.refresh_list()
        else:
            self._status_label.setText("派发失败：%s" % resp.get("error", "未知错误"))

    # ---------------- ★ M16: SSE 实时流消费 ----------------
    def _open_sse(self):
        """发起 GET /api/task/<id>/stream 的 SSE 长连接（QNetworkAccessManager）。"""
        if not self._current_task:
            return
        url = QUrl("http://%s:%d/api/task/%s/stream"
                   % (self._host, self._port, self._current_task))
        req = QNetworkRequest(url)
        req.setRawHeader(b"Accept", b"text/event-stream")
        self._sse_reply = self._sse_nam.get(req)
        self._sse_reply.readyRead.connect(self._on_sse_ready)
        self._sse_reply.finished.connect(self._on_sse_finished)

    def _on_sse_ready(self):
        """SSE 数据块到达：累积字节，按行解析 data: 前缀的 SSE 事件。"""
        reply = self._sse_reply
        if reply is None:
            return
        try:
            raw = bytes(reply.readAll()).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return
        self._sse_buffer += raw
        events, self._sse_buffer = parse_sse_events(self._sse_buffer)
        for evt in events:
            self._handle_sse_event(evt)

    def _handle_sse_event(self, evt):
        """处理一条 SSE 事件：token 追加 / status 更新 / done 收尾 / ping 忽略。"""
        # ★ 403T-4: 任意事件到达即证明连接成功，隐藏占位
        if not self._ever_connected:
            self._ever_connected = True
            if self._placeholder is not None:
                self._placeholder.hide()
            self._retry_timer.stop()
        etype = evt.get("type")
        if etype == "token" or ("token" in evt and etype is None):
            tok = evt.get("token", "")
            if tok:
                self._summary.insertPlainText(tok)
                if self._auto_scroll.isChecked():
                    sb = self._summary.verticalScrollBar()
                    sb.setValue(sb.maximum())
        elif etype == "status":
            self._status_label.setText(
                "task=%s · 来源=%s · 状态=%s · SSE 实时"
                % (self._current_task, "standard", evt.get("status", "")))
        elif etype == "done":
            self._on_sse_done()
        elif etype == "ping":
            pass  # 心跳 ping：忽略
        elif etype == "error":
            self._status_label.setText("SSE 错误：%s" % evt.get("error", "未知"))

    def _on_sse_done(self):
        """done 事件：正常结束 SSE，停连接并刷新列表。"""
        self._sse_on = False
        self._close_sse()
        self._status_label.setText(
            "task=%s · 来源=%s · 状态=完成 · SSE 已结束"
            % (self._current_task, "standard"))
        self.refresh_list()

    # ---------------- ★ 403T-4: SSE 占位重试 ----------------
    def _retry_connect(self):
        """QTimer 5s 周期触发的占位重连：探测本地 127.0.0.1:7780 是否已可用。"""
        if self._ever_connected:
            return
        # 仅当有未完成任务且 SSE 未激活时才探测
        if not self._current_task or self._sse_on:
            return
        rec = self._get("/api/task/%s" % self._current_task)
        if rec and not rec.get("done"):
            # 占位仍然显示，定时器下次再试
            self._placeholder.show()
            self._status_label.setText(
                "task=%s · 等待本地引擎 127.0.0.1:%d 就绪…"
                % (self._current_task, self._port))

    def _on_sse_finished(self):
        """SSE 连接结束（正常 done 或异常断线）。断线时尝试重连（≤3 次）。"""
        if not self._sse_on:
            return
        done = self._current_task and self._sse_fetch_done(self._current_task)
        if done:
            self._on_sse_done()
            return
        # 断线重连
        self._close_sse()
        if self._sse_retries < self._sse_max_retries:
            self._sse_retries += 1
            self._status_label.setText(
                "SSE 断线，重连中…（%d/%d）" % (self._sse_retries, self._sse_max_retries))
            QTimer.singleShot(800, self._open_sse)
        else:
            # 重连耗尽 → 退回 QTimer 轮询兜底
            self._sse_on = False
            self._status_label.setText("SSE 连接失败，退回轮询模式…")
            self._timer.start(self._poll_ms)

    def _sse_fetch_done(self, task_id):
        """轮询一次判断任务是否已结束（供 SSE 断线时确认收尾）。"""
        rec = self._get("/api/task/%s" % task_id)
        return bool(rec and rec.get("done"))

    def _close_sse(self):
        """关闭当前 SSE 网络请求（防泄漏）。"""
        if self._sse_reply is not None:
            try:
                self._sse_reply.readyRead.disconnect(self._on_sse_ready)
            except (RuntimeError, TypeError):
                pass
            try:
                self._sse_reply.finished.disconnect(self._on_sse_finished)
            except (RuntimeError, TypeError):
                pass
            try:
                self._sse_reply.abort()
            except RuntimeError:
                pass
            self._sse_reply = None
        self._sse_buffer = ""

    # ---------------- 轮询降级（★ M16: 仅 SSE 失败后启用） ----------------
    def _poll(self):
        if not self._current_task or self._sse_on:
            return
        rec = self._get("/api/task/%s" % self._current_task)
        if not rec:
            return
        self._status_label.setText(
            "task=%s · 来源=%s · 状态=%s · tokens=%d · 完成=%s"
            % (rec["task_id"], rec.get("source", ""), rec["status"],
               rec["tokens_count"], rec["done"])
        )
        # 流式摘要：直接展示已累积内容（轮询即产生打字机效果）
        self._summary.setPlainText(rec.get("summary", ""))
        # 自动滚动到底部（开关受控）
        if self._auto_scroll.isChecked():
            sb = self._summary.verticalScrollBar()
            sb.setValue(sb.maximum())
        if rec.get("done"):
            self._timer.stop()
            self.refresh_list()

    def copy_full_reply(self):
        text = self._summary.toPlainText()
        if not text:
            self._status_label.setText("状态：暂无回复可复制")
            return
        try:
            from PyQt5.QtWidgets import QApplication
            QApplication.clipboard().setText(text)
            self._status_label.setText("状态：已复制完整回复（%d 字）" % len(text))
        except Exception as e:  # noqa: BLE001
            self._status_label.setText("复制失败：%s" % e)

    def refresh_list(self):
        data = self._get("/api/tasks")
        if not data:
            return
        lines = []
        for t in data.get("tasks", [])[:20]:
            lines.append(
                "%s | %s | src=%s | status=%s | tokens=%d | %s"
                % (t["task_id"], t["command"], t.get("source", ""),
                   t["status"], t["tokens_count"], t["updated_at"])
            )
        self._list.setPlainText("\n".join(lines) if lines else "（暂无派发记录）")

    def closeEvent(self, event):
        """面板关闭时停止定时器并释放 SSE 网络请求，防止后台泄漏。"""
        self._timer.stop()
        self._sse_on = False
        self._close_sse()
        super().closeEvent(event)
