# -*- coding: utf-8 -*-
"""
MIMO Code Agent — 统一设计系统
小米 × MIMO Code 融合主题
- 小米品牌橙 #ff6900
- MIMO 像素橙 #e67e22
- 深邃黑底 + 微光表面
"""

# ============================================================
# 品牌色
# ============================================================
LEMON_ORANGE = '#ff6900'         # 柠檬橙（主品牌色）
LEMON_ORANGE_LIGHT = '#ff8c42'   # 柠檬橙浅色
LEMON_ORANGE_DARK = '#cc5400'    # 柠檬橙深色
LEMON_YELLOW = '#ffd700'         # 柠檬黄（辅助色）
LEMON_YELLOW_LIGHT = '#ffe066'   # 柠檬黄浅色
LEMON_GOLD = '#d4a574'           # 柠檬金

XIAOMI_ORANGE = LEMON_ORANGE     # 兼容旧变量
XIAOMI_ORANGE_LIGHT = LEMON_ORANGE_LIGHT
XIAOMI_ORANGE_DARK = LEMON_ORANGE_DARK
MIMO_ORANGE = LEMON_ORANGE       # 兼容旧变量
MIMO_ORANGE_LIGHT = LEMON_ORANGE_LIGHT
MIMO_GOLD = LEMON_GOLD

# ============================================================
# 背景层级
# ============================================================
BG_ROOT = '#080808'             # 最底层（窗口背景）
BG_PRIMARY = '#0d0d0d'          # 主背景
BG_SECONDARY = '#111111'        # 次级背景
BG_SURFACE = '#161616'          # 卡片表面
BG_SURFACE_HOVER = '#1c1c1c'    # 悬停表面
BG_SURFACE_ACTIVE = '#222222'   # 激活表面
BG_OVERLAY = 'rgba(0,0,0,0.6)'  # 遮罩
BG_GLASS = 'rgba(18,18,18,0.85)'# 玻璃效果
BG_ELEVATED = '#1a1a2a'         # 提升层

BG_DARK = BG_ROOT               # 兼容新面板变量
BG_PANEL = BG_PRIMARY

# ============================================================
# 边框
# ============================================================
BORDER_SUBTLE = '#1a1a1a'
BORDER_DEFAULT = '#252525'
BORDER_STRONG = '#333333'
BORDER_FOCUS = '#ff6900'
BORDER_FOCUS_MIMO = '#e67e22'

# ============================================================
# 文字层级
# ============================================================
TEXT_PRIMARY = '#ffffff'
TEXT_SECONDARY = '#b0b0b0'
TEXT_TERTIARY = '#808080'
TEXT_MUTED = '#555555'
TEXT_DISABLED = '#3a3a3a'
TEXT_PLACEHOLDER = '#4a4a4a'

# ============================================================
# 语义色
# ============================================================
SUCCESS_COLOR = '#4caf50'
SUCCESS = SUCCESS_COLOR
SUCCESS_BG = '#0a2a0e'
SUCCESS_BORDER = '#2d6a30'

ERROR_COLOR = '#ff5252'
ERROR = ERROR_COLOR
ERROR_BG = '#2a0a0a'
ERROR_BORDER = '#6a2d2d'

WARNING_COLOR = '#ffab40'
WARNING = WARNING_COLOR
WARNING_BG = '#2a1a0a'
WARNING_BORDER = '#6a4d2d'

INFO_COLOR = '#448aff'
INFO = INFO_COLOR
INFO_BG = '#0a1a2a'
INFO_BORDER = '#2d4d6a'

# ============================================================
# Diff 专用色
# ============================================================
DIFF_ADD_BG = '#0a2a0e'
DIFF_ADD_BG_LINE = '#122d1e'
DIFF_ADD_TEXT = '#4caf50'
DIFF_ADD_GUTTER = '#2d6a30'
DIFF_REMOVE_BG = '#2a0a0a'
DIFF_REMOVE_BG_LINE = '#3d151a'
DIFF_REMOVE_TEXT = '#ff5252'
DIFF_REMOVE_GUTTER = '#6a2d2d'

# ============================================================
# 语法高亮色
# ============================================================
SYNTAX_KEYWORD = '#ff6a00'       # 关键字（小米橙）
SYNTAX_STRING = '#98c379'        # 字符串
SYNTAX_NUMBER = '#d19a66'        # 数字
SYNTAX_COMMENT = '#5c6370'       # 注释
SYNTAX_FUNCTION = '#61afef'      # 函数名
SYNTAX_CLASS = '#e5c07b'         # 类名
SYNTAX_DECORATOR = '#c678dd'     # 装饰器
SYNTAX_BUILTIN = '#56b6c2'       # 内置函数
SYNTAX_SELF = '#e06c75'          # self
SYNTAX_OPERATOR = '#abb2bf'      # 操作符

# ============================================================
# 字体
# ============================================================
FONT_SYSTEM = '"Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif'
FONT_MONO = '"Cascadia Code", "Consolas", "Fira Code", "JetBrains Mono", monospace'
FONT_BRAND = '"MiSans", "Segoe UI", "Microsoft YaHei", sans-serif'
FONT_CODE_LOGO = '"Consolas", "Courier New", monospace'
FONT_SIZE_XS = '14px'
FONT_SIZE_SM = '15px'
FONT_SIZE_BASE = '16px'
FONT_SIZE_MD = '17px'
FONT_SIZE_LG = '20px'
FONT_SIZE_XL = '26px'
FONT_SIZE_2XL = '34px'
FONT_SIZE_LOGO = '64px'

# ============================================================
# 间距
# ============================================================
SPACE_XS = '4px'
SPACE_SM = '8px'
SPACE_MD = '12px'
SPACE_LG = '16px'
SPACE_XL = '24px'
SPACE_2XL = '32px'

# ============================================================
# 圆角
# ============================================================
RADIUS_SM = '4px'
RADIUS_MD = '6px'
RADIUS_LG = '8px'
RADIUS_XL = '12px'
RADIUS_FULL = '9999px'
BORDER_RADIUS = RADIUS_MD         # 兼容新面板变量
FONT_FAMILY = FONT_SYSTEM         # 兼容新面板变量

# ============================================================
# 阴影
# ============================================================
SHADOW_SM = '0 1px 3px rgba(0,0,0,0.4)'
SHADOW_MD = '0 4px 12px rgba(0,0,0,0.5)'
SHADOW_LG = '0 8px 24px rgba(0,0,0,0.6)'
SHADOW_GLOW_ORANGE = '0 0 20px rgba(255,105,0,0.3)'
SHADOW_GLOW_MIMO = '0 0 20px rgba(230,126,34,0.3)'

# ============================================================
# ★ v3.97: 高级简约规范 — 卡片/标签/空态/徽章 设计系统
# ============================================================
# 卡片
CARD_BG = BG_SURFACE
CARD_BG_HOVER = BG_SURFACE_HOVER
CARD_BORDER = BORDER_DEFAULT
CARD_BORDER_FOCUS = LEMON_ORANGE
CARD_RADIUS = RADIUS_LG          # 8px 圆角，温和不刺眼
CARD_PADDING = '14px'
CARD_GAP = 10

# 标签/徽章
TAG_BG = BG_PANEL
TAG_BG_BUILTIN = SUCCESS_BG
TAG_TEXT_BUILTIN = SUCCESS_COLOR
TAG_BG_REMOTE = WARNING_BG
TAG_TEXT_REMOTE = WARNING_COLOR
TAG_RADIUS = RADIUS_SM
TAG_FONT_SIZE = '10px'

# 空态
EMPTY_TEXT_COLOR = TEXT_TERTIARY
EMPTY_ICON_SIZE = '48px'

# ============================================================
# 过渡
# ============================================================
TRANSITION_FAST = '150ms ease'
TRANSITION_BASE = '200ms ease'
TRANSITION_SLOW = '300ms ease'

# ============================================================
# 图标 (极简线条风格 SVG - 软件特色线条绘制)
# ============================================================
SVG_ICONS = {
    'folder': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>''',
    'folder_open': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-9l-3-4z"/></svg>''',
    'file_py': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
  <polyline points="14,2 14,8 20,8"/>
  <text x="6.5" y="16" font-size="7" font-weight="bold" fill="currentColor" font-family="monospace">PY</text>
</svg>''',
    'file_js': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
  <polyline points="14,2 14,8 20,8"/>
  <text x="7" y="16" font-size="7" font-weight="bold" fill="currentColor" font-family="monospace">JS</text>
</svg>''',
    'file_json': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
  <polyline points="14,2 14,8 20,8"/>
  <text x="5.5" y="16" font-size="6" font-weight="bold" fill="currentColor" font-family="monospace">JSON</text>
</svg>''',
    'file_md': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
  <polyline points="14,2 14,8 20,8"/>
  <text x="7" y="16" font-size="7" font-weight="bold" fill="currentColor" font-family="monospace">MD</text>
</svg>''',
    'file_html': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
  <polyline points="14,2 14,8 20,8"/>
  <text x="5.5" y="16" font-size="6" font-weight="bold" fill="currentColor" font-family="monospace">HTML</text>
</svg>''',
    'file_css': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
  <polyline points="14,2 14,8 20,8"/>
  <text x="6.5" y="16" font-size="7" font-weight="bold" fill="currentColor" font-family="monospace">CSS</text>
</svg>''',
    'file_txt': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
  <polyline points="14,2 14,8 20,8"/>
  <text x="7.5" y="16" font-size="7" font-weight="bold" fill="currentColor" font-family="monospace">TXT</text>
</svg>''',
    'file_img': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21,15 16,10 5,21"/></svg>''',
    'file_git': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
  <polyline points="14,2 14,8 20,8"/>
  <text x="6.5" y="16" font-size="7" font-weight="bold" fill="currentColor" font-family="monospace">GIT</text>
</svg>''',
    'file_default': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14,2 14,8 20,8"/></svg>''',
    'search': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>''',
    'git': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M6 21V9a9 9 0 0 0 9 9h6"/></svg>''',
    'run': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="5,3 19,12 5,21 5,3"/></svg>''',
    'build': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>''',
    'debug': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>''',
    'terminal': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="4,17 10,11 4,5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>''',
    'check': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20,6 9,17 4,12"/></svg>''',
    'cross': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>''',
    'warn': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>''',
    'info': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>''',
    'thinking': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>''',
    'tool': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>''',
    'plus': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>''',
    'minus': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"/></svg>''',
    'upload': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17,8 12,3 7,8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>''',
    'image': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21,15 16,10 5,21"/></svg>''',
    'chart': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>''',
    'chevron_down': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6,9 12,15 18,9"/></svg>''',
    'chevron_right': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9,18 15,12 9,6"/></svg>''',
    'refresh': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23,4 23,10 17,10"/><polyline points="1,20 1,14 7,14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>''',
    'send': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22,2 15,22 11,13 2,9 22,2"/></svg>''',
    'settings': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>''',
    # ===== Skill 个性化图标 =====
    'skill_formatter': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M4 7V4h16v3"/>
  <path d="M9 20h6"/>
  <path d="M12 4v16"/>
  <text x="3" y="14" font-size="5" font-weight="bold" fill="currentColor" font-family="monospace">{ }</text>
</svg>''',
    'skill_lint': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
  <line x1="12" y1="9" x2="12" y2="13"/>
  <line x1="12" y1="17" x2="12.01" y2="17"/>
  <text x="8.5" y="7.5" font-size="4" font-weight="bold" fill="currentColor" font-family="monospace">LINT</text>
</svg>''',
    'skill_test': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M9 2h6"/>
  <path d="M10 2v6"/>
  <path d="M14 2v6"/>
  <path d="M8 6h8"/>
  <path d="M12 6v12"/>
  <path d="M8 18h8"/>
  <text x="7" y="15" font-size="4.5" font-weight="bold" fill="currentColor" font-family="monospace">TEST</text>
</svg>''',
    'skill_scaffold': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <rect x="3" y="3" width="7" height="7" rx="1"/>
  <rect x="14" y="3" width="7" height="7" rx="1"/>
  <rect x="3" y="14" width="7" height="7" rx="1"/>
  <rect x="14" y="14" width="7" height="7" rx="1"/>
  <line x1="10" y1="6.5" x2="14" y2="6.5"/>
  <line x1="6.5" y1="10" x2="6.5" y2="14"/>
  <line x1="17.5" y1="10" x2="17.5" y2="14"/>
  <line x1="10" y1="17.5" x2="14" y2="17.5"/>
</svg>''',
    'skill_git': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="6" cy="6" r="2.5"/>
  <circle cx="18" cy="6" r="2.5"/>
  <circle cx="12" cy="18" r="2.5"/>
  <path d="M6 8.5v3a3 3 0 0 0 3 3h6a3 3 0 0 0 3-3v-3"/>
  <path d="M12 12.5v3"/>
  <text x="10" y="19.5" font-size="3.5" font-weight="bold" fill="currentColor" font-family="monospace">GIT</text>
</svg>''',
    'skill_default': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <polygon points="12,2 15,8.5 22,9.3 17,14.1 18.2 21 12,17.8 5.8,21 7,14.1 2,9.3 9,8.5 12,2"/>
</svg>''',
    # ===== 咩咩工具图标（与全站统一的极简线条风格）=====
    'pencil': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>''',
    'database': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>''',
    'palette': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="13.5" cy="6.5" r=".5" fill="currentColor"/><circle cx="17.5" cy="10.5" r=".5" fill="currentColor"/><circle cx="8.5" cy="7.5" r=".5" fill="currentColor"/><circle cx="6.5" cy="12.5" r=".5" fill="currentColor"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z"/></svg>''',
    'clipboard': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/><line x1="9" y1="12" x2="15" y2="12"/><line x1="9" y1="16" x2="13" y2="16"/></svg>''',
    'globe': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>''',
    'star': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>''',
    'user': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>''',
    'sheep': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4c-2.6 0-4.5 2-4.5 4.5 0 1.2-.6 2.2-1.7 2.8-1.9 1-2.8 3.2-2 5 1 2.2 3.2 3.7 5.7 3.7h5c2.5 0 4.7-1.5 5.7-3.7.8-1.8-.1-4-2-5-1.1-.6-1.7-1.6-1.7-2.8C16.5 6 14.6 4 12 4z"/><circle cx="9.5" cy="12.5" r=".5" fill="currentColor"/><circle cx="14" cy="12.5" r=".5" fill="currentColor"/><path d="M10 15.5c1.3 1 2.7 1 4 0"/></svg>''',
    'sparkles': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.9 5.8L20 10.7l-6.1 1.9L12 18.4l-1.9-5.8L4 10.7l6.1-1.9z"/><path d="M19 15l.9 2.6L22.5 18.5l-2.6.9L19 22l-.9-2.6-2.6-.9 2.6-.9z"/></svg>''',
    # 服务功能按钮（顶部右侧 4 个）
    'history': '''<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/></svg>''',
    'trash': '''<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><polyline points="3,6 5,6 21,6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/></svg>''',
    'download': '''<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7,10 12,15 17,10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>''',
    'help': '''<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>''',
    'close': '''<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>''',
    'chevron_up': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="18,15 12,9 6,15"/></svg>''',
    'alert_triangle': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>''',
    'file_doc': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14,2 14,8 20,8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10,9 9,9 8,9"/></svg>''',
    'eye': '''<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>''',
}


