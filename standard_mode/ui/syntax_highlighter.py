# -*- coding: utf-8 -*-
"""
多语言语法高亮器 — MIMO Code 配色
支持 Python / JavaScript / TypeScript / HTML / CSS / JSON
"""
import os
import re
from PyQt5.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont
from ui.design.tokens import Lemon

# ★ 修复：此前有 5 个值写成字符串字面量 'Lemon.ACCENT_ORANGE'（带引号），
#   传给 QColor() 时无法解析 → 装饰器/内置函数/正则/模板字符串全部回退默认色，
#   语法高亮实际只剩 3~4 组配色。现统一改为真实 token 引用。
C = {
    'keyword': Lemon.SYNTAX_KEYWORD,    # 关键字 橙
    'string': Lemon.SYNTAX_STRING,      # 字符串 绿
    'comment': Lemon.SYNTAX_COMMENT,    # 注释 灰
    'number': Lemon.SYNTAX_NUMBER,      # 数字 橙黄（原错用 SYNTAX_FUNCTION 蓝）
    'function': Lemon.SYNTAX_FUNCTION,  # 函数名 蓝（原用 SYNTAX_VARIABLE 白，暗底不可读）
    'decorator': Lemon.ACCENT_PURPLE,   # 装饰器 紫
    'builtin': Lemon.SYNTAX_BUILTIN,    # 内置函数 青
    'self': Lemon.SYNTAX_CONSTANT,      # self/this 红（原与 keyword 撞色）
    'operator': Lemon.SYNTAX_OPERATOR,  # 操作符 灰白（原与 keyword 撞色）
    'class': Lemon.SYNTAX_TYPE,         # 类名 黄（原与 keyword 撞色）
    'text': Lemon.DARK_TEXT_1,          # 普通文字
    'tag': Lemon.SYNTAX_TAG,            # HTML标签 红（原与 keyword 撞色）
    'attr': Lemon.SYNTAX_ATTR,          # HTML属性 橙黄（原与 function 撞色）
    'css_prop': Lemon.SYNTAX_FUNCTION,  # CSS属性 蓝
    'css_val': Lemon.SYNTAX_STRING,     # CSS值 绿
    'css_sel': Lemon.SYNTAX_TYPE,       # CSS选择器 黄
    'json_key': Lemon.SYNTAX_FUNCTION,  # JSON键 蓝
    'json_val': Lemon.SYNTAX_STRING,    # JSON值 绿
    'regex': Lemon.ACCENT_ORANGE,       # 正则表达式 橙
    'template': Lemon.SYNTAX_STRING,    # 模板字符串 绿
    'todo': Lemon.SYNTAX_TODO,          # TODO/FIXME 注释 警告橙
}


class _BaseHighlighter(QSyntaxHighlighter):
    """高亮器基类：统一的多规则匹配逻辑"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rules = []

    def _add_rule(self, pattern, fmt):
        self._rules.append((re.compile(pattern), fmt))

    def _add_todo_rule(self, comment_prefix: str):
        """TODO / FIXME / XXX / HACK / WARNING / NOTE 注释高亮（PyCharm、Trae 标配）。

        ★ 必须在普通注释规则【之后】调用：highlightBlock 按 rules 顺序依次
          setFormat，后注册的格式会覆盖先注册的，放在注释之后才能把
          TODO 行从灰色注释里"提"出来。
        """
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['todo']))
        fmt.setFontWeight(QFont.Bold)
        self._add_rule(
            comment_prefix + r'\s*(TODO|FIXME|XXX|HACK|WARNING|NOTE)\b[^\n]*', fmt)

    def highlightBlock(self, text):
        for pattern, fmt in self._rules:
            for match in pattern.finditer(text):
                start = match.start()
                length = match.end() - start
                if pattern.groups > 0:
                    for i in range(1, pattern.groups + 1):
                        if match.group(i):
                            start = match.start(i)
                            length = match.end(i) - start
                            break
                self.setFormat(start, length, fmt)


class PythonHighlighter(_BaseHighlighter):
    """Python 语法高亮"""

    KEYWORDS = [
        'and', 'as', 'assert', 'async', 'await', 'break', 'class', 'continue',
        'def', 'del', 'elif', 'else', 'except', 'finally', 'for', 'from',
        'global', 'if', 'import', 'in', 'is', 'lambda', 'nonlocal', 'not',
        'or', 'pass', 'raise', 'return', 'try', 'while', 'with', 'yield',
        'True', 'False', 'None',
    ]

    BUILTINS = [
        'print', 'len', 'range', 'int', 'str', 'float', 'list', 'dict',
        'set', 'tuple', 'bool', 'type', 'isinstance', 'enumerate', 'zip',
        'map', 'filter', 'sorted', 'reversed', 'open', 'input', 'super',
        'any', 'all', 'max', 'min', 'sum', 'abs', 'round', 'hasattr',
        'getattr', 'setattr', 'dir', 'vars', 'id', 'hex', 'oct', 'bin',
        'chr', 'ord', 'repr', 'eval', 'exec', 'compile',
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_rules()

    def _build_rules(self):
        # 关键字
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['keyword']))
        fmt.setFontWeight(QFont.Bold)
        self._add_rule(r'\b(' + '|'.join(self.KEYWORDS) + r')\b', fmt)

        # 内置函数
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['builtin']))
        self._add_rule(r'\b(' + '|'.join(self.BUILTINS) + r')\b', fmt)

        # 装饰器
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['decorator']))
        self._add_rule(r'@\w+', fmt)

        # 类名 (class Foo:)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['class']))
        fmt.setFontWeight(QFont.Bold)
        self._add_rule(r'\bclass\s+(\w+)', fmt)

        # 函数定义 (def foo:)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['function']))
        self._add_rule(r'\bdef\s+(\w+)', fmt)

        # 函数调用 foo(...)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['function']))
        self._add_rule(r'\b(\w+)(?=\s*\()', fmt)

        # self
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['self']))
        fmt.setFontItalic(True)
        self._add_rule(r'\bself\b', fmt)

        # 数字
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['number']))
        self._add_rule(r'\b[0-9]+\.?[0-9]*\b', fmt)

        # 字符串 (双引号)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['string']))
        self._add_rule(r'"[^"\\]*(\\.[^"\\]*)*"', fmt)

        # 字符串 (单引号)
        self._add_rule(r"'[^'\\]*(\\.[^'\\]*)*'", fmt)

        # 三引号字符串
        self._add_rule(r'"""[^"]*"""', fmt)
        self._add_rule(r"'''[^']*'''", fmt)

        # f-string
        self._add_rule(r'f"[^"\\]*(\\.[^"\\]*)*"', fmt)
        self._add_rule(r"f'[^'\\]*(\\.[^'\\]*)*'", fmt)

        # 注释
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['comment']))
        fmt.setFontItalic(True)
        self._add_rule(r'#[^\n]*', fmt)

        # TODO/FIXME（须在注释规则之后注册才能覆盖注释色）
        self._add_todo_rule(r'#')


