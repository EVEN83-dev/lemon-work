# -*- coding: utf-8 -*-
"""Lemon Work 启动入口 —— 复用原版 LEMONCODE 客户端，只保留「右侧会话区 + 底部终端」

实现方式：零侵入。
  · 不修改 standard_mode/main.py、main_window.py 一行代码
  · 通过运行时猴补丁（monkey patch）在窗口首次显示后隐藏其余面板

保留：
  ✔ 右侧会话工作区（顶部会话 Tab、NATIVE/HOST、搜索框、积分、技能工具条、输入区、时钟）
  ✔ 底部终端面板（bottom_panel）
隐藏：
  ✘ 左侧活动栏 + 侧面板（side_panel）
  ✘ 文件资源管理器（explorer）
  ✘ 代码编辑器（editor_area）

如需恢复完整四栏布局：把 FOCUS_MODE 改为 False。
"""
from __future__ import annotations

import os
import sys
import runpy

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "standard_mode"))
sys.path.insert(0, os.path.join(ROOT, "standard_mode", "core"))
os.environ["PYTHONPATH"] = ROOT

# ── Qt 环境自举（中文路径下 WebEngine 必需）──
SP = os.path.join(ROOT, "_py312", "Lib", "site-packages")
QT5BIN = os.path.join(SP, "PyQt5", "Qt5", "bin")
QT_PLUGIN = os.path.join(SP, "PyQt5", "Qt5", "plugins")
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = os.path.join(QT_PLUGIN, "platforms")
os.environ["QT_PLUGIN_PATH"] = QT_PLUGIN
os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
_qp = os.path.join(QT5BIN, "QtWebEngineProcess.exe")
if os.path.exists(_qp):
    os.environ["QTWEBENGINEPROCESS_PATH"] = _qp
_res = os.path.join(SP, "PyQt5", "Qt5", "resources")
if os.path.isdir(_res):
    os.environ["QTWEBENGINE_RESOURCES_PATH"] = _res
if os.path.isdir(QT5BIN):
    os.environ["PATH"] = QT5BIN + os.pathsep + ROOT + os.pathsep + os.environ.get("PATH", "")
    try:
        os.add_dll_directory(QT5BIN)
    except Exception:
        pass

try:
    if sys.stdout is None:
        sys.stdout = open(os.path.join(ROOT, "运行日志.txt"), "w", encoding="utf-8", buffering=1)
    if sys.stderr is None:
        sys.stderr = open(os.path.join(ROOT, "运行日志.err.txt"), "w", encoding="utf-8", buffering=1)
except Exception:
    pass

FOCUS_MODE = True          # False = 恢复原版四栏布局
BOTTOM_RATIO = 260         # 底部终端初始高度（px）
HIDE_HTML_MENU = False     # 是否隐藏 HTML 顶栏菜单行（默认关闭，避免误伤内容区）
REBRAND = True             # 品牌改名 + 去「技能/双单窗口」+ 输入区重排

# 启动窗口比例：1400×1060（约 1.32:1，比原来的 1400×900 更高，对话区更舒展）
INITIAL_W = 1400
INITIAL_H = 1060
CENTER_WINDOW = True       # 启动时居中（参考图二的位置）


