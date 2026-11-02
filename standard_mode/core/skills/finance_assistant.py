# -*- coding: utf-8 -*-
"""
Skill: finance_assistant v2.0 — 金融助手
==========================================
支持：实时行情（新浪/腾讯）、K线数据、大盘概览、记账管理、收支统计、货币换算。
v2.0新增：realtime_quote / kline / overview / HUD卡片HTML生成
依赖：requests（可选，用于行情查询）
"""

import json
import os
import re
import time
import traceback
import html as _html
from datetime import datetime
from typing import Dict, Any, Optional, List

import sys, os as _os
sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "finance_assistant",
    "description": ("金融助手v2.1：实时行情、K线数据、大盘概览、记账管理、收支统计、货币换算，"
                    "并支持复利/利息计算（query 命中 复利/利息/利率/本金/收益/汇率/贷款 等"
                    "关键词时自动本地计算本息合计，无需记账、不调用LLM）。输出星空HUD风格富卡片。"),
    "category": "finance",
    "version": "2.1.0",
}

_LEDGER_DIR = _os.path.expanduser("~/.lemoncode/finance")
_LEDGER_FILE = _os.path.join(_LEDGER_DIR, "ledger.json")

_CACHE: Dict[str, Any] = {}
_CACHE_TTL = 3.0
_RATE_LIMIT_WINDOW = 60
_RATE_LIMIT_MAX = 30
_RATE_LOG: List[float] = []
_DEGRADED_UNTIL: float = 0.0

def _ensure_ledger_dir():
    _os.makedirs(_LEDGER_DIR, exist_ok=True)