class JavaScriptHighlighter(_BaseHighlighter):
    """JavaScript / TypeScript 语法高亮"""

    KEYWORDS = [
        'break', 'case', 'catch', 'class', 'const', 'continue', 'debugger',
        'default', 'delete', 'do', 'else', 'export', 'extends', 'finally',
        'for', 'function', 'if', 'import', 'in', 'instanceof', 'let', 'new',
        'of', 'return', 'super', 'switch', 'this', 'throw', 'try', 'typeof',
        'var', 'void', 'while', 'with', 'yield', 'async', 'await',
        'true', 'false', 'null', 'undefined',
        # TypeScript 额外关键字
        'type', 'interface', 'enum', 'implements', 'abstract', 'declare',
        'namespace', 'module', 'readonly', 'keyof', 'as', 'is', 'infer',
        'never', 'unknown', 'any', 'string', 'number', 'boolean', 'symbol',
    ]

    BUILTINS = [
        'console', 'Math', 'JSON', 'Promise', 'Array', 'Object', 'String',
        'Number', 'Boolean', 'Date', 'RegExp', 'Error', 'Map', 'Set',
        'WeakMap', 'WeakSet', 'Symbol', 'parseInt', 'parseFloat',
        'setTimeout', 'setInterval', 'clearTimeout', 'clearInterval',
        'fetch', 'document', 'window', 'navigator', 'require',
        'Buffer', 'process', 'module', 'exports',
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_rules()

    def _build_rules(self):
        # 关键字
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['keyword']))
        fmt.setFontWeight(QFont.Bold)
        self._add_rule(r'\b(' + '|'.join(self.KEYWORDS) + r')\b', fmt)

        # 内置对象
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['builtin']))
        self._add_rule(r'\b(' + '|'.join(self.BUILTINS) + r')\b', fmt)

        # 函数定义 function foo / const foo = (...) =>
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['function']))
        self._add_rule(r'\b(?:function|async)\s+(\w+)', fmt)
        self._add_rule(r'\b(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(', fmt)

        # 箭头函数参数
        self._add_rule(r'\b(\w+)\s*=>', fmt)

        # 函数调用 foo(...)
        self._add_rule(r'\b(\w+)(?=\s*\()', fmt)

        # 类名 class Foo
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['class']))
        fmt.setFontWeight(QFont.Bold)
        self._add_rule(r'\bclass\s+(\w+)', fmt)

        # this
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['self']))
        fmt.setFontItalic(True)
        self._add_rule(r'\bthis\b', fmt)

        # 数字
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['number']))
        self._add_rule(r'\b[0-9]+\.?[0-9]*(?:[eE][+-]?[0-9]+)?\b', fmt)
        self._add_rule(r'\b0[xX][0-9a-fA-F]+\b', fmt)
        self._add_rule(r'\b0[bB][01]+\b', fmt)

        # 模板字符串
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['template']))
        self._add_rule(r'`[^`]*`', fmt)

        # 字符串 (双引号)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['string']))
        self._add_rule(r'"[^"\\]*(\\.[^"\\]*)*"', fmt)

        # 字符串 (单引号)
        self._add_rule(r"'[^'\\]*(\\.[^'\\]*)*'", fmt)

        # 正则表达式
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['regex']))
        self._add_rule(r'/[^/\\]*(\\.[^/\\]*)*/[gimsuy]*', fmt)

        # 行注释
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['comment']))
        fmt.setFontItalic(True)
        self._add_rule(r'//[^\n]*', fmt)

        # 块注释
        self._add_rule(r'/\*[\s\S]*?\*/', fmt)

        # TODO/FIXME（须在注释规则之后注册才能覆盖注释色）
        self._add_todo_rule(r'//')


