# -*- coding: utf-8 -*-
"""
miemie_engine.py — 咩咩真实工具引擎
====================================
把底栏咩咩面板的 11 个工具从 mock 换成真实实现：
  glob / grep / read_file / write_file / edit_file / bash / web_fetch /
  analyze_style / memory_search / sql_query / plan

线程模型：
    MiemieEngineWorker(QThread) 在工作线程中顺序执行计划，逐步发射信号：
      step_event(dict)   : 工具调用块（tool/args/desc/state=running|done|error）
      result_event(dict) : 工具结果（tool/result）
      summary_event(dict): 任务摘要
      done_event(dict)   : 全部完成
    UI 侧逐条流式渲染，产生"工具链正在跑"的节奏感。

数据：
    - SQLite   : data/miemie/miemie.db     （tasks / sessions 表，惰性初始化）
    - 咩咩记忆  : data/miemie/miemie_memory.json

注意：本模块绝不改动 data/miemie/miemie_pixel_map.json（咩咩 OC 像素形象）。
"""

import os
import re
import io
import sys
import json
import time
import queue as _queue
import base64
import shutil
import threading
import glob as _glob
import sqlite3
import subprocess
import traceback
import urllib.request

from PyQt5.QtCore import QThread, pyqtSignal

try:
    import requests
except ImportError:
    requests = None

# 本机 LLM（Ollama）入口
_OLLAMA_URL = "http://127.0.0.1:11434"

# 项目根（lemon_agent）
_LEMON_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA_DIR = os.path.join(_LEMON_ROOT, "data", "miemie")
_DB_PATH = os.path.join(_DATA_DIR, "miemie.db")
_MEMORY_PATH = os.path.join(_DATA_DIR, "miemie_memory.json")

# 默认扫描忽略目录
_IGNORE_DIRS = {
    "node_modules", ".git", ".venv", "venv", "__pycache__",
    ".idea", ".vscode", "dist", "build", ".codebuddy",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
}

# 文本文件后缀（read_file 允许读取；其余一律拒绝二进制）
_TEXT_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".htm", ".css", ".scss",
    ".json", ".md", ".txt", ".toml", ".yml", ".yaml", ".ini", ".cfg",
    ".conf", ".sql", ".xml", ".svg", ".sh", ".bat", ".ps1", ".c", ".h",
    ".cpp", ".hpp", ".java", ".go", ".rs", ".rb", ".php", ".lua", ".vue",
}

_MAX_READ_CHARS = 200_000   # read_file 单文件读取上限
_MAX_MATCHES = 60           # grep/glob 最大返回条数


# =====================================================================
# 数据初始化（惰性）
# =====================================================================

def _ensure_data_dir():
    os.makedirs(_DATA_DIR, exist_ok=True)


def init_database():
    """初始化 SQLite：tasks / sessions 表，无表则建表并预置种子数据。"""
    _ensure_data_dir()
    conn = sqlite3.connect(_DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS tasks ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " name TEXT NOT NULL,"
            " status TEXT DEFAULT '进行中',"
            " ts TEXT DEFAULT (datetime('now','localtime'))"
            ")"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS sessions ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " title TEXT NOT NULL,"
            " ts TEXT DEFAULT (datetime('now','localtime'))"
            ")"
        )
        n = cur.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        if n == 0:
            for name, status in [
                ("咩咩像素化", "完成"),
                ("底栏面板改造", "进行中"),
                ("能力调用接口", "规划"),
                ("工具引擎接入", "规划"),
                ("OC 形象提取", "完成"),
            ]:
                cur.execute("INSERT INTO tasks(name, status) VALUES (?,?)", (name, status))
        conn.commit()
    finally:
        conn.close()


def init_memory():
    """初始化咩咩记忆库 JSON；文件缺失时写入预置记忆。"""
    _ensure_data_dir()
    if os.path.exists(_MEMORY_PATH):
        return
    seed = {
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "entries": [
            {"topic": "用户偏好", "detail": "深色主题 · 高对比度 · 简洁界面"},
            {"topic": "咩咩形象", "detail": "唯一形象来源为用户 OC 图提取的像素矩阵，禁止手绘替换"},
            {"topic": "项目结构", "detail": "lemon_agent 主项目 + MIEMIE 独立项目"},
            {"topic": "代码风格", "detail": "snake_case 命名 · 4 空格缩进 · 中文注释"},
            {"topic": "底栏定位", "detail": "咩咩是 Agent 工作者：半对话半操作，工具链驱动"},
        ],
    }
    with open(_MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(seed, f, ensure_ascii=False, indent=2)


def ensure_data():
    """确保数据库与记忆库就绪（幂等）。"""
    init_database()
    init_memory()


# 预置记忆主题（清洗时永不删除）
_SEED_TOPICS = {"用户偏好", "咩咩形象", "项目结构", "代码风格", "底栏定位"}


def memory_evolve(user_text, outcome="", kind="task"):
    """咩咩记忆进化：把一次任务/对话沉淀为记忆条目（自我更新人格与偏好）。

    kind:
      - "task"  工具类任务（记录：指令 → 结果摘要）
      - "chat"  聊天对话（记录用户话题）
    - 偏好类指令（"我喜欢/记住/偏好"等）额外生成"用户偏好"条目。
    - 条目上限 80，清洗时优先删最旧的非预置条目，预置主题永不删除。
    任何失败都静默（不阻塞主流程）。
    """
    try:
        _ensure_data_dir()
        data = {}
        if os.path.exists(_MEMORY_PATH):
            with open(_MEMORY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        entries = data.get("entries") or []
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        text = (user_text or "").strip()
        if not text:
            return

        # 1) 偏好类指令 → 更新/新增"用户偏好"条目
        pref_kw = ("记住", "我喜欢", "我不喜欢", "偏好", "以后", "别忘了", "每次都")
        if any(k in text for k in pref_kw):
            detail = text[:120]
            found = False
            for e in entries:
                if e.get("topic") == "用户偏好" and e.get("detail") == detail:
                    e["updated"] = now
                    found = True
                    break
            if not found:
                entries.insert(0, {"topic": "用户偏好", "detail": detail,
                                   "src": "pref", "updated": now})

        # 2) 任务/对话记录
        if kind == "task" and outcome:
            summary = (outcome or "").strip().replace("\n", " ")[:140]
            entries.insert(0, {"topic": "任务记录", "src": "task",
                               "detail": f"[{now}] {text[:40]} → {summary}",
                               "updated": now})
        elif kind == "chat":
            entries.insert(0, {"topic": "对话记录", "src": "chat",
                               "detail": f"[{now}] 用户说：{text[:100]}",
                               "updated": now})

        # 3) 上限清洗：<=80 条，优先删最旧的非预置条目
        if len(entries) > 80:
            removable = [i for i, e in enumerate(entries)
                         if e.get("topic") not in _SEED_TOPICS]
            removable.sort(key=lambda i: entries[i].get("updated", ""))
            entries = [e for i, e in enumerate(entries) if i not in removable[:len(entries) - 80]]

        data["entries"] = entries
        data["updated"] = now
        with open(_MEMORY_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# =====================================================================
# 路径辅助
# =====================================================================

def _resolve(path):
    """相对路径基于项目根解析；绝对路径原样返回。"""
    if not path:
        return _LEMON_ROOT
    if os.path.isabs(path):
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(_LEMON_ROOT, path))


def _walk(root):
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS and not d.startswith(".")]
        for f in files:
            yield os.path.join(base, f)


# =====================================================================
# 工具实现（全部真实执行）
# =====================================================================

def tool_glob(pattern="**/*.py", max_results=_MAX_MATCHES):
    """真实 glob：扫描项目内文件（排除依赖/构建目录）。"""
    ensure_data()
    if pattern in ("**/*", "*", ""):
        pattern = "**/*.py"
    pat = re.sub(r"^\*\*/?", "", pattern)
    if "*" not in pat:
        pat = "**/" + pat
    name_re = None
    if "." in pat and "*" not in pat.split("/")[-1]:
        pass
    # 用 fnmatch 逐文件匹配
    import fnmatch
    root = _LEMON_ROOT
    matches = []
    pat = pat.replace("**", "*")
    for fp in _walk(root):
        rel = os.path.relpath(fp, root).replace("\\", "/")
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(os.path.basename(rel), pattern.split("/")[-1] if "/" in pattern else pattern):
            matches.append(rel)
        if len(matches) >= max_results:
            break
    if not matches:
        # 回退：返回项目内常见代码文件
        for fp in _walk(root):
            if fp.endswith((".py", ".js", ".html", ".md")):
                matches.append(os.path.relpath(fp, root).replace("\\", "/"))
            if len(matches) >= max_results:
                break
    return {"ok": True, "pattern": pattern, "matches": matches[:max_results],
            "count": len(matches[:max_results]), "root": root}


def tool_grep(pattern="TODO|FIXME", path_filter="", max_results=_MAX_MATCHES):
    """真实 grep：正则搜索项目内文本文件。"""
    ensure_data()
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return {"ok": False, "error": f"正则错误: {e}"}
    root = _LEMON_ROOT if not path_filter else _resolve(path_filter)
    if not os.path.isdir(root):
        root = _LEMON_ROOT
    hits = []
    for fp in _walk(root):
        if not fp.endswith(tuple(_TEXT_EXTS)):
            continue
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                for ln, line in enumerate(f, 1):
                    if rx.search(line):
                        hits.append({
                            "file": os.path.relpath(fp, root).replace("\\", "/"),
                            "line": ln,
                            "text": line.strip()[:120],
                        })
                        if len(hits) >= max_results:
                            return {"ok": True, "pattern": pattern, "matches": hits,
                                    "count": len(hits)}
        except (OSError, UnicodeDecodeError):
            continue
    return {"ok": True, "pattern": pattern, "matches": hits, "count": len(hits)}


def tool_read_file(path):
    """真实读取文件内容。"""
    ensure_data()
    fp = _resolve(path)
    if not os.path.isfile(fp):
        return {"ok": False, "error": f"文件不存在: {path}"}
    if not fp.endswith(tuple(_TEXT_EXTS)):
        return {"ok": False, "error": f"非文本文件（拒绝读取二进制）: {path}"}
    try:
        with open(fp, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(_MAX_READ_CHARS + 1)
        truncated = len(content) > _MAX_READ_CHARS
        content = content[:_MAX_READ_CHARS]
        return {"ok": True, "path": fp, "lines": content.count("\n") + 1,
                "chars": len(content), "truncated": truncated, "content": content}
    except OSError as e:
        return {"ok": False, "error": f"读取失败: {e}"}


def tool_write_file(path, content=""):
    """真实写入文件（覆盖）。"""
    ensure_data()
    fp = _resolve(path)
    try:
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "w", encoding="utf-8") as f:
            f.write(content)
        return {"ok": True, "path": fp, "chars": len(content)}
    except OSError as e:
        return {"ok": False, "error": f"写入失败: {e}"}


def tool_edit_file(path, old="", new="", count=1):
    """真实字符串替换。"""
    ensure_data()
    fp = _resolve(path)
    if not os.path.isfile(fp):
        return {"ok": False, "error": f"文件不存在: {path}"}
    if not old:
        return {"ok": False, "error": "缺少 old（要替换的原文）"}
    try:
        with open(fp, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        if count and count > 1:
            n = content.count(old)
            content = content.replace(old, new, count)
        elif count == 0:
            n = content.count(old)
            content = content.replace(old, new)
        else:
            n = content.count(old)
            content = content.replace(old, new, 1)
        with open(fp, "w", encoding="utf-8") as f:
            f.write(content)
        return {"ok": True, "path": fp, "replaced": n}
    except OSError as e:
        return {"ok": False, "error": f"编辑失败: {e}"}


def tool_bash(command):
    """真实执行 shell 命令（超时 20s）。"""
    ensure_data()
    if not command:
        return {"ok": False, "error": "命令为空"}
    try:
        proc = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=20,
            cwd=_LEMON_ROOT,
        )
        return {"ok": proc.returncode == 0, "command": command,
                "exit_code": proc.returncode,
                "stdout": (proc.stdout or "")[:8000],
                "stderr": (proc.stderr or "")[:4000]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "命令超时（>20s）", "command": command}
    except Exception as e:
        return {"ok": False, "error": f"执行失败: {e}"}


def tool_web_fetch(url):
    """真实抓取网页文本（超时 8s，截断）。"""
    ensure_data()
    if not url.startswith(("http://", "https://")):
        return {"ok": False, "error": "仅支持 http/https URL"}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "LemonCode-MIEMIE/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read(60_000)
        text = raw.decode("utf-8", errors="replace")
        text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.I)
        text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return {"ok": True, "url": url, "chars": len(text), "text": text[:3000]}
    except Exception as e:
        return {"ok": False, "error": f"抓取失败: {e}"}


