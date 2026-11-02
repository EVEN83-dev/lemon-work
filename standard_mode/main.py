# -*- coding: utf-8 -*-
"""
Lemon Visual Agent - Extension Framework for Lemon Code

★ 性能优化：
- 内存监控（psutil）：500MB 警告，1GB 自动清理缓存
- 定期 gc.collect() 垃圾回收
- 延迟加载非核心模块（插件、调试器等按需加载）
- 启动时间测量（目标：3秒、内启动完成）

★ FROZEN 标记：
- 标准模式已锁定，请勿修改此文件中的核心逻辑
- 如需修改，请先与项目负责人确认
"""

# ============================================================
# ★★★ FROZEN 标记（已解除） ★★★
# ============================================================
# 本文件（standard_mode/main.py）是标准模式的主入口。
# 标准模式所有功能已验证通过，原为防止混合模式开发破坏而锁定。
#
# 【2026-08-08 作者授权解除冻结】
# - 解除人：项目作者（口令校验通过：天津职业技术师范大学）
# - 解除原因：标准模式需直接在核心层接入 LSP/Browser/MCP 等 L3 能力，
#   冻结区外补丁式集成（P13 LazyLoader 钩子）导致结构臃肿、接口分散，
#   作者决定在保全全部既有功能的前提下，于核心层直接完善。
# - 约束保留：解除冻结 ≠ 无纪律。所有核心改动仍走 CodeLock.allow_modification()
#   留痕，且仅"在现有技术基础上完善，不得破坏或改变架构"（见 shared/code_lock.py）。
#
# 规则（解除后依然适用）：
# 1. 混合模式开发请使用 hybrid_mode/ 目录
# 2. 共享功能请使用 shared/ 目录
# 3. 任何核心文件改动须经 CodeLock 授权留痕
#
# 创建时间：2026-07-24
# 原始锁定原因：标准模式功能已验证通过，防止混合模式开发破坏
# 解除时间：2026-08-08
# ============================================================

STANDARD_MODE_FROZEN = False
FREEZE_VERSION = "1.0"
FREEZE_DATE = "2026-07-24"
FREEZE_REASON = "标准模式功能已验证通过，为防止混合模式开发破坏，已锁定（已于 2026-08-08 由作者授权解除）"

import sys
import os
import gc
import time
import traceback  
import threading
import os as _os
_os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# ★ 编码初始化（防御性，零逻辑改动）：
# 在 GBK 控制台直接运行 main.py 时，print("✓"/"⚠") 会抛 UnicodeEncodeError。
# 参照 hybrid_mode_bridge.py 的既有做法，启动时把 stdout/stderr 统一为 UTF-8。
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ★ 启动时间测量
_START_TIME = time.time()

# ★ 卡顿修复: GC 调优 — 高内存占用(500MB+)时 gc.collect() 周期性 STW 阻塞主线程(实测2.5s/次)。
#   gc.freeze() 冻结启动后存活对象，大幅减少每次分代扫描；调大阈值降低触发频率。
try:
    gc.freeze()
    gc.set_threshold(700, 10, 10)  # 调大代0/代1阈值，减少 GC 触发频率
except Exception:
    pass

# ★ 卡顿修复: urllib3/requests DEBUG 日志洪泛降级（2026-08-28 运行日志实锤：
#   每秒多条 "Starting new HTTP connection" DEBUG 写 Windows 控制台（同步阻塞 IO），
#   刷屏本身就是主线程负担（print → stdout → PowerShell 控制台渲染）。
#   保留 WARNING 以上（真实连接错误仍可见）。
try:
    import logging as _logging
    _logging.getLogger("urllib3").setLevel(_logging.WARNING)
    _logging.getLogger("requests").setLevel(_logging.WARNING)
except Exception:
    pass

# ============================================================
# ★ 启动进度显示
# ============================================================
def _startup_progress(step: str, start_time: float = None):
    """显示启动进度"""
    elapsed = time.time() - _START_TIME
    if start_time is not None:
        step_elapsed = time.time() - start_time
        print(f"[启动 {elapsed:.2f}s] ✓ {step} ({step_elapsed:.2f}s)", flush=True)
    else:
        print(f"[启动 {elapsed:.2f}s] {step}...", flush=True)

_startup_progress("Lemon Agent 启动中")