def _apply_rebrand(win):
    """运行时注入：1) 品牌改 Lemon Work  2) 去掉「技能」与「双单窗口」
    3) 输入区重排（textarea 独占整行，模型选择/发送按钮下移到工具条行）

    说明：这些元素由前端 JS 动态生成，源码中无稳定类名，故按**精确文本**定位，
    且全部包在 try/catch 中，任何一步失败都不影响其它功能。
    """
    from PyQt5.QtWebEngineWidgets import QWebEngineView

    js = r"""(function(){
  var R={renamed:0,hidden:[],composer:'no-ts'};

  // ── 1) 品牌文本替换：已改为静态源码修改（mimo_page.html 的 CODE→WORK、
  //      main_window.py 的标题与词标），此处不再做全局替换，避免污染
  //     「LemonCode 模型」等业务文案。保留空位便于将来按需启用。

  // ── 2) 按文本 + 几何过滤隐藏「技能」「双单窗口」 ──
  function hideByText(txt, maxW, maxH){
    maxW=maxW||170; maxH=maxH||52;
    var els=document.querySelectorAll('div,span,button,a,li,p');
    var hit=0;
    for(var i=0;i<els.length;i++){
      var el=els[i];
      var flat=(el.textContent||'').replace(/\s+/g,'');
      if(flat.indexOf(txt)<0) continue;
      if(flat.length>txt.length+6) continue;
      if(el.querySelector('textarea,input')) continue;
      var r=el.getBoundingClientRect();
      if(r.width>0 && r.width<maxW && r.height>0 && r.height<maxH){
        el.style.display='none';
        R.hidden.push(txt);
        hit++;
        if(hit>=2) break;
      }
    }
    return hit;
  }
  try{ hideByText('技能',170,52); }catch(e){}
  try{ hideByText('双单窗口',320,90); }catch(e){}
  try{ hideByText('单窗口',320,90); }catch(e){}

  // ── 2.5) 彻底取消「模式」：隐藏前端残留的 NATIVE / HOST / 模式 文本控件 ──
  try{ hideByText('NATIVE',200,44); }catch(e){}
  try{ hideByText('HOST',200,44); }catch(e){}
  try{ hideByText('模式',90,34); }catch(e){}

  // ── 3) 输入区重排：已改为 mimo_style.css 静态覆盖，
  //     此处不再重复设置 inline 样式，避免与 CSS 冲突。
  R.composer='css';

  // ── 4) 首屏大标题：开始对话后淡出（学 Big C / DeepSeek 首屏行为）
  //     只要输出区出现第一条真实消息就收起；清空对话后自动恢复。
  try{
    var hero=document.getElementById('heroArea')||document.querySelector('.logo-area');
    var out=document.getElementById('outputMessages');
    if(hero && out){
      var sync=function(){
        var has=false;
        for(var i=0;i<out.children.length;i++){
          var c=out.children[i];
          if(c.style && c.style.display==='none') continue;
          if((c.textContent||'').trim().length>0) { has=true; break; }
          if(c.querySelector && c.querySelector('img,canvas,video,svg')){ has=true; break; }
        }
        hero.classList.toggle('lw-hero-hidden', has);
        R.hero = has ? 'hidden' : 'shown';
      };
      try{
        new MutationObserver(sync).observe(out,{childList:true,characterData:true,subtree:false});
      }catch(e){}
      var fadeNow=function(){ hero.classList.add('lw-hero-hidden'); };
      var sb=document.getElementById('sendBtn');
      if(sb){ sb.addEventListener('click', fadeNow); }
      var ta=document.getElementById('inputField');
      if(ta){
        ta.addEventListener('keydown', function(e){
          if(e.key==='Enter' && !e.shiftKey && !e.isComposing) fadeNow();
        });
      }
      sync();
    }
  }catch(e){}

  return R;
})()"""

    n = 0

    def _cb(res):
        try:
            print("[LemonWork] 品牌注入结果:", res, flush=True)
        except Exception:
            pass

    for view in win.findChildren(QWebEngineView):
        try:
            view.loadFinished.connect(
                lambda ok, v=view, s=js: v.page().runJavaScript(s, _cb))
            view.page().runJavaScript(js, _cb)
            n += 1
        except Exception as e:
            print("[LemonWork] 品牌注入失败:", e, flush=True)
    print("[LemonWork] 品牌/布局注入已挂载 view=%d" % n, flush=True)


def _hide_html_top_menu(win):
    """隐藏 HTML 顶栏里的「文件/编辑/选择/视图/搜索/运行/帮助」菜单行

    该菜单由前端 JS 动态生成，源码中无稳定类名，故用「文字特征定位容器」的方式：
    找出同时包含 ≥5 个菜单标签、且子节点数最小的元素，将其收起。
    """
    from PyQt5.QtWebEngineWidgets import QWebEngineView

    js = r"""(function(){
  var L=['文件','编辑','选择','视图','搜索','运行','帮助'];
  var els=[].slice.call(document.querySelectorAll('*'));
  var best=null,bestCnt=0,bestSize=1e9;
  for(var i=0;i<els.length;i++){
    var el=els[i];
    var txt=el.textContent||'';
    var c=0;
    for(var j=0;j<L.length;j++){ if(txt.indexOf(L[j])>=0) c++; }
    if(c>=5 && c>bestCnt && el.children.length<60){
      var sz=el.querySelectorAll('*').length;
      if(sz<bestSize){ best=el; bestCnt=c; bestSize=sz; }
    }
  }
  if(best){ best.style.display='none'; return 'hidden'; }
  return 'notfound';
})()"""

    for view in win.findChildren(QWebEngineView):
        if getattr(view, "_lw_menu_patched", False):
            continue
        view._lw_menu_patched = True
        try:
            view.loadFinished.connect(
                lambda ok, v=view, s=js: v.page().runJavaScript(s))
            view.page().runJavaScript(js)
        except Exception as e:
            print("[LemonWork] HTML 菜单隐藏注入失败:", e, flush=True)


