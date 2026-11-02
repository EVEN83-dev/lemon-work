# -*- coding: utf-8 -*-
"""
Few-Shot 知识库 — 蒸馏系统核心模块
===================================
功能：
1. 存储高质量用户-助手对话对（few-shot examples）
2. 按任务类型检索最佳匹配的示例
3. 注入到 LLM prompt 中提升响应质量
4. 自动评分和淘汰低质量示例
5. 支持向量相似度搜索（可选，依赖 sentence-transformers）
6. 与 InteractionLogger 和 FeedbackLoop 联动

设计原理：
- 用户-助手对话对作为 few-shot 示例，而非单独 assistant 消息
- 防止模型偏差，提升响应准确性
- 定期淘汰低质量示例，保持知识库新鲜度
"""

import os
import json
import time
import threading
import hashlib
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from collections import OrderedDict


# ============================================================
# 数据模型
# ============================================================

@dataclass
class FewShotExample:
    """Few-Shot 示例"""
    id: str
    user_message: str
    assistant_response: str
    task_type: str = "general"        # 任务类型
    quality_score: float = 5.0        # 质量评分 (0-10)
    usage_count: int = 0              # 使用次数
    success_count: int = 0            # 成功次数
    created_at: float = 0.0
    last_used: float = 0.0
    tags: List[str] = field(default_factory=list)

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()

    def to_dict(self) -> Dict:
        return asdict(self)

    @property
    def success_rate(self) -> float:
        if self.usage_count == 0:
            return 0.0
        return self.success_count / self.usage_count

    @property
    def is_active(self) -> bool:
        """是否仍活跃（质量评分 >= 3.0）"""
        return self.quality_score >= 3.0


# ============================================================
# Few-Shot 知识库
# ============================================================

