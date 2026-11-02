# -*- coding: utf-8 -*-
"""
Lemon Serve Bridge — 基于 mimo serve HTTP API 的双向通信桥
=========================================================
核心思路：
1. 启动 `mimo serve` 作为后台服务进程
2. 通过 HTTP REST API 发送消息、接收回复
3. 通过 SSE 事件流实时监听 Lemon Code 输出
4. 右侧面板输入同步发送到 API，回复实时显示

功能：
- {ICON:circle-check} 消息发送/接收（同步 + SSE 实时推送）
- {ICON:circle-check} 会话管理（创建/恢复/列表）
- {ICON:circle-check} 权限响应
- {ICON:circle-check} 配置选项
- {ICON:circle-check} 底部面板显示 serve 进程日志
"""

import os, sys, json, threading, time, re, traceback
import subprocess
import logging
import logging.handlers
from datetime import datetime
from typing import Optional, Dict
import requests
from PyQt5.QtCore import QObject, pyqtSignal, QTimer
from PyQt5.QtWidgets import QApplication

# ★ 事件总线 + 快照管理器 + 消息存储 + 设置管理 + 交互日志
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.interaction_logger import get_interaction_logger
from event_bus import EventBus, EventType
from snapshot_manager import SnapshotManager
from message_store import MessageStore
from ollama_bridge import OllamaAutoDetector, OllamaModelManager
from builtin_skills import CodeFormatterSkill, CodeReviewSkill
from crash_recovery import CrashRecovery
from settings_manager import get_settings_manager
from workspace_manager import get_workspace_manager
from context_manager import ContextManager

# ★ v3.118: 右侧面板 Skill 可视化仪表盘
try:
    from core.skill_visualizer import get_skill_visualizer
    _SKILL_VISUALIZER_AVAILABLE = True
except ImportError:
    _SKILL_VISUALIZER_AVAILABLE = False
    get_skill_visualizer = None

# ★ v3.57: 通信模式
COMMUNICATION_MODE_STDIO = 'stdio'
COMMUNICATION_MODE_HTTP = 'http'

# ★ v3.73: Process Bridge 统一导入路径（shared/bridges/）
try:
    from shared.bridges.mimo_process_bridge import MIMOProcessBridge
    _PROCESS_BRIDGE_AVAILABLE = True
except ImportError:
    _PROCESS_BRIDGE_AVAILABLE = False
    MIMOProcessBridge = None

# ★ v3.58: ACP Bridge 作为备用通信方式
try:
    from shared.acp_bridge import ACPBridge
    _ACP_BRIDGE_AVAILABLE = True
except ImportError:
    _ACP_BRIDGE_AVAILABLE = False
    ACPBridge = None

# ★ v3.71: PTY Bridge 作为第三备选通信方式
try:
    from shared.pty_bridge import PTYBridge
    _PTY_BRIDGE_AVAILABLE = True
except ImportError:
    _PTY_BRIDGE_AVAILABLE = False
    PTYBridge = None

# ★ v3.54: 智能桥接路由器
try:
    from core.intelligent_bridge_router import (
        IntelligentBridgeRouter, BridgeType, BridgeStatus
    )
    _ROUTER_AVAILABLE = True
except ImportError:
    _ROUTER_AVAILABLE = False
    IntelligentBridgeRouter = None

try:
    import markdown as md_lib
    _MARKDOWN_AVAILABLE = True
except ImportError:
    _MARKDOWN_AVAILABLE = False

try:
    from pygments import highlight
    from pygments.lexers import get_lexer_by_name, guess_lexer
    from pygments.formatters import HtmlFormatter
    from pygments.styles import get_style_by_name
    _PYGMENTS_AVAILABLE = True
except ImportError:
    _PYGMENTS_AVAILABLE = False


# ==================== ★ 性能优化模块 ====================

class ConnectionPool:
    """HTTP 连接池管理器：复用 requests.Session 减少 TCP 握手开销
    
    用途：多次 HTTP 请求复用同一个 Session 对象，利用连接池和 keep-alive
    减少每次请求的 TCP 握手延迟（约 50-100ms/次）。
    """
    
    def __init__(self, max_pool_size: int = 10, max_retries: int = 3):
        self._session: Optional[requests.Session] = None
        self._max_pool_size = max_pool_size
        self._max_retries = max_retries
        self._lock = threading.Lock()
        self._created_at = time.time()
    
    def get_session(self) -> requests.Session:
        """获取或创建 HTTP 会话（线程安全）"""
        with self._lock:
            if self._session is None:
                self._session = requests.Session()
                adapter = requests.adapters.HTTPAdapter(
                    pool_connections=self._max_pool_size,
                    pool_maxsize=self._max_pool_size,
                    max_retries=self._max_retries,
                    pool_block=False,
                )
                self._session.mount('http://', adapter)
                self._session.mount('https://', adapter)
            return self._session
    
    def close(self):
        """关闭连接池"""
        with self._lock:
            if self._session:
                try:
                    self._session.close()
                except Exception:
                    pass
                self._session = None
    
    def __enter__(self):
        return self.get_session()
    
    def __exit__(self, *args):
        pass  # 不关闭，保持复用


class RetryConfig:
    """HTTP 请求重试配置"""
    
    def __init__(self, max_retries: int = 3, base_delay: float = 1.0,
                 max_delay: float = 30.0, backoff_factor: float = 2.0,
                 retryable_statuses: tuple = (429, 500, 502, 503, 504)):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.retryable_statuses = retryable_statuses


def retry_request(retry_config: RetryConfig = None):
    """HTTP 请求重试装饰器
    
    对可重试的 HTTP 状态码和连接异常自动重试，使用指数退避策略。
    """
    if retry_config is None:
        retry_config = RetryConfig()
    
    def decorator(func):
        import functools
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(retry_config.max_retries + 1):
                try:
                    response = func(*args, **kwargs)
                    if response.status_code in retry_config.retryable_statuses:
                        if attempt < retry_config.max_retries:
                            delay = min(
                                retry_config.base_delay * (retry_config.backoff_factor ** attempt),
                                retry_config.max_delay
                            )
                            print(f"[Retry] HTTP {response.status_code}，{delay:.1f}s 后重试 (第{attempt+1}次)",
                                  flush=True)
                            time.sleep(delay)
                            continue
                    return response
                except (requests.exceptions.ConnectionError,
                        requests.exceptions.Timeout,
                        requests.exceptions.ChunkedEncodingError) as e:
                    last_exception = e
                    if attempt < retry_config.max_retries:
                        delay = min(
                            retry_config.base_delay * (retry_config.backoff_factor ** attempt),
                            retry_config.max_delay
                        )
                        print(f"[Retry] {type(e).__name__}，{delay:.1f}s 后重试 (第{attempt+1}次)", flush=True)
                        time.sleep(delay)
                    else:
                        raise
            if last_exception:
                raise last_exception
            return response
        return wrapper
    return decorator


class TimeoutConfig:
    """超时配置：为不同端点设置不同的超时时间"""
    
    def __init__(self):
        self.health_check: float = 3.0      # 健康检查
        self.session_create: float = 10.0    # 会话创建
        self.message_send: float = 30.0      # 消息发送
        self.model_list: float = 5.0          # 模型列表
        self.snapshot: float = 15.0           # 快照操作
        self.default: float = 10.0            # 默认超时
    
    def get(self, endpoint: str = "default") -> float:
        """获取指定端点的超时时间"""
        return getattr(self, endpoint, self.default)

class MessageBatcher:
    """消息合并器：高频率的小消息在 100ms 窗口内合并发送
    
    用途：流式输出时，大量小 token 消息会频繁触发 UI 更新。
    本类将 100ms 内到达的消息合并为一条，减少 UI 重绘次数。
    """
    
    def __init__(self, flush_callback, window_ms: int = 100, max_size: int = 50):
        self._flush_callback = flush_callback
        self._window = window_ms / 1000.0
        self._max_size = max_size
        self._buffer: list = []
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self._closed = False
    
    def add(self, item):
        """添加一条消息到缓冲区"""
        if self._closed:
            return
        with self._lock:
            self._buffer.append(item)
            if len(self._buffer) >= self._max_size:
                self._flush_now()
            elif self._timer is None:
                self._timer = threading.Timer(self._window, self._flush_now)
                self._timer.daemon = True
                self._timer.start()
    
    def _flush_now(self):
        """立即刷新缓冲区"""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            if not self._buffer:
                return
            items = self._buffer[:]
            self._buffer.clear()
        try:
            self._flush_callback(items)
        except Exception as e:
            print(f"[MessageBatcher] flush 错误: {e}", flush=True)
    
    def flush(self):
        """手动刷新"""
        self._flush_now()
    
    def close(self):
        self._closed = True
        self._flush_now()


class GitStatusCache:
    """Git 状态缓存：git status 结果缓存指定秒数，避免频繁调用"""
    
    def __init__(self, ttl: float = 5.0):
        self._ttl = ttl
        self._cache: Dict[str, tuple] = {}  # path -> (timestamp, result)
        self._lock = threading.Lock()
    
    def get(self, project_path: str) -> Optional[str]:
        """获取缓存的 git status 结果（未过期则返回缓存，否则 None）"""
        with self._lock:
            entry = self._cache.get(project_path)
            if entry is None:
                return None
            ts, result = entry
            if time.time() - ts < self._ttl:
                return result
            return None
    
    def set(self, project_path: str, result: str):
        with self._lock:
            self._cache[project_path] = (time.time(), result)
    
    def get_or_compute(self, project_path: str, compute_fn) -> str:
        """获取缓存或计算（计算后缓存）"""
        cached = self.get(project_path)
        if cached is not None:
            return cached
        result = compute_fn()
        self.set(project_path, result)
        return result
    
    def invalidate(self, project_path: str = ""):
        """使缓存失效"""
        with self._lock:
            if project_path:
                self._cache.pop(project_path, None)
            else:
                self._cache.clear()


class LogRotator:
    """日志轮转：日志文件超过指定大小自动轮转"""
    
    def __init__(self, log_file: str, max_bytes: int = 10 * 1024 * 1024,
                 backup_count: int = 3):
        self._log_file = log_file
        self._max_bytes = max_bytes
        self._backup_count = backup_count
        self._handler = None
        self._setup()
    
    def _setup(self):
        try:
            log_dir = os.path.dirname(self._log_file)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            self._handler = logging.handlers.RotatingFileHandler(
                self._log_file,
                maxBytes=self._max_bytes,
                backupCount=self._backup_count,
                encoding='utf-8',
            )
            self._handler.setFormatter(
                logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
            )
        except Exception as e:
            print(f"[LogRotator] 初始化失败: {e}", flush=True)
    
    def get_logger(self, name: str = "mimo_agent") -> logging.Logger:
        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)
        if self._handler and self._handler not in logger.handlers:
            logger.addHandler(self._handler)
        return logger
    
    def check_and_rotate(self):
        """手动检查是否需要轮转"""
        if self._handler and os.path.exists(self._log_file):
            try:
                if os.path.getsize(self._log_file) > self._max_bytes:
                    self._handler.doRollover()
            except Exception:
                pass


# ==================== Markdown → HTML 转换器 ====================
_PYGMENTS_CSS = ""
if _PYGMENTS_AVAILABLE:
    try:
        _formatter = HtmlFormatter(style='monokai')
        _PYGMENTS_CSS = _formatter.get_style_defs('.codehilite')
    except Exception:
        pass

def _highlight_code(code, lang=''):
    """使用 Pygments 进行代码高亮"""
    if not _PYGMENTS_AVAILABLE:
        safe = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        return f'<pre><code>{safe}</code></pre>'
    try:
        if lang and lang.strip():
            lexer = get_lexer_by_name(lang, stripall=False)
        else:
            lexer = guess_lexer(code)
        formatter = HtmlFormatter(
            style='monokai',
            noclasses=False,
            cssclass='codehilite',
            linenos='table',
            linenostart=1,
        )
        return highlight(code, lexer, formatter)
    except Exception:
        safe = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        return f'<pre><code>{safe}</code></pre>'


# ==================== 图表自动检测与HTML内容拦截 ====================
# 1. 检测到图表/几何体关键词时，注入标记供右侧栏前端渲染
# 2. 检测到 HTML 文件生成/打开相关内容时，隐藏掉（不让用户看到）

_CHART_PATTERNS = [
    # === 函数图像 ===
    (r'(sin|cos|tan)[_]?x?[_]?(?:plot|graph|image|chart|func|函数)[_.].*(?:html|png|jpg|svg)',
     lambda m: f'y = {m.group(1).lower()}(x)'),
    (r'(正弦|sin)[^。\n]{0,30}(?:图像|曲线|函数|图)', lambda m: 'y = sin(x)'),
    (r'(余弦|cos)[^。\n]{0,30}(?:图像|曲线|函数|图)', lambda m: 'y = cos(x)'),
    (r'(正切|tan)[^。\n]{0,30}(?:图像|曲线|函数|图)', lambda m: 'y = tan(x)'),
    (r'sin\s*\(\s*x\s*\).*?(?:图像|曲线|plot|graph|chart)', lambda m: 'y = sin(x)'),
    (r'cos\s*\(\s*x\s*\).*?(?:图像|曲线|plot|graph|chart)', lambda m: 'y = cos(x)'),
    (r'tan\s*\(\s*x\s*\).*?(?:图像|曲线|plot|graph|chart)', lambda m: 'y = tan(x)'),
    (r'(?:图像|曲线|plot|graph|chart).*?sin\s*\(\s*x\s*\)', lambda m: 'y = sin(x)'),
    (r'(?:图像|曲线|plot|graph|chart).*?cos\s*\(\s*x\s*\)', lambda m: 'y = cos(x)'),
    (r'(?:图像|曲线|plot|graph|chart).*?tan\s*\(\s*x\s*\)', lambda m: 'y = tan(x)'),
    # === 饼图/扇形图（市场份额/占比/比例优先匹配饼图） ===
    (r'饼图|pie\s*chart|饼状图|扇形图|市场份额|占比|比例分布', lambda m: '【chart:pie】'),
    (r'(?:饼|扇形|pie).*?(?:图|chart|plot)', lambda m: '【chart:pie】'),
    (r'市场调查|市场调研|竞品分析|占比分析', lambda m: '【chart:pie】'),
    # === 折线图/曲线图/趋势图 ===
    (r'折线图|曲线图|line\s*chart|折线统计|趋势图|走势图', lambda m: '【chart:line】'),
    (r'(?:折线|曲线|line|趋势|走势).*?(?:图|chart|plot)', lambda m: '【chart:line】'),
    # 检测"数据趋势""增长趋势""变化趋势"等
    (r'(数据趋势|增长趋势|变化趋势|发展趋势|市场趋势|趋势分析|走势分析)', lambda m: '【chart:line】'),
    # 检测"蓝色折线""红色折线"等描述
    (r'[蓝红黄紫绿粉灰黑白色].*?折线.*?(?:市场|企业|数据|规模|数量|收入)', lambda m: '【chart:line】'),
    (r'[蓝红黄紫绿粉灰黑白色].*?折线', lambda m: '【chart:line】'),
    # === 柱状图/直方图/条形图 ===
    (r'直方图|柱状图|条形图|bar\s*chart|histogram|柱形图', lambda m: '【chart:bar】'),
    (r'(?:bar|柱|条|hist).*?(?:图|chart|plot|graph)', lambda m: '【chart:bar】'),
    # === 散点图 ===
    (r'散点图|scatter\s*plot|scatter\s*chart', lambda m: '【chart:scatter】'),
    (r'散点.*?(?:图|chart|plot)', lambda m: '【chart:scatter】'),
    # === 3D曲面 ===
    (r'3D\s*surface|三维曲面|3d\s*plot', lambda m: '【chart:surface3d】'),
    (r'(?:3D|三维|surface).*?(?:图|chart|plot|曲面)', lambda m: '【chart:surface3d】'),
    # === 3D几何体：正方体/立方体 ===
    (r'正方体|立方体|cube|正六面体', lambda m: '【geom:cube】'),
    (r'(?:正方|立方|cube).*?(?:体|图形|模型|几何体|shape|geometry)', lambda m: '【geom:cube】'),
    # === 3D几何体：长方体/四棱柱 ===
    (r'长方体|四棱柱|cuboid|rectangular.*prism', lambda m: '【geom:cuboid】'),
    (r'(?:长方|四棱柱).*?(?:体|图形|模型|几何体)', lambda m: '【geom:cuboid】'),
    # === 3D几何体：圆柱 ===
    (r'圆柱体?|cylinder|圆柱', lambda m: '【geom:cylinder】'),
    (r'(?:圆柱).*?(?:体|图形|模型|几何体)', lambda m: '【geom:cylinder】'),
    # === 3D几何体：圆锥 ===
    (r'圆锥体?|cone|圆锥', lambda m: '【geom:cone】'),
    (r'(?:圆锥).*?(?:体|图形|模型|几何体)', lambda m: '【geom:cone】'),
    # === 3D几何体：球 ===
    (r'球(?:体|形)?|sphere|球体', lambda m: '【geom:sphere】'),
    (r'(?:球|sphere).*?(?:体|图形|模型|几何体|surface)', lambda m: '【geom:sphere】'),
    # === 3D几何体：椭球/椭圆体 ===
    (r'椭球|椭圆体|椭球体|ellipsoid|椭圆的.*(?:体|球)', lambda m: '【geom:ellipsoid】'),
    (r'(?:椭球|椭圆体|ellipsoid).*?(?:体|图形|模型)', lambda m: '【geom:ellipsoid】'),
    # === 3D几何体：三棱锥/四面体 ===
    (r'三棱锥|四面体|triangular\s*pyramid|tetrahedron|三角锥', lambda m: '【geom:pyramid3】'),
    (r'(?:三棱锥|四面体|三角锥).*?(?:体|图形|模型|几何体)', lambda m: '【geom:pyramid3】'),
    # === 3D几何体：四棱锥 ===
    (r'四棱锥|方锥|pyramid|棱锥', lambda m: '【geom:pyramid4】'),
    (r'(?:四棱锥|方锥|棱锥).*?(?:体|图形|模型|几何体)', lambda m: '【geom:pyramid4】'),
    # === 3D几何体：三棱柱 ===
    (r'三棱柱|三角柱|triangular\s*prism', lambda m: '【geom:prism3】'),
    # === 通用：3D几何体/几何模型 ===
    (r'3D几何体|三维几何体|几何模型|立体图形|3d.*geometry', lambda m: '【geom:cube】'),
    # === 通用图表/数据可视化（放最后，优先级最低） ===
    (r'市场分析|数据分析|数据统计|统计图|数据可视化|matplotlib|数据图表', lambda m: '【chart:bar】'),
]


def _extract_chart_data(text: str, chart_type: str) -> Optional[dict]:
    """从 AI 回复文本中提取图表数据。

    支持以下格式（按优先级从高到低）：
    1. JSON 数据块：```json\n{"labels":["A","B"],"values":[10,20]}\n```
    2. Markdown 表格：| 月份 | 销量 |\n|---|---|\n| 1月 | 100 |
    3. 百分比格式：A占30%, B占25%, C占45%
    4. 纯文本列表：1月:100, 2月:200, 3月:150
    5. CSV 格式：A,10\nB,20\nC,30

    返回 {"labels": [...], "values": [...]} 或 None
    """
    if not text or not chart_type:
        return None
    # 仅对统计图表提取数据（几何体/函数图像不需要）
    if not chart_type.startswith('【chart:'):
        return None

    # ===== 1. JSON 数据块（最高优先级） =====
    for m in re.finditer(r'```(?:json)?\s*\n(.*?)```', text, re.DOTALL):
        try:
            obj = json.loads(m.group(1).strip())
            if isinstance(obj, dict):
                values = obj.get('values') or obj.get('value') or obj.get('data')
                labels = obj.get('labels') or obj.get('label') or obj.get('categories')
                if isinstance(values, list) and values:
                    if not isinstance(labels, list) or len(labels) != len(values):
                        labels = [f'项{i+1}' for i in range(len(values))]
                    num_values = []
                    for v in values:
                        try:
                            num_values.append(float(v))
                        except (TypeError, ValueError):
                            num_values.append(0)
                    return {'labels': [str(l) for l in labels], 'values': num_values}
        except (json.JSONDecodeError, TypeError):
            continue

    # ===== 2. Markdown 表格 =====
    # 修复：使用更宽松的正则，匹配所有包含 | 的行
    table_match = re.search(r'((?:^\|.*\|\n?)+)', text, re.MULTILINE)
    if not table_match:
        # 备用方案：直接按行分割
        lines = [l.strip() for l in text.strip().split('\n') if l.strip() and '|' in l]
    else:
        lines = [l.strip() for l in table_match.group(1).strip().split('\n') if l.strip()]

    if lines:
        # 过滤分隔行 |---|---|
        data_lines = [l for l in lines if not re.match(r'^\|[\s\-:|]+\|$', l)]
        if len(data_lines) >= 2:
            headers = [h.strip() for h in data_lines[0].strip('|').split('|')]
            rows = []
            for line in data_lines[1:]:
                cells = [c.strip() for c in line.strip('|').split('|')]
                rows.append(cells)
            if rows and len(headers) >= 2:
                labels = [r[0] for r in rows if r]
                values = []
                for r in rows:
                    if len(r) >= 2:
                        # 提取数字（去除千分位逗号、百分号、单位）
                        cleaned = r[1].replace(',', '').replace('%', '').replace('万', '0000')
                        num_match = re.search(r'[\d.]+', cleaned)
                        try:
                            values.append(float(num_match.group()) if num_match else 0)
                        except (ValueError, AttributeError):
                            values.append(0)
                if values:
                    return {'labels': labels, 'values': values}

    # ===== 3. 百分比格式（饼图优先）：A占30%, B占25% =====
    pct_matches = re.findall(r'([^\s,，、()%]+?)\s*(?:占|占比|为|比例|份额)\s*([\d.]+)\s*%', text)
    if len(pct_matches) >= 2:
        labels = [m[0].strip() for m in pct_matches]
        values = []
        for m in pct_matches:
            try:
                values.append(float(m[1]))
            except ValueError:
                values.append(0)
        return {'labels': labels, 'values': values}

    # ===== 4. 纯文本列表：1月:100, 2月:200 =====
    # 注意：冒号后只允许水平空白（空格/制表符），不允许换行，避免跨行误匹配
    list_matches = re.findall(r'([^\s,，、:：]+?)\s*[:：][ \t]*([\d.]+)(?![\d.])', text)
    if len(list_matches) >= 2:
        labels = [m[0].strip() for m in list_matches]
        values = []
        for m in list_matches:
            try:
                values.append(float(m[1]))
            except ValueError:
                values.append(0)
        return {'labels': labels, 'values': values}

    # ===== 5. CSV 格式：A,10\nB,20\nC,30 =====
    csv_lines = re.findall(r'^\s*([^\s,][^\s,\n]*?)\s*,\s*([\d.]+)\s*$', text, re.MULTILINE)
    if len(csv_lines) >= 2:
        labels = [m[0].strip() for m in csv_lines]
        values = []
        for m in csv_lines:
            try:
                values.append(float(m[1]))
            except ValueError:
                values.append(0)
        return {'labels': labels, 'values': values}

    return None