class HTMLHighlighter(_BaseHighlighter):
    """HTML 语法高亮"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_rules()

    def _build_rules(self):
        # 标签名 <tagname
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['tag']))
        fmt.setFontWeight(QFont.Bold)
        self._add_rule(r'(</?)(\w+)', fmt)

        # 属性名
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['attr']))
        self._add_rule(r'\s(\w[\w-]*)(?=\s*=)', fmt)

        # 属性值
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['string']))
        self._add_rule(r'"[^"\\]*(\\.[^"\\]*)*"', fmt)
        self._add_rule(r"'[^'\\]*(\\.[^'\\]*)*'", fmt)

        # 注释
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['comment']))
        fmt.setFontItalic(True)
        self._add_rule(r'<!--[\s\S]*?-->', fmt)

        # TODO/FIXME（须在注释规则之后注册才能覆盖注释色）
        self._add_todo_rule(r'<!--')

        # DOCTYPE
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['decorator']))
        fmt.setFontWeight(QFont.Bold)
        self._add_rule(r'<!DOCTYPE[^>]*>', fmt)


class CSSHighlighter(_BaseHighlighter):
    """CSS / SCSS 语法高亮"""

    PROPERTIES = [
        'color', 'background', 'background-color', 'font', 'font-size',
        'font-weight', 'font-family', 'text-align', 'text-decoration',
        'margin', 'padding', 'border', 'border-radius', 'width', 'height',
        'display', 'position', 'top', 'left', 'right', 'bottom', 'z-index',
        'overflow', 'opacity', 'transform', 'transition', 'animation',
        'box-shadow', 'text-shadow', 'filter', 'flex', 'flex-direction',
        'justify-content', 'align-items', 'grid', 'gap', 'cursor',
        'pointer-events', 'user-select', 'outline', 'visibility',
        'white-space', 'line-height', 'letter-spacing', 'word-spacing',
        'content', 'backdrop-filter', 'clip-path', 'object-fit',
        'max-width', 'min-width', 'max-height', 'min-height',
        'box-sizing', 'resize', 'vertical-align', 'float', 'clear',
        'list-style', 'text-overflow', 'word-break', 'word-wrap',
        'background-image', 'background-size', 'background-position',
        'background-repeat', 'border-collapse', 'table-layout',
        'scroll-behavior', 'will-change', 'perspective',
    ]

    VALUES = [
        'none', 'auto', 'inherit', 'initial', 'unset', 'block', 'inline',
        'inline-block', 'flex', 'grid', 'hidden', 'visible', 'scroll',
        'absolute', 'relative', 'fixed', 'sticky', 'static',
        'center', 'left', 'right', 'top', 'bottom', 'middle',
        'bold', 'normal', 'italic', 'underline', 'uppercase', 'lowercase',
        'transparent', 'cover', 'contain', 'repeat', 'no-repeat',
        'pointer', 'not-allowed', 'text', 'move', 'grab', 'grabbing',
        'nowrap', 'pre', 'pre-wrap', 'pre-line', 'break-word',
        'solid', 'dashed', 'dotted', 'double', 'groove', 'ridge',
        'ease', 'linear', 'ease-in', 'ease-out', 'ease-in-out',
        'infinite', 'alternate', 'forwards', 'backwards', 'both',
        'row', 'column', 'row-reverse', 'column-reverse',
        'space-between', 'space-around', 'space-evenly', 'stretch',
        'flex-start', 'flex-end', 'baseline', 'wrap', 'nowrap',
        'inset', 'outset', 'border-box', 'content-box',
        'true', 'false',
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_rules()

    def _build_rules(self):
        # 选择器 (.class #id element)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['css_sel']))
        self._add_rule(r'[.#][\w-]+', fmt)

        # 伪类/伪元素
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['decorator']))
        self._add_rule(r'::?[\w-]+', fmt)

        # CSS 属性
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['css_prop']))
        self._add_rule(r'\b(' + '|'.join(self.PROPERTIES) + r')\b', fmt)

        # CSS 值关键字
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['css_val']))
        self._add_rule(r'\b(' + '|'.join(self.VALUES) + r')\b', fmt)

        # 数字和单位
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['number']))
        self._add_rule(r'\b[0-9]+\.?[0-9]*(?:px|em|rem|%|vh|vw|vmin|vmax|s|ms|deg|rad|ch|ex|cm|mm|pt|pc|dpi|dppx)?\b', fmt)

        # 颜色值
        self._add_rule(r'#[0-9a-fA-F]{3,8}\b', fmt)

        # 字符串
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['string']))
        self._add_rule(r'"[^"\\]*(\\.[^"\\]*)*"', fmt)
        self._add_rule(r"'[^'\\]*(\\.[^'\\]*)*'", fmt)

        # 注释
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['comment']))
        fmt.setFontItalic(True)
        self._add_rule(r'/\*[\s\S]*?\*/', fmt)

        # TODO/FIXME（须在注释规则之后注册才能覆盖注释色）
        self._add_todo_rule(r'/\*')

        # @规则
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['decorator']))
        fmt.setFontWeight(QFont.Bold)
        self._add_rule(r'@[\w-]+', fmt)


class JSONHighlighter(_BaseHighlighter):
    """JSON 语法高亮"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_rules()

    def _build_rules(self):
        # 键名
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['json_key']))
        self._add_rule(r'"[^"\\]*(\\.[^"\\]*)*"\s*:', fmt)

        # 字符串值
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['json_val']))
        self._add_rule(r'"[^"\\]*(\\.[^"\\]*)*"', fmt)

        # 数字
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['number']))
        self._add_rule(r'\b-?[0-9]+\.?[0-9]*(?:[eE][+-]?[0-9]+)?\b', fmt)

        # 布尔值和null
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C['keyword']))
        fmt.setFontWeight(QFont.Bold)
        self._add_rule(r'\b(?:true|false|null)\b', fmt)