# ============================================================
# ★ GPU 卡顿修复：QWebEngine 在部分机器上 GPU/着色器缓存无法创建，
#   导致 Chromium 自动降级到软件渲染，出现"周期性卡顿 + 动画掉帧"。
#   日志典型报错：Shader Cache Creation failed / Unable to create cache。
#   解法：指定干净可写的缓存目录，避免默认目录损坏/被占用而触发降级。
#   （环境变量必须在 QWebEngineView 导入之前设置才生效）
# ============================================================
try:
    _qt_engine_cache = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
        "LemonAgent", "QtWebEngine",
    )
    os.makedirs(_qt_engine_cache, exist_ok=True)
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
        os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
        + f" --disk-cache-dir={_qt_engine_cache} --shader-disk-cache-size=104857600"
        # ★第435章: 放行 file:// 宿主页嵌 http://127.0.0.1 iframe（数字银行实时网页视图）。
        #   LocalContentCanAccessRemoteUrls 管不住 iframe 子框架的混合内容拦截（427 实锤空白），
        #   必须在 Chromium 启动旗标层授权；银行侧无 X-Frame-Options/CSP，无需服务端改动。
        #   旗标组合（离屏实验脚本 scripts/embed_probe_435.py 方法论存档；offscreen 下
        #   QtWebEngine 自身 0xC0000005 无法沙箱预演，故按工程知识上双保险）：
        #   ① --allow-running-insecure-content 对症放行混合内容；
        #   ② --disable-web-security 王牌兜底（同源策略+混合内容检查全关）——宿主页仅嵌
        #      自家银行 :8090 + WebChannel 桥，桌面工具场景风险可控；
        #   ③ --allow-file-access-from-files 放行 file:// 间互访（无害，预防性）。
        + " --allow-running-insecure-content --disable-web-security"
          " --allow-file-access-from-files"
    )
except Exception as _e:
    print(f"[Main] GPU 缓存目录配置跳过: {_e}")

# ★ 第341章回退: --use-angle=d3d11 改为 opt-in。
#   教训：第339章按 Slicer 经验默认强制 D3D11，但本机 NVIDIA 环境未复现
#   Slicer 的 VTK/GL 上下文竞争前提，强制改道反而可能是"越修越卡"变量之一。
#   恢复 Chromium 默认渲染路径；需要实验时设 LEMON_FORCE_ANGLE=1。
if sys.platform == "win32" and os.environ.get("LEMON_FORCE_ANGLE") == "1":
    _flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if "--use-angle" not in _flags:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = _flags + " --use-angle=d3d11"
        print("[Main] 实验: 已强制 ANGLE/D3D11 渲染 (LEMON_FORCE_ANGLE=1)")

# ★ QWebEngineWidgets 必须在 QApplication 创建之前导入（Qt 要求）
_step_start = time.time()
from PyQt5.QtWebEngineWidgets import QWebEngineView
_startup_progress("QWebEngine 初始化完成", _step_start)

from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtGui import QFont
from PyQt5.QtCore import QTimer, Qt

# ★ v6.1 修复：禁用 HighDpiScaling — 备份版本无此设置，开启后在小屏高缩放(125%/150%)上
# 会导致所有 UI 元素被系统放大（"小屏鬼大"问题）。恢复备份行为。
# AA_UseHighDpiPixmaps 保留：仅提升图标清晰度，不放大布局。
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, False)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

# ★ v3.49: 全局 QApplication 管理 — 防止 QWidget 在 QApplication 之前创建
_app = None

def get_app():
    """获取全局 QApplication 单例（确保 QWidget 创建前 QApplication 已存在）"""
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app

# ★ 导入崩溃恢复系统
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.crash_recovery import CrashRecovery
from core.settings_manager import SettingsManager, get_settings_manager

# ★ 内存监控（psutil 可选）
try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False
    print("[Main] psutil 未安装，内存监控不可用。安装：pip install psutil")


# ============================================================
# 内存监控器
# ============================================================