def tool_analyze_style(directory=""):
    """真实代码风格分析（复用 miemie.code_clone.CodeCloneAnalyzer）+ stylometry 提炼。

    ★ v4.3.9: 在原有画像基础上提炼"人格可消费"的字段：
      comment_density / error_style / long_function_ratio / short_function_ratio /
      pattern_detected / style_brief（一行中文风格画像，供 persona_extract 直接消费）
    """
    ensure_data()
    target = _resolve(directory)
    if not os.path.isdir(target):
        target = _LEMON_ROOT
    try:
        sys.path.insert(0, _LEMON_ROOT)
        from miemie.code_clone import CodeCloneAnalyzer
        analyzer = CodeCloneAnalyzer()
        profile = analyzer.analyze_directory(target, pattern="*.py", max_files=120)
        d = profile.to_dict()
        naming = d.get("naming", {})
        indent = d.get("indentation", {})
        flen = d.get("function_length", {})
        cmt = d.get("comments", {})
        err = d.get("error_handling", {})
        pat = d.get("design_patterns", {})
        # naming 无 dominant 键（dominant 是 NamingStats 的方法），手动取计数最大的风格
        _cands = {k: naming.get(k, 0) for k in
                  ("snake_case", "camel_case", "pascal_case", "constant_case")}
        dominant = max(_cands, key=_cands.get) if sum(_cands.values()) else "unknown"
        # avg_length 字段未填充，按 distribution 估算平均函数长度
        dist = flen.get("distribution", {})
        if flen.get("avg_length", 0) > 0:
            avg_len = flen["avg_length"]
        else:
            buckets = {"1-10": 5.5, "11-30": 20, "31-50": 40, "51-100": 75, "100+": 120}
            total = sum(dist.values()) or 1
            avg_len = sum(buckets.get(k, 30) * v for k, v in dist.items()) / total
        long_ratio = flen.get("long_function_ratio", 0)
        short_ratio = flen.get("short_function_ratio", 0)
        error_style = err.get("style", "unknown")
        pattern_detected = pat.get("detected", [])
        comment_density = cmt.get("density", 0)
        style_brief = _build_style_brief(
            dominant, indent, avg_len, long_ratio, short_ratio,
            error_style, pattern_detected, comment_density, d.get("tags", []))
        return {
            "ok": True,
            "target": target,
            "files_analyzed": d.get("files_analyzed", 0),
            "total_lines": d.get("total_lines", 0),
            "naming_style": dominant,
            "indent_style": indent.get("style", "unknown"),
            "indent_width": indent.get("width", 0),
            "avg_function_length": round(avg_len, 1),
            "long_function_ratio": round(long_ratio * 100, 1),
            "short_function_ratio": round(short_ratio * 100, 1),
            "comment_density": round(comment_density * 100, 1),
            "error_style": error_style,
            "pattern_detected": pattern_detected,
            "style_brief": style_brief,
            "tags": d.get("tags", []),
            "summary": d.get("summary", ""),
            "profile": d,
        }
    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": f"风格分析失败: {e}"}


def _build_style_brief(naming, indent, avg_len, long_ratio, short_ratio,
                       error_style, pattern_detected, comment_density, tags):
    """把代码风格统计提炼成一行中文画像（供人格抽取 LLM 消费）。"""
    parts = []
    if naming and naming != "unknown":
        parts.append(f"命名偏好{_STYLE_CN.get(naming, naming)}")
    if indent.get("style") == "spaces" and indent.get("width"):
        parts.append(f"{indent['width']}空格缩进")
    elif indent.get("style") == "tabs":
        parts.append("Tab缩进")
    if comment_density > 0:
        if comment_density >= 0.2:
            parts.append("注释较丰富")
        elif comment_density <= 0.05:
            parts.append("注释极少")
    if long_ratio > 0.3:
        parts.append("函数偏长")
    elif short_ratio > 0.5:
        parts.append("偏好短函数")
    if error_style and error_style != "unknown":
        parts.append(f"错误处理偏{_STYLE_CN.get(error_style, error_style)}")
    if pattern_detected:
        parts.append("使用设计模式:" + "/".join(pattern_detected[:4]))
    if tags:
        parts.append("标签:" + "/".join(tags[:4]))
    return "；".join(parts) if parts else "风格特征不明显"


# 中文化短标签（供 _build_style_brief 使用）
_STYLE_CN = {
    "snake_case": "snake_case", "camel_case": "camelCase", "pascal_case": "PascalCase",
    "constant_case": "CONSTANT_CASE",
    "try-except": "try-except", "if-check": "if-check", "logging": "logging", "mixed": "混合",
}


def tool_memory_search(query="", max_results=8):
    """真实记忆检索：关键词命中评分。"""
    ensure_data()
    try:
        with open(_MEMORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"ok": False, "error": "记忆库不可用"}
    entries = data.get("entries", [])
    if not query:
        # 无查询词：按更新时间倒序返回最近记忆
        entries = sorted(entries, key=lambda e: e.get("updated", ""), reverse=True)
        return {"ok": True, "query": query, "entries": entries[:max_results]}
    q = query.lower()
    scored = []
    for e in entries:
        topic = e.get("topic", "")
        detail = e.get("detail", "")
        hay = (topic + " " + detail).lower()
        score = sum(1 for kw in re.split(r"[\s,，。]+", q) if kw and kw in hay)
        # topic 命中加权（用户偏好/对话记录等分类优先）
        if topic and any(kw in topic.lower() for kw in re.split(r"[\s,，。]+", q) if kw):
            score += 3
        if score > 0 or q in hay:
            scored.append((score, e))
    scored.sort(key=lambda x: (-x[0], x[1].get("updated", "")), reverse=True)
    scored.sort(key=lambda x: x[0], reverse=True)
    return {"ok": True, "query": query,
            "entries": [e for _, e in scored[:max_results]]}


# =====================================================================
# 人格分身（★ v4.3.9 P1：Layer 1 人格档案 + Big Five 抽取 + 置信度融合）
# =====================================================================

# Layer 1 人格档案（人格是提炼物，不是档案馆——只存画像，不存原始数据）
_PERSONA_PATH = os.path.join(_DATA_DIR, "miemie_persona.json")

# Big Five（OCEAN）中文维度——心理学界公认框架，比 MBTI 更可辩护
_BIG5_LABELS = {
    "openness": "开放性",
    "conscientiousness": "尽责性",
    "extraversion": "外向性",
    "agreeableness": "宜人性",
    "neuroticism": "神经质",
}

# 人格抽取系统提示：让 LLM 从代码风格 + 文本素材推断 Big Five 画像（JSON）
_BIG5_SYSTEM_PROMPT = (
    "你是人格心理学分析师。根据【程序员代码风格画像】与【用户文本素材】"
    "（聊天记录/朋友圈/自述等），推断用户的大五人格（Big Five, OCEAN）画像。\n"
    "只输出一个 JSON 对象，不要输出任何其他文字。格式：\n"
    "{\n"
    '  "openness": {"score": 0-100, "confidence": 0-1, "evidence": "中文依据"},'
    '  "conscientiousness": {...}, "extraversion": {...},\n'
    '  "agreeableness": {...}, "neuroticism": {...},\n'
    '  "communication": "沟通风格一句话",\n'
    '  "aesthetic": "审美/品味偏好一句话",\n'
    '  "portrait": "整体人格画像一句话"\n'
    "}\n"
    "规则：\n"
    "1. score 为维度得分，50 为中等，越高越偏向该特质（如尽责性高=有条理自律）。\n"
    "2. confidence 为推断把握度 0~1，素材少就给低值，绝不虚高。\n"
    "3. evidence 用中文简述依据（如：命名整洁、注释丰富、错误处理谨慎）。\n"
    "4. 只依据提供的素材推断，素材不足时降低 confidence，不要编造。"
)