class FewShotKnowledgeBase:
    """Few-Shot 知识库

    三级存储：
    1. 内存缓存（快速检索）
    2. 本地 JSON 文件（持久化）
    3. 向量索引（可选，语义相似度）
    """

    DEFAULT_TASK_TYPES = [
        "code_generation",
        "code_review",
        "debugging",
        "refactoring",
        "testing",
        "documentation",
        "data_analysis",
        "web_development",
        "devops",
        "security",
        "general",
    ]

    def __init__(
        self,
        storage_dir: str = None,
        max_examples: int = 500,
        max_per_task: int = 50,
        min_quality: float = 3.0,
        enable_vector_search: bool = True,
    ):
        if storage_dir is None:
            storage_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..", "..", "data", "few_shot_kb"
            )
        self.storage_dir = os.path.abspath(storage_dir)
        self.max_examples = max_examples
        self.max_per_task = max_per_task
        self.min_quality = min_quality
        self.enable_vector_search = enable_vector_search

        self._examples: Dict[str, FewShotExample] = OrderedDict()
        self._task_index: Dict[str, List[str]] = {}  # task_type → [example_ids]
        self._lock = threading.Lock()
        self._embedding_model = None
        self._embeddings: Dict[str, List[float]] = {}  # example_id → embedding

        os.makedirs(self.storage_dir, exist_ok=True)
        self._load_from_disk()

        if enable_vector_search:
            self._init_vector_search()

    # ---- 添加 ----

    def add_example(
        self,
        user_message: str,
        assistant_response: str,
        task_type: str = "general",
        quality_score: float = 5.0,
        tags: List[str] = None,
    ) -> str:
        """添加 Few-Shot 示例"""
        example_id = self._generate_id(user_message, assistant_response)

        with self._lock:
            # 检查是否已存在
            if example_id in self._examples:
                existing = self._examples[example_id]
                existing.quality_score = (existing.quality_score + quality_score) / 2
                existing.usage_count += 1
                existing.last_used = time.time()
                return example_id

            # 容量控制
            if len(self._examples) >= self.max_examples:
                self._evict_lowest_quality()

            # 每任务类型容量控制
            task_examples = self._task_index.get(task_type, [])
            if len(task_examples) >= self.max_per_task:
                self._evict_task_lowest(task_type)

            example = FewShotExample(
                id=example_id,
                user_message=user_message,
                assistant_response=assistant_response,
                task_type=task_type or "general",
                quality_score=quality_score,
                tags=tags or [],
            )

            self._examples[example_id] = example
            self._task_index.setdefault(task_type, []).append(example_id)

            # 向量索引
            if self.enable_vector_search and self._embedding_model:
                try:
                    embedding = self._compute_embedding(user_message)
                    self._embeddings[example_id] = embedding
                except Exception:
                    pass

        return example_id

    # ---- 检索 ----

    def retrieve(
        self,
        prompt: str,
        task_type: Optional[str] = None,
        limit: int = 5,
        min_quality: float = None,
    ) -> List[FewShotExample]:
        """检索最佳匹配的 Few-Shot 示例

        Args:
            prompt: 当前用户输入
            task_type: 任务类型过滤
            limit: 返回数量
            min_quality: 最低质量阈值

        Returns:
            按匹配度排序的示例列表
        """
        min_q = min_quality or self.min_quality

        candidates = []
        with self._lock:
            # 按任务类型过滤
            if task_type and task_type in self._task_index:
                ids = self._task_index[task_type]
                candidates = [
                    self._examples[eid] for eid in ids
                    if eid in self._examples and self._examples[eid].quality_score >= min_q
                ]
            else:
                candidates = [
                    e for e in self._examples.values()
                    if e.quality_score >= min_q
                ]

        if not candidates:
            return []

        # 向量相似度排序
        if self.enable_vector_search and self._embedding_model and self._embeddings:
            try:
                query_embedding = self._compute_embedding(prompt)
                scored = []
                for ex in candidates:
                    ex_emb = self._embeddings.get(ex.id)
                    if ex_emb:
                        sim = self._cosine_similarity(query_embedding, ex_emb)
                        scored.append((ex, sim * ex.quality_score / 10))
                    else:
                        scored.append((ex, ex.quality_score / 10))
                scored.sort(key=lambda x: x[1], reverse=True)
                return [s[0] for s in scored[:limit]]
            except Exception:
                pass

        # 回退：按质量评分 + 最近使用排序
        candidates.sort(
            key=lambda e: (e.quality_score * 0.7 + min(e.last_used / time.time(), 1) * 0.3),
            reverse=True
        )
        return candidates[:limit]

    def retrieve_by_keywords(
        self,
        keywords: List[str],
        task_type: Optional[str] = None,
        limit: int = 5,
    ) -> List[FewShotExample]:
        """按关键词检索"""
        with self._lock:
            candidates = list(self._examples.values())
            if task_type:
                candidates = [e for e in candidates if e.task_type == task_type]

        scored = []
        for ex in candidates:
            text = (ex.user_message + " " + ex.assistant_response).lower()
            score = sum(1 for kw in keywords if kw.lower() in text)
            if score > 0:
                scored.append((ex, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [s[0] for s in scored[:limit]]

    # ---- 格式化 ----

    def format_as_prompt(self, examples: List[FewShotExample]) -> str:
        """将 Few-Shot 示例格式化为 Prompt 注入文本"""
        if not examples:
            return ""

        lines = [
            "\n# 以下是历史高质量对话示例，请参考其风格和格式：\n",
        ]
        for i, ex in enumerate(examples, 1):
            lines.append(f"## 示例 {i}")
            lines.append(f"用户: {ex.user_message}")
            lines.append(f"助手: {ex.assistant_response}")
            lines.append("")

        return "\n".join(lines)

    def format_as_messages(self, examples: List[FewShotExample]) -> List[Dict]:
        """将 Few-Shot 示例格式化为消息列表"""
        messages = []
        for ex in examples:
            messages.append({"role": "user", "content": ex.user_message})
            messages.append({"role": "assistant", "content": ex.assistant_response})
        return messages

    # ---- 反馈 ----

    def record_usage(self, example_id: str, success: bool = True):
        """记录示例使用情况"""
        with self._lock:
            if example_id in self._examples:
                ex = self._examples[example_id]
                ex.usage_count += 1
                if success:
                    ex.success_count += 1
                ex.last_used = time.time()

                # 动态调整质量评分
                if ex.usage_count >= 10:
                    sr = ex.success_rate
                    if sr < 0.3:
                        ex.quality_score = max(0, ex.quality_score - 1.0)
                    elif sr > 0.8:
                        ex.quality_score = min(10, ex.quality_score + 0.5)

    def update_quality(self, example_id: str, score: float):
        """更新质量评分"""
        with self._lock:
            if example_id in self._examples:
                ex = self._examples[example_id]
                ex.quality_score = max(0, min(10, score))

    # ---- 管理 ----

    def get_stats(self) -> Dict:
        """获取统计信息"""
        with self._lock:
            total = len(self._examples)
            active = sum(1 for e in self._examples.values() if e.is_active)
            avg_quality = (
                sum(e.quality_score for e in self._examples.values()) / total
                if total > 0 else 0
            )
            task_counts = {
                t: len(ids) for t, ids in self._task_index.items()
            }

        return {
            "total_examples": total,
            "active_examples": active,
            "average_quality": round(avg_quality, 2),
            "task_distribution": task_counts,
            "max_examples": self.max_examples,
            "embedding_model": self._embedding_model is not None,
        }

    def prune(self) -> int:
        """清理低质量示例"""
        removed = 0
        with self._lock:
            to_remove = [
                eid for eid, ex in self._examples.items()
                if not ex.is_active
            ]
            for eid in to_remove:
                ex = self._examples.pop(eid, None)
                if ex:
                    task_ids = self._task_index.get(ex.task_type, [])
                    if eid in task_ids:
                        task_ids.remove(eid)
                    self._embeddings.pop(eid, None)
                    removed += 1

        if removed > 0:
            self._save_to_disk()
        return removed

    def clear(self):
        """清空知识库"""
        with self._lock:
            self._examples.clear()
            self._task_index.clear()
            self._embeddings.clear()
        self._save_to_disk()

    # ---- 内部方法 ----

    def _generate_id(self, user_msg: str, assistant_msg: str) -> str:
        content = (user_msg + assistant_msg).encode("utf-8")
        return hashlib.md5(content).hexdigest()[:12]

    def _evict_lowest_quality(self):
        """淘汰最低质量的示例"""
        if not self._examples:
            return
        worst = min(self._examples.values(), key=lambda e: e.quality_score)
        self._examples.pop(worst.id, None)
        task_ids = self._task_index.get(worst.task_type, [])
        if worst.id in task_ids:
            task_ids.remove(worst.id)
        self._embeddings.pop(worst.id, None)

    def _evict_task_lowest(self, task_type: str):
        """淘汰指定任务类型中最低质量的示例"""
        ids = self._task_index.get(task_type, [])
        if not ids:
            return
        worst_id = min(
            ids,
            key=lambda eid: self._examples[eid].quality_score if eid in self._examples else 10
        )
        self._examples.pop(worst_id, None)
        ids.remove(worst_id)
        self._embeddings.pop(worst_id, None)

    def _compute_embedding(self, text: str) -> List[float]:
        """计算文本嵌入向量"""
        if not self._embedding_model:
            # 回退：简单 TF-IDF 风格哈希
            words = text.lower().split()
            embedding = [0.0] * 128
            for w in words:
                h = hash(w) % 128
                embedding[h] += 1.0
            # 归一化
            norm = max(1.0, sum(e**2 for e in embedding) ** 0.5)
            return [e / norm for e in embedding]
        return self._embedding_model.encode(text).tolist()

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        if len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x**2 for x in a) ** 0.5
        norm_b = sum(y**2 for y in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _init_vector_search(self):
        """初始化向量搜索"""
        try:
            from sentence_transformers import SentenceTransformer
            self._embedding_model = SentenceTransformer(
                "paraphrase-multilingual-MiniLM-L12-v2"
            )
            print(f"[FewShotKB] 向量搜索已启用 (sentence-transformers)")
        except ImportError:
            print("[FewShotKB] sentence-transformers 未安装，使用哈希回退")
            self._embedding_model = None
        except Exception as e:
            print(f"[FewShotKB] 向量搜索初始化失败: {e}")
            self._embedding_model = None

    def _save_to_disk(self):
        """持久化到磁盘"""
        try:
            data = {
                "examples": [e.to_dict() for e in self._examples.values()],
                "task_index": self._task_index,
                "saved_at": time.time(),
            }
            path = os.path.join(self.storage_dir, "few_shot_examples.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[FewShotKB] 保存失败: {e}")

    def _load_from_disk(self):
        """从磁盘加载"""
        path = os.path.join(self.storage_dir, "few_shot_examples.json")
        if not os.path.exists(path):
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for ex_data in data.get("examples", []):
                example = FewShotExample(**ex_data)
                self._examples[example.id] = example
                self._task_index.setdefault(example.task_type, []).append(example.id)

            print(f"[FewShotKB] 已加载 {len(self._examples)} 个示例")
        except Exception as e:
            print(f"[FewShotKB] 加载失败: {e}")


# ============================================================
# 批量导入
# ============================================================

def import_from_interaction_logger(
    kb: FewShotKnowledgeBase,
    logger,
    min_rating: int = 4,
    limit: int = 200,
):
    """从 InteractionLogger 批量导入高质量对话对"""
    pairs = logger.get_high_quality_pairs(min_rating=min_rating, limit=limit)
    imported = 0
    for pair in pairs:
        user_msg = pair.get("prompt", "")
        assistant_msg = pair.get("response", "")
        task_type = pair.get("task_type", "general")
        rating = pair.get("rating", 5)

        if user_msg and assistant_msg:
            kb.add_example(
                user_message=user_msg,
                assistant_response=assistant_msg,
                task_type=task_type,
                quality_score=min(10, rating * 2),  # 5分制 → 10分制
                tags=pair.get("tags", []),
            )
            imported += 1

    return imported


# ============================================================
# 全局单例
# ============================================================

_global_kb: Optional[FewShotKnowledgeBase] = None
_kb_lock = threading.Lock()


def get_few_shot_kb() -> FewShotKnowledgeBase:
    """获取全局 Few-Shot 知识库单例"""
    global _global_kb
    if _global_kb is None:
        with _kb_lock:
            if _global_kb is None:
                _global_kb = FewShotKnowledgeBase()
    return _global_kb


# ============================================================
# 自检
# ============================================================

if __name__ == "__main__":
    kb = get_few_shot_kb()

    # 添加示例
    kb.add_example(
        user_message="帮我写一个Python排序函数",
        assistant_response="以下是冒泡排序的实现：\ndef bubble_sort(arr):\n    n = len(arr)\n    for i in range(n):\n        for j in range(0, n-i-1):\n            if arr[j] > arr[j+1]:\n                arr[j], arr[j+1] = arr[j+1], arr[j]\n    return arr",
        task_type="code_generation",
        quality_score=8.0,
        tags=["python", "sorting", "algorithm"],
    )

    kb.add_example(
        user_message="这段代码有什么问题？for i in range(len(arr)): print(arr[i+1])",
        assistant_response="这段代码有数组越界风险：当 i = len(arr)-1 时，arr[i+1] 会访问 arr[len(arr)]，导致 IndexError。建议改为 range(len(arr)-1)。",
        task_type="code_review",
        quality_score=9.0,
        tags=["python", "bug", "index-error"],
    )

    # 检索
    results = kb.retrieve("写一个排序算法", task_type="code_generation")
    print(f"检索到 {len(results)} 个相关示例")

    # 统计
    stats = kb.get_stats()
    print(f"知识库统计: {stats}")

    # 格式化
    prompt = kb.format_as_prompt(results)
    print(f"Prompt 注入:\n{prompt[:200]}...")