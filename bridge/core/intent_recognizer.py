from __future__ import annotations

import hashlib
import json
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Lock
from typing import Callable, List, Optional


@dataclass
class IntentResult:
    is_agent_related: bool
    domain: str
    intent: str
    keywords: List[str]
    skill_suggestions: List[dict]
    fallback_used: bool
    latency_ms: float


DOMAINS = [
    "programming",
    "finance",
    "research",
    "creative",
    "office",
    "system",
    "communication",
    "general",
]

DOMAIN_PATTERNS: dict[str, list[str]] = {
    "programming": [
        "代码", "编程", "python", "debug", "函数", "java", "javascript", "typescript",
        "api", "bug", "编译", "compile", "部署", "deploy", "git", "refactor",
        "重构", "算法", "algorithm", "数据库", "database", "sql", "后端", "前端",
        "backend", "frontend", "框架", "framework", "库", "library", "测试", "test",
        "unit test", "ci", "cd", "docker", "kubernetes", "运维", "devops",
    ],
    "finance": [
        "股票", "行情", "K线", "财报", "基金", "利率", "汇率", "期货", "期权",
        "债券", "收益", "投资", "理财", "证券", "金融", "估值", "市值", "涨跌",
        "portfolio", "stock", "bond", "dividend", "option", "futures", "trading",
    ],
    "research": [
        "论文", "研究", "实验", "文献", "学术", "期刊", "引用", "数据分析",
        "统计", "hypothesis", "research", "paper", "study", "survey", "analysis",
        "方法论", "methodology", "综述", "review", "arxiv", "doi",
    ],
    "creative": [
        "写作", "故事", "小说", "诗歌", "剧本", "文案", "创意", "设计",
        "绘画", "音乐", "视频", "创作", "writing", "story", "novel", "poem",
        "creative", "design", "art", "song", "compose", "illustration",
    ],
    "office": [
        "文档", "表格", "ppt", "excel", "word", "幻灯片", "报告", "会议",
        "日程", "邮件", "备忘录", "document", "spreadsheet", "presentation",
        "report", "meeting", "schedule", "email", "memo", "summary", "总结",
        "归纳", "整理",
    ],
    "system": [
        "文件", "目录", "进程", "服务", "配置", "安装", "卸载", "权限",
        "网络", "防火墙", "系统", "终端", "命令行", "shell", "terminal",
        "file", "directory", "process", "service", "config", "install",
        "permission", "network", "system", "cron", "task", "定时任务",
    ],
    "communication": [
        "聊天", "消息", "通知", "提醒", "通讯录", "群组", "频道", "推送",
        "chat", "message", "notification", "reminder", "contact", "group",
        "channel", "push", "短信", "email", "邮件", "转发", "回复",
    ],
    "general": [],
}

INTENT_VOCAB: dict[str, dict[str, list[str]]] = {
    "programming": {
        "code_write": ["写", "实现", "创建", "编写", "write", "create", "implement", "开发"],
        "code_review": ["审查", "review", "检查", "优化", "review", "check", "优化代码"],
        "code_debug": ["调试", "debug", "修复", "fix", "排错", "报错", "错误"],
        "code_explain": ["解释", "explain", "理解", "说明", "什么意思"],
        "code_refactor": ["重构", "refactor", "改进", "重写", "rewrite"],
        "code_test": ["测试", "test", "单元测试", "unit test", "覆盖率"],
    },
    "finance": {
        "market_query": ["行情", "查询", "走势", "价格", "涨跌", "quote"],
        "financial_analysis": ["分析", "财报", "估值", "指标", "分析"],
        "portfolio_advice": ["建议", "投资", "配置", "组合", "portfolio"],
        "risk_assessment": ["风险", "评估", "风控", "risk"],
    },
    "research": {
        "paper_search": ["查找", "搜索", "论文", "文献", "search", "find"],
        "data_analysis": ["分析", "数据", "统计", "analysis", "statistics"],
        "literature_review": ["综述", "回顾", "总结", "review", "survey"],
        "experiment_design": ["设计", "实验", "方案", "design", "experiment"],
    },
    "creative": {
        "creative_write": ["写", "创作", "写作", "write", "compose"],
        "brainstorm": ["头脑风暴", "创意", "想法", "brainstorm", "idea"],
        "style_transfer": ["风格", "改写", "模仿", "style", "rewrite"],
        "content_polish": ["润色", "修改", "优化", "polish", "refine"],
    },
    "office": {
        "file_edit": ["编辑", "修改", "整理", "edit", "modify"],
        "document_generate": ["生成", "创建", "写", "generate", "create"],
        "data_summary": ["汇总", "统计", "总结", "summary", "aggregate"],
        "schedule_manage": ["日程", "安排", "计划", "schedule", "plan"],
    },
    "system": {
        "file_edit": ["编辑", "修改", "文件", "edit", "file", "modify"],
        "file_search": ["查找", "搜索", "find", "search", "locate"],
        "process_manage": ["进程", "服务", "启动", "停止", "process", "service"],
        "system_config": ["配置", "设置", "config", "setting", "configure"],
    },
    "communication": {
        "send_message": ["发送", "发", "通知", "send", "notify", "push"],
        "schedule_meeting": ["会议", "预约", "安排", "meeting", "schedule"],
        "contact_manage": ["联系人", "通讯录", "contact"],
    },
    "general": {
        "general_qa": ["什么", "为什么", "怎么", "如何", "what", "why", "how"],
        "chitchat": ["你好", "谢谢", "早上好", "hello", "hi", "thanks"],
        "weather": ["天气", "气温", "weather", "temperature"],
        "translation": ["翻译", "translate", "英文", "中文"],
    },
}