def _clamp_num(v, lo, hi, default=0.0):
    """安全地把任意值夹到 [lo, hi]，非法返回 default。"""
    try:
        n = float(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _parse_big5_json(raw):
    """从 LLM 输出中提取 JSON 对象（容忍前后说明文字）。"""
    if not raw:
        return None
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _load_persona():
    """读取人格档案；缺失/损坏返回 None。"""
    try:
        with open(_PERSONA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _fuse_score(old, new):
    """单个维度的置信度加权融合（贝叶斯式信念更新，不覆盖旧档案）。

    old/new: {"score": float, "confidence": float, "evidence": str}
    新证据权重 = 新置信度 / (旧置信度 + 新置信度)；置信度提升做衰减累加。
    """
    if not new:
        return old
    old_c = _clamp_num(old.get("confidence"), 0, 1, 0.5) if old else 0.0
    new_c = _clamp_num(new.get("confidence"), 0, 1, 0.5)
    if new_c <= 0:
        return old
    w_new = new_c / (old_c + new_c) if (old_c + new_c) > 0 else 0.5
    old_s = _clamp_num(old.get("score"), 0, 100, 50) if old else 50.0
    new_s = _clamp_num(new.get("score"), 0, 100, 50)
    fused_s = round(old_s * (1 - w_new) + new_s * w_new, 1)
    fused_c = round(min(0.99, old_c + (1 - old_c) * new_c * 0.5), 3)
    evidence = (new.get("evidence") or "").strip() or (old.get("evidence") or "" if old else "")
    return {"score": fused_s, "confidence": fused_c, "evidence": evidence}


def _fuse_persona(old, new):
    """把一次抽取结果融合进旧人格档案（置信度加权，不覆盖）。"""
    if not new:
        return old
    if not old:
        return new
    old_big5 = old.get("big5") or {}
    new_big5 = new.get("big5") or {}
    fused_big5 = {}
    for k in _BIG5_LABELS:
        fused_big5[k] = _fuse_score(old_big5.get(k), new_big5.get(k))
    old["big5"] = fused_big5
    # 沟通/审美/画像：新证据非空则更新（保留旧值兜底）
    for k in ("communication", "aesthetic", "portrait"):
        v = (new.get(k) or "").strip()
        if v:
            old[k] = v
    # 来源合并
    old["sources"] = sorted(set(old.get("sources") or []) | set(new.get("sources") or []))
    old["updated"] = new.get("updated") or old.get("updated", "")
    return old


def persona_extract(text="", code_style=None, model=""):
    """人格抽取核心：代码风格 + 文本素材 → Big Five 人格档案（写 Layer 1）。

    返回：
        {"ok": True, "persona": {...}, "updated": "..."}  成功（已落盘融合）
        {"ok": False, "error": "..."}                     失败（Ollama 不可用等）
    """
    _ensure_data_dir()
    blocks = []
    if code_style:
        blocks.append("【程序员代码风格画像】" +
                      json.dumps(code_style, ensure_ascii=False, default=str)[:1500])
    if text and str(text).strip():
        blocks.append("【用户文本素材】" + str(text).strip()[:3000])
    if not blocks:
        return {"ok": False, "error": "缺少素材：请提供代码风格（analyze_style）或文本内容（聊天/朋友圈/自述）"}

    ok, content = _ollama_chat(
        [{"role": "system", "content": _BIG5_SYSTEM_PROMPT},
         {"role": "user", "content": "\n\n".join(blocks)}],
        model=model,
        timeout=180,
    )
    if not ok or not content:
        return {"ok": False, "error": f"人格抽取失败（Ollama 不可用或超时）: {content}"}
    parsed = _parse_big5_json(content)
    if not parsed:
        return {"ok": False, "error": "模型输出无法解析为 JSON，请重试或检查模型"}

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    big5 = {}
    for k in _BIG5_LABELS:
        v = parsed.get(k)
        if isinstance(v, dict):
            big5[k] = {
                "score": _clamp_num(v.get("score"), 0, 100, 50),
                "confidence": _clamp_num(v.get("confidence"), 0, 1, 0.5),
                "evidence": str(v.get("evidence") or "")[:200],
            }
    sources = []
    if code_style:
        sources.append("code")
    if text and str(text).strip():
        sources.append("text")
    new_p = {
        "updated": now,
        "sources": sources,
        "big5": big5,
        "communication": str(parsed.get("communication") or "")[:200],
        "aesthetic": str(parsed.get("aesthetic") or "")[:200],
        "portrait": str(parsed.get("portrait") or "")[:300],
    }
    merged = _fuse_persona(_load_persona(), new_p)
    with open(_PERSONA_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    return {"ok": True, "persona": merged, "updated": now}


def tool_persona_extract(text="", code_style_json="", model=""):
    """真实工具：抽取/更新用户人格画像（Big Five + 沟通/审美偏好）。

    参数：
        text:            聊天记录/朋友圈/自述等文本（可空）
        code_style_json: analyze_style 输出（JSON 字符串，可空）
        model:           指定模型名，空则自动挑选
    """
    ensure_data()
    code_style = None
    if code_style_json:
        try:
            code_style = json.loads(code_style_json) if isinstance(code_style_json, str) else code_style_json
        except json.JSONDecodeError:
            code_style = {"raw": str(code_style_json)[:500]}
    res = persona_extract(text=text, code_style=code_style, model=model)
    if not res.get("ok"):
        return res
    p = res["persona"]
    big5 = p.get("big5") or {}
    brief = ["人格画像已更新（Layer 1）：" + (p.get("portrait") or "已生成")]
    for k, label in _BIG5_LABELS.items():
        v = big5.get(k) or {}
        brief.append(f"- {label}: {v.get('score', '-')}/100（置信度 {v.get('confidence', '-')}）")
    if p.get("communication"):
        brief.append(f"- 沟通风格: {p['communication']}")
    if p.get("aesthetic"):
        brief.append(f"- 审美偏好: {p['aesthetic']}")
    return {
        "ok": True,
        "summary": "\n".join(brief),
        "sources": p.get("sources", []),
        "updated": res.get("updated", ""),
        "persona": p,
    }


# =====================================================================
# ★ v4.3.9 P2：多模态喂料 + 图层级记忆（Layer2 索引 + Layer3 原始档案）
# =====================================================================

# Layer 3 原始档案目录（按日期分文件夹存原图/原文，冷数据按需细读）
_ARCHIVE_DIR = os.path.join(_DATA_DIR, "archive")
# Layer 2 索引（只记"哪天哪类事"，不存全文）
_ARCHIVE_INDEX_PATH = os.path.join(_DATA_DIR, "miemie_archive_index.json")


def _load_archive_index():
    """读取 Layer2 索引；缺失/损坏返回 []。"""
    try:
        with open(_ARCHIVE_INDEX_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("items", [])
    except (OSError, json.JSONDecodeError):
        return []


def _save_archive_index(items):
    _ensure_data_dir()
    with open(_ARCHIVE_INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump({"updated": time.strftime("%Y-%m-%d %H:%M:%S"), "items": items},
                  f, ensure_ascii=False, indent=2)


def archive_store(kind="text", content="", filename="", desc=""):
    """归档原始素材到 Layer3（按日期分文件夹），并在 Layer2 登记索引。

    kind: "text"（聊天/朋友圈文本）| "image"（图片，content 为源图片路径，拷贝归档）
    desc: 一句话摘要（写入 Layer2 索引）
    返回 {"ok": True, "file": "相对路径"}。
    """
    _ensure_data_dir()
    today = time.strftime("%Y-%m-%d")
    day_dir = os.path.join(_ARCHIVE_DIR, today)
    os.makedirs(day_dir, exist_ok=True)
    if not filename:
        ext = ".jpg" if kind == "image" else ".txt"
        filename = f"{kind}_{int(time.time())}{ext}"
    safe = re.sub(r'[\\/:*?"<>|]', "_", filename)
    dest = os.path.join(day_dir, safe)
    try:
        if kind == "image" and os.path.isfile(content):
            shutil.copy2(content, dest)
        else:
            with open(dest, "w", encoding="utf-8") as f:
                f.write(str(content or ""))
    except Exception as e:
        return {"ok": False, "error": f"归档失败: {e}"}
    rel = os.path.relpath(dest, _DATA_DIR).replace("\\", "/")
    items = _load_archive_index()
    items.insert(0, {
        "date": today, "kind": kind, "file": rel,
        "desc": str(desc or "")[:120],
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    _save_archive_index(items[:200])   # 索引上限 200 条
    return {"ok": True, "file": rel}


def tool_memory_index(query="", date=""):
    """检索 Layer2 档案索引（按关键词/日期），供"提醒后细读 Layer3"使用。"""
    ensure_data()
    items = _load_archive_index()
    if date:
        items = [i for i in items if i.get("date") == date]
    if query:
        q = query.lower()
        items = [i for i in items if q in (i.get("desc", "") + " " + i.get("file", "")).lower()]
    return {"ok": True, "query": query, "date": date,
            "count": len(items), "items": items[:30]}


def _pick_vision_model(models):
    """挑选视觉模型（qwen3-vl / qwen-vl / llava 等）。"""
    for pref in ("qwen3-vl", "qwen2-vl", "qwen-vl", "minicpm"):
        for m in models:
            if m.startswith(pref) or m.split(":")[0] == pref:
                return m
    for m in models:
        low = m.lower()
        if "vl" in low or "llava" in low:
            return m
    return ""


def _ollama_chat_vision(prompt, image_b64, model="", timeout=180, num_ctx=4096):
    """调 Ollama /api/chat 带单张 base64 图片（视觉理解/OCR）。

    num_ctx: 上下文窗口（KV cache）。视觉模型默认上下文极大（如 128k），
    本机内存不足时会导致 llama-server OOM，显式限制 num_ctx 可避免；
    但需大于图片 token 数（通常 2k~4k），调用方可按需调大。
    返回 (ok, content/err)。
    """
    if requests is None:
        return False, "requests 库不可用"
    if not model:
        models = _ollama_models()
        if not models:
            return False, "Ollama 未运行（localhost:11434）或无可用模型"
        model = _pick_vision_model(models)
        if not model:
            return False, "本机无视觉模型（需 qwen3-vl / llava）"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt, "images": [image_b64]}],
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 1024, "num_ctx": num_ctx},
    }
    try:
        resp = requests.post(f"{_OLLAMA_URL}/api/chat", json=payload, timeout=timeout)
        if resp.status_code != 200:
            return False, f"Ollama HTTP {resp.status_code}: {resp.text[:200]}"
        msg = resp.json().get("message", {}) or {}
        content = (msg.get("content", "") or "").strip()
        return (True, content) if content else (False, "视觉模型返回空结果")
    except requests.exceptions.ConnectionError:
        return False, "Ollama 连接失败（localhost:11434）"
    except requests.exceptions.Timeout:
        return False, "Ollama 响应超时"
    except Exception as e:
        return False, f"Ollama 异常: {e}"


def _image_to_b64_preview(path, max_side=1280, max_bytes=1024 * 1024):
    """图片 → base64（大图等比压缩预处理）。

    ★ v4.4.1：视觉模型按图片 token 计费，超大图/长边过大会吃满上下文且拖慢速度。
    用 PIL 等比缩放到 max_side 内、再以 JPEG quality 控制体积，明显降 token 提速；
    压缩失败（无 PIL/损坏）则回退原图 base64。
    返回 base64 字符串；读取失败返回 None。
    """
    try:
        with open(path, "rb") as f:
            raw = f.read()
        try:
            from PIL import Image
            import io as _io
            img = Image.open(_io.BytesIO(raw))
            img.load()
            w, h = img.size
            if max(w, h) > max_side:
                scale = max_side / float(max(w, h))
                img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                                  Image.LANCZOS)
            buf = _io.BytesIO()
            img.convert("RGB").save(buf, "JPEG", quality=85, optimize=True)
            out = buf.getvalue()
            if len(out) < len(raw) or len(out) <= max_bytes:
                return base64.b64encode(out).decode("ascii")
        except Exception:
            pass
        # 回退：原图直接 base64
        return base64.b64encode(raw).decode("ascii")
    except OSError:
        return None


def tool_vision_analyze(path="", prompt=""):
    """视觉分析：用 qwen3-vl 读图片（内容理解 + 图内文字 OCR + 风格线索）。

    参数：
        path:  图片路径（相对项目根或绝对）
        prompt: 自定义提示（默认自动含内容描述/OCR/审美线索三问）

    ★ 坑（实测）：qwen3-vl:4b 默认上下文极大，本机内存不足会
    "llama-server OOM: failed to allocate buffer for kv cache"。
    方案：① 显式 num_ctx=4096（够装 2k~4k 图片 token）；② 大图先用 PIL
    等比压缩（长边 ≤1280，JPEG q85），进一步降 token；仍超 token 自动重试 8192。
    """
    ensure_data()
    if not path:
        return {"ok": False, "error": "缺少图片路径"}
    target = _resolve(path)
    if not os.path.isfile(target):
        return {"ok": False, "error": f"图片不存在: {target}"}
    b64 = _image_to_b64_preview(target)
    if b64 is None:
        return {"ok": False, "error": "读取图片失败（可能损坏或格式不支持）"}
    q = prompt or (
        "请用中文分析这张图片：\n"
        "1) 描述图片内容（场景、主体、色彩、构图）；\n"
        "2) 提取图中所有文字（OCR），逐条列出；\n"
        "3) 结合图片内容，推测图片主人的审美偏好或生活风格（一句话）。"
    )
    ok, content = _ollama_chat_vision(q, b64, num_ctx=4096)
    if not ok:
        if "context size" in str(content):
            # 图片 token 超出 4096：加大上下文重试
            ok, content = _ollama_chat_vision(q, b64, num_ctx=8192)
        elif "out-of-memory" in str(content) or "failed to allocate" in str(content):
            return {"ok": False,
                    "error": f"视觉模型内存不足（{content[:120]}）。"
                             "可尝试：在 Ollama 服务端加大内存，或改用更小图片。"}
        if not ok:
            return {"ok": False, "error": f"视觉分析失败: {content}"}
    return {"ok": True, "path": target, "model": _pick_vision_model(_ollama_models()),
            "description": content}


def tool_persona_feed(text="", image_paths="", image_caption=""):
    """多源喂料：聊天/朋友圈文本 + 图片（视觉解读）→ 融合进人格档案。

    参数：
        text:          聊天记录/朋友圈文字/自述（可空）
        image_paths:   逗号分隔的图片路径列表（可空，逐张视觉解读）
        image_caption: 图片说明（可空，配合图片使用）
    流程：图片→qwen3-vl 解读→与文本合并→persona_extract 融合→原素材归档 Layer3。
    """
    ensure_data()
    materials = []
    sources = []
    # 1) 文本素材
    if text and str(text).strip():
        materials.append("【聊天/朋友圈文本】" + str(text).strip()[:3000])
        sources.append("text")
    # 2) 图片素材（逐张视觉解读）
    imgs = [p.strip() for p in re.split(r"[,，;；]+", image_paths or "") if p.strip()]
    vis_lines = []
    for p in imgs:
        vr = tool_vision_analyze(path=p)
        if vr.get("ok"):
            vis_lines.append(f"【图片 {os.path.basename(p)}】\n{vr['description']}")
            archive_store("image", p, filename=os.path.basename(p), desc="朋友圈/图片喂料")
            sources.append("image")
        else:
            vis_lines.append(f"【图片 {os.path.basename(p)} 分析失败】{vr.get('error')}")
    if vis_lines:
        materials.append("【图片视觉解读】\n" + "\n".join(vis_lines))
    # 3) 图片说明
    if image_caption and str(image_caption).strip():
        materials.append("【图片说明】" + str(image_caption).strip()[:500])
        sources.append("caption")
    if not materials:
        return {"ok": False, "error": "缺少素材：请提供文本、图片路径或图片说明"}
    # 4) 融合进人格档案
    res = persona_extract(text="\n\n".join(materials))
    if not res.get("ok"):
        return res
    # 5) 文本素材归档 Layer3（原始档案，冷数据）
    archive_store("text", "\n\n".join(materials), desc="人格喂料汇总")
    return {"ok": True,
            "summary": f"已融合 {len(sources)} 类素材（{'/'.join(sources)}）→ "
                       f"{(res['persona'].get('portrait') or '画像已更新')}",
            "updated": res.get("updated"), "persona": res["persona"]}


# =====================================================================
# ★ v4.3.9 P3：分身校准（用户本人反馈优先，高置信度更新）
# =====================================================================

_CALIBRATE_SYSTEM_PROMPT = (
    "你是人格校准助手。用户会对 AI 分身的人格画像提出修正反馈，"
    "请把反馈解析成 Big Five 维度上的调整。只输出一个 JSON 对象：\n"
    '{"big5": {"openness": {"score": 55, "confidence": 0.9, "evidence": "用户反馈：…"}}}\n'
    "规则：\n"
    "1. 只输出用户明确提到的维度；未提到的不要出现。\n"
    "2. score 为调整后的新分数（0-100，50 中等），confidence 给 0.9（用户本人反馈可信度高）。\n"
    "3. evidence 用中文写用户原话要点。不要输出任何其他文字。"
)


def tool_persona_calibrate(feedback=""):
    """分身校准：用户反馈 → 高置信度更新人格档案（用户本人反馈优先）。"""
    ensure_data()
    feedback = (feedback or "").strip()
    if not feedback:
        return {"ok": False, "error": "缺少校准反馈"}
    ok, content = _ollama_chat(
        [{"role": "system", "content": _CALIBRATE_SYSTEM_PROMPT},
         {"role": "user", "content": feedback}],
        timeout=120,
    )
    if not ok or not content:
        return {"ok": False, "error": f"校准失败（Ollama 不可用或超时）: {content}"}
    parsed = _parse_big5_json(content)
    if not parsed:
        return {"ok": False, "error": "模型输出无法解析为 JSON，请重试"}
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    new_big5 = {}
    for k in _BIG5_LABELS:
        v = (parsed.get("big5") or {}).get(k)
        if isinstance(v, dict):
            new_big5[k] = {
                "score": _clamp_num(v.get("score"), 0, 100, 50),
                "confidence": _clamp_num(v.get("confidence"), 0, 1, 0.9),
                "evidence": str(v.get("evidence") or f"用户校准：{feedback[:80]}")[:200],
            }
    if not new_big5:
        return {"ok": False, "error": "校准反馈未命中任何人格维度"}
    new_p = {"updated": now, "sources": ["calibrate"], "big5": new_big5}
    merged = _fuse_persona(_load_persona(), new_p)
    with open(_PERSONA_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    brief = ["分身校准完成（用户本人反馈，高置信度）："]
    for k, label in _BIG5_LABELS.items():
        v = new_big5.get(k)
        if v:
            brief.append(f"- {label}: {v['score']}/100")
    return {"ok": True, "summary": "\n".join(brief), "updated": now, "persona": merged}


# =====================================================================
# ★ v4.4.1 异步后台炼化队列（大文件/大批量喂料不阻塞 UI）
#
# 用户可把聊天记录/朋友圈截图/图片说明一次性丢进队列，后台线程逐项
# 炼化（persona_feed），状态持久化到 JSON，前端轮询 tool_persona_status。
# 这对应"本地模型慢也没关系，哪怕花一天，异步后台跑"的产品定位。
# =====================================================================

_REFINE_STATUS_PATH = os.path.join(_DATA_DIR, "miemie_refine_status.json")
_refine_queue = _queue.Queue()
_refine_worker = None
_refine_lock = threading.Lock()
# ★ 修复: 停止信号 + 毒丸（worker 线程可干净退出，避免进程退出时线程残留）
_refine_stop = threading.Event()
_REFINE_POISON = object()


def _load_refine_status():
    """读取炼化队列状态；缺失/损坏返回空结构。"""
    try:
        with open(_REFINE_STATUS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"items": []}


def _save_refine_status(data):
    _ensure_data_dir()
    with open(_REFINE_STATUS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _update_refine_status(item_id, state, summary="", error="", persona=None):
    with _refine_lock:
        data = _load_refine_status()
        for it in data["items"]:
            if it.get("id") == item_id:
                it["state"] = state
                it["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
                if summary:
                    it["summary"] = summary
                if error:
                    it["error"] = error
                if persona is not None:
                    it["persona"] = persona
                break
        _save_refine_status(data)


class _PersonaRefineWorker(QThread):
    """后台炼化线程：顺序消费队列，逐项调 persona_feed 并持久化状态。"""

    item_done = pyqtSignal(dict)

    def stop(self):
        """请求线程停止：置停止标志并放入毒丸唤醒阻塞的 get()。"""
        _refine_stop.set()
        try:
            _refine_queue.put(_REFINE_POISON)
        except Exception:
            pass

    def run(self):
        while not _refine_stop.is_set():
            try:
                item = _refine_queue.get(timeout=0.5)
            except _queue.Empty:
                continue
            # 毒丸 → 退出
            if item is _REFINE_POISON:
                break
            item_id = item.get("id", "")
            _update_refine_status(item_id, "running")
            try:
                res = tool_persona_feed(
                    text=item.get("text", ""),
                    image_paths=item.get("image_paths", ""),
                    image_caption=item.get("image_caption", ""))
                if res.get("ok"):
                    _update_refine_status(item_id, "done",
                                          summary=res.get("summary", ""),
                                          persona=res.get("persona"))
                    self.item_done.emit({"id": item_id, "ok": True})
                else:
                    _update_refine_status(item_id, "error",
                                          error=res.get("error", ""))
                    self.item_done.emit({"id": item_id, "ok": False,
                                         "error": res.get("error", "")})
            except Exception as e:
                _update_refine_status(item_id, "error", error=str(e))
                self.item_done.emit({"id": item_id, "ok": False, "error": str(e)})
            finally:
                _refine_queue.task_done()


def tool_persona_enqueue(text="", image_paths="", image_caption=""):
    """异步喂料入队：后台线程逐项炼化，不阻塞 UI。

    参数与 tool_persona_feed 相同。返回任务 id 与当前队列长度。
    """
    ensure_data()
    if not str(text).strip() and not str(image_paths).strip() and not str(image_caption).strip():
        return {"ok": False, "error": "缺少素材：请提供文本、图片路径或图片说明"}
    global _refine_worker
    item = {
        "id": str(int(time.time() * 1000)),
        "text": str(text or ""),
        "image_paths": str(image_paths or ""),
        "image_caption": str(image_caption or ""),
        "state": "queued",
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with _refine_lock:
        data = _load_refine_status()
        data["items"].insert(0, item)
        _save_refine_status(data)
    _refine_queue.put(item)
    if _refine_worker is None or not _refine_worker.isRunning():
        # 重新启动前先复位停止标志（防止线程曾因 stop() 退出后无法再拉起）
        _refine_stop.clear()
        _refine_worker = _PersonaRefineWorker()
        _refine_worker.start()
    return {"ok": True, "id": item["id"], "state": "queued",
            "queue_len": _refine_queue.qsize() + 1}


def tool_persona_status(limit=10):
    """查询后台炼化队列状态（排队中/执行中/完成/失败）。"""
    ensure_data()
    data = _load_refine_status()
    items = data["items"][:limit]
    running = sum(1 for i in items if i.get("state") == "running")
    return {"ok": True, "queue_len": _refine_queue.qsize(),
            "running": running, "items": items}


def tool_persona_worker_stop(timeout_ms=3000):
    """停止后台炼化线程（应用退出/插件停用时调用），避免线程残留。

    安全：毒丸入队后线程会在处理完当前条目后退出；不会丢弃未处理条目
    （未处理条目保留在队列与 JSON 状态中，下次 enqueue 可继续）。
    """
    global _refine_worker
    w = _refine_worker
    if w is not None and w.isRunning():
        w.stop()
        w.wait(timeout_ms)
    return {"ok": True}


def tool_persona_queue_clear(keep_done=0):
    """清空炼化队列历史（默认全部清；keep_done 保留最近 N 条完成记录）。"""
    with _refine_lock:
        data = _load_refine_status()
        active = [i for i in data["items"] if i.get("state") in ("queued", "running")]
        done = [i for i in data["items"] if i.get("state") not in ("queued", "running")]
        data["items"] = active + done[:keep_done]
        _save_refine_status(data)
    return {"ok": True, "count": len(data["items"])}


def tool_sql_query(query):
    """真实 SQLite 查询（只读为主，允许常见 DML 但拒绝 DROP）。"""
    ensure_data()
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "SQL 为空"}
    if re.search(r"\b(drop|delete from|truncate)\b", q, re.I):
        return {"ok": False, "error": "拒绝危险 SQL（drop/delete/truncate）"}
    conn = sqlite3.connect(_DB_PATH)
    try:
        cur = conn.execute(q)
        if cur.description:
            cols = [d[0] for d in cur.description]
            rows = cur.fetchmany(20)
            return {"ok": True, "query": q, "columns": cols, "rows": rows,
                    "row_count": len(rows)}
        conn.commit()
        return {"ok": True, "query": q, "affected": cur.rowcount}
    except sqlite3.Error as e:
        return {"ok": False, "error": f"SQL 错误: {e}"}
    finally:
        conn.close()


def tool_plan(goal=""):
    """真实任务规划：结合项目文件规模 + 记忆生成步骤。"""
    ensure_data()
    goal = goal or "优化项目结构"
    # 统计项目规模
    py_count = sum(1 for fp in _walk(_LEMON_ROOT) if fp.endswith(".py"))
    mem = tool_memory_search("项目")["entries"][:2]
    steps = [
        {"n": 1, "action": "调研现状", "tools": ["glob", "grep"]},
        {"n": 2, "action": "梳理模块依赖", "tools": ["read_file"]},
        {"n": 3, "action": "设计改造方案", "tools": ["memory_search", "analyze_style"]},
        {"n": 4, "action": "实现代码", "tools": ["write_file", "edit_file"]},
        {"n": 5, "action": "测试验证", "tools": ["bash"]},
    ]
    return {"ok": True, "goal": goal, "py_files": py_count,
            "steps": steps, "memory_hints": mem}


# =====================================================================
# 本机 LLM（Ollama）— 意图路由 + 纯聊天
# =====================================================================

def _ollama_models(timeout=3):
    """返回本机 Ollama 可用模型名列表；服务不可用返回 []。"""
    if requests is None:
        return []
    try:
        resp = requests.get(f"{_OLLAMA_URL}/api/tags", timeout=timeout)
        if resp.status_code != 200:
            return []
        return [m.get("name", "") for m in resp.json().get("models", []) if m.get("name")]
    except Exception:
        return []


# 文本意图分类首选模型（排除 llava/vl 视觉模型）
_MODEL_PREFERENCE = [
    "qwen3.5:4b",
    "qwen3.5:9b",
]


def _pick_text_model(models):
    """从本机模型列表挑选文本模型（跳过视觉模型）。"""
    for pref in _MODEL_PREFERENCE:
        for m in models:
            base = m.split(":")[0]
            if m == pref or base == pref.split(":")[0]:
                return m
    for m in models:
        low = m.lower()
        if "llava" not in low and "vl" not in low:
            return m
    return models[0] if models else ""


def _ollama_chat(messages, model="", timeout=90):
    """调 Ollama /api/chat（非流式）。返回 (ok, content/err)。"""
    if requests is None:
        return False, "requests 库不可用"
    if not model:
        models = _ollama_models()
        if not models:
            return False, "Ollama 未运行（localhost:11434）或无可用模型"
        model = _pick_text_model(models)
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 512},
    }
    try:
        resp = requests.post(f"{_OLLAMA_URL}/api/chat", json=payload, timeout=timeout)
        if resp.status_code != 200:
            return False, f"Ollama HTTP {resp.status_code}"
        msg = resp.json().get("message", {})
        content = (msg.get("content", "") or "").strip()
        return (True, content) if content else (False, "Ollama 返回空回复")
    except requests.exceptions.ConnectionError:
        return False, "Ollama 连接失败（localhost:11434）"
    except requests.exceptions.Timeout:
        return False, "Ollama 响应超时"
    except Exception as e:
        return False, f"Ollama 异常: {e}"


def _ollama_chat_stream(messages, model="", timeout=300):
    """流式调 Ollama /api/chat（打字机 token 流）。

    返回 (ok, gen 或 err)。gen 迭代产出 (token增量, full累计文本)。
    """
    if requests is None:
        return False, "requests 库不可用"
    if not model:
        models = _ollama_models()
        if not models:
            return False, "Ollama 未运行（localhost:11434）或无可用模型"
        model = _pick_text_model(models)
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": {"temperature": 0.2, "num_predict": 512},
    }

    def _gen():
        full = ""
        try:
            with requests.post(f"{_OLLAMA_URL}/api/chat", json=payload,
                               stream=True, timeout=timeout) as resp:
                if resp.status_code != 200:
                    yield "", f"Ollama HTTP {resp.status_code}"
                    return
                for line in resp.iter_lines(decode_unicode=True):
                    if not line or not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except Exception:
                        continue
                    msg = data.get("message") or {}
                    tok = (msg.get("content") or "") if isinstance(msg, dict) else ""
                    if tok:
                        full += tok
                        yield tok, full
                    if data.get("done"):
                        break
        except requests.exceptions.ConnectionError:
            yield "", full or "Ollama 连接失败（localhost:11434）"
        except requests.exceptions.Timeout:
            yield "", full or "Ollama 响应超时"
        except Exception as e:
            yield "", full or f"Ollama 异常: {e}"

    return True, _gen()


# ---- 自主编排（agentic tool calling）----
_AGENTIC_MODEL_PREFERENCE = [
    "deepseek-r1-tool-calling:8b", "qwen3.5:9b",
    "qwen3.5:4b",
]
_AGENTIC_MAX_ROUNDS = 4   # 单次任务最多几轮工具调用


def _pick_agentic_model(models):
    """挑选适合工具调用的模型（优先 deepseek-r1-tool-calling）。"""
    for pref in _AGENTIC_MODEL_PREFERENCE:
        for m in models:
            base = m.split(":")[0]
            if m == pref or base == pref.split(":")[0]:
                return m
    return _pick_text_model(models)


def _build_tool_schemas():
    """把 TOOL_DEFS 转成 Ollama tools JSON schema（供模型自主选工具）。"""
    _PARAMS = {
        "glob":          {"pattern": ("string", "glob 模式，如 **/*.py", True),
                          "max_results": ("integer", "最大返回条数", False)},
        "grep":          {"pattern": ("string", "正则表达式", True),
                          "path_filter": ("string", "限定的目录/文件，可空", False),
                          "max_results": ("integer", "最大返回条数", False)},
        "read_file":     {"path": ("string", "文件路径（相对项目根）", True)},
        "write_file":    {"path": ("string", "文件路径", True),
                          "content": ("string", "写入内容", False)},
        "edit_file":     {"path": ("string", "文件路径", True),
                          "old": ("string", "要替换的原文", True),
                          "new": ("string", "替换后的新文本", False),
                          "count": ("integer", "替换次数", False)},
        "bash":          {"command": ("string", "shell 命令", True)},
        "web_fetch":     {"url": ("string", "http/https 网址", True)},
        "analyze_style": {"directory": ("string", "分析目录，空为项目根", False)},
        "persona_extract": {"text": ("string", "聊天记录/朋友圈/自述文本，可空", False),
                            "code_style_json": ("string", "analyze_style 输出 JSON，可空", False),
                            "model": ("string", "指定模型名，空为自动", False)},
        "vision_analyze": {"path": ("string", "图片路径", True),
                           "prompt": ("string", "自定义提示，可空", False)},
        "persona_feed": {"text": ("string", "聊天/朋友圈文本，可空", False),
                         "image_paths": ("string", "逗号分隔图片路径，可空", False),
                         "image_caption": ("string", "图片说明，可空", False)},
        "persona_calibrate": {"feedback": ("string", "用户校准反馈", True)},
        "persona_enqueue": {"text": ("string", "聊天/朋友圈文本，可空", False),
                            "image_paths": ("string", "逗号分隔图片路径，可空", False),
                            "image_caption": ("string", "图片说明，可空", False)},
        "persona_status": {"limit": ("integer", "返回条数，默认10", False)},
        "memory_index": {"query": ("string", "关键词，可空", False),
                         "date": ("string", "日期 YYYY-MM-DD，可空", False)},
        "memory_search": {"query": ("string", "记忆检索关键词", False),
                          "max_results": ("integer", "最大返回条数", False)},
        "sql_query":     {"query": ("string", "SQL（只读为主）", True)},
        "plan":          {"goal": ("string", "规划目标", False)},
    }
    tools = []
    for name, defn in TOOL_DEFS.items():
        props = {}
        required = []
        for pname, (ptype, pdesc, is_req) in _PARAMS.get(name, {}).items():
            props[pname] = {"type": ptype, "description": pdesc}
            if is_req:
                required.append(pname)
        tools.append({
            "type": "function",
            "function": {
                "name": name,
                "description": defn["desc"],
                "parameters": {"type": "object", "properties": props,
                               "required": required},
            },
        })
    return tools


def _ollama_chat_agentic(messages, tools=None, timeout=180):
    """调 Ollama /api/chat 支持 tools 的 agentic 请求（非流式）。

    返回 (ok, msg_dict/err)。msg_dict 形如：
        {"role": "assistant", "content": "...",
         "tool_calls": [{"function": {"name": "...", "arguments": "{...}"}}]}
    """
    if requests is None:
        return False, {"error": "requests 库不可用"}
    models = _ollama_models()
    if not models:
        return False, {"error": "Ollama 未运行（localhost:11434）或无可用模型"}
    model = _pick_agentic_model(models)
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 1024},
    }
    if tools:
        payload["tools"] = tools
    try:
        resp = requests.post(f"{_OLLAMA_URL}/api/chat", json=payload, timeout=timeout)
        if resp.status_code != 200:
            return False, {"error": f"Ollama HTTP {resp.status_code}: {resp.text[:200]}"}
        msg = resp.json().get("message", {}) or {}
        if not msg:
            return False, {"error": "Ollama 返回空消息"}
        return True, msg
    except requests.exceptions.ConnectionError:
        return False, {"error": "Ollama 连接失败（localhost:11434）"}
    except requests.exceptions.Timeout:
        return False, {"error": "Ollama 响应超时"}
    except Exception as e:
        return False, {"error": f"Ollama 异常: {e}"}