# ============================================================
# 表驱动高亮器 —— 用配置描述一门语言，避免为每门语言复制一套样板代码
# ============================================================
class _TableHighlighter(_BaseHighlighter):
    """表驱动高亮器基类。

    ★ 注册顺序即优先级（后者覆盖前者）：
        额外规则 → 数字 → 字符串 → 内置名 → 关键字 → 注释 → TODO
      - 注释必须排在字符串之后，否则字符串里的 `//` 会被残留的字符串色盖掉；
      - TODO 必须排在注释之后，才能把 TODO 行从灰色注释里"提"出来。

    ★ 已知局限：块注释按单行匹配，跨行块注释只染首尾行。
      与既有 Python/JS/HTML/CSS/JSON 高亮器行为一致（未做跨行状态机）。
    """

    KEYWORDS = ()
    BUILTINS = ()
    LINE_COMMENT = None          # 行注释前缀（正则，需自行转义）
    BLOCK_COMMENT = None         # (起始正则, 结束正则)
    EXTRA_RULES = ()             # ((pattern, color_key[, bold]), ...)
    KEYWORDS_PATTERN = None      # 需要 (?i) 等内联标志时，直接给完整正则

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_rules()

    def _fmt(self, key, bold=False):
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C[key]))
        if bold:
            fmt.setFontWeight(QFont.Bold)
        return fmt

    def _add(self, pattern, key, bold=False):
        self._add_rule(pattern, self._fmt(key, bold))

    def _build_rules(self):
        for rule in self.EXTRA_RULES:
            pattern, key = rule[0], rule[1]
            bold = rule[2] if len(rule) > 2 else False
            self._add(pattern, key, bold)

        # 数字（含 0x/0b/0o 进制字面量与下划线分隔）
        self._add(r'\b0[xXbBoO][0-9a-fA-F_]+\b', 'number')
        self._add(r'\b[0-9][0-9_]*(?:\.[0-9_]+)?(?:[eE][+-]?[0-9]+)?\b', 'number')

        # 字符串
        self._add(r'"[^"\\\n]*(\\.[^"\\\n]*)*"', 'string')
        self._add(r"'[^'\\\n]*(\\.[^'\\\n]*)*'", 'string')

        # 内置名 / 关键字
        if self.BUILTINS:
            self._add(r'\b(' + '|'.join(re.escape(k) for k in self.BUILTINS) + r')\b', 'builtin')
        if self.KEYWORDS_PATTERN:
            self._add(self.KEYWORDS_PATTERN, 'keyword', True)
        elif self.KEYWORDS:
            self._add(r'\b(' + '|'.join(re.escape(k) for k in self.KEYWORDS) + r')\b',
                      'keyword', True)

        # 注释（须在字符串之后）
        if self.LINE_COMMENT:
            self._add(self.LINE_COMMENT + r'[^\n]*', 'comment')
        if self.BLOCK_COMMENT:
            start, end = self.BLOCK_COMMENT
            self._add(start + r'[\s\S]*?' + end, 'comment')

        # TODO/FIXME（须在注释之后）
        if self.LINE_COMMENT:
            self._add_todo_rule(self.LINE_COMMENT)


class NullHighlighter(_TableHighlighter):
    """无高亮回落 —— 未知文件类型一律零染色。

    此前未知扩展名会落到 PythonHighlighter，导致 .qml/.cpp/.cs 等被
    Python 规则误染（def/class 之外全是灰白，观感反而更差）。

    注意：必须 override `_build_rules`，否则会继承基类的数字/字符串规则，
    仍会对未知类型做部分染色。
    """

    def _build_rules(self):
        pass          # 不注册任何规则 → 完全零染色


class QmlHighlighter(_TableHighlighter):
    """QML / Qt Quick"""
    KEYWORDS = ('import', 'as', 'property', 'signal', 'function', 'readonly',
                'default', 'required', 'alias', 'component', 'on', 'pragma',
                'Singleton', 'QtObject', 'Item', 'Rectangle', 'Text', 'Image',
                'MouseArea', 'Row', 'Column', 'Grid', 'ListView', 'Repeater',
                'Loader', 'Component', 'Window', 'ApplicationWindow', 'Button',
                'Label', 'TextField', 'anchors', 'parent', 'id')
    BUILTINS = ('int', 'real', 'string', 'bool', 'var', 'color', 'url', 'list',
                'true', 'false', 'null', 'undefined')
    LINE_COMMENT = r'//'
    BLOCK_COMMENT = (r'/\*', r'\*/')
    EXTRA_RULES = (
        (r'\bid\s*:', 'attr', False),
        (r'\b(?:property|signal)\s+\w+', 'function', False),
        (r'\b\w+(?=\s*:)', 'attr', False),
        (r'\bon\s+\w+', 'decorator', True),
    )