# ============================================================
# ★ 文件类型色板 — VSCode Material-Icon 12 色分类（暗色底适配）
#   单一来源为 ui/design/tokens.py::Lemon，此处做零风险回退。
#   设计意图：形状负责"这是什么文件"，颜色负责"这是哪一类文件"，
#   扫侧栏时按色块即可定位，不必逐行读扩展名。
# ============================================================
try:                                    # pragma: no cover - 导入失败时回退到字面量
    from ui.design.tokens import Lemon as _LemonTokens
except Exception:                       # 路径不同 / 冻结区缺失 → 用同值字面量
    _LemonTokens = None


def _tk(name, fallback):
    """从 design tokens 取值，取不到就用同值字面量"""
    return getattr(_LemonTokens, name, fallback) if _LemonTokens else fallback


FILE_C_BLUE = _tk('FILE_C_BLUE', '#519ABA')      # 主流语言 py/ts/cpp/c#
FILE_C_YELLOW = _tk('FILE_C_YELLOW', '#F0DB4F')  # 脚本 js/json/yaml
FILE_C_ORANGE = _tk('FILE_C_ORANGE', '#E34F26')  # 标记语言 html/xml/vue
FILE_C_CYAN = _tk('FILE_C_CYAN', '#4DD0E1')      # 样式 css/scss/less
FILE_C_GREEN = _tk('FILE_C_GREEN', '#89E051')    # shell/可执行/构建
FILE_C_PURPLE = _tk('FILE_C_PURPLE', '#C792EA')  # 数据 sql/db
FILE_C_PINK = _tk('FILE_C_PINK', '#FF80AB')      # 媒体 图片/音视频
FILE_C_RED = _tk('FILE_C_RED', '#F44336')        # pdf/归档/文档
FILE_C_BROWN = _tk('FILE_C_BROWN', '#DEA584')    # rust/编译产物
FILE_C_INDIGO = _tk('FILE_C_INDIGO', '#7986CB')  # 文档 md/doc/txt
FILE_C_LIME = _tk('FILE_C_LIME', '#C3E88D')      # 配置 toml/ini/env
FILE_C_GRAY = _tk('FILE_C_GRAY', '#9E9E9E')      # 兜底/未知类型

# ============================================================
# ★ 品牌色（V2，第352章补记3）— Simple Icons 官方 hex 的暗底提亮变体
#   规范来源：simpleicons.org（Python #3776AB → 暗底 #4B8BBE 等）。
#   语言文件一律用品牌色（主流 IDE 的共识），分类色 FILE_C_* 只服务
#   无品牌符号的杂类（txt/log/pdf/zip/媒体）与文件夹分层。
# ============================================================
BRAND_PYTHON = '#4B8BBE'     # Python 蓝（官方 #3776AB 提亮）
BRAND_JS = '#F7DF1E'         # JavaScript 黄
BRAND_TS = '#3178C6'         # TypeScript 蓝
BRAND_ETS = '#0A59F7'        # 鸿蒙 ArkTS（HarmonyOS 品牌蓝）
BRAND_JSON = '#CBCB41'       # JSON 黄
BRAND_HTML = '#E34F26'       # HTML5 橙
BRAND_CSS = '#1572B6'        # CSS3 蓝
BRAND_SCSS = '#CF649A'       # Sass 粉
BRAND_MD = '#519ABA'         # Markdown 蓝
BRAND_VUE = '#41B883'        # Vue 绿
BRAND_CPP = '#659AD2'        # C/C++ 六边形蓝（#00599C 提亮）
BRAND_CS = '#A074C4'         # C# 紫（#68217A 提亮）
BRAND_GO = '#00ADD8'         # Go 青
BRAND_RUST = '#DEA584'       # Rust 橙棕
BRAND_JAVA = '#F89820'       # Java 咖啡橙
BRAND_KOTLIN = '#9B7BFF'     # Kotlin 紫（#7F52FF 提亮）
BRAND_SWIFT = '#F05138'      # Swift 橙红
BRAND_DART = '#4FC3F7'       # Dart 天蓝（#0175C2 提亮）
BRAND_LUA = '#7B9AE1'        # Lua 月蓝（#000080 提亮）
BRAND_PHP = '#AEB2D5'        # PHP 淡紫（#777BB4 提亮）
BRAND_RUBY = '#E9573F'       # Ruby 宝石红（#CC342D 提亮）
BRAND_QT = '#41CD52'         # Qt/QML 绿
BRAND_SHELL = '#89E051'      # Shell 绿
BRAND_SQL = '#E48E00'        # SQL 金橙
BRAND_YAML = '#F14E4E'       # YAML 红（#CB171E 提亮）


# ============================================================
# ★ 文件类型图标库 — 折角文件壳 + 内部「1 个专属几何符号」
#   此前实现是「同款文件壳 + 内嵌 2 字母小字」（PY/JS/JSON…）：
#   小字号下文字糊成一团、形状又完全一样，py/js/json 几乎看不出区别。
#   改为几何符号后：16~24px 全档清晰，形状本身即语义。
# ============================================================
_FILE_SHELL = (
    '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
    '<polyline points="14,2 14,8 20,8"/>'
)
_FOLDER_SHELL = '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>'


def _file_svg(inner: str) -> str:
    """文件壳 + 内部几何符号 → 完整 SVG 字符串"""
    return (
        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">{_FILE_SHELL}{inner}</svg>'
    )


def _folder_svg(inner: str = '') -> str:
    """文件夹壳 + 内部分类符号 → 完整 SVG 字符串"""
    return (
        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">{_FOLDER_SHELL}{inner}</svg>'
    )


def _brand_svg(inner: str, sw: float = 1.8) -> str:
    """V2：无文件壳的品牌符号 —— 符号直出占满 24 画布（Material Icon Theme 式）。

    同 px 下无壳大符号的视觉尺寸比「壳+小字母」大 40%+，
    这是"图标怎么调都显小"的结构性解法。
    """
    return (
        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round">{inner}</svg>'
    )


def _text_svg(txt: str, size: float = 12) -> str:
    """V2：纯大字图标（JS/TS/GO/Qt/W/X/P 等官方即"字母徽章"的语言）。

    text 用 fill=currentColor + 同色 stroke 0.55 把字母加粗一圈
    （font-weight 700 的笔画在 24 viewBox 下仍偏细，实测填充率仅 ~9%）。
    渲染管线会把两处 currentColor 一并替换为品牌色。
    """
    return (
        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-linejoin="round">'
        f'<text x="12" y="17.5" font-size="{size}" font-weight="700" text-anchor="middle" '
        'font-family="Segoe UI, Arial, sans-serif" fill="currentColor" '
        f'stroke="currentColor" stroke-width="0.55">{txt}</text></svg>'
    )


