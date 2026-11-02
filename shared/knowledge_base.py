# -*- coding: utf-8 -*-
"""
柠檬小助手 知识库加载器（v2.0 — 向量检索 + 会话记忆）
===============================================
负责加载 data/robot_knowledge 下的知识库文件，并提供：
- 场景匹配（关键词命中 + TF-IDF 向量检索返回剧本回复）
- 系统提示词构建（性格 + Agent 指导 + 技术知识摘要）
- 上下文构建（匹配到的场景作为 few-shot 示例注入）
- 会话记忆（跨会话记忆持久化 + 项目级记忆）
- 向量检索（基于 TF-IDF 的语义相似度匹配）

所有知识库文件用 UTF-8 读取，文件缺失时不崩溃，返回空值。
"""

import os
import re
import json
import math
import time
from collections import defaultdict
from typing import List, Dict, Optional, Tuple


class KnowledgeBase:
    """柠檬小助手 的知识储备库"""

    # 场景文件里每条记录的分隔符：场景|用户可能说的话|机器人回复
    _SCENE_SEP = '|'

    def __init__(self, knowledge_dir='data/robot_knowledge'):
        # 支持相对路径：以本文件所在目录为基准向上推导项目根
        if not os.path.isabs(knowledge_dir):
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            knowledge_dir = os.path.join(base, knowledge_dir)
        self.knowledge_dir = knowledge_dir

        self.scenes = []          # 场景对话列表：[(scene, phrase, reply), ...]
        self.guide = ''           # 操作指南（agent_guide.txt 全文）
        self.personality = ''     # 性格设定（personality.txt 全文）
        self.tech = ''            # 技术知识（tech_knowledge.txt 全文）

        self._loaded = False

    # ==================== 文件读取 ====================
    def _read_text(self, filename):
        """安全读取一个知识库文件，UTF-8 编码。不存在/出错返回空串。"""
        path = os.path.join(self.knowledge_dir, filename)
        if not os.path.isfile(path):
            return ''
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except (OSError, UnicodeDecodeError):
            return ''

    # ==================== 加载 ====================
    def load(self):
        """加载所有知识库文件"""
        self.guide = self._read_text('agent_guide.txt')
        self.personality = self._read_text('personality.txt')
        self.tech = self._read_text('tech_knowledge.txt')
        self.scenes = self._parse_scenes(self._read_text('chat_scenarios.txt'))
        self._loaded = True
        return self

    def _parse_scenes(self, content):
        """解析场景剧本文件。
        每行格式：场景|用户可能说的话|机器人回复
        跳过空行、注释（# 开头）、分隔线（=== 开头）以及无 | 的标题行。
        """
        scenes = []
        if not content:
            return scenes
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            # 跳过注释和装饰行
            if line.startswith('#') or line.startswith('===') or line.startswith('---'):
                continue
            # 必须至少有两个分隔符，构成三段
            parts = line.split(self._SCENE_SEP)
            if len(parts) < 3:
                continue
            scene = parts[0].strip()
            phrase = parts[1].strip()
            # 回复可能自身含有 | ，故用第3段之后的全部内容拼接还原
            reply = self._SCENE_SEP.join(parts[2:]).strip()
            if not scene or not phrase or not reply:
                continue
            scenes.append((scene, phrase, reply))
        return scenes

    # ==================== 场景匹配 ====================
    def _match_scenes(self, user_input, limit=5):
        """根据用户输入做关键词匹配，返回命中的场景列表。
        
        匹配优先级（从高到低）：
        1. 完全匹配：用户输入 == phrase
        2. 正向包含：phrase 在用户输入中（长关键词优先）
        3. 反向包含：用户输入中的核心词在 phrase 中（排除通用词）
        4. 模糊匹配：用户输入中的词与 phrase 有部分重叠
        
        通用词不参与反向匹配。
        """
        if not user_input or not self.scenes:
            return []
        text = user_input.strip().lower()
        if not text:
            return []

        # 通用词列表（不参与反向匹配）
        stop_words = {
            '什么', '怎么', '为什么', '吗', '呢', '了', '的', '是', '我', '你', '他', '她', '它',
            '这', '那', '有', '在', '也', '就', '都', '还', '又', '再', '很', '太', '真', '好',
            '不', '没', '给', '把', '被', '让', '叫', '说', '看', '听', '想', '要', '会', '能',
            '可以', '呀', '啊', '哦', '哈', '嘿', '哎', '唉', '吧', '啦', '嘛', '呢', '咯',
            '一个', '一下', '一些', '一点', '有点', '比较', '非常', '特别', '十分', '相当',
        }

        exact_matches = []       # 优先级1：完全匹配
        forward_matches = []     # 优先级2：正向包含（phrase in text）
        backward_matches = []    # 优先级3：反向包含（非通用词在 phrase 中）
        fuzzy_matches = []       # 优先级4：模糊匹配
        seen_reply = set()

        for scene, phrase, reply in self.scenes:
            if not phrase or reply in seen_reply:
                continue
            p = phrase.strip().lower()
            if not p:
                continue

            # 优先级1：完全匹配
            if p == text:
                exact_matches.append((scene, phrase, reply, 1000 + len(p)))
                seen_reply.add(reply)
                continue

            # 优先级2：正向包含（phrase 在用户输入中）
            if p in text:
                forward_matches.append((scene, phrase, reply, 100 + len(p)))
                seen_reply.add(reply)
                continue

            # 优先级3：反向包含（用户输入中的非通用词在 phrase 中）
            matched = False
            max_bigram_len = 0
            if len(text) >= 2:
                for i in range(len(text) - 1):
                    bigram = text[i:i+2]
                    if bigram in stop_words:
                        continue
                    if len(bigram.strip()) < 2:
                        continue
                    if bigram in p:
                        matched = True
                        max_bigram_len = max(max_bigram_len, 2)
                for i in range(len(text) - 2):
                    trigram = text[i:i+3]
                    if trigram in stop_words:
                        continue
                    if trigram in p:
                        matched = True
                        max_bigram_len = max(max_bigram_len, 3)

            if matched and reply not in seen_reply:
                backward_matches.append((scene, phrase, reply, 10 + max_bigram_len))
                seen_reply.add(reply)
                continue

            # 优先级4：模糊匹配（单字匹配）
            if not matched and reply not in seen_reply:
                # 提取用户输入中的关键字符（排除通用词）
                key_chars = set()
                for ch in text:
                    if ch not in stop_words and len(ch.strip()) > 0:
                        key_chars.add(ch)
                
                # 检查 phrase 中是否包含这些字符
                match_count = sum(1 for ch in key_chars if ch in p)
                if match_count >= 2:  # 至少2个字符匹配
                    fuzzy_matches.append((scene, phrase, reply, match_count))
                    seen_reply.add(reply)

        # 组合所有匹配，按分数倒序
        all_matches = exact_matches + forward_matches + backward_matches + fuzzy_matches
        all_matches.sort(key=lambda item: item[3], reverse=True)
        
        # 去掉分数字段，只返回场景三元组
        result = [(s, p, r) for s, p, r, _ in all_matches]
        return result[:limit]

    def find_scene_reply(self, user_input):
        """根据用户输入匹配场景，返回最佳回复（单条字符串）。
        没有命中则返回空串。
        """
        matches = self._match_scenes(user_input, limit=1)
        if not matches:
            return ''
        return matches[0][2]

    # ==================== 系统提示词 ====================
    def build_system_prompt(self):
        """构建精简的系统提示词（只包含核心回复规范）"""
        if not self._loaded:
            self.load()

        # 核心回复规范（极简版 - 小模型用短提示词效果更好）
        core_prompt = """你是柠檬小助手，活泼的AI小助手，住在编辑器里。

【★★★ 绝对禁止 - 生成文件 ★★★】
严禁生成任何保存图片的Python代码！
严禁使用matplotlib、plt.savefig、plt.show等函数！
严禁生成.html文件！严禁用explorer或浏览器打开任何文件！
严禁在回复中提"已生成html文件"、"用浏览器打开"、"explorer"等内容！
违反以上规则会导致系统崩溃！

【重要 - 右侧栏可视化能力】
右侧栏可直接渲染所有图表和几何体！支持：
- 统计图表：柱状图、折线图、饼图、散点图
- 函数图像：y=sin(x)、y=cos(x)、y=tan(x)、y=x^2、y=sqrt(x)、y=e^x等
- 3D几何体：正方体、长方体、圆柱、圆锥、球体、椭球、三棱锥、四棱锥、三棱柱
- 3D曲面

你只需输出函数表达式（如"y = sin(x)"）或几何体名称（如"正方体"、"柱状图"），右侧栏会自动渲染。
直接输出表达式或名称即可，右侧栏会自动显示图像，无需生成任何文件！

【重要 - 统计图必须附带结构化数据】
当你提到柱状图/折线图/饼图/散点图时，必须在回复中附带数据，格式任选其一：

格式1（Markdown表格，推荐）：
| 月份 | 销量 |
|---|---|
| 1月 | 100 |
| 2月 | 200 |

格式2（JSON代码块）：
```json
{"labels": ["1月", "2月", "3月"], "values": [100, 200, 150]}
```

格式3（纯文本）：
1月:100, 2月:200, 3月:150

格式4（百分比，饼图推荐）：
电子产品占30%, 笔记本占25%, 手机占45%

数据会自动传递到图表渲染器，无需生成HTML文件。

回复要求：
- 简短口语化，20字以内
- 可用1个emoji
- 针对问题直接回答
- 不知道就说不知道"""

        return core_prompt

    # ==================== 上下文构建 ====================
    def build_context(self, user_input):
        """根据用户输入构建上下文（匹配到的场景作为 few-shot 示例）。
        返回一段提示文本，可拼接到对话历史之前。无命中时返回空串。
        """
        if not self._loaded:
            self.load()

        matches = self._match_scenes(user_input, limit=5)
        if not matches:
            return ''

        lines = ['【参考对话示例（请参考语气和风格，但不要照抄，结合用户原话自然回复）】']
        for scene, phrase, reply in matches:
            lines.append(f'用户：{phrase}')
            lines.append(f'柠檬小助手：{reply}')
        lines.append('【示例结束】')
        return '\n'.join(lines)

    # ==================== 工具方法 ====================
    @staticmethod
    def _strip_decor(text):
        """去掉装饰性的 === 分隔线和 --- 分隔线，压缩连续空行，保留正文。"""
        if not text:
            return text
        kept = []
        for line in text.splitlines():
            s = line.strip()
            if s.startswith('===') or s.startswith('---'):
                continue
            kept.append(line)
        out = '\n'.join(kept)
        # 压缩 3 个及以上连续换行为 2 个
        out = re.sub(r'\n{3,}', '\n\n', out)
        return out.strip()

    def _tech_summary(self):
        """从技术知识全文抽取一个精简摘要（取每个小节标题行 + 后两行）。"""
        if not self.tech:
            return ''
        lines = self.tech.splitlines()
        summary_lines = []
        i = 0
        while i < len(lines):
            s = lines[i].strip()
            # 小节标题形如：【...】 或 数字编号开头
            if s.startswith('【') and s.endswith('】'):
                summary_lines.append(s)
                # 取紧跟其后的 2 行非装饰行
                take = 0
                j = i + 1
                while j < len(lines) and take < 2:
                    sj = lines[j].strip()
                    if sj and not sj.startswith('===') and not sj.startswith('---'):
                        summary_lines.append(sj)
                        take += 1
                    j += 1
                summary_lines.append('')
            i += 1
        result = '\n'.join(summary_lines).strip()
        return result or self._strip_decor(self.tech)[:500]

    # ==================== 便捷 ====================
    def is_loaded(self):
        return self._loaded

    def scene_count(self):
        return len(self.scenes)

    # ==================== 反馈闭环集成 ====================
    def refresh(self):
        """重新加载知识库（扫描新的日志/场景数据）"""
        return self.load()

    def add_positive_example(self, query: str, response: str, category: str = "auto_learned"):
        """将高质量交互作为正例加入知识库

        Args:
            query: 用户输入
            response: 高质量回复
            category: 场景分类标签

        Returns:
            True 表示添加成功
        """
        scene = category
        phrase = query.strip()
        reply = response.strip()
        if not phrase or not reply:
            return False
        self.scenes.append((scene, phrase, reply))
        # 持久化到场景文件
        try:
            path = os.path.join(self.knowledge_dir, 'chat_scenarios.txt')
            os.makedirs(self.knowledge_dir, exist_ok=True)
            with open(path, 'a', encoding='utf-8') as f:
                f.write(f"\n{scene}|{phrase}|{reply}")
        except OSError:
            pass
        return True

    def get_stats(self) -> Dict:
        """获取知识库统计信息"""
        return {
            "scene_count": len(self.scenes),
            "loaded": self._loaded,
            "has_guide": bool(self.guide),
            "has_personality": bool(self.personality),
            "has_tech": bool(self.tech),
            "guide_length": len(self.guide),
            "personality_length": len(self.personality),
            "tech_length": len(self.tech),
        }