class DomainClassifier:
    def classify(self, text: str, llm_callback: Callable[[str], str] | None = None) -> str:
        if llm_callback is not None:
            try:
                prompt = (
                    f"Classify the following user input into one of these domains: "
                    f"{', '.join(DOMAINS)}. Return only the domain name.\n\nInput: {text}"
                )
                response = llm_callback(prompt).strip().lower()
                for domain in DOMAINS:
                    if domain in response:
                        return domain
            except Exception:
                pass
        return self._fallback(text)

    def _fallback(self, text: str) -> str:
        text_lower = text.lower()
        best_domain = "general"
        best_score = 0
        for domain, patterns in DOMAIN_PATTERNS.items():
            if domain == "general":
                continue
            score = sum(1 for p in patterns if p.lower() in text_lower)
            if score > best_score:
                best_score = score
                best_domain = domain
        return best_domain


class IntentExtractor:
    def extract(self, text: str, domain: str, llm_callback: Callable[[str], str] | None = None) -> dict:
        if llm_callback is not None:
            try:
                prompt = (
                    f"Given the user input and domain '{domain}', extract the specific intent and keywords. "
                    f'Return JSON: {{"intent": "...", "keywords": [...]}}\n\nInput: {text}'
                )
                response = llm_callback(prompt)
                parsed = json.loads(response)
                if isinstance(parsed, dict) and "intent" in parsed and "keywords" in parsed:
                    return {"intent": str(parsed["intent"]), "keywords": list(parsed["keywords"])}
            except Exception:
                pass
        return self._fallback(text, domain)

    def _fallback(self, text: str, domain: str) -> dict:
        vocab = INTENT_VOCAB.get(domain, INTENT_VOCAB.get("general", {}))
        text_lower = text.lower()
        best_intent = "general_qa"
        best_score = 0
        matched_keywords: list[str] = []

        for intent, keywords in vocab.items():
            score = 0
            for kw in keywords:
                if kw.lower() in text_lower:
                    score += 1
                    if kw not in matched_keywords:
                        matched_keywords.append(kw)
            if score > best_score:
                best_score = score
                best_intent = intent

        if not matched_keywords:
            tokens = re.findall(r"[\w\u4e00-\u9fff]+", text_lower)
            matched_keywords = tokens[:5]

        return {"intent": best_intent, "keywords": matched_keywords}


class SkillMatcher:
    def __init__(self, available_skills: List[dict]) -> None:
        self._skills = available_skills

    def match(self, intent: str, domain: str, keywords: List[str]) -> List[dict]:
        scored: list[tuple[float, dict]] = []
        for skill in self._skills:
            score = 0.0
            if skill.get("category", "").lower() == domain:
                score += 3.0
            skill_kw = [k.lower() for k in skill.get("keywords", [])]
            for kw in keywords:
                if kw.lower() in skill_kw:
                    score += 1.0
            if intent in skill.get("name", "").lower() or intent in skill.get("description", "").lower():
                score += 2.0
            if score > 0:
                max_possible = 3.0 + len(keywords) + 2.0
                confidence = min(score / max_possible, 1.0) if max_possible > 0 else 0.0
                scored.append((confidence, skill))

        scored.sort(key=lambda x: x[0], reverse=True)

        results: list[dict] = []
        for confidence, skill in scored[:5]:
            results.append({
                "skill_id": skill.get("name", ""),
                "confidence": round(confidence, 4),
                "reason": f"domain={domain}, intent={intent}, keyword_overlap",
            })
        return results