FILE_SVG_ICONS = {
    # ============================================================
    # V2「语言符号直出」—— 无文件壳，品牌符号占满 24 画布
    # （对标 Material Icon Theme；文件壳只留给无品牌符号的杂类）
    # ============================================================

    # ---- 语言品牌符号（无壳）----
    # Python：双蛇互锁（上下两个大圆角方块 + 蛇眼）
    'file_py': _brand_svg('<rect x="5" y="3" width="14" height="9.5" rx="2.4"/>'
                          '<rect x="5" y="11.5" width="14" height="9.5" rx="2.4"/>'
                          '<circle cx="8.2" cy="6" r=".8" fill="currentColor" stroke="none"/>'
                          '<circle cx="15.8" cy="18" r=".8" fill="currentColor" stroke="none"/>',
                          1.8),
    # JS / TS：官方即「方框大字」，直接粗体大字输出
    'file_js': _text_svg('JS', 14),
    'file_ts': _text_svg('TS', 14),
    # 鸿蒙 ArkTS：圆角方 + 「e」（.ets 最高频，鸿蒙工程必备）
    'file_ets': _brand_svg('<rect x="3" y="3" width="18" height="18" rx="4"/>'
                           '<text x="12" y="16.5" font-size="11" font-weight="700" '
                           'text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" '
                           'fill="currentColor" stroke="none">e</text>', 1.7),
    # JSON：大花括号
    'file_json': _brand_svg('<path d="M10 3.5c-2 0-3 1-3 3v3c0 1.7-1 2.7-2.5 2.5 1.5-.2 2.5.8 2.5 2.5v3.5c0 2 1 3 3 3"/>'
                            '<path d="M14 3.5c2 0 3 1 3 3v3c0 1.7 1 2.7 2.5 2.5-1.5-.2-2.5.8-2.5 2.5v3.5c0 2-1 3-3 3"/>',
                            2.0),
    # HTML5 / CSS3：盾牌
    'file_html': _brand_svg('<path d="M4.5 3h15l-1.4 15.5L12 21l-6.1-2.5z"/>'
                            '<path d="M12 6.8v10.4l4-1.6.8-8.8z"/>', 1.7),
    'file_css': _brand_svg('<path d="M4.5 3h15l-1.4 15.5L12 21l-6.1-2.5z"/>'
                           '<path d="M8 8h8"/><path d="M8.5 11.5h7"/><path d="M12 15h3.5"/>', 1.7),
    # Markdown：圆角框 + M + 下箭头（Material 同款）
    'file_md': _brand_svg('<rect x="2.5" y="5" width="19" height="14" rx="2.5"/>'
                          '<path d="M6 15.5v-7l3 3.5 3-3.5v7"/>'
                          '<path d="M15.5 9v6.5"/><path d="M13.5 13.5l2 2 2-2"/>', 1.7),
    # Vue：双层 V
    'file_vue': _brand_svg('<path d="M2.5 4h4.8L12 11.5 16.7 4h4.8L12 21z"/>'
                           '<path d="M8.4 4L12 9.8 15.6 4"/>', 1.8),
    # C / C++ / 头文件：六边形 + 大字母（C++ 右上加号）
    'file_c': _brand_svg('<path d="M12 2.5l8.2 4.75v9.5L12 21.5l-8.2-4.75v-9.5z"/>'
                         '<text x="12" y="16" font-size="11" font-weight="700" text-anchor="middle" '
                         'font-family="Segoe UI, Arial, sans-serif" fill="currentColor" stroke="none">C</text>', 1.7),
    'file_cpp': _brand_svg('<path d="M12 2.5l8.2 4.75v9.5L12 21.5l-8.2-4.75v-9.5z"/>'
                           '<text x="10.5" y="15.8" font-size="10" font-weight="700" text-anchor="middle" '
                           'font-family="Segoe UI, Arial, sans-serif" fill="currentColor" stroke="none">C</text>'
                           '<path d="M16.2 7.5v4.4"/><path d="M14 9.7h4.4"/>', 1.7),
    'file_h': _brand_svg('<path d="M12 2.5l8.2 4.75v9.5L12 21.5l-8.2-4.75v-9.5z"/>'
                         '<text x="12" y="15.8" font-size="10" font-weight="700" text-anchor="middle" '
                         'font-family="Segoe UI, Arial, sans-serif" fill="currentColor" stroke="none">H</text>', 1.7),
    'file_cs': _brand_svg('<rect x="2.5" y="2.5" width="19" height="19" rx="4"/>'
                          '<text x="12" y="16" font-size="8.5" font-weight="700" text-anchor="middle" '
                          'font-family="Segoe UI, Arial, sans-serif" fill="currentColor" stroke="none">C#</text>', 1.7),
    'file_go': _text_svg('GO', 13),
    # Rust：大齿轮
    'file_rs': _brand_svg('<circle cx="12" cy="12" r="4.2"/><circle cx="12" cy="12" r="1.1"/>'
                          '<path d="M12 3v2.6M12 18.4V21M3 12h2.6M18.4 12H21"/>'
                          '<path d="M5.6 5.6l1.9 1.9M16.5 16.5l1.9 1.9M18.4 5.6l-1.9 1.9M7.5 16.5l-1.9 1.9"/>', 1.7),
    # Java：咖啡杯 + 蒸汽
    'file_java': _brand_svg('<path d="M6 9h10v6a4 4 0 0 1-4 4H10a4 4 0 0 1-4-4z"/>'
                            '<path d="M16 10.5h1.5a2.25 2.25 0 0 1 0 4.5H16"/>'
                            '<path d="M9.5 2.5c-.8 1.2.8 1.8 0 3"/><path d="M13 2.5c-.8 1.2.8 1.8 0 3"/>', 1.7),
    'file_jar': _brand_svg('<path d="M6.5 3.5h11l-1.3 15.8a2.2 2.2 0 0 1-2.2 2h-4a2.2 2.2 0 0 1-2.2-2z"/>'
                           '<path d="M7 8.5h10"/><path d="M7.4 13h9.2"/>', 1.7),
    # Kotlin：方形对角切角
    'file_kotlin': _brand_svg('<path d="M3.5 3.5h17L12 12l8.5 8.5h-17z"/>', 1.9),
    # Swift：飞鸟三弧
    'file_swift': _brand_svg('<path d="M3.5 16.5c6-1 9.5-5 11.5-10"/>'
                             '<path d="M15 6.5c-.8 3-2.8 5.3-6 6.8"/>'
                             '<path d="M6 19.5c5.5 0 10-3 12.5-9"/>', 1.8),
    # Dart：双翼
    'file_dart': _brand_svg('<path d="M11.5 2.5L3 11l4.5 4.5L16 7z"/>'
                            '<path d="M12.5 21.5L21 13l-4.5-4.5L8 17z"/>', 1.7),
    # Lua：月亮 + 伴星
    'file_lua': _brand_svg('<circle cx="10.5" cy="12.5" r="7.5"/><circle cx="19" cy="5" r="2.2"/>'
                           '<circle cx="8" cy="10.5" r=".7" fill="currentColor" stroke="none"/>'
                           '<circle cx="13" cy="14.5" r=".7" fill="currentColor" stroke="none"/>', 1.7),
    # PHP：椭圆 + php
    'file_php': _brand_svg('<ellipse cx="12" cy="12" rx="10" ry="6.5"/>'
                           '<text x="12" y="14.5" font-size="7.5" font-weight="700" text-anchor="middle" '
                           'font-family="Segoe UI, Arial, sans-serif" fill="currentColor" stroke="none">php</text>', 1.6),
    # Ruby：多面宝石
    'file_rb': _brand_svg('<path d="M7 3.5h10l4.5 5.5L12 21.5 2.5 9z"/>'
                          '<path d="M2.5 9h19"/><path d="M7 3.5L9.5 9 12 21.5 14.5 9 17 3.5"/>'
                          '<path d="M9.5 9h5"/>', 1.5),
    # Qt / QML
    'file_qml': _text_svg('Qt', 13),
    # Shell / bat / ps1：终端 >_
    'file_sh': _brand_svg('<path d="M4.5 4.5l7 7.5-7 7.5"/><path d="M13.5 19.5H20"/>', 2.2),
    'file_ps1': _brand_svg('<path d="M4.5 4.5l7 7.5-7 7.5"/><path d="M13.5 19.5H20"/>', 2.2),
    'file_bat': _brand_svg('<path d="M4.5 4.5l7 7.5-7 7.5"/><path d="M13.5 19.5H20"/>'
                           '<path d="M4.5 2.8h15"/>', 2.0),
    # SQL：数据库圆柱
    'file_sql': _brand_svg('<ellipse cx="12" cy="5.5" rx="7.5" ry="3"/>'
                           '<path d="M4.5 5.5v13c0 1.66 3.36 3 7.5 3s7.5-1.34 7.5-3v-13"/>'
                           '<path d="M4.5 12c0 1.66 3.36 3 7.5 3s7.5-1.34 7.5-3"/>', 1.8),
    # YAML：错落列表
    'file_yaml': _brand_svg('<path d="M4.5 6h10.5"/><path d="M4.5 12h15"/><path d="M4.5 18h10.5"/>', 2.0),
    # TOML / INI / 配置：表格
    'file_toml': _brand_svg('<rect x="3.5" y="5" width="17" height="14" rx="2"/>'
                            '<path d="M3.5 11.5h17"/><path d="M10 5v14"/>', 1.7),
    # 挂锁 / 归档 / 可执行
    'file_lock': _brand_svg('<rect x="5" y="10.5" width="14" height="10" rx="2"/>'
                            '<path d="M8 10.5V7.5a4 4 0 0 1 8 0v3"/>', 2.0),
    'file_zip': _brand_svg('<rect x="5.5" y="3" width="13" height="18" rx="2"/>'
                           '<path d="M10 6.5h4"/><path d="M10 10h4"/><path d="M10 13.5h4"/>', 1.7),
    'file_exe': _brand_svg('<rect x="3.5" y="4.5" width="17" height="15" rx="2"/>'
                           '<path d="M10 9.5l5 2.5-5 2.5z"/>', 1.7),
    # Git 分支
    'file_git': _brand_svg('<path d="M6 3.5v11"/><circle cx="17.5" cy="6" r="2.8"/>'
                           '<circle cx="6" cy="18.5" r="2.8"/>'
                           '<path d="M17.5 8.8a8.5 8.5 0 0 1-8.5 8.2"/>', 1.7),
    # ---- Office 字母徽章（微软官方即字母方章）----
    'file_doc': _text_svg('W', 14),
    'file_xls': _text_svg('X', 14),
    'file_ppt': _text_svg('P', 14),
    'file_pdf': _text_svg('PDF', 8.5),
    # ---- 媒体（无品牌符号，用通用大符号）----
    'file_img': _brand_svg('<rect x="3" y="4" width="18" height="16" rx="2"/>'
                           '<circle cx="9" cy="9.5" r="1.8"/>'
                           '<path d="M21 15.5l-5-5L5 21"/>', 1.7),
    'file_audio': _brand_svg('<path d="M9 18.5V6l10-2v12.5"/>'
                             '<circle cx="6.5" cy="18.5" r="2.5"/><circle cx="16.5" cy="16.5" r="2.5"/>', 1.7),
    'file_video': _brand_svg('<rect x="3" y="6" width="13" height="12" rx="2"/>'
                             '<path d="M16 10.5l5-3v9l-5-3z"/>', 1.7),
    # ---- 杂类（保留文件壳：无品牌符号可用）----
    'file_txt': _file_svg('<path d="M8 12.5h8"/><path d="M8 15.5h8"/><path d="M8 18.5h5"/>'),
    # ---- 文件夹分层（开底 + 分类符号，Material 风格）----
    'folder_src': _folder_svg('<path d="M10 13.5l-2 2.5 2 2.5"/>'
                              '<path d="M14 13.5l2 2.5-2 2.5"/>'),
    'folder_doc': _folder_svg('<path d="M8.5 14h7"/><path d="M8.5 17h4.5"/>'),
    'folder_img': _folder_svg('<path d="M7.5 18.5l3-3.5 2 2.5 1.5-2 3 3z"/>'
                              '<circle cx="9.5" cy="14" r=".9"/>'),
    'folder_test': _folder_svg('<path d="M8.5 16.5l2.5 2.5 4.5-5"/>'),
    'folder_build': _folder_svg('<circle cx="12" cy="16" r="2"/><path d="M12 12.8v1"/>'
                                '<path d="M12 18.2v1"/><path d="M8.8 16h1"/><path d="M14.2 16h1"/>'),
    'folder_git': _folder_svg('<circle cx="9.5" cy="14.3" r="1.3"/>'
                              '<circle cx="9.5" cy="18" r="1.3"/><circle cx="14.5" cy="18" r="1.3"/>'
                              '<path d="M9.5 15.6v1.1"/><path d="M10.8 18h2.4"/>'),
}

# 合并进主图标表（同名键覆盖 V1「壳+符号」实现）
SVG_ICONS.update(FILE_SVG_ICONS)


