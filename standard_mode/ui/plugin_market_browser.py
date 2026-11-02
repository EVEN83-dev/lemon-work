# -*- coding: utf-8 -*-
"""
Trae 式插件市场浏览器（v3.97 高级简约版）
===========================================
卡片流浏览 + 分类筛选 + 搜索 + 一键安装/卸载。
全部按 Lemon Code 高级简约规范设计（深色底 + 柠檬橙 + 温和圆角 + SVG 线条图标）。

数据来源：shared/plugin_market.PluginMarket（内置 + 远程 + 离线兜底）
"""

import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QLabel, QScrollArea, QGridLayout, QFrame, QButtonGroup,
    QMessageBox, QDialog, QTextEdit, QSizePolicy,
)
from PyQt5.QtGui import QFont, QIcon, QPixmap, QPainter, QColor
from PyQt5.QtSvg import QSvgRenderer

from standard_mode.core.i18n import _t

from theme import (
    BG_ROOT, BG_SURFACE, BG_SURFACE_HOVER, BG_PANEL,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY, TEXT_MUTED,
    LEMON_ORANGE, LEMON_YELLOW, LEMON_ORANGE_LIGHT,
    SUCCESS_COLOR, WARNING_COLOR, ERROR_COLOR, INFO_COLOR,
    BORDER_DEFAULT, RADIUS_LG, RADIUS_MD, RADIUS_SM,
    FONT_FAMILY, FONT_SIZE_SM, FONT_SIZE_BASE,
    CARD_BG, CARD_BG_HOVER, CARD_BORDER, CARD_BORDER_FOCUS,
    CARD_RADIUS, CARD_PADDING, CARD_GAP,
    TAG_BG_BUILTIN, TAG_TEXT_BUILTIN, TAG_BG_REMOTE, TAG_TEXT_REMOTE,
    TAG_RADIUS, TAG_FONT_SIZE, EMPTY_TEXT_COLOR,
    SVG_ICONS, get_svg_icon,
)
from ui.design.tokens import Lemon

# 本地别名（简洁名）
BG_HOVER = BG_SURFACE_HOVER

# 分类（i18n key + SVG 图标键）
# v4.8: 使用 i18n key 替代硬编码中文，运行时通过 _t() 解析
_CATEGORIES = [
    ("plugin.category.all", ""),
    ("plugin.category.editor", "editor"),
    ("plugin.category.tool", "tool"),
    ("plugin.category.format", "format"),
    ("plugin.category.code", "code"),
    ("plugin.category.text", "text"),
    ("plugin.category.document", "document"),
    ("plugin.category.language", "language"),
    ("plugin.category.network", "network"),
    ("plugin.category.terminal", "terminal"),
    ("plugin.category.data", "data"),
    ("plugin.category.image", "image"),
    ("plugin.category.analysis", "analysis"),
    ("plugin.category.theme", "theme"),
    ("plugin.category.collab", "collab"),
    ("plugin.category.other", "other"),
]

# 分类→SVG 图标映射
_CAT_ICONS = {
    "editor": "plus", "tool": "tool", "format": "skill_formatter",
    "code": "build", "text": "file_txt", "git": "git",
    "document": "folder", "language": "thinking", "network": "send",
    "terminal": "terminal", "data": "chart", "image": "image",
    "analysis": "chart", "theme": "settings", "collab": "plus",
}


def _render_svg_pixmap(svg: str, size: int, color: str = "currentColor") -> QPixmap:
    """把 SVG 字符串真实渲染为像素图（QSvgRenderer），避免 QLabel 直接显示 SVG 文本乱码。

    color 若为 'currentColor' 则用内置主题色替换；否则作为描边色。
    """
    if color and color != "currentColor":
        svg = svg.replace('stroke="currentColor"', f'stroke="{color}"')
    renderer = QSvgRenderer()
    if not renderer.load(svg.encode("utf-8")):
        return QPixmap(size, size)
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    renderer.render(painter)
    painter.end()
    return pm