# ================================================================
# TF-IDF 向量检索器（v2.0 新增）
# ================================================================

class TFIDFVectorizer:
    """轻量级 TF-IDF 向量化器 — 无需外部依赖"""
    
    def __init__(self):
        self._idf: Dict[str, float] = {}
        self._documents: List[str] = []
        self._vocabulary: Dict[str, int] = {}
        self._tokenized_docs: List[Dict[str, int]] = []
    
    def _tokenize(self, text: str) -> List[str]:
        """中文 + 英文分词（简单切分）"""
        tokens = []
        # 提取中文字符
        for ch in text:
            if '\u4e00' <= ch <= '\u9fff' or '\u3400' <= ch <= '\u4dbf':
                tokens.append(ch)
        
        # 提取英文单词
        words = re.findall(r'[a-zA-Z]+', text.lower())
        tokens.extend(words)
        
        # 提取数字
        numbers = re.findall(r'\d+', text)
        tokens.extend(numbers)
        
        # 双字词（中文bigram）
        chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
        for i in range(len(chinese_chars) - 1):
            tokens.append(chinese_chars[i] + chinese_chars[i+1])
        
        return tokens
    
    def fit(self, documents: List[str]):
        """训练 TF-IDF 模型"""
        self._documents = documents
        doc_count = len(documents)
        df = defaultdict(int)  # document frequency
        
        self._tokenized_docs = []
        for doc in documents:
            tokens = self._tokenize(doc)
            tf = defaultdict(int)
            for token in tokens:
                tf[token] += 1
            self._tokenized_docs.append(dict(tf))
            for token in set(tokens):
                df[token] += 1
        
        # 构建词汇表
        self._vocabulary = {token: idx for idx, token in enumerate(sorted(df.keys()))}
        
        # 计算 IDF
        self._idf = {}
        for token, freq in df.items():
            self._idf[token] = math.log((doc_count + 1) / (freq + 1)) + 1
    
    def transform(self, text: str) -> Dict[str, float]:
        """将文本转换为 TF-IDF 向量（稀疏表示）"""
        tokens = self._tokenize(text)
        tf = defaultdict(int)
        for token in tokens:
            tf[token] += 1
        
        tfidf = {}
        for token, count in tf.items():
            if token in self._idf:
                tfidf[token] = (count / max(len(tokens), 1)) * self._idf[token]
        
        return tfidf
    
    def cosine_similarity(self, vec1: Dict[str, float], vec2: Dict[str, float]) -> float:
        """计算两个稀疏向量的余弦相似度"""
        dot_product = 0
        for token, val1 in vec1.items():
            val2 = vec2.get(token, 0)
            dot_product += val1 * val2
        
        norm1 = math.sqrt(sum(v * v for v in vec1.values()))
        norm2 = math.sqrt(sum(v * v for v in vec2.values()))
        
        if norm1 == 0 or norm2 == 0:
            return 0
        
        return dot_product / (norm1 * norm2)
    
    def search(self, query: str, top_k: int = 5) -> List[Tuple[int, float, str]]:
        """搜索最相似的文档，返回 [(index, score, document), ...]"""
        query_vec = self.transform(query)
        
        scores = []
        for i, doc_tf in enumerate(self._tokenized_docs):
            doc_vec = {token: (count / max(len(doc_tf), 1)) * self._idf.get(token, 1)
                       for token, count in doc_tf.items()}
            score = self.cosine_similarity(query_vec, doc_vec)
            if score > 0:
                scores.append((i, score, self._documents[i]))
        
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