# 扩展名/全文件名 → (图标名, 品牌色/分类色)。
# 语言类一律品牌色（Simple Icons 暗底提亮变体）；杂类用分类色 FILE_C_*。
FILE_TYPE_MAP = {
    # ---- 全文件名（无扩展名兜底，explorer 先按整名查）----
    'dockerfile': ('file_sh', BRAND_SHELL),
    'makefile': ('file_sh', FILE_C_GRAY),
    'license': ('file_txt', FILE_C_GRAY), 'licence': ('file_txt', FILE_C_GRAY),
    # ---- Python 系 ----
    '.py': ('file_py', BRAND_PYTHON), '.pyw': ('file_py', BRAND_PYTHON),
    '.pyi': ('file_py', BRAND_PYTHON), '.pyx': ('file_py', BRAND_PYTHON),
    # ---- JS / TS / ArkTS ----
    '.js': ('file_js', BRAND_JS), '.jsx': ('file_js', BRAND_JS),
    '.mjs': ('file_js', BRAND_JS), '.cjs': ('file_js', BRAND_JS),
    '.ts': ('file_ts', BRAND_TS), '.tsx': ('file_ts', BRAND_TS),
    '.mts': ('file_ts', BRAND_TS), '.cts': ('file_ts', BRAND_TS),
    '.ets': ('file_ets', BRAND_ETS), '.etsx': ('file_ets', BRAND_ETS),
    '.json': ('file_json', BRAND_JSON), '.jsonc': ('file_json', BRAND_JSON),
    '.json5': ('file_json', BRAND_JSON),
    '.lock': ('file_lock', FILE_C_GRAY),
    # ---- 标记 / 样式 ----
    '.html': ('file_html', BRAND_HTML), '.htm': ('file_html', BRAND_HTML),
    '.xhtml': ('file_html', BRAND_HTML), '.xml': ('file_html', BRAND_HTML),
    '.xaml': ('file_html', BRAND_HTML), '.fxml': ('file_html', BRAND_HTML),
    '.svg': ('file_img', FILE_C_PINK),
    '.css': ('file_css', BRAND_CSS), '.less': ('file_css', BRAND_CSS),
    '.scss': ('file_css', BRAND_SCSS), '.sass': ('file_css', BRAND_SCSS),
    '.md': ('file_md', BRAND_MD), '.markdown': ('file_md', BRAND_MD),
    '.mdx': ('file_md', BRAND_MD), '.rst': ('file_md', BRAND_MD),
    '.vue': ('file_vue', BRAND_VUE),
    # ---- C 家族 ----
    '.c': ('file_c', BRAND_CPP), '.m': ('file_c', BRAND_CPP),
    '.cpp': ('file_cpp', BRAND_CPP), '.cc': ('file_cpp', BRAND_CPP),
    '.cxx': ('file_cpp', BRAND_CPP), '.mm': ('file_cpp', BRAND_CPP),
    '.h': ('file_h', BRAND_CS), '.hpp': ('file_h', BRAND_CS), '.hh': ('file_h', BRAND_CS),
    '.cs': ('file_cs', BRAND_CS),
    # ---- 系统级语言 ----
    '.go': ('file_go', BRAND_GO), '.rs': ('file_rs', BRAND_RUST),
    '.java': ('file_java', BRAND_JAVA), '.jar': ('file_jar', BRAND_JAVA),
    '.kt': ('file_kotlin', BRAND_KOTLIN), '.kts': ('file_kotlin', BRAND_KOTLIN),
    '.swift': ('file_swift', BRAND_SWIFT), '.dart': ('file_dart', BRAND_DART),
    '.lua': ('file_lua', BRAND_LUA), '.php': ('file_php', BRAND_PHP),
    '.rb': ('file_rb', BRAND_RUBY),
    '.qml': ('file_qml', BRAND_QT), '.qrc': ('file_qml', BRAND_QT),
    '.ui': ('file_qml', BRAND_QT), '.pro': ('file_qml', BRAND_QT),
    # ---- 脚本 / 可执行 ----
    '.sh': ('file_sh', BRAND_SHELL), '.bash': ('file_sh', BRAND_SHELL),
    '.zsh': ('file_sh', BRAND_SHELL), '.fish': ('file_sh', BRAND_SHELL),
    '.ps1': ('file_ps1', BRAND_CS), '.bat': ('file_bat', BRAND_SHELL),
    '.cmd': ('file_bat', BRAND_SHELL),
    '.exe': ('file_exe', FILE_C_GREEN), '.wasm': ('file_exe', FILE_C_PURPLE),
    '.dll': ('file_exe', FILE_C_PURPLE), '.so': ('file_exe', FILE_C_PURPLE),
    '.pyd': ('file_exe', FILE_C_PURPLE),
    # ---- 数据 / 配置 ----
    '.sql': ('file_sql', BRAND_SQL), '.db': ('file_sql', BRAND_SQL),
    '.sqlite': ('file_sql', BRAND_SQL),
    '.proto': ('file_toml', FILE_C_INDIGO),
    '.graphql': ('file_json', '#E535AB'), '.gql': ('file_json', '#E535AB'),
    '.yaml': ('file_yaml', BRAND_YAML), '.yml': ('file_yaml', BRAND_YAML),
    '.toml': ('file_toml', FILE_C_LIME), '.ini': ('file_toml', FILE_C_LIME),
    '.cfg': ('file_toml', FILE_C_LIME), '.conf': ('file_toml', FILE_C_LIME),
    '.env': ('file_toml', FILE_C_LIME), '.properties': ('file_toml', FILE_C_LIME),
    '.gradle': ('file_java', BRAND_JAVA),
    '.cmake': ('file_toml', FILE_C_GREEN),
    # ---- 版本控制 ----
    '.gitignore': ('file_git', FILE_C_ORANGE),
    '.gitattributes': ('file_git', FILE_C_ORANGE),
    '.gitmodules': ('file_git', FILE_C_ORANGE),
    # ---- 文档 ----
    '.txt': ('file_txt', FILE_C_INDIGO), '.log': ('file_txt', FILE_C_GRAY),
    '.pdf': ('file_pdf', FILE_C_RED),
    '.doc': ('file_doc', FILE_C_BLUE), '.docx': ('file_doc', FILE_C_BLUE),
    '.xls': ('file_xls', FILE_C_GREEN), '.xlsx': ('file_xls', FILE_C_GREEN),
    '.csv': ('file_xls', FILE_C_GREEN),
    '.ppt': ('file_ppt', FILE_C_ORANGE), '.pptx': ('file_ppt', FILE_C_ORANGE),
    '.ipynb': ('file_json', '#F37726'),
    # ---- 媒体 ----
    '.png': ('file_img', FILE_C_PINK), '.jpg': ('file_img', FILE_C_PINK),
    '.jpeg': ('file_img', FILE_C_PINK), '.gif': ('file_img', FILE_C_PINK),
    '.bmp': ('file_img', FILE_C_PINK), '.webp': ('file_img', FILE_C_PINK),
    '.ico': ('file_img', FILE_C_PINK),
    '.mp3': ('file_audio', FILE_C_PINK), '.wav': ('file_audio', FILE_C_PINK),
    '.flac': ('file_audio', FILE_C_PINK), '.ogg': ('file_audio', FILE_C_PINK),
    '.mp4': ('file_video', FILE_C_PINK), '.avi': ('file_video', FILE_C_PINK),
    '.mov': ('file_video', FILE_C_PINK), '.mkv': ('file_video', FILE_C_PINK),
    # ---- 归档 / 包（含鸿蒙 .hap/.har/.app）----
    '.zip': ('file_zip', FILE_C_GRAY), '.tar': ('file_zip', FILE_C_GRAY),
    '.gz': ('file_zip', FILE_C_GRAY), '.7z': ('file_zip', FILE_C_GRAY),
    '.rar': ('file_zip', FILE_C_GRAY),
    '.apk': ('file_zip', FILE_C_GREEN), '.hap': ('file_zip', FILE_C_GREEN),
    '.har': ('file_zip', FILE_C_GREEN), '.app': ('file_zip', FILE_C_GREEN),
}

# 目录名 → (图标名, 色板色)。含鸿蒙 ArkTS 工程结构（entry/pages/ets/AppScope）。
FOLDER_TYPE_MAP = {
    # 通用
    'src': ('folder_src', FILE_C_BLUE), 'lib': ('folder_src', FILE_C_BLUE),
    'core': ('folder_src', FILE_C_BLUE), 'app': ('folder_src', FILE_C_BLUE),
    'components': ('folder_src', FILE_C_CYAN), 'ui': ('folder_src', FILE_C_CYAN),
    'widgets': ('folder_src', FILE_C_CYAN),
    'docs': ('folder_doc', FILE_C_INDIGO), 'doc': ('folder_doc', FILE_C_INDIGO),
    'data': ('folder_doc', FILE_C_GRAY), 'logs': ('folder_doc', FILE_C_GRAY),
    'assets': ('folder_img', FILE_C_PINK), 'images': ('folder_img', FILE_C_PINK),
    'img': ('folder_img', FILE_C_PINK), 'icons': ('folder_img', FILE_C_PINK),
    'media': ('folder_img', FILE_C_PINK), 'fonts': ('folder_img', FILE_C_INDIGO),
    'tests': ('folder_test', FILE_C_GREEN), 'test': ('folder_test', FILE_C_GREEN),
    'spec': ('folder_test', FILE_C_GREEN), '__tests__': ('folder_test', FILE_C_GREEN),
    'build': ('folder_build', FILE_C_BROWN), 'dist': ('folder_build', FILE_C_BROWN),
    'out': ('folder_build', FILE_C_BROWN), 'target': ('folder_build', FILE_C_BROWN),
    '.git': ('folder_git', FILE_C_ORANGE), '.github': ('folder_git', FILE_C_ORANGE),
    # ---- 鸿蒙 ArkTS 工程（DevEco / HUAWEI.MIEMIE 结构）----
    'entry': ('folder_src', BRAND_ETS),
    'pages': ('folder_src', BRAND_ETS),
    'ets': ('folder_src', BRAND_ETS),
    'appscope': ('folder_src', BRAND_ETS),
    'ability': ('folder_src', BRAND_ETS),
    'resources': ('folder_img', BRAND_ETS),
    'rawfile': ('folder_doc', FILE_C_GRAY),
}


def get_file_icon_spec(ext_or_name: str, is_dir: bool = False):
    """扩展名/目录名 → (图标名, 色板色)。未命中返回兜底。

    用法::

        get_file_icon_spec('.py')        # ('file_py', '#519ABA')
        get_file_icon_spec('src', True)  # ('folder_src', '#519ABA')
    """
    key = (ext_or_name or '').lower()
    if is_dir:
        return FOLDER_TYPE_MAP.get(key, ('folder', FILE_C_BLUE))
    return FILE_TYPE_MAP.get(key, ('file_default', FILE_C_GRAY))


# stroke-width 随尺寸自适应：放大时线条不过粗、缩小时不过细（等效 non-scaling-stroke）
_STROKE_BY_SIZE = {14: 1.25, 16: 1.5, 18: 1.6, 20: 1.75, 22: 1.9, 24: 2.0}


def get_svg_icon(name, size=16, color='currentColor'):
    """获取SVG图标，可自定义大小和颜色。

    ★ 尺寸自适应：stroke-width 按 size 查表缩放（16→1.5 / 20→1.75 / 24→2.0），
      解决此前「SVG 写死 16×16、放大后比例失衡糊成一团」的问题。
    """
    import re as _re_icon
    svg = SVG_ICONS.get(name, SVG_ICONS['file_default'])
    svg = _re_icon.sub(r'width="\d+"', f'width="{size}"', svg)
    svg = _re_icon.sub(r'height="\d+"', f'height="{size}"', svg)
    sw = _STROKE_BY_SIZE.get(size, max(1.0, round(1.5 * size / 16.0, 2)))
    svg = _re_icon.sub(r'stroke-width="[\d.]+"', f'stroke-width="{sw}"', svg)
    if color != 'currentColor':
        svg = svg.replace('stroke="currentColor"', f'stroke="{color}"')
        svg = svg.replace('fill="currentColor"', f'fill="{color}"')
    return svg


# ============================================================
# ★ 节日装饰组件系统（SVG + CSS + 祝福语）
# ============================================================