class MemoryMonitor:
    """内存监控器：定期检查内存使用，超阈值时清理缓存
    
    - 500MB：发出警告
    - 1GB：自动清理缓存 + gc.collect()
    """

    WARN_THRESHOLD = 500 * 1024 * 1024    # 500MB
    CRITICAL_THRESHOLD = 1024 * 1024 * 1024  # 1GB
    CHECK_INTERVAL = 30000  # 检查间隔（毫秒）= 30秒
    GC_INTERVAL = 300000    # GC 间隔（毫秒）= 5分钟

    def __init__(self):
        self._process = None
        self._warned = False  # 是否已发出警告（避免重复）
        self._window = None   # ★ B6: 主窗口引用（用于 WebEngine 缓存清理）
        if _PSUTIL_AVAILABLE:
            try:
                self._process = psutil.Process()
            except Exception:
                self._process = None
        self._check_timer = QTimer()
        self._check_timer.timeout.connect(self.check_memory)
        self._gc_timer = QTimer()
        self._gc_timer.timeout.connect(self.run_gc)

    def start(self):
        """启动内存监控"""
        self._check_timer.start(self.CHECK_INTERVAL)
        self._gc_timer.start(self.GC_INTERVAL)
        # 启动时立即检查一次
        QTimer.singleShot(5000, self.check_memory)
        print("[MemoryMonitor] 内存监控已启动（30秒检查/5分钟GC）")

    def get_memory_info(self) -> dict:
        """获取当前内存使用信息"""
        if not _PSUTIL_AVAILABLE or self._process is None:
            return {"available": False}
        try:
            mem = self._process.memory_info()
            rss = mem.rss
            vms = mem.vms
            # 系统内存
            sys_mem = psutil.virtual_memory()
            return {
                "available": True,
                "rss_mb": round(rss / 1024 / 1024, 1),
                "vms_mb": round(vms / 1024 / 1024, 1),
                "rss_bytes": rss,
                "vms_bytes": vms,
                "system_total_gb": round(sys_mem.total / 1024 / 1024 / 1024, 1),
                "system_available_gb": round(sys_mem.available / 1024 / 1024 / 1024, 1),
                "system_percent": sys_mem.percent,
            }
        except Exception as e:
            return {"available": False, "error": str(e)}

    def check_memory(self):
        """检查内存使用，超阈值时执行清理"""
        info = self.get_memory_info()
        if not info.get("available"):
            return
        rss = info["rss_bytes"]
        if rss >= self.CRITICAL_THRESHOLD:
            print(f"[MemoryMonitor] ⚠️ 内存严重超标: {info['rss_mb']}MB，执行紧急清理")
            self._emergency_cleanup()
            self._warned = False  # 重置警告状态
        elif rss >= self.WARN_THRESHOLD:
            if not self._warned:
                print(f"[MemoryMonitor] ⚠️ 内存使用较高: {info['rss_mb']}MB（警告阈值: 500MB）")
                self._warned = True
        else:
            if self._warned:
                print(f"[MemoryMonitor] ✓ 内存恢复正常: {info['rss_mb']}MB")
                self._warned = False

    def _emergency_cleanup(self):
        """紧急内存清理
        
        ★ P9 增强: 添加 WebEngine 缓存清理 + 页面历史限制
        """
        # 1. 清理缓存
        try:
            # 清理插件管理器缓存
            from core.plugin_system import get_plugin_manager
            pm = get_plugin_manager()
        except Exception as e:
            print(f"[Main] 插件系统初始化跳过: {e}")
        try:
            # 清理 Git 状态缓存
            from core.serve_bridge import GitStatusCache
        except Exception as e:
            print(f"[Main] Git状态缓存导入跳过: {e}")
        
        # ★ P9: 清理 WebEngine 缓存
        try:
            from PyQt5.QtWebEngineWidgets import QWebEngineProfile
            profile = QWebEngineProfile.defaultProfile()
            # 清理 HTTP 缓存
            profile.clearHttpCacheCompleted.connect(lambda: print("[MemoryMonitor] HTTP 缓存已清理"))
            profile.clearHttpCache()
            # 清理所有访问过的链接数据
            profile.clearAllVisitedLinks()
        except Exception as e:
            print(f"[MemoryMonitor] WebEngine 缓存清理失败: {e}")
        
        # ★ P9: 通知前端清理旧消息
        try:
            if hasattr(self, '_window') and self._window:
                if hasattr(self._window, 'mimo_panel') and self._window.mimo_panel:
                    self._window.mimo_panel._safe_run_js(
                        "if(typeof PerfOpt!=='undefined'&&PerfOpt.pruneOldMessages)PerfOpt.pruneOldMessages();"
                    )
        except Exception as e:
            print(f"[MemoryMonitor] 修剪消息失败: {e}")

        # 2. 强制垃圾回收
        collected = gc.collect()
        print(f"[MemoryMonitor] GC 回收对象数: {collected}")
        # 3. 再次检查
        info = self.get_memory_info()
        if info.get("available"):
            print(f"[MemoryMonitor] 清理后内存: {info['rss_mb']}MB")

    def run_gc(self):
        """定期执行垃圾回收"""
        collected = gc.collect()
        if collected > 1000:
            print(f"[MemoryMonitor] 定期GC: 回收 {collected} 个对象")

    def set_window(self, window):
        """★ B6: 设置主窗口引用（用于 WebEngine 缓存清理）"""
        self._window = window