_LLM_INTENTS = ("analyze", "search", "memory", "plan", "db", "direct", "chat")

# 咩咩 LLM 系统提示基础段（意图路由）
_LLM_SYSTEM_PROMPT = (
    "你是柠檬码项目里的 AI 助手「咩咩」。根据用户指令判断意图，意图只允许七种：\n"
    "- analyze：分析项目代码风格/结构/画像\n"
    "- search：搜索代码（TODO、错误、类、函数等）\n"
    "- memory：查询记忆/偏好/历史\n"
    "- plan：制定任务计划/规划步骤\n"
    "- db：查询数据库/任务表/记录\n"
    "- direct：跨会话指挥——把任务发给其他会话窗口执行并读回结果（会话指挥）\n"
    "- chat：打招呼、闲聊、问咩咩能做什么、无法归类的对话\n"
    "示例：\n"
    "用户：帮我分析项目风格 → analyze\n"
    "用户：搜索代码里的 TODO → search\n"
    "用户：查一下数据库任务 → db\n"
    "用户：把代码审查发给会话2 → direct\n"
    "用户：你好呀 → chat\n"
    "输出格式（严格遵守）：第一行只输出意图标签，第二行一句话理解，第三行开始简短回复。"
)


def _build_system_prompt():
    """构建咩咩 LLM 系统提示：基础规则 + 动态注入用户人格档案（分身层）。

    ★ v4.3.9 P3-1：人格档案存在时，追加"用户人格画像 · 按此品味行事"段落，
    让咩咩回复与行动贴合用户人格（分身注入），而非单纯模仿。
    """
    base = _LLM_SYSTEM_PROMPT
    try:
        p = _load_persona()
        if not p:
            return base
        big5 = p.get("big5") or {}
        seg = []
        if p.get("portrait"):
            seg.append(f"- 整体画像：{p['portrait']}")
        for k, label in _BIG5_LABELS.items():
            v = big5.get(k) or {}
            if v.get("score") is not None and float(v.get("confidence", 0) or 0) >= 0.4:
                seg.append(f"- {label}：{v['score']}/100")
        if p.get("communication"):
            seg.append(f"- 沟通风格：{p['communication']}")
        if p.get("aesthetic"):
            seg.append(f"- 审美偏好：{p['aesthetic']}")
        if seg:
            return base + ("\n\n【用户人格画像 · 咩咩是用户的分身，请按此品味行事】\n" + "\n".join(seg))
    except Exception:
        pass
    return base