# 节日祝福语库
FESTIVAL_BLESSINGS = {
    'christmas': [
        '🎄 圣诞快乐！愿您在这个温馨的节日里收获满满的幸福',
        '🎅 Merry Christmas！愿圣诞老人为您带来惊喜与欢乐',
        '⭐ 平安夜快乐！愿星光照亮您前行的道路',
        '🔔 铃儿响叮当，幸福来敲门！圣诞快乐！',
        '🎁 愿这份节日的温暖陪伴您度过美好时光',
    ],
    'halloween': [
        '🎃 万圣节快乐！不给糖就捣蛋！',
        '👻 Trick or Treat！愿您度过一个神秘的夜晚',
        '🦇 万圣狂欢夜，释放您的奇思妙想',
        '🕷️ 愿南瓜灯照亮您的创意之路',
        '🌙 幽灵出没，惊喜不断！万圣节快乐！',
    ],
    'cny': [
        '🧧 新春大吉！愿您在新的一年里万事如意',
        '🏮 恭喜发财！愿红包带来满满的好运',
        '🐉 龙年大吉！愿您龙腾虎跃，前程似锦',
        '🎊 春节快乐！愿鞭炮声声带来好运',
        '💝 年年有余！愿您的生活红红火火',
    ],
    'newyear': [
        '🎆 新年快乐！愿新的一年充满希望与美好',
        '✨ 2024，新的开始，新的精彩！',
        '🎉 辞旧迎新，愿您在新的一年里心想事成',
        '🌟 新年新气象，愿梦想照进现实',
        '🎊 新年钟声响，幸福满人间',
    ],
    'valentine': [
        '💕 情人节快乐！愿爱永远陪伴您',
        '💗 爱在心中，情暖人间',
        '🌹 愿这朵玫瑰传达我深深的祝福',
        '💖 甜蜜的节日，甜蜜的心情',
        '💝 愿您被爱包围，幸福常在',
    ],
    'easter': [
        '🐰 复活节快乐！愿新生带来希望',
        '🥚 寻找彩蛋，发现惊喜！',
        '🐣 春暖花开，万物复苏',
        '🌱 新生命的开始，愿您充满活力',
        '🌸 春天来了，愿您的心情如花绽放',
    ],
    'national': [
        '🇨🇳 国庆快乐！愿祖国繁荣昌盛',
        '🎉 庆祝华诞，共祝祖国好',
        '🎊 金秋十月，举国同庆',
        '🧧 祖国生日，愿山河无恙',
        '🎋 国泰民安，幸福美满',
    ],
    'space': [
        '🌌 星空璀璨，愿您的梦想如星辰闪耀',
        '🚀 探索宇宙，发现无限可能',
        '⭐ 每颗星星都是一个愿望',
        '🌙 月光如水，愿您的心情宁静美好',
        '💫 银河漫漫，愿您的人生精彩无限',
    ],
}