def _load_ledger() -> list:
    _ensure_ledger_dir()
    if not _os.path.exists(_LEDGER_FILE):
        return []
    try:
        with open(_LEDGER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def _save_ledger(entries: list):
    _ensure_ledger_dir()
    with open(_LEDGER_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

def _lazy_import(lib_name: str):
    try:
        mod = __import__(lib_name)
        for part in lib_name.split('.')[1:]:
            mod = getattr(mod, part)
        return mod
    except (ImportError, AttributeError):
        return None

def _get_cached(key: str) -> Optional[Any]:
    entry = _CACHE.get(key)
    if entry and (time.time() - entry["ts"]) < _CACHE_TTL:
        return entry["data"]
    return None

def _set_cached(key: str, data: Any):
    _CACHE[key] = {"ts": time.time(), "data": data}

def _check_rate_limit() -> bool:
    global _DEGRADED_UNTIL
    if time.time() < _DEGRADED_UNTIL:
        return False
    now = time.time()
    while _RATE_LOG and now - _RATE_LOG[0] > _RATE_LIMIT_WINDOW:
        _RATE_LOG.pop(0)
    if len(_RATE_LOG) >= _RATE_LIMIT_MAX:
        _DEGRADED_UNTIL = now + 60
        return False
    _RATE_LOG.append(now)
    return True

def _esc(text: Any) -> str:
    return _html.escape(str(text), quote=True)

# ============================================================
# v2.0: 实时行情（新浪/腾讯双源）
# ============================================================

def _sina_quote(symbol: str) -> Optional[Dict]:
    requests = _lazy_import("requests")
    if requests is None:
        return None
    if symbol.startswith("sh") or symbol.startswith("sz"):
        sina_code = symbol
    elif symbol.isdigit() and len(symbol) == 6:
        sina_code = ("sh" if symbol.startswith("6") else "sz") + symbol
    elif "." in symbol:
        parts = symbol.split(".")
        prefix = "sh" if parts[-1].upper() in ("SS", "SH") else "sz"
        sina_code = prefix + parts[0]
    else:
        sina_code = symbol
    try:
        url = f"https://hq.sinajs.cn/list={sina_code}"
        headers = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code != 200:
            return None
        text = resp.text
        eq_pos = text.find('="')
        if eq_pos < 0:
            return None
        content = text[eq_pos + 2:].strip().rstrip('"').rstrip(';')
        if not content:
            return None
        parts = content.split(",")
        if len(parts) < 32:
            return None
        name = parts[0]
        open_p = float(parts[1]) if parts[1] else 0
        prev_close = float(parts[2]) if parts[2] else 0
        price = float(parts[3]) if parts[3] else 0
        high = float(parts[4]) if parts[4] else 0
        low = float(parts[5]) if parts[5] else 0
        volume = float(parts[8]) if parts[8] else 0
        turnover = float(parts[9]) if parts[9] else 0
        change_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0
        return {
            "symbol": sina_code, "name": name, "price": price,
            "open": open_p, "prev_close": prev_close, "high": high, "low": low,
            "volume": volume, "turnover": turnover,
            "change": round(price - prev_close, 3),
            "change_pct": round(change_pct, 2),
            "currency": "CNY", "source": "sina",
        }
    except Exception:
        return None

def _yahoo_quote(symbol: str) -> Optional[Dict]:
    requests = _lazy_import("requests")
    if requests is None:
        return None
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code != 200:
            return None
        data = resp.json()
        result = data.get("chart", {}).get("result", [{}])[0]
        meta = result.get("meta", {})
        price = meta.get("regularMarketPrice", 0)
        prev = meta.get("previousClose", 0)
        change_pct = ((price - prev) / prev * 100) if prev > 0 else 0
        return {
            "symbol": symbol, "name": meta.get("shortName", symbol),
            "price": price, "open": meta.get("chartPreviousClose", prev),
            "prev_close": prev, "high": 0, "low": 0,
            "volume": 0, "turnover": 0,
            "change": round(price - prev, 4),
            "change_pct": round(change_pct, 2),
            "currency": meta.get("currency", "USD"), "source": "yahoo",
        }
    except Exception:
        return None

def _realtime_quote(symbol: str) -> Dict:
    cached = _get_cached(f"quote:{symbol}")
    if cached:
        return cached
    if not _check_rate_limit():
        return {"error": f"请求频率过高，60秒内最多{_RATE_LIMIT_MAX}次。请稍后再试或降低监控频率。"}
    result = _sina_quote(symbol)
    if result is None:
        result = _yahoo_quote(symbol)
    if result is None:
        return {"error": f"无法获取 {symbol} 行情（新浪/腾讯/Yahoo均失败）"}
    _set_cached(f"quote:{symbol}", result)
    return result

# ============================================================
# v2.0: K线数据
# ============================================================

def _kline_data(symbol: str, period: str = "daily", count: int = 30) -> Dict:
    requests = _lazy_import("requests")
    if requests is None:
        return {"error": "requests库未安装"}
    cached = _get_cached(f"kline:{symbol}:{period}:{count}")
    if cached:
        return cached
    if not _check_rate_limit():
        return {"error": f"请求频率过高，60秒内最多{_RATE_LIMIT_MAX}次。请稍后再试。"}
    try:
        if symbol.isdigit() and len(symbol) == 6:
            sina_code = ("sh" if symbol.startswith("6") else "sz") + symbol
        elif symbol.startswith("sh") or symbol.startswith("sz"):
            sina_code = symbol
        else:
            result = _yahoo_kline(symbol, period, count)
            if result:
                _set_cached(f"kline:{symbol}:{period}:{count}", result)
                return result
            return {"error": f"K线数据获取失败: {symbol}"}
        period_map = {"daily": "daily", "weekly": "weekly", "monthly": "monthly"}
        p = period_map.get(period, "daily")
        url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={sina_code}&scale=240&ma=no&datalen={count}"
        headers = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code != 200:
            return {"error": f"K线请求失败: HTTP {resp.status_code}"}
        data = resp.json()
        if not isinstance(data, list) or len(data) == 0:
            return {"error": "K线数据为空"}
        candles = []
        for item in data[-count:]:
            candles.append({
                "date": item.get("day", ""),
                "open": float(item.get("open", 0)),
                "high": float(item.get("high", 0)),
                "low": float(item.get("low", 0)),
                "close": float(item.get("close", 0)),
                "volume": float(item.get("volume", 0)),
            })
        result = {"symbol": sina_code, "period": p, "candles": candles, "count": len(candles), "source": "sina"}
        _set_cached(f"kline:{symbol}:{period}:{count}", result)
        return result
    except Exception as e:
        return {"error": f"K线异常: {e}"}

def _yahoo_kline(symbol: str, period: str, count: int) -> Optional[Dict]:
    requests = _lazy_import("requests")
    if requests is None:
        return None
    try:
        interval_map = {"daily": "1d", "weekly": "1wk", "monthly": "1mo"}
        interval = interval_map.get(period, "1d")
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval={interval}&range={count}d"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code != 200:
            return None
        data = resp.json()
        result = data.get("chart", {}).get("result", [{}])[0]
        timestamps = result.get("timestamp", [])
        q = result.get("indicators", {}).get("quote", [{}])[0]
        candles = []
        for i in range(len(timestamps)):
            o = q.get("open", [])[i] if i < len(q.get("open", [])) else 0
            h = q.get("high", [])[i] if i < len(q.get("high", [])) else 0
            l = q.get("low", [])[i] if i < len(q.get("low", [])) else 0
            c = q.get("close", [])[i] if i < len(q.get("close", [])) else 0
            v = q.get("volume", [])[i] if i < len(q.get("volume", [])) else 0
            if c is None:
                continue
            dt = datetime.fromtimestamp(timestamps[i]).strftime("%Y-%m-%d") if i < len(timestamps) else ""
            candles.append({"date": dt, "open": float(o or 0), "high": float(h or 0), "low": float(l or 0), "close": float(c), "volume": float(v or 0)})
        return {"symbol": symbol, "period": period, "candles": candles[-count:], "count": len(candles[-count:]), "source": "yahoo"}
    except Exception:
        return None

# ============================================================
# v2.0: 大盘概览
# ============================================================

def _market_overview() -> Dict:
    cached = _get_cached("market_overview")
    if cached:
        return cached
    if not _check_rate_limit():
        return {"error": f"请求频率过高，60秒内最多{_RATE_LIMIT_MAX}次。请稍后再试。", "indices": [], "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    indices = [
        ("sh000001", "上证指数"),
        ("sz399001", "深证成指"),
        ("sz399006", "创业板指"),
    ]
    results = []
    for code, name in indices:
        q = _sina_quote(code)
        if q:
            q["name"] = name
            results.append(q)
        else:
            results.append({"symbol": code, "name": name, "error": "获取失败"})
    overview = {"indices": results, "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    _set_cached("market_overview", overview)
    return overview

# ============================================================
# v2.0: HUD卡片HTML生成（星空浮层风格）
# ============================================================

def _hud_text_shadow() -> str:
    return "text-shadow: 0 0 12px rgba(5,5,8,0.95), 0 1px 3px rgba(0,0,0,0.8);"

def _hud_soft_btn(label: str, action: str, icon: str = "") -> str:
    icon_html = f'<span style="display:inline-flex;vertical-align:middle;margin-right:4px;">{icon}</span>' if icon else ""
    return (
        f'<button class="fin-hud-btn" onclick="window._callPython(\'financialAction\', '
        f'\'{ _esc(action) }\')" '
        f'style="background:rgba(8,8,12,0.75);border:1px solid rgba(255,255,255,0.08);'
        f'color:rgba(255,255,255,0.7);padding:4px 12px;border-radius:6px;font-size:12px;'
        f'cursor:pointer;backdrop-filter:blur(6px);transition:all 0.2s;pointer-events:auto;" '
        f'onmouseover="this.style.background=\'rgba(255,105,0,0.12)\';this.style.borderColor=\'rgba(255,105,0,0.4)\';this.style.color=\'Lemon.BRAND_ORANGE_LIGHT\'" '
        f'onmouseout="this.style.background=\'rgba(8,8,12,0.75)\';this.style.borderColor=\'rgba(255,255,255,0.08)\';this.style.color=\'rgba(255,255,255,0.7)\'"'
        f'>{icon_html}{_esc(label)}</button>'
    )

def _render_quote_hud(data: Dict) -> str:
    if "error" in data:
        return f'<div class="fin-hud" style="padding:12px;color:Lemon.ACCENT_RED;{_hud_text_shadow()}">{_esc(data["error"])}</div>'
    name = data.get("name", data.get("symbol", ""))
    price = data.get("price", 0)
    change = data.get("change", 0)
    pct = data.get("change_pct", 0)
    currency = data.get("currency", "CNY")
    color = "Lemon.ACCENT_GREEN" if change >= 0 else "Lemon.ACCENT_RED"
    arrow = "▲" if change >= 0 else "▼"
    prev = data.get("prev_close", 0)
    high = data.get("high", 0)
    low = data.get("low", 0)
    vol = data.get("volume", 0)
    vol_str = f"{vol / 1e8:.2f}亿" if vol > 1e8 else f"{vol / 1e4:.1f}万" if vol > 1e4 else str(int(vol))
    ts = datetime.now().strftime("%H:%M:%S")
    return (
        f'<div class="fin-hud fin-hud-quote" style="padding:16px 12px 8px;pointer-events:auto;">'
        f'<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px;">'
        f'<span style="font-size:14px;color:Lemon.DIVIDER;{_hud_text_shadow()}">{_esc(name)}</span>'
        f'<span style="font-size:11px;color:rgba(255,255,255,0.3);{_hud_text_shadow()}">{ts}</span>'
        f'</div>'
        f'<div style="display:flex;align-items:baseline;gap:10px;margin-bottom:10px;">'
        f'<span style="font-size:32px;font-weight:700;color:{color};{_hud_text_shadow()}">{price:.2f}</span>'
        f'<span style="font-size:15px;font-weight:600;color:{color};{_hud_text_shadow()}">{arrow} {abs(change):.2f} ({abs(pct):.2f}%)</span>'
        f'<span style="font-size:12px;color:rgba(255,255,255,0.4);{_hud_text_shadow()}">{currency}</span>'
        f'</div>'
        f'<div style="display:flex;gap:16px;font-size:12px;color:rgba(255,255,255,0.5);{_hud_text_shadow()}margin-bottom:10px;">'
        f'<span>开 {prev:.2f}</span><span>高 {high:.2f}</span><span>低 {low:.2f}</span><span>量 {vol_str}</span>'
        f'</div>'
        f'<div style="display:flex;gap:6px;flex-wrap:wrap;">'
        f'{_hud_soft_btn("刷新", "refresh:" + _esc(data.get("symbol", "")))}'
        f'{_hud_soft_btn("K线", "kline:" + _esc(data.get("symbol", "")))}'
        f'{_hud_soft_btn("监控", "monitor:" + _esc(data.get("symbol", "")))}'
        f'{_hud_soft_btn("停止", "stop_monitor")}'
        f'</div>'
        f'</div>'
    )

def _render_overview_hud(data: Dict) -> str:
    indices = data.get("indices", [])
    ts = data.get("timestamp", "")
    rows = ""
    for idx in indices:
        if "error" in idx:
            rows += f'<div style="padding:6px 0;color:Lemon.ACCENT_RED;{_hud_text_shadow()}">{_esc(idx.get("name",""))}: {_esc(idx["error"])}</div>'
            continue
        name = idx.get("name", "")
        price = idx.get("price", 0)
        change = idx.get("change", 0)
        pct = idx.get("change_pct", 0)
        color = "Lemon.ACCENT_GREEN" if change >= 0 else "Lemon.ACCENT_RED"
        arrow = "▲" if change >= 0 else "▼"
        rows += (
            f'<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;'
            f'border-bottom:1px solid rgba(255,255,255,0.04);">'
            f'<span style="font-size:13px;color:Lemon.DIVIDER;{_hud_text_shadow()}">{_esc(name)}</span>'
            f'<span style="font-size:14px;font-weight:600;color:{color};{_hud_text_shadow()}">'
            f'{price:.2f} {arrow}{abs(pct):.2f}%</span></div>'
        )
    return (
        f'<div class="fin-hud fin-hud-overview" style="padding:16px 12px 8px;pointer-events:auto;">'
        f'<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px;">'
        f'<span style="font-size:14px;font-weight:600;color:Lemon.BRAND_ORANGE_LIGHT;{_hud_text_shadow()}">大盘概览</span>'
        f'<span style="font-size:11px;color:rgba(255,255,255,0.3);{_hud_text_shadow()}">{ts}</span>'
        f'</div>'
        f'{rows}'
        f'<div style="display:flex;gap:6px;margin-top:10px;">'
        f'{_hud_soft_btn("刷新", "refresh_overview")}'
        f'{_hud_soft_btn("自动刷新", "auto_overview")}'
        f'</div>'
        f'</div>'
    )

def _render_kline_hud(data: Dict, img_base64: str = "", canvas_js: str = "") -> str:
    if "error" in data:
        return f'<div class="fin-hud" style="padding:12px;color:Lemon.ACCENT_RED;{_hud_text_shadow()}">{_esc(data["error"])}</div>'
    symbol = data.get("symbol", "")
    period = data.get("period", "daily")
    count = data.get("count", 0)
    chart_html = ""
    if canvas_js:
        canvas_id = f"kline_{symbol.replace('.','_')}_{int(time.time()*1000)}"
        chart_html = (
            f'<canvas id="{canvas_id}" class="fin-hud-canvas" '
            f'style="width:100%;height:260px;border-radius:6px;border:1px solid rgba(255,255,255,0.06);background:rgba(5,5,8,0.08);cursor:crosshair;pointer-events:auto;"></canvas>'
            f'<script>(function(){{'
            f'var c=document.getElementById("{canvas_id}");'
            f'if(!c)return;'
            f'var dpr=window.devicePixelRatio||1;'
            f'c.width=c.offsetWidth*dpr;c.height=c.offsetHeight*dpr;'
            f'var ctx=c.getContext("2d");ctx.scale(dpr,dpr);'
            f'var W=c.offsetWidth,H=c.offsetHeight;'
            f'var data={canvas_js};'
            f'var ox=0,oy=0,scale=1,dragging=false,lx=0,ly=0;'
            f'function draw(){{'
            f'ctx.clearRect(0,0,W,H);'
            f'var bars=data;if(!bars||!bars.length)return;'
            f'var padL=50,padR=10,padT=10,padB=30;'
            f'var cW=W-padL-padR,cH=H-padT-padB;'
            f'var visible=Math.max(5,Math.floor(bars.length/scale));'
            f'var startIdx=Math.max(0,Math.floor(ox));'
            f'var endIdx=Math.min(bars.length,startIdx+visible);'
            f'var slice=bars.slice(startIdx,endIdx);'
            f'if(!slice.length)return;'
            f'var allH=[],allL=[];'
            f'for(var i=0;i<slice.length;i++){{allH.push(slice[i].h);allL.push(slice[i].l);}}'
            f'var maxH=Math.max.apply(null,allH),minL=Math.min.apply(null,allL);'
            f'var range=maxH-minL;if(range<0.01)range=0.01;'
            f'var barW=cW/visible*0.7,gap=cW/visible*0.3;'
            f'function yP(v){{return padT+cH-(v-minL)/range*cH;}}'
            f'ctx.strokeStyle="rgba(255,255,255,0.06)";ctx.lineWidth=0.5;'
            f'for(var g=0;g<5;g++){{var gy=padT+cH*g/4;ctx.beginPath();ctx.moveTo(padL,gy);ctx.lineTo(W-padR,gy);ctx.stroke();'
            f'ctx.fillStyle="rgba(255,255,255,0.3)";ctx.font="9px sans-serif";ctx.textAlign="right";'
            f'ctx.fillText((maxH-(range*g/4)).toFixed(2),padL-4,gy+3);}}'
            f'for(var i=0;i<slice.length;i++){{'
            f'var b=slice[i],x=padL+i*(barW+gap)+gap/2;'
            f'var up=b.c>=b.o;var col=up?"Lemon.ACCENT_GREEN":"Lemon.ACCENT_RED";'
            f'ctx.strokeStyle=col;ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x+barW/2,yP(b.l));ctx.lineTo(x+barW/2,yP(b.h));ctx.stroke();'
            f'var bot=Math.min(b.o,b.c),ht=Math.abs(b.c-b.o);'
            f'if(ht<0.001)ht=0.001;'
            f'ctx.fillStyle=col;ctx.fillRect(x,yP(bot+ht),barW,ht/range*cH);'
            f'}}'
            f'}}'
            f'c.addEventListener("wheel",function(e){{e.preventDefault();'
            f'if(e.deltaY<0)scale=Math.min(scale*1.2,bars.length/5);'
            f'else scale=Math.max(scale/1.2,1);draw();}},{{passive:false}});'
            f'c.addEventListener("mousedown",function(e){{dragging=true;lx=e.clientX;}});'
            f'c.addEventListener("mousemove",function(e){{if(!dragging)return;'
            f'var dx=e.clientX-lx;ox-=dx/(c.offsetWidth/bars.length)*0.3;'
            f'ox=Math.max(0,Math.min(ox,bars.length-bars.length/scale));lx=e.clientX;draw();}});'
            f'c.addEventListener("mouseup",function(){{dragging=false;}});'
            f'c.addEventListener("mouseleave",function(){{dragging=false;}});'
            f'draw();'
            f'}})();</script>'
        )
    elif img_base64:
        chart_html = f'<img src="data:image/png;base64,{img_base64}" style="width:100%;border-radius:6px;border:1px solid rgba(255,255,255,0.06);margin-bottom:8px;" />'
    period_btns = ""
    for p, label in [("daily", "日K"), ("weekly", "周K"), ("monthly", "月K")]:
        active = "background:rgba(255,105,0,0.2);color:Lemon.BRAND_ORANGE_LIGHT;border-color:rgba(255,105,0,0.4);" if p == period else ""
        period_btns += (
            f'<button class="fin-hud-btn" onclick="window._callPython(\'financialAction\', \'kline:{_esc(symbol)}:{p}\')" '
            f'style="background:rgba(8,8,12,0.75);border:1px solid rgba(255,255,255,0.08);'
            f'color:rgba(255,255,255,0.7);padding:3px 10px;border-radius:4px;font-size:11px;'
            f'cursor:pointer;backdrop-filter:blur(6px);transition:all 0.2s;pointer-events:auto;{active}" '
            f'onmouseover="this.style.background=\'rgba(255,105,0,0.12)\';this.style.color=\'Lemon.BRAND_ORANGE_LIGHT\'" '
            f'onmouseout="if(\'{p}\'!=\'{period}\'){{this.style.background=\'rgba(8,8,12,0.75)\';this.style.color=\'rgba(255,255,255,0.7)\'}}"'
            f'>{label}</button>'
        )
    return (
        f'<div class="fin-hud fin-hud-kline" style="padding:16px 12px 8px;pointer-events:auto;">'
        f'<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px;">'
        f'<span style="font-size:14px;font-weight:600;color:Lemon.BRAND_ORANGE_LIGHT;{_hud_text_shadow()}">{_esc(symbol)} K线 ({count}根)</span>'
        f'<span style="font-size:10px;color:rgba(255,255,255,0.3);">{_esc("滚轮缩放 / 拖拽平移" if canvas_js else "matplotlib静态图")}</span>'
        f'</div>'
        f'{chart_html}'
        f'<div style="display:flex;gap:6px;flex-wrap:wrap;">'
        f'{period_btns}'
        f'{_hud_soft_btn("行情", "quote:" + _esc(symbol))}'
        f'{_hud_soft_btn("监控", "monitor:" + _esc(symbol))}'
        f'</div>'
        f'</div>'
    )

def _generate_kline_chart(candles: List[Dict]) -> str:
    plt = _lazy_import("matplotlib.pyplot")
    numpy = _lazy_import("numpy")
    mpl_finance = _lazy_import("mplfinance")
    base64_mod = _lazy_import("base64")
    io_mod = _lazy_import("io")
    if plt is None or numpy is None or base64_mod is None or io_mod is None:
        return ""
    try:
        plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
        plt.rcParams['axes.unicode_minus'] = False
        fig, ax = plt.subplots(figsize=(8, 4.5), dpi=100, facecolor='rgba(5,5,8,0.0)')
        ax.set_facecolor('rgba(5,5,8,0.0)')
        dates = [c["date"] for c in candles]
        opens = [c["open"] for c in candles]
        closes = [c["close"] for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        x = list(range(len(dates)))
        for i in range(len(x)):
            color = 'Lemon.ACCENT_GREEN' if closes[i] >= opens[i] else 'Lemon.ACCENT_RED'
            body_bottom = min(opens[i], closes[i])
            body_height = abs(closes[i] - opens[i])
            if body_height < 0.001:
                body_height = 0.001
            ax.plot([x[i], x[i]], [lows[i], highs[i]], color=color, linewidth=0.8, alpha=0.8)
            ax.bar(x[i], body_height, bottom=body_bottom, color=color, width=0.6, alpha=0.85, edgecolor=color, linewidth=0.5)
        ax.tick_params(colors='rgba(255,255,255,0.4)', labelsize=8)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_color('rgba(255,255,255,0.08)')
        ax.spines['left'].set_color('rgba(255,255,255,0.08)')
        step = max(1, len(dates) // 6)
        ax.set_xticks(x[::step])
        ax.set_xticklabels([dates[i] for i in x[::step]], rotation=30, fontsize=7, color='rgba(255,255,255,0.4)')
        ax.yaxis.tick_right()
        fig.tight_layout(pad=0.5)
        buf = io_mod.BytesIO()
        fig.savefig(buf, format='png', facecolor='rgba(5,5,8,0.0)', transparent=True, dpi=100)
        plt.close(fig)
        buf.seek(0)
        img_base64 = base64_mod.b64encode(buf.read()).decode('ascii')
        return img_base64
    except Exception:
        try:
            plt.close('all')
        except Exception:
            pass
        return ""

def _generate_kline_canvas_data(candles: List[Dict]) -> str:
    if not candles:
        return ""
    items = []
    for c in candles:
        items.append(
            '{{"o":{},"c":{},"h":{},"l":{},"d":"{}"}}'.format(
                c.get("open", 0), c.get("close", 0),
                c.get("high", 0), c.get("low", 0),
                c.get("date", "")
            )
        )
    return '[' + ','.join(items) + ']'

# ============================================================
# 旧版兼容接口
# ============================================================

def _stock_query(symbol: str) -> SkillResult:
    data = _realtime_quote(symbol)
    if "error" in data:
        return SkillResult(success=False, error=data["error"], output=data["error"])
    hud_html = _render_quote_hud(data)
    name = data.get("name", symbol)
    price = data.get("price", 0)
    prev = data.get("prev_close", 0)
    change = data.get("change", 0)
    currency = data.get("currency", "CNY")
    text_output = f"{name} ({symbol})\n当前: {price} {currency}\n前收: {prev} {currency}\n涨跌: {change} {currency}"
    return SkillResult(
        success=True,
        output=text_output,
        data={"symbol": symbol, "price": price, "previous_close": prev, "change": change, "currency": currency, "hud_html": hud_html},
    )

def _record_expense(amount: float, category: str, description: str, entry_type: str) -> SkillResult:
    ledger = _load_ledger()
    entry = {
        "id": str(len(ledger) + 1),
        "type": entry_type,
        "amount": amount,
        "category": category,
        "description": description,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    ledger.append(entry)
    _save_ledger(ledger)
    sign = "+" if entry_type == "income" else "-"
    return SkillResult(
        success=True,
        output=f"已记录: {sign}{amount} | {category} | {description}",
        data=entry,
    )

def _get_stats(period: str) -> SkillResult:
    ledger = _load_ledger()
    if not ledger:
        return SkillResult(success=True, output="暂无记账记录", data={"total_income": 0, "total_expense": 0, "balance": 0})
    now = datetime.now()
    filtered = []
    for e in ledger:
        try:
            d = datetime.strptime(e.get("date", ""), "%Y-%m-%d %H:%M:%S")
            if period == "month" and (d.year != now.year or d.month != now.month):
                continue
            elif period == "week" and (now - d).days > 7:
                continue
            filtered.append(e)
        except Exception:
            filtered.append(e)
    total_income = sum(e.get("amount", 0) for e in filtered if e.get("type") == "income")
    total_expense = sum(e.get("amount", 0) for e in filtered if e.get("type") == "expense")
    balance = total_income - total_expense
    by_category = {}
    for e in filtered:
        cat = e.get("category", "other")
        by_category[cat] = by_category.get(cat, 0) + e.get("amount", 0)
    return SkillResult(
        success=True,
        output=f"统计({period}):\n收入: {total_income:.2f}\n支出: {total_expense:.2f}\n结余: {balance:.2f}\n分类: {json.dumps(by_category, ensure_ascii=False)}",
        data={"total_income": total_income, "total_expense": total_expense, "balance": balance, "by_category": by_category, "count": len(filtered)},
    )

def _currency_convert(amount: float, from_currency: str, to_currency: str) -> SkillResult:
    requests = _lazy_import("requests")
    if requests is None:
        return SkillResult(success=False, error="requests 库未安装", output="请执行: pip install requests")
    try:
        url = f"https://open.er-api.com/v6/latest/{from_currency.upper()}"
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return SkillResult(success=False, error=f"汇率查询失败: HTTP {resp.status_code}")
        rates = resp.json().get("rates", {})
        rate = rates.get(to_currency.upper())
        if rate is None:
            return SkillResult(success=False, error=f"不支持的目标货币: {to_currency}")
        converted = round(amount * rate, 4)
        return SkillResult(
            success=True,
            output=f"{amount} {from_currency.upper()} = {converted} {to_currency.upper()} (汇率: {rate})",
            data={"amount": amount, "from": from_currency.upper(), "to": to_currency.upper(), "rate": rate, "result": converted},
        )
    except Exception as e:
        return SkillResult(success=False, error=f"汇率查询异常: {e}", output=traceback.format_exc())

# ============================================================
# 统一入口
# ============================================================

# ============================================================
# 377-2：计算型 query 分流 —— 复利 / 利息本地计算
# ============================================================
# 背景：此前 "计算复利：本金 10000 元..." 这类请求没有 action 参数，
# 落到 execute() 的默认值 action="stats" → 被当成记账统计 → 空账本
# → 返回"暂无记账记录"（forced 模式也 MISS，唯一双 MISS）。
_COMPOUND_KEYWORDS = ("复利", "年化", "利息", "利率", "本金", "收益", "汇率", "贷款")

# 本金：本金/金额/存入/投资/贷款 后的数字
_P_PAT = r"(?:本金|金额|存入|投资|贷款|起始资金)\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)"
# 年利率：数字后紧跟 %
_R_PAT = r"([0-9]+(?:\.[0-9]+)?)\s*(?:%|％)"
# 年限：数字后紧跟 年/期
_N_PAT = r"([0-9]+(?:\.[0-9]+)?)\s*(?:年|期|years?)"


def _match_calc_query(query: str) -> bool:
    """判断是否为计算型 query（复利/利息/利率类）。"""
    if not query:
        return False
    return any(k in query for k in _COMPOUND_KEYWORDS)


def _compound_interest(query: str) -> SkillResult:
    """复利计算：本息合计 = P × (1 + r)^n。

    ★ 纯本地计算：不调用 LLM、不落账本、不产生副作用。
    ★ 抽取失败时返回 usage 提示（不抛异常、不计为命中）。
    """
    m_p = re.search(_P_PAT, query)
    m_r = re.search(_R_PAT, query)
    m_n = re.search(_N_PAT, query)
    if not (m_p and m_r and m_n):
        missing = []
        if not m_p:
            missing.append("本金（例：本金 10000 元）")
        if not m_r:
            missing.append("年利率（例：年利率 5%）")
        if not m_n:
            missing.append("年限（例：存 10 年）")
        return SkillResult(
            success=False,
            error="参数不足",
            output=("复利计算需要三个数字，未能从请求中识别：" + "、".join(missing)
                    + "\n用法示例：计算复利：本金 10000 元，年利率 5%，存 10 年"),
        )
    principal = float(m_p.group(1))
    rate = float(m_r.group(1)) / 100.0
    years = float(m_n.group(1))
    total = principal * (1.0 + rate) ** years
    interest = total - principal
    return SkillResult(
        success=True,
        output=(
            "复利计算结果：\n"
            f"本金：{principal:.2f} 元\n"
            f"年利率：{rate * 100:.2f}%\n"
            f"期限：{years:g} 年\n"
            f"本息合计：{total:.2f} 元\n"
            f"利息收益：{interest:.2f} 元\n"
            f"计算公式：{principal:.2f} × (1 + {rate * 100:.2f}%)^{years:g}"
        ),
        data={
            "type": "compound_interest",
            "principal": principal,
            "annual_rate": rate,
            "years": years,
            "total": round(total, 2),
            "interest": round(interest, 2),
            "formula": "P*(1+r)^n",
        },
    )


def execute(
    action: str = "stats",
    symbol: str = "",
    amount: float = 0,
    category: str = "other",
    description: str = "",
    entry_type: str = "expense",
    period: str = "month",
    from_currency: str = "USD",
    to_currency: str = "CNY",
    period_kline: str = "daily",
    count: int = 30,
    **kwargs,
) -> SkillResult:
    # ★ 377-2：计算型 query 优先分流（复利/利息/利率类）。
    #   必须排在 action 分支之前 —— 自然语言请求（只带 query、不带 action）
    #   此前会落到默认 action="stats"，被当成记账统计 → 空账本 →
    #   返回"暂无记账记录"，forced 模式同样 MISS。
    _q = " ".join(str(v) for v in (kwargs.get("query"), kwargs.get("q"),
                                   kwargs.get("text")) if v)
    if not _q and description and _match_calc_query(str(description)):
        _q = str(description)
    if _q and _match_calc_query(_q):
        return _compound_interest(_q)
    if action == "stock":
        if not symbol:
            return SkillResult(success=False, error="股票代码不能为空")
        return _stock_query(symbol)
    elif action == "realtime":
        if not symbol:
            return SkillResult(success=False, error="股票代码不能为空")
        data = _realtime_quote(symbol)
        if "error" in data:
            return SkillResult(success=False, error=data["error"], output=data["error"])
        hud_html = _render_quote_hud(data)
        return SkillResult(
            success=True,
            output=hud_html,
            data=data,
        )
    elif action == "kline":
        if not symbol:
            return SkillResult(success=False, error="股票代码不能为空")
        data = _kline_data(symbol, period_kline, count)
        if "error" in data:
            return SkillResult(success=False, error=data["error"], output=data["error"])
        canvas_js = _generate_kline_canvas_data(data.get("candles", []))
        img_b64 = _generate_kline_chart(data.get("candles", []))
        hud_html = _render_kline_hud(data, img_b64=img_b64, canvas_js=canvas_js)
        return SkillResult(
            success=True,
            output=hud_html,
            data=data,
        )
    elif action == "overview":
        data = _market_overview()
        hud_html = _render_overview_hud(data)
        return SkillResult(
            success=True,
            output=hud_html,
            data=data,
        )
    elif action == "record":
        if amount <= 0:
            return SkillResult(success=False, error="金额必须大于0")
        return _record_expense(amount, category, description, entry_type)
    elif action == "stats":
        return _get_stats(period)
    elif action == "convert":
        if amount <= 0:
            return SkillResult(success=False, error="金额必须大于0")
        return _currency_convert(amount, from_currency, to_currency)
    elif action == "list":
        ledger = _load_ledger()
        lines = [f"#{e.get('id','')} {e.get('type','')} {e.get('amount',0)} | {e.get('category','')} | {e.get('description','')} | {e.get('date','')}" for e in ledger[-20:]]
        return SkillResult(success=True, output="\n".join(lines) if lines else "暂无记录", data={"entries": ledger[-20:], "total": len(ledger)})
    else:
        return SkillResult(success=False, error=f"未知操作: {action}")

def register(registry) -> None:
    registry.register(SkillDef(
        name="finance_assistant",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["stock", "realtime", "kline", "overview", "record", "stats", "convert", "list"],
                    "description": ("操作类型：stock=行情(纯文本), realtime=实时行情HUD, kline=K线图, "
                                    "overview=大盘概览, record=记账, stats=统计, convert=货币换算, list=查看记录。"
                                    "注意：复利/利息计算无需指定 action —— query 中含 复利/利息/利率/本金/"
                                    "收益/汇率/贷款 等关键词时自动本地计算本息合计"),
                },
                "query": {
                    "type": "string",
                    "description": ("自然语言金融请求。计算类（复利/利息）直接传原文，"
                                    "例：'计算复利：本金 10000 元，年利率 5%，存 10 年'"),
                },
                "symbol": {"type": "string", "description": "股票代码（如 600519, AAPL, sh600519）"},
                "amount": {"type": "number", "description": "金额"},
                "category": {"type": "string", "description": "分类（如 food, transport, salary）", "default": "other"},
                "description": {"type": "string", "description": "备注说明"},
                "entry_type": {"type": "string", "enum": ["income", "expense"], "description": "收入/支出", "default": "expense"},
                "period": {"type": "string", "enum": ["all", "month", "week"], "description": "统计周期", "default": "month"},
                "period_kline": {"type": "string", "enum": ["daily", "weekly", "monthly"], "description": "K线周期", "default": "daily"},
                "count": {"type": "integer", "description": "K线根数", "default": 30},
                "from_currency": {"type": "string", "description": "源货币代码", "default": "USD"},
                "to_currency": {"type": "string", "description": "目标货币代码", "default": "CNY"},
            },
            "required": ["action"],
        },
        handler=execute,
        category=METADATA["category"],
        timeout=15,
    ))

def get_metadata() -> Dict[str, Any]:
    return METADATA