class IntentCache:
    def __init__(self, max_size: int = 500) -> None:
        self._max_size = max_size
        self._cache: OrderedDict[str, tuple[float, IntentResult]] = OrderedDict()
        self._lock = Lock()

    def get(self, text_hash: str) -> Optional[IntentResult]:
        with self._lock:
            entry = self._cache.get(text_hash)
            if entry is None:
                return None
            expire_at, result = entry
            if time.time() > expire_at:
                del self._cache[text_hash]
                return None
            self._cache.move_to_end(text_hash)
            return result

    def set(self, text_hash: str, result: IntentResult, ttl: int = 3600) -> None:
        with self._lock:
            if text_hash in self._cache:
                self._cache.move_to_end(text_hash)
            self._cache[text_hash] = (time.time() + ttl, result)
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)


class IntentRecognizer:
    def __init__(self, available_skills: List[dict] | None = None) -> None:
        self._domain_classifier = DomainClassifier()
        self._intent_extractor = IntentExtractor()
        self._skill_matcher = SkillMatcher(available_skills or [])
        self._cache = IntentCache()

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", text.strip().lower())

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _check_relevance(self, text: str, llm_callback: Callable[[str], str] | None, timeout_at: float) -> bool:
        if llm_callback is not None and time.time() < timeout_at:
            try:
                prompt = (
                    'Is this input something an AI assistant can help with? '
                    'Return JSON: {"related": true/false}\n\nInput: ' + text
                )
                response = llm_callback(prompt)
                parsed = json.loads(response)
                if isinstance(parsed, dict) and "related" in parsed:
                    return bool(parsed["related"])
            except Exception:
                pass
        return self._relevance_fallback(text)

    @staticmethod
    def _relevance_fallback(text: str) -> bool:
        if "?" in text or "？" in text:
            return True
        imperative_patterns = [
            r"^(请|帮我|help|can you|could you|would you|please|let|make|create|write|read|show|find|search|tell|explain|分析|解释|写|做|生成|查找|搜索|计算|翻译)",
        ]
        for pat in imperative_patterns:
            if re.search(pat, text, re.IGNORECASE):
                return True
        all_keywords: list[str] = []
        for kws in DOMAIN_PATTERNS.values():
            all_keywords.extend(kws)
        text_lower = text.lower()
        for kw in all_keywords:
            if kw.lower() in text_lower:
                return True
        return False

    def recognize(
        self,
        text: str,
        llm_callback: Callable[[str], str] | None = None,
        timeout: float = 2.0,
    ) -> IntentResult:
        start = time.monotonic()
        fallback_used = False
        timeout_at = time.time() + timeout

        normalized = self._normalize(text)
        cache_key = self._hash(normalized)

        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        is_agent_related = self._check_relevance(text, llm_callback, timeout_at)
        if time.time() >= timeout_at:
            fallback_used = True

        if time.time() < timeout_at and llm_callback is not None:
            domain = self._domain_classifier.classify(text, llm_callback)
        else:
            domain = self._domain_classifier._fallback(text)
            fallback_used = True

        if time.time() < timeout_at and llm_callback is not None:
            extracted = self._intent_extractor.extract(text, domain, llm_callback)
        else:
            extracted = self._intent_extractor._fallback(text, domain)
            fallback_used = True

        intent = extracted.get("intent", "general_qa")
        keywords = extracted.get("keywords", [])

        skill_suggestions = self._skill_matcher.match(intent, domain, keywords)

        elapsed = time.monotonic() - start
        result = IntentResult(
            is_agent_related=is_agent_related,
            domain=domain,
            intent=intent,
            keywords=keywords,
            skill_suggestions=skill_suggestions,
            fallback_used=fallback_used,
            latency_ms=round(elapsed * 1000, 2),
        )

        self._cache.set(cache_key, result)
        return result