# 节日SVG装饰组件（精心设计的小米风格+节日元素）
FESTIVAL_DECORATIONS = {
    'christmas': {
        # 圣诞树顶部装饰
        'tree_top': '''<svg viewBox="0 0 40 50" fill="none">
            <polygon points="20,2 38,35 2,35" fill="#22c55e" stroke="#fff" stroke-width="1"/>
            <polygon points="20,12 32,30 8,30" fill="#22c55e" stroke="#fff" stroke-width="1"/>
            <rect x="16" y="35" width="8" height="12" fill="#c41e3a" stroke="#8B4513" stroke-width="1"/>
            <circle cx="20" cy="8" r="3" fill="#ffd700"/>
            <circle cx="14" cy="18" r="2" fill="#c41e3a"/>
            <circle cx="26" cy="18" r="2" fill="#c41e3a"/>
            <circle cx="20" cy="25" r="2" fill="#ffd700"/>
        </svg>''',
        # 圣诞袜
        'stocking': '''<svg viewBox="0 0 30 40" fill="none">
            <path d="M5 5 L5 25 Q5 35 15 35 L25 35 L25 5 Z" fill="#c41e3a" stroke="#fff" stroke-width="1"/>
            <rect x="3" y="3" width="24" height="8" rx="2" fill="#fff"/>
            <circle cx="12" cy="20" r="2" fill="#22c55e"/>
            <circle cx="18" cy="25" r="2" fill="#ffd700"/>
        </svg>''',
        # 礼物盒
        'gift': '''<svg viewBox="0 0 30 30" fill="none">
            <rect x="3" y="10" width="24" height="17" rx="2" fill="#c41e3a" stroke="#fff" stroke-width="1"/>
            <rect x="3" y="10" width="24" height="5" fill="#22c55e" stroke="#fff" stroke-width="1"/>
            <line x1="15" y1="10" x2="15" y2="27" stroke="#ffd700" stroke-width="3"/>
            <path d="M12 10 Q15 3 18 10" fill="none" stroke="#ffd700" stroke-width="2"/>
        </svg>''',
        # 雪花（小米风格简约）
        'snowflake': '''<svg viewBox="0 0 24 24" fill="none">
            <line x1="12" y1="2" x2="12" y2="22" stroke="#fff" stroke-width="1.5"/>
            <line x1="2" y1="12" x2="22" y2="12" stroke="#fff" stroke-width="1.5"/>
            <line x1="5" y1="5" x2="19" y2="19" stroke="#fff" stroke-width="1.5"/>
            <line x1="19" y1="5" x2="5" y2="19" stroke="#fff" stroke-width="1.5"/>
            <circle cx="12" cy="12" r="3" fill="#fff" fill-opacity="0.3"/>
        </svg>''',
        # 铃铛
        'bell': '''<svg viewBox="0 0 24 32" fill="none">
            <path d="M12 2 Q4 8 4 16 L4 20 L20 20 L20 16 Q20 8 12 2 Z" fill="#ffd700" stroke="#fff" stroke-width="1"/>
            <circle cx="12" cy="24" r="4" fill="#ffd700" stroke="#fff" stroke-width="1"/>
            <circle cx="12" cy="4" r="2" fill="#c41e3a"/>
        </svg>''',
    },
    'halloween': {
        # 南瓜灯
        'pumpkin': '''<svg viewBox="0 0 32 32" fill="none">
            <ellipse cx="16" cy="18" rx="14" ry="12" fill="#ff6b00" stroke="#000" stroke-width="1"/>
            <rect x="14" y="4" width="4" height="6" fill="#22c55e"/>
            <polygon points="18,4 24,1 18,6" fill="#22c55e"/>
            <polygon points="10,14 8,16 10,18" fill="#ffd700"/>
            <polygon points="22,14 24,16 22,18" fill="#ffd700"/>
            <path d="M10 22 Q16 26 22 22" fill="#ffd700" stroke="#000" stroke-width="1"/>
        </svg>''',
        # 幽灵
        'ghost': '''<svg viewBox="0 0 28 36" fill="none">
            <path d="M14 2 Q2 6 2 18 L2 32 L6 28 L10 32 L14 28 L18 32 L22 28 L26 32 L26 18 Q26 6 14 2 Z" fill="#fff" fill-opacity="0.9" stroke="#9333ea" stroke-width="1"/>
            <circle cx="10" cy="14" r="2" fill="#000"/>
            <circle cx="18" cy="14" r="2" fill="#000"/>
            <ellipse cx="14" cy="20" rx="3" ry="2" fill="#000"/>
        </svg>''',
        # 蝙蝠
        'bat': '''<svg viewBox="0 0 32 20" fill="none">
            <path d="M16 10 L10 4 L2 2 L8 10 L2 18 L10 12 L16 16 L22 12 L30 18 L24 10 L30 2 L22 4 L16 10 Z" fill="#000" stroke="#9333ea" stroke-width="0.5"/>
            <circle cx="12" cy="10" r="1" fill="#ff6b00"/>
            <circle cx="20" cy="10" r="1" fill="#ff6b00"/>
        </svg>''',
        # 糖果
        'candy': '''<svg viewBox="0 0 36 20" fill="none">
            <ellipse cx="18" cy="10" rx="12" ry="8" fill="#9333ea"/>
            <ellipse cx="18" cy="10" rx="8" ry="5" fill="#ff6b00"/>
            <rect x="2" y="6" width="6" height="8" rx="3" fill="#ffd700"/>
            <rect x="28" y="6" width="6" height="8" rx="3" fill="#ffd700"/>
        </svg>''',
        # 巫师帽
        'witch_hat': '''<svg viewBox="0 0 32 36" fill="none">
            <polygon points="16,2 28,28 4,28" fill="#1a0a1e" stroke="#9333ea" stroke-width="1"/>
            <ellipse cx="16" cy="28" rx="14" ry="6" fill="#9333ea"/>
            <circle cx="16" cy="14" r="3" fill="#ffd700"/>
        </svg>''',
    },
    'cny': {
        # 灯笼
        'lantern': '''<svg viewBox="0 0 32 48" fill="none">
            <rect x="12" y="2" width="8" height="4" fill="#ffd700"/>
            <line x1="16" y1="6" x2="16" y2="10" stroke="#ffd700" stroke-width="2"/>
            <ellipse cx="16" cy="24" rx="14" ry="16" fill="#dc2626" stroke="#ffd700" stroke-width="1"/>
            <rect x="6" y="20" width="20" height="3" fill="#ffd700"/>
            <rect x="6" y="28" width="20" height="3" fill="#ffd700"/>
            <path d="M10 38 L10 46 M16 38 L16 48 M22 38 L22 46" stroke="#ffd700" stroke-width="2"/>
        </svg>''',
        # 福字
        'fu': '''<svg viewBox="0 0 32 32" fill="none">
            <rect x="2" y="2" width="28" height="28" fill="#dc2626" stroke="#ffd700" stroke-width="2"/>
            <text x="16" y="22" font-size="20" font-weight="bold" fill="#ffd700" text-anchor="middle" font-family="KaiTi, STKaiti, serif">福</text>
        </svg>''',
        # 爆竹
        'firecracker': '''<svg viewBox="0 0 20 40" fill="none">
            <rect x="6" y="8" width="8" height="28" fill="#dc2626" stroke="#ffd700" stroke-width="1"/>
            <rect x="6" y="8" width="8" height="4" fill="#ffd700"/>
            <rect x="6" y="16" width="8" height="4" fill="#ffd700"/>
            <rect x="6" y="24" width="8" height="4" fill="#ffd700"/>
            <line x1="10" y1="2" x2="10" y2="8" stroke="#ffd700" stroke-width="1"/>
            <polygon points="8,2 10,0 12,2" fill="#ffd700"/>
        </svg>''',
        # 红包
        'red_packet': '''<svg viewBox="0 0 28 40" fill="none">
            <rect x="2" y="4" width="24" height="34" rx="3" fill="#dc2626" stroke="#ffd700" stroke-width="1"/>
            <ellipse cx="14" cy="16" rx="8" ry="6" fill="#ffd700"/>
            <text x="14" y="18" font-size="8" fill="#dc2626" text-anchor="middle" font-weight="bold">¥</text>
            <path d="M10 4 Q14 0 18 4" fill="#ffd700"/>
        </svg>''',
        # 中国结
        'chinese_knot': '''<svg viewBox="0 0 40 50" fill="none">
            <circle cx="20" cy="15" r="12" fill="none" stroke="#dc2626" stroke-width="3"/>
            <circle cx="20" cy="15" r="6" fill="none" stroke="#dc2626" stroke-width="2"/>
            <path d="M14 27 Q14 35 10 45 M26 27 Q26 35 30 45 M20 27 Q20 40 20 50" stroke="#dc2626" stroke-width="2" fill="none"/>
        </svg>''',
    },
    'newyear': {
        # 烟花
        'firework': '''<svg viewBox="0 0 40 40" fill="none">
            <circle cx="20" cy="20" r="3" fill="#ffd700"/>
            <line x1="20" y1="20" x2="20" y2="5" stroke="#0ea5e9" stroke-width="2"/>
            <line x1="20" y1="20" x2="20" y2="35" stroke="#0ea5e9" stroke-width="2"/>
            <line x1="20" y1="20" x2="5" y2="20" stroke="#ff6b00" stroke-width="2"/>
            <line x1="20" y1="20" x2="35" y2="20" stroke="#ff6b00" stroke-width="2"/>
            <line x1="20" y1="20" x2="8" y2="8" stroke="#22c55e" stroke-width="2"/>
            <line x1="20" y1="20" x2="32" y2="8" stroke="#22c55e" stroke-width="2"/>
            <line x1="20" y1="20" x2="8" y2="32" stroke="#ec4899" stroke-width="2"/>
            <line x1="20" y1="20" x2="32" y2="32" stroke="#ec4899" stroke-width="2"/>
            <circle cx="20" cy="5" r="2" fill="#ffd700"/>
            <circle cx="20" cy="35" r="2" fill="#ffd700"/>
            <circle cx="5" cy="20" r="2" fill="#ff6b00"/>
            <circle cx="35" cy="20" r="2" fill="#ff6b00"/>
        </svg>''',
        # 香槟
        'champagne': '''<svg viewBox="0 0 24 40" fill="none">
            <path d="M8 10 L6 38 L18 38 L16 10 Z" fill="#0ea5e9" stroke="#ffd700" stroke-width="1"/>
            <rect x="7" y="4" width="10" height="8" rx="2" fill="#0ea5e9" stroke="#ffd700" stroke-width="1"/>
            <ellipse cx="12" cy="10" rx="5" ry="2" fill="#ffd700" fill-opacity="0.5"/>
            <circle cx="8" cy="6" r="2" fill="#fff" fill-opacity="0.6"/>
            <circle cx="16" cy="8" r="1" fill="#fff" fill-opacity="0.6"/>
        </svg>''',
        # 倒数时钟
        'countdown': '''<svg viewBox="0 0 32 32" fill="none">
            <circle cx="16" cy="16" r="14" fill="#1e3a5f" stroke="#ffd700" stroke-width="2"/>
            <text x="16" y="20" font-size="12" fill="#ffd700" text-anchor="middle" font-weight="bold">00</text>
            <line x1="16" y1="16" x2="16" y2="8" stroke="#0ea5e9" stroke-width="2"/>
            <circle cx="16" cy="16" r="2" fill="#ffd700"/>
        </svg>''',
        # 星星
        'star': '''<svg viewBox="0 0 24 24" fill="none">
            <polygon points="12,2 15,9 22,9 17,14 19,21 12,17 5,21 7,14 2,9 9,9" fill="#ffd700" stroke="#0ea5e9" stroke-width="1"/>
        </svg>''',
        # 派对帽
        'party_hat': '''<svg viewBox="0 0 32 36" fill="none">
            <polygon points="16,2 28,32 4,32" fill="#0ea5e9" stroke="#ffd700" stroke-width="1"/>
            <circle cx="12" cy="14" r="2" fill="#ff6b00"/>
            <circle cx="18" cy="10" r="2" fill="#22c55e"/>
            <circle cx="14" cy="20" r="2" fill="#ec4899"/>
            <circle cx="20" cy="24" r="2" fill="#ffd700"/>
        </svg>''',
    },
    'valentine': {
        # 爱心
        'heart': '''<svg viewBox="0 0 32 28" fill="none">
            <path d="M16 26 Q2 16 2 8 Q2 2 8 2 Q12 2 16 8 Q20 2 24 2 Q30 2 30 8 Q30 16 16 26 Z" fill="#ec4899" stroke="#f472b6" stroke-width="1"/>
        </svg>''',
        # 玫瑰
        'rose': '''<svg viewBox="0 0 28 40" fill="none">
            <circle cx="14" cy="10" r="8" fill="#ec4899"/>
            <path d="M14 18 Q10 24 12 32 M14 18 Q18 24 16 32" fill="none" stroke="#22c55e" stroke-width="2"/>
            <ellipse cx="8" cy="26" rx="4" ry="2" fill="#22c55e"/>
            <ellipse cx="20" cy="26" rx="4" ry="2" fill="#22c55e"/>
        </svg>''',
        # 爱神之箭
        'arrow': '''<svg viewBox="0 0 40 20" fill="none">
            <path d="M2 10 L30 10" stroke="#ec4899" stroke-width="2"/>
            <polygon points="30,10 38,10 32,6 32,14" fill="#ec4899"/>
            <polygon points="2,10 8,6 8,14" fill="#f472b6"/>
        </svg>''',
        # 巧克力
        'chocolate': '''<svg viewBox="0 0 32 24" fill="none">
            <rect x="2" y="4" width="28" height="16" rx="3" fill="#8B4513"/>
            <rect x="4" y="6" width="8" height="6" fill="#D2691E"/>
            <rect x="12" y="6" width="8" height="6" fill="#D2691E"/>
            <rect x="20" y="6" width="8" height="6" fill="#D2691E"/>
            <rect x="8" y="14" width="16" height="4" fill="#D2691E"/>
        </svg>''',
        # 戒指
        'ring': '''<svg viewBox="0 0 28 32" fill="none">
            <circle cx="14" cy="22" r="10" fill="none" stroke="#ffd700" stroke-width="3"/>
            <polygon points="10,12 14,4 18,12 14,8" fill="#fff"/>
            <circle cx="14" cy="8" r="3" fill="#ffd700"/>
        </svg>''',
    },
    'easter': {
        # 彩蛋
        'easter_egg': '''<svg viewBox="0 0 28 36" fill="none">
            <ellipse cx="14" cy="20" rx="12" ry="14" fill="#22c55e"/>
            <ellipse cx="14" cy="20" rx="8" ry="10" fill="#fde047"/>
            <circle cx="10" cy="16" r="2" fill="#ec4899"/>
            <circle cx="18" cy="18" r="2" fill="#0ea5e9"/>
            <circle cx="14" cy="24" r="2" fill="#ff6b00"/>
        </svg>''',
        # 兔子
        'bunny': '''<svg viewBox="0 0 32 36" fill="none">
            <ellipse cx="16" cy="24" rx="10" ry="10" fill="#fff" stroke="#fde047" stroke-width="1"/>
            <ellipse cx="10" cy="8" rx="4" ry="10" fill="#fff" stroke="#fde047" stroke-width="1"/>
            <ellipse cx="22" cy="8" rx="4" ry="10" fill="#fff" stroke="#fde047" stroke-width="1"/>
            <ellipse cx="10" cy="12" rx="2" ry="6" fill="#ff69b4"/>
            <ellipse cx="22" cy="12" rx="2" ry="6" fill="#ff69b4"/>
            <circle cx="12" cy="22" r="2" fill="#000"/>
            <circle cx="20" cy="22" r="2" fill="#000"/>
            <ellipse cx="16" cy="26" rx="2" ry="1" fill="#ff69b4"/>
        </svg>''',
        # 小鸡
        'chick': '''<svg viewBox="0 0 28 32" fill="none">
            <ellipse cx="14" cy="18" rx="10" ry="12" fill="#fde047"/>
            <circle cx="10" cy="14" r="2" fill="#000"/>
            <circle cx="18" cy="14" r="2" fill="#000"/>
            <polygon points="14,18 10,22 18,22" fill="#ff6b00"/>
            <ellipse cx="14" cy="28" rx="6" ry="2" fill="#ff6b00"/>
        </svg>''',
        # 郁金香
        'tulip': '''<svg viewBox="0 0 24 40" fill="none">
            <ellipse cx="12" cy="12" rx="4" ry="10" fill="#ec4899"/>
            <ellipse cx="8" cy="14" rx="3" ry="8" fill="#f472b6"/>
            <ellipse cx="16" cy="14" rx="3" ry="8" fill="#f472b6"/>
            <line x1="12" y1="20" x2="12" y2="38" stroke="#22c55e" stroke-width="2"/>
            <ellipse cx="6" cy="30" rx="4" ry="2" fill="#22c55e"/>
        </svg>''',
        # 蝴蝶
        'butterfly': '''<svg viewBox="0 0 32 24" fill="none">
            <ellipse cx="8" cy="8" rx="6" ry="6" fill="#fde047"/>
            <ellipse cx="24" cy="8" rx="6" ry="6" fill="#fde047"/>
            <ellipse cx="10" cy="18" rx="4" ry="4" fill="#22c55e"/>
            <ellipse cx="22" cy="18" rx="4" ry="4" fill="#22c55e"/>
            <ellipse cx="16" cy="12" rx="2" ry="8" fill="#000"/>
            <line x1="16" y1="4" x2="14" y2="0" stroke="#000" stroke-width="1"/>
            <line x1="16" y1="4" x2="18" y2="0" stroke="#000" stroke-width="1"/>
        </svg>''',
    },
    'national': {
        # 旗子
        'flag': '''<svg viewBox="0 0 32 40" fill="none">
            <rect x="4" y="2" width="2" height="36" fill="#ffd700"/>
            <rect x="6" y="2" width="22" height="16" fill="#dc2626"/>
            <polygon points="10,6 10,14 18,10" fill="#ffd700"/>
            <text x="14" y="26" font-size="6" fill="#dc2626" text-anchor="middle">国庆</text>
        </svg>''',
        # 天安门
        'tiananmen': '''<svg viewBox="0 0 40 32" fill="none">
            <rect x="2" y="20" width="36" height="10" fill="#dc2626"/>
            <rect x="6" y="12" width="28" height="10" fill="#dc2626"/>
            <rect x="10" y="4" width="20" height="10" fill="#dc2626"/>
            <rect x="16" y="6" width="8" height="6" fill="#ffd700"/>
            <rect x="8" y="22" width="4" height="6" fill="#ffd700"/>
            <rect x="18" y="22" width="4" height="6" fill="#ffd700"/>
            <rect x="28" y="22" width="4" height="6" fill="#ffd700"/>
        </svg>''',
        # 烟花
        'national_firework': '''<svg viewBox="0 0 40 40" fill="none">
            <circle cx="20" cy="20" r="4" fill="#dc2626"/>
            <line x1="20" y1="20" x2="20" y2="4" stroke="#fcd34d" stroke-width="2"/>
            <line x1="20" y1="20" x2="36" y2="20" stroke="#fcd34d" stroke-width="2"/>
            <line x1="20" y1="20" x2="4" y2="20" stroke="#fcd34d" stroke-width="2"/>
            <line x1="20" y1="20" x2="32" y2="8" stroke="#dc2626" stroke-width="2"/>
            <line x1="20" y1="20" x2="8" y2="8" stroke="#dc2626" stroke-width="2"/>
            <line x1="20" y1="20" x2="32" y2="32" stroke="#dc2626" stroke-width="2"/>
            <line x1="20" y1="20" x2="8" y2="32" stroke="#dc2626" stroke-width="2"/>
        </svg>''',
        # 气球
        'balloon': '''<svg viewBox="0 0 28 40" fill="none">
            <ellipse cx="14" cy="14" rx="10" ry="12" fill="#dc2626"/>
            <polygon points="12,26 14,28 16,26 14,24" fill="#fcd34d"/>
            <line x1="14" y1="28" x2="14" y2="38" stroke="#fcd34d" stroke-width="1"/>
            <ellipse cx="8" cy="10" rx="3" ry="4" fill="#fff" fill-opacity="0.3"/>
        </svg>''',
        # 花篮
        'flower_basket': '''<svg viewBox="0 0 32 36" fill="none">
            <path d="M6 16 Q4 28 8 32 L24 32 Q28 28 26 16 Z" fill="#dc2626" stroke="#fcd34d" stroke-width="1"/>
            <rect x="4" y="14" width="24" height="4" rx="2" fill="#fcd34d"/>
            <circle cx="12" cy="8" r="5" fill="#ff6b00"/>
            <circle cx="20" cy="6" r="5" fill="#ffd700"/>
            <circle cx="16" cy="10" r="5" fill="#dc2626"/>
        </svg>''',
    },
    'space': {
        # 星星
        'space_star': '''<svg viewBox="0 0 24 24" fill="none">
            <polygon points="12,2 14,10 22,10 16,14 18,22 12,18 6,22 8,14 2,10 10,10" fill="#a78bfa" stroke="#e0e7ff" stroke-width="1"/>
        </svg>''',
        # 行星
        'planet': '''<svg viewBox="0 0 32 32" fill="none">
            <circle cx="16" cy="16" r="10" fill="#8b5cf6"/>
            <ellipse cx="16" cy="16" rx="14" ry="4" fill="none" stroke="#a78bfa" stroke-width="2" transform="rotate(-20 16 16)"/>
            <circle cx="12" cy="14" r="2" fill="#a78bfa" fill-opacity="0.5"/>
        </svg>''',
        # 火箭
        'rocket': '''<svg viewBox="0 0 20 40" fill="none">
            <path d="M10 2 Q4 8 4 20 L6 30 L14 30 L16 20 Q16 8 10 2 Z" fill="#e0e7ff"/>
            <polygon points="10,2 6,8 14,8" fill="#8b5cf6"/>
            <circle cx="10" cy="14" r="3" fill="#06b6d4"/>
            <polygon points="4,30 2,38 6,32" fill="#ff6b00"/>
            <polygon points="16,30 18,38 14,32" fill="#ff6b00"/>
            <polygon points="10,30 10,40 8,38 12,38" fill="#fcd34d"/>
        </svg>''',
        # UFO
        'ufo': '''<svg viewBox="0 0 40 24" fill="none">
            <ellipse cx="20" cy="16" rx="18" ry="6" fill="#8b5cf6"/>
            <ellipse cx="20" cy="10" rx="10" ry="8" fill="#a78bfa" fill-opacity="0.7"/>
            <ellipse cx="20" cy="10" rx="6" ry="5" fill="#e0e7ff" fill-opacity="0.5"/>
            <circle cx="8" cy="18" r="2" fill="#ffd700"/>
            <circle cx="20" cy="20" r="2" fill="#ffd700"/>
            <circle cx="32" cy="18" r="2" fill="#ffd700"/>
        </svg>''',
        # 银河
        'galaxy': '''<svg viewBox="0 0 40 40" fill="none">
            <ellipse cx="20" cy="20" rx="18" ry="8" fill="none" stroke="#a78bfa" stroke-width="1" transform="rotate(45 20 20)"/>
            <ellipse cx="20" cy="20" rx="14" ry="6" fill="none" stroke="#8b5cf6" stroke-width="1" transform="rotate(45 20 20)"/>
            <circle cx="20" cy="20" r="6" fill="#a78bfa"/>
            <circle cx="12" cy="12" r="1" fill="#e0e7ff"/>
            <circle cx="28" cy="28" r="1" fill="#e0e7ff"/>
            <circle cx="28" cy="12" r="1" fill="#e0e7ff"/>
            <circle cx="12" cy="28" r="1" fill="#e0e7ff"/>
        </svg>''',
    },
}