class CppHighlighter(_TableHighlighter):
    """C / C++ / Objective-C"""
    KEYWORDS = ('if', 'else', 'for', 'while', 'do', 'switch', 'case', 'default',
                'break', 'continue', 'return', 'goto', 'sizeof', 'typedef',
                'struct', 'union', 'enum', 'static', 'const', 'volatile',
                'extern', 'register', 'auto', 'inline', 'restrict', 'template',
                'typename', 'namespace', 'using', 'class', 'public', 'private',
                'protected', 'virtual', 'override', 'explicit', 'friend',
                'operator', 'new', 'delete', 'this', 'try', 'catch', 'throw',
                'constexpr', 'noexcept', 'nullptr', 'decltype', 'static_cast',
                'dynamic_cast', 'reinterpret_cast', 'const_cast')
    BUILTINS = ('void', 'char', 'short', 'int', 'long', 'float', 'double',
                'signed', 'unsigned', 'bool', 'wchar_t', 'size_t', 'std',
                'string', 'vector', 'map', 'true', 'false', 'NULL', 'printf',
                'scanf', 'malloc', 'free', 'cout', 'cin', 'cerr', 'endl')
    LINE_COMMENT = r'//'
    BLOCK_COMMENT = (r'/\*', r'\*/')
    EXTRA_RULES = (
        (r'^\s*#\s*\w+', 'decorator', True),
        (r'#\s*include\s*[<"][^>"]*[>"]', 'string', False),
    )


class CSharpHighlighter(CppHighlighter):
    """C# —— 复用 C/C++ 骨架，替换关键字与内置名"""
    KEYWORDS = ('namespace', 'using', 'class', 'struct', 'interface', 'enum',
                'public', 'private', 'protected', 'internal', 'static',
                'readonly', 'const', 'abstract', 'virtual', 'override',
                'sealed', 'partial', 'async', 'await', 'get', 'set', 'var',
                'if', 'else', 'for', 'foreach', 'while', 'do', 'switch',
                'case', 'default', 'break', 'continue', 'return', 'new',
                'this', 'base', 'try', 'catch', 'finally', 'throw', 'typeof',
                'nameof', 'is', 'as', 'in', 'out', 'ref', 'delegate', 'event')
    BUILTINS = ('void', 'string', 'int', 'uint', 'long', 'float', 'double',
                'bool', 'char', 'byte', 'object', 'dynamic', 'var', 'true',
                'false', 'null', 'Console', 'WriteLine', 'Write', 'ReadLine',
                'String', 'Int32', 'Boolean', 'Task', 'List', 'Dictionary')
    EXTRA_RULES = (
        (r'^\s*#\s*\w+', 'decorator', True),
        (r'\[[\w.]+\]', 'decorator', False),
    )


class RustHighlighter(_TableHighlighter):
    """Rust"""
    KEYWORDS = ('fn', 'let', 'mut', 'const', 'static', 'struct', 'enum',
                'trait', 'impl', 'for', 'while', 'loop', 'match', 'if',
                'else', 'return', 'use', 'mod', 'pub', 'crate', 'super',
                'self', 'Self', 'as', 'where', 'type', 'dyn', 'ref', 'move',
                'unsafe', 'async', 'await', 'in', 'dyn')
    BUILTINS = ('i8', 'i16', 'i32', 'i64', 'i128', 'u8', 'u16', 'u32', 'u64',
                'usize', 'isize', 'f32', 'f64', 'bool', 'char', 'str',
                'String', 'Vec', 'Option', 'Some', 'None', 'Result', 'Ok',
                'Err', 'println', 'format', 'vec')
    LINE_COMMENT = r'//'
    BLOCK_COMMENT = (r'/\*', r'\*/')
    EXTRA_RULES = (
        (r'#!?\[[^\]]*\]', 'decorator', True),
        (r'\b\w+!', 'function', False),
        (r"'[a-z_][\w]*", 'operator', False),      # 生命周期标注 'a
    )


class GoHighlighter(_TableHighlighter):
    """Go"""
    KEYWORDS = ('package', 'import', 'func', 'var', 'const', 'type', 'struct',
                'interface', 'map', 'chan', 'go', 'defer', 'select', 'switch',
                'case', 'default', 'if', 'else', 'for', 'range', 'return',
                'break', 'continue', 'fallthrough', 'goto')
    BUILTINS = ('string', 'int', 'int8', 'int16', 'int32', 'int64', 'uint',
                'uint8', 'uint32', 'uint64', 'float32', 'float64', 'bool',
                'byte', 'rune', 'error', 'nil', 'true', 'false', 'make',
                'new', 'len', 'cap', 'append', 'copy', 'delete', 'panic',
                'recover', 'print', 'println')
    LINE_COMMENT = r'//'
    BLOCK_COMMENT = (r'/\*', r'\*/')