def _apply_focus_mode(win):
    """只保留右侧会话区 + 底部终端"""
    try:
        # 0) 启动窗口比例：按参考图（宽 1400、比例约 1.32:1）居中打开
        if CENTER_WINDOW:
            try:
                scr = win.screen()
                avail = scr.availableGeometry() if scr is not None else None
                if avail is not None:
                    w = min(INITIAL_W, max(800, avail.width() - 80))
                    h = min(INITIAL_H, max(600, avail.height() - 80))
                    win.resize(w, h)
                    win.move(avail.x() + (avail.width() - w) // 2,
                             avail.y() + (avail.height() - h) // 2)
                    print("[LemonWork] 启动窗口: %dx%d (比例 %.2f)" %
                          (w, h, w / max(1, h)), flush=True)
            except Exception as e:
                print("[LemonWork] 启动窗口设置失败:", e, flush=True)

        # 1) 隐藏文件树、编辑器与菜单栏（参考界面中均不存在）
        for name in ("explorer", "editor_area", "menu_bar"):
            w = getattr(win, name, None)
            if w is not None:
                w.hide()

        # 2) 隐藏左侧容器（活动栏 + 侧面板）
        sp = getattr(win, "side_panel", None)
        if sp is not None:
            sp.hide()
        ab = getattr(win, "activity_bar", None)
        if ab is not None:
            holder = ab.parentWidget()
            if holder is not None:
                holder.hide()

        # 3) 横向分割器：只留会话区
        h = getattr(win, "_h_splitter", None)
        if h is not None:
            try:
                h.setSizes([0, 0, 2000])
            except Exception:
                pass

        # 4) 底部终端保留并给定初始高度
        bp = getattr(win, "bottom_panel", None)
        if bp is not None:
            bp.show()
        v = getattr(win, "_v_splitter", None)
        if v is not None:
            try:
                v.setSizes([900, BOTTOM_RATIO])
            except Exception:
                pass

        # 5) 隐藏菜单栏与状态栏（原版参考界面中不存在）
        try:
            mb = win.menuBar()
            if mb is not None:
                mb.hide()
        except Exception:
            pass
        try:
            sb = win.statusBar()
            if sb is not None:
                sb.hide()
        except Exception:
            pass

        # 6) 标题栏图标
        try:
            from PyQt5.QtGui import QIcon
            ico = os.path.join(ROOT, "..", "icon", "lemonwork.ico")
            if os.path.exists(ico):
                win.setWindowIcon(QIcon(ico))
        except Exception:
            pass

        # 7) HTML 顶栏菜单行隐藏（默认关闭：文字特征定位会误伤主内容区，
        #    如需精确隐藏请改为按 DOM 类名注入 CSS，见 HIDE_HTML_MENU 开关）
        if HIDE_HTML_MENU:
            _hide_html_top_menu(win)

        # 7.5) 取消顶栏「模式 NATIVE / HOST」及模式切换按键（Lemon Work 不设模式概念）
        try:
            tb = getattr(win, "title_bar", None)
            es = getattr(tb, "engine_selector", None) if tb is not None else None
            if es is not None:
                es.setVisible(False)
                print("[LemonWork] 已隐藏顶栏模式切换器 NATIVE/HOST", flush=True)
            if tb is not None:
                from PyQt5.QtWidgets import QToolButton
                for b in tb.findChildren(QToolButton):
                    try:
                        tip = b.toolTip() or ""
                    except Exception:
                        continue
                    if tip.startswith("AI 面板停靠"):
                        b.setVisible(False)
                print("[LemonWork] 已隐藏面板布局切换键", flush=True)
        except Exception as e:
            print("[LemonWork] 隐藏顶栏模式失败:", e, flush=True)

        # 8) 品牌改名 + 去「技能/双单窗口」+ 输入区重排
        if REBRAND:
            _apply_rebrand(win)

        # 9) Qt 侧控件隐藏：文本以「技能」「双单窗口」开头的按钮/标签
        try:
            from PyQt5.QtWidgets import QPushButton, QToolButton, QLabel
            for w in win.findChildren((QPushButton, QToolButton, QLabel)):
                try:
                    txt = (w.text() or "").strip()
                except Exception:
                    continue
                if txt.startswith("双单窗口") or txt == "技能" or txt.startswith("技能 "):
                    w.hide()
                    print("[LemonWork] 已隐藏 Qt 控件:", txt[:12], flush=True)
        except Exception as e:
            print("[LemonWork] Qt 控件隐藏失败:", e, flush=True)

        print("[LemonWork] 聚焦模式已应用：保留右侧会话区 + 底部终端", flush=True)
    except Exception as e:
        print("[LemonWork] 聚焦模式应用失败:", e, flush=True)


BANK_DIR = r"D:\虚拟系统软件模拟\数字银行"
BANK_URL = "http://127.0.0.1:8090"
_BANK_WATCHDOG_STARTED = False


def _spawn_bank_server():
    """静默拉起数字银行（无窗口、stdin 关闭、stdout/err 落 server.log）。"""
    import subprocess
    srv = os.path.join(BANK_DIR, "server.py")
    if not os.path.exists(srv):
        print("[LemonWork] 数字银行目录不存在，跳过自启", flush=True)
        return False
    py = os.path.join(ROOT, "_py312", "python.exe")
    if not os.path.exists(py):
        py = sys.executable
    env = dict(os.environ)
    env.setdefault("SIM_DAY_SECONDS", "30")
    env["PYTHONUNBUFFERED"] = "1"   # 启动横幅/异常堆栈实时落盘
    try:
        os.makedirs(os.path.join(BANK_DIR, "data"), exist_ok=True)
        # ★ 关键：日志落盘（此前 DEVNULL 吞掉银行崩溃原因，无法定位"服务又挂了"）
        log = open(os.path.join(BANK_DIR, "data", "server.log"), "ab", buffering=0)
        subprocess.Popen(
            [py, srv], cwd=BANK_DIR, env=env,
            stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        print("[LemonWork] 已拉起数字银行（:8090，无窗口守护）", flush=True)
        return True
    except Exception as e:
        print("[LemonWork] 数字银行自启失败:", e, flush=True)
        return False


def _start_bank_watchdog():
    """★ Lemon Work: 银行常驻看门狗 —— 进程掉了就自动复活，而不是等下次启动。

    用户实测：银行会在会话中途死掉 → Agent 所有 remote_bank_* 工具直接
    "ERROR 127.0.0.1:8090 拒绝连接"，看起来像"DeepSeek 执行不了"。
    10s 探测一次；连续 2 次不可达（约 20s）才重启，避免抖动/双开。"""
    global _BANK_WATCHDOG_STARTED
    if _BANK_WATCHDOG_STARTED:
        return
    _BANK_WATCHDOG_STARTED = True

    def _loop():
        import threading as _th
        import time as _tm
        fails = 0
        while True:
            _tm.sleep(10)
            try:
                import requests
                r = requests.get(BANK_URL + "/api/health", timeout=2,
                                 proxies={"http": None, "https": None})
                if r.status_code == 200:
                    fails = 0
                    continue
            except Exception:
                pass
            fails += 1
            if fails < 2:
                continue
            print("[LemonWork] 检测到数字银行离线，自动重启…", flush=True)
            if _spawn_bank_server():
                fails = 0
                _tm.sleep(8)   # 给 Flask 启动时间，避免下一轮误判

    try:
        import threading
        threading.Thread(target=_loop, daemon=True, name="bank-watchdog").start()
        print("[LemonWork] 数字银行看门狗已启动（10s 探测 / 掉线自愈）", flush=True)
    except Exception as e:
        print("[LemonWork] 看门狗启动失败:", e, flush=True)


def _ensure_bank_server():
    """★ Lemon Work: 数字银行守护 —— 启动时探活，离线则拉起，并挂常驻看门狗。"""
    try:
        import requests
        requests.get(BANK_URL + "/api/health", timeout=2,
                     proxies={"http": None, "https": None})
        print("[LemonWork] 数字银行在线（:8090）", flush=True)
    except Exception:
        _spawn_bank_server()
    _start_bank_watchdog()


def _install_patch():
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QMainWindow

    try:
        from ui.main_window import MIMOWindow
    except Exception:
        from standard_mode.ui.main_window import MIMOWindow

    if getattr(MIMOWindow, "_lw_patched", False):
        return

    def _wrap(orig):
        def inner(self, *a, **kw):
            r = orig(self, *a, **kw)
            if FOCUS_MODE:
                # 等一帧，确保 _apply_ai_layout 等初始化完成后再覆盖布局
                QTimer.singleShot(120, lambda: _apply_focus_mode(self))
                QTimer.singleShot(600, lambda: _apply_focus_mode(self))
            return r
        return inner

    for meth in ("show", "showMaximized", "showNormal", "showFullScreen"):
        if hasattr(MIMOWindow, meth):
            setattr(MIMOWindow, meth, _wrap(getattr(MIMOWindow, meth)))
    MIMOWindow._lw_patched = True
    print("[LemonWork] 布局补丁已安装", flush=True)


if __name__ == "__main__":
    _ensure_bank_server()
    _install_patch()
    runpy.run_path(os.path.join(ROOT, "standard_mode", "main.py"), run_name="__main__")