def get_festival_blessing(festival_id):
    """获取随机节日祝福语"""
    import random
    blessings = FESTIVAL_BLESSINGS.get(festival_id, [])
    if blessings:
        return random.choice(blessings)
    return ''


def get_festival_decoration(festival_id, decoration_name):
    """获取节日装饰SVG"""
    decorations = FESTIVAL_DECORATIONS.get(festival_id, {})
    return decorations.get(decoration_name, '')


def get_all_decorations_for_festival(festival_id):
    """获取某节日的所有装饰"""
    return FESTIVAL_DECORATIONS.get(festival_id, {})


# ============================================================
# ★ 节日主题系统（全局）
# ============================================================

FESTIVAL_THEMES = {
    'default': {
        'name': '默认',
        'accent': XIAOMI_ORANGE,
        'accent_light': XIAOMI_ORANGE_LIGHT,
        'accent_dark': XIAOMI_ORANGE_DARK,
        'secondary': MIMO_ORANGE,
        'bg_primary': BG_PRIMARY,
        'bg_secondary': BG_SECONDARY,
        'bg_surface': BG_SURFACE,
        'border_focus': BORDER_FOCUS,
        'glow': 'rgba(255,105,0,0.3)',
        'robot_eye': XIAOMI_ORANGE,
        'robot_body': '#2a2a35',
    },
    'christmas': {
        'name': '圣诞节',
        'accent': '#c41e3a',
        'accent_light': '#e53935',
        'accent_dark': '#a31528',
        'secondary': '#22c55e',
        'bg_primary': '#0a1628',
        'bg_secondary': '#111d36',
        'bg_surface': '#162340',
        'border_focus': '#c41e3a',
        'glow': 'rgba(196,30,58,0.35)',
        'robot_eye': '#22c55e',
        'robot_body': '#166534',
    },
    'halloween': {
        'name': '万圣节',
        'accent': '#ff6b00',
        'accent_light': '#ff9500',
        'accent_dark': '#cc5500',
        'secondary': '#9333ea',
        'bg_primary': '#1a0a1e',
        'bg_secondary': '#2d1b35',
        'bg_surface': '#3d2848',
        'border_focus': '#ff6b00',
        'glow': 'rgba(255,107,0,0.4)',
        'robot_eye': '#ff6b00',
        'robot_body': '#2d1b35',
    },
    'cny': {
        'name': '春节',
        'accent': '#dc2626',
        'accent_light': '#ef4444',
        'accent_dark': '#b91c1c',
        'secondary': '#ffd700',
        'bg_primary': '#1a0000',
        'bg_secondary': '#2d0a0a',
        'bg_surface': '#3d1515',
        'border_focus': '#dc2626',
        'glow': 'rgba(220,38,38,0.4)',
        'robot_eye': '#ffd700',
        'robot_body': '#991b1b',
    },
    'newyear': {
        'name': '新年',
        'accent': '#0ea5e9',
        'accent_light': '#38bdf8',
        'accent_dark': '#0284c7',
        'secondary': '#ffd700',
        'bg_primary': '#0c1929',
        'bg_secondary': '#1e3a5f',
        'bg_surface': '#2a4a72',
        'border_focus': '#0ea5e9',
        'glow': 'rgba(14,165,233,0.35)',
        'robot_eye': '#0ea5e9',
        'robot_body': '#1e3a5f',
    },
    'valentine': {
        'name': '情人节',
        'accent': '#ec4899',
        'accent_light': '#f472b6',
        'accent_dark': '#db2777',
        'secondary': '#ff69b4',
        'bg_primary': '#1a0a14',
        'bg_secondary': '#2d1b28',
        'bg_surface': '#3d2538',
        'border_focus': '#ec4899',
        'glow': 'rgba(236,72,153,0.35)',
        'robot_eye': '#ec4899',
        'robot_body': '#831843',
    },
    'easter': {
        'name': '复活节',
        'accent': '#22c55e',
        'accent_light': '#4ade80',
        'accent_dark': '#16a34a',
        'secondary': '#fde047',
        'bg_primary': '#052e16',
        'bg_secondary': '#14532d',
        'bg_surface': '#1a5c34',
        'border_focus': '#22c55e',
        'glow': 'rgba(34,197,94,0.35)',
        'robot_eye': '#22c55e',
        'robot_body': '#14532d',
    },
    'national': {
        'name': '国庆',
        'accent': '#dc2626',
        'accent_light': '#fcd34d',
        'accent_dark': '#b91c1c',
        'secondary': '#fcd34d',
        'bg_primary': '#1a0000',
        'bg_secondary': '#3d0000',
        'bg_surface': '#5a1515',
        'border_focus': '#dc2626',
        'glow': 'rgba(220,38,38,0.4)',
        'robot_eye': '#fcd34d',
        'robot_body': '#7f1d1d',
    },
    'space': {
        'name': '星空',
        'accent': '#8b5cf6',
        'accent_light': '#a78bfa',
        'accent_dark': '#7c3aed',
        'secondary': '#06b6d4',
        'bg_primary': '#0f0c29',
        'bg_secondary': '#302b63',
        'bg_surface': '#3d3780',
        'border_focus': '#8b5cf6',
        'glow': 'rgba(139,92,246,0.35)',
        'robot_eye': '#8b5cf6',
        'robot_body': '#1e1b4b',
    },
    # ★ v3.98: 专注时刻（Focus Moment）— 复古打字机 + 暖色聚光灯
    'focus_moment': {
        'name': '专注时刻',
        'accent': '#ff6900',
        'accent_light': '#ffaa55',
        'accent_dark': '#cc5400',
        'secondary': '#ffd700',
        'bg_primary': '#0a0a0a',
        'bg_secondary': '#1a1208',
        'bg_surface': '#2d1f10',
        'border_focus': '#ff6900',
        'glow': 'rgba(255,105,0,0.4)',
        'robot_eye': '#ff6900',
        'robot_body': '#1a1208',
        'wallpaper': 'data/lemon_wallpaper.png',
    },
}

# 当前主题（默认为default）
_current_festival_theme = 'default'


def get_festival_theme(theme_id=None):
    """获取节日主题配置"""
    global _current_festival_theme
    if theme_id:
        return FESTIVAL_THEMES.get(theme_id, FESTIVAL_THEMES['default'])
    return FESTIVAL_THEMES.get(_current_festival_theme, FESTIVAL_THEMES['default'])


def set_festival_theme(theme_id):
    """设置当前节日主题"""
    global _current_festival_theme
    if theme_id in FESTIVAL_THEMES:
        _current_festival_theme = theme_id
        return True
    return False


def get_current_accent():
    """获取当前主题的主色"""
    return get_festival_theme()['accent']


def get_current_accent_light():
    """获取当前主题的浅色"""
    return get_festival_theme()['accent_light']


def get_current_secondary():
    """获取当前主题的辅助色"""
    return get_festival_theme()['secondary']


def get_current_bg_surface():
    """获取当前主题的背景色"""
    return get_festival_theme()['bg_surface']


def festival_button_style(size='md'):
    """节日主题按钮样式"""
    theme = get_festival_theme()
    sizes = {
        'xs': ('22px', '10px', '4px'),
        'sm': ('28px', '11px', '5px'),
        'md': ('34px', '12px', '6px'),
        'lg': ('40px', '14px', '8px'),
    }
    h, fs, br = sizes.get(size, sizes['md'])
    return f"""
        QPushButton {{
            background: {theme['bg_surface']};
            color: {TEXT_SECONDARY};
            border: 1px solid {theme['border_focus']};
            border-radius: {br};
            font-size: {fs};
            padding: 0 14px;
            min-height: {h};
        }}
        QPushButton:hover {{
            background: {theme['accent']};
            color: #fff;
            border-color: {theme['accent_light']};
        }}
        QPushButton:pressed {{
            background: {theme['accent_dark']};
        }}
    """


def festival_primary_button_style(size='md'):
    """节日主题主按钮样式"""
    theme = get_festival_theme()
    sizes = {
        'sm': ('28px', '11px', '5px'),
        'md': ('34px', '12px', '6px'),
        'lg': ('40px', '14px', '8px'),
    }
    h, fs, br = sizes.get(size, sizes['md'])
    return f"""
        QPushButton {{
            background: {theme['accent']};
            color: #fff;
            border: none;
            border-radius: {br};
            font-size: {fs};
            font-weight: 600;
            padding: 0 16px;
            min-height: {h};
        }}
        QPushButton:hover {{
            background: {theme['accent_light']};
        }}
        QPushButton:pressed {{
            background: {theme['accent_dark']};
        }}
    """