class JavaHighlighter(_TableHighlighter):
    """Java"""
    KEYWORDS = ('public', 'private', 'protected', 'class', 'interface',
                'enum', 'extends', 'implements', 'abstract', 'final',
                'static', 'void', 'new', 'this', 'super', 'import',
                'package', 'return', 'if', 'else', 'for', 'while', 'do',
                'switch', 'case', 'default', 'break', 'continue', 'try',
                'catch', 'finally', 'throw', 'throws', 'instanceof',
                'native', 'synchronized', 'volatile', 'transient', 'assert')
    BUILTINS = ('String', 'Integer', 'Boolean', 'Double', 'Float', 'Long',
                'int', 'boolean', 'char', 'byte', 'short', 'long', 'float',
                'double', 'true', 'false', 'null', 'System', 'out', 'println')
    LINE_COMMENT = r'//'
    BLOCK_COMMENT = (r'/\*', r'\*/')
    EXTRA_RULES = (
        (r'@\w+', 'decorator', True),
    )


class KotlinHighlighter(_TableHighlighter):
    """Kotlin"""
    KEYWORDS = ('fun', 'val', 'var', 'class', 'object', 'interface', 'enum',
                'data', 'sealed', 'companion', 'init', 'constructor', 'if',
                'else', 'for', 'while', 'do', 'when', 'return', 'break',
                'continue', 'try', 'catch', 'finally', 'throw', 'is', 'in',
                'as', 'typealias', 'import', 'package', 'suspend', 'override')
    BUILTINS = ('String', 'Int', 'Long', 'Double', 'Float', 'Boolean', 'Char',
                'Byte', 'Short', 'Unit', 'Any', 'Nothing', 'true', 'false',
                'null', 'listOf', 'mutableListOf', 'mapOf', 'println')
    LINE_COMMENT = r'//'
    BLOCK_COMMENT = (r'/\*', r'\*/')
    EXTRA_RULES = (
        (r'@\w+', 'decorator', True),
    )


class SwiftHighlighter(_TableHighlighter):
    """Swift"""
    KEYWORDS = ('func', 'let', 'var', 'class', 'struct', 'enum', 'protocol',
                'extension', 'import', 'init', 'deinit', 'guard', 'if',
                'else', 'for', 'in', 'while', 'repeat', 'return', 'break',
                'continue', 'switch', 'case', 'default', 'where', 'try',
                'catch', 'throw', 'throws', 'async', 'await', 'inout',
                'static', 'final', 'private', 'public', 'internal', 'open',
                'fileprivate', 'mutating', 'lazy', 'self')
    BUILTINS = ('String', 'Int', 'Double', 'Float', 'Bool', 'Character',
                'Array', 'Dictionary', 'Set', 'Optional', 'true', 'false',
                'nil', 'print')
    LINE_COMMENT = r'//'
    BLOCK_COMMENT = (r'/\*', r'\*/')
    EXTRA_RULES = (
        (r'@\w+', 'decorator', True),
    )


class LuaHighlighter(_TableHighlighter):
    """Lua（行注释 --，块注释 --[[ ]]）"""
    KEYWORDS = ('and', 'break', 'do', 'else', 'elseif', 'end', 'false', 'for',
                'function', 'if', 'in', 'local', 'nil', 'not', 'or', 'repeat',
                'return', 'then', 'true', 'until', 'while')
    BUILTINS = ('print', 'pairs', 'ipairs', 'type', 'tostring', 'tonumber',
                'require', 'math', 'string', 'table', 'io', 'os', 'self')
    LINE_COMMENT = r'--'
    BLOCK_COMMENT = (r'--\[\[', r'\]\]')


class DartHighlighter(_TableHighlighter):
    """Dart / Flutter"""
    KEYWORDS = ('class', 'extends', 'implements', 'mixin', 'enum', 'typedef',
                'import', 'export', 'part', 'library', 'as', 'show', 'hide',
                'abstract', 'static', 'final', 'const', 'var', 'dynamic',
                'void', 'Function', 'if', 'else', 'for', 'while', 'do',
                'switch', 'case', 'default', 'return', 'break', 'continue',
                'try', 'catch', 'finally', 'throw', 'rethrow', 'new', 'this',
                'super', 'async', 'await', 'sync', 'yield', 'late')
    BUILTINS = ('String', 'int', 'double', 'bool', 'num', 'List', 'Map',
                'Set', 'Iterable', 'Object', 'Future', 'Stream', 'true',
                'false', 'null', 'print')
    LINE_COMMENT = r'//'
    BLOCK_COMMENT = (r'/\*', r'\*/')
    EXTRA_RULES = (
        (r'@\w+', 'decorator', True),
    )


class PhpHighlighter(_TableHighlighter):
    """PHP（行注释 // 与 #）"""
    KEYWORDS = ('echo', 'print', 'if', 'else', 'elseif', 'for', 'foreach',
                'while', 'do', 'switch', 'case', 'default', 'break',
                'continue', 'return', 'function', 'class', 'interface',
                'trait', 'namespace', 'use', 'public', 'private',
                'protected', 'static', 'final', 'abstract', 'const', 'new',
                'clone', 'try', 'catch', 'finally', 'throw', 'instanceof',
                'global', 'require', 'include', 'require_once', 'include_once')
    BUILTINS = ('array', 'count', 'strlen', 'isset', 'unset', 'empty',
                'true', 'false', 'null', 'NULL', 'php')
    LINE_COMMENT = r'(?://|#)'
    BLOCK_COMMENT = (r'/\*', r'\*/')
    EXTRA_RULES = (
        (r'<[?](?:php)?', 'decorator', True),
        (r'[?]>', 'decorator', True),
        (r'\$\w+', 'self', False),
    )