def _inject_func_plot_expr(html: str, plain_text: str) -> str:
    """检测输出中是否包含图表/几何体提及，做两件事：
    1. 在开头注入标记文本供前端检测
    2. 彻底隐藏所有 HTML 文件生成/打开相关内容（路径、命令、提示等）
    """
    if not plain_text:
        return html
    
    # ===== 第一步：检测图表/几何体类型 =====
    marker = None
    for pattern, builder in _CHART_PATTERNS:
        m = re.search(pattern, plain_text, re.IGNORECASE)
        if m:
            marker = builder(m)
            break
    
    # ===== 第二步：隐藏 HTML 文件相关内容（无论是否检测到图表都执行） =====
    # 隐藏内容列表：
    # - explorer xxx.html 命令行
    # - 已生成 xxx.html ...
    # - 用浏览器打开...
    # - 文件路径 .../xxx.html
    # - 已打开 xxx.html
    # - 绿色发光边框 / 粉色顶点 等HTML文件内的描述
    
    result = html
    
    # 隐藏 explorer 命令及其路径
    result = re.sub(
        r'(?:explorer|start)\s+[^\s<]*\.html[^\n。]*',
        '<span style="display:none;">\\g<0></span>',
        result,
        flags=re.IGNORECASE
    )
    
    # 隐藏"已生成 xxx.html"到句号结束
    result = re.sub(
        r'已生成[^。\n]*\.html[^。\n]*。?',
        '<span style="display:none;">\\g<0></span>',
        result
    )
    
    # 隐藏"已打开 xxx.html"到句号结束
    result = re.sub(
        r'已打开[^。\n]*\.html[^。\n]*。?',
        '<span style="display:none;">\\g<0></span>',
        result
    )
    
    # 隐藏"用浏览器打开"到句号结束
    result = re.sub(
        r'用浏览器打开[^。\n]*。?',
        '<span style="display:none;">\\g<0></span>',
        result
    )
    
    # 隐藏包含 .html 的文件路径（整行）
    result = re.sub(
        r'[A-Za-z]:\\[^\s<\n]*\.html[^\s<\n]*',
        '<span style="display:none;">\\g<0></span>',
        result
    )
    
    # 隐藏 xxx_plot.html / xxx_chart.html 等文件名（孤立出现的）
    result = re.sub(
        r'\b\w*[_\-](?:plot|chart|graph|cube|sphere|geom|shape)\w*\.html\b',
        '<span style="display:none;">\\g<0></span>',
        result,
        flags=re.IGNORECASE
    )
    
    # 隐藏"绿色发光边框 / 粉色顶点 / 自动旋转动画"等HTML内描述特征文本
    if marker and marker.startswith('【geom:'):
        result = re.sub(
            r'[绿色发光|粉色顶点|自动旋转|拖动旋转|点击切换][^。\n]*。?',
            '<span style="display:none;">\\g<0></span>',
            result
        )

    # ★ 隐藏文本中的图表/几何体标记（【chart:xxx】和【geom:xxx】）
    result = re.sub(
        r'【(chart|geom):(\w+)】',
        '<span style="display:none;">【\\1:\\2】</span>',
        result
    )

    # ===== 第三步：注入标记 + 数据（如果检测到） =====
    if marker:
        # ★ 从文本中提取图表数据
        chart_data = _extract_chart_data(plain_text, marker)
        if chart_data:
            # 将数据编码为 data-values 属性
            data_json = json.dumps(chart_data, ensure_ascii=False)
            data_attr = f' data-values="{data_json.replace(chr(34), "&quot;")}"'
            result = f'<div class="chart-marker" data-type="{marker}"{data_attr} style="display:none;width:0;height:0;overflow:hidden;">{marker}</div>' + result
            # ★ 发布图表检测事件
            try:
                EventBus.instance().publish(EventType.CHART_DETECTED, {
                    "marker": marker,
                    "data": chart_data,
                })
            except Exception:
                pass
        else:
            logger.info(f"[360章] 图表标记 【{marker}】 无可提取数据，跳过注入，防黑块")
    
    return result


def _sanitize_html(html: str) -> str:
    """★ v3.69: XSS 防护 — 移除危险的 HTML 标签和属性

    移除内容：
    - <script>...</script> 标签及内容
    - <iframe>、<object>、<embed>、<style> 标签
    - 所有 on* 事件属性（onclick, onerror, onload 等）
    - javascript: 协议的 URL

    保留内容：
    - 基本格式标签（<b>, <i>, <p>, <div>, <table> 等）
    - class, style, href, src 等安全属性
    - codeDiff 等特殊代码块
    """
    # 1. 移除 <script>...</script> 及内容
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # 2. 移除 <style>...</style> 及内容（防止 CSS 注入）
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # 3. 移除 <iframe>、<object>、<embed>、<applet> 标签（保留内容）
    html = re.sub(r'</?(iframe|object|embed|applet|meta|link|base)[^>]*>', '', html, flags=re.IGNORECASE)
    # 4. 移除所有 on* 事件属性（onclick, onerror, onload, onmouseover 等）
    html = re.sub(r'\s+on\w+\s*=\s*["\'][^"\']*["\']', '', html, flags=re.IGNORECASE)
    html = re.sub(r'\s+on\w+\s*=\s*[^\s>]+', '', html, flags=re.IGNORECASE)
    # 5. 移除 javascript: 协议的 URL
    html = re.sub(r'(href|src)\s*=\s*["\']javascript:[^"\']*["\']',
                  r'\1="#"', html, flags=re.IGNORECASE)
    # 6. 移除 data: 协议的 URL（防止 data:text/html 执行）
    html = re.sub(r'(src)\s*=\s*["\']data:text/html[^"\']*["\']',
                  r'\1="#"', html, flags=re.IGNORECASE)

    return html


def _render_codediff_blocks(html: str) -> str:
    """★ v3.69: codeDiff 块级渲染 — 整块标绿(新增)/标红(删除)

    将 ```codeDiff 代码块转换为带颜色的 diff 视图：
    - `+` 开头行 → 绿色背景（新增）
    - `-` 开头行 → 红色背景（删除）
    - ` ` 开头行 → 默认色（上下文）
    - 其他行 → 默认色

    支持两种 HTML 形式（官方库和备用方案产生的）：
    1. <pre><code class="language-codeDiff">...</code></pre>
    2. <pre><code class="language-codediff">...</code></pre>
    """
    def _process_diff_block(match):
        lang = match.group(1).lower()
        if lang not in ('codediff',):
            return match.group(0)

        code_html = match.group(2)
        # 反转义 HTML 实体（&amp; &lt; &gt;）以正确解析 +/- 前缀
        code_text = code_html.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')

        lines = code_text.split('\n')
        rendered_lines = []
        for line in lines:
            # 跳过空行
            if not line.strip():
                rendered_lines.append('<div style="padding:0 8px;min-height:18px;">&nbsp;</div>')
                continue
            if line.startswith('+'):
                # 新增行 — 绿色背景
                escaped = line[1:].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                rendered_lines.append(
                    f'<div style="padding:0 8px;background:#0d2818;color:Lemon.ACCENT_GREEN;border-left:3px solid Lemon.STATUS_ONLINE;">+{escaped}</div>'
                )
            elif line.startswith('-'):
                # 删除行 — 红色背景
                escaped = line[1:].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                rendered_lines.append(
                    f'<div style="padding:0 8px;background:#2d0d0d;color:Lemon.ACCENT_RED;border-left:3px solid Lemon.ACCENT_RED;">-{escaped}</div>'
                )
            elif line.startswith(' '):
                # 上下文行 — 默认色
                escaped = line[1:].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                rendered_lines.append(
                    f'<div style="padding:0 8px;color:#ccc;">&nbsp;{escaped}</div>'
                )
            else:
                # 其他行（如 diff 头 @@ ... @@）
                escaped = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                rendered_lines.append(
                    f'<div style="padding:0 8px;color:Lemon.ACCENT_BLUE;font-weight:bold;">{escaped}</div>'
                )

        return (
            '<div class="code-diff-block" style="'
            'font-family:Consolas,Monaco,monospace;font-size:13px;'
            'border:1px solid #333;border-radius:4px;overflow:auto;">'
            + ''.join(rendered_lines)
            + '</div>'
        )

    # 匹配 <pre><code class="language-codeDiff">...</code></pre>
    html = re.sub(
        r'<pre><code class="language-(codeDiff|codediff)">(.*?)</code></pre>',
        _process_diff_block,
        html,
        flags=re.DOTALL
    )
    return html


