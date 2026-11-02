# -*- coding: utf-8 -*-
"""
382B-3: 用户语义记忆层
======================
事实/偏好抽取（正则+关键词，不依赖LLM），JSONL 落盘，
上限 200 条 + 90 天时间衰减降权 = 智能遗忘。

接口：
    record_fact(text, source)        # 从对话文本中抽取事实/偏好
    recall_user_profile(top_k=5)     # 返回 top-k 用户画像（按权重）
    inject_into_prompt(prompt, max_chars=300)  # 注入到 system prompt

铁律：全部函数 try/except 自包——任何异常不得影响主流程。
"""

import json
import os
import re
import time
import threading
from typing import List, Dict, Optional

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MEMORY_FILE = os.path.join(_PROJECT_ROOT, "data", "user_memory.jsonl")
_MAX_ENTRIES = 200
_DECAY_DAYS = 90

_lock = threading.Lock()


_PREFERENCE_PATTERNS = [
    (re.compile(r"(?:我喜欢?|偏好|倾向|prefer|I like|I prefer)\s*(.{2,30})", re.I), "preference"),
    (re.compile(r"(?:我不喜欢?|讨厌|avoid|I hate|I dislike)\s*(.{2,30})", re.I), "aversion"),
    (re.compile(r"(?:我的名字是?|叫?我|I am|my name is)\s*(.{2,20})", re.I), "identity"),
    (re.compile(r"(?:我在?|工作在?|位于|I work at|I live in)\s*(.{2,30})", re.I), "location"),
    (re.compile(r"(?:用的是?|用的是|using|with)\s*(\S{2,20})", re.I), "tool_preference"),
    (re.compile(r"(?:项目(?:在|路径|根)|project (?:root|path|dir))\s*[是为：:]\s*(.{2,60})", re.I), "project_context"),
]

_FACT_KEYWORDS = [
    "名叫", "名字是", "我的", "偏好", "喜欢", "讨厌", "不用",
    "习惯", "风格", "配色", "主题", "语言", "框架", "工具",
    "prefer", "like", "dislike", "always", "never", "usually",
]


def _tokenize_bigram(text: str) -> set:
    if not text:
        return set()
    tokens = set()
    buf = ""
    for ch in text.lower():
        if ch.isalnum():
            buf += ch
        else:
            if len(buf) >= 2:
                tokens.add(buf)
            buf = ""
    if len(buf) >= 2:
        tokens.add(buf)
    cjk = [ch for ch in text if '\u4e00' <= ch <= '\u9fff']
    for i in range(len(cjk) - 1):
        tokens.add(cjk[i] + cjk[i + 1])
    return tokens


def _similarity(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _decay_weight(ts_str: str) -> float:
    try:
        entry_time = time.mktime(time.strptime(ts_str, "%Y-%m-%d %H:%M:%S"))
    except Exception:
        return 0.5
    age_days = (time.time() - entry_time) / 86400
    if age_days <= 0:
        return 1.0
    if age_days >= _DECAY_DAYS:
        return 0.1
    return 1.0 - 0.9 * (age_days / _DECAY_DAYS)


def _load_all() -> List[Dict]:
    if not os.path.exists(_MEMORY_FILE):
        return []
    entries = []
    try:
        with open(_MEMORY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        return []
    return entries


def _save_all(entries: List[Dict]) -> bool:
    try:
        os.makedirs(os.path.dirname(_MEMORY_FILE), exist_ok=True)
        with _lock:
            with open(_MEMORY_FILE, "w", encoding="utf-8") as f:
                for e in entries:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def record_fact(text: str, source: str = "dialog") -> bool:
    """从文本中抽取事实/偏好并落盘。"""
    try:
        extracted = []
        for pattern, fact_type in _PREFERENCE_PATTERNS:
            for m in pattern.finditer(text):
                value = m.group(1).strip()
                if value and len(value) >= 2:
                    extracted.append({"type": fact_type, "value": value})

        has_keyword = any(kw in text.lower() for kw in _FACT_KEYWORDS)
        if not extracted and has_keyword:
            snippet = text.strip()[:160]
            if len(snippet) >= 4:
                extracted.append({"type": "fact", "value": snippet})

        if not extracted:
            return False

        with _lock:
            entries = _load_all()

        for fact in extracted:
            entry = {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "type": fact["type"],
                "value": fact["value"],
                "source": source,
            }
            is_dup = False
            for e in entries[-20:]:
                if e.get("value") == fact["value"] and e.get("type") == fact["type"]:
                    e["ts"] = entry["ts"]
                    is_dup = True
                    break
            if not is_dup:
                entries.append(entry)

            if len(entries) > _MAX_ENTRIES:
                scored = []
                for e in entries:
                    w = _decay_weight(e.get("ts", ""))
                    e["_w"] = w
                    scored.append(e)
                scored.sort(key=lambda x: x.get("_w", 0.5))
                entries = scored[len(scored) - _MAX_ENTRIES:]
                for e in entries:
                    e.pop("_w", None)

        _save_all(entries)
        return True
    except Exception:
        return False


def recall_user_profile(top_k: int = 5, query: str = "") -> List[Dict]:
    """返回 top-k 用户画像（按衰减权重 + 可选查询相似度排序）。"""
    try:
        with _lock:
            entries = _load_all()

        q_tokens = _tokenize_bigram(query) if query else set()

        scored = []
        for e in entries:
            w = _decay_weight(e.get("ts", ""))
            sim = _similarity(q_tokens, _tokenize_bigram(e.get("value", ""))) if q_tokens else 0.0
            score = w * 0.7 + sim * 0.3
            scored.append({**e, "_score": round(score, 4)})

        scored.sort(key=lambda x: x.get("_score", 0), reverse=True)
        result = []
        for s in scored[:top_k]:
            s.pop("_score", None)
            s.pop("_w", None)
            result.append(s)
        return result
    except Exception:
        return []


def inject_into_prompt(system_prompt: str, query: str = "", max_chars: int = 300) -> str:
    """注入用户画像 top-5 到 system prompt 尾部。"""
    try:
        profile = recall_user_profile(top_k=5, query=query)
        if not profile:
            return system_prompt
        parts = []
        for p in profile:
            t = p.get("type", "fact")
            v = p.get("value", "")
            parts.append(f"  [{t}] {v}")
        block = "\n## 用户画像\n" + "\n".join(parts) + "\n"
        if len(block) > max_chars:
            block = block[:max_chars] + "\n..."
        return system_prompt.rstrip() + "\n" + block
    except Exception:
        return system_prompt


def get_memory_stats() -> Dict:
    try:
        with _lock:
            entries = _load_all()
        types = {}
        for e in entries:
            t = e.get("type", "unknown")
            types[t] = types.get(t, 0) + 1
        return {"total": len(entries), "max": _MAX_ENTRIES, "types": types, "decay_days": _DECAY_DAYS}
    except Exception:
        return {"total": 0, "max": _MAX_ENTRIES, "types": {}, "decay_days": _DECAY_DAYS}