class RubyHighlighter(_TableHighlighter):
    """Ruby"""
    KEYWORDS = ('def', 'end', 'class', 'module', 'if', 'elsif', 'else',
                'unless', 'while', 'until', 'for', 'in', 'do', 'begin',
                'rescue', 'ensure', 'raise', 'return', 'yield', 'self',
                'nil', 'true', 'false', 'and', 'or', 'not', 'case', 'when',
                'then', 'require', 'require_relative', 'attr_accessor',
                'attr_reader', 'attr_writer')
    BUILTINS = ('puts', 'print', 'p', 'gets', 'length', 'size', 'each',
                'map', 'select', 'reject', 'to_s', 'to_i')
    LINE_COMMENT = r'#'
    EXTRA_RULES = (
        (r'@@?\w+', 'self', False),                # 实例/类变量 @x @@x
        (r':\w+', 'attr', False),                  # 符号 :sym
        (r'\b\w+!', 'function', False),            # 危险方法 save!
        (r'^\s*(?:=begin)[\s\S]*?(?:=end)', 'comment', False),
    )


class ShellHighlighter(_TableHighlighter):
    """Shell / Bash / Zsh / PowerShell"""
    KEYWORDS = ('if', 'then', 'else', 'elif', 'fi', 'for', 'while', 'until',
                'do', 'done', 'case', 'esac', 'function', 'return', 'in',
                'select', 'local', 'export', 'readonly', 'declare', 'unset',
                'shift', 'source', 'alias', 'echo', 'exit', 'set', 'env')
    BUILTINS = ('cd', 'ls', 'pwd', 'cat', 'grep', 'sed', 'awk', 'find',
                'mkdir', 'rm', 'cp', 'mv', 'chmod', 'chown', 'sudo', 'apt',
                'yum', 'npm', 'git', 'python', 'node', 'pip', 'true', 'false')
    LINE_COMMENT = r'#'
    EXTRA_RULES = (
        (r'^#!', 'decorator', True),               # shebang
        (r'\$\{?\w+\}?', 'self', False),           # 变量 $VAR / ${VAR}
        (r'^\s*\w+(?=\s*\(\))', 'function', True),  # 函数定义
    )


class YamlHighlighter(_TableHighlighter):
    """YAML"""
    KEYWORDS = ('true', 'false', 'null', 'yes', 'no', 'on', 'off')
    LINE_COMMENT = r'#'
    EXTRA_RULES = (
        (r'^\s*[\w.\-/]+(?=\s*:)', 'json_key', True),   # 键名
        (r'(?<=:\s)[^\n#]*', 'json_val', False),        # 值
        (r'^\s*-\s+', 'operator', True),                # 列表项
        (r'^\s*(?:---|\.\.\.)\s*$', 'decorator', True),  # 文档分隔
        (r'[&*][\w.\-]+', 'decorator', False),          # 锚点/别名
    )


class SqlHighlighter(_TableHighlighter):
    """SQL（关键字大小写不敏感）"""
    KEYWORDS_PATTERN = r'\b(?i:select|from|where|insert|into|values|update|' \
                       r'set|delete|create|table|database|index|view|drop|' \
                       r'alter|add|column|primary|key|foreign|references|' \
                       r'join|left|right|inner|outer|full|cross|on|as|and|' \
                       r'or|not|in|exists|between|like|ilike|group|by|order|' \
                       r'having|limit|offset|union|all|distinct|case|when|' \
                       r'then|else|end|with|null|is|asc|desc|count|sum|avg|' \
                       r'min|max|coalesce|cast|begin|commit|rollback|' \
                       r'transaction)\b'
    BUILTINS = ('int', 'bigint', 'varchar', 'text', 'boolean', 'date',
                'timestamp', 'numeric', 'decimal', 'float', 'blob', 'json',
                'true', 'false', 'null')
    LINE_COMMENT = r'--'
    BLOCK_COMMENT = (r'/\*', r'\*/')
    EXTRA_RULES = (
        (r'@\w+', 'self', False),                  # 参数占位符
    )


class MarkdownHighlighter(_TableHighlighter):
    """Markdown"""
    KEYWORDS = ()
    BUILTINS = ()
    LINE_COMMENT = None
    EXTRA_RULES = (
        (r'^#{1,6}[^\n]*', 'keyword', True),            # 标题
        (r'^\s*(?:```|~~~)[^\n]*', 'decorator', True),  # 代码围栏
        (r'^\s*>[^\n]*', 'comment', False),             # 引用
        (r'^\s*[-*+]\s+', 'operator', True),            # 无序列表
        (r'^\s*\d+\.\s+', 'operator', True),            # 有序列表
        (r'^\s*(?:---|\*\*\*|___)\s*$', 'decorator', False),  # 分隔线
        (r'`[^`\n]+`', 'string', False),                # 行内代码
        (r'\*\*[^*\n]+\*\*', 'keyword', True),          # 粗体
        (r'\[[^\]\n]*\]\([^)\n]*\)', 'function', False),  # 链接
    )