def _render_initial_icon(initial: str, size: int, accent: str = LEMON_ORANGE) -> QPixmap:
    """无 SVG 图标时，生成品牌色「首字母」简笔图标（高级简约风格）。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    # 圆底
    p.setBrush(QColor("{Lemon.DARK_MID_5}"))
    p.setPen(Qt.NoPen)
    p.drawEllipse(1, 1, size - 2, size - 2)
    # 描边圆环（柠檬橙细线）
    p.setBrush(Qt.NoBrush)
    pen = QColor(accent)
    pen.setAlpha(200)
    p.setPen(pen)
    p.drawEllipse(2, 2, size - 4, size - 4)
    # 首字母
    p.setPen(QColor(accent))
    f = QFont("Microsoft YaHei UI", int(size * 0.42), QFont.Bold)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, initial[:1].upper())
    p.end()
    return pm


def _format_downloads(count: int) -> str:
    """下载量格式化：1234 -> 1.2k，1234567 -> 1.2M；0 显示为 —"""
    try:
        count = int(count or 0)
    except Exception:
        count = 0
    if count <= 0:
        return "—"
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}k"
    return str(count)


def _rating_stars(rating: float) -> str:
    """把 0~5 评级渲染为「★」「☆」字符串（半星向下取整显示）。"""
    rating = max(0.0, min(5.0, float(rating)))
    full = int(round(rating))
    full = max(0, min(5, full))
    return "★" * full + "☆" * (5 - full)


class _PluginCard(QFrame):
    """单张插件卡片 — VSCode / Trae 风格高级版（徽章+大图标+紧凑布局+绿色按钮）"""

    install_clicked = pyqtSignal(str)
    uninstall_clicked = pyqtSignal(str)
    clicked = pyqtSignal(str)

    # VSCode 绿（已安装/安装中）+ 红色（卸载）+ 灰（未安装）
    BTN_INSTALL = "{Lemon.ACCENT_GREEN}"
    BTN_INSTALL_HOVER = "{Lemon.ACCENT_GREEN}"
    BTN_UNINSTALL_BORDER = "{Lemon.ERROR}"
    BTN_INSTALLED_BG = "{Lemon.ACCENT_GREEN}"
    BADGE_COLORS = {
        "HOT":  ("{Lemon.BRAND_ORANGE}", "{Lemon.BG}"),
        "NEW":  ("{Lemon.ACCENT_GREEN}", "{Lemon.BG}"),
        "推荐": ("#8957e5", "{Lemon.BG}"),
        "官方精选": ("#0969da", "{Lemon.BG}"),
    }

    def __init__(self, info, parent=None):
        super().__init__(parent)
        self._name = info.name
        self._info = info
        self.setObjectName("pluginCard")
        self.setFixedHeight(96)
        self.setCursor(Qt.PointingHandCursor)
        self._build_ui(info)
        self._apply_style()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._name)
        super().mouseReleaseEvent(event)

    def _apply_style(self):
        self.setStyleSheet(f"""
            #pluginCard {{
                background-color: {CARD_BG};
                border: 1px solid {CARD_BORDER};
                border-radius: {CARD_RADIUS};
            }}
            #pluginCard:hover {{
                background-color: {CARD_BG_HOVER};
                border-color: {CARD_BORDER_FOCUS};
            }}
        """)

    def _render_icon_pixmap(self, info, size: int) -> QPixmap:
        pm = None
        try:
            cat_key = info.category or "other"
            svg_key = _CAT_ICONS.get(cat_key, "file_default")
            svg_str = get_svg_icon(svg_key, size=size, color=LEMON_ORANGE)
            pm = _render_svg_pixmap(svg_str, size, LEMON_ORANGE)
            if pm is None or pm.width() == 0:
                pm = None
        except Exception:
            pm = None
        if pm is None:
            initial = (info.display_name or info.name or "?")[0:1]
            pm = _render_initial_icon(initial, size, LEMON_ORANGE)
        return pm

    def _build_ui(self, info):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body = QWidget()
        lay = QHBoxLayout(body)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(12)

        # ── 左侧：大图标（56px 深色圆角容器）──
        icon_frame = QFrame()
        icon_frame.setFixedSize(56, 56)
        icon_frame.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #2d2f3a, stop:1 #1f2128);
                border-radius: 12px;
                border: 1px solid {BORDER_DEFAULT};
            }}
        """)
        icon_inner = QVBoxLayout(icon_frame)
        icon_inner.setContentsMargins(0, 0, 0, 0)
        icon_inner.setAlignment(Qt.AlignCenter)
        icon_lbl = QLabel()
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setPixmap(self._render_icon_pixmap(info, 36))
        icon_inner.addWidget(icon_lbl)
        lay.addWidget(icon_frame)

        # ── 中间：信息区 ──
        mid = QVBoxLayout()
        mid.setSpacing(2)

        # 名称行（加粗 + 徽章右对齐）
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        name_lbl = QLabel(info.display_name or info.name)
        name_lbl.setFont(QFont("Microsoft YaHei UI", 12, QFont.Bold))
        name_lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; background: transparent;")
        title_row.addWidget(name_lbl)

        # 徽章（HOT/NEW/推荐）——右上角彩条
        badge = getattr(info, "badge", "") or ""
        if badge and badge in self.BADGE_COLORS:
            bg_c, fg_c = self.BADGE_COLORS[badge]
            b = QLabel(badge)
            b.setAlignment(Qt.AlignCenter)
            b.setStyleSheet(f"""
                background-color: {bg_c}; color: {fg_c}; border-radius: 4px;
                font-size: 10px; font-weight: 800; padding: 1px 6px;
                letter-spacing: 1px;
            """)
            title_row.addWidget(b)

        ver_lbl = QLabel(f"v{info.version}")
        ver_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; background: transparent;")
        title_row.addWidget(ver_lbl)
        title_row.addStretch()
        mid.addLayout(title_row)

        # 描述（单行截断）
        desc = info.description or ""
        desc_lbl = QLabel(desc)
        desc_lbl.setWordWrap(False)
        desc_lbl.setTextFormat(Qt.PlainText)
        desc_elided = desc_lbl.fontMetrics().elidedText(desc, Qt.ElideRight, 360)
        desc_lbl.setText(desc_elided)
        desc_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px; background: transparent;")
        mid.addWidget(desc_lbl)

        # 底部：星级 + 下载量 + 作者
        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        rating = getattr(info, "rating", 4.5) or 4.5
        downloads = getattr(info, "downloads", 0) or 0
        rating_text = float(rating)
        stars = QLabel(_rating_stars(rating))
        stars.setStyleSheet(
            f"color: {LEMON_ORANGE}; font-size: 12px; letter-spacing: 1px; background: transparent;"
        )
        bottom.addWidget(stars)
        rate_lbl = QLabel(f"{rating_text:.1f}" if rating_text > 0 else "—")
        rate_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px; background: transparent;")
        bottom.addWidget(rate_lbl)
        sep1 = QLabel("·")
        sep1.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; background: transparent;")
        bottom.addWidget(sep1)
        dl_lbl = QLabel(f"⬇ {_format_downloads(downloads)}")
        dl_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px; background: transparent;")
        bottom.addWidget(dl_lbl)
        if info.author:
            sep2 = QLabel("·")
            sep2.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; background: transparent;")
            bottom.addWidget(sep2)
            a = QLabel(f"by {info.author}")
            a.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; background: transparent;")
            bottom.addWidget(a)
        bottom.addStretch()
        mid.addLayout(bottom)

        lay.addLayout(mid, 1)

        # ── 右侧：操作按钮（VSCode 绿/红色）──
        self._btn = QPushButton()
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.setFixedSize(78, 30)
        self._btn.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        self._update_btn_style(info.is_installed)
        if info.is_installed:
            self._btn.clicked.connect(lambda: self.uninstall_clicked.emit(self._name))
        else:
            self._btn.clicked.connect(lambda: self.install_clicked.emit(self._name))
        lay.addWidget(self._btn, 0, Qt.AlignVCenter)

        outer.addWidget(body)

    def _update_btn_style(self, installed: bool):
        if installed:
            self._btn.setText("已安装")
            self._btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {self.BTN_INSTALLED_BG}; color: #fff;
                    border: none; border-radius: 5px;
                }}
                QPushButton:hover {{ background-color: {self.BTN_UNINSTALL_BORDER}; }}
            """)
        else:
            self._btn.setText("安装")
            self._btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {self.BTN_INSTALL}; color: #fff;
                    border: none; border-radius: 5px;
                }}
                QPushButton:hover {{ background-color: {self.BTN_INSTALL_HOVER}; }}
            """)

    def set_installed(self, installed: bool):
        self._info.is_installed = installed
        self._update_btn_style(installed)
        # 重新连接信号（已安装时按钮点击变卸载）
        try:
            self._btn.clicked.disconnect()
        except Exception:
            pass
        if installed:
            self._btn.clicked.connect(lambda: self.uninstall_clicked.emit(self._name))
        else:
            self._btn.clicked.connect(lambda: self.install_clicked.emit(self._name))

    @property
    def name(self):
        return self._name