# 自主编排（agentic）系统提示 — 让模型自己决定调什么工具、什么顺序
_AGENTIC_SYSTEM_PROMPT = (
    "你是柠檬码项目里的 AI 助手「咩咩」。你可以自主调用工具完成任务。\n"
    "工具：glob(按模式找文件) / grep(正则搜索代码) / read_file / write_file / edit_file /\n"
    "      bash(执行命令) / web_fetch(抓网页) / analyze_style(代码风格画像) /\n"
    "      persona_extract(抽取用户人格画像) / vision_analyze(视觉解读图片) /\n"
    "      persona_feed(多源喂料炼化人格) / persona_calibrate(分身校准) /\n"
    "      persona_enqueue(异步喂料入队) / persona_status(查炼化队列) /\n"
    "      memory_index(查档案索引) / memory_search(查咩咩记忆) /\n"
    "      sql_query(查数据库) / plan(任务规划) /\n"
    "      session_list(列出所有会话窗口) / session_read(读取指定会话输出) /\n"
    "      session_send(向指定会话发送命令) / session_status(查会话忙碌) /\n"
    "      session_watch(等待会话空闲并读回结果)\n"
    "跨会话指挥（direct）：当用户要求把任务分发给其他会话窗口时——\n"
    "  先 session_list 拿到会话 id，再 session_send 把命令发给目标会话，\n"
    "  最后 session_watch 等待执行完成并读回结果，汇总给用户。\n"
    "规则：\n"
    "1. 根据用户指令自主决定调用哪些工具、按什么顺序（一次可并行调多个）。\n"
    "2. 拿到工具结果后继续，直到任务完成；中途可修改计划。\n"
    "3. 任务完成后，用 1~3 句中文总结结果（做了什么、关键发现）。\n"
    "4. 纯闲聊无需调工具时，直接回复用户。\n"
    "不要捏造工具结果，一切以真实返回为准。"
)