def markdown_to_html(text: str) -> str:
    """将 Markdown 文本转换为 HTML（使用 python-markdown 库）"""
    if not text:
        return ""
    
    # ★ 特殊可视化语言标记列表（保留原始 class，不进行代码高亮）
    # ★ v3.69: 新增 'codeDiff' — 块级渲染（整块标绿/标红）
    _VISUAL_LANGS = {'function-cards', 'matrix', 'sequence', 'dot-plot', 'function-plot',
                     'task-plan', 'file-diff', 'codeDiff', 'codediff'}
    
    # ★ 保护数学公式：在 markdown 处理前，将 $...$ 和 $$...$$ 替换为占位符
    # 这样 python-markdown 不会转义或破坏 LaTeX 表达式
    _math_placeholders = []
    def save_math(m):
        idx = len(_math_placeholders)
        _math_placeholders.append(m.group(0))
        return f'\x00MATH{idx}\x00'
    
    # 先保护 $$...$$（块级公式），再保护 $...$（行内公式）
    text = re.sub(r'\$\$(.+?)\$\$', save_math, text, flags=re.DOTALL)
    text = re.sub(r'\$([^\$\n]+?)\$', save_math, text)
    # 也保护 \(...\) 和 \[...\]
    text = re.sub(r'\\\((.+?)\\\)', save_math, text, flags=re.DOTALL)
    text = re.sub(r'\\\[(.+?)\\\]', save_math, text, flags=re.DOTALL)
    
    if _MARKDOWN_AVAILABLE:
        try:
            extensions = [
                'extra',           # 表格、脚注、属性列表等
                'tables',          # 表格支持
                'fenced_code',     # 围栏代码块
                'nl2br',           # 换行转<br>
                'sane_lists',      # 更智能的列表
                'admonition',      # 提示框
            ]
            
            html = md_lib.markdown(text, extensions=extensions, output_format='html5')
            
            # 后处理：对代码块应用高亮
            # ★ 但保留特殊可视化语言标记的代码块（不做高亮替换）
            def replace_code_block(m):
                lang = m.group(1) or ''
                code = m.group(2)
                # ★ 特殊可视化语言：保留原始 HTML，不做代码高亮
                if lang.lower() in _VISUAL_LANGS:
                    return m.group(0)  # 返回原始匹配，不做替换
                return _highlight_code(code, lang)
            
            html = re.sub(
                r'<pre><code class="language-([^"]*)">(.*?)</code></pre>',
                replace_code_block,
                html,
                flags=re.DOTALL
            )
            html = re.sub(
                r'<pre><code>(.*?)</code></pre>',
                lambda m: _highlight_code(m.group(1), ''),
                html,
                flags=re.DOTALL
            )
            
            # ★ 函数图像自动检测注入
            html = _inject_func_plot_expr(html, text)

            # ★ v3.69: codeDiff 块级渲染 — 整块标绿(新增)/标红(删除)
            html = _render_codediff_blocks(html)

            # ★ v3.69: XSS 防护 — 移除危险标签和属性
            html = _sanitize_html(html)

            # ★ 恢复数学公式占位符
            for i, math_expr in enumerate(_math_placeholders):
                html = html.replace(f'\x00MATH{i}\x00', math_expr)

            return html
        except Exception as e:
            print(f"[Markdown] 官方库渲染失败，使用备用方案: {e}")
    
    # ===== 备用方案：手动轻量转换 =====
    # 保存原始纯文本（用于函数图像检测）
    _original_text = text
    
    # 保护代码块
    code_blocks = []
    def save_code_block(m):
        idx = len(code_blocks)
        lang = m.group(1) if m.group(1) else ''
        code = m.group(2)
        code_blocks.append((lang, code))
        return f'\x00CODEBLOCK{idx}\x00'
    
    text = re.sub(r'```(\w*)\n(.*?)```', save_code_block, text, flags=re.DOTALL)
    
    # 保护行内代码
    inline_codes = []
    def save_inline_code(m):
        idx = len(inline_codes)
        inline_codes.append(m.group(1))
        return f'\x00INLINECODE{idx}\x00'
    
    text = re.sub(r'`([^`]+)`', save_inline_code, text)
    
    # 转义 HTML 特殊字符
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    
    # 标题
    text = re.sub(r'^######\s+(.+)$', r'<h6>\1</h6>', text, flags=re.MULTILINE)
    text = re.sub(r'^#####\s+(.+)$', r'<h5>\1</h5>', text, flags=re.MULTILINE)
    text = re.sub(r'^####\s+(.+)$', r'<h4>\1</h4>', text, flags=re.MULTILINE)
    text = re.sub(r'^###\s+(.+)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)
    text = re.sub(r'^##\s+(.+)$', r'<h2>\1</h2>', text, flags=re.MULTILINE)
    text = re.sub(r'^#\s+(.+)$', r'<h1>\1</h1>', text, flags=re.MULTILINE)
    
    # 粗体和斜体
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<b><i>\1</i></b>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
    text = re.sub(r'___(.+?)___', r'<b><i>\1</i></b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)
    text = re.sub(r'_(.+?)_', r'<i>\1</i>', text)
    
    # 行内代码（恢复）
    for i, code in enumerate(inline_codes):
        safe = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        text = text.replace(f'\x00INLINECODE{i}\x00', 
            f'<code class="inline-code">{safe}</code>')
    
    # 代码块（恢复）
    # ★ 特殊可视化语言标记列表（保留原始 class，不进行代码高亮）
    # ★ v3.69: 新增 'codeDiff'
    _VISUAL_LANGS_FALLBACK = {'function-cards', 'matrix', 'sequence', 'dot-plot', 'function-plot',
                              'task-plan', 'file-diff', 'codeDiff', 'codediff'}
    for i, (lang, code) in enumerate(code_blocks):
        if lang.lower() in _VISUAL_LANGS_FALLBACK:
            # ★ 保留原始 class 标记，不做代码高亮（供前端渲染）
            safe = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            text = text.replace(f'\x00CODEBLOCK{i}\x00',
                f'<pre><code class="language-{lang}">{safe}</code></pre>')
        else:
            highlighted = _highlight_code(code, lang)
            text = text.replace(f'\x00CODEBLOCK{i}\x00', highlighted)
    
    # 无序列表
    text = re.sub(r'^[\-\*\+]\s+(.+)$', r'<li>\1</li>', text, flags=re.MULTILINE)
    
    # 有序列表
    text = re.sub(r'^(\d+)\.\s+(.+)$', r'<li>\2</li>', text, flags=re.MULTILINE)
    
    # 包裹列表（简单处理：连续 li 包裹成 ul/ol）
    lines = text.split('\n')
    result_lines = []
    in_list = False
    list_type = 'ul'
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('<li>'):
            if not in_list:
                # 判断是有序还是无序列表
                if i > 0 and re.match(r'^\d+\.', lines[i-1].strip()):
                    list_type = 'ol'
                else:
                    list_type = 'ul'
                result_lines.append(f'<{list_type}>')
                in_list = True
            result_lines.append(line)
        else:
            if in_list:
                result_lines.append(f'</{list_type}>')
                in_list = False
            result_lines.append(line)
        i += 1
    if in_list:
        result_lines.append(f'</{list_type}>')
    text = '\n'.join(result_lines)
    
    # 水平线
    text = re.sub(r'^---+\s*$', '<hr>', text, flags=re.MULTILINE)
    text = re.sub(r'^\*\*\*+\s*$', '<hr>', text, flags=re.MULTILINE)
    
    # 引用
    text = re.sub(r'^&gt;\s+(.+)$', r'<blockquote>\1</blockquote>', text, flags=re.MULTILINE)
    
    # Markdown 表格
    lines = text.split('\n')
    result_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if '|' in line and i + 1 < len(lines) and re.match(r'^\s*\|[\s\-:|]+\|\s*$', lines[i + 1]):
            headers = [h.strip() for h in line.split('|')[1:-1]]
            i += 2
            rows = []
            while i < len(lines) and '|' in lines[i]:
                cells = [c.strip() for c in lines[i].split('|')[1:-1]]
                if cells:
                    rows.append(cells)
                i += 1
            table_html = '<table class="md-table">'
            table_html += '<thead><tr>'
            for h in headers:
                table_html += f'<th>{h}</th>'
            table_html += '</tr></thead><tbody>'
            for row_idx, row in enumerate(rows):
                table_html += '<tr>'
                for cell in row:
                    table_html += f'<td>{cell}</td>'
                table_html += '</tr>'
            table_html += '</tbody></table>'
            result_lines.append(table_html)
        else:
            result_lines.append(line)
            i += 1
    text = '\n'.join(result_lines)
    
    # 换行
    text = text.replace('\n', '<br>')
    
    # ★ 函数图像自动检测注入
    text = _inject_func_plot_expr(text, _original_text)

    # ★ v3.69: codeDiff 块级渲染（备用方案路径）
    text = _render_codediff_blocks(text)

    # ★ v3.69: XSS 防护（备用方案路径）
    text = _sanitize_html(text)

    # ★ 恢复数学公式占位符（备用方案也需要恢复）
    for i, math_expr in enumerate(_math_placeholders):
        text = text.replace(f'\x00MATH{i}\x00', math_expr)

    return text

# Lemon Code 可执行文件路径
# ★ v3.72: 修正MIMO路径，指向本地 lemon_agent/bin/mimo.exe
_LEMON_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # standard_mode/core → 3级 = lemon_agent
MIMO_EXE = os.path.join(_LEMON_ROOT, "bin", "mimo.exe")
# 备用路径（当本地 mimo.exe 不存在时）
if not os.path.exists(MIMO_EXE):
    _ALT_ROOT = os.path.expanduser(r"~\AppData\Local\Programs\@mimo-ai\mimocode-windows-x64")
    MIMO_EXE = os.path.join(_ALT_ROOT, "bin", "mimo.exe")
MIMO_EXE_ALT = MIMO_EXE  # 备用路径与主路径一致
SERVE_PORT = 4097  # ★ v3.28: mimo serve 固定监听 4097（恢复备份版配置）
SERVE_URL = f"http://127.0.0.1:{SERVE_PORT}"


class MIMOServeBridge(QObject):
    """
    Lemon Serve 双向通信桥
    
    - 底层：mimo serve 子进程（HTTP API + SSE）
    - 上层：Qt 信号驱动 UI 更新
    """
    
    # ==================== 输出信号 ====================
    output_received = pyqtSignal(str)      # 完整输出（HTML）
    delta_received = pyqtSignal(str)       # 增量文本（纯文本，用于底部终端行内追加）
    thinking_received = pyqtSignal(str)    # 思考过程（HTML）
    thinking_step_received = pyqtSignal(str, str, dict, float)
    tool_card_received = pyqtSignal(dict)
    status_received = pyqtSignal(str)      # 状态消息
    error_occurred = pyqtSignal(str)       # 错误
    tool_output = pyqtSignal(str)          # 工具输出
    file_preview = pyqtSignal(str)         # v3.90: 文件预览（HTML iframe/图像/代码内嵌）
    serve_log = pyqtSignal(str)            # serve 进程日志

    # ★ 流式输出专用信号
    stream_started = pyqtSignal()            # 流式输出开始
    stream_token = pyqtSignal(str)           # 流式 token（纯文本）
    stream_ended = pyqtSignal(str)           # 流式结束（参数=完整文本）
    stream_error = pyqtSignal(str)           # 流式错误/中断
    
    # ==================== 交互信号 ====================
    config_options_received = pyqtSignal(str, list)
    permission_requested = pyqtSignal(str, object, list)
    mode_changed = pyqtSignal(str)
    
    # ==================== 状态信号 ====================
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    connection_error = pyqtSignal(str)
    task_started = pyqtSignal(str)
    task_finished = pyqtSignal(bool, str)
    queue_updated = pyqtSignal(int, list)  # (队列长度, 任务列表)
    
    # ==================== 会话/用量信号 ====================
    session_created = pyqtSignal(str)      # session_id
    usage_info = pyqtSignal(object)
    file_changed = pyqtSignal(str, str, object)  # (file_path, change_type, diff_info)
    file_status = pyqtSignal(str, str)  # v3.82-F5: (file_path, status: "writing"/"done"/"failed")
    
    def __init__(self, project_path: str = None, port: int = SERVE_PORT):
        super().__init__()
        self.project_path = os.path.abspath(project_path or os.getcwd())
        self.port = port
        self.base_url = f"http://127.0.0.1:{port}"
        
        # 进程管理
        self._process = None
        self._serve_thread = None
        self._sse_thread = None
        self._running = False
        self._connected = False
        
        # 会话
        self._session_id: Optional[str] = None
        self._pending_messages: list = []
        self._tool_shown: dict = {}  # 跟踪已显示的工具调用，避免重复
        self._last_updated_text: str = ""  # 跟踪上次 updated 文本，避免重复

        # ★ 流式输出状态
        self._streaming: bool = False       # 是否正在流式输出
        self._stream_buffer: str = ""       # 流式累积的完整文本
        self._stream_first_token: bool = True  # 是否是第一个 token
        
        # ★ P12: 交互日志 — 蒸馏数据管道
        self._interaction_logger = None
        try:
            self._interaction_logger = get_interaction_logger()
        except Exception:
            pass
        
        # 任务队列（排队回答功能）
        self._task_queue: list = []  # 待执行的任务列表
        self._is_processing: bool = False  # 是否正在处理任务
        self._current_task: Optional[str] = None  # 当前正在处理的任务
        self._send_lock = threading.Lock()  # ★ P13: 防止竞态条件（B1修复）
        
        # 信任模式（自动同意权限请求）
        self._trust_mode = False  # 是否启用信任模式
        self._auto_approve_tools = set()  # 自动同意的工具类型集合
        self._permission_history = []  # 权限请求历史
        
        # ★ v3.58: MIMO模式下禁止自动切换到Ollama
        self._auto_fallback_disabled = True
        
        # ★ v3.58: Process Bridge 作为主要通信方式
        self._process_bridge = None
        if _PROCESS_BRIDGE_AVAILABLE:
            # ★ v3.72: 启用 STDIO 持久化模式 — 一个 Node.js 进程持续通信，不再每次新建子进程
            self._process_bridge = MIMOProcessBridge(
                project_path=self.project_path,
                use_stdio_bridge=True
            )
            self._connect_process_bridge_signals()
            if not self._process_bridge.start():
                # STDIO 模式启动失败，回退到直接模式
                print("[ServeBridge] STDIO 模式启动失败，回退到直接模式", flush=True)
                self._process_bridge = MIMOProcessBridge(
                    project_path=self.project_path,
                    use_stdio_bridge=False
                )
                self._connect_process_bridge_signals()
                self._process_bridge.start()
            print(f"[ServeBridge] Process Bridge 已启动 (主要通信)", flush=True)
        
        # ★ v3.58: ACP Bridge 作为备用通信方式（完整夺舍）
        self._acp_bridge = None
        if _ACP_BRIDGE_AVAILABLE:
            self._acp_bridge = ACPBridge(project_path=self.project_path)
            self._connect_acp_bridge_signals()
            print(f"[ServeBridge] ACP Bridge 已就绪 (备用通信)", flush=True)
        
        # ★ v3.71: PTY Bridge 作为第三备选通信方式（伪终端）
        self._pty_bridge = None
        if _PTY_BRIDGE_AVAILABLE:
            self._pty_bridge = PTYBridge(project_path=self.project_path)
            self._connect_pty_bridge_signals()
            print(f"[ServeBridge] PTY Bridge 已就绪 (第三备选)", flush=True)
        
        # ★ v3.54: 智能桥接路由器
        self._bridge_router = None
        if _ROUTER_AVAILABLE:
            self._bridge_router = IntelligentBridgeRouter()
            self._setup_bridge_router()
            print(f"[ServeBridge] IntelligentBridgeRouter 已就绪", flush=True)
        
        # SSE
        self._sse_stop = threading.Event()
        
        # ★ 会话验证缓存（避免每次发送都验证）
        self._last_session_check = 0  # 上次验证时间戳
        self._session_check_interval = 30  # 会话验证间隔（秒）
        self._session_known_good = False  # 已知会话良好（最近验证过）
        
        # ★ 进程崩溃检测和消息重发
        self._last_message: Optional[str] = None  # 最后一条消息（用于崩溃后重发）
        self._crash_count = 0  # 崩溃计数
        self._max_crash_retries = 3  # 最大崩溃重试次数

        # ★ 快照管理器 + 事件总线 + 消息存储
        self._snapshot_mgr = SnapshotManager(self.project_path)
        self._event_bus = EventBus.instance()
        self._last_snapshot_id: Optional[str] = None  # 最近一次快照ID（供前端回退用）
        self._message_store = MessageStore()  # SQLite 消息持久化
        self._db_session_id: Optional[str] = None  # 当前数据库会话ID

        # ★ Ollama 自动检测 + 模型管理
        self._ollama_detector = OllamaAutoDetector()
        self._ollama_mgr = OllamaModelManager()
        self._ollama_status: Optional[dict] = None  # 缓存检测结果
        self._ollama_check_timer = QTimer()
        self._ollama_check_timer.timeout.connect(self._check_ollama_status)
        self._ollama_check_timer.start(60000)  # 每60秒检测一次
        # 启动时立即检测一次
        QTimer.singleShot(2000, self._check_ollama_status)

        # ★ 内置 Skill：代码格式化 + 代码审查
        self._formatter = CodeFormatterSkill()
        self._reviewer = CodeReviewSkill()

        # ★ 崩溃恢复
        self._crash_recovery = CrashRecovery()
        self._crash_recovery.install_excepthook()
        self._crash_recovery.install_threading_excepthook()
        self._reconnect_attempts = 0
        self._max_reconnect_delay = 60  # 最大重连间隔（秒）

        # ★ 新增：HTTP 连接池、超时配置、重试配置
        self._conn_pool = ConnectionPool(max_pool_size=10, max_retries=3)
        self._timeout_config = TimeoutConfig()
        self._retry_config = RetryConfig(
            max_retries=3,
            base_delay=1.0,
            max_delay=30.0,
        )
        # ★ 新增：崩溃恢复状态持久化
        self._crash_state_file = os.path.join(
            os.path.expanduser("~"), ".mimo_agent", "crash_state.json"
        )
        self._save_crash_state()  # 初始化时保存状态

        # ★ 性能优化：消息合并器、Git 缓存、日志轮转、AI 超时
        self._msg_batcher = MessageBatcher(
            flush_callback=self._flush_batched_messages,
            window_ms=100,
            max_size=50,
        )
        self._git_cache = GitStatusCache(ttl=5.0)
        self._log_rotator = LogRotator(
            log_file=os.path.join(os.path.expanduser("~"), ".mimo_agent", "logs", "mimo_agent.log"),
            max_bytes=10 * 1024 * 1024,  # 10MB
            backup_count=3,
        )
        self._logger = self._log_rotator.get_logger()
        self._ai_timeout: float = 30.0  # AI 请求超时（秒）
        self._ai_timeout_timer: Optional[QTimer] = None
        # 日志轮转定时检查（每 5 分钟）
        self._log_rotate_timer = QTimer()
        self._log_rotate_timer.timeout.connect(self._log_rotator.check_and_rotate)
        self._log_rotate_timer.start(300000)
        # 归档定时器（每小时检查一次老消息归档）
        self._archive_timer = QTimer()
        self._archive_timer.timeout.connect(self._archive_old_messages)
        self._archive_timer.start(3600000)
        # 启动时延迟执行一次归档
        QTimer.singleShot(10000, self._archive_old_messages)
        
        # ★ v3.57: 通信模式（默认 stdio，HTTP 作为备用）
        self.communication_mode = COMMUNICATION_MODE_STDIO
        self._stdio_enabled = False  # stdio 是否已成功初始化
        
        # ★ v3.57: 上下文管理器
        self._context_manager = ContextManager(max_history=20)
        self._context_manager.set_system_prompt(
            "你是一个专业的 AI 编程助手，名为 Lemon Code。"
            "请用简洁清晰的中文回答用户的问题，专注于代码和软件开发相关的话题。"
        )
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    @property
    def is_connected(self) -> bool:
        return self._connected
    
    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    # ================================================================
    # ★ HTTP 请求辅助方法（使用连接池 + 重试 + 超时配置）
    # ================================================================

    def _http_get(self, path: str, timeout: float = None,
                  endpoint: str = "default") -> requests.Response:
        """发送 GET 请求（使用连接池复用 + 自动重试）
        
        Args:
            path: API 路径（如 "/global/health"）
            timeout: 超时时间（秒），默认使用 TimeoutConfig 配置
            endpoint: 端点类型（用于查找对应的超时配置）
        """
        if timeout is None:
            timeout = self._timeout_config.get(endpoint)
        session = self._conn_pool.get_session()
        return session.get(f"{self.base_url}{path}", timeout=timeout)

    def _http_post(self, path: str, json_data: dict = None,
                   timeout: float = None, endpoint: str = "default") -> requests.Response:
        """发送 POST 请求（使用连接池复用 + 自动重试）
        
        Args:
            path: API 路径
            json_data: JSON 请求体
            timeout: 超时时间（秒）
            endpoint: 端点类型
        """
        if timeout is None:
            timeout = self._timeout_config.get(endpoint)
        session = self._conn_pool.get_session()
        return session.post(f"{self.base_url}{path}", json=json_data, timeout=timeout)

    def _http_request_with_retry(self, method: str, path: str,
                                  json_data: dict = None, timeout: float = None,
                                  endpoint: str = "default") -> Optional[requests.Response]:
        """带重试的 HTTP 请求（对可恢复错误自动重试）
        
        Returns:
            成功时返回 Response 对象，全部失败时返回 None
        """
        last_error = None
        for attempt in range(self._retry_config.max_retries + 1):
            try:
                if method == "GET":
                    resp = self._http_get(path, timeout, endpoint)
                else:
                    resp = self._http_post(path, json_data, timeout, endpoint)
                
                if resp.status_code in self._retry_config.retryable_statuses:
                    if attempt < self._retry_config.max_retries:
                        delay = min(
                            self._retry_config.base_delay * (self._retry_config.backoff_factor ** attempt),
                            self._retry_config.max_delay
                        )
                        self._logger.warning(f"HTTP {resp.status_code} on {path}, retry in {delay:.1f}s")
                        time.sleep(delay)
                        continue
                return resp
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout) as e:
                last_error = e
                if attempt < self._retry_config.max_retries:
                    delay = min(
                        self._retry_config.base_delay * (self._retry_config.backoff_factor ** attempt),
                        self._retry_config.max_delay
                    )
                    self._logger.warning(f"{type(e).__name__} on {path}, retry in {delay:.1f}s")
                    time.sleep(delay)
                else:
                    self._logger.error(f"All retries exhausted for {path}: {e}")
                    return None
        
        if last_error:
            self._logger.error(f"Request failed after {self._retry_config.max_retries} retries: {last_error}")
        return None

    # ================================================================
    # ★ 崩溃恢复状态持久化
    # ================================================================

    def _save_crash_state(self):
        """保存崩溃恢复状态到文件"""
        try:
            state = {
                "session_id": self._session_id,
                "last_message": self._last_message,
                "crash_count": self._crash_count,
                "connected": self._connected,
                "timestamp": datetime.now().isoformat(),
            }
            os.makedirs(os.path.dirname(self._crash_state_file), exist_ok=True)
            with open(self._crash_state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[CrashState] 保存失败: {e}", flush=True)

    def _load_crash_state(self) -> Optional[dict]:
        """从文件加载崩溃恢复状态"""
        try:
            if os.path.exists(self._crash_state_file):
                with open(self._crash_state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"[CrashState] 加载失败: {e}", flush=True)
        return None

    def _restore_from_crash(self):
        """从崩溃状态恢复会话"""
        state = self._load_crash_state()
        if not state:
            return
        saved_session = state.get("session_id")
        if saved_session and saved_session != self._session_id:
            self._session_id = saved_session
            self._last_message = state.get("last_message")
            self._crash_count = state.get("crash_count", 0)
            self._logger.info(f"已从崩溃状态恢复会话: {saved_session[:16]}...")
            self.status_received.emit(
                f"<span style='color:Lemon.ACCENT_ORANGE;'>{{ICON:triangle-alert}} 已从崩溃恢复会话</span>"
            )
            # 重发最后一条消息
            if self._last_message:
                self._logger.info(f"重发崩溃前的最后一条消息")
                QTimer.singleShot(3000, lambda: self.send_message(self._last_message))

    # ================================================================
    # ★ 性能优化方法
    # ================================================================

    def _flush_batched_messages(self, items: list):
        """批量消息刷新回调：将合并后的消息一次性发送到前端"""
        if not items:
            return
        try:
            # 合并所有文本
            combined = "".join(str(it) for it in items)
            if combined:
                self._event_bus.publish(EventType.MESSAGE_DELTA, combined)
        except Exception as e:
            print(f"[ServeBridge] 批量消息刷新错误: {e}", flush=True)

    def _archive_old_messages(self):
        """定时归档老消息（超过30天）"""
        try:
            if self._message_store:
                count = self._message_store.archive_old_messages(days=30)
                if count > 0:
                    self._logger.info(f"归档 {count} 条老消息")
        except Exception as e:
            print(f"[ServeBridge] 归档失败: {e}", flush=True)

    def _start_ai_timeout(self):
        """启动 AI 请求超时定时器（30秒无响应自动断开，线程安全）"""
        import threading
        if threading.current_thread() is not threading.main_thread():
            from PyQt5.QtCore import QMetaObject, Qt
            QMetaObject.invokeMethod(self, "_start_ai_timeout", Qt.QueuedConnection)
            return
        self._stop_ai_timeout()
        self._ai_timeout_timer = QTimer()
        self._ai_timeout_timer.setSingleShot(True)
        self._ai_timeout_timer.timeout.connect(self._on_ai_timeout)
        self._ai_timeout_timer.start(int(self._ai_timeout * 1000))

    def _stop_ai_timeout(self):
        """停止 AI 超时定时器（★ 必须在 __init__ 早期也可安全调用）"""
        _t = getattr(self, "_ai_timeout_timer", None)
        if _t is not None:
            try:
                _t.stop()
                _t.deleteLater()
            except Exception:
                pass
            self._ai_timeout_timer = None

    def _on_ai_timeout(self):
        """AI 请求超时处理 — 自动回退到 Ollama（仅在自动模式下）"""
        self._logger.warning(f"AI 请求超时（{self._ai_timeout}s 无响应）")
        # ★ v3.51: 检查是否禁用了自动回退
        if getattr(self, '_auto_fallback_disabled', False):
            self._logger.warning("自动回退已禁用，不切换到 Ollama")
            self._event_bus.publish(EventType.STATUS_UPDATE, {
                "type": "error",
                "message": f"AI 响应超时（{self._ai_timeout}s）。当前为 MIMO 模式，不会自动切换。",
            })
            self.error_occurred.emit(
                f"AI 响应超时（{self._ai_timeout}s）。当前为 MIMO 模式，不会自动切换到 Ollama。"
            )
            self._streaming = False
            self._is_processing = False
            self._current_task = None
            self._stop_ai_timeout()
            QTimer.singleShot(500, self._process_next_task)
            return

        self._event_bus.publish(EventType.STATUS_UPDATE, {
            "type": "warning",
            "message": f"AI 响应超时（{self._ai_timeout}s），正在切换到 Ollama...",
        })
        # ★ v3.50: 超时后尝试 Ollama 回退
        if self._current_task:
            last_msg = self._current_task
            self._streaming = False
            self._is_processing = False
            self._current_task = None
            self._stop_ai_timeout()
            # 在后台线程执行 Ollama 回退
            threading.Thread(
                target=self._try_ollama_fallback,
                args=(last_msg,),
                daemon=True
            ).start()
        else:
            # 重置流式状态
            self._streaming = False
            self._is_processing = False
            self._current_task = None
            # 处理队列中的下一个任务
            QTimer.singleShot(500, self._process_next_task)

    def get_git_status_cached(self) -> str:
        """获取 git status（带5秒缓存）"""
        def _compute():
            try:
                result = subprocess.run(
                    ["git", "status", "--porcelain"],
                    capture_output=True, text=True, timeout=5,
                    encoding="utf-8", errors="replace",
                    cwd=self.project_path,
                )
                return result.stdout if result.returncode == 0 else ""
            except Exception:
                return ""
        return self._git_cache.get_or_compute(self.project_path, _compute)

    # ================================================================
    # 启动/停止
    # ================================================================
    
    def _cleanup_stale_serve(self):
        """★ 清理残留的 mimo serve 进程（防止端口占用）"""
        try:
            import subprocess
            # 检查端口4097是否被占用
            _cf = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            result = subprocess.run(
                ["netstat", "-ano"],
                stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=5,
                encoding="utf-8", errors="replace",
                creationflags=_cf,
            )
            for line in result.stdout.split('\n'):
                if ':4097' in line and 'LISTENING' in line:
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        pid = parts[4]
                        # 检查是否是 mimo.exe 进程
                        task_result = subprocess.run(
                            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                            stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=5,
                            encoding="utf-8", errors="replace",
                            creationflags=_cf,
                        )
                        if 'mimo.exe' in task_result.stdout:
                            print(f"[CLEANUP] 终止占用端口4097的残留 mimo 进程: PID={pid}", flush=True)
                            subprocess.run(["taskkill", "/F", "/PID", pid],
                                           stdin=subprocess.DEVNULL,
                                           capture_output=True, timeout=5,
                                           creationflags=_cf)
                            time.sleep(1)  # 等待端口释放
                        break
        except Exception as e:
            print(f"[CLEANUP] 清理失败: {e}", flush=True)
    
    def start(self) -> bool:
        """启动 mimo serve 并建立连接"""
        if self._running:
            return True
        
        # ★ v3.26: 先检查是否已有 serve 在运行（避免误杀正在运行的进程）
        if self._check_existing_serve():
            self.status_received.emit("发现已运行的 mimo serve，直接连接...")
            self._on_serve_ready()
            return True
        
        # ★ 清理残留进程（防止上次崩溃后端口占用）
        self._cleanup_stale_serve()
        
        # ★ 优化的路径查找逻辑（3级优先级）
        exe_path = None

        # 优先级1：向上逐级查找 bin/mimo.exe（适配嵌套目录结构）
        current = os.path.dirname(os.path.abspath(__file__))
        for _ in range(5):  # 最多向上查找5级
            parent = os.path.dirname(current)
            if parent == current:
                break
            bin_exe = os.path.join(parent, "bin", "mimo.exe")
            if os.path.exists(bin_exe):
                exe_path = bin_exe
                self.serve_log.emit(f"<span style='color:Lemon.ACCENT_GREEN;'>{{ICON:check}} 使用项目 bin 目录: {bin_exe}</span>")
                break
            current = parent
        
        # 优先级2：Lemon AI 目录
        if not exe_path and os.path.exists(MIMO_EXE):
            exe_path = MIMO_EXE
            self.serve_log.emit(f"<span style='color:Lemon.ACCENT_GREEN;'>{{ICON:check}} 使用 Lemon AI 目录: {MIMO_EXE}</span>")

        # 优先级3：系统 PATH
        if not exe_path:
            try:
                import shutil
                exe_path = shutil.which("mimo.exe")
                if exe_path:
                    self.serve_log.emit(f"<span style='color:Lemon.ACCENT_GREEN;'>{{ICON:check}} 从系统 PATH 找到: {exe_path}</span>")
            except Exception:
                pass
        
        # 未找到可执行文件
        if not exe_path:
            self.error_occurred.emit("找不到 mimo.exe（尝试了项目 bin、Lemon AI 目录、系统 PATH）")
            return False
        
        # ★ 保存路径供 _run_serve 使用
        self._exe_path = exe_path
        
        self._running = True
        
        # 1. 启动新的 mimo serve 进程
        self._serve_thread = threading.Thread(target=self._run_serve, daemon=True)
        self._serve_thread.start()
        
        # 3. 等待服务就绪
        threading.Thread(target=self._wait_for_serve, daemon=True).start()
        
        return True
    
    def stop(self):
        """停止 mimo serve"""
        self._running = False
        self._connected = False
        self._sse_stop.set()

        # ★ 保存崩溃恢复状态
        self._save_crash_state()

        # ★ 性能优化：停止消息合并器、超时定时器、归档定时器
        self._stop_ai_timeout()
        try:
            self._msg_batcher.close()
        except Exception:
            pass
        try:
            self._log_rotate_timer.stop()
        except Exception:
            pass
        try:
            self._archive_timer.stop()
        except Exception:
            pass
        # ★ 新增：关闭 HTTP 连接池
        try:
            self._conn_pool.close()
        except Exception:
            pass

        # 停止轮询定时器
        if hasattr(self, '_poll_timer'):
            self._poll_timer.stop()

        # 终止 serve 进程
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None

        self.disconnected.emit()
    
    def _check_existing_serve(self) -> bool:
        """检查是否已有 mimo serve 在运行"""
        try:
            r = requests.get(f"{self.base_url}/global/health", timeout=3)
            if r.status_code == 200 and r.json().get("healthy"):
                return True
        except Exception:
            pass
        return False
    
    def _run_serve(self):
        """在后台线程运行 mimo serve"""
        import subprocess
        
        # ★ 使用动态路径（优先级已确定）
        exe_path = self._exe_path if hasattr(self, '_exe_path') else MIMO_EXE
        
        cmd = [
            exe_path, "serve",
            "--port", str(self.port),
            "--print-logs",
        ]
        
        self.serve_log.emit(f"$ {' '.join(cmd)}")
        
        try:
            self._process = subprocess.Popen(
                cmd,
                # ★ Lemon Work: pythonw 启动时父进程无控制台，子进程若继承无效句柄
                #   会尝试自建控制台并可能以 0xc0000142 失败；显式 DEVNULL + 无窗口启动
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=self.project_path,
                text=True,
                encoding="utf-8", errors="replace",
                bufsize=1,
                creationflags=(subprocess.CREATE_NO_WINDOW
                               if os.name == "nt" else 0),
            )
            
            # 读取进程输出
            for line in self._process.stdout:
                if not self._running:
                    break
                line = line.rstrip()
                if line:
                    self.serve_log.emit(line)
            
            return_code = self._process.wait()
            
            # ★ 进程崩溃检测（非正常退出）
            if return_code != 0 and self._running:
                self._crash_count += 1
                self.serve_log.emit(
                    f"[ERROR] Lemon Code 进程崩溃 (退出码: {return_code}, 第{self._crash_count}次)"
                )
                # ★ 保存崩溃状态
                self._save_crash_state()
                
                # 崩溃后自动重启
                if self._crash_count <= self._max_crash_retries:
                    self.serve_log.emit(
                        f"[RECOVERY] 正在重启 Lemon Code (尝试 {self._crash_count}/{self._max_crash_retries})..."
                    )
                    time.sleep(2)  # 等待2秒后重启
                    
                    # 重新启动
                    self._process = None
                    self._serve_thread = threading.Thread(target=self._run_serve, daemon=True)
                    self._serve_thread.start()
                    threading.Thread(target=self._wait_for_serve, daemon=True).start()
                    
                    # 重发最后一条消息
                    if self._last_message:
                        self.serve_log.emit(
                            f"[RECOVERY] 重发最后一条消息: {self._last_message[:50]}..."
                        )
                        QTimer.singleShot(5000, lambda: self.send_message(self._last_message))
                else:
                    self.serve_log.emit(
                        f"[FATAL] Lemon Code 崩溃次数超过限制 ({self._max_crash_retries})，停止重试"
                    )
                    self.connection_error.emit("Lemon Code 进程反复崩溃，请检查日志文件")
                    
                    # ★ 自动切换到 CLI 模式
                    self.switch_to_cli_mode()
            
        except Exception as e:
            self.serve_log.emit(f"[ERROR] serve 启动失败: {e}")
            self.connection_error.emit(str(e))
    
    def _wait_for_serve(self):
        """等待 mimo serve 就绪

        ★ 卡顿修复（2026-08-28）: 原实现无条件轮询 30 秒。运行日志实锤：
        4097 端口有服务但 /global/health 返回 404（路由不存在）时，
        永远等不到 200，却仍每秒空轮询 30 次（每次新建 HTTP 连接 + DEBUG 日志刷屏）。
        现在: 连续 3 次 404 视为"端口被不兼容服务占用"，提前放弃等待。
        """
        not_found_streak = 0
        for i in range(30):  # 最多等30秒
            if not self._running:
                return
            time.sleep(1)
            try:
                r = requests.get(f"{self.base_url}/global/health", timeout=2)
                if r.status_code == 200 and r.json().get("healthy"):
                    self._on_serve_ready()
                    return
                if r.status_code == 404:
                    not_found_streak += 1
                    if not_found_streak >= 3:
                        # 端口有 HTTP 服务但无 /global/health 路由 → 不兼容的
                        # 服务占用（旧版 mimo serve / 其他进程），继续等待无意义
                        self.serve_log.emit(
                            "<span style='color:Lemon.ACCENT_ORANGE;'>{ICON:triangle-alert} "
                            "端口 4097 存在不兼容服务（/global/health 404），跳过 HTTP 就绪等待，"
                            "继续使用 Process Bridge 通道</span>"
                        )
                        return
            except Exception:
                pass

        self._running = False
        self.connection_error.emit("mimo serve 启动超时")
    
    def _on_serve_ready(self):
        """mimo serve 就绪后初始化"""
        self._connected = True
        self._crash_count = 0  # ★ 成功连接后重置崩溃计数
        self.connected.emit()
        
        # ★ 检测 Lemon Code 版本，验证 API 兼容性
        self._check_version_compatibility()
        
        # ★ 尝试从崩溃状态恢复
        self._restore_from_crash()
        
        # 创建或恢复会话
        try:
            self._create_or_resume_session()
        except Exception as e:
            self.error_occurred.emit(f"创建会话失败: {e}")
        
        # ★ 关键修复：先启动 SSE 监听，再发送缓存消息
        # 之前 SSE 监听器通过 singleShot(0) 延迟启动，导致 flush 时监听器尚未就绪，
        # 第一条消息的响应事件会丢失
        self._start_sse_listener()
        
        # SSE 监听器已启动，现在发送缓存消息
        self._flush_pending_messages()
        
        # ★ 保存崩溃恢复状态
        self._save_crash_state()
    
    def switch_to_cli_mode(self):
        """★ 切换到 CLI 模式（当 HTTP API 不稳定时）"""
        self.status_received.emit(
            "<span style='color:Lemon.ACCENT_ORANGE;'>{ICON:triangle-alert} HTTP API 不稳定，切换到 CLI 模式...</span>"
        )
        
        # 停止 HTTP API
        self.stop()
        
        # 启动 CLI 模式
        try:
            from core.cli_bridge import MIMOCLIBridge
            self._cli_bridge = MIMOCLIBridge()
            self._cli_bridge.output_received.connect(self.output_received.emit)
            self._cli_bridge.error_occurred.connect(self.error_occurred.emit)
            self._cli_bridge.connected.connect(self.connected.emit)
            
            if self._cli_bridge.start():
                self.status_received.emit(
                    "<span style='color:Lemon.ACCENT_GREEN;'>{ICON:check} CLI 模式已启用</span>"
                )
            else:
                self.error_occurred.emit("CLI 模式启动失败")
        except Exception as e:
            self.error_occurred.emit(f"切换 CLI 模式失败: {e}")
    
    def _check_version_compatibility(self):
        """检测 Lemon Code 版本，验证 API 兼容性"""
        try:
            r = requests.get(f"{self.base_url}/global/version", timeout=5)
            if r.status_code == 200:
                ver_data = r.json()
                mimo_version = ver_data.get("version", "unknown")
                api_version = ver_data.get("api_version", "1")
                self.status_received.emit(
                    f"<span style='color:Lemon.ACCENT_GREEN;'>{{ICON:check}} Lemon Code v{mimo_version} (API v{api_version})</span>"
                )
                # 检查 API 兼容性
                try:
                    api_ver = int(str(api_version).split(".")[0])
                    if api_ver > 1:
                        self.status_received.emit(
                            f"<span style='color:Lemon.ACCENT_ORANGE;'>{{ICON:triangle-alert}} API 版本 {api_version} 可能不完全兼容，部分功能可能受限</span>"
                        )
                except ValueError:
                    pass
                return
        except Exception:
            pass
        
        # 如果 /global/version 不可用，尝试其他端点
        try:
            r = requests.get(f"{self.base_url}/global/health", timeout=3)
            if r.status_code == 200:
                self.status_received.emit(
                    f"<span style='color:Lemon.ACCENT_GREEN;'>{{ICON:check}} Lemon Code 服务已连接</span>"
                )
        except Exception:
            self.status_received.emit(
                f"<span style='color:Lemon.ACCENT_ORANGE;'>{{ICON:triangle-alert}} 无法获取 Lemon Code 版本信息</span>"
            )
    
    def _check_server_alive(self) -> bool:
        """★ 快速检查 Lemon Code 服务器是否存活（超时3秒）
        
        用于避免多个10秒超时请求叠加，导致总超时达到40秒
        """
        try:
            r = requests.get(f"{self.base_url}/global/health", timeout=3)
            return r.status_code == 200
        except Exception:
            return False
    
    def _create_or_resume_session(self, force_new=False):
        """创建新会话或恢复最近的会话
        
        ★ 修复：重连时复用已有 session_id，避免创建重复会话
        - force_new=False（默认）：优先复用已有 session_id
        - force_new=True：强制创建新会话（用户主动点击"新建会话"时使用）
        """
        # ★ 快速检查服务器是否存活（避免多个10秒超时叠加）
        if not self._check_server_alive():
            print(f"[SESSION] 服务器未响应，跳过会话创建", flush=True)
            return
        
        # ★ 如果已有 session_id 且不强制新建，先验证已有会话是否仍然有效
        if not force_new and self._session_id:
            try:
                r = requests.get(
                    f"{self.base_url}/session/{self._session_id}",
                    timeout=10  # 增加超时时间
                )
                if r.status_code == 200:
                    print(f"[SESSION] 复用已有会话: {self._session_id[:16]}...", flush=True)
                    self.session_created.emit(self._session_id)
                    self._session_known_good = True
                    self._last_session_check = time.time()
                    return
                else:
                    print(f"[SESSION] 已有会话失效 (HTTP {r.status_code})，尝试恢复...", flush=True)
                    self._session_known_good = False
            except Exception as e:
                print(f"[SESSION] 验证已有会话失败: {e}，尝试恢复...", flush=True)
        
        # 尝试获取已有会话列表
        try:
            r = requests.get(f"{self.base_url}/session", timeout=10)
            if r.status_code == 200:
                sessions = r.json()
                if sessions and len(sessions) > 0:
                    # 使用最近的会话
                    existing_id = sessions[0].get("id", "")
                    if existing_id:
                        # ★ 如果和当前 session_id 相同，无需重复设置
                        if existing_id == self._session_id:
                            print(f"[SESSION] 会话未变化: {self._session_id[:16]}...", flush=True)
                            self.session_created.emit(self._session_id)
                            self._session_known_good = True
                            self._last_session_check = time.time()
                            return
                        self._session_id = existing_id
                        self.session_created.emit(self._session_id)
                        self.status_received.emit(f"恢复会话: {self._session_id[:16]}...")
                        self._session_known_good = True
                        self._last_session_check = time.time()
                        return
        except Exception:
            pass
        
        # 创建新会话
        try:
            r = requests.post(
                f"{self.base_url}/session",
                json={"title": "Lemon Agent"},
                timeout=10
            )
            if r.status_code == 200:
                data = r.json()
                self._session_id = data.get("id", "")
                self.session_created.emit(self._session_id)
                self.status_received.emit(f"创建会话: {self._session_id[:16]}...")
                self._session_known_good = True
                self._last_session_check = time.time()
            else:
                self.error_occurred.emit(f"创建会话失败: {r.status_code} {r.text[:200]}")
                self._session_known_good = False
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            self.error_occurred.emit(f"创建会话连接失败: {e}")
            self._session_known_good = False
        except Exception as e:
            self.error_occurred.emit(f"创建会话异常: {e}")
            self._session_known_good = False
    
    def create_session(self):
        """创建新会话（用户主动点击"新建会话"时使用）"""
        # ★ 使用 force_new=True 强制创建新会话
        self._create_or_resume_session(force_new=True)
        # ★ 发布会话创建事件
        self._event_bus.publish(EventType.SESSION_CREATED, {
            "session_id": self._session_id,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        })
    
    def list_sessions(self):
        """列出所有会话"""
        try:
            r = requests.get(f"{self.base_url}/session", timeout=5)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return []
    
    def list_models(self):
        """列出可用模型"""
        try:
            r = requests.get(f"{self.base_url}/global/models", timeout=5)
            if r.status_code == 200:
                data = r.json()
                models = data.get("models", data.get("providers", []))
                if isinstance(models, list):
                    return models
                result = []
                for provider_id, provider in models.items():
                    if isinstance(provider, dict):
                        for mid, m in provider.get("models", {}).items():
                            result.append({"id": mid, "name": m.get("name", mid)})
                return result
        except Exception:
            pass
        return []
    
    def refresh_connection(self):
        """刷新连接：重新获取会话"""
        if not self._running:
            return
        self._create_or_resume_session()
    
    def _normalize_session_id(self, session_id):
        """把前端本地会话 ID 归一化为后端可识别的 ses_ ID。

        - 已是 ses_ 前缀 → 原样返回（后端原生会话）
        - session_/其他前缀 → 尝试从后端会话列表匹配（按 title 或位置）；
          匹配不到返回 ""（调用方回退 _create_or_resume_session）
        """
        if not session_id:
            return ""
        sid = str(session_id)
        if sid.startswith("ses_") or sid.startswith("ses-"):
            return sid
        try:
            sessions = self.list_sessions()
            if sessions and isinstance(sessions, list):
                # 后端会话的 title 通常对应前端 tab 名，按顺序/位置匹配
                for s in sessions:
                    rid = s.get("id", "")
                    if rid.startswith("ses_"):
                        return rid
                # 有 ses_ 会话则取最近一个
                first = sessions[0].get("id", "")
                if first:
                    return first
        except Exception:
            pass
        return ""

    def switch_session(self, session_id):
        """切换到指定会话 — 加载历史消息并重建 SSE 连接

        ★ 修复 v4.4.3（/session 404 + POLL 轮询风暴）：
        前端面板的会话 ID 是本地生成的 `session_xxx`（mimo_page.html
        `'session_' + Date.now().toString(36)`），而后端 mimo serve 只认
        `ses_xxx`（packages/opencode/src/id/id.ts prefix 定义）。若直接把本地 ID
        写入 self._session_id，轮询/发消息/加载历史全都会 404，SSE 事件也因
        sessionId 不匹配被丢弃。
        方案：若收到 session_ 前缀的本地 ID，先尝试从后端会话列表映射到真实
        ses_ ID；映射不到则回退 _create_or_resume_session() 获取真实 ID。
        """
        backend_id = self._normalize_session_id(session_id)
        old_session_id = self._session_id
        self._session_id = backend_id if backend_id else session_id
        # ★ 发布会话切换事件
        self._event_bus.publish(EventType.SESSION_SWITCHED, {
            "old_session_id": old_session_id,
            "new_session_id": session_id,
        })
        
        # 加载会话历史消息（★ 用归一化后的后端 ID 查询，避免 session_ 本地 ID 404）
        history = self._load_session_history(self._session_id)
        if history:
            self.status_received.emit(
                f"<span style='color:Lemon.ACCENT_GREEN;'>{{ICON:file-text}} 切换到会话: {self._session_id[:16]}... ({len(history)} 条历史)</span>"
            )
            # 发射历史消息用于恢复面板显示
            for msg in history:
                role = msg.get("role", "")
                parts = msg.get("parts", msg.get("content", []))
                if isinstance(parts, list):
                    for part in parts:
                        text = part.get("text", "") if isinstance(part, dict) else str(part)
                        if text and role == "assistant":
                            html = markdown_to_html(text)
                            self.output_received.emit(html)
                        elif text and role == "user":
                            self.status_received.emit(
                                f"<span style='color:#888;'>{{ICON:user}} {self._escape_html(text[:200])}</span>"
                            )
        else:
            self.status_received.emit(f"切换会话: {self._session_id[:16]}...")
        
        # 重新连接 SSE 以刷新事件流
        self._sse_stop.set()
        time.sleep(0.5)
        self._start_sse_listener()
    
    def _load_session_history(self, session_id: str):
        """从 API 加载会话的历史消息"""
        try:
            r = requests.get(
                f"{self.base_url}/session/{session_id}/messages",
                timeout=10
            )
            if r.status_code == 200:
                data = r.json()
                return data if isinstance(data, list) else data.get("messages", [])
        except Exception:
            pass
        return []
    
    # ================================================================
    # SSE 事件流监听
    # ================================================================
    
    def _start_sse_listener(self):
        """启动 SSE 事件流监听线程"""
        self._sse_stop.clear()
        self._last_sse_event_time = time.time()  # ★ 记录最后事件时间
        self._sse_thread = threading.Thread(target=self._sse_loop, daemon=True)
        self._sse_thread.start()
        # ★ 启动轮询回退定时器（SSE断线时兜底）
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._poll_session_status)
        self._poll_timer.start(3000)  # 每3秒轮询一次
    
    def _sse_loop(self):
        """SSE 事件流主循环"""
        while not self._sse_stop.is_set():
            try:
                url = f"{self.base_url}/event"
                print(f"[SSE] 连接 {url}", flush=True)
                r = requests.get(url, stream=True, timeout=300, headers={"Accept": "text/event-stream"})
                
                if r.status_code != 200:
                    print(f"[SSE] 连接失败 status={r.status_code}", flush=True)
                    time.sleep(2)
                    continue
                
                # 强制 UTF-8
                r.encoding = 'utf-8'
                print(f"[SSE] 连接成功, Content-Type={r.headers.get('Content-Type','?')}, 开始监听...", flush=True)
                # ★ 重连成功，重置计数器
                if self._reconnect_attempts > 0:
                    print(f"[SSE] 重连成功（之前尝试了{self._reconnect_attempts}次）", flush=True)
                    self._reconnect_attempts = 0
                    self.status_received.emit(
                        "<span style='color:Lemon.ACCENT_GREEN;'>{ICON:check} 连接已恢复</span>"
                    )
                    self._event_bus.publish(EventType.STATUS_UPDATE, {"status": "reconnected"})
                
                # SSE 多行 data 累积
                data_lines = []
                last_event_type = ""
                event_count = 0
                
                for line in r.iter_lines(decode_unicode=True):
                    if self._sse_stop.is_set():
                        break
                    
                    self._last_sse_event_time = time.time()  # ★ 更新最后事件时间
                    
                    if not line:
                        # 空行 = 事件结束
                        if data_lines:
                            data_str = "\n".join(data_lines)
                            data_lines = []
                            try:
                                data = json.loads(data_str)
                                if "type" not in data and last_event_type:
                                    data["type"] = last_event_type
                                self._handle_sse_event(data)
                                event_count += 1
                                # 打印前20个事件用于调试
                                if event_count <= 20:
                                    et = data.get("type", "?")
                                    print(f"[SSE] 事件#{event_count}: type={et}", flush=True)
                            except json.JSONDecodeError:
                                print(f"[SSE] JSON解析失败: {data_str[:200]}", flush=True)
                        last_event_type = ""
                        continue
                    
                    if line.startswith("data:"):
                        payload = line[5:].lstrip()
                        data_lines.append(payload)
                    elif line.startswith("event:"):
                        last_event_type = line[6:].strip()
                    elif line.startswith("retry:"):
                        pass
                    elif line.startswith(":"):
                        pass
                
                # ★ 指数退避重连：1s, 2s, 4s, 8s, 16s, 32s, 60s
                self._reconnect_attempts += 1
                delay = min(2 ** (self._reconnect_attempts - 1), self._max_reconnect_delay)
                print(f"[SSE] 连接断开（已处理{event_count}个事件），{delay}秒后重连（第{self._reconnect_attempts}次）", flush=True)
                # ★ 如果正在流式输出，发射中断信号
                if self._streaming:
                    self._streaming = False
                    self.stream_error.emit("连接中断")
                # ★ SSE 断开时重置任务状态，避免新消息被永久阻塞
                if self._is_processing:
                    self._is_processing = False
                    self._current_task = None
                    self._stop_ai_timeout()
                    QTimer.singleShot(1000, self._process_next_task)
                # 发布状态
                self.status_received.emit(
                    f"<span style='color:Lemon.STATUS_WARNING;'>{{ICON:triangle-alert}} 连接断开，{delay}秒后重连（第{self._reconnect_attempts}次）</span>"
                )
                time.sleep(delay)

            except requests.exceptions.Timeout:
                continue
            except Exception as e:
                if not self._sse_stop.is_set():
                    self._reconnect_attempts += 1
                    delay = min(2 ** (self._reconnect_attempts - 1), self._max_reconnect_delay)
                    print(f"[SSE] 异常: {e}，{delay}秒后重连", flush=True)
                    # ★ 异常断开时也重置任务状态
                    if self._streaming:
                        self._streaming = False
                    if self._is_processing:
                        self._is_processing = False
                        self._current_task = None
                        self._stop_ai_timeout()
                        QTimer.singleShot(1000, self._process_next_task)
                    time.sleep(delay)
    
    def _handle_sse_event(self, data: dict):
        """处理 SSE 事件（所有数据在 properties 嵌套中）"""
        try:
            self._crash_recovery.heartbeat()
            self._dispatch_sse_event(data)
        except Exception as e:
            print(f"[SSE] 事件处理异常: {e}", flush=True)
            traceback.print_exc()
            self._crash_recovery.log_crash(type(e), e, e.__traceback__)
            # ★ 发布崩溃恢复事件
            self._event_bus.publish(EventType.CRASH_RECOVERED, {
                "error": str(e),
                "error_type": type(e).__name__,
                "source": "sse_event_handler",
            })

    def _dispatch_sse_event(self, data: dict):
        """实际处理 SSE 事件"""
        event_type = data.get("type", data.get("event", ""))
        props = data.get("properties", {})
        
        # ★ 调试：打印所有SSE事件类型
        if event_type in ("message.part.updated", "session.updated", "session.status", "message.updated"):
            print(f"[SSE_DEBUG] type={event_type}", flush=True)
        
        # ★ 会话过滤：如果事件带有sessionId且与当前会话不匹配，跳过
        event_session_id = props.get("sessionId") or props.get("session_id") or data.get("sessionId")
        if event_session_id and self._session_id:
            if event_session_id != self._session_id:
                # ★ 调试：打印session不匹配信息
                print(f"[SSE] 会话不匹配: event={event_session_id[:30]}... vs current={self._session_id[:30]}..., 跳过", flush=True)
                return
        elif event_session_id:
            # ★ 调试：self._session_id为空，但事件有sessionId
            print(f"[SSE] 当前session_id为空，但事件有sessionId={event_session_id[:30]}...", flush=True)
        elif self._session_id:
            # ★ 调试：事件没有sessionId，但当前有session_id（移除{ICON:check}符号避免GBK编码崩溃）
            print(f"[SSE] 事件无sessionId，当前session={self._session_id[:30]}..., 继续处理", flush=True)
        
        # 更新最后事件时间
        self._last_sse_event_time = time.time()
        
        # 消息片段更新（完整内容）
        if event_type == "message.part.updated":
            part = props.get("part", {})
            part_type = part.get("type", "")
            
            if part_type == "text":
                text = part.get("text", "")
                # ★ 调试：打印message.part.updated的完整内容
                print(f"[SSE_DEBUG] message.part.updated text: len={len(text)}, content={text[:200]!r}", flush=True)
                # ★ 修复：过滤掉用户输入回显（MIMO Code会回显用户输入，不应当成AI输出）
                # 检查是否是用户输入的回显（_last_user_message在send_message中设置）
                is_user_echo = (hasattr(self, '_last_user_message') and self._last_user_message and text == self._last_user_message)
                if is_user_echo:
                    print(f"[SSE_DEBUG] 跳过用户输入回显: {text[:100]!r}", flush=True)
                    self._last_user_message = None  # 清除，避免误判后续相同内容
                # ★ 修复：严格去重，避免SSE重连时重放旧事件导致重复消息
                elif text and text != self._last_updated_text:
                    # ★ 使用 markdown_to_html 转换，避免星号乱码
                    html = markdown_to_html(text)
                    self._last_updated_text = text
                    print(f"[SSE_DEBUG] 发射output_received: html_len={len(html)}, html={html[:200]!r}", flush=True)
                    # 发射完整内容更新
                    self.output_received.emit(html)
                    # ★ 发布 MESSAGE_RECEIVED 事件
                    self._event_bus.publish(EventType.MESSAGE_RECEIVED, {"text": text, "html": html})
                    # ★ 持久化 AI 回复到 SQLite
                    if self._db_session_id:
                        self._message_store.add_message(
                            self._db_session_id, "assistant", text,
                            metadata={"html": html[:500] if html else ""}
                        )
                    # ★ 结束流式输出
                    if self._streaming:
                        self._streaming = False
                        self.stream_ended.emit(text)
                        self._stream_buffer = ""
            
            elif part_type == "reasoning":
                text = part.get("text", "")
                if text:
                    safe = self._escape_html(text)
                    self.thinking_received.emit(
                        f"<span style='color:#888;font-style:italic;'>{{ICON:brain}} {safe}</span>"
                    )
            
            elif part_type == "step-start":
                self.status_received.emit(
                    f"<span style='color:Lemon.ACCENT_ORANGE;'>{{ICON:wrench}} 开始执行...</span>"
                )
            
            elif part_type == "step-finish":
                tokens = part.get("tokens", {})
                if tokens:
                    self.usage_info.emit(tokens)
            
            elif part_type == "tool":
                # 工具调用事件（part.type === "tool"）
                tool_name = part.get("tool", "unknown")
                state = part.get("state", {})
                status = state.get("status", "")
                tool_input = state.get("input", {})
                tool_output = state.get("output", "")
                
                # 工具图标映射
                tool_icons = {
                    "bash": "{ICON:zap}", "read": "{ICON:file}", "edit": "{ICON:square-pen}", "write": "{ICON:file-edit}",
                    "grep": "{ICON:search}", "glob": "{ICON:folder-open}", "webfetch": "{ICON:globe}", "list": "{ICON:file-text}",
                    "delete": "{ICON:file-x}", "multiedit": "{ICON:square-pen}",
                }
                icon = tool_icons.get(tool_name, "{ICON:wrench}")
                
                # ★ 检测并清理 HTML 文件（防止弹出浏览器）
                html_file_path = None
                if tool_name == "write" and tool_input:
                    fp = tool_input.get("filePath", "")
                    if fp and isinstance(fp, str) and fp.lower().endswith('.html'):
                        html_file_path = fp

                # ★ 文件写入工具执行前创建快照
                if tool_name in ("write", "edit", "multiedit") and tool_input and not self._tool_shown.get(part.get("callID", "")):
                    snap = self._snapshot_mgr.create_snapshot(f"before_{tool_name}")
                    if snap:
                        self._last_snapshot_id = snap['id']
                        self._event_bus.publish(EventType.SNAPSHOT_CREATED, snap)
                        self._event_bus.publish(EventType.TOOL_BEFORE, {
                            "tool": tool_name,
                            "input": tool_input,
                            "snapshot_id": snap['id'],
                        })
                
                # 只在有输入时显示工具名（避免重复显示 pending/running 状态）
                if tool_input and not self._tool_shown.get(part.get("callID", "")):
                    self._tool_shown[part.get("callID", "")] = True
                    # 根据工具类型格式化命令显示
                    show_cmd = True
                    cmd = ""
                    if tool_name == "bash" and "command" in tool_input:
                        cmd = tool_input["command"]
                        # ★ 隐藏 explorer/html 命令
                        cmd_lower = cmd.lower()
                        if ('explorer' in cmd_lower or 'start ' in cmd_lower) and '.html' in cmd_lower:
                            self.status_received.emit(
                                f"<span style='color:Lemon.ACCENT_ORANGE;'>{{ICON:shield}} 已拦截浏览器打开HTML文件操作</span>"
                            )
                            show_cmd = False
                    elif tool_name == "read" and "filePath" in tool_input:
                        cmd = f"读取文件: {tool_input['filePath']}"
                    elif tool_name == "edit" and "filePath" in tool_input:
                        cmd = f"编辑文件: {tool_input['filePath']}"
                    elif tool_name == "write" and "filePath" in tool_input:
                        fp = tool_input['filePath']
                        if fp and isinstance(fp, str) and fp.lower().endswith('.html'):
                            self.status_received.emit(
                                f"<span style='color:Lemon.ACCENT_ORANGE;'>{{ICON:shield}} 检测到HTML文件生成，右侧栏将直接渲染图表</span>"
                            )
                            show_cmd = False
                        else:
                            cmd = f"写入文件: {fp}"
                    elif tool_name == "grep" and "pattern" in tool_input:
                        cmd = f"搜索: {tool_input['pattern']}"
                    elif tool_name == "glob" and "pattern" in tool_input:
                        cmd = f"查找文件: {tool_input['pattern']}"
                    elif tool_name == "webfetch" and "url" in tool_input:
                        cmd = f"访问网页: {tool_input['url']}"
                    elif "description" in tool_input:
                        cmd = tool_input["description"]
                    else:
                        cmd = str(tool_input)[:100]
                    
                    if show_cmd and cmd:
                        self.status_received.emit(
                            f"<span style='color:Lemon.ACCENT_ORANGE;'>{icon} [{tool_name}] {self._escape_html(str(cmd))}</span>"
                        )
                
                # 工具完成时
                if status == "completed":
                    # ★ 文件写入工具完成后创建快照
                    if tool_name in ("write", "edit", "multiedit"):
                        snap = self._snapshot_mgr.create_snapshot(f"after_{tool_name}")
                        if snap:
                            self._last_snapshot_id = snap['id']
                            self._event_bus.publish(EventType.SNAPSHOT_CREATED, snap)
                        self._event_bus.publish(EventType.TOOL_AFTER, {
                            "tool": tool_name,
                            "output": tool_output,
                        })
                        # 发布 FILE_SAVED 事件
                        if tool_input and tool_input.get("filePath"):
                            self._event_bus.publish(EventType.FILE_SAVED, {
                                "file_path": tool_input["filePath"],
                                "tool": tool_name,
                            })

                # ★ 工具错误时发布 TOOL_ERROR 事件
                elif status == "error" or status == "failed":
                    self._event_bus.publish(EventType.TOOL_ERROR, {
                        "tool": tool_name,
                        "error": tool_output,
                        "input": tool_input,
                    })

                    # ★ 清理生成的 HTML 文件（防止浏览器弹出）
                    if html_file_path and os.path.exists(html_file_path):
                        try:
                            os.remove(html_file_path)
                            print(f"[HTML-Cleanup] 已删除: {html_file_path}", flush=True)
                        except Exception as e:
                            print(f"[HTML-Cleanup] 删除失败: {e}", flush=True)

                    # ★ 自动格式化 + 代码审查（write/edit/multiedit 完成后）
                    if tool_name in ("write", "edit", "multiedit") and tool_input:
                        file_path = tool_input.get("filePath", "")
                        if file_path and os.path.exists(file_path):
                            ext = os.path.splitext(file_path)[1].lower()
                            if ext in ('.py', '.js', '.ts', '.html', '.css'):
                                # 格式化
                                try:
                                    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                                        code = f.read()
                                    lang_map = {'.py': 'python', '.js': 'javascript', '.ts': 'typescript', '.html': 'html', '.css': 'css'}
                                    fmt_result = self._formatter.format_code(code, lang_map.get(ext, 'generic'))
                                    if fmt_result.changed:
                                        with open(file_path, 'w', encoding='utf-8') as f:
                                            f.write(fmt_result.formatted)
                                        self.status_received.emit(
                                            f"<span style='color:Lemon.ACCENT_GREEN;'>{{ICON:sparkles}} 代码已自动格式化: {os.path.basename(file_path)}</span>"
                                        )
                                except Exception as e:
                                    print(f"[AutoFormat] 格式化失败: {e}", flush=True)

                                # 代码审查（仅 Python）
                                if ext == '.py':
                                    try:
                                        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                                            code = f.read()
                                        issues = self._reviewer.review_code(code, 'python')
                                        if issues:
                                            errors = sum(1 for i in issues if i.severity == "error")
                                            warnings = sum(1 for i in issues if i.severity == "warning")
                                            if errors > 0 or warnings > 0:
                                                report = self._reviewer.generate_report(issues, os.path.basename(file_path))
                                                self.status_received.emit(
                                                    f"<span style='color:{'Lemon.ACCENT_RED' if errors else 'Lemon.STATUS_WARNING'};'>{{ICON:file-text}} 代码审查: {errors}错误 {warnings}警告 — {os.path.basename(file_path)}</span>"
                                                )
                                                # 通过信号发送详细审查结果到前端
                                                self.tool_output.emit(
                                                    f"<div class='code-review-result' data-file='{file_path}'>"
                                                    + report.replace('\n', '<br>')
                                                    + "</div>"
                                                )
                                    except Exception as e:
                                        print(f"[AutoReview] 审查失败: {e}", flush=True)
                    
                    # 显示输出
                    if tool_output:
                        output_str = str(tool_output).strip()
                        # 如果是写 HTML 的输出，隐藏掉
                        if html_file_path:
                            pass  # 不显示输出
                        else:
                            if len(output_str) > 500:
                                output_str = output_str[:500] + "\n... (截断)"
                            safe = self._escape_html(output_str)
                            self.tool_output.emit(
                                f"<pre style='color:Lemon.SUCCESS;font-size:11px;line-height:1.5;margin:4px 0;padding:6px 10px;background:rgba(0,0,0,0.35);border-left:2px solid Lemon.ACCENT_GREEN;border-radius:3px;white-space:pre-wrap;font-family:monospace;'>{safe}</pre>"
                            )
                    # 清理已显示的工具记录
                    if part.get("callID"):
                        self._tool_shown.pop(part.get("callID"), None)
                    # ★ 持久化工具输出到 SQLite
                    if self._db_session_id and tool_output:
                        self._message_store.add_message(
                            self._db_session_id, "tool", str(tool_output)[:2000],
                            metadata={"tool": tool_name, "input": str(tool_input)[:500] if tool_input else ""}
                        )
        
        # 消息片段增量更新（流式文本）
        elif event_type == "message.part.delta":
            field = props.get("field", "")
            delta = props.get("delta", "")
            
            if field == "text" and delta:
                # ★ 流式输出：首次 delta 时发射 stream_started
                if not self._streaming:
                    self._streaming = True
                    self._stream_buffer = ""
                    self._stream_first_token = True
                    self.stream_started.emit()

                # 累积流式文本
                self._stream_buffer += delta

                # ★ 发射流式 token 信号（前端逐字渲染）
                self.stream_token.emit(delta)

                # ★ 也发射 delta_received（底部终端用）+ 事件总线
                self.delta_received.emit(delta)
                self._event_bus.publish(EventType.MESSAGE_DELTA, {"delta": delta})

                self._stream_first_token = False
        
        # 会话状态变化
        elif event_type == "session.status":
            status = props.get("status", {})
            status_type = status.get("type", "")
            
            if status_type == "busy":
                self.status_received.emit(
                    f"<span style='color:Lemon.ACCENT_ORANGE;'>◷ Lemon Code 执行中...</span>"
                )
            elif status_type == "idle":
                self.status_received.emit(
                    f"<span style='color:Lemon.ACCENT_GREEN;'>{{ICON:check}} 空闲</span>"
                )
                self._finish_task(True, "完成")
        
        # 会话空闲（任务完成）
        elif event_type == "session.idle":
            self._finish_task(True, "完成")
        
        # 消息更新（包含完成信息）
        elif event_type == "message.updated":
            info = props.get("info", {})
            role = info.get("role", "")
            # 只处理 assistant 角色的消息完成
            if role == "assistant":
                finish = info.get("finish", "")
                tokens = info.get("tokens", {})
                if finish == "stop":
                    self._finish_task(True, f"finish={finish}")
                    if tokens:
                        self.usage_info.emit(tokens)
        
        # 权限请求
        elif event_type == "session.permission":
            perm_id = props.get("permissionID", data.get("permissionID", ""))
            tool_info = props.get("tool", {})
            options = props.get("options", [])
            opt_list = []
            for opt in options:
                opt_list.append({
                    "id": opt.get("id", opt.get("value", "")),
                    "name": opt.get("name", opt.get("label", "")),
                    "kind": opt.get("kind", ""),
                })
            if perm_id:
                # ★ 先检查是否是危险操作（打开HTML文件/写入HTML文件），如果是则自动拒绝
                if self._auto_reject_dangerous(perm_id, tool_info, opt_list):
                    pass  # 已自动拒绝
                # 再尝试自动同意（信任模式）
                elif self._try_auto_approve(perm_id, tool_info, opt_list):
                    pass  # 已自动同意
                else:
                    self.permission_requested.emit(perm_id, tool_info, opt_list)
        
        # 配置更新
        elif event_type == "session.config":
            pass
        
        # 文件变更通知
        elif event_type == "session.diff":
            diff = props.get("diff", props)
            if isinstance(diff, dict):
                path = diff.get("path", diff.get("filePath", "未知文件"))
                typ = diff.get("type", diff.get("op", "modified"))
                type_icons = {"created": "{ICON:sparkles}", "modified": "{ICON:file-edit}", "deleted": "{ICON:file-x}", "renamed": "{ICON:file-symlink}"}
                icon = type_icons.get(typ, "{ICON:file-edit}")
                self.status_received.emit(
                    f"<span style='color:Lemon.ACCENT_BLUE;'>{icon} 文件{typ}: {self._escape_html(str(path))}</span>"
                )
                # 发射文件变更信号（供其他模块使用）
                self.file_changed.emit(path, typ, diff)
        
        # 服务器连接
        elif event_type == "server.connected":
            self.status_received.emit("SSE 已连接到 Lemon Code")
        
        elif event_type == "thinking_step":
            step_type = props.get("stepType", data.get("stepType", "unknown"))
            description = props.get("description", data.get("description", ""))
            details = props.get("details", data.get("details", {}))
            duration_ms = float(props.get("durationMs", data.get("durationMs", 0.0)))
            self.thinking_step_received.emit(step_type, description, details, duration_ms)
        
        elif event_type in ("tool_execute", "tool_execute_result"):
            card_data = props.get("card", data.get("card", {}))
            call_id = props.get("callId", data.get("callId", ""))
            if card_data:
                card_data["callId"] = call_id
                self.tool_card_received.emit(card_data)
    
    def _poll_session_status(self):
        """★ 轮询会话状态（SSE断线时的回退机制）
        
        修复：避免重复发送相同内容，只发送增量更新
        """
        if not self._session_id or not self._connected:
            return
        
        # 检查SSE是否长时间没有收到事件
        sse_stale = False
        if hasattr(self, '_last_sse_event_time'):
            elapsed = time.time() - self._last_sse_event_time
            if elapsed < 5:  # 5秒后才触发轮询
                return
            sse_stale = True
        
        # SSE断线，轮询检查会话状态
        try:
            if sse_stale:
                print(f"[POLL] 轮询会话状态 (SSE断线{elapsed:.1f}秒)...", flush=True)
            r = requests.get(
                f"{self.base_url}/session/{self._session_id}",
                timeout=3  # ★ 卡顿修复(第338章): 10→3s。本函数由 3s QTimer 在主线程调用，
                           # timeout=10 时最坏冻结 UI 10 秒（与 9s 周期卡顿特征吻合）。
            )
            if r.status_code == 200:
                data = r.json()
                status = data.get("status", {})
                status_type = status.get("type", "")
                print(f"[POLL] 会话状态: type={status_type}", flush=True)
                
                if status_type == "idle":
                    self.status_received.emit(
                        f"<span style='color:Lemon.ACCENT_GREEN;'>{{ICON:check}} 空闲（轮询检测）</span>"
                    )
                    self.task_finished.emit(True, "完成（轮询）")
                elif status_type == "busy":
                    # 仍在执行，通过轮询获取最新输出（只发送增量）
                    messages = data.get("messages", [])
                    if messages:
                        last_msg = messages[-1]
                        if last_msg.get("role") == "assistant":
                            parts = last_msg.get("parts", [])
                            for part in parts:
                                if part.get("type") == "text":
                                    text = part.get("text", "")
                                    # ★ 关键修复：只在新文本出现时才发送
                                    if text and text != self._last_updated_text:
                                        print(f"[POLL] 检测到新文本: len={len(text)} preview={text[:80]!r}", flush=True)
                                        html = markdown_to_html(text)
                                        self.output_received.emit(html)
                                        self._last_updated_text = text
                                        # 只在首次检测到时触发完成
                                        self.task_finished.emit(True, "完成（轮询）")
                                    else:
                                        print(f"[POLL] 文本未已发送，跳过", flush=True)
        except Exception as e:
            print(f"[POLL] 轮询失败: {e}", flush=True)
            pass  # 静默失败，等待下次轮询
    
    # ================================================================
    # 消息发送
    # ================================================================
    
    def _is_greeting(self, text: str) -> bool:
        """检测消息是否为问候语
        
        问候语包括：你好、您好、嗨、哈喽、早上好、下午好、晚上好、早安、午安、晚安、
        hi、hello、hey、good morning、good afternoon、good evening、greetings
        
        匹配规则：消息去除空白后，与问候语完全匹配或以问候语开头（后跟标点或空白）
        """
        greeting_pattern = re.compile(
            r'^(你好|您好|嗨|哈喽|早上好|下午好|晚上好|早安|午安|晚安|hi|hello|hey|good\s+morning|good\s+afternoon|good\s+evening|greetings)([\s,，.。！!？?]|$)',
            re.IGNORECASE
        )
        return bool(greeting_pattern.match(text.strip()))
    
    def send_message(self, text: str) -> bool:
        """发送消息到 Lemon Code（支持任务队列）"""
        if not text.strip():
            return False

        # ★ v4.1.10: 身份类问题本地拦截（修复模型自称 Claude Code / MiMo Code）
        # 不依赖底层模型，本地直接给出标准身份回答
        try:
            from core.agent_identity import detect_identity_question, build_identity_answer
            if detect_identity_question(text):
                engine = getattr(self, '_last_engine_used', '') or 'auto'
                model = getattr(self, '_last_model_used', '') or '由引擎自动选择'
                answer = build_identity_answer(engine=engine, model=model)
                html = (
                    f"<div style='color:#7ee787;margin:6px 0;padding:8px 10px;"
                    f"border-left:3px solid #7ee787;background:#0f2418;border-radius:6px;'>"
                    f" {answer.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace(chr(10), '<br>')}"
                    f"</div>"
                )
                try:
                    self.output_received.emit(html)
                except Exception:
                    pass
                try:
                    self.task_finished.emit(True, "身份问题本地回答")
                except Exception:
                    pass
                print(f"[Identity] serve_bridge 本地回答身份问题: {text[:30]}...", flush=True)
                return True
        except Exception as e:
            print(f"[Identity] 身份拦截异常（继续走引擎）: {e}", flush=True)

        # ★ 问候语检测：如果是问候语，强制创建新会话
        if self._is_greeting(text):
            self._create_or_resume_session(force_new=True)

        try:
            # ★ 注册恢复点
            self._crash_recovery.register_recovery_point("before_send_message", {
                "message": text[:200],
                "session_id": self._session_id or "",
            })
            # ★ 更新心跳
            self._crash_recovery.heartbeat()
        except Exception:
            pass

        # ★ 发布 MESSAGE_SENT 事件
        self._event_bus.publish(EventType.MESSAGE_SENT, {"text": text})

        # ★ 持久化用户消息到 SQLite
        self._ensure_db_session()
        if self._db_session_id:
            self._message_store.add_message(
                self._db_session_id, "user", text,
                metadata={"source": "right_panel"}
            )

        # ★ 记录最后一条消息（用于崩溃后重发）
        self._last_message = text
        # ★ v3.29: 记录用户输入，用于过滤SSE中的用户输入回显
        self._last_user_message = text
        
        # 连接未就绪 → 尝试 Process Bridge / ACP Bridge / PTY Bridge（不依赖 HTTP 连接）
        # ★ 修复：之前 _connected=False 时直接缓存消息且永不处理，
        # 导致 mimo serve 未启动时所有消息静默丢失。
        # 现在允许 _do_send 尝试 Process Bridge（纯 subprocess，无需 HTTP）。
        if not self._connected or not self._session_id:
            if self._process_bridge or self._acp_bridge or self._pty_bridge:
                # ★ 有非 HTTP 通道可用，直接走 _do_send
                print(f"[ServeBridge] HTTP 未连接，尝试非 HTTP 通道发送", flush=True)
                self._start_task(text)
                return True
            # 无任何通道 → 缓存（等待 HTTP 连接建立后处理）
            self._pending_messages.append(text)
            self.status_received.emit("⏳ 连接尚未就绪，消息已缓存...")
            return True
        
        # 如果正在处理任务，加入队列
        # ★ P13 B1修复: 用锁保护 check-then-act 防止竞态条件
        with self._send_lock:
            if self._is_processing:
                self._task_queue.append(text)
                queue_len = len(self._task_queue)
                self.status_received.emit(
                    f"<span style='color:Lemon.STATUS_RUNNING;'>{{ICON:file-text}} 任务已加入队列（第 {queue_len} 位）</span>"
                )
                if hasattr(self, 'queue_updated'):
                    self.queue_updated.emit(len(self._task_queue), self._task_queue.copy())
                return True
        
        # 立即执行（锁外调用，避免死锁）
        self._start_task(text)
        return True
    
    def _start_task(self, text: str):
        """开始执行任务"""
        self._is_processing = True
        self._current_task = text
        self.task_started.emit(text)
        # ★ 启动 AI 超时定时器（30秒无响应自动断开）
        self._start_ai_timeout()
        # 在后台线程发送
        threading.Thread(target=self._do_send, args=(text,), daemon=True).start()
    
    def _process_next_task(self):
        """处理队列中的下一个任务"""
        if self._task_queue:
            next_task = self._task_queue.pop(0)
            self.status_received.emit(
                f"<span style='color:Lemon.ACCENT_BLUE;'>▶ 开始处理队列中的任务（剩余 {len(self._task_queue)} 个）</span>"
            )
            if hasattr(self, 'queue_updated'):
                self.queue_updated.emit(len(self._task_queue), self._task_queue.copy())
            self._start_task(next_task)
        else:
            with self._send_lock:
                self._is_processing = False
            self._current_task = None
            if hasattr(self, 'queue_updated'):
                self.queue_updated.emit(0, [])
    
    def _finish_task(self, success: bool, message: str):
        """任务完成，触发信号并处理下一个任务（保证只执行一次）"""
        if not self._is_processing:
            return
        
        # ★ P12: 记录交互日志（蒸馏数据管道）— 必须在清除 _current_task 之前
        self._log_interaction(success)
        
        self._is_processing = False
        self._current_task = None
        self._stream_buffer = ""  # ★ P13 B2修复: 清除流式缓冲区，防止下次任务残留
        # ★ 停止 AI 超时定时器
        self._stop_ai_timeout()
        self.task_finished.emit(success, message)
        # 延迟一点处理下一个任务，避免状态竞争
        QTimer.singleShot(500, self._process_next_task)
    
    def _log_interaction(self, success: bool):
        """★ P12: 记录交互到蒸馏数据管道"""
        if not self._interaction_logger:
            return
        try:
            prompt = self._current_task or ""
            response = self._stream_buffer or ""
            if not prompt and not response:
                return
            
            engine = "mimocode"
            model = "auto"
            mode = "build"
            
            try:
                from core.engine_manager import get_engine_manager
                em = get_engine_manager()
                if em:
                    current = em.get_current_engine()
                    if current:
                        engine = current.get("name", "mimocode")
                        model = current.get("model", "auto")
            except Exception:
                pass
            
            token_estimate = len(prompt) // 3 + len(response) // 3
            
            self._interaction_logger.log_interaction(
                session_id=self._session_id or "default",
                prompt=prompt,
                response=response,
                engine=engine,
                model=model,
                mode=mode,
                token_count=token_estimate,
            )
        except Exception as e:
            print(f"[InteractionLogger] 记录失败: {e}", flush=True)
    
    # ==================== v3.54: Process Bridge 备用通道 ====================
    
    def _connect_process_bridge_signals(self):
        """连接 Process Bridge 信号到 Serve Bridge"""
        if not self._process_bridge:
            return
        self._process_bridge.output_received.connect(self.output_received)
        self._process_bridge.thinking_received.connect(self.thinking_received)
        self._process_bridge.status_received.connect(self.status_received)
        self._process_bridge.error_occurred.connect(self._on_process_bridge_error)
        # ★ v3.88: 转发 tool_output 信号（工具调用输出到右侧可折叠区域）
        self._process_bridge.tool_output.connect(self.tool_output)
        # ★ v3.90: 转发 file_preview 信号（HTML/图像/代码内嵌到右侧栏）
        self._process_bridge.file_preview.connect(self.file_preview)
        # ★ v3.72 修复: task_started 已由 _start_task 统一发出，不再重复连接
        # self._process_bridge.task_started.connect(self.task_started)
        self._process_bridge.task_finished.connect(self._on_process_bridge_finished)
        # ★ v3.72 修复: raw_output 不再连到 serve_log，避免终端显示 MIMO 内部工具调用输出乱码
    
    def _connect_acp_bridge_signals(self):
        """★ v3.58: 连接 ACP Bridge 信号到 Serve Bridge"""
        if not self._acp_bridge:
            return
        self._acp_bridge.output_received.connect(self.output_received)
        self._acp_bridge.thinking_received.connect(self.thinking_received)
        self._acp_bridge.status_received.connect(self.status_received)
        self._acp_bridge.error_occurred.connect(self._on_process_bridge_error)
        self._acp_bridge.task_started.connect(self.task_started)
        self._acp_bridge.task_finished.connect(self._on_process_bridge_finished)
        self._acp_bridge.connected.connect(
            lambda: self.status_received.emit(
                "<span style='color:Lemon.ACCENT_GREEN;'>{ICON:link} ACP Bridge 已连接</span>"
            )
        )
        self._acp_bridge.disconnected.connect(
            lambda: self.status_received.emit(
                "<span style='color:Lemon.ACCENT_ORANGE;'>{ICON:triangle-alert} ACP Bridge 已断开</span>"
            )
        )
    
    # ================================================================
    # ★ v3.118: 右侧面板 Skill 可视化数据注入
    # ================================================================
    
    def _inject_visualizer_data(self, data: Dict):
        """向右侧面板注入可视化数据
        
        通过 output_received 信号发送一段 <script> 标签，
        前端 _handleVisualizerMessage() 会解析并更新面板。
        
        Args:
            data: 可视化数据字典，包含:
                - type: 'skill_started'|'skill_completed'|'skill_failed'|
                        'task_updated'|'thinking_added'|'file_changed'|
                        'dashboard_state'
                - 其他字段根据 type 而定
        """
        if not _SKILL_VISUALIZER_AVAILABLE:
            return
        
        try:
            # 添加 _visualizer 标记，前端 _handleVisualizerMessage 会识别
            data["_visualizer"] = True
            data_json = json.dumps(data, ensure_ascii=False)
            script = (
                f'<script class="viz-data" type="application/json" '
                f'style="display:none;">{data_json}</script>'
                '<script>'
                f'(function(){{'
                f'var d=JSON.parse(document.currentScript.previousElementSibling.textContent);'
                f'if(typeof _handleVisualizerMessage==="function")_handleVisualizerMessage(d);'
                f'}})();'
                f'</script>'
            )
            self.output_received.emit(script)
        except Exception as e:
            print(f"[Visualizer] 注入失败: {e}", flush=True)
    
    def notify_skill_started(self, skill_id: str, skill_name: str, icon_svg: str = None):
        """通知前端 Skill 已启动"""
        self._inject_visualizer_data({
            "type": "skill_started",
            "skillId": skill_id,
            "skillName": skill_name,
            "iconSvg": icon_svg,
        })
    
    def notify_skill_completed(self, skill_id: str, output: str = ""):
        """通知前端 Skill 已完成"""
        self._inject_visualizer_data({
            "type": "skill_completed",
            "skillId": skill_id,
            "output": output[:500] if output else "",
        })
    
    def notify_skill_failed(self, skill_id: str, error: str = ""):
        """通知前端 Skill 执行失败"""
        self._inject_visualizer_data({
            "type": "skill_failed",
            "skillId": skill_id,
            "error": error[:200] if error else "执行失败",
        })
    
    def notify_task_updated(self, tasks: list):
        """通知前端任务列表已更新"""
        self._inject_visualizer_data({
            "type": "task_updated",
            "tasks": tasks,
        })
    
    def notify_thinking_added(self, content: str, is_working: bool = False):
        """通知前端新增思考记录"""
        self._inject_visualizer_data({
            "type": "thinking_added",
            "content": content[:500] if content else "",
            "isWorking": is_working,
        })
    
    def notify_file_changed(self, path: str, added: int, deleted: int, diff: str = "", change_type: str = "modified"):
        """通知前端文件已变更"""
        self._inject_visualizer_data({
            "type": "file_changed",
            "path": path,
            "added": added,
            "deleted": deleted,
            "diff": diff[:2000] if diff else "",
            "type": change_type,
        })
    
    def notify_dashboard_state(self):
        """推送完整仪表盘状态到前端"""
        if not _SKILL_VISUALIZER_AVAILABLE:
            return
        try:
            viz = get_skill_visualizer()
            state = viz.get_dashboard_state()
            state["type"] = "dashboard_state"
            state["_visualizer"] = True
            self._inject_visualizer_data(state)
        except Exception as e:
            print(f"[Visualizer] 推送仪表盘状态失败: {e}", flush=True)
    
    def _on_process_bridge_error(self, error_msg: str):
        """Process Bridge 错误处理"""
        print(f"[ProcessBridge] 错误: {error_msg}", flush=True)
        self._streaming = False
        self._stop_ai_timeout()
        # ★ v3.72 修复: 通过 _finish_task 统一处理
        self._finish_task(False, f"Process Bridge 错误: {error_msg[:80]}")
    
    def _on_process_bridge_finished(self, exit_code: int):
        """Process Bridge 任务完成"""
        print(f"[ProcessBridge] 任务完成 exit_code={exit_code}", flush=True)
        self._streaming = False
        self._stop_ai_timeout()
        # ★ v3.72 修复: 通过 _finish_task 统一发出 task_finished 信号，
        # 避免在 _do_send 中过早调用 _finish_task 导致 "{ICON:check} 完成" 提前显示
        success = exit_code == 0
        self._finish_task(success, f"消息完成" if success else f"Process Bridge 异常退出 (code={exit_code})")
    
    def _try_process_bridge(self, text: str) -> bool:
        """★ v3.59: 通过 Process Bridge 发送消息（主要通信方式）
        
        Process Bridge 通过 subprocess.Popen 运行 mimo run 命令，
        绕过 HTTP 线程池，直接捕获 stdout 输出。
        
        返回:
            True: 发送成功
            False: Process Bridge 不可用或正忙
        """
        if not self._process_bridge:
            return False
        
        # ★ v3.71 修复: 如果未启动，自动初始化
        if not self._process_bridge.is_running():
            if not self._process_bridge.start():
                print("[ProcessBridge] 启动失败", flush=True)
                return False
        
        # ★ v3.59: 使用 is_busy 检查是否正在处理消息（而非 is_running）
        if self._process_bridge.is_busy:
            print("[ProcessBridge] 上一个任务仍在处理中", flush=True)
            return False
        
        print(f"[ProcessBridge] 尝试发送: {text[:50]!r}", flush=True)
        self._is_processing = True
        self._current_task = text
        self._streaming = True
        
        self.status_received.emit(
            f"<span style='color:Lemon.ACCENT_BLUE;'>⟳ Process Bridge 模式 (绕过 HTTP 线程池)</span>"
        )
        
        return self._process_bridge.send_message(text)
    
    def _try_acp_bridge(self, text: str) -> bool:
        """★ v3.59: 通过 ACP Bridge 发送消息（备用通信方式）
        
        ACP Bridge 通过 ACP 协议与 MIMO Code 建立标准化双向通信，
        支持完整的夺舍功能（配置选项、权限请求、模式切换）。
        
        返回:
            True: 发送成功
            False: ACP Bridge 不可用或正忙
        """
        if not self._acp_bridge:
            return False
        
        # ★ v3.59: 使用 is_busy 检查是否正在处理消息（而非 is_connected）
        if self._acp_bridge.is_busy:
            print("[ACPBridge] 上一个任务仍在处理中", flush=True)
            return False
        
        print(f"[ACPBridge] 尝试发送: {text[:50]!r}", flush=True)
        self._is_processing = True
        self._current_task = text
        self._streaming = True
        
        self.status_received.emit(
            f"<span style='color:#ce93d8;'>{{ICON:sparkles}} ACP Bridge 模式 (夺舍通信)</span>"
        )
        
        # 确保 ACP 连接并夺舍
        if not self._acp_bridge.is_connected:
            if not self._acp_bridge.start():
                return False
            # 等待连接
            import time as _time
            wait_start = _time.time()
            while not self._acp_bridge.is_connected and _time.time() - wait_start < 10:
                _time.sleep(0.3)
        
        if not self._acp_bridge.is_connected:
            return False
        
        # 设置信任模式（自动同意权限）
        self._acp_bridge.set_trust_mode(True)
        
        return self._acp_bridge.send_message(text)
    
    def _try_pty_bridge(self, text: str) -> bool:
        """★ v3.71: 通过 PTY Bridge 发送消息（第三备选）
        
        PTY Bridge 通过 Windows 伪终端 (ConPTY/pywinpty) 运行 mimo.exe，
        实现底层可靠的终端级交互，作为最终的兜底方案。
        
        返回:
            True: 发送成功
            False: PTY Bridge 不可用或正忙
        """
        if not self._pty_bridge:
            return False
        
        if self._pty_bridge.is_busy:
            print("[PTY Bridge] 上一个任务仍在处理中", flush=True)
            return False
        
        print(f"[PTY Bridge] 尝试发送: {text[:50]!r}", flush=True)
        self._is_processing = True
        self._current_task = text
        self._streaming = True
        
        self.status_received.emit(
            f"<span style='color:Lemon.ACCENT_ORANGE;'>{{ICON:wrench}} PTY Bridge 模式 (伪终端兜底)</span>"
        )
        
        # 确保 PTY 进程已启动
        if not self._pty_bridge.is_running:
            if not self._pty_bridge.start():
                print("[PTY Bridge] 启动失败", flush=True)
                return False
        
        return self._pty_bridge.send_message(text)
    
    def _connect_pty_bridge_signals(self):
        """★ v3.71: 连接 PTY Bridge 信号"""
        if not self._pty_bridge:
            return
        self._pty_bridge.output_received.connect(self.output_received)
        self._pty_bridge.thinking_received.connect(self.thinking_received)
        self._pty_bridge.status_received.connect(self.status_received)
        self._pty_bridge.error_occurred.connect(self._on_process_bridge_error)
        self._pty_bridge.task_started.connect(self.task_started)
        self._pty_bridge.task_finished.connect(self._on_process_bridge_finished)
        self._pty_bridge.process_started.connect(
            lambda: self.status_received.emit(
                "<span style='color:Lemon.ACCENT_GREEN;'>[PTY] 伪终端进程已启动</span>"
            )
        )
        self._pty_bridge.process_stopped.connect(
            lambda code: self.status_received.emit(
                f"<span style='color:Lemon.BRAND_ORANGE_LIGHT;'>[PTY] 伪终端进程已退出 (code={code})</span>"
            )
        )
        self._pty_bridge.connection_error.connect(
            lambda err: self.error_occurred.emit(
                f"<span style='color:Lemon.ACCENT_RED;'>[PTY] 连接错误: {err}</span>"
            )
        )
    
    # ==================== v3.54: 智能桥接路由器 ====================
    
    def _setup_bridge_router(self):
        """设置智能桥接路由器 — ★ v3.60: 仅 Process Bridge，禁止 Ollama"""
        if not self._bridge_router:
            return
        
        # 设置健康检查回调
        self._bridge_router.set_http_checker(self._quick_check_mimo)
        # ★ v3.55: Process Bridge 可用性 = 模块已加载（mimo.exe 路径存在）
        self._bridge_router.set_process_checker(
            lambda: self._process_bridge is not None
        )
        # ★ v3.60: 不设置 Ollama checker，禁止路由器使用 Ollama
        
        # 连接信号
        self._bridge_router.bridge_changed.connect(self._on_bridge_changed)
        self._bridge_router.health_updated.connect(self._on_health_updated)
        self._bridge_router.bridge_error.connect(self._on_bridge_error)
        
        # ★ v3.60: 强制 Process Bridge 模式，不启动自动监控
        self._bridge_router.force_bridge(BridgeType.PROCESS)
    
    def _on_bridge_changed(self, old_bridge: str, new_bridge: str):
        """桥接通道切换回调"""
        print(f"[Router] 通道切换: {old_bridge} → {new_bridge}", flush=True)
        self.status_received.emit(
            f"<span style='color:Lemon.ACCENT_BLUE;'>{{ICON:loader-circle}} 通道切换: {old_bridge} → {new_bridge}</span>"
        )
    
    def _on_health_updated(self, health_json: str):
        """健康状态更新回调"""
        try:
            health = json.loads(health_json)
            active = health.get("active_bridge", "unknown")
            self.status_received.emit(
                f"<span style='color:#888;'>{{ICON:chart}} 桥接路由: {active}</span>"
            )
        except Exception:
            pass  # 健康状态解析失败不影响主流程
    
    def _on_bridge_error(self, bridge_type: str, error_msg: str):
        """桥接错误回调"""
        print(f"[Router] 桥接错误 [{bridge_type}]: {error_msg}", flush=True)
    
    def force_router_bridge(self, bridge_type: str):
        """强制路由器使用指定通道"""
        if not self._bridge_router:
            return
        bt_map = {
            "http": BridgeType.HTTP,
            "process": BridgeType.PROCESS,
            "ollama": BridgeType.OLLAMA,
        }
        bt = bt_map.get(bridge_type)
        if bt:
            self._bridge_router.force_bridge(bt)
    
    def set_router_auto_mode(self):
        """设置路由器为自动模式"""
        if self._bridge_router:
            self._bridge_router.set_auto_mode()
    
    def _send_via_stdio(self, text: str) -> bool:
        """通过 stdio 管道发送消息到 mimo.exe
        
        使用 Process Bridge 或直接 subprocess.Popen 建立 stdio 管道，
        发送 JSON 格式的请求，接收 JSON 格式的响应。
        
        Returns:
            True 如果发送成功，False 如果失败
        """
        import subprocess as _subprocess
        try:
            # 1. 尝试使用已有的 Process Bridge
            if self._process_bridge and self._process_bridge.is_running():
                self.status_received.emit(
                    "<span style='color:Lemon.STATUS_RUNNING;'>{ICON:link} 通过 Process Bridge (stdio) 发送...</span>"
                )
                success = self._process_bridge.send_message(text)
                if success:
                    self._stdio_enabled = True
                    return True
            
            # 2. 尝试使用智能桥接路由器（★ v3.60: 强制 Process 模式）
            if self._bridge_router:
                self.status_received.emit(
                    "<span style='color:Lemon.STATUS_RUNNING;'>{ICON:link} 通过智能路由器 (stdio) 发送...</span>"
                )
                # ★ v3.60: 强制 Process Bridge，不调用 set_auto_mode()
                result = self._bridge_router.send(text)
                if result:
                    self._stdio_enabled = True
                    return True
            
            # 3. 直接使用 subprocess 建立 stdio 管道
            import subprocess
            import json as json_lib
            
            # 获取上下文
            context = self._context_manager.get_recent_context(10)
            
            # 构建 stdio 请求
            payload = {
                "type": "chat",
                "session_id": self._session_id or "default",
                "message": text,
                "context": context,
            }
            
            self.status_received.emit(
                f"<span style='color:Lemon.STATUS_RUNNING;'>{{ICON:package}} 通过 stdio 发送消息 (上下文: {len(context)}条)...</span>"
            )
            
            # 执行 mimo run --session --format json
            cmd = self._build_stdio_command(text)
            if cmd is None:
                return False
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=self.project_path,
            )
            
            if result.returncode == 0 and result.stdout:
                # 解析 JSON 响应并发送到 UI
                self._handle_stdio_response(result.stdout)
                self._stdio_enabled = True
                return True
            else:
                stderr = result.stderr[:200] if result.stderr else "无错误输出"
                print(f"[Stdio] 命令失败: {stderr}", flush=True)
                return False
                
        except _subprocess.TimeoutExpired:
            print(f"[Stdio] 命令超时", flush=True)
            self.status_received.emit(
                "<span style='color:Lemon.ACCENT_RED;'>⏱ Stdio 命令超时</span>"
            )
            return False
        except FileNotFoundError:
            print(f"[Stdio] mimo.exe 未找到", flush=True)
            self.status_received.emit(
                "<span style='color:Lemon.ACCENT_RED;'>{ICON:circle-x} mimo.exe 未找到，无法使用 stdio 模式</span>"
            )
            return False
        except Exception as e:
            print(f"[Stdio] 发送失败: {e}", flush=True)
            self.status_received.emit(
                f"<span style='color:Lemon.ACCENT_RED;'>{{ICON:circle-x}} Stdio 发送失败: {str(e)[:100]}</span>"
            )
            return False
    
    def _build_stdio_command(self, text: str) -> Optional[list]:
        """构建 stdio 通信命令
        
        使用 mimo run --session <id> <message> 通过子进程执行。
        """
        try:
            # 查找 mimo.exe
            exe_path = getattr(self, '_exe_path', None)
            if not exe_path:
                return None
            
            cmd = [exe_path, "run", "--format", "json"]
            
            if self._session_id:
                cmd.extend(["--session", self._session_id])
            
            cmd.append(text)
            return cmd
            
        except Exception as e:
            print(f"[Stdio] 构建命令失败: {e}", flush=True)
            return None
    
    def _handle_stdio_response(self, stdout: str):
        """处理 stdio 响应（JSON 格式输出）"""
        try:
            import json as json_lib
            
            lines = stdout.strip().split('\n')
            full_content = ""
            thinking_content = ""
            
            for line in lines:
                if not line.strip():
                    continue
                try:
                    data = json_lib.loads(line)
                    msg_type = data.get("type", "")
                    
                    if msg_type == "step_start":
                        pass
                    elif msg_type == "text":
                        text_content = data.get("part", {}).get("text", "") if "part" in data else data.get("text", "")
                        full_content += text_content
                        self.stream_token.emit(text_content)
                    elif msg_type == "thinking":
                        thinking_text = data.get("text", "")
                        thinking_content += thinking_text
                        self.thinking_received.emit(thinking_text)
                    elif msg_type == "thinking_step":
                        step_type = data.get("stepType", "unknown")
                        description = data.get("description", "")
                        details = data.get("details", {})
                        duration_ms = float(data.get("durationMs", 0.0))
                        self.thinking_step_received.emit(step_type, description, details, duration_ms)
                    elif msg_type in ("tool_execute", "tool_execute_result"):
                        card_data = data.get("card", {})
                        call_id = data.get("callId", "")
                        if card_data:
                            card_data["callId"] = call_id
                            self.tool_card_received.emit(card_data)
                    elif msg_type == "tool_use":
                        tool_name = data.get("tool", "unknown")
                        self.tool_output.emit(f"{{ICON:wrench}} 调用工具: {tool_name}")
                    elif msg_type == "step_finish":
                        break
                    elif msg_type == "error":
                        error_msg = data.get("error", "未知错误")
                        self.error_occurred.emit(error_msg)
                        return
                        
                except json_lib.JSONDecodeError:
                    # 非 JSON 行，可能是纯文本输出
                    full_content += line
                    self.stream_token.emit(line)
            
            # 发送完整响应
            if full_content:
                self._context_manager.add_message("assistant", full_content)
                self.output_received.emit(full_content)
                self.stream_ended.emit(full_content)
            
            if thinking_content:
                self.thinking_received.emit(thinking_content)
                
        except Exception as e:
            print(f"[Stdio] 解析响应失败: {e}", flush=True)
            self.error_occurred.emit(f"解析 stdio 响应失败: {str(e)}")
    
    def _do_send(self, text: str):
        """★ v3.59: 在后台线程发送消息
        通信降级链：Process Bridge → ACP Bridge → PTY Bridge → 错误报告
        MIMO模式下不自动切换到Ollama
        """
        try:
            print(f"[SEND] 开始发送 (mode={self.communication_mode}): {text[:50]!r}", flush=True)
            
            # ★ v3.57: 记录上下文
            self._context_manager.add_message("user", text)
            
            # ★ v3.58: 通信降级链
            # 第1优先：Process Bridge（stdio 管道，绕过 HTTP 线程池）
            if self._process_bridge:
                result = self._try_process_bridge(text)
                if result:
                    # ★ v3.72 修复: 不再立即调用 _finish_task，
                    # 由 _on_process_bridge_finished 在子进程真正完成后统一处理
                    print("[SEND] Process Bridge 已接管，等待完成信号...", flush=True)
                    return
                print("[SEND] Process Bridge 不可用，尝试 ACP Bridge...", flush=True)
            
            # 第2优先：ACP Bridge（ACP 协议，完整夺舍功能）
            if self._acp_bridge:
                result = self._try_acp_bridge(text)
                if result:
                    # ★ v3.72 修复: 不立即调用 _finish_task，
                    # 由 _on_process_bridge_finished / ACP 完成信号统一处理
                    print("[SEND] ACP Bridge 已接管，等待完成信号...", flush=True)
                    return
                print("[SEND] ACP Bridge 不可用，尝试 PTY Bridge...", flush=True)
            
            # ★ v3.71: 第3优先：PTY Bridge（伪终端，底层可靠交互）
            if self._pty_bridge:
                result = self._try_pty_bridge(text)
                if result:
                    # ★ v3.72 修复: 不立即调用 _finish_task
                    print("[SEND] PTY Bridge 已接管，等待完成信号...", flush=True)
                    return
                print("[SEND] PTY Bridge 不可用", flush=True)
            
            # ★ v3.58: 所有桥接都失败，报告错误（不自动回退到 Ollama）
            self.error_occurred.emit(self._build_mimo_unavailable_message())
            self._finish_task(False, "所有 MIMO 通信通道均不可用")
            
        except Exception as e:
            print(f"[SEND] 发送异常: {e}", flush=True)
            traceback.print_exc()
            self._finish_task(False, str(e))
    
    def _quick_check_mimo(self) -> bool:
        """★ v3.62: HTTP 健康检查 MIMO serve（serve + attach 架构）"""
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            result = sock.connect_ex(('127.0.0.1', 4097))
            sock.close()
            if result != 0:
                return False
            r = requests.get(f"{self.base_url}/global/health", timeout=3)
            return r.status_code == 200
        except Exception:
            return False
    
    def _build_mimo_unavailable_message(self) -> str:
        """★ v3.57: 构建友好的 MIMO 不可用引导提示
        
        包含：
        - MIMO Code 未启动说明
        - 启动方法（命令行）
        - 端口状态（TCP + HTTP 双重检测）
        - 替代方案（切换到 Ollama/自动模式）
        """
        import socket
        
        # 1. 检测 TCP 端口状态
        port_open = False
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            port_open = sock.connect_ex(('127.0.0.1', 4097)) == 0
            sock.close()
        except Exception:
            pass
        
        # 2. 检测 HTTP 响应状态
        http_ok = False
        http_status = "无响应"
        try:
            r = requests.get(f"{self.base_url}/global/health", timeout=2)
            http_status = f"HTTP {r.status_code}"
            http_ok = r.status_code == 200
        except requests.exceptions.Timeout:
            http_status = "超时"
        except requests.exceptions.ConnectionError:
            http_status = "连接被拒绝"
        except Exception as e:
            http_status = f"错误: {str(e)[:30]}"
        
        # 3. 构建引导消息
        port_status_icon = "{ICON:circle}" if port_open else "{ICON:circle}"
        http_status_icon = "{ICON:circle}" if http_ok else "{ICON:circle}"
        
        # 检测 mimo.exe 路径
        import os
        exe_path = getattr(self, '_exe_path', '')
        if not exe_path:
            _mimo_root = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "小米AI", "node_global"
            )
            exe_path = os.path.join(
                _mimo_root, "node_modules",
                "@mimo-ai", "mimocode-windows-x64", "bin", "mimo.exe"
            )
        exe_exists = os.path.exists(exe_path)
        
        msg = f"""
<div style='background:rgba(244,67,54,0.08);border:1px solid rgba(244,67,54,0.3);border-radius:8px;padding:12px 16px;margin:8px 0;font-size:13px;line-height:1.6;'>
  <div style='color:Lemon.ACCENT_RED;font-weight:bold;font-size:14px;margin-bottom:8px;'>{{ICON:triangle-alert}} MIMO Code 服务不可用</div>
  
  <div style='color:Lemon.DIVIDER;margin-bottom:6px;'>{{ICON:zap}} <b>端口状态</b></div>
  <div style='color:#bbb;margin-left:12px;margin-bottom:8px;'>
    {port_status_icon} TCP 端口 4097：{'已开放' if port_open else '未开放'}<br/>
    {http_status_icon} HTTP 健康检查：{http_status}
  </div>
  
  <div style='color:Lemon.DIVIDER;margin-bottom:6px;'>{{ICON:rocket}} <b>启动 MIMO Code</b></div>
  <div style='background:rgba(0,0,0,0.4);color:Lemon.SUCCESS;padding:8px 12px;border-radius:4px;font-family:Courier New,monospace;font-size:12px;margin-bottom:8px;'>
    cd "{os.path.dirname(exe_path) if exe_exists else 'MIMO安装目录'}"<br/>
    mimo serve --port 4097
  </div>
  {"<div style='color:Lemon.ACCENT_ORANGE;font-size:11px;margin-bottom:8px;'>{{ICON:triangle-alert}} mimo.exe 未找到，请确认 MIMO Code 已正确安装</div>" if not exe_exists else ""}
  
  <div style='color:Lemon.DIVIDER;margin-bottom:6px;'>{{ICON:lightbulb}} <b>替代方案</b></div>
  <div style='color:#bbb;margin-left:12px;'>
    • 切换到 <b>Ollama 模式</b>：使用本地 AI 引擎<br/>
    • 切换到 <b>自动模式</b>：MIMO 在线时自动使用，离线时回退到 Ollama
  </div>
</div>"""
        return msg
    
    def _try_ollama_fallback(self, text: str):
        """v3.53: MIMO 不可用时回退到 Ollama 引擎
        v3.81: 改用 agent_chat() 实现工具调用闭环
        v3.82-F5: 注入 project_root 到 SkillsRegistry
        
        使用 EngineManager.agent_chat() 而非 chat()：
        - chat() = 纯文本对话，模型只能"建议"
        - agent_chat() = 工具调用循环，模型能真实执行 write_file / run_command 等
        """
        # v3.82-F5: 注入 project_root 到 registry（确保 write_file 解析相对路径正确）
        try:
            from core.skills_registry import get_skills_registry
            _reg = get_skills_registry()
            if _reg.get_project_root() != self.project_path:
                _reg.set_project_root(self.project_path)
        except Exception:
            pass

        # [DIAG] v3.82-F5: 路径诊断
        print(f"[DIAG] cwd={os.getcwd()} project_path={self.project_path} registry_root={_reg.get_project_root() if _reg else 'N/A'}", flush=True)
        # ★ v3.51: 检查是否禁用了自动回退（MIMO/Ollama 固定模式）
        if getattr(self, '_auto_fallback_disabled', False):
            print("[Ollama回退] 自动回退已禁用，不切换到Ollama", flush=True)
            self.error_occurred.emit(
                "<span style='color:Lemon.ACCENT_RED;'>MIMO Code 服务不可用，请检查服务是否启动</span>"
            )
            self._streaming = False
            self._is_processing = False
            self._current_task = None
            self._stop_ai_timeout()
            QTimer.singleShot(500, self._process_next_task)
            return

        try:
            print(f"[Ollama回退] 开始处理(Agent模式): {text[:50]!r}", flush=True)
            self._is_processing = True
            self._current_task = text
            self._streaming = True
            
            # v3.82-C3: timeline event - agent loop start
            try:
                import json as _json
                self.status_received.emit(
                    _json.dumps({"type": "timeline", "event": "agent_start", "ts": time.time()})
                )
            except Exception:
                pass
            
            # 发布思考状态
            self.thinking_received.emit(
                f"<span style='color:Lemon.ACCENT_ORANGE;'>{{ICON:brain}} Ollama Agent 模式（工具调用闭环）...</span>"
            )
            
            import sys as _sys
            _lemon_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            if _lemon_root not in _sys.path:
                _sys.path.insert(0, _lemon_root)
            from shared.engine_manager import get_engine_manager
            
            engine_mgr = get_engine_manager()
            if not engine_mgr._engines.get("ollama"):
                engine_mgr.initialize()
            
            _proj_name = os.path.basename(self.project_path.rstrip('/\\'))
            # ★ v4.7.17+ 契约单一事实源：工具清单从 registry schema 自动生成，
            # 不再硬编码 —— schema 改一处，prompt 自动跟上，杜绝参数名漂移。
            _tools_lines = []
            try:
                from core.skills_registry import get_skills_registry
                for _t in get_skills_registry().get_tool_definitions():
                    _fn = _t.get("function", _t)
                    _tname = _fn.get("name", "")
                    _tdesc = _fn.get("description", "") or ""
                    _tparams = _fn.get("parameters", {}).get("properties", {})
                    if _tname in ("write_file", "edit_file", "read_file",
                                  "run_command", "grep_search"):
                        _param_str = ", ".join(_tparams.keys())
                        _tools_lines.append(f"- {_tname}({_param_str})  {_tdesc}")
            except Exception:
                pass
            if not _tools_lines:
                # 兜底（registry 不可用时）
                _tools_lines = [
                    "- write_file(file_path, content)  创建/覆盖文件，file_path 相对于项目根",
                    "- run_command(command, cwd=None)  执行 shell 命令",
                    "- read_file(file_path, max_lines=200)  读取文件内容",
                    "- edit_file(file_path, old_text, new_text)  精确编辑",
                    "- grep_search(pattern, path='.', include='*')  代码搜索",
                ]
            _tools_desc = "\n".join(_tools_lines)

            # ★ v4.7.17+: 强引导工具调用 + 工程规范（避免小模型写出 echo bat 这种偷懒代码）
            coding_prompt = (
                f"你是一个 AI 编程助手，运行在 Lemon Code 编辑器中。\n"
                f"当前工作目录: {self.project_path}\n"
                f"项目名称: {_proj_name}\n\n"
                f"【铁律一 · 工具调用】凡是涉及「建文件夹/写文件/运行程序/修改代码/读取文件」的请求，"
                f"必须**真正调用工具**（write_file / run_command / read_file 等），"
                f"**禁止**用自然语言描述文件路径或代码块代替。"
                f"**禁止**编造不存在的工具名（如 create_and_run_file、save_file、mkdir 等），"
                f"只能使用下方清单中的工具名。\n\n"
                f"【铁律二 · 工程规范】编写真实可运行的商业级代码：\n"
                f"1. **完整实现**：禁止用 echo bat、占位符、TODO 注释偷懒；"
                f"   用户要求 X 个文件，就写出 X 个完整文件，每个文件含真实业务逻辑\n"
                f"2. **架构合理**：Flask/FastAPI 后端按 routes/models/services 分层；"
                f"   HTML/CSS/JS 前端按 page/style/script 分层；不要把所有代码塞进单个 main.py\n"
                f"3. **错误处理**：try/except 包裹 IO/网络/解析，错误消息清晰\n"
                f"4. **注释充分**：关键函数 docstring + 必要行内注释（中文）\n"
                f"5. **依赖完整**：requirements.txt / package.json 列出所有外部依赖\n\n"
                f"【铁律三 · 任务规划】复杂任务先**列出计划**：\n"
                f"- 步骤1: 创建哪些目录/文件\n"
                f"- 步骤2: 每个文件的核心内容概述\n"
                f"- 步骤3: 依赖与启动方式\n"
                f"然后按计划逐步调用工具执行。\n\n"
                f"工具清单（参数名严格按此命名，来自 schema 单一事实源）：\n"
                f"{_tools_desc}\n\n"
                f"调用格式（必须严格遵守，每次只输出一个 JSON 块，参数名与上方清单完全一致）：\n"
                f"```json\n"
                f"{{\"tool_calls\": [{{\"name\": \"write_file\", \"arguments\": {{\"file_path\": \"main.py\", \"content\": \"...\"}}}}]}}\n"
                f"```\n\n"
                f"示例：\n"
                f"用户：建一个 Python Flask Hello World\n"
                f"助手：\n"
                f"```json\n"
                f'{{"tool_calls": [{{"name": "write_file", "arguments": {{"file_path": "app.py", "content": "from flask import Flask\\napp = Flask(__name__)\\n\\n@app.route(\\\"/\\\")\\ndef hello():\\n    return \\\"Hello, World!\\\"\\n\\nif __name__ == \\\"__main__\\\":\\n    app.run(debug=True)\\n"}}}}]}}\n'
                f"```\n\n"
                f"工具返回结果后，再用自然语言总结。\n"
                f"回复要求: 使用中文，简洁直接"
            )

            # ★ v3.81: 工具执行流式输出回调
            # ★ v4.7.17+: 节流 stream emit —— 每个 token 都触发 WebEngine 重绘，
            # 导致 CPU 100%。改为每 50ms 或累计 20 个 token 才 flush 一次。
            _accumulated_tokens = []
            _last_emit_ms = [0]
            from PyQt5.QtCore import QTimer as _QT
            _flush_timer = _QT()
            _flush_timer.setSingleShot(True)
            def _flush_stream():
                if not _accumulated_tokens:
                    return
                chunk = "".join(_accumulated_tokens)
                _accumulated_tokens.clear()
                try:
                    self.stream_token.emit(chunk)
                except Exception:
                    pass
            _flush_timer.timeout.connect(_flush_stream)
            def _stream_cb(token: str):
                _accumulated_tokens.append(token)
                # 累积满 20 token 或距上次 emit 已过 50ms → 立即 flush
                if len(_accumulated_tokens) >= 20:
                    if _flush_timer.isActive():
                        _flush_timer.stop()
                    _flush_stream()
                else:
                    # 启动/重置 50ms 单次定时器
                    if not _flush_timer.isActive():
                        _flush_timer.start(50)

            # v3.82-C3: 工具调用实时通知回调
            _engine_tool_cb = None
            try:
                engine_mgr_tool_signal = engine_mgr.tool_call_made
                def _engine_tool_cb(tool_info: dict):
                    try:
                        name = tool_info.get("name", "?")
                        success = tool_info.get("success", False)
                        result_preview = tool_info.get("result", "")[:200]
                        # v3.82-F5: file_status for write-in-progress
                        args = tool_info.get("arguments", {})
                        fpath = args.get("path", args.get("file_path", ""))
                        if name in ("write_file", "edit_file", "multi_edit") and fpath:
                            self.file_status.emit(fpath, "done" if success else "failed")
                        status_icon = "{ICON:check}" if success else "{ICON:circle-x}"
                        html = (
                            f"<div class='tool-card' data-status='done'>"
                            f"<span class='tool-ico'>{{ICON:wrench}}</span> "
                            f"<b>{name}</b> {status_icon}<br/>"
                            f"<code style='font-size:11px;color:var(--text-secondary);'>{result_preview}</code>"
                            f"</div>"
                        )
                        self.tool_output.emit(html)
                        # v3.82-C3: file change notification for write/edit
                        if name in ("write_file", "edit_file", "multi_edit"):
                            if fpath and success:
                                try:
                                    import difflib
                                    old_content = ""
                                    new_content = ""
                                    if os.path.isfile(fpath):
                                        with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
                                            new_content = fh.read()
                                    old_lines = old_content.splitlines(keepends=True)
                                    new_lines = new_content.splitlines(keepends=True)
                                    diff = "".join(difflib.unified_diff(old_lines, new_lines, n=3))[:2000]
                                    added = max(0, len(new_lines) - len(old_lines))
                                    deleted = max(0, len(old_lines) - len(new_lines))
                                    ctype = "created" if name == "write_file" and not old_content else "modified"
                                    self.notify_file_changed(fpath, added, deleted, diff, ctype)
                                except Exception:
                                    self.notify_file_changed(fpath, 0, 0, "", "modified")
                    except Exception:
                        pass
                engine_mgr_tool_signal.connect(_engine_tool_cb)
            except Exception:
                pass

            # v3.82-F5: tool_call_starting -> file_status("writing")
            _engine_tool_starting_cb = None
            try:
                engine_mgr_tool_start_signal = engine_mgr.tool_call_starting
                def _engine_tool_starting_cb(tool_info: dict):
                    try:
                        name = tool_info.get("name", "")
                        args = tool_info.get("arguments", {})
                        fpath = args.get("path", args.get("file_path", ""))
                        if name in ("write_file", "edit_file", "multi_edit") and fpath:
                            self.file_status.emit(fpath, "writing")
                    except Exception:
                        pass
                engine_mgr_tool_start_signal.connect(_engine_tool_starting_cb)
            except Exception:
                pass

            # ★ v3.81: 获取确认回调（从 ToolConfirmGate）
            _confirm_cb = getattr(self, '_tool_confirm_callback', None)
            
            # ★ v3.81: 改用 agent_chat() — 带工具调用循环
            # ★ v4.7.17+: max_iterations 从 20 降到 5 —— qwen3.5:4b 小模型工具调用
            # 成功率低，循环 20 轮会导致模型陷入"创作欲"死循环，CPU 100% 风扇狂转。
            # 5 轮足够覆盖一般任务，工具调用失败时及时返回错误让用户决策。
            result = engine_mgr.agent_chat(
                text,
                engine="ollama",
                system_prompt=coding_prompt,
                max_iterations=5,
                stream_callback=_stream_cb,
                confirm_callback=_confirm_cb,
            )
            
            full_content = result.get("content", "") if isinstance(result, dict) else str(result)
            iterations = result.get("iterations", 0) if isinstance(result, dict) else 0
            tool_calls_made = result.get("tool_calls_made", []) if isinstance(result, dict) else []
            total_time = result.get("total_time", 0) if isinstance(result, dict) else 0
            token_info = result.get("token_info", "") if isinstance(result, dict) else ""
            is_cancelled = result.get("cancelled", False) if isinstance(result, dict) else False

            # ★ v3.81: 被取消时保存恢复状态并提示追问
            if is_cancelled:
                self.status_received.emit(
                    "<span style='color:Lemon.BRAND_ORANGE_LIGHT;'>{ICON:pause} Agent 已暂停 — 发送「继续」可恢复</span>"
                )
                if full_content:
                    self.output_received.emit(full_content)
                self._streaming = False
                self._is_processing = False
                self._current_task = None
                self._stop_ai_timeout()
                QTimer.singleShot(500, self._process_next_task)
                return

            # ★ 工具调用元数据卡片
            if tool_calls_made:
                tool_names = [tc.get("name", "?") for tc in tool_calls_made]
                tool_summary = " → ".join(tool_names)
                meta_html = (
                    f"<div style='margin:6px 0;padding:6px 10px;"
                    f"background:linear-gradient(135deg,Lemon.DARK_MID_5,Lemon.DARK_BG_4);"
                    f"border:1px solid rgba(255,154,74,0.2);border-radius:6px;"
                    f"color:#aaa;font-size:11px;font-family:Consolas,monospace;'>"
                    f"<span style='color:Lemon.BRAND_ORANGE_LIGHT;'>{{ICON:wrench}} Agent 工具链</span> "
                    f"{iterations}轮 · {len(tool_calls_made)}次调用 · {total_time:.1f}s"
                    f"<br/><span style='color:Lemon.ACCENT_GREEN;'>{tool_summary}</span>"
                    f"</div>"
                )
                self.status_received.emit(meta_html)
            
            if full_content:
                print(f"[Ollama回退] Agent完成: {iterations}轮, {len(tool_calls_made)}次工具调用, {len(full_content)}字", flush=True)
                self.output_received.emit(full_content)
                self.status_received.emit(
                    f"<span style='color:Lemon.ACCENT_GREEN;'>{{ICON:check}} Ollama Agent 完成 ({iterations}轮, {len(tool_calls_made)}次工具调用)</span>"
                )
            elif tool_calls_made:
                # 纯工具调用场景（无最终文本回复），输出工具结果摘要
                last_result = tool_calls_made[-1].get("result", "")[:500] if tool_calls_made else ""
                self.output_received.emit(f"工具执行完成。\n{last_result}")
                self.status_received.emit(
                    f"<span style='color:Lemon.ACCENT_GREEN;'>{{ICON:check}} Ollama Agent 工具链完成</span>"
                )
            else:
                self.error_occurred.emit("Ollama Agent 返回空内容")
                
        except Exception as e:
            print(f"[Ollama回退] 异常: {e}", flush=True)
            import traceback
            traceback.print_exc()
            self.error_occurred.emit(f"Ollama Agent 失败: {e}")
        finally:
            if _engine_tool_cb is not None:
                try:
                    engine_mgr.tool_call_made.disconnect(_engine_tool_cb)
                except Exception:
                    pass
            self._streaming = False
            self._is_processing = False
            self._current_task = None
            self._stop_ai_timeout()
            QTimer.singleShot(500, self._process_next_task)
    
    def _validate_session(self, force_check=False) -> bool:
        """★ 验证会话是否仍然有效（带缓存，避免频繁请求）
        
        Args:
            force_check: 强制验证（忽略缓存）
        """
        if not self._session_id:
            return False
        
        # 缓存命中：最近30秒内验证过且成功，直接返回True
        if not force_check and self._session_known_good:
            elapsed = time.time() - self._last_session_check
            if elapsed < self._session_check_interval:
                return True
        
        try:
            r = requests.get(
                f"{self.base_url}/session/{self._session_id}",
                timeout=10  # 超时从5秒增加到10秒，避免误判
            )
            valid = r.status_code == 200
            self._session_known_good = valid
            self._last_session_check = time.time()
            return valid
        except requests.exceptions.ConnectionError:
            # ★ 连接被拒绝（服务器未启动），直接返回 False
            self._session_known_good = False
            return False
        except Exception:
            # 其他网络异常（如DNS解析失败），如果之前验证成功过则保持乐观
            # 否则返回 False
            if self._session_known_good:
                return True
            return False
    
    def _flush_pending_messages(self):
        """发送缓存的消息"""
        if not self._pending_messages:
            return
        messages = self._pending_messages.copy()
        self._pending_messages.clear()
        for msg in messages:
            self.send_message(msg)
    
    # ================================================================
    # 交互方法
    # ================================================================
    
    def respond_permission(self, session_id: str, choice_id: str):
        """响应权限请求"""
        try:
            requests.post(
                f"{self.base_url}/session/{self._session_id}/permissions/{session_id}",
                json={"choice": choice_id},
                timeout=10
            )
        except Exception as e:
            self.error_occurred.emit(f"权限响应失败: {e}")

    # ==================== 信任模式（自动同意） ====================
    def set_trust_mode(self, enabled: bool, auto_approve_tools: list = None):
        """设置信任模式
        
        Args:
            enabled: 是否启用自动同意
            auto_approve_tools: 自动同意的工具类型列表，如 ['file_write', 'shell', 'file_read']
                              为 None 或空列表时表示自动同意所有
        """
        self._trust_mode = enabled
        if auto_approve_tools:
            self._auto_approve_tools = set(auto_approve_tools)
        else:
            self._auto_approve_tools = set()
    
    def get_trust_mode(self) -> tuple:
        """获取信任模式状态"""
        return self._trust_mode, list(self._auto_approve_tools)

    # ==================== 快照管理（供 QWebChannel 调用） ====================

    def list_snapshots(self) -> list:
        """获取快照列表"""
        return self._snapshot_mgr.list_snapshots()

    def restore_snapshot(self, snapshot_id: str) -> dict:
        """回退到指定快照"""
        success, msg = self._snapshot_mgr.restore_snapshot(snapshot_id)
        if success:
            self._event_bus.publish(EventType.SNAPSHOT_RESTORED, {
                "snapshot_id": snapshot_id,
                "message": msg,
            })
        return {"success": success, "message": msg}

    def diff_snapshot(self, snapshot_id: str) -> str:
        """获取快照与当前版本的 diff"""
        return self._snapshot_mgr.diff_snapshots(snapshot_id)

    def get_last_snapshot_id(self) -> Optional[str]:
        """获取最近一次快照ID"""
        return self._last_snapshot_id

    # ==================== 流式输出控制（供外部调用） ====================

    def push_stream_token(self, token: str):
        """手动推送流式 token（供 Ollama 等外部流式源调用）"""
        if not self._streaming:
            self._streaming = True
            self._stream_buffer = ""
            self._stream_first_token = True
            self.stream_started.emit()

        self._stream_buffer += token
        self.stream_token.emit(token)
        self._event_bus.publish(EventType.MESSAGE_DELTA, {"delta": token})

    def end_stream(self, full_text: str = ""):
        """手动结束流式输出"""
        if self._streaming:
            self._streaming = False
            text = full_text or self._stream_buffer
            self.stream_ended.emit(text)
            self._stream_buffer = ""

    def is_streaming(self) -> bool:
        """是否正在流式输出"""
        return self._streaming

    # ==================== 心跳检测（供前端调用） ====================

    def heartbeat(self):
        """前端心跳 ping"""
        self._crash_recovery.heartbeat()
        return {"status": "ok", "timestamp": time.time()}

    def get_crash_logs(self) -> list:
        """获取崩溃日志列表"""
        return self._crash_recovery.list_crash_logs()

    def get_recovery_points(self) -> list:
        """获取恢复点列表"""
        return self._crash_recovery.list_recovery_points()

    # ==================== 设置管理（AI 参数） ====================

    def get_ai_settings(self) -> dict:
        """从 SettingsManager 读取 AI 相关设置，供发送消息时使用"""
        try:
            sm = get_settings_manager()
            return {
                "model": sm.ai_model,
                "temperature": sm.ai_temperature,
                "max_tokens": sm.ai_max_tokens,
            }
        except Exception as e:
            print(f"[Settings] 读取 AI 设置失败，使用默认值: {e}")
            return {"model": "auto", "temperature": 0.7, "max_tokens": 4096}

    def get_appearance_settings(self) -> dict:
        """读取外观设置"""
        try:
            sm = get_settings_manager()
            return {
                "theme": sm.theme,
                "font_size": sm.font_size,
            }
        except Exception:
            return {"theme": "cyber", "font_size": 14}

    def get_visualization_settings(self) -> dict:
        """读取可视化设置"""
        try:
            sm = get_settings_manager()
            return {
                "chart_style": sm.get("visualization.chart_style", "neon"),
                "render_quality": sm.get("visualization.render_quality", "high"),
                "animation": sm.animation_enabled,
            }
        except Exception:
            return {"chart_style": "neon", "render_quality": "high", "animation": True}

    # ==================== 工作区管理 ====================

    def get_current_workspace(self) -> dict:
        """获取当前工作区信息"""
        try:
            wm = get_workspace_manager()
            ws = wm.get_current_workspace()
            return ws if ws else {}
        except Exception as e:
            print(f"[Workspace] 获取当前工作区失败: {e}")
            return {}

    def get_workspace_path(self) -> str:
        """获取当前工作区路径（供工具调用上下文隔离使用）"""
        try:
            wm = get_workspace_manager()
            return wm.get_current_path()
        except Exception:
            return ""

    def list_workspaces(self) -> list:
        """列出所有工作区"""
        try:
            wm = get_workspace_manager()
            return wm.list_workspaces()
        except Exception as e:
            print(f"[Workspace] 列出工作区失败: {e}")
            return []

    def switch_workspace(self, ws_id: str) -> dict:
        """切换工作区，返回切换结果。
        切换后，后续工具调用将使用新工作区的路径作为上下文。
        """
        try:
            wm = get_workspace_manager()
            result = wm.switch_workspace(ws_id)
            new_path = result["workspace"].get("path", "")
            # 更新本桥接的工作目录上下文
            if new_path and os.path.isdir(new_path):
                self.project_path = new_path
                print(f"[Workspace] serve_bridge 工作目录已更新: {new_path}")
            return result
        except Exception as e:
            print(f"[Workspace] 切换工作区失败: {e}")
            return {"error": str(e)}

    def add_workspace(self, path: str, name: str = "") -> dict:
        """添加工作区"""
        try:
            wm = get_workspace_manager()
            entry = wm.add_workspace(path, name)
            return {"workspace": entry}
        except Exception as e:
            print(f"[Workspace] 添加工作区失败: {e}")
            return {"error": str(e)}

    def remove_workspace(self, ws_id: str) -> dict:
        """移除工作区"""
        try:
            wm = get_workspace_manager()
            ok = wm.remove_workspace(ws_id)
            return {"success": ok}
        except Exception as e:
            print(f"[Workspace] 移除工作区失败: {e}")
            return {"success": False, "error": str(e)}

    def save_current_session_to_workspace(self, session_id: str) -> None:
        """将当前会话 ID 保存到当前工作区（切换工作区前调用）"""
        try:
            wm = get_workspace_manager()
            wm.set_current_session_id(session_id)
        except Exception as e:
            print(f"[Workspace] 保存会话到工作区失败: {e}")

    # ==================== 调试管理（供 QWebChannel 调用） ====================

    def debug_start(self, program: str, args: list = None, cwd: str = "") -> dict:
        """启动调试会话"""
        try:
            from debug_session import get_debug_manager
            dm = get_debug_manager()
            return dm.start_debug(program, args or [], cwd or self.project_path)
        except Exception as e:
            print(f"[Debug] 启动失败: {e}")
            return {"success": False, "message": str(e)}

    def debug_stop(self) -> dict:
        """停止调试会话"""
        try:
            from debug_session import get_debug_manager
            dm = get_debug_manager()
            ok = dm.stop_debug()
            return {"success": ok}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def debug_continue(self) -> dict:
        """继续执行"""
        try:
            from debug_session import get_debug_manager
            dm = get_debug_manager()
            ok = dm.continue_execution()
            return {"success": ok}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def debug_pause(self) -> dict:
        """暂停执行"""
        try:
            from debug_session import get_debug_manager
            dm = get_debug_manager()
            ok = dm.pause_execution()
            return {"success": ok}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def debug_step(self, step_type: str) -> dict:
        """单步执行（over/into/out）"""
        try:
            from debug_session import get_debug_manager
            dm = get_debug_manager()
            if step_type == 'over':
                ok = dm.step_over()
            elif step_type == 'into':
                ok = dm.step_into()
            elif step_type == 'out':
                ok = dm.step_out()
            else:
                return {"success": False, "message": f"未知步进类型: {step_type}"}
            return {"success": ok}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def debug_get_variables(self, scope: str = "local") -> dict:
        """获取变量列表"""
        try:
            from debug_session import get_debug_manager
            dm = get_debug_manager()
            return {"variables": dm.get_variables(scope)}
        except Exception as e:
            return {"variables": [], "error": str(e)}

    def debug_get_stack_trace(self) -> dict:
        """获取调用栈"""
        try:
            from debug_session import get_debug_manager
            dm = get_debug_manager()
            return {"frames": dm.get_stack_trace()}
        except Exception as e:
            return {"frames": [], "error": str(e)}

    def debug_evaluate(self, expr: str) -> dict:
        """表达式求值"""
        try:
            from debug_session import get_debug_manager
            dm = get_debug_manager()
            return {"result": dm.evaluate_expression(expr)}
        except Exception as e:
            return {"result": "", "error": str(e)}

    def debug_set_breakpoint(self, file: str, line: int, condition: str = None) -> dict:
        """设置断点"""
        try:
            from debug_session import get_debug_manager
            dm = get_debug_manager()
            s = dm.active_session
            if s:
                bp = s.add_breakpoint(file, line, condition)
                return {"success": True, "breakpoint": {"file": file, "line": line, "id": bp.id}}
            return {"success": False, "message": "无活动调试会话"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def debug_toggle_breakpoint(self, file: str, line: int) -> dict:
        """切换断点"""
        try:
            from debug_session import get_debug_manager
            dm = get_debug_manager()
            s = dm.active_session
            if s:
                added = s.toggle_breakpoint(file, line)
                return {"success": True, "added": added}
            return {"success": False, "message": "无活动调试会话"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def debug_remove_breakpoint(self, file: str, line: int) -> dict:
        """移除断点"""
        try:
            from debug_session import get_debug_manager
            dm = get_debug_manager()
            s = dm.active_session
            if s:
                ok = s.remove_breakpoint(file, line)
                return {"success": ok}
            return {"success": False, "message": "无活动调试会话"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def debug_get_breakpoints(self) -> dict:
        """获取所有断点"""
        try:
            from debug_session import get_debug_manager
            dm = get_debug_manager()
            return {"breakpoints": dm.get_all_breakpoints()}
        except Exception as e:
            return {"breakpoints": [], "error": str(e)}

    def debug_get_state(self) -> dict:
        """获取调试状态"""
        try:
            from debug_session import get_debug_manager
            dm = get_debug_manager()
            return {"state": dm.get_state()}
        except Exception as e:
            return {"state": "idle", "error": str(e)}

    # ==================== 消息持久化（供 QWebChannel 调用） ====================

    def _ensure_db_session(self):
        """确保数据库会话存在，与 Lemon Code session 关联"""
        if self._db_session_id:
            return
        # 用 Lemon Code session_id 或时间戳生成唯一ID
        sid = self._session_id or f"local_{int(time.time())}"
        self._db_session_id = sid
        self._message_store.create_session(
            session_id=sid,
            title=f"会话 {datetime.now().strftime('%m/%d %H:%M')}",
            project_path=self.project_path,
        )
        print(f"[MessageStore] 数据库会话已创建: {sid}", flush=True)

    def list_db_sessions(self, limit: int = 20) -> list:
        """获取历史会话列表"""
        return self._message_store.list_sessions(limit)

    def get_db_messages(self, session_id: str, limit: int = 100) -> list:
        """获取指定会话的消息列表"""
        return self._message_store.get_messages(session_id, limit)

    def search_db_messages(self, keyword: str, limit: int = 50) -> list:
        """搜索历史消息"""
        return self._message_store.search_messages(keyword, limit)

    def delete_db_session(self, session_id: str) -> bool:
        """删除历史会话"""
        return self._message_store.delete_session(session_id)

    def load_last_session_messages(self) -> list:
        """启动时加载最近会话的消息"""
        sessions = self._message_store.list_sessions(limit=1)
        if not sessions:
            return []
        last_session = sessions[0]
        self._db_session_id = last_session['id']
        messages = self._message_store.get_messages(last_session['id'], limit=100)
        print(f"[MessageStore] 已加载最近会话: {last_session['title']} ({len(messages)} 条消息)", flush=True)
        return messages

    # ==================== Ollama 管理（供 QWebChannel 调用） ====================

    def _check_ollama_status(self):
        """定时检测 Ollama 状态"""
        def _do_check():
            status = self._ollama_detector.detect_ollama()
            old_running = self._ollama_status.get("running") if self._ollama_status else None
            self._ollama_status = status
            if old_running is not None and old_running != status["running"]:
                # 状态变化时发布事件
                self._event_bus.publish(EventType.OLLAMA_STATUS_CHANGED, status)
                print(f"[Ollama] 状态变化: running={status['running']}", flush=True)

        t = threading.Thread(target=_do_check, daemon=True)
        t.start()

    def get_ollama_status(self) -> dict:
        """获取 Ollama 状态（供前端调用）"""
        if not self._ollama_status:
            return self._ollama_detector.detect_ollama()
        return self._ollama_status

    def get_ollama_models(self) -> list:
        """获取已安装模型列表"""
        return self._ollama_detector.get_installed_models()

    def recommend_ollama_model(self, task_type: str = "chat") -> dict:
        """推荐模型"""
        return self._ollama_detector.recommend_model(task_type)

    def download_ollama_model(self, model_name: str) -> dict:
        """下载模型（同步，可能较慢）"""
        success = self._ollama_mgr.download_model(model_name)
        return {"success": success, "model": model_name}

    def delete_ollama_model(self, model_name: str) -> dict:
        """删除模型"""
        success, msg = self._ollama_mgr.delete_model(model_name)
        return {"success": success, "message": msg}

    def get_ollama_model_info(self, model_name: str) -> dict:
        """获取模型详细信息"""
        info = self._ollama_mgr.get_model_info(model_name)
        return info or {"error": "无法获取模型信息"}

    # ==================== 代码格式化 + 审查（供 QWebChannel 调用） ====================

    def format_code(self, code: str, language: str = "python") -> dict:
        """格式化代码"""
        result = self._formatter.format_code(code, language)
        return result.to_dict()

    def format_file(self, file_path: str) -> dict:
        """格式化文件"""
        if not os.path.exists(file_path):
            return {"error": "文件不存在"}
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            code = f.read()
        ext = os.path.splitext(file_path)[1].lower()
        lang_map = {'.py': 'python', '.js': 'javascript', '.html': 'html', '.css': 'css'}
        result = self._formatter.format_code(code, lang_map.get(ext, 'generic'))
        if result.changed:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(result.formatted)
        return result.to_dict()

    def review_code(self, code: str, language: str = "python") -> dict:
        """审查代码"""
        issues = self._reviewer.review_code(code, language)
        return {
            "issues": [i.to_dict() for i in issues],
            "count": len(issues),
            "errors": sum(1 for i in issues if i.severity == "error"),
            "warnings": sum(1 for i in issues if i.severity == "warning"),
            "report": self._reviewer.generate_report(issues),
        }

    def review_file(self, file_path: str) -> dict:
        """审查文件"""
        if not os.path.exists(file_path):
            return {"error": "文件不存在"}
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            code = f.read()
        ext = os.path.splitext(file_path)[1].lower()
        lang_map = {'.py': 'python', '.js': 'javascript'}
        issues = self._reviewer.review_code(code, lang_map.get(ext, 'generic'))
        return {
            "issues": [i.to_dict() for i in issues],
            "count": len(issues),
            "errors": sum(1 for i in issues if i.severity == "error"),
            "warnings": sum(1 for i in issues if i.severity == "warning"),
            "report": self._reviewer.generate_report(issues, os.path.basename(file_path)),
            "file": file_path,
        }

    def _auto_reject_dangerous(self, perm_id: str, tool_info: dict, opt_list: list) -> bool:
        """自动拒绝危险操作（打开HTML文件、写入HTML文件等）
        
        Returns:
            True 表示已自动拒绝，False 表示不是危险操作
        """
        tool_kind = tool_info.get('kind', '')
        tool_name = tool_info.get('title', '')
        tool_input = tool_info.get('input', {})
        
        # 检查工具名称或类型中的危险关键词
        name_lower = f"{tool_name} {tool_kind}".lower()
        
        is_dangerous = False
        danger_reason = ""
        
        # 方式1：从 tool_info 的 input 字段直接判断（如果有的话）
        if tool_input and isinstance(tool_input, dict):
            # bash / shell 命令
            cmd = tool_input.get('command', '') or tool_input.get('cmd', '') or ''
            if cmd and isinstance(cmd, str):
                cmd_lower = cmd.lower()
                if ('explorer' in cmd_lower or 'start ' in cmd_lower or 'msedge' in cmd_lower 
                    or 'chrome' in cmd_lower or 'webbrowser' in cmd_lower or 'open ' in cmd_lower) \
                    and '.html' in cmd_lower:
                    is_dangerous = True
                    danger_reason = "打开HTML文件"
            
            # write / edit 工具写 HTML
            file_path = tool_input.get('filePath', '') or tool_input.get('path', '') or ''
            if file_path and isinstance(file_path, str) and file_path.lower().endswith('.html'):
                is_dangerous = True
                danger_reason = "写入HTML文件"
        
        # 方式2：从工具名称/标题/类型判断
        if not is_dangerous:
            # 明确写 HTML 文件的工具
            if (tool_kind == 'file_write' or 'write' in name_lower or '写入' in tool_name) and '.html' in name_lower:
                is_dangerous = True
                danger_reason = "写入HTML文件"
            # 执行命令且包含 explorer + html
            elif ('bash' in name_lower or 'shell' in name_lower or 'command' in name_lower
                  or '命令' in tool_name or '执行' in tool_name) and '.html' in name_lower:
                is_dangerous = True
                danger_reason = "打开HTML文件"
        
        # 方式3：如果信息不足，尝试拉取会话状态获取详情
        if not is_dangerous and self._session_id:
            try:
                r = requests.get(
                    f"{self.base_url}/session/{self._session_id}",
                    timeout=5
                )
                if r.status_code == 200:
                    data = r.json()
                    messages = data.get("messages", [])
                    if messages:
                        last_msg = messages[-1]
                        if last_msg.get("role") == "assistant":
                            parts = last_msg.get("parts", [])
                            for part in parts:
                                if part.get("type") == "tool":
                                    state = part.get("state", {})
                                    if state.get("status") in ("pending", "permission", "running"):
                                        t_input = state.get("input", {})
                                        if t_input and isinstance(t_input, dict):
                                            cmd = t_input.get('command', '') or t_input.get('cmd', '') or ''
                                            file_path = t_input.get('filePath', '') or t_input.get('path', '') or ''
                                            if cmd and isinstance(cmd, str):
                                                cmd_lower = cmd.lower()
                                                if ('explorer' in cmd_lower or 'start ' in cmd_lower 
                                                    or 'msedge' in cmd_lower or 'chrome' in cmd_lower) \
                                                    and '.html' in cmd_lower:
                                                    is_dangerous = True
                                                    danger_reason = "打开HTML文件"
                                                    break
                                            if file_path and isinstance(file_path, str) and file_path.lower().endswith('.html'):
                                                is_dangerous = True
                                                danger_reason = "写入HTML文件"
                                                break
            except Exception:
                pass
        
        # 方式4：tool_info 中其他可能包含命令的字段（做一次全面扫描）
        if not is_dangerous and tool_info and isinstance(tool_info, dict):
            import json
            try:
                info_str = json.dumps(tool_info, ensure_ascii=False).lower()
                if '.html' in info_str and ('explorer' in info_str or 'write' in info_str or 'file' in info_str):
                    is_dangerous = True
                    danger_reason = "HTML文件操作"
            except Exception:
                pass
        
        if not is_dangerous:
            return False
        
        # 找到拒绝选项
        reject_choice = None
        for opt in opt_list:
            opt_name = opt.get('name', '').lower()
            opt_id = opt.get('id', '')
            if '拒绝' in opt_name or '取消' in opt_name or '否' in opt_name or 'deny' in opt_name or 'reject' in opt_name:
                reject_choice = opt_id
                break
        
        # 如果没找到明确的拒绝选项，用第二个选项（通常是拒绝/取消）
        if not reject_choice and len(opt_list) >= 2:
            reject_choice = opt_list[1].get('id', '')
        
        if reject_choice:
            try:
                self.respond_permission(perm_id, reject_choice)
                self.status_received.emit(
                    f"<span style='color:Lemon.ACCENT_ORANGE;'>{{ICON:shield}} 已自动拦截: {danger_reason}（右侧栏直接渲染图表）</span>"
                )
                return True
            except Exception as e:
                print(f"[Auto-reject] 失败: {e}")
                return False
        
        return False

    def _try_auto_approve(self, perm_id: str, tool_info: dict, opt_list: list) -> bool:
        """尝试自动同意权限请求
        
        Returns:
            True 表示已自动同意，False 表示需要用户确认
        """
        if not self._trust_mode:
            return False
        
        tool_kind = tool_info.get('kind', '')
        tool_name = tool_info.get('title', '')
        
        # 判断是否应该自动同意
        should_approve = False
        if not self._auto_approve_tools:
            # 空集合表示自动同意所有
            should_approve = True
        elif tool_kind in self._auto_approve_tools:
            should_approve = True
        
        if not should_approve:
            return False
        
        # 找到默认的同意选项（通常是第一个或名称包含"同意"/"允许"/"确认"的选项）
        approve_choice = None
        for opt in opt_list:
            opt_name = opt.get('name', '').lower()
            opt_id = opt.get('id', '')
            if '同意' in opt_name or '允许' in opt_name or '确认' in opt_name or '是' in opt_name:
                approve_choice = opt_id
                break
        
        # 如果没找到明确的同意选项，使用第一个kind为primary或默认的选项
        if not approve_choice and opt_list:
            for opt in opt_list:
                if opt.get('kind') == 'primary':
                    approve_choice = opt.get('id', '')
                    break
            if not approve_choice:
                approve_choice = opt_list[0].get('id', '')
        
        if approve_choice:
            # 记录历史
            self._permission_history.append({
                'time': time.time(),
                'tool': tool_name,
                'auto_approved': True
            })
            # 自动响应
            try:
                self.respond_permission(perm_id, approve_choice)
                self.status_received.emit(
                    f"<span style='color:Lemon.ACCENT_BLUE;'>{{ICON:shield}} 自动同意: {self._escape_html(str(tool_name))}</span>"
                )
                return True
            except Exception as e:
                print(f"[Auto-approve] 失败: {e}")
                return False
        
        return False
    
    def set_mode(self, mode_id: str):
        """切换模式（通过配置 API）"""
        try:
            requests.patch(
                f"{self.base_url}/config",
                json={"mode": mode_id},
                timeout=10
            )
            self.mode_changed.emit(mode_id)
        except Exception as e:
            self.error_occurred.emit(f"模式切换失败: {e}")
    
    def switch_model(self, model_id: str):
        """切换模型"""
        try:
            requests.patch(
                f"{self.base_url}/config",
                json={"model": model_id},
                timeout=10
            )
            self.status_received.emit(f"<span style='color:Lemon.ACCENT_GREEN;'>{{ICON:loader-circle}} 模型切换: {model_id}</span>")
        except Exception as e:
            self.error_occurred.emit(f"模型切换失败: {e}")
    
    def get_usage_info(self):
        """获取用量信息（token 消耗）"""
        try:
            if self._session_id:
                r = requests.get(
                    f"{self.base_url}/session/{self._session_id}",
                    timeout=5
                )
                if r.status_code == 200:
                    data = r.json()
                    usage = data.get("usage", {})
                    if usage:
                        self.usage_info.emit(usage)
                        return usage
        except Exception:
            pass
        return None
    
    def cancel_current_task(self):
        """取消当前任务"""
        if self._session_id:
            try:
                requests.post(
                    f"{self.base_url}/session/{self._session_id}/abort",
                    timeout=10
                )
            except Exception:
                pass
    
    # ================================================================
    # 工具方法
    # ================================================================
    
    @staticmethod
    def _escape_html(text: str) -> str:
        return (str(text)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&#39;'))