def festival_global_stylesheet():
    """节日主题全局样式表"""
    theme = get_festival_theme()
    return f"""
        /* ===== 全局 ===== */
        QMainWindow, QWidget {{
            background: {theme['bg_primary']};
            color: {TEXT_PRIMARY};
            font-family: {FONT_SYSTEM};
            font-size: {FONT_SIZE_BASE};
        }}

        /* ===== 分割器 ===== */
        QSplitter::handle {{
            background: {BORDER_SUBTLE};
            width: 1px;
        }}
        QSplitter::handle:hover {{
            background: {theme['accent']};
        }}

        /* ===== 滚动条 ===== */
        QScrollBar:vertical {{
            background: {theme['bg_primary']};
            width: 6px;
            border: none;
            margin: 0;
        }}
        QScrollBar::handle:vertical {{
            background: {theme['accent']};
            border-radius: 3px;
            min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {theme['accent_light']};
        }}
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {{
            height: 0;
        }}
        QScrollBar:horizontal {{
            background: {theme['bg_primary']};
            height: 6px;
            border: none;
            margin: 0;
        }}
        QScrollBar::handle:horizontal {{
            background: {theme['accent']};
            border-radius: 3px;
            min-width: 30px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {theme['accent_light']};
        }}
        QScrollBar::add-line:horizontal,
        QScrollBar::sub-line:horizontal {{
            width: 0;
        }}

        /* ===== 标签页 ===== */
        QTabWidget::pane {{
            border: none;
            background: {theme['bg_primary']};
        }}
        QTabBar {{
            background: {theme['bg_secondary']};
            border-bottom: 1px solid {BORDER_SUBTLE};
        }}
        QTabBar::tab {{
            background: {theme['bg_secondary']};
            color: {TEXT_TERTIARY};
            padding: 8px 16px;
            border: none;
            border-right: 1px solid {BORDER_SUBTLE};
            font-size: {FONT_SIZE_SM};
        }}
        QTabBar::tab:selected {{
            background: {theme['bg_primary']};
            color: {TEXT_PRIMARY};
            border-bottom: 2px solid {theme['accent']};
        }}
        QTabBar::tab:hover:!selected {{
            background: {theme['bg_surface']};
            color: {TEXT_SECONDARY};
        }}

        /* ===== 工具提示 ===== */
        QToolTip {{
            background: {theme['bg_surface']};
            color: {TEXT_PRIMARY};
            border: 1px solid {theme['accent']};
            border-radius: {RADIUS_SM};
            padding: 6px 10px;
            font-size: {FONT_SIZE_XS};
        }}

        /* ===== 状态栏 ===== */
        QStatusBar {{
            background: {theme['bg_secondary']};
            color: {TEXT_TERTIARY};
            font-size: {FONT_SIZE_XS};
            border-top: 1px solid {theme['accent']};
            padding: 2px 8px;
        }}

        /* ===== 菜单 ===== */
        QMenu {{
            background: {theme['bg_surface']};
            color: {TEXT_PRIMARY};
            border: 1px solid {theme['accent']};
            border-radius: {RADIUS_MD};
            padding: 4px;
        }}
        QMenu::item {{
            padding: 6px 24px;
            border-radius: {RADIUS_SM};
        }}
        QMenu::item:selected {{
            background: {theme['accent']};
            color: #fff;
        }}
    """


# ============================================================
# 全局 QSS 样式表
# ============================================================
def global_stylesheet():
    return f"""
        /* ===== 全局 ===== */
        QMainWindow, QWidget {{
            background: {BG_PRIMARY};
            color: {TEXT_PRIMARY};
            font-family: {FONT_SYSTEM};
            font-size: {FONT_SIZE_BASE};
        }}

        /* ===== 分割器 ===== */
        QSplitter::handle {{
            background: {BORDER_SUBTLE};
            width: 1px;
        }}
        QSplitter::handle:hover {{
            background: {BORDER_FOCUS};
        }}

        /* ===== 滚动条 ===== */
        QScrollBar:vertical {{
            background: {BG_ROOT};
            width: 6px;
            border: none;
            margin: 0;
        }}
        QScrollBar::handle:vertical {{
            background: {BORDER_DEFAULT};
            border-radius: 3px;
            min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {BORDER_STRONG};
        }}
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {{
            height: 0;
        }}
        QScrollBar:horizontal {{
            background: {BG_ROOT};
            height: 6px;
            border: none;
            margin: 0;
        }}
        QScrollBar::handle:horizontal {{
            background: {BORDER_DEFAULT};
            border-radius: 3px;
            min-width: 30px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {BORDER_STRONG};
        }}
        QScrollBar::add-line:horizontal,
        QScrollBar::sub-line:horizontal {{
            width: 0;
        }}

        /* ===== 标签页 ===== */
        QTabWidget::pane {{
            border: none;
            background: {BG_PRIMARY};
        }}
        QTabBar {{
            background: {BG_SECONDARY};
            border-bottom: 1px solid {BORDER_SUBTLE};
        }}
        QTabBar::tab {{
            background: {BG_SECONDARY};
            color: {TEXT_TERTIARY};
            padding: 8px 16px;
            border: none;
            border-right: 1px solid {BORDER_SUBTLE};
            font-size: {FONT_SIZE_SM};
        }}
        QTabBar::tab:selected {{
            background: {BG_PRIMARY};
            color: {TEXT_PRIMARY};
            border-bottom: 2px solid {XIAOMI_ORANGE};
        }}
        QTabBar::tab:hover:!selected {{
            background: {BG_SURFACE};
            color: {TEXT_SECONDARY};
        }}
        QTabBar::close-button {{
            image: none;
            background: transparent;
            padding: 0;
            margin: 0 0 0 6px;
        }}

        /* ===== 工具提示 ===== */
        QToolTip {{
            background: {BG_SURFACE_ACTIVE};
            color: {TEXT_PRIMARY};
            border: 1px solid {BORDER_DEFAULT};
            border-radius: {RADIUS_SM};
            padding: 6px 10px;
            font-size: {FONT_SIZE_XS};
        }}

        /* ===== 状态栏 ===== */
        QStatusBar {{
            background: {BG_SECONDARY};
            color: {TEXT_TERTIARY};
            font-size: {FONT_SIZE_XS};
            border-top: 1px solid {BORDER_SUBTLE};
            padding: 2px 8px;
        }}

        /* ===== 菜单 ===== */
        QMenu {{
            background: {BG_SURFACE};
            color: {TEXT_PRIMARY};
            border: 1px solid {BORDER_DEFAULT};
            border-radius: {RADIUS_MD};
            padding: 4px;
        }}
        QMenu::item {{
            padding: 6px 24px;
            border-radius: {RADIUS_SM};
        }}
        QMenu::item:selected {{
            background: {BG_SURFACE_HOVER};
        }}

        /* ===== 表单控件 ===== */
        QLabel {{
            color: {TEXT_PRIMARY};
        }}
        QPushButton {{
            color: {TEXT_SECONDARY};
        }}
        QPushButton:hover {{
            color: {TEXT_PRIMARY};
        }}
        QLineEdit {{
            color: {TEXT_PRIMARY};
            background: {BG_SURFACE};
            border: 1px solid {BORDER_DEFAULT};
            border-radius: {RADIUS_SM};
            padding: 4px 8px;
        }}
        QLineEdit:focus {{
            border-color: {BORDER_FOCUS};
        }}
    """


def button_style(accent_color=XIAOMI_ORANGE, size='md'):
    """生成按钮样式"""
    sizes = {
        'xs': ('22px', '10px', '4px'),
        'sm': ('28px', '11px', '5px'),
        'md': ('34px', '12px', '6px'),
        'lg': ('40px', '14px', '8px'),
    }
    h, fs, br = sizes.get(size, sizes['md'])
    return f"""
        QPushButton {{
            background: {BG_SURFACE};
            color: {TEXT_SECONDARY};
            border: 1px solid {BORDER_DEFAULT};
            border-radius: {br};
            font-size: {fs};
            padding: 0 14px;
            min-height: {h};
        }}
        QPushButton:hover {{
            background: {BG_SURFACE_HOVER};
            color: {TEXT_PRIMARY};
            border-color: {BORDER_STRONG};
        }}
        QPushButton:pressed {{
            background: {BG_SURFACE_ACTIVE};
        }}
        QPushButton:disabled {{
            background: {BG_ROOT};
            color: {TEXT_DISABLED};
            border-color: {BORDER_SUBTLE};
        }}
    """


def button_primary_style(size='md'):
    """小米橙色主按钮"""
    sizes = {
        'sm': ('28px', '11px', '5px'),
        'md': ('34px', '12px', '6px'),
        'lg': ('40px', '14px', '8px'),
    }
    h, fs, br = sizes.get(size, sizes['md'])
    return f"""
        QPushButton {{
            background: {XIAOMI_ORANGE};
            color: #000;
            border: none;
            border-radius: {br};
            font-size: {fs};
            font-weight: 600;
            padding: 0 16px;
            min-height: {h};
        }}
        QPushButton:hover {{
            background: {XIAOMI_ORANGE_LIGHT};
        }}
        QPushButton:pressed {{
            background: {XIAOMI_ORANGE_DARK};
        }}
        QPushButton:disabled {{
            background: {BORDER_STRONG};
            color: {TEXT_DISABLED};
        }}
    """


def input_style(focus_color=XIAOMI_ORANGE):
    return f"""
        QLineEdit, QTextEdit {{
            background: {BG_ROOT};
            color: {TEXT_PRIMARY};
            border: 1px solid {BORDER_DEFAULT};
            border-radius: {RADIUS_MD};
            padding: 8px 12px;
            font-size: {FONT_SIZE_BASE};
            selection-background-color: {focus_color};
            selection-color: #000;
        }}
        QLineEdit:focus, QTextEdit:focus {{
            border-color: {focus_color};
        }}
        QLineEdit::placeholder {{
            color: {TEXT_PLACEHOLDER};
        }}
    """


# ============================================================
# SVG icon rendering functions
# ============================================================

import re as _re


def svg_to_pixmap(name, size=16, color=None):
    """SVG icon name -> QPixmap (lazy PyQt5 import, returns None on failure)."""
    try:
        from PyQt5.QtSvg import QSvgRenderer
        from PyQt5.QtCore import Qt as _Qt, QByteArray, QRectF
        from PyQt5.QtGui import QPixmap, QPainter

        svg = SVG_ICONS.get(name, SVG_ICONS['file_default'])
        svg = _re.sub(r'width="\d+"', f'width="{size}"', svg)
        svg = _re.sub(r'height="\d+"', f'height="{size}"', svg)
        if color:
            svg = svg.replace('stroke="currentColor"', f'stroke="{color}"')
            svg = svg.replace('fill="currentColor"', f'fill="{color}"')

        renderer = QSvgRenderer(QByteArray(svg.encode('utf-8')))
        pixmap = QPixmap(size, size)
        pixmap.fill(_Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        return pixmap
    except Exception:
        return None


def svg_to_qicon(name, size=16, color=None):
    """SVG icon name -> QIcon (lazy PyQt5 import, returns empty QIcon on failure)."""
    try:
        from PyQt5.QtGui import QIcon
        pixmap = svg_to_pixmap(name, size=size, color=color)
        return QIcon(pixmap) if pixmap is not None else QIcon()
    except Exception:
        from PyQt5.QtGui import QIcon
        return QIcon()


def svg_to_png_data_uri(name, size=16, color=None):
    """SVG icon name -> base64 PNG data URI for QLabel rich text."""
    import base64
    pixmap = svg_to_pixmap(name, size=size, color=color)
    if pixmap is None:
        return ""
    try:
        from PyQt5.QtCore import QBuffer, QByteArray, QIODevice
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        pixmap.save(buf, "PNG")
        buf.close()
        return "data:image/png;base64," + base64.b64encode(bytes(ba)).decode("ascii")
    except Exception:
        return ""


def icon_text_html(icon_name, text, color=None, size=14):
    """Generate SVG icon + text HTML fragment for QLabel rich text."""
    import html as _html
    safe_text = _html.escape(text)
    uri = svg_to_png_data_uri(icon_name, size=size, color=color)
    if uri:
        return (f'<img src="{uri}" width="{size}" height="{size}" '
                f'style="vertical-align:middle; margin-right:4px;">{safe_text}')
    return safe_text


def get_theme_colors():
    """Return current theme color dict for external modules."""
    return {
        'BG_ROOT': BG_ROOT,
        'BG_SURFACE': BG_SURFACE,
        'BG_ELEVATED': BG_ELEVATED,
        'TEXT_PRIMARY': TEXT_PRIMARY,
        'TEXT_SECONDARY': TEXT_SECONDARY,
        'TEXT_TERTIARY': TEXT_TERTIARY,
        'TEXT_PLACEHOLDER': TEXT_PLACEHOLDER,
        'BORDER_DEFAULT': BORDER_DEFAULT,
        'BORDER_HOVER': BORDER_HOVER,
        'LEMON_ORANGE': LEMON_ORANGE,
        'XIAOMI_ORANGE': XIAOMI_ORANGE,
        'SUCCESS': SUCCESS,
        'ERROR': ERROR,
        'WARNING': WARNING,
    }