def _chunk_text(text, size=6):
    """把长文本切成小块（供打字机逐块发射）。"""
    text = text or ""
    return [text[i:i + size] for i in range(0, len(text), size)] if text else [""]


def _parse_llm_output(full, user_text=""):
    """解析模型输出 → {"plan", "reply", "reason"}。

    预期格式：第一行意图标签，第二行理解，第三行起为回复。
    意图解析失败时用 user_text（或全文）关键词路由降级。
    """
    lines = [l.strip() for l in full.splitlines() if l.strip()]
    intent = ""
    reply = ""
    reason = ""
    if lines:
        first = lines[0].lower().strip(" \t:：\"'。，,、")
        for it in _LLM_INTENTS:
            if it in first:
                intent = it
                break
        if intent not in _LLM_INTENTS:
            _cn = {
                "分析": "analyze", "搜索": "search", "查找": "search", "搜": "search",
                "记忆": "memory", "规划": "plan", "计划": "plan",
                "数据库": "db", "查询": "db", "指挥": "direct", "调度": "direct",
                "派发": "direct", "发给会话": "direct",
                "聊天": "chat", "闲聊": "chat", "你好": "chat",
                "打招呼": "chat", "能做什么": "chat",
            }
            for k, v in _cn.items():
                if k in first:
                    intent = v
                    break
    if len(lines) >= 2:
        reason = lines[1]
    if len(lines) >= 3:
        reply = "\n".join(lines[2:])[:600]
    if intent not in _LLM_INTENTS:
        intent = _keyword_route(user_text or full)
    if not reply:
        reply = "好的，咩咩明白了。"
    return {"plan": intent, "reply": reply, "reason": reason}


def llm_route(user_text):
    """用本机 LLM 判断用户意图。

    返回 dict：
        {"plan": "analyze"|"search"|"memory"|"plan"|"db"|"chat"|None,
         "reply": str  (纯聊天时的回复，或空),
         "reason": str (模型给出的原因),
         "llm": bool  (是否走了 LLM)}
    Ollama 不可用 / 解析失败时自动降级关键词路由（llm=False）。
    """
    text = (user_text or "").strip()
    if not text:
        return {"plan": "chat", "reply": "请告诉咩咩你想做什么～", "reason": "", "llm": False}

    ok, raw = _ollama_chat([
        {"role": "system", "content": _build_system_prompt()},
        {"role": "user", "content": text},
    ])
    if not ok:
        # 降级：关键词路由
        return {"plan": _keyword_route(text), "reply": "", "reason": raw, "llm": False}

    parsed = _parse_llm_output(raw, text)
    return {"plan": parsed["plan"], "reply": parsed["reply"],
            "reason": parsed["reason"], "llm": True}


def _keyword_route(lower):
    """关键词路由（LLM 降级方案）。"""
    if "风格" in lower or "画像" in lower or "分析" in lower:
        return "analyze"
    if "搜" in lower or "查找" in lower or "todo" in lower or "fixme" in lower or "错误" in lower:
        return "search"
    if "记忆" in lower or "偏好" in lower:
        return "memory"
    if "规划" in lower or "计划" in lower:
        return "plan"
    if "数据" in lower or "sql" in lower or "任务表" in lower:
        return "db"
    if "指挥" in lower or "调度" in lower or "派发" in lower or "发给会话" in lower or "让会话" in lower:
        return "direct"
    return "chat"


# =====================================================================
# ★ v4.7.3: 跨会话指挥（总指挥/工人）—— 由 MIMOWindow 注册实现
# 咩咩作为「总指挥」：读各会话窗口信息 → 规划任务 → 派发命令 → 监控调度。
# =====================================================================

_session_ops = {}  # {"list": fn, "read": fn, "send": fn, "busy": fn}


def register_session_ops(ops):
    """注册跨会话操作（由 MIMOWindow 注入 SessionWorkspace 的能力）。

    ops: {"list": fn()->dict, "read": fn(sid, max_chars)->dict,
          "send": fn(sid, text)->dict, "busy": fn(sid)->bool}
    """
    _session_ops.clear()
    _session_ops.update(ops or {})


def _session_op(name):
    return _session_ops.get(name)


def tool_session_list():
    """列出所有会话窗口（id/名称/忙碌状态）。"""
    fn = _session_op("list")
    if not fn:
        return {"ok": False, "error": "会话指挥未就绪（多会话 Tab 未启用）"}
    try:
        return fn()
    except Exception as e:
        return {"ok": False, "error": str(e)}


def tool_session_read(session_id=None, max_chars=2000):
    """读取指定会话最近输出（默认当前会话）。"""
    fn = _session_op("read")
    if not fn:
        return {"ok": False, "error": "会话指挥未就绪"}
    try:
        return fn(session_id, max_chars)
    except Exception as e:
        return {"ok": False, "error": str(e)}


