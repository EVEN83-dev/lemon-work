# -*- coding: utf-8 -*-
"""
379-2→380A-3: 成功轨迹 RAG —— 全引擎化
====================================================
设计依据（379 章命令 3.1 授权 → 380A-3 全引擎化升级）：
现有 VectorDatabaseManager 为 QObject +
ChromaDB/TF-IDF 重量级实现，不适合在 agent_chat 热路径内直接复用；
技能轨迹条目少（≤500）、字段固定、检索需求仅为"关键词重合"，
故采用最朴素方案：data/skill_trajectories.jsonl 落盘 + 字符 bigram 重合度检索。

380A-3 变更：
  - record_skill_trajectory 新增 engine 参数，入库打标签区分来源
  - 调用方不再限制为 ollama，所有引擎均可入库/检索
  - 裸答拦截器（379-1）的 ollama 守卫不动

接口：
    record_skill_trajectory(prompt, tool_calls_made, engine="")   # 成功收尾时记录
    recall_similar_trajectories(prompt, top_k=2)       # 开头注入 top-k 相似历史

铁律：全部函数 try/except 自包——任何异常不得影响 agent_chat 主流程。
"""

import json
import os
import threading
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAJECTORY_FILE = os.path.join(_PROJECT_ROOT, "data", "skill_trajectories.jsonl")
_MAX_ENTRIES = 500

_lock = threading.Lock()


def _tokenize(text: str) -> set:
    """极简中英混合分词：连续字母/数字词 + 中文单字 bigram。"""
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
    # 中文 bigram
    cjk = [ch for ch in text if '\u4e00' <= ch <= '\u9fff']
    for i in range(len(cjk) - 1):
        tokens.add(cjk[i] + cjk[i + 1])
    return tokens


def _similarity(a_tokens: set, b_tokens: set) -> float:
    """Jaccard 重合度。"""
    if not a_tokens or not b_tokens:
        return 0.0
    inter = len(a_tokens & b_tokens)
    union = len(a_tokens | b_tokens)
    return inter / union if union else 0.0


def _load_all():
    if not os.path.exists(TRAJECTORY_FILE):
        return []
    entries = []
    try:
        with open(TRAJECTORY_FILE, "r", encoding="utf-8") as f:
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


def record_skill_trajectory(prompt: str, tool_calls_made, engine: str = "") -> bool:
    """记录一次成功任务的轨迹（≥1 次技能调用即记录；>500 条滚动淘汰最旧）。

    Args:
        prompt: 用户原始请求
        tool_calls_made: agent_chat 的 tool_calls_made 列表
                         [{name, arguments, success, ...}, ...]
        engine: 引擎名称（380A-3: 打标签区分来源）
    Returns:
        True=已记录
    """
    try:
        if not tool_calls_made:
            return False
        skills = []
        for tc in tool_calls_made:
            name = tc.get("name", "") if isinstance(tc, dict) else str(tc)
            if name and name not in skills:
                skills.append(name)
        if not skills:
            return False
        entry = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "prompt_summary": (prompt or "")[:160],
            "skills": skills,
            "args_summary": json.dumps(
                [tc.get("arguments", {}) for tc in tool_calls_made[:3]
                 if isinstance(tc, dict)], ensure_ascii=False)[:300],
            "engine": engine or "unknown",
        }
        with _lock:
            os.makedirs(os.path.dirname(TRAJECTORY_FILE), exist_ok=True)
            entries = _load_all()
            entries.append(entry)
            if len(entries) > _MAX_ENTRIES:
                entries = entries[-_MAX_ENTRIES:]  # 滚动淘汰最旧
            with open(TRAJECTORY_FILE, "w", encoding="utf-8") as f:
                for e in entries:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def recall_similar_trajectories(prompt: str, top_k: int = 2,
                                min_score: float = 0.06) -> list:
    """按关键词重合度检索 top-k 相似历史成功轨迹。

    Returns:
        [{"skill": str, "score": float, "ts": str}, ...]（按分数降序）
        无轨迹/异常时返回 []。
    """
    try:
        q_tokens = _tokenize(prompt)
        if not q_tokens:
            return []
        scored = []
        for e in _load_all():
            skills = e.get("skills") or []
            if not skills:
                continue
            score = _similarity(q_tokens, _tokenize(e.get("prompt_summary", "")))
            if score >= min_score:
                scored.append({"skill": skills[0], "skills": skills,
                               "score": round(score, 3), "ts": e.get("ts", "")})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:max(1, top_k)]
    except Exception:
        return []