class EnvHighlighter(_TableHighlighter):
    """INI / .env / .conf / .properties / TOML 键值配置"""
    LINE_COMMENT = r'[#;]'
    EXTRA_RULES = (
        (r'^\s*\[[^\]\n]*\]', 'decorator', True),       # section
        (r'^\s*[\w.\-]+(?=\s*[=:])', 'json_key', True),  # 键名
    )


class LogHighlighter(_TableHighlighter):
    """日志文件 —— 按等级染色（ERROR 红 / WARN 橙 / INFO 青）"""
    LINE_COMMENT = None
    EXTRA_RULES = (
        (r'\b(?i:error|failed|fatal|exception|traceback|critical)\b[^\n]*',
         'self', True),
        (r'\b(?i:warn|warning|deprecated)\b[^\n]*', 'todo', True),
        (r'\b(?i:info|debug|success|ok|done|passed)\b', 'builtin', False),
        (r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?', 'number', False),
        (r'^\s*\[[^\]\n]*\]', 'decorator', False),
    )


# ============================================================
# 工厂函数：根据文件名/扩展名返回对应的高亮器
# ============================================================
HIGHLIGHTER_MAP = {
    # ---- Python ----
    '.py': PythonHighlighter, '.pyw': PythonHighlighter, '.pyi': PythonHighlighter,
    '.pyx': PythonHighlighter,
    # ---- Web ----
    '.js': JavaScriptHighlighter, '.mjs': JavaScriptHighlighter,
    '.cjs': JavaScriptHighlighter, '.jsx': JavaScriptHighlighter,
    '.ts': JavaScriptHighlighter, '.tsx': JavaScriptHighlighter,
    '.vue': JavaScriptHighlighter,
    '.html': HTMLHighlighter, '.htm': HTMLHighlighter,
    '.xml': HTMLHighlighter, '.svg': HTMLHighlighter, '.xaml': HTMLHighlighter,
    '.css': CSSHighlighter, '.scss': CSSHighlighter, '.less': CSSHighlighter,
    '.json': JSONHighlighter, '.jsonc': JSONHighlighter, '.lock': JSONHighlighter,
    # ---- 桌面 / 移动 ----
    '.qml': QmlHighlighter,
    # ---- C 家族 ----
    '.c': CppHighlighter, '.h': CppHighlighter, '.cpp': CppHighlighter,
    '.cc': CppHighlighter, '.cxx': CppHighlighter, '.hpp': CppHighlighter,
    '.hh': CppHighlighter, '.mm': CppHighlighter,
    '.cs': CSharpHighlighter,
    # ---- 系统级 ----
    '.rs': RustHighlighter, '.go': GoHighlighter,
    # ---- JVM / Apple / 脚本 ----
    '.java': JavaHighlighter,
    '.kt': KotlinHighlighter, '.kts': KotlinHighlighter,
    '.swift': SwiftHighlighter,
    '.lua': LuaHighlighter, '.dart': DartHighlighter,
    '.php': PhpHighlighter, '.rb': RubyHighlighter,
    # ---- Shell ----
    '.sh': ShellHighlighter, '.bash': ShellHighlighter, '.zsh': ShellHighlighter,
    '.fish': ShellHighlighter, '.ps1': ShellHighlighter,
    '.bat': ShellHighlighter, '.cmd': ShellHighlighter,
    # ---- 数据 / 配置 ----
    '.yaml': YamlHighlighter, '.yml': YamlHighlighter,
    '.sql': SqlHighlighter,
    '.ini': EnvHighlighter, '.cfg': EnvHighlighter, '.conf': EnvHighlighter,
    '.properties': EnvHighlighter, '.toml': EnvHighlighter,
    # ---- 文档 / 日志 ----
    '.md': MarkdownHighlighter, '.markdown': MarkdownHighlighter,
    '.log': LogHighlighter,
    '.txt': NullHighlighter,
}

# 无扩展名的特殊文件名（os.path.splitext('.env') → ('', '.env') 取不到 ext）
SPECIAL_NAME_MAP = {
    '.env': EnvHighlighter,
    '.gitignore': ShellHighlighter,
    '.gitattributes': ShellHighlighter,
    '.gitmodules': EnvHighlighter,
    '.editorconfig': EnvHighlighter,
    'dockerfile': ShellHighlighter,
    'makefile': ShellHighlighter,
    'cmakelists.txt': ShellHighlighter,
    'license': NullHighlighter,
    'readme': MarkdownHighlighter,
}


def create_highlighter(file_path, parent=None):
    """根据文件名/扩展名创建对应的语法高亮器。

    ★ 未知类型回落 NullHighlighter（零染色），不再误用 Python 规则
      —— 此前 .qml/.cpp/.cs 等会被 Python 的 def/class 规则误染，
      实际观感比"不高亮"更差。
    """
    if not file_path:
        return NullHighlighter(parent)
    name = os.path.basename(file_path).lower()
    cls = SPECIAL_NAME_MAP.get(name)
    if cls:
        return cls(parent)
    ext = os.path.splitext(file_path)[1].lower()
    cls = HIGHLIGHTER_MAP.get(ext)
    if cls:
        return cls(parent)
    return NullHighlighter(parent)