def tool_session_send(session_id="", text=""):
    """向指定会话窗口注入一条命令，触发该会话执行。"""
    if not session_id:
        return {"ok": False, "error": "需要 session_id（先用 session_list 获取）"}
    if not text:
        return {"ok": False, "error": "需要 text（要发送的命令）"}
    fn = _session_op("send")
    if not fn:
        return {"ok": False, "error": "会话指挥未就绪"}
    try:
        return fn(session_id, text)
    except Exception as e:
        return {"ok": False, "error": str(e)}


def tool_session_status(session_id=None):
    """查询会话忙碌状态。"""
    fn = _session_op("busy")
    if not fn:
        return {"ok": False, "error": "会话指挥未就绪"}
    try:
        return {"ok": True, "busy": bool(fn(session_id))}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def tool_session_watch(session_id=None, timeout=60, interval=2, max_chars=2000):
    """轮询等待会话空闲，然后读回结果（用于调度后收集产出）。"""
    busy = _session_op("busy")
    read = _session_op("read")
    if not busy or not read:
        return {"ok": False, "error": "会话指挥未就绪"}
    import time
    try:
        timeout = float(timeout or 60)
        interval = float(interval or 2)
    except Exception:
        timeout, interval = 60.0, 2.0
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if not busy(session_id):
                return read(session_id, max_chars)
        except Exception:
            return {"ok": False, "error": "等待会话时出错"}
        time.sleep(interval)
    return {"ok": True, "timeout": True,
            "msg": "等待超时（会话仍在执行，可稍后 session_read 再读）"}


# =====================================================================
# 工具注册表
# =====================================================================

# icon 字段 = theme.py SVG_ICONS 的 key（全站统一极简线条风格，禁用 emoji）
TOOL_DEFS = {
    "glob":          {"icon": "folder", "name": "glob", "desc": "按模式匹配项目内文件", "fn": tool_glob},
    "grep":          {"icon": "search", "name": "grep", "desc": "正则搜索代码", "fn": tool_grep},
    "read_file":     {"icon": "file_default", "name": "read_file", "desc": "读取文件内容", "fn": tool_read_file},
    "write_file":    {"icon": "pencil", "name": "write_file", "desc": "创建/覆盖文件", "fn": tool_write_file},
    "edit_file":     {"icon": "tool", "name": "edit_file", "desc": "精确字符串替换", "fn": tool_edit_file},
    "bash":          {"icon": "terminal", "name": "bash", "desc": "执行 shell 命令", "fn": tool_bash},
    "web_fetch":     {"icon": "globe", "name": "web_fetch", "desc": "抓取网页", "fn": tool_web_fetch},
    "analyze_style": {"icon": "palette", "name": "analyze_style", "desc": "扫描代码风格画像", "fn": tool_analyze_style},
    "persona_extract": {"icon": "user", "name": "persona_extract", "desc": "抽取/更新用户人格画像（Big Five）", "fn": tool_persona_extract},
    "vision_analyze": {"icon": "image", "name": "vision_analyze", "desc": "视觉解读图片（内容+OCR）", "fn": tool_vision_analyze},
    "persona_feed": {"icon": "star", "name": "persona_feed", "desc": "多源喂料（文本/图片）炼化人格", "fn": tool_persona_feed},
    "persona_calibrate": {"icon": "user", "name": "persona_calibrate", "desc": "分身校准（用户反馈修正画像）", "fn": tool_persona_calibrate},
    "persona_enqueue": {"icon": "star", "name": "persona_enqueue", "desc": "异步喂料入队（后台炼化不阻塞）", "fn": tool_persona_enqueue},
    "persona_status": {"icon": "info", "name": "persona_status", "desc": "查询后台炼化队列状态", "fn": tool_persona_status},
    "memory_index": {"icon": "folder", "name": "memory_index", "desc": "查 Layer2 档案索引（按日期/关键词）", "fn": tool_memory_index},
    "memory_search": {"icon": "star", "name": "memory_search", "desc": "查咩咩记忆库", "fn": tool_memory_search},
    "sql_query":     {"icon": "database", "name": "sql_query", "desc": "查询数据库", "fn": tool_sql_query},
    "plan":          {"icon": "clipboard", "name": "plan", "desc": "任务规划/拆解", "fn": tool_plan},
    # ★ v4.7.3: 跨会话指挥工具（总指挥 → 工人会话）
    "session_list":  {"icon": "folder", "name": "session_list", "desc": "列出所有会话窗口", "fn": tool_session_list},
    "session_read":  {"icon": "star", "name": "session_read", "desc": "读取指定会话最近输出", "fn": tool_session_read},
    "session_send":  {"icon": "pencil", "name": "session_send", "desc": "向指定会话发送命令", "fn": tool_session_send},
    "session_status": {"icon": "clipboard", "name": "session_status", "desc": "查询会话忙碌状态", "fn": tool_session_status},
    "session_watch": {"icon": "globe", "name": "session_watch", "desc": "等待会话空闲并读回结果", "fn": tool_session_watch},
}

# ★ v4.7.0 P2: 高风险工具（执行前需用户确认，Human-in-the-Loop）
# 对应 HITL 风险分级：bash/写文件/编辑/网络抓取 → 确认卡；其余只读/低风险自动。
_HIGH_RISK_TOOLS = {"bash", "write_file", "edit_file", "web_fetch"}


# =====================================================================
# 计划定义（真实工具链）
# =====================================================================

MIEMIE_PLANS = {
    "analyze": [
        {"tool": "glob", "args": {"pattern": "**/*.py"}, "desc": "枚举 Python 文件"},
        {"tool": "analyze_style", "args": {"directory": ""}, "desc": "扫描代码风格画像"},
        {"tool": "memory_search", "args": {"query": "代码风格"}, "desc": "对照咩咩记忆中的风格偏好"},
    ],
    "search": [
        {"tool": "grep", "args": {"pattern": "TODO|FIXME"}, "desc": "搜索 TODO/FIXME 标记"},
        {"tool": "grep", "args": {"pattern": "class \\w+"}, "desc": "搜索类定义"},
    ],
    "memory": [
        {"tool": "memory_search", "args": {"query": ""}, "desc": "列出全部记忆"},
        {"tool": "memory_search", "args": {"query": "用户偏好"}, "desc": "检索用户偏好"},
    ],
    "plan": [
        {"tool": "plan", "args": {"goal": ""}, "desc": "分析项目规模并拆解任务"},
        {"tool": "memory_search", "args": {"query": "项目"}, "desc": "检索项目记忆"},
    ],
    "db": [
        {"tool": "sql_query", "args": {"query": "SELECT id, name, status FROM tasks ORDER BY id DESC LIMIT 10"}, "desc": "查询任务表"},
        {"tool": "sql_query", "args": {"query": "SELECT id, title, ts FROM sessions ORDER BY id DESC LIMIT 5"}, "desc": "查询会话表"},
        {"tool": "memory_search", "args": {"query": "数据库"}, "desc": "检索数据库相关记忆"},
    ],
    # ★ v4.7.3: 跨会话指挥 —— 优先走模型自主编排（agentic），此计划仅作降级兜底
    "direct": [
        {"tool": "session_list", "args": {}, "desc": "列出所有会话窗口"},
    ],
}


# =====================================================================
# 执行 Worker
# =====================================================================