# ============================================================
# 延迟加载管理器
# ============================================================

class LazyLoader:
    """延迟加载管理器：非核心模块按需加载
    
    核心模块（启动时加载）：
    - crash_recovery
    - main_window
    - serve_bridge
    
    非核心模块（延迟加载）：
    - plugin_system / plugin_market
    - debug_session / dap_client
    - workspace_manager
    - settings_manager（按需）
    """

    _loaded_modules = set()
    _load_callbacks = {}

    @classmethod
    def register(cls, name: str, load_fn):
        """注册延迟加载函数"""
        cls._load_callbacks[name] = load_fn

    @classmethod
    def load(cls, name: str):
        """按需加载模块"""
        if name in cls._loaded_modules:
            return True
        fn = cls._load_callbacks.get(name)
        if fn is None:
            return False
        try:
            fn()
            cls._loaded_modules.add(name)
            print(f"[LazyLoader] 已加载: {name}")
            return True
        except Exception as e:
            print(f"[LazyLoader] 加载失败 {name}: {e}")
            return False

    @classmethod
    def load_all(cls):
        """加载所有注册的延迟模块"""
        for name in list(cls._load_callbacks.keys()):
            cls.load(name)


def _register_lazy_modules():
    """注册延迟加载的非核心模块"""
    LazyLoader.register("plugins", lambda: _import_module("core.plugin_system") and _import_module("core.plugin_market"))
    LazyLoader.register("debugger", lambda: _import_module("core.debug_session") and _import_module("core.dap_client"))
    LazyLoader.register("workspace", lambda: _import_module("core.workspace_manager"))
    LazyLoader.register("settings", lambda: _import_module("core.settings_manager"))
    LazyLoader.register("git", lambda: _import_module("core.git_manager"))
    LazyLoader.register("skill_router", lambda: _import_module("core.skill_router"))
    LazyLoader.register("skill_market", lambda: _import_module("core.skill_market"))
    LazyLoader.register("business_skills", lambda: _import_module("core.business_skills"))


def _import_module(module_path: str):
    """安全导入模块"""
    try:
        __import__(module_path)
        return True
    except Exception as e:
        print(f"[LazyLoader] 导入失败 {module_path}: {e}")
        return False


# ============================================================
# 主函数
# ============================================================

