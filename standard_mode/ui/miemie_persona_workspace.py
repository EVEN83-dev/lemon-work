# -*- coding: utf-8 -*-
"""
miemie_persona_workspace.py
===========================
咩咩分身 · 人格工作区（★ v4.7.0 P0：三栏工作区，替代 460px 小弹窗）

设计依据（第 247 章）：
    - 延续聊天心智模型：采集 → 分析 → 调节 三栏流水线
    - 多模态统一输入：拖拽 Word/PDF/PPT/图片、剪贴板图片组(10张/组)、@文件地址、文本
    - 复用现有后端：tool_persona_enqueue（异步队列）/ tool_persona_status（轮询）/
      _load_persona / _PERSONA_PATH（Big Five Layer1 档案）——不重造后端
    - 特征调节：Big5 滑块 + 子特征标签点选 + 画像描述编辑 → 写回档案

视觉：沿用底栏咩咩设计系统（暗色优雅风、橙色点睛、零 emoji）。
"""

import os
import json
import time

from PyQt5.QtCore import Qt, QTimer, QUrl
from PyQt5.QtGui import QPixmap, QImage, QPainter, QColor, QFont
from PyQt5.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QSplitter, QFrame, QSizePolicy, QLineEdit, QScrollArea,
    QFileDialog, QSlider, QProgressBar,
)

# 复用咩咩人格引擎（后端能力，不重造）
from .miemie_engine import (
    tool_persona_enqueue,
    tool_persona_status,
    tool_persona_calibrate,
    _load_persona,
    _PERSONA_PATH,
)

# ★ v4.7.x: 国际化（key 见 core/i18n.py 的 miemie.persona.* 区块）
try:
    from core.i18n import _t
except ImportError:
    try:
        from standard_mode.core.i18n import _t
    except ImportError:
        def _t(key, **kwargs):
            return key

from ui.design.tokens import Lemon

# 设计系统（与 miemie_panel 一致）
_C = {
    "bg": Lemon.DARK_BG_1,
    "surface": "Lemon.DARK_BG_2",
    "surface_hi": Lemon.DARK_BG_3,
    "text": Lemon.DARK_TEXT_1,
    "text_sec": Lemon.DARK_TEXT_2,
    "text_ter": Lemon.DARK_TEXT_3,
    "primary": Lemon.BRAND_ORANGE,
    "primary_hi": Lemon.BRAND_ORANGE_LIGHT,
    "accent": "#5c9dff",
    "success": "Lemon.ACCENT_GREEN",
    "warning": Lemon.ACCENT_GOLD,
    "error": Lemon.ERROR,
    "border": "rgba(255,255,255,0.08)",
    "border_hi": "rgba(255,122,47,0.45)",
}

_BIG5_LABELS = [
    ("openness", "开放性"),
    ("conscientiousness", "尽责性"),
    ("extraversion", "外向性"),
    ("agreeableness", "宜人性"),
    ("neuroticism", "神经质"),
]

_IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif")
_DOC_EXTS = (".pdf", ".docx", ".pptx", ".txt", ".md")


class _DropZone(QLabel):
    """拖拽接收区：接受文件（图片/文档）。"""

    def __init__(self, on_drop, parent=None):
        super().__init__(parent)
        self._on_drop = on_drop
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(88)
        self.setWordWrap(True)
        self.setStyleSheet(
            "QLabel{background:Lemon.DARK_BG_1; border:1px dashed rgba(255,122,47,0.4);"
            " border-radius:10px; color:{Lemon.DARK_TEXT_2}; font-size:12px; padding:10px;}"
        )
        self.setText("把文件拖到这里\n图片 · Word · PDF · PPT（自动抽文本/视觉解读）")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        files = []
        for u in e.mimeData().urls():
            fp = u.toLocalFile()
            if fp and os.path.isfile(fp):
                files.append(fp)
        if files:
            self._on_drop(files)
        e.acceptProposedAction()