class MiemieEngineWorker(QThread):
    """在工作线程中顺序执行计划，逐步发射信号供 UI 流式渲染。

    信号：
        step_event(dict)   : 工具调用块开始（tool/args/desc/state='running'）
        result_event(dict) : 工具结果（tool/result/state='done'|'error'）
        summary_event(dict): 摘要（text/ok）
        done_event(dict)   : 全部完成（ok/task）
    """

    step_event = pyqtSignal(dict)
    result_event = pyqtSignal(dict)
    summary_event = pyqtSignal(dict)
    done_event = pyqtSignal(dict)
    token_event = pyqtSignal(str)   # LLM 流式 token（打字机）
    # ★ v4.7.0 P2: HITL 确认请求（worker 线程发，UI 插确认卡）
    confirm_requested = pyqtSignal(dict)

    def __init__(self, plan_name, override_args=None, user_text=None, parent=None):
        super().__init__(parent)
        self._plan_name = plan_name
        self._override_args = override_args or {}
        self._user_text = user_text
        self._cancelled = False
        self._step_records = []      # 步骤执行记录（供 LLM 总结）
        self._last_all_ok = True
        # ★ v4.7.0 P2: 权限分层（auto/confirm/debug）与 HITL 确认
        self._confirm_mode = "auto"
        self._confirm_evt = threading.Event()
        self._confirm_ok = False
        self._always_allow = set()
        self._always_lock = threading.Lock()

    def cancel(self):
        self._cancelled = True
        # 若正阻塞等待确认，立即放行（拒绝）避免卡死
        self._confirm_ok = False
        self._confirm_evt.set()

    def set_confirm_mode(self, mode):
        """设置权限分层：auto（低风险直接跑，高风险确认）/ confirm（全部确认）/ debug（逐步确认）。"""
        if mode in ("auto", "confirm", "debug"):
            self._confirm_mode = mode

    def set_confirm(self, ok, always=False):
        """UI 主线程回传确认结果；always=True 时本会话内该工具不再询问。"""
        if always and ok:
            with self._always_lock:
                self._always_allow.add(self._pending_tool)
        self._confirm_ok = bool(ok)
        self._confirm_evt.set()

    def _maybe_confirm(self, tool, args):
        """按权限模式决定是否阻塞等待用户确认；True=放行执行，False=拒绝。"""
        risk_high = tool in _HIGH_RISK_TOOLS
        mode = self._confirm_mode
        if mode == "auto":
            need = risk_high
        elif mode == "confirm":
            need = True
        else:  # debug
            need = True
        if not need:
            return True
        with self._always_lock:
            if tool in self._always_allow:
                return True
        self._pending_tool = tool
        self._confirm_evt.clear()
        self._confirm_ok = False
        self.confirm_requested.emit({
            "tool": tool,
            "args": args,
            "desc": (TOOL_DEFS.get(tool, {}).get("desc") or tool),
            "risk": "high" if risk_high else "low",
        })
        # 阻塞等待 UI 确认（cancel 会放行并拒绝）
        self._confirm_evt.wait()
        return self._confirm_ok

    def run(self):
        if self._plan_name == "llm":
            self._run_llm_route()
            return
        plan = MIEMIE_PLANS.get(self._plan_name, MIEMIE_PLANS["analyze"])
        self._execute_plan(plan)
        self._finish(self._plan_name)

    # ---------------- LLM 意图路由模式（全流式打字机） ----------------

    def _run_llm_route(self):
        """LLM 全流式：边生成边逐 token 推送（打字机），
        生成完成后解析意图：可归类→执行对应计划；纯聊天→流式回复即结果。"""
        text = self._user_text or ""
        if not text.strip():
            self.step_event.emit({"tool": "llm", "args": {}, "desc": "咩咩思考中…", "state": "running"})
            self.result_event.emit({"tool": "llm", "result": {"ok": True, "reply": "请告诉咩咩你想做什么～"},
                                    "state": "done"})
            self._finish("chat")
            return

        self.step_event.emit({"tool": "llm", "args": {}, "desc": "咩咩思考中…", "state": "running"})

        ok, gen = _ollama_chat_stream([
            {"role": "system", "content": _build_system_prompt()},
            {"role": "user", "content": text},
        ])
        if not ok:
            # Ollama 不可用：降级关键词路由
            plan = _keyword_route(text)
            self.result_event.emit({"tool": "llm", "result": {
                "ok": False, "error": gen,
                "intent": plan if plan in MIEMIE_PLANS else "",
            }, "state": "error"})
            if plan in MIEMIE_PLANS:
                self._execute_plan(MIEMIE_PLANS[plan])
                self._finish(plan)
            else:
                self._finish("chat")
            return

        full = ""
        seen_newline = False  # 跳过第一行意图标签，从第二行开始打字
        for tok, full in gen:
            if self._cancelled:
                break
            if not tok:
                continue
            if not seen_newline:
                nl = full.find("\n")
                if nl < 0:
                    continue  # 第一行（意图标签）还没结束
                tail = full[nl + 1:]
                seen_newline = True
                if tail:
                    self.token_event.emit(tail)
            else:
                self.token_event.emit(tok)

        parsed = _parse_llm_output(full, text)
        plan = parsed["plan"]
        self.result_event.emit({
            "tool": "llm",
            "result": {"ok": True, "intent": plan, "reply": parsed["reply"],
                       "reason": parsed["reason"]},
            "state": "done",
        })
        if plan in MIEMIE_PLANS:
            # ★ v4.3.8: 优先模型自主编排工具链（deepseek-r1-tool-calling:8b），
            #            Ollama 不支持/不可用时降级固定计划。
            used = self._run_agentic_loop(text)
            if not used:
                self._execute_plan(MIEMIE_PLANS[plan])
            self._finish(plan)
        else:
            self._finish("chat")

    # ---------------- 计划执行核心 ----------------

    def _execute_plan(self, plan):
        all_ok = True
        for step in plan:
            if self._cancelled:
                break
            tool = step["tool"]
            args = dict(step.get("args", {}))
            # 允许对首个参数做覆盖（自然语言指令）
            if self._override_args and tool in self._override_args:
                args.update(self._override_args[tool])
            if tool not in TOOL_DEFS:
                self.result_event.emit({"tool": tool, "result": {"ok": False, "error": "未知工具"}, "state": "error"})
                all_ok = False
                continue
            desc = step["desc"]
            if not desc.startswith(tool + ":") and not desc.startswith(tool + " ") and desc != tool:
                desc = f"{tool}: {desc}"
            self.step_event.emit({"tool": tool, "args": args, "desc": desc, "state": "running"})
            res, state = self._exec_tool(tool, args)
            if state == "error":
                all_ok = False
            self.result_event.emit({"tool": tool, "result": res, "state": state})
            self._record_step(tool, args, res, state)
            time.sleep(0.3)  # 流式节奏
        self._last_all_ok = all_ok

    def _exec_tool(self, tool, args):
        """执行单个工具（含参数异常重试），返回 (res, state)。"""
        defn = TOOL_DEFS.get(tool)
        if defn is None:
            return {"ok": False, "error": "未知工具"}, "error"
        # ★ v4.7.0 P2: HITL —— 高风险工具/确认/调试模式需用户确认
        if self._confirm_mode != "auto" or tool in _HIGH_RISK_TOOLS:
            if not self._maybe_confirm(tool, args):
                return {"ok": False, "error": f"用户拒绝执行 {tool}"}, "error"
        try:
            res = defn["fn"](**args)
        except TypeError as te:
            # 参数不匹配时重试（缺省参数）
            try:
                res = defn["fn"](*list(args.values())[:1]) if args else defn["fn"]()
            except Exception:
                res = {"ok": False, "error": f"参数错误: {te}"}
        except Exception as e:
            res = {"ok": False, "error": f"执行异常: {e}"}
        state = "error" if (not res.get("ok")) else "done"
        return res, state

    def _record_step(self, tool, args, res, state):
        """记录步骤摘要（供任务后 LLM 总结）。"""
        try:
            self._step_records.append(self._brief_step(tool, args, res, state))
        except Exception:
            pass

    # ---------------- 自主编排（模型自己决定工具链） ----------------

    def _run_agentic_loop(self, user_text):
        """让模型自主决定调什么工具、什么顺序，直到给出最终回复。

        返回 True = 自主编排完成；False = Ollama 不可用/不支持 tools
        （调用方应降级为固定计划执行）。
        """
        tools = _build_tool_schemas()
        messages = [
            {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ]
        self.step_event.emit({"tool": "llm", "args": {}, "desc": "咩咩自主规划工具链…", "state": "running"})
        last_reply = ""
        reached_max = False
        for rnd in range(_AGENTIC_MAX_ROUNDS):
            if self._cancelled:
                break
            ok, msg = _ollama_chat_agentic(messages, tools=tools)
            if not ok:
                err = (msg.get("error") if isinstance(msg, dict) else None) or "自主编排不可用"
                self.result_event.emit({"tool": "llm", "result": {"ok": False, "error": err}, "state": "error"})
                return False
            content = (msg.get("content") or "").strip()
            calls = msg.get("tool_calls") or []
            messages.append({"role": "assistant", "content": content, "tool_calls": calls})
            if not calls:
                last_reply = content
                break
            # 执行本轮所有工具调用
            for tc in calls:
                if self._cancelled:
                    break
                fn = tc.get("function") if isinstance(tc, dict) and tc.get("function") else {}
                name = fn.get("name", "")
                try:
                    raw_args = fn.get("arguments") or {}
                    args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                except Exception:
                    args = {}
                if not isinstance(args, dict):
                    args = {}
                desc = TOOL_DEFS.get(name, {}).get("desc") or name
                if desc != name and not desc.startswith(name + " ") and not desc.startswith(name + ":"):
                    desc = f"{name}: {desc}"
                self.step_event.emit({"tool": name, "args": args,
                                      "desc": desc,
                                      "state": "running"})
                res, state = self._exec_tool(name, args)
                self.result_event.emit({"tool": name, "result": res, "state": state})
                self._record_step(name, args, res, state)
                res_txt = json.dumps(res, ensure_ascii=False, default=str)[:2000]
                messages.append({"role": "tool", "content": res_txt, "tool_name": name})
            time.sleep(0.2)
        else:
            reached_max = True

        # 最终回复（打字机流式发射）
        if not last_reply:
            last_reply = "任务已执行完成。" if not reached_max else "任务已执行完成（自主编排达到最大轮次，已截断）。"
        self.result_event.emit({"tool": "llm", "result": {"ok": True, "intent": "agentic", "reply": last_reply}, "state": "done"})
        for chunk in _chunk_text(last_reply, 6):
            if self._cancelled:
                break
            self.token_event.emit(chunk)
            time.sleep(0.02)
        return True

    @staticmethod
    def _brief_step(tool, args, res, state):
        """把一次工具执行压缩成一行摘要文本，供 LLM 总结。"""
        arg_bits = []
        for k, v in (args or {}).items():
            s = str(v)
            arg_bits.append(f"{k}={s[:60]}" + ("…" if len(s) > 60 else ""))
        arg_txt = " ".join(arg_bits) if arg_bits else ""
        res_txt = ""
        if isinstance(res, dict):
            if res.get("error"):
                res_txt = f"错误: {str(res['error'])[:80]}"
            elif res.get("reply"):
                res_txt = str(res["reply"])[:80]
            elif res.get("summary"):
                res_txt = str(res["summary"])[:80]
            elif res.get("ok"):
                res_txt = "成功"
        return f"[{tool}] {arg_txt} → {res_txt if res_txt else state}"

    def _finish(self, plan_name):
        ok = getattr(self, "_last_all_ok", True)
        label = _PLAN_LABELS.get(plan_name, "完成任务")
        text = ("✅ 任务完成 · 咩咩已" + label) if ok else "⚠ 任务部分失败，请检查上面的错误步骤"
        # ★ v4.3.8: 任务后 LLM 自动总结（基于真实执行记录），Ollama 不可用则降级模板文案
        if ok and self._step_records:
            llm_text = self._llm_summarize(plan_name, label)
            if llm_text:
                text = llm_text
        # ★ v4.3.8: 记忆进化——把本次任务/对话沉淀进记忆库（自我更新）
        try:
            user_txt = (self._user_text or "").strip()
            is_chat = (plan_name == "chat") or (plan_name == "llm" and not self._step_records)
            if user_txt:
                memory_evolve(user_txt, text, kind="chat" if is_chat else "task")
        except Exception:
            pass
        self.summary_event.emit({"text": text, "ok": ok})
        self.done_event.emit({"ok": ok, "task": plan_name})

    def _llm_summarize(self, plan_name, label):
        """用本机 Ollama 基于步骤记录生成一句话任务总结（非流式，超时保护）。"""
        steps_txt = "\n".join(self._step_records) or "（无步骤）"
        user_txt = (self._user_text or "").strip()
        prompt = (
            f"你是项目里的 AI 助手「咩咩」。用户指令：{user_txt or label}\n"
            f"刚执行了「{label}」计划，步骤记录如下：\n{steps_txt}\n\n"
            "请用 1~2 句中文总结任务结果：做了什么、关键发现或产出是什么。"
            "直接输出总结内容，不要任何前缀标签或 emoji。"
        )
        try:
            ok, content = _ollama_chat(
                [{"role": "system", "content": _build_system_prompt()},
                 {"role": "user", "content": prompt}],
                timeout=60,
            )
            if not ok or not content:
                return ""
            # 去掉可能残留的意图标签行
            lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
            for i, ln in enumerate(lines):
                if ln in _LLM_INTENTS or ln.startswith(tuple(_LLM_INTENTS + ("intent",))):
                    continue
                lines = lines[i:]
                break
            return "\n".join(lines)[:300].strip()
        except Exception:
            return ""


_PLAN_LABELS = {
    "analyze": "分析项目风格",
    "search": "搜索代码",
    "memory": "查询记忆库",
    "plan": "规划任务",
    "db": "查询数据库",
}


# 启动时确保数据就绪（不阻塞，幂等）
ensure_data()
