# -*- coding: utf-8 -*-
"""蒸馏知识库（DistillKnowledgeBase）
=====================================

从 InteractionLogger 落盘的 JSONL 交互日志中蒸馏 Few-Shot 示例：
  - 扫描 log_dir 下全部 *.jsonl，提取 type='interaction' 的记录
  - 过滤过短 prompt（<10 字符）/ 过短 response（<20 字符）
  - 建立词条倒排索引，按查询词覆盖率打分检索
  - format_few_shot() 把检索结果格式化为可注入 prompt 的示例块

★ v5.8 补全：tests/test_distillation_core.py 定义了完整契约但实现此前缺失
（core.knowledge_base 是转发柠檬小助手 KB 的垫片，与本 API 不同名同命），
本模块按测试契约实现，作为「蒸馏四模块」的知识库拼图。
"""
import os
import re
import glob
import json
import logging
import threading
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# CJK 单字 + ASCII 词元（中文按单字切，英文按完整单词切，避免误匹配）
_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]")

_PROMPT_MIN = 10    # prompt 最短字符数
_RESPONSE_MIN = 20  # response 最短字符数
_SCORE_MIN = 0.2    # 检索最低相关度（查询词覆盖率）
_PROMPT_TRUNC = 200   # few-shot 示例中 prompt 截断长度
_RESPONSE_TRUNC = 300  # few-shot 示例中 response 截断长度


def _tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall((text or "").lower())


class KnowledgeBase:
    """交互日志蒸馏知识库（Few-Shot 检索）。"""

    MAX_EXAMPLES = 2000  # 类属性：允许测试 patch 覆盖

    def __init__(self, log_dir: str = None):
        self.log_dir = log_dir or ""
        self._examples: List[Dict] = []          # 蒸馏出的示例列表
        self._term_index: Dict[str, int] = {}    # 词条 → 出现的示例数
        self._example_tokens: List[set] = []     # 每条示例的词元集合（与 _examples 对齐）
        self._loaded = False
        self._lock = threading.RLock()

        if self.log_dir and os.path.isdir(self.log_dir):
            self._load_examples()
            self._loaded = True

    # ============================================================
    # 加载 / 蒸馏
    # ============================================================

    def _load_examples(self) -> None:
        """扫描 log_dir 下全部 *.jsonl，蒸馏有效交互记录。"""
        with self._lock:
            self._examples = []
            self._term_index = {}
            self._example_tokens = []

            for filepath in sorted(glob.glob(os.path.join(self.log_dir, "*.jsonl"))):
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                record = json.loads(line)
                            except json.JSONDecodeError:
                                continue  # 跳过损坏行
                            self._absorb(record)
                            if len(self._examples) >= self.MAX_EXAMPLES:
                                return
                except OSError as e:
                    logger.debug("[DistillKB] 读取失败 %s: %s", filepath, e)

    def _absorb(self, record: dict) -> None:
        """单条记录蒸馏入库（不合规记录静默过滤）。"""
        if not isinstance(record, dict):
            return
        if record.get("type") != "interaction":
            return
        prompt = (record.get("prompt") or "").strip()
        response = (record.get("response") or "").strip()
        if len(prompt) < _PROMPT_MIN or len(response) < _RESPONSE_MIN:
            return

        tokens = set(_tokenize(prompt))
        self._examples.append({
            "prompt": prompt,
            "response": response,
            "engine": record.get("engine", ""),
            "timestamp": record.get("timestamp", ""),
        })
        self._example_tokens.append(tokens)
        for t in tokens:
            self._term_index[t] = self._term_index.get(t, 0) + 1

    def refresh(self) -> None:
        """重新扫描 log_dir（新增日志后调用）。"""
        if self.log_dir and os.path.isdir(self.log_dir):
            self._load_examples()
            self._loaded = True

    # ============================================================
    # 检索
    # ============================================================

    def retrieve(self, query: str, k: Optional[int] = None) -> List[Dict]:
        """按查询词覆盖率检索相似历史交互。

        Returns:
            [{'prompt','response','score','engine','timestamp'}, ...]
            score ∈ [0,1]，按相关度降序；无相关结果返回 []。
        """
        q_tokens = _tokenize(query or "")
        if not q_tokens:
            return []

        q_set = set(q_tokens)
        scored = []
        with self._lock:
            for i, tokens in enumerate(self._example_tokens):
                if not tokens:
                    continue
                overlap = len(q_set & tokens)
                score = overlap / len(q_set)
                if score >= _SCORE_MIN:
                    item = dict(self._examples[i])
                    item["score"] = round(min(score, 1.0), 4)
                    scored.append(item)

        scored.sort(key=lambda r: -r["score"])
        if k is not None:
            scored = scored[:k]
        return scored

    def format_few_shot(self, query: str, k: int = 3) -> str:
        """把检索结果格式化为可注入 system/prompt 的 Few-Shot 示例块。

        无相关结果时返回空字符串（调用方据此跳过注入）。
        """
        results = self.retrieve(query, k=k)
        if not results:
            return ""

        blocks = []
        for idx, r in enumerate(results, 1):
            blocks.append(
                f"--- 示例 {idx} ---\n"
                f"问: {r['prompt'][:_PROMPT_TRUNC]}\n"
                f"答: {r['response'][:_RESPONSE_TRUNC]}"
            )
        return (
            "以下是历史上类似问题的回答示例，供参考：\n\n"
            + "\n\n".join(blocks)
            + "\n\n--- 当前问题 ---"
        )

    # ============================================================
    # 统计
    # ============================================================

    def get_stats(self) -> Dict:
        return {
            "total_examples": len(self._examples),
            "indexed_terms": len(self._term_index),
            "loaded": self._loaded,
            "log_dir": self.log_dir,
        }


# ============================================================
# 全局单例
# ============================================================

_kb_instance: Optional[KnowledgeBase] = None


def get_knowledge_base() -> KnowledgeBase:
    """获取全局蒸馏知识库单例（log_dir 取默认交互日志目录）。"""
    global _kb_instance
    if _kb_instance is None:
        from core.interaction_logger import get_interaction_logger
        try:
            default_dir = get_interaction_logger()._log_dir
        except Exception:
            default_dir = os.path.join("data", "interactions")
        _kb_instance = KnowledgeBase(log_dir=default_dir)
    return _kb_instance