class PluginMarketBrowser(QWidget):
    """Trae 式插件市场浏览器 — 高级简约版"""

    plugin_installed = pyqtSignal(str)
    plugin_uninstalled = pyqtSignal(str)

    def __init__(self, market=None, plugin_manager=None, parent=None):
        super().__init__(parent)
        self._market = market
        self._plugin_manager = plugin_manager
        # 必须让 market 与外部 PluginManager 实例保持一致，否则安装会加载到错误/空的 manager，
        # 造成"点了安装但左侧扩展列表不显示"的假能用现象。
        if self._market is not None and self._market._plugin_manager is None and self._plugin_manager is not None:
            self._market._plugin_manager = self._plugin_manager
        self._current_category = ""
        self._search_text = ""
        self._view = "all"   # all / official / installed
        self._cards = {}
        self._all_infos = []

        self._init_ui()
        self._load_market()

    # ============================================================
    # 数据
    # ============================================================

    def _get_market(self):
        if self._market is not None:
            return self._market
        try:
            from shared.plugin_market import PluginMarket
            return PluginMarket()
        except Exception:
            return None

    def _load_market(self):
        market = self._get_market()
        if market is None:
            self._status_label.setText("插件市场初始化失败")
            return
        # 启动时 discover_plugins 可能已经加载了内置插件；同步到 market 的 _installed，
        # 避免市场里显示"安装"而左侧扩展面板其实已经加载的状态不一致。
        try:
            market.sync_from_manager()
        except Exception:
            pass
        try:
            market.reload_catalog()
            self._all_infos = list(market._catalog.values())
        except Exception as e:
            self._all_infos = []
            self._status_label.setText(f"目录加载失败：{e}")
        self._sync_installed_state()
        self._refresh()

    def _sync_installed_state(self):
        mgr = self._plugin_manager
        if mgr is None:
            return
        installed = set()
        try:
            for p in mgr.get_all_plugins():
                installed.add(p.name)
        except Exception:
            pass
        for info in self._all_infos:
            info.is_installed = info.name in installed

    # ============================================================
    # UI
    # ============================================================

    def _init_ui(self):
        self.setStyleSheet(f"background-color: {BG_ROOT};")
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ===================== 左侧导航栏 =====================
        sidebar = self._build_sidebar()
        root.addWidget(sidebar)

        # ===================== 右侧内容区 =====================
        right = QVBoxLayout()
        right.setContentsMargins(16, 14, 16, 12)
        right.setSpacing(10)

        # 顶部工具栏：搜索 + 刷新 + 标题（同一行）
        head = QHBoxLayout()
        head.setSpacing(10)
        title = QLabel(_t("plugin.market.title"))
        title.setFont(QFont("Microsoft YaHei UI", 15, QFont.Bold))
        title.setStyleSheet(f"color: {TEXT_PRIMARY}; background: transparent;")
        head.addWidget(title)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(_t("plugin.market.search_browser"))
        self.search_input.textChanged.connect(self._on_search)
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {BG_SURFACE}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT}; border-radius: {RADIUS_MD};
                padding: 6px 12px; font-size: {FONT_SIZE_BASE};
            }}
            QLineEdit:focus {{ border-color: {LEMON_ORANGE}; }}
        """)
        self.search_input.setFixedWidth(360)
        head.addWidget(self.search_input)

        head.addStretch()

        refresh = QPushButton(_t("plugin.market.refresh"))
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.setStyleSheet(f"""
            QPushButton {{ background: {BG_SURFACE}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT}; border-radius: 6px;
                padding: 6px 14px; font-size: 13px; }}
            QPushButton:hover {{ border-color: {LEMON_ORANGE}; }}
        """)
        refresh.clicked.connect(self._on_refresh)
        head.addWidget(refresh)

        # v4.8: 本地创建插件按钮（无需远程服务器）
        create_btn = QPushButton("＋ 创建插件")
        create_btn.setCursor(Qt.PointingHandCursor)
        create_btn.setStyleSheet(f"""
            QPushButton {{ background: {LEMON_ORANGE}; color: #111;
                border: none; border-radius: 6px;
                padding: 6px 14px; font-size: 13px; font-weight: 600; }}
            QPushButton:hover {{ background: {LEMON_ORANGE_LIGHT}; }}
        """)
        create_btn.clicked.connect(self._on_create_local_plugin)
        head.addWidget(create_btn)

        right.addLayout(head)

        # 分类标签行（横向 chip 风格）
        cat_wrap = QWidget()
        cat_layout = QHBoxLayout(cat_wrap)
        cat_layout.setContentsMargins(0, 0, 0, 0)
        cat_layout.setSpacing(6)
        self._cat_buttons = {}
        self._cat_group = QButtonGroup(self)
        self._cat_group.setExclusive(True)
        for label, key in _CATEGORIES:
            btn = QPushButton(_t(label))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setCheckable(True)
            btn.setChecked(key == "")
            btn.clicked.connect(lambda checked, k=key: self._on_cat_changed(k, checked))
            self._cat_group.addButton(btn)
            self._cat_buttons[key] = btn
            cat_layout.addWidget(btn)
        cat_layout.addStretch()
        self._update_view_styles()
        right.addWidget(cat_wrap)

        # 卡片滚动区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea {{ background: {BG_ROOT}; border: none; }}")
        self._cards_container = QWidget()
        self._cards_grid = QGridLayout(self._cards_container)
        self._cards_grid.setContentsMargins(0, 4, 0, 0)
        self._cards_grid.setSpacing(CARD_GAP)
        self._cards_grid.setAlignment(Qt.AlignTop)
        scroll.setWidget(self._cards_container)
        right.addWidget(scroll, 1)

        # 底部状态
        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 12px;")
        right.addWidget(self._status_label)

        right_container = QWidget()
        right_container.setLayout(right)
        root.addWidget(right_container, 1)

        self._update_view_styles()

    def _build_sidebar(self):
        """构建左侧导航栏：品牌区 + 视图 Tab + 分类。"""
        sidebar = QFrame()
        sidebar.setFixedWidth(208)
        sidebar.setObjectName("marketSidebar")
        sidebar.setStyleSheet(f"""
            QFrame#marketSidebar {{
                background-color: {BG_SURFACE}; border: none;
                border-right: 1px solid {BORDER_DEFAULT};
            }}
        """)

        lay = QVBoxLayout(sidebar)
        lay.setContentsMargins(14, 18, 14, 14)
        lay.setSpacing(6)

        # 品牌区
        brand_row = QHBoxLayout()
        brand_row.setSpacing(8)
        logo_lbl = QLabel()
        logo_pm = _render_svg_pixmap(
            get_svg_icon("skill_formatter", size=22, color=LEMON_ORANGE),
            22, LEMON_ORANGE,
        )
        if logo_pm is None or logo_pm.width() == 0:
            logo_pm = _render_initial_icon("L", 22, LEMON_ORANGE)
        logo_lbl.setPixmap(logo_pm)
        brand_row.addWidget(logo_lbl)
        bn = QLabel("Lemon Code")
        bn.setFont(QFont("Microsoft YaHei UI", 12, QFont.Bold))
        bn.setStyleSheet(f"color: {TEXT_PRIMARY}; background: transparent;")
        brand_row.addWidget(bn)
        brand_row.addStretch()
        lay.addLayout(brand_row)
        lay.addSpacing(10)

        # 分组：浏览
        lay.addWidget(self._build_sidebar_label("浏览"))
        self._view_buttons = {}
        self._view_group = QButtonGroup(self)
        self._view_group.setExclusive(True)
        sidebar_views = [
            (_t("plugin.market.featured"), "featured"),
            (_t("plugin.market.installed_tab"), "installed"),
            (_t("plugin.market.latest"), "latest"),
            ("🏷  " + _t("plugin.category.all"), "all"),
        ]
        for label, key in sidebar_views:
            btn = QPushButton(label)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setCheckable(True)
            btn.setChecked(key == "all")
            btn.clicked.connect(lambda checked, k=key: self._on_view_changed(k, checked))
            self._view_group.addButton(btn)
            self._view_buttons[key] = btn
            lay.addWidget(btn)
        lay.addSpacing(8)

        # 分组：分类
        lay.addWidget(self._build_sidebar_label(_t("plugin.market.category")))
        for label, key in _CATEGORIES:
            sb = QPushButton(_t(label))
            sb.setCursor(Qt.PointingHandCursor)
            sb.setCheckable(True)
            sb.clicked.connect(lambda checked, k=key: self._on_cat_changed(k, checked))
            self._cat_buttons_sidebar = getattr(self, "_cat_buttons_sidebar", {})
            self._cat_buttons_sidebar[key] = sb
            lay.addWidget(sb)
        lay.addStretch()
        return sidebar

    def _build_sidebar_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"""
            color: {TEXT_TERTIARY}; background: transparent;
            font-size: 11px; font-weight: 700; letter-spacing: 1px;
            padding: 8px 6px 4px 6px;
        """)
        return lbl

    # ============================================================
    # 交互
    # ============================================================

    def _on_view_changed(self, key, checked):
        self._view = key if checked else "all"
        self._update_view_styles()
        self._refresh()

    def _update_view_styles(self):
        # 视图按钮（左导栏）：左侧橙色细条表示选中 + 深底
        for k, btn in self._view_buttons.items():
            checked = (k == self._view)
            if checked:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {BG_HOVER}; color: {LEMON_ORANGE};
                        border: none; border-radius: 0px;
                        border-left: 3px solid {LEMON_ORANGE};
                        padding: 9px 12px 9px 10px; text-align: left;
                        font-size: 13px; font-weight: 700;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: transparent; color: {TEXT_SECONDARY};
                        border: none; border-left: 3px solid transparent;
                        border-radius: 0px; padding: 9px 12px 9px 10px;
                        text-align: left; font-size: 13px;
                    }}
                    QPushButton:hover {{ color: {TEXT_PRIMARY}; background: {BG_HOVER}; }}
                """)

        # 顶部分类标签（chip 风格）
        for k, btn in self._cat_buttons.items():
            checked = (k == self._current_category)
            if checked:
                btn.setStyleSheet(f"""
                    QPushButton {{ background: {LEMON_ORANGE}; color: #111;
                        border: none; border-radius: 5px; padding: 5px 12px;
                        font-size: 12px; font-weight: 700; }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{ background: {BG_SURFACE}; color: {TEXT_SECONDARY};
                        border: 1px solid {BORDER_DEFAULT}; border-radius: 5px;
                        padding: 5px 12px; font-size: 12px; }}
                    QPushButton:hover {{ border-color: {LEMON_ORANGE}; color: {TEXT_PRIMARY}; }}
                """)

        # 侧栏分类按钮（与视图同风格）
        for k, btn in getattr(self, "_cat_buttons_sidebar", {}).items():
            checked = (k == self._current_category)
            if checked:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {BG_HOVER}; color: {LEMON_ORANGE};
                        border: none; border-left: 3px solid {LEMON_ORANGE};
                        border-radius: 0px; padding: 8px 12px 8px 10px;
                        text-align: left; font-size: 12px; font-weight: 600;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: transparent; color: {TEXT_SECONDARY};
                        border: none; border-left: 3px solid transparent;
                        border-radius: 0px; padding: 8px 12px 8px 10px;
                        text-align: left; font-size: 12px;
                    }}
                    QPushButton:hover {{ color: {TEXT_PRIMARY}; background: {BG_HOVER}; }}
                """)

    def _on_search(self, text):
        self._search_text = text.strip().lower()
        self._refresh()

    def _on_cat_changed(self, key, checked):
        self._current_category = key if checked else ""
        self._update_view_styles()
        self._refresh()

    def _on_refresh(self):
        self._load_market()

    def _on_create_local_plugin(self):
        """v4.8: 打开本地插件创建对话框"""
        market = self._get_market()
        if market is None:
            QMessageBox.warning(self, "创建插件", "插件市场未初始化")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("创建本地插件")
        dialog.setMinimumWidth(420)
        dialog.setStyleSheet(f"""
            QDialog {{ background-color: {BG_ROOT}; color: {TEXT_PRIMARY}; }}
            QLabel {{ color: {TEXT_PRIMARY}; background: transparent; }}
            QLineEdit, QTextEdit {{
                background-color: {BG_SURFACE}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT}; border-radius: 6px;
                padding: 6px 10px; font-size: 13px;
            }}
            QLineEdit:focus, QTextEdit:focus {{ border-color: {LEMON_ORANGE}; }}
            QPushButton {{ background: {BG_SURFACE}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT}; border-radius: 6px;
                padding: 6px 16px; font-size: 13px; }}
            QPushButton:hover {{ border-color: {LEMON_ORANGE}; }}
            QPushButton#create_ok {{ background: {LEMON_ORANGE}; color: #111;
                border: none; font-weight: 600; }}
            QPushButton#create_ok:hover {{ background: {LEMON_ORANGE_LIGHT}; }}
        """)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)

        form_fields = [
            ("插件标识 (英文):", "plugin_id", "my_plugin"),
            ("显示名称:", "display_name", "我的插件"),
            ("图标 (emoji):", "icon", "🧩"),
            ("分类:", "category", "tool"),
        ]

        inputs = {}
        for label_text, key, placeholder in form_fields:
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setFixedWidth(120)
            row.addWidget(lbl)
            edit = QLineEdit()
            edit.setPlaceholderText(placeholder)
            if key == "plugin_id":
                edit.setValidator(None)
            row.addWidget(edit, 1)
            inputs[key] = edit
            layout.addLayout(row)

        desc_label = QLabel("插件描述:")
        layout.addWidget(desc_label)
        desc_edit = QTextEdit()
        desc_edit.setPlaceholderText("描述这个插件的功能...")
        desc_edit.setMaximumHeight(60)
        layout.addWidget(desc_edit)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(dialog.reject)
        btn_row.addWidget(cancel_btn)
        ok_btn = QPushButton("创建")
        ok_btn.setObjectName("create_ok")
        ok_btn.clicked.connect(dialog.accept)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

        if dialog.exec_() == QDialog.Accepted:
            result = market.create_local_plugin(
                name=inputs["plugin_id"].text().strip(),
                display_name=inputs["display_name"].text().strip(),
                description=desc_edit.toPlainText().strip(),
                category=inputs["category"].text().strip() or "tool",
                icon=inputs["icon"].text().strip() or "🧩",
            )
            if result.get("ok"):
                msg = f"插件 '{result['name']}' 已创建\n路径: {result['path']}"
                if result.get("warning"):
                    msg += f"\n\n⚠️ {result['warning']}"
                QMessageBox.information(self, "创建成功", msg)
                self._load_market()
            else:
                QMessageBox.critical(self, "创建失败", result.get("error", "未知错误"))

    def _refresh(self):
        self._clear_grid()
        filtered = []
        for info in self._all_infos:
            if self._current_category and info.category != self._current_category:
                continue
            if self._view == "featured" and not getattr(info, "featured", False):
                continue
            if self._view == "installed" and not getattr(info, "is_installed", False):
                continue
            if self._view == "latest" and getattr(info, "badge", "") not in ("NEW", "HOT", "推荐"):
                continue
            if self._search_text:
                hay = f"{info.name} {info.display_name} {info.description} {info.author}".lower()
                if self._search_text not in hay:
                    continue
            filtered.append(info)
        self._cards = {}
        for i, info in enumerate(filtered):
            card = _PluginCard(info)
            card.install_clicked.connect(self._on_install)
            card.uninstall_clicked.connect(self._on_uninstall)
            card.clicked.connect(self._show_detail)
            self._cards[info.name] = card
            self._cards_grid.addWidget(card, i, 0)
        if not filtered:
            empty = QLabel("没有找到匹配的插件，换个分类或搜索词试试")
            empty.setStyleSheet(f"color: {EMPTY_TEXT_COLOR}; font-size: 13px; padding: 40px;")
            empty.setAlignment(Qt.AlignCenter)
            self._cards_grid.addWidget(empty, 0, 0)
        total = len(self._all_infos)
        installed = sum(1 for i in self._all_infos if i.is_installed)
        shown = len(filtered)
        self._status_label.setText(
            f"共 {total} 个插件 · 已安装 {installed} · 当前显示 {shown}"
        )

    def _clear_grid(self):
        while self._cards_grid.count():
            item = self._cards_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _on_install(self, name):
        market = self._get_market()
        if market is None:
            return
        try:
            result = market.install(name)
            if result.get("ok"):
                self._sync_installed_state()
                self._refresh()
                self.plugin_installed.emit(name)
                self._status_label.setStyleSheet(f"color: {SUCCESS_COLOR}; font-size: 12px;")
                self._status_label.setText(f"已安装 {name}")
            else:
                self._status_label.setStyleSheet(f"color: {ERROR_COLOR}; font-size: 12px;")
                self._status_label.setText(f"安装失败：{result.get('error')}")
        except Exception as e:
            self._status_label.setStyleSheet(f"color: {ERROR_COLOR}; font-size: 12px;")
            self._status_label.setText(f"安装异常：{e}")

    def _on_uninstall(self, name):
        market = self._get_market()
        if market is None:
            return
        ret = QMessageBox.question(
            self, "确认卸载", f"确定要卸载 {name} 吗？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return
        try:
            result = market.uninstall(name)
            if result.get("ok"):
                self._sync_installed_state()
                self._refresh()
                self.plugin_uninstalled.emit(name)
                self._status_label.setStyleSheet(f"color: {WARNING_COLOR}; font-size: 12px;")
                self._status_label.setText(f"已卸载 {name}")
            else:
                self._status_label.setStyleSheet(f"color: {ERROR_COLOR}; font-size: 12px;")
                self._status_label.setText(f"卸载失败：{result.get('error')}")
        except Exception as e:
            self._status_label.setStyleSheet(f"color: {ERROR_COLOR}; font-size: 12px;")
            self._status_label.setText(f"卸载异常：{e}")

    # ============================================================
    # 详情预览
    # ============================================================

    def _show_detail(self, name):
        info = None
        for i in self._all_infos:
            if i.name == name:
                info = i
                break
        if info is None:
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(info.display_name or info.name)
        dlg.setMinimumSize(520, 460)
        dlg.setStyleSheet(f"background-color: {BG_ROOT};")

        root = QVBoxLayout(dlg)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(12)

        # 头部：图标 + 名称 + 来源
        head = QHBoxLayout()
        head.setSpacing(14)
        big_icon = QLabel()
        big_icon.setFixedSize(52, 52)
        try:
            cat_key = info.category or "other"
            svg_str = get_svg_icon(_CAT_ICONS.get(cat_key, "file_default"), size=48, color=LEMON_ORANGE)
            ipm = _render_svg_pixmap(svg_str, 48, LEMON_ORANGE)
            if ipm is None or ipm.width() == 0:
                ipm = _render_initial_icon((info.display_name or info.name or "?")[0:1], 48, LEMON_ORANGE)
        except Exception:
            ipm = _render_initial_icon((info.display_name or info.name or "?")[0:1], 48, LEMON_ORANGE)
        big_icon.setPixmap(ipm)
        head.addWidget(big_icon)

        tcol = QVBoxLayout()
        tcol.setSpacing(3)
        tname = QLabel(info.display_name or info.name)
        tname.setFont(QFont("Microsoft YaHei UI", 16, QFont.Bold))
        tname.setStyleSheet(f"color: {TEXT_PRIMARY}; background: transparent;")
        tcol.addWidget(tname)

        src = "内置" if info.is_builtin else "远程"
        src_bg = TAG_BG_BUILTIN if info.is_builtin else TAG_BG_REMOTE
        src_fg = TAG_TEXT_BUILTIN if info.is_builtin else TAG_TEXT_REMOTE
        src_tag = QLabel(f"{src} · v{info.version} · {info.category}")
        src_tag.setStyleSheet(f"""
            color: {src_fg}; background: {src_bg}; border-radius: {TAG_RADIUS};
            font-size: {TAG_FONT_SIZE}; font-weight: 600; padding: 2px 8px;
        """)
        tcol.addWidget(src_tag)
        head.addLayout(tcol, 1)
        root.addLayout(head)

        # 星级 + 下载量
        stat_row = QHBoxLayout()
        stat_row.setSpacing(10)
        rating = getattr(info, "rating", 4.5) or 4.5
        downloads = getattr(info, "downloads", 0) or 0
        s = QLabel(f"{_rating_stars(rating)}  {float(rating):.1f}")
        s.setStyleSheet(f"color: {LEMON_ORANGE}; font-size: 15px; background: transparent;")
        stat_row.addWidget(s)
        d = QLabel(f"下载量 {_format_downloads(downloads)}")
        d.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px; background: transparent;")
        stat_row.addWidget(d)
        if info.author:
            a = QLabel(f"作者 {info.author}")
            a.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; background: transparent;")
            stat_row.addWidget(a)
        stat_row.addStretch()
        root.addLayout(stat_row)

        # 标签
        if info.tags:
            tags_row = QHBoxLayout()
            tags_row.setSpacing(6)
            for t in info.tags[:6]:
                tb = QLabel(f" #{t} ")
                tb.setStyleSheet(f"""
                    color: {TEXT_TERTIARY}; background: {BG_SURFACE};
                    border: 1px solid {BORDER_DEFAULT}; border-radius: 10px;
                    font-size: 11px; padding: 2px 8px;
                """)
                tags_row.addWidget(tb)
            tags_row.addStretch()
            root.addLayout(tags_row)

        # 描述
        desc = QTextEdit()
        desc.setReadOnly(True)
        desc.setPlainText(info.description or "（无描述）")
        desc.setStyleSheet(f"""
            QTextEdit {{
                background: {BG_SURFACE}; color: {TEXT_SECONDARY};
                border: 1px solid {BORDER_DEFAULT}; border-radius: {RADIUS_MD};
                padding: 10px; font-size: 13px;
            }}
        """)
        desc.setMinimumHeight(90)
        root.addWidget(desc, 1)

        # 操作按钮
        btns = QHBoxLayout()
        btns.addStretch()
        if info.is_installed:
            btn = QPushButton("卸载")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{ background: transparent; color: {ERROR_COLOR};
                    border: 1px solid {ERROR_COLOR}; border-radius: 6px; padding: 7px 20px;
                    font-size: 13px; font-weight: 600; }}
                QPushButton:hover {{ background: rgba(255,82,82,0.15); }}
            """)
            btn.clicked.connect(lambda: self._do_uninstall_from_detail(dlg, name))
        else:
            btn = QPushButton("安装")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{ background: {LEMON_ORANGE}; color: #111;
                    border: none; border-radius: 6px; padding: 7px 22px;
                    font-size: 13px; font-weight: 700; }}
                QPushButton:hover {{ background: {LEMON_YELLOW}; }}
            """)
            btn.clicked.connect(lambda: self._do_install_from_detail(dlg, name))
        btns.addWidget(btn)
        root.addLayout(btns)

        dlg.exec_()

    def _do_install_from_detail(self, dlg, name):
        self._on_install(name)
        dlg.accept()

    def _do_uninstall_from_detail(self, dlg, name):
        self._on_uninstall(name)
        dlg.accept()