class PersonaWorkspace(QDialog):
    """咩咩分身 · 人格工作区（三栏：采集 / 分析流 / 特征调节）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_t("miemie.persona.title"))
        self.resize(1220, 780)
        self.setMinimumSize(1020, 640)
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        # 非模态：可保留主窗口交互（调用方需保存引用）
        self.setModal(False)

        self._material_items = []   # [{"kind": "text"|"image"|"doc", "name": str, "path": str}]
        self._task_ids = []          # 本工作区发起的入队任务 id
        self._flowed = set()         # 已追加到分析流的任务 id
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(2500)
        self._poll_timer.timeout.connect(self._poll_status)

        self._build_ui()
        self.refresh_persona()
        self._append_flow("[就绪] " + _t("miemie.persona.batch_info"))

    # =========================================================
    # UI 构建
    # =========================================================
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # —— 顶栏：标题 + 状态 + 动作 ——
        top = QHBoxLayout()
        title = QLabel(_t("miemie.persona.title"))
        title.setStyleSheet("font-size:15px; font-weight:700; color:{Lemon.DARK_TEXT_1};")
        top.addWidget(title)
        self.status_lbl = QLabel("待机")
        self.status_lbl.setStyleSheet(
            "QLabel{color:{Lemon.DARK_TEXT_2}; font-size:11px; background:Lemon.DARK_BG_2;"
            " border:1px solid rgba(255,255,255,0.08); border-radius:10px; padding:3px 10px;}")
        top.addWidget(self.status_lbl)
        top.addStretch(1)
        self.btn_clear = self._mk_btn(_t("miemie.persona.btn_clear"), self._clear_materials, subtle=True)
        top.addWidget(self.btn_clear)
        self.btn_analyze = self._mk_btn(_t("miemie.persona.btn_analyze"), self._start_analyze)
        top.addWidget(self.btn_analyze)
        root.addLayout(top)

        # —— 三栏 ——
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        split.addWidget(self._build_collect_panel())
        split.addWidget(self._build_flow_panel())
        split.addWidget(self._build_tune_panel())
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 3)
        split.setStretchFactor(2, 4)
        root.addWidget(split, 1)

    def _mk_btn(self, text, slot, subtle=False):
        b = QPushButton(text)
        if subtle:
            b.setStyleSheet(
                "QPushButton{background:{Lemon.DARK_BG_3}; color:{Lemon.PLACEHOLDER}; border:1px solid rgba(255,255,255,0.1);"
                " border-radius:6px; padding:6px 14px; font-size:12px;}"
                "QPushButton:hover{background:Lemon.DARK_BG_4; border-color:rgba(255,122,47,0.4); color:{Lemon.DARK_TEXT_1};}")
        else:
            b.setStyleSheet(
                "QPushButton{background:{Lemon.BRAND_ORANGE}; color:#fff; border:none; border-radius:6px;"
                " padding:7px 18px; font-size:13px; font-weight:600;}"
                "QPushButton:hover{background:#ff8f4d;}"
                "QPushButton:disabled{background:#3a3a3e; color:#777;}")
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(slot)
        return b

    # ---- 左栏：采集 ----
    def _build_collect_panel(self):
        panel = self._panel_widget("采集素材")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        self._dropzone = _DropZone(self._on_files_dropped)
        lay.addWidget(self._dropzone)

        row = QHBoxLayout()
        self.btn_paste_imgs = QPushButton("粘贴图片组(≤10张)")
        self.btn_paste_imgs.setStyleSheet(
            "QPushButton{background:{Lemon.DARK_BG_3}; color:{Lemon.PLACEHOLDER}; border:1px solid rgba(255,255,255,0.1);"
            " border-radius:6px; padding:5px 10px; font-size:11px;}"
            "QPushButton:hover{background:Lemon.DARK_BG_4; color:{Lemon.DARK_TEXT_1};}")
        self.btn_paste_imgs.setCursor(Qt.PointingHandCursor)
        self.btn_paste_imgs.clicked.connect(self._paste_clipboard_images)
        row.addWidget(self.btn_paste_imgs)

        self.btn_pick_files = QPushButton("选择文件…")
        self.btn_pick_files.setStyleSheet(
            "QPushButton{background:{Lemon.DARK_BG_3}; color:{Lemon.PLACEHOLDER}; border:1px solid rgba(255,255,255,0.1);"
            " border-radius:6px; padding:5px 10px; font-size:11px;}"
            "QPushButton:hover{background:Lemon.DARK_BG_4; color:{Lemon.DARK_TEXT_1};}")
        self.btn_pick_files.setCursor(Qt.PointingHandCursor)
        self.btn_pick_files.clicked.connect(self._pick_files)
        row.addWidget(self.btn_pick_files)
        lay.addLayout(row)

        # @文件地址输入
        addr_row = QHBoxLayout()
        self.addr_input = QLineEdit()
        self.addr_input.setPlaceholderText("@文件路径（如 D:/doc/我.docx），可多个、逗号分隔")
        self.addr_input.setStyleSheet(
            "QLineEdit{background:Lemon.DARK_BG_1; border:1px solid rgba(255,255,255,0.1);"
            " border-radius:6px; padding:5px 8px; color:{Lemon.DARK_TEXT_1}; font-size:11px;}"
            "QLineEdit:focus{border-color:rgba(255,122,47,0.5);}")
        addr_row.addWidget(self.addr_input, 1)
        self.btn_add_addr = QPushButton("加入")
        self.btn_add_addr.setStyleSheet(
            "QPushButton{background:{Lemon.DARK_BG_3}; color:{Lemon.PLACEHOLDER}; border:1px solid rgba(255,255,255,0.1);"
            " border-radius:6px; padding:5px 10px; font-size:11px;}"
            "QPushButton:hover{background:Lemon.DARK_BG_4; color:{Lemon.DARK_TEXT_1};}")
        self.btn_add_addr.setCursor(Qt.PointingHandCursor)
        self.btn_add_addr.clicked.connect(self._add_addresses)
        addr_row.addWidget(self.btn_add_addr)
        lay.addLayout(addr_row)

        # 文本输入
        self.text_input = QTextEdit()
        self.text_input.setPlaceholderText("粘贴聊天记录 / 朋友圈 / 自我描述…")
        self.text_input.setMaximumHeight(120)
        self.text_input.setStyleSheet(
            "QTextEdit{background:Lemon.DARK_BG_1; border:1px solid rgba(255,255,255,0.1);"
            " border-radius:8px; color:{Lemon.DARK_TEXT_1}; font-size:12px; padding:6px;}")
        lay.addWidget(self.text_input, 1)

        # 素材列表
        cap = QLabel("素材列表")
        cap.setStyleSheet("color:{Lemon.DARK_TEXT_2}; font-size:11px; font-weight:600;")
        lay.addWidget(cap)
        self._mat_scroll = QScrollArea()
        self._mat_scroll.setWidgetResizable(True)
        self._mat_scroll.setFrameShape(QFrame.NoFrame)
        self._mat_box = QWidget()
        self._mat_lay = QVBoxLayout(self._mat_box)
        self._mat_lay.setContentsMargins(0, 0, 0, 0)
        self._mat_lay.setSpacing(3)
        self._mat_scroll.setWidget(self._mat_box)
        self._mat_scroll.setMaximumHeight(150)
        lay.addWidget(self._mat_scroll)

        # 底部：档案
        cap2 = QLabel("人格档案（Layer 1）")
        cap2.setStyleSheet("color:{Lemon.DARK_TEXT_2}; font-size:11px; font-weight:600;")
        lay.addWidget(cap2)
        self.archive_info = QLabel("（尚无档案）")
        self.archive_info.setWordWrap(True)
        self.archive_info.setStyleSheet(f"color:{Lemon.DARK_TEXT_3}; font-size:11px;")
        lay.addWidget(self.archive_info)
        btn_arch = QPushButton("刷新档案")
        btn_arch.setStyleSheet(
            "QPushButton{background:{Lemon.DARK_BG_3}; color:{Lemon.PLACEHOLDER}; border:1px solid rgba(255,255,255,0.1);"
            " border-radius:6px; padding:4px 10px; font-size:11px;}"
            "QPushButton:hover{background:Lemon.DARK_BG_4; color:{Lemon.DARK_TEXT_1};}")
        btn_arch.setCursor(Qt.PointingHandCursor)
        btn_arch.clicked.connect(self.refresh_persona)
        lay.addWidget(btn_arch, alignment=Qt.AlignLeft)

        return panel

    # ---- 中栏：分析流 ----
    def _build_flow_panel(self):
        panel = self._panel_widget("分析流")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        self.queue_progress = QProgressBar()
        self.queue_progress.setRange(0, 100)
        self.queue_progress.setValue(0)
        self.queue_progress.setTextVisible(True)
        self.queue_progress.setStyleSheet(
            "QProgressBar{background:Lemon.DARK_BG_2; border:1px solid rgba(255,255,255,0.08);"
            " border-radius:6px; color:{Lemon.DARK_TEXT_2}; font-size:10px; height:16px; text-align:center;}"
            "QProgressBar::chunk{background:{Lemon.BRAND_ORANGE}; border-radius:5px;}")
        lay.addWidget(self.queue_progress)

        self.flow_lbl = QLabel("")
        self.flow_lbl.setWordWrap(True)
        self.flow_lbl.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.flow_lbl.setStyleSheet(f"color:{Lemon.DARK_TEXT_2}; font-size:11px;")
        flow_scroll = QScrollArea()
        flow_scroll.setWidgetResizable(True)
        flow_scroll.setFrameShape(QFrame.NoFrame)
        flow_scroll.setWidget(self.flow_lbl)
        lay.addWidget(flow_scroll, 1)

        return panel

    # ---- 右栏：特征调节 ----
    def _build_tune_panel(self):
        panel = self._panel_widget("人格特征调节")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)

        hint = QLabel("分析完成后，拖动滑块 / 点选标签微调，再「保存画像」。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:{Lemon.DARK_TEXT_3}; font-size:11px;")
        lay.addWidget(hint)

        # Big5 滑块区
        self._sliders = {}   # key -> (slider, val_label)
        for key, cn in _BIG5_LABELS:
            row = QHBoxLayout()
            name = QLabel(cn)
            name.setFixedWidth(56)
            name.setStyleSheet("color:{Lemon.PLACEHOLDER}; font-size:12px;")
            row.addWidget(name)
            s = QSlider(Qt.Horizontal)
            s.setRange(0, 100)
            s.setValue(50)
            s.setFixedHeight(18)
            s.setStyleSheet(
                "QSlider::groove:horizontal{background:{Lemon.DARK_BG_3}; height:6px; border-radius:3px;}"
                "QSlider::sub-page:horizontal{background:{Lemon.BRAND_ORANGE}; border-radius:3px;}"
                "QSlider::handle:horizontal{background:{Lemon.BRAND_ORANGE_LIGHT}; width:14px; height:14px;"
                " margin:-4px 0; border-radius:7px;}")
            v = QLabel("50")
            v.setFixedWidth(34)
            v.setAlignment(Qt.AlignRight)
            v.setStyleSheet("color:{Lemon.BRAND_ORANGE_LIGHT}; font-size:12px; font-weight:600;")
            s.valueChanged.connect(lambda x, lab=v: lab.setText(str(x)))
            self._sliders[key] = (s, v)
            row.addWidget(s, 1)
            row.addWidget(v)
            lay.addLayout(row)

        # 子特征标签（点选）
        cap = QLabel("特征标签（点选启用）")
        cap.setStyleSheet("color:{Lemon.DARK_TEXT_2}; font-size:11px; font-weight:600;")
        lay.addWidget(cap)
        self._tag_box = QWidget()
        self._tag_lay = QHBoxLayout(self._tag_box)
        self._tag_lay.setContentsMargins(0, 0, 0, 0)
        self._tag_lay.setSpacing(4)
        self._tag_btns = []
        for tag in ("追求简洁", "注重细节", "大胆创新", "严谨稳妥", "善于协作", "独立思考", "行动力强", "理性务实"):
            b = QPushButton(tag)
            b.setCheckable(True)
            b.setStyleSheet(
                "QPushButton{background:Lemon.DARK_BG_2; color:{Lemon.DARK_TEXT_2}; border:1px solid rgba(255,255,255,0.1);"
                " border-radius:10px; padding:3px 8px; font-size:10px;}"
                "QPushButton:checked{background:rgba(255,122,47,0.18); color:{Lemon.BRAND_ORANGE_LIGHT};"
                " border-color:rgba(255,122,47,0.45);}")
            b.setCursor(Qt.PointingHandCursor)
            self._tag_btns.append(b)
            self._tag_lay.addWidget(b)
        lay.addWidget(self._tag_box)

        # 画像描述
        cap2 = QLabel("画像描述（可编辑）")
        cap2.setStyleSheet("color:{Lemon.DARK_TEXT_2}; font-size:11px; font-weight:600;")
        lay.addWidget(cap2)
        self.portrait_edit = QTextEdit()
        self.portrait_edit.setPlaceholderText("一句话描述这个人的画像…")
        self.portrait_edit.setMaximumHeight(90)
        self.portrait_edit.setStyleSheet(
            "QTextEdit{background:Lemon.DARK_BG_1; border:1px solid rgba(255,255,255,0.1);"
            " border-radius:8px; color:{Lemon.DARK_TEXT_1}; font-size:12px; padding:6px;}")
        lay.addWidget(self.portrait_edit, 1)

        btn_row = QHBoxLayout()
        self.btn_save = self._mk_btn("保存画像", self._save_persona)
        btn_row.addWidget(self.btn_save)
        self.btn_calib = self._mk_btn("AI 校准", self._do_calibrate, subtle=True)
        btn_row.addWidget(self.btn_calib)
        lay.addLayout(btn_row)

        self.save_status = QLabel("")
        self.save_status.setWordWrap(True)
        self.save_status.setStyleSheet("color:Lemon.ACCENT_GREEN; font-size:11px;")
        lay.addWidget(self.save_status)

        return panel

    def _panel_widget(self, title):
        w = QWidget()
        w.setStyleSheet("background:Lemon.DARK_BG_2; border:1px solid rgba(255,255,255,0.07); border-radius:10px;")
        return w

    # =========================================================
    # 采集
    # =========================================================
    def _on_files_dropped(self, files):
        added = 0
        for fp in files:
            if self._add_material_file(fp):
                added += 1
        if added:
            self._render_materials()
            self._append_flow(f"[采集] 拖入 {added} 个文件。")

    def _pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择素材文件",
            "", "素材文件 (*.jpg *.jpeg *.png *.webp *.bmp *.gif *.pdf *.docx *.pptx *.txt *.md);;所有文件 (*)")
        if files:
            added = sum(1 for fp in files if self._add_material_file(fp))
            if added:
                self._render_materials()
                self._append_flow(f"[采集] 选择 {added} 个文件。")

    def _add_material_file(self, fp):
        ext = os.path.splitext(fp)[1].lower()
        if ext in _IMG_EXTS:
            self._material_items.append({"kind": "image", "name": os.path.basename(fp), "path": fp})
            return True
        if ext in _DOC_EXTS:
            self._material_items.append({"kind": "doc", "name": os.path.basename(fp), "path": fp})
            return True
        return False

    def _add_addresses(self):
        txt = self.addr_input.text().strip()
        if not txt:
            return
        added = 0
        for part in txt.replace("，", ",").split(","):
            p = part.strip()
            if not p:
                continue
            p = p.lstrip("@")
            if os.path.isfile(p) and self._add_material_file(p):
                added += 1
        self.addr_input.clear()
        if added:
            self._render_materials()
            self._append_flow(f"[采集] 地址引用加入 {added} 个文件。")

    def _paste_clipboard_images(self):
        from PyQt5.QtWidgets import QApplication
        mime = QApplication.clipboard().mimeData()
        if mime is None or not mime.hasImage():
            self.status_lbl.setText("剪贴板里没有图片")
            return
        img = QImage(mime.imageData())
        if img.isNull():
            self.status_lbl.setText("剪贴板图片无效")
            return
        # 落盘临时文件，加入素材
        tmp_dir = os.path.join(os.path.dirname(_PERSONA_PATH))
        os.makedirs(tmp_dir, exist_ok=True)
        fp = os.path.join(tmp_dir, "clip_%d.png" % int(time.time() * 1000))
        if not img.save(fp, "PNG"):
            self.status_lbl.setText("保存剪贴板图片失败")
            return
        self._material_items.append({"kind": "image", "name": os.path.basename(fp), "path": fp})
        self._render_materials()
        self._append_flow(f"[采集] 粘贴 1 张剪贴板图片。")

    def _collect_text(self):
        txt = self.text_input.toPlainText().strip()
        if txt:
            self._material_items.append({"kind": "text", "name": "文本素材", "path": "", "text": txt})
            self.text_input.clear()
            self._render_materials()
            self._append_flow(f"[采集] 加入文本素材（{len(txt)} 字）。")

    def _clear_materials(self):
        self._material_items = []
        self._render_materials()
        self._append_flow("[采集] 已清空素材。")

    def _render_materials(self):
        # 清空
        while self._mat_lay.count():
            item = self._mat_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        if not self._material_items:
            self._mat_lay.addWidget(QLabel("（暂无素材）"))
            self._mat_lay.itemAt(0).widget().setStyleSheet(f"color:{Lemon.DARK_TEXT_3}; font-size:11px;")
            return
        for i, m in enumerate(self._material_items):
            kind_cn = {"text": "文本", "image": "图片", "doc": "文档"}.get(m["kind"], "?")
            icon = {"text": "T", "image": "IMG", "doc": "DOC"}.get(m["kind"], "?")
            l = QLabel(f'<span style="color:{Lemon.BRAND_ORANGE};font-weight:700;">[{icon}]</span> '
                       f'<span style="color:{Lemon.PLACEHOLDER};">{kind_cn} · {m["name"]}</span>')
            l.setToolTip(m.get("path") or m.get("text", "")[:80])
            l.setStyleSheet("background:Lemon.DARK_BG_1; border:1px solid rgba(255,255,255,0.07);"
                            " border-radius:5px; padding:3px 6px; font-size:11px;")
            self._mat_lay.addWidget(l)

    # =========================================================
    # 分析流（异步队列，复用后端）
    # =========================================================
    def _start_analyze(self):
        # 收集文本素材（先取输入框文本，再取列表中的文本项）
        if self.text_input.toPlainText().strip():
            self._collect_text()
        if not self._material_items:
            self.status_lbl.setText("请先添加素材（文本/图片/文件）")
            return
        self.btn_analyze.setEnabled(False)
        self._task_ids = []
        self._append_flow("[分析] 开始入队…")
        # 图片/文档 → 入队（每文件一个任务，图片走视觉解读，文档走文本抽取）
        n = 0
        for m in self._material_items:
            if m["kind"] == "text":
                r = tool_persona_enqueue(text=m.get("text", ""))
            elif m["kind"] == "image":
                r = tool_persona_enqueue(text="", image_paths=m["path"], image_caption="")
            elif m["kind"] == "doc":
                text = self._extract_doc_text(m["path"])
                r = tool_persona_enqueue(text=text, image_paths="", image_caption="")
            else:
                continue
            if r.get("ok"):
                self._task_ids.append(r["id"])
                self._append_flow(f"[入队] {m['name']} → #{r['id']}")
                n += 1
        self.status_lbl.setText(f"已入队 {n} 项，后台炼化中…")
        self._poll_timer.start()
        self._poll_status()

    def _extract_doc_text(self, path):
        """按扩展名抽取文档文本（缺库时返回提示）。"""
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == ".txt" or ext == ".md":
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    return f.read(4000)
            if ext == ".docx":
                import docx
                d = docx.Document(path)
                return "\n".join(p.text for p in d.paragraphs)[:4000]
            if ext == ".pptx":
                from pptx import Presentation
                prs = Presentation(path)
                parts = []
                for slide in prs.slides:
                    for shape in slide.shapes:
                        if shape.has_text_frame:
                            parts.append(shape.text_frame.text)
                return "\n".join(parts)[:4000]
            if ext == ".pdf":
                import pdfplumber
                with pdfplumber.open(path) as pdf:
                    return "\n".join(p.extract_text() or "" for p in pdf.pages[:10])[:4000]
        except ImportError as e:
            return f"（无法解析 {os.path.basename(path)}：缺少库 {e}）"
        except Exception as e:
            return f"（解析失败：{e}）"
        return ""

    def _poll_status(self):
        """轮询后端队列，更新进度与分析流。"""
        try:
            res = tool_persona_status(limit=80)
        except Exception:
            return
        items = res.get("items") or []
        mine = [i for i in items if i.get("id") in self._task_ids]
        if not self._task_ids:
            self._poll_timer.stop()
            return
        done = sum(1 for i in mine if i.get("state") == "done")
        err = sum(1 for i in mine if i.get("state") == "error")
        running = sum(1 for i in mine if i.get("state") == "running")
        total = len(self._task_ids)
        self.queue_progress.setValue(int(done * 100 / total) if total else 0)
        self.queue_progress.setFormat(f"完成 {done}/{total}（运行中 {running}）")
        # 新增完成的条目 → 追加流
        for i in mine:
            if i.get("state") == "done" and i.get("id") not in self._flowed:
                self._append_flow(f"[完成] #{i['id']} {i.get('summary', '')[:100]}")
                self._flowed.add(i["id"])
            elif i.get("state") == "error" and i.get("id") not in self._flowed:
                self._append_flow(f"[失败] #{i['id']} {i.get('error', '')[:100]}")
                self._flowed.add(i["id"])
        if done + err >= total:
            self._poll_timer.stop()
            self.btn_analyze.setEnabled(True)
            self.status_lbl.setText("分析完成")
            self._append_flow(f"[分析] 完成（成功 {done}，失败 {err}），刷新特征面板。")
            self.refresh_persona()
            self._refresh_tune_from_persona()
        elif err >= total:
            self._poll_timer.stop()
            self.btn_analyze.setEnabled(True)
            self.status_lbl.setText("分析失败")

    def _append_flow(self, line):
        cur = self.flow_lbl.text()
        new = (cur + "\n" + line) if cur else line
        self.flow_lbl.setText(new)
        self.flow_lbl.update()

    # =========================================================
    # 特征调节 / 保存
    # =========================================================
    def refresh_persona(self):
        p = _load_persona()
        if not p:
            self.archive_info.setText("（尚无档案）")
            return
        big5 = p.get("big5") or {}
        parts = []
        for key, cn in _BIG5_LABELS:
            v = big5.get(key) or {}
            parts.append(f"{cn} {v.get('score', 50):.0f}")
        portrait = p.get("portrait") or ""
        self.archive_info.setText(
            " · ".join(parts) + (f"\n{portrait[:60]}" if portrait else ""))
        self.archive_info.setStyleSheet(f"color:{Lemon.DARK_TEXT_2}; font-size:11px;")

    def _refresh_tune_from_persona(self):
        p = _load_persona() or {}
        big5 = p.get("big5") or {}
        for key, (s, v) in self._sliders.items():
            d = big5.get(key) or {}
            val = int(float(d.get("score", 50)))
            s.setValue(val)
            v.setText(str(val))
        if p.get("portrait"):
            self.portrait_edit.setPlainText(str(p["portrait"]))
        # 标签：按档案中的 sources/tags 点选（简化：不清空，用户手动点选）
        self.save_status.setText("")

    def _save_persona(self):
        """把当前滑块/标签/画像写回 Layer1 档案（保留其他字段）。"""
        try:
            p = _load_persona() or {}
            big5 = p.get("big5") or {}
            for key, (s, v) in self._sliders.items():
                old = big5.get(key) or {}
                old["score"] = float(s.value())
                old["confidence"] = float(old.get("confidence", 0.8))
                big5[key] = old
            p["big5"] = big5
            portrait = self.portrait_edit.toPlainText().strip()
            if portrait:
                p["portrait"] = portrait
            tags = [b.text() for b in self._tag_btns if b.isChecked()]
            if tags:
                p["tags"] = tags
            p["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
            p.setdefault("sources", []).append("workspace_manual")
            with open(_PERSONA_PATH, "w", encoding="utf-8") as f:
                json.dump(p, f, ensure_ascii=False, indent=2)
            self.save_status.setText("已保存到人格档案")
            self.refresh_persona()
        except Exception as e:
            self.save_status.setText(f"保存失败：{e}")
            self.save_status.setStyleSheet(f"color:{Lemon.ERROR}; font-size:11px;")

    def _do_calibrate(self):
        """AI 校准：用户反馈 → 高置信度更新档案（复用后端）。"""
        from PyQt5.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, "AI 校准", "输入校准反馈（如「我其实很外向」）：")
        if not ok or not text.strip():
            return
        self.status_lbl.setText("校准中…")
        try:
            res = tool_persona_calibrate(text.strip())
        except Exception as e:
            res = {"ok": False, "error": str(e)}
        if res.get("ok"):
            self.status_lbl.setText("校准完成")
            self.save_status.setText("AI 校准已更新画像")
            self.refresh_persona()
            self._refresh_tune_from_persona()
        else:
            self.status_lbl.setText("校准失败")
            self.save_status.setText(str(res.get("error") or "校准失败"))
            self.save_status.setStyleSheet(f"color:{Lemon.ERROR}; font-size:11px;")


def open_persona_workspace(parent=None):
    """便捷入口：返回一个非模态工作区实例（调用方需保存引用防 GC）。"""
    return PersonaWorkspace(parent)