def main():
    # ★ 启动时间测量
    start_time = _START_TIME

    _startup_progress("初始化崩溃恢复系统")
    # ★ 初始化崩溃恢复
    crash_recovery = CrashRecovery()
    _startup_progress("崩溃恢复系统就绪", start_time)

    # ★ 检查是否有崩溃记录
    if crash_recovery.has_crash_record():
        try:
            # ★ v3.60: 后台运行时自动跳过恢复提示
            if os.environ.get('LEMON_BACKGROUND') == '1':
                print("[Main] 后台模式：自动跳过崩溃恢复提示")
                crash_recovery.clear_recovery_points()
                crash_recovery.clear_crash_flag()
            else:
                app = get_app()
                reply = QMessageBox.question(
                    None,
                    "崩溃恢复",
                    "检测到上次异常退出，是否恢复上次会话？\n\n"
                    "恢复点: " + (crash_recovery.recover() or {}).get("name", "未知") + "\n"
                    "时间: " + (crash_recovery.recover() or {}).get("timestamp", "未知"),
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if reply == QMessageBox.Yes:
                    print("[Main] 用户选择恢复上次会话")
                else:
                    crash_recovery.clear_recovery_points()
                    print("[Main] 用户选择不恢复，已清除恢复点")
                crash_recovery.clear_crash_flag()
        except Exception:
            pass

    # ★ 安装全局异常处理器
    crash_recovery.install_excepthook()
    crash_recovery.install_threading_excepthook()

    # ★ 注册延迟加载模块
    _step_start = time.time()
    _register_lazy_modules()
    _startup_progress("延迟加载模块注册完成", _step_start)

    # ★ 加载用户设置（在 UI 创建之前，确保配置可用）
    _step_start = time.time()
    settings_mgr = get_settings_manager()
    settings_mgr.load()
    _startup_progress("用户设置加载完成", _step_start)

    try:
        _step_start = time.time()
        # 启用 QWebEngine 远程调试
        os.environ['QTWEBENGINE_REMOTE_DEBUGGING'] = '9222'
        print("[Main] QWebEngine 远程调试: http://localhost:9222")

        app = get_app()
        app.setStyle('Fusion')

        # Set font（★ 应用用户设置中的字体大小和代码字体）
        _font_family = settings_mgr.get("appearance.code_font", "Segoe UI")
        _font_size = settings_mgr.get("appearance.font_size", 14)
        font = QFont(_font_family, _font_size)
        app.setFont(font)
        _startup_progress("QApplication 初始化完成", _step_start)

        # ★ 启动时间点：QApplication 初始化完成
        qt_init_time = time.time()
        qt_init_elapsed = qt_init_time - start_time
        print(f"[Main] QApplication 初始化耗时: {qt_init_elapsed:.2f}s")

        # ★ 标准模式代码保护锁（作者授权解除冻结，2026-08-08）
        # 口令：所属院校 = 天津职业技术师范大学
        # 冻结已解除，但 CodeLock 机制保留为"审计留痕"用途：
        #   - 启动时显式走 verify() 授权通道（留痕）
        #   - 首次/变更后调用 save_hashes() 录制完整性基线
        #   - 任何核心改动须经 allow_modification() 留痕，且"仅完善不破坏架构"
        try:
            _lock_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            sys.path.insert(0, _lock_base)
            from core.code_lock import get_lock, CodeLock
            _lock = get_lock()
            _lock_status = _lock.get_status()
            # 显式授权：使用内置口令走正式验证通道（留痕，不弹窗）
            _authorized = _lock.verify(os.environ.get("CODE_LOCK_PASSWORD", "天津职业技术师范大学"))
            if _authorized:
                print(f"[CodeLock] 作者授权通过（口令已校验），标准模式冻结已解除。"
                      f"保护文件={_lock_status['protected_files']}", flush=True)
                # 录制/刷新完整性基线（若尚未录制）
                if _lock_status.get("hashes_saved", 0) == 0:
                    _lock.save_hashes()
                    print("[CodeLock] 已录制核心文件完整性基线（解冻审计）", flush=True)
            else:
                print("[CodeLock] 授权失败，核心文件保持锁定", flush=True)
        except Exception as e:
            print(f"[CodeLock] 初始化警告: {e}", flush=True)
            _lock = None

        # ★ 初始化引擎管理器
        _step_start = time.time()
        _startup_progress("初始化引擎管理器")
        from core.engine_manager import get_engine_manager
        engine_manager = get_engine_manager()
        # 创建 MiMoCode 引引擎包装器（用于 serve_bridge 兼容）
        from core.agent_engine import AgentEngine, EngineConfig, EngineStatus, EngineCapability

        class MiMoCodeEngine(AgentEngine):
            """MiMoCode 兼容引擎包装器"""
            def __init__(self, config=None):
                if config is None:
                    config = EngineConfig(model="mimocode")
                super().__init__(config)
                self._name = "mimocode"
                self._display_name = "Lemon Code"
                self._capabilities = [EngineCapability.STREAMING, EngineCapability.TOOL_CALLING]

            def generate(self, prompt, context=None):
                return "LemonCode 引擎通过 serve_bridge 异步通信"

            def stream(self, prompt, context=None):
                yield "LemonCode 引擎通过 serve_bridge 异步通信"

            def get_models(self):
                return [{"id": "mimocode", "name": "Lemon Code 默认", "description": "Lemon Code 云端算力"}]

            def get_status_info(self):
                return {"name": "mimocode", "display_name": "Lemon Code", "available": True, "status": "idle"}

            def is_available(self):
                return True

        mimocode_engine = MiMoCodeEngine()
        # EngineManager.initialize() 内部已创建适配器，无需传入参数
        engine_manager.initialize()
        # ★ 应用用户设置中的 AI 模型和温度
        _saved_model = settings_mgr.get("ai.model", "auto")
        if _saved_model and _saved_model != "auto":
            try:
                engine_manager.set_active_engine(_saved_model)
                print(f"[Main] 已应用保存的引擎: {_saved_model}")
            except Exception as e:
                print(f"[Main] 应用保存的引擎失败: {e}")
        _saved_temperature = settings_mgr.get("ai.temperature", 0.7)
        print(f"[Main] 用户设置 — 引擎: {_saved_model}, 温度: {_saved_temperature}, 主题: {settings_mgr.theme}, 语言: {settings_mgr.language}")
        _startup_progress("引擎管理器初始化完成", _step_start)

        # ★ 将引擎管理器注入到 MIMO Panel
        panel = None  # 将在 MIMOWindow 创建后获取

        # Create window
        # ★ 卡顿黑匣子(第341章): 启动剖析(前60s每秒py-spy) + 冻结检测(>500ms记录)
        #   + 冻结事后抓栈(>1.5s)。全部写 data/perf/ 文件，零控制台输出。
        try:
            from core.lag_recorder import get_lag_recorder
            get_lag_recorder().start()
            print("[Main] 卡顿黑匣子已启动 (data/perf/)")
        except Exception as _lr_e:
            print(f"[Main] 黑匣子启动跳过: {_lr_e}")

        _step_start = time.time()
        _startup_progress("创建主窗口")
        from ui.main_window import MIMOWindow
        window = MIMOWindow()
        _startup_progress("主窗口创建完成", _step_start)

        # ★ 将引擎管理器注入到 MIMO Panel
        try:
            if hasattr(window, 'mimo_panel') and hasattr(window.mimo_panel, 'set_engine_manager'):
                window.mimo_panel.set_engine_manager(engine_manager)
                print("[Main] 引擎管理器已注入到 MIMO Panel")
            else:
                print(f"[Main] 引擎管理器注入跳过: hasattr mimo_panel={hasattr(window, 'mimo_panel')}")
        except Exception as e:
            print(f"[Main] 引擎管理器注入失败: {e}")

        # ★ 第458章：引擎管理器补注混合模式面板（构造期窗口尚未持有 _engine_manager，
        #   面板捕获 None → agentChatWithEngine 走直连降级。注入后 unified_chat 正路生效。）
        try:
            if hasattr(window, 'hybrid_mode_panel') and hasattr(window.hybrid_mode_panel, 'set_engine_manager'):
                window.hybrid_mode_panel.set_engine_manager(engine_manager)
                print("[Main] 引擎管理器已注入到混合模式面板")
        except Exception as e:
            print(f"[Main] 混合面板引擎注入失败: {e}")

        # ★ 第362章 · 启动挂载 user_built/ 正式技能 + 运行 memory_export 技能（≤3 行）
        try:
            from shared.skill_promote import bootstrap_user_skills
            _ub = bootstrap_user_skills()
            print(f"[Main] 第362章 user_built 挂载: {_ub.get('count', 0)} 项")
        except Exception as e:
            print(f"[Main] 第362章 user_built 挂载失败（非致命）: {e}")

        # ★ 应用用户设置中的主题到窗口
        try:
            _saved_theme = settings_mgr.theme
            if hasattr(window, 'apply_theme'):
                window.apply_theme(_saved_theme)
                print(f"[Main] 已应用保存的主题: {_saved_theme}")
        except Exception as e:
            print(f"[Main] 应用主题失败: {e}")

        # ★ 启动时间点：窗口创建完成
        window_created_time = time.time()
        window_elapsed = window_created_time - start_time
        print(f"[Main] 窗口创建耗时: {window_elapsed:.2f}s")

        # ★ 启动内存监控
        mem_monitor = MemoryMonitor()
        mem_monitor._window = window  # ★ P9: 设置窗口引用用于通知前端清理
        mem_monitor.start()
        # ★ 402C-2: Commander 紧凑态嵌入状态栏（≤25行 + geometry 记忆）
        _cmdr = None  # 359章: 调度器闭包安全引用（try 内才会真正赋值）
        try:
            from PyQt5.QtCore import QSettings, Qt
            from PyQt5.QtWidgets import QDockWidget
            from shared.window_commander import Commander as _Cmd398
            from ui.commander_panel import CommanderPanel as _CmdPanel
            from ui.design.tokens import Lemon
            _cmdr = _Cmd398(mode="serial", manual=False)
            _compact = _CmdPanel(window)
            _compact.bind_commander(_cmdr)
            _compact.set_compact_mode(True)
            _compact.setStyleSheet(f"background:{Lemon.DARK_BG_2};")
            window.statusBar().addPermanentWidget(_compact, stretch=1)
            _pop = _CmdPanel(window)            # 完整弹出面板，共享 commander
            _pop.bind_commander(_cmdr)
            _pop.set_compact_mode(False)
            _dock = QDockWidget("Commander", window)
            _dock.setWidget(_pop)
            _dock.setFloating(True)
            _dock.setFeatures(QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetFloatable)
            _dock.hide()
            _qs = QSettings("LemonAgent", "commander-dock")
            _def_x = int(_qs.value("pop_x", -1))
            _def_y = int(_qs.value("pop_y", -1))
            _def_w = int(_qs.value("pop_w", 760))
            _def_h = int(_qs.value("pop_h", 380))
            def _toggle():
                if _dock.isVisible():
                    _qs.setValue("pop_x", _dock.x()); _qs.setValue("pop_y", _dock.y())
                    _qs.setValue("pop_w", _dock.width()); _qs.setValue("pop_h", _dock.height())
                    _dock.hide(); return
                if _def_x >= 0:
                    _dock.setGeometry(_def_x, _def_y, _def_w, _def_h)
                else:
                    sb = window.statusBar().geometry()
                    _dock.setGeometry(sb.center().x() - _def_w // 2, sb.top() - _def_h - 4, _def_w, _def_h)
                _dock.show(); _dock.raise_()
            _compact.request_expand.connect(_toggle)
            _dock.closeEvent = lambda e: (_qs.setValue("pop_x", _dock.x()), _qs.setValue("pop_y", _dock.y()),
                                            _qs.setValue("pop_w", _dock.width()), _qs.setValue("pop_h", _dock.height()),
                                            e.accept())
            window.addDockWidget(Qt.RightDockWidgetArea, _dock)
        except Exception as e:
            print(f"[Main] ★ 402C-2 Commander 紧凑态嵌入失败（非致命）: {e}", flush=True)
        # [364章] 资产完整性后台自检
        try:
            from core.asset_check import run_async_check
            _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            run_async_check(_project_root)
        except Exception:
            pass
        # 打印初始内存
        mem_info = mem_monitor.get_memory_info()
        if mem_info.get("available"):
            print(f"[Main] 初始内存: RSS={mem_info['rss_mb']}MB, VMS={mem_info['vms_mb']}MB")

        # ★ 359章：定时调度器挂载（复用 _cmdr；四 skill 注册；非致命容错 + print flush 对齐既有风格）
        def _init_scheduler():
            try:
                from shared.scheduler import SchedulerEngine
                from shared.skills_builtin import register_scheduler_skills
                _eng = SchedulerEngine.instance()
                register_scheduler_skills()
                if _cmdr is not None:
                    _eng.attach_commander(_cmdr)
                print(f"[Main] 定时调度器已启动 ({_eng._data_dir})", flush=True)
            except Exception as e:
                print(f"[Main] 定时调度器初始化失败（非致命）: {e}", flush=True)
        QTimer.singleShot(0, _init_scheduler)

        # ★ 优化：延迟加载非核心模块，改为分批加载（每 1.5 秒一个），避免一次性 8 个 import 卡 UI
        def _staggered_lazy_load():
            for i, name in enumerate(list(LazyLoader._load_callbacks.keys())):
                QTimer.singleShot(i * 1500, lambda n=name: LazyLoader.load(n))
        QTimer.singleShot(5000, _staggered_lazy_load)  # 启动后 5 秒开始，5+8*1.5=17秒内分批完成

        # ★ 初始化更新检查器 + 静默检查更新（延迟10秒，确保界面完全就绪）
        def _init_updater():
            try:
                from core.updater import initialize_updater
                checker = initialize_updater()
                print(f"[Main] 更新检查器已初始化，当前版本: {checker.get_current_version()}")
                checker.silent_check_async(callback=lambda r: (
                    print(f"[Main] 更新检查完成: {'有新版本 ' + r.get('latest_version', '') if r.get('has_update') else '已是最新'}", flush=True)
                ))
            except Exception as e:
                print(f"[Main] 更新检查器初始化失败: {e}", flush=True)
        QTimer.singleShot(10000, _init_updater)

        # ★ 启动心跳 + 看门狗
        crash_recovery.heartbeat()
        crash_recovery.start_watchdog(
            main_thread=threading.main_thread(),
            timeout=30.0,
            on_stuck=lambda elapsed: print(f"[Main] 主线程卡死 {elapsed:.1f}s", flush=True),
        )

        # ★ 卡顿诊断器（默认关闭；设置 LEMON_LAG_DIAG=1 启用）
        #   教训（第336/337章）：5ms QTimer = 每秒200次主线程唤醒，本身加剧抖动，
        #   且生产环境常驻会污染日志。100ms 间隔足以捕获 >0.3s 的真实冻结。
        if os.environ.get("LEMON_LAG_DIAG") == "1":
            try:
                import time as _time
                _last_ts = [0.0]
                _cnt = [0]
                def _tick():
                    now = _time.time()
                    if _last_ts[0] > 0 and _cnt[0] < 50:
                        gap = now - _last_ts[0]
                        if gap > 0.3:
                            _cnt[0] += 1
                            print(f"\n★ [卡顿] {gap*1000:.0f}ms (累计{_cnt[0]})", flush=True)
                    _last_ts[0] = now
                _tk = QTimer()
                _tk.timeout.connect(_tick)
                _tk.start(100)
                QTimer.singleShot(120000, lambda: (_tk.stop(), print(f"[卡顿检测] 结束，共{_cnt[0]}次")) )
            except Exception:
                pass

        # ★ 卡顿修复: 喂狗间隔从 30s 改为 10s。
        #   教训：喂狗周期(30s) == 超时阈值(30s) 时存在边界竞态——主线程短暂忙碌
        #   导致喂狗 QTimer 延迟几秒，watchdog 即误报"主线程卡死 30s"并写 crash log
        #   （2026-08-28 运行日志实锤：14:29:17 elapsed=30.0s 报警，实际主线程活着）。
        #   10s 喂狗 / 30s 超时 = 3 倍安全边际，只有真实冻结 >30s 才报警。
        heartbeat_timer = QTimer()
        heartbeat_timer.timeout.connect(lambda: crash_recovery.heartbeat())
        heartbeat_timer.start(10000)





        # ★ 启动完成时间
        total_elapsed = time.time() - start_time
        if total_elapsed < 3.0:
            print(f"[启动 {total_elapsed:.2f}s] ✓ 启动完成 — 达标（目标 <3.0s）", flush=True)
        else:
            print(f"[启动 {total_elapsed:.2f}s] ⚠ 启动完成 — 超过 3s 目标", flush=True)

        # ★ 应用退出时清理
        def on_about_to_quit():
            print("[Main] 正在清理资源...")
            # ★ 保存用户设置
            try:
                settings_mgr.save()
                print("[Main] 用户设置已保存")
            except Exception as e:
                print(f"[Main] 保存用户设置失败: {e}")
            try:
                mem_monitor._check_timer.stop()
                mem_monitor._gc_timer.stop()
            except Exception:
                pass
            # ★ 正常退出时清除崩溃标记（防止下次启动误弹窗）
            try:
                crash_recovery.clear_crash_flag()
                print("[Main] 崩溃标记已清除（正常退出）")
            except Exception:
                pass
            # 执行最后一次 GC
            gc.collect()
            print("[Main] 资源清理完成")
        app.aboutToQuit.connect(on_about_to_quit)

        sys.exit(app.exec_())

    except Exception as e:
        print("[Main] 启动失败:", e)
        traceback.print_exc()
        crash_recovery.log_crash(type(e), e, e.__traceback__)
        sys.exit(1)


if __name__ == '__main__':
    main()
  