# ================================================================
# 会话记忆管理器（v2.0 新增）
# ================================================================

class SessionMemory:
    """
    跨会话记忆管理器
    
    功能：
    - 项目级记忆：记录项目相关的关键决策和约定
    - 会话摘要：保存每次会话的关键信息
    - 记忆持久化：JSON 文件存储，重启不丢失
    - 向量检索：快速查找相关历史记忆
    """
    
    def __init__(self, memory_dir: str = ""):
        if not memory_dir:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            memory_dir = os.path.join(base, "data", "memory")
        self._memory_dir = memory_dir
        self._memory_file = os.path.join(memory_dir, "project_memory.json")
        self._sessions_file = os.path.join(memory_dir, "sessions_memory.json")
        self._vectorizer = TFIDFVectorizer()
        
        self._project_memories: List[Dict] = []  # 项目级记忆
        self._session_summaries: List[Dict] = []  # 会话摘要
        self._loaded = False
        self._load()
    
    def _ensure_dir(self):
        """确保记忆目录存在"""
        os.makedirs(self._memory_dir, exist_ok=True)
    
    def _load(self):
        """加载持久化的记忆"""
        self._ensure_dir()
        
        try:
            if os.path.isfile(self._memory_file):
                with open(self._memory_file, 'r', encoding='utf-8') as f:
                    self._project_memories = json.load(f)
        except (json.JSONDecodeError, OSError):
            self._project_memories = []
        
        try:
            if os.path.isfile(self._sessions_file):
                with open(self._sessions_file, 'r', encoding='utf-8') as f:
                    self._session_summaries = json.load(f)
        except (json.JSONDecodeError, OSError):
            self._session_summaries = []
        
        # 重建向量索引
        self._rebuild_index()
        self._loaded = True
    
    def _save(self):
        """持久化记忆到文件"""
        self._ensure_dir()
        
        try:
            with open(self._memory_file, 'w', encoding='utf-8') as f:
                json.dump(self._project_memories, f, ensure_ascii=False, indent=2)
        except OSError:
            pass
        
        try:
            with open(self._sessions_file, 'w', encoding='utf-8') as f:
                json.dump(self._session_summaries, f, ensure_ascii=False, indent=2)
        except OSError:
            pass
    
    def _rebuild_index(self):
        """重建 TF-IDF 向量索引"""
        all_texts = []
        for mem in self._project_memories:
            all_texts.append(mem.get("content", ""))
        for sess in self._session_summaries:
            all_texts.append(sess.get("summary", ""))
        
        if all_texts:
            self._vectorizer.fit(all_texts)
    
    # ================================================================
    # 项目记忆
    # ================================================================
    
    def add_project_memory(self, content: str, category: str = "general", 
                           tags: List[str] = None):
        """添加项目级记忆"""
        memory = {
            "id": str(int(time.time() * 1000)),
            "content": content,
            "category": category,
            "tags": tags or [],
            "created_at": time.time(),
        }
        self._project_memories.append(memory)
        self._rebuild_index()
        self._save()
        return memory["id"]
    
    def get_project_memories(self, category: str = "", limit: int = 20) -> List[Dict]:
        """获取项目记忆"""
        if category:
            return [m for m in self._project_memories if m.get("category") == category][-limit:]
        return self._project_memories[-limit:]
    
    def search_project_memories(self, query: str, top_k: int = 5) -> List[Dict]:
        """向量检索项目记忆"""
        all_texts = [m.get("content", "") for m in self._project_memories]
        if not all_texts:
            return []
        
        self._vectorizer.fit(all_texts)
        results = self._vectorizer.search(query, top_k)
        
        return [
            {**self._project_memories[idx], "score": round(score, 3)}
            for idx, score, _ in results
        ]
    
    def clear_project_memories(self):
        """清除所有项目记忆"""
        self._project_memories = []
        self._rebuild_index()
        self._save()
    
    # ================================================================
    # 会话记忆
    # ================================================================
    
    def save_session_summary(self, session_id: str, summary: str, 
                             key_topics: List[str] = None):
        """保存会话摘要"""
        # 更新或添加
        for sess in self._session_summaries:
            if sess.get("session_id") == session_id:
                sess["summary"] = summary
                sess["key_topics"] = key_topics or []
                sess["updated_at"] = time.time()
                self._rebuild_index()
                self._save()
                return
        
        self._session_summaries.append({
            "session_id": session_id,
            "summary": summary,
            "key_topics": key_topics or [],
            "created_at": time.time(),
            "updated_at": time.time(),
        })
        self._rebuild_index()
        self._save()
    
    def get_session_summaries(self, limit: int = 10) -> List[Dict]:
        """获取最近的会话摘要"""
        sorted_sessions = sorted(
            self._session_summaries,
            key=lambda s: s.get("updated_at", 0),
            reverse=True
        )
        return sorted_sessions[:limit]
    
    def search_sessions(self, query: str, top_k: int = 5) -> List[Dict]:
        """向量检索会话记忆"""
        session_texts = [s.get("summary", "") for s in self._session_summaries]
        if not session_texts:
            return []
        
        vec = TFIDFVectorizer()
        vec.fit(session_texts)
        results = vec.search(query, top_k)
        
        return [
            {**self._session_summaries[idx], "score": round(score, 3)}
            for idx, score, _ in results
        ]
    
    def build_context_from_memory(self, query: str, max_items: int = 3) -> str:
        """从记忆构建上下文（用于注入到 AI 对话中）"""
        # 搜索项目记忆
        project_hits = self.search_project_memories(query, top_k=2)
        # 搜索会话记忆
        session_hits = self.search_sessions(query, top_k=2)
        
        lines = []
        
        if project_hits:
            lines.append("【项目记忆 — 相关历史决策】")
            for hit in project_hits:
                lines.append(f"- [{hit.get('category', 'general')}] {hit['content'][:200]}")
            lines.append("")
        
        if session_hits:
            lines.append("【会话记忆 — 相关历史对话】")
            for hit in session_hits:
                lines.append(f"- {hit['summary'][:200]}")
            lines.append("")
        
        return "\n".join(lines) if lines else ""
    
    # ================================================================
    # 摘要
    # ================================================================
    
    def get_summary(self) -> Dict:
        """获取记忆系统摘要"""
        return {
            "project_memories": len(self._project_memories),
            "session_summaries": len(self._session_summaries),
            "categories": list(set(m.get("category", "general") for m in self._project_memories)),
            "recent_sessions": len(self.get_session_summaries(5)),
            "loaded": self._loaded,
        }


# ================================================================
# 全局单例
# ================================================================
_kb_instance = None


def get_knowledge_base() -> "KnowledgeBase":
    """获取 KnowledgeBase 全局单例（懒加载）"""
    global _kb_instance
    if _kb_instance is None:
        _kb_instance = KnowledgeBase()
        _kb_instance.load()
    return _kb_instance


if __name__ == '__main__':
    # 简单自测
    kb = KnowledgeBase()
    kb.load()
    print(f'场景数: {kb.scene_count()}')
    print(f'指导长度: {len(kb.guide)} 字')
    print(f'性格长度: {len(kb.personality)} 字')
    print(f'技术长度: {len(kb.tech)} 字')
    print('-' * 40)
    for q in ['早', '好累', '怎么用', '写bug了', '几点了', '你是谁', '讲个笑话']:
        reply = kb.find_scene_reply(q)
        print(f'用户: {q}  ->  柠檬小助手: {reply}')
    print('-' * 40)
    print('系统提示词前 200 字:')
    print(kb.build_system_prompt()[:200])
    print('-' * 40)
    print('上下文（"好累"）:')
    print(kb.build_context('好累'))
