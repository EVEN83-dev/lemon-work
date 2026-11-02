# -*- coding: utf-8 -*-
"""
Feedback Loop — P12 蒸馏 Step 7
=================================
自动收集反馈 + 优化知识库的闭环系统。

功能：
1. 自动质量评分 — 基于多项指标自动评估回复质量
2. 反馈收集 — 用户评分/反馈自动关联到交互记录
3. 知识库优化 — 高质量回复自动纳入 KnowledgeBase
4. 模式学习 — 从成功/失败案例中提取模式
5. 退化检测 — 检测模型输出质量下降趋势

闭环流程：
  用户交互 → 自动评分 → 收集反馈 → 筛选高质量 → 更新知识库
                                                ↓
                                         检测退化 → 触发告警
"""

import time
import threading
import logging
from typing import Optional, Dict, Any, List, Tuple, Callable  # ★ v5.8: 补 Callable（L519/524/528 使用却未导入 → NameError）
from datetime import datetime
from collections import deque

from .interaction_logger import get_interaction_logger
from shared.knowledge_base import get_knowledge_base
from .response_validator import ResponseValidator, ValidationLevel, get_response_validator

logger = logging.getLogger(__name__)


class FeedbackLoop:
    """
    反馈闭环系统
    
    使用方式：
        loop = FeedbackLoop()
        loop.process_interaction(prompt, response, engine, model)
        loop.add_user_feedback(record_id, rating=5)
    """
    
    # 自动评分权重
    SCORE_WEIGHTS = {
        "length": 0.15,       # 回复长度适当性
        "completeness": 0.20,  # 完整性（是否截断/空）
        "format": 0.15,        # 格式正确性（代码块等）
        "relevance": 0.25,     # 相关性（是否回答用户问题）
        "quality": 0.25,       # 内容质量（无幻觉/重复）
    }
    
    # 高质量阈值
    HIGH_QUALITY_THRESHOLD = 0.7
    
    # 退化检测窗口
    DEGRADATION_WINDOW = 20  # 最近 N 次交互
    
    def __init__(self):
        self._logger = get_interaction_logger()
        self._kb = get_knowledge_base()
        self._validator = get_response_validator()
        
        self._lock = threading.Lock()
        
        # 质量追踪
        self._recent_scores = deque(maxlen=self.DEGRADATION_WINDOW)
        self._degradation_alerts = 0
        
        # 统计
        self._stats = {
            'total_processed': 0,
            'auto_scored': 0,
            'user_feedback_received': 0,
            'kb_updates': 0,
            'high_quality_count': 0,
            'degradation_detected': 0,
            'low_quality_logged': 0,
        }

        # 低质量记录（用于改进分析）
        self._improvement_log: List[Dict[str, Any]] = []
    
    def process_interaction(self,
                            prompt: str,
                            response: str,
                            engine: str,
                            model: str,
                            session_id: str = "default",
                            mode: str = "build") -> Dict:
        """
        处理一次交互的完整闭环
        
        Args:
            prompt: 用户输入
            response: AI 回复
            engine: 使用的引擎
            model: 使用的模型
            session_id: 会话 ID
            mode: 模式
        
        Returns:
            {
                "record_id": str,
                "auto_score": float,
                "quality_level": str,
                "issues": [...],
                "kb_updated": bool,
            }
        """
        self._stats['total_processed'] += 1
        
        result = {
            "record_id": "",
            "auto_score": 0.0,
            "quality_level": "unknown",
            "issues": [],
            "kb_updated": False,
        }
        
        with self._lock:
            # 1. 自动评分
            auto_score, issues = self._auto_score(prompt, response)
            self._stats['auto_scored'] += 1
            self._recent_scores.append(auto_score)
            
            result["auto_score"] = auto_score
            result["issues"] = issues
            
            if auto_score >= 0.8:
                result["quality_level"] = "excellent"
            elif auto_score >= self.HIGH_QUALITY_THRESHOLD:
                result["quality_level"] = "good"
            elif auto_score >= 0.4:
                result["quality_level"] = "fair"
            else:
                result["quality_level"] = "poor"
            
            # 2. 记录交互
            record_id = self._logger.log_interaction(
                session_id=session_id,
                prompt=prompt,
                response=response,
                engine=engine,
                model=model,
                mode=mode,
            )
            result["record_id"] = record_id
            
            # 3. 高质量内容自动纳入知识库
            if auto_score >= self.HIGH_QUALITY_THRESHOLD:
                self._kb.refresh()  # 刷新知识库（新日志会被加载）
                self._stats['kb_updates'] += 1
                self._stats['high_quality_count'] += 1
                result["kb_updated"] = True
            
            # 4. 退化检测
            if self._detect_degradation():
                self._degradation_alerts += 1
                self._stats['degradation_detected'] += 1
                logger.warning(
                    f"[FeedbackLoop] 检测到质量退化! "
                    f"最近 {self.DEGRADATION_WINDOW} 次交互平均分: "
                    f"{self._get_avg_score():.2f}"
                )
        
        return result
    
    def add_user_feedback(self,
                          record_id: str,
                          rating: Optional[int] = None,
                          feedback: Optional[str] = None,
                          was_helpful: Optional[bool] = None):
        """
        添加用户反馈
        
        Args:
            record_id: 交互记录 ID
            rating: 评分 (1-5)
            feedback: 反馈文本
            was_helpful: 是否有帮助
        """
        self._stats['user_feedback_received'] += 1
        
        self._logger.add_feedback(
            record_id=record_id,
            rating=rating,
            feedback=feedback,
            was_helpful=was_helpful,
        )
        
        # 高评分反馈 → 刷新知识库
        if rating and rating >= 4:
            self._kb.refresh()
            self._stats['kb_updates'] += 1
    
    def submit_and_learn(self,
                         query: str,
                         response: str,
                         rating: float = None,
                         user_feedback: str = None) -> Dict:
        """
        提交交互并自动学习：评分 → 纳入知识库或记录改进

        Args:
            query: 用户输入
            response: AI 回复
            rating: 可选的外部评分 (0.0-1.0)，不提供则自动评分
            user_feedback: 可选的用户反馈文本

        Returns:
            {
                "score": float,          # 最终评分
                "action": str,           # "added_to_kb" | "logged_for_improvement"
                "quality_level": str,    # "excellent" | "good" | "fair" | "poor"
            }
        """
        self._stats['total_processed'] += 1

        with self._lock:
            # 1. 确定评分
            if rating is not None:
                score = max(0.0, min(1.0, float(rating)))
                issues = []
            else:
                score, issues = self._auto_score(query, response)
                self._stats['auto_scored'] += 1

            self._recent_scores.append(score)

            # 2. 判定质量等级
            if score >= 0.8:
                quality_level = "excellent"
            elif score >= self.HIGH_QUALITY_THRESHOLD:
                quality_level = "good"
            elif score >= 0.4:
                quality_level = "fair"
            else:
                quality_level = "poor"

            # 3. 根据阈值决定动作
            if score >= self.HIGH_QUALITY_THRESHOLD:
                added = self._kb.add_positive_example(query, response)
                if added:
                    self._stats['kb_updates'] += 1
                    self._stats['high_quality_count'] += 1
                action = "added_to_kb"
            else:
                self._improvement_log.append({
                    "query": query,
                    "response": response,
                    "score": score,
                    "issues": issues,
                    "user_feedback": user_feedback,
                    "timestamp": datetime.now().isoformat(),
                })
                self._stats['low_quality_logged'] += 1
                action = "logged_for_improvement"
                logger.info(
                    f"[FeedbackLoop] 低质量回复已记录 (score={score:.2f}): "
                    f"query={query[:50]}... issues={issues}"
                )

            # 4. 退化检测
            if self._detect_degradation():
                self._degradation_alerts += 1
                self._stats['degradation_detected'] += 1
                logger.warning(
                    f"[FeedbackLoop] 检测到质量退化! "
                    f"最近 {self.DEGRADATION_WINDOW} 次交互平均分: "
                    f"{self._get_avg_score():.2f}"
                )

        return {
            "score": round(score, 3),
            "action": action,
            "quality_level": quality_level,
        }
    
    def _auto_score(self, prompt: str, response: str) -> Tuple[float, List[str]]:
        """
        自动评分
        
        评分维度：
        1. 长度适当性 (15%)
        2. 完整性 (20%)
        3. 格式正确性 (15%)
        4. 相关性 (25%)
        5. 内容质量 (25%)
        """
        scores = {}
        issues = []
        
        # 1. 长度评分
        resp_len = len(response)
        if resp_len < 10:
            scores["length"] = 0.0
            issues.append("回复过短")
        elif resp_len < 50:
            scores["length"] = 0.4
        elif resp_len < 200:
            scores["length"] = 0.7
        elif resp_len < 2000:
            scores["length"] = 1.0
        else:
            scores["length"] = 0.8  # 过长可能冗长
            issues.append("回复过长")
        
        # 2. 完整性评分
        validation = self._validator.validate(response, prompt)
        if validation.level == ValidationLevel.PASS:
            scores["completeness"] = 1.0
        elif validation.level == ValidationLevel.WARN:
            scores["completeness"] = 0.7
            issues.extend(validation.issues)
        elif validation.level == ValidationLevel.RETRY:
            scores["completeness"] = 0.3
            issues.extend(validation.issues)
        else:
            scores["completeness"] = 0.1
            issues.extend(validation.issues)
        
        # 3. 格式评分
        scores["format"] = 0.7 if validation.score >= 0.7 else validation.score
        
        # 4. 相关性评分（基于关键词重叠）
        import re
        prompt_words = set(re.findall(r'[\w\u4e00-\u9fff]{2,}', prompt.lower()))
        response_words = set(re.findall(r'[\w\u4e00-\u9fff]{2,}', response.lower()))
        if prompt_words:
            overlap = prompt_words & response_words
            scores["relevance"] = min(1.0, len(overlap) / max(len(prompt_words) * 0.3, 1))
        else:
            scores["relevance"] = 0.5
        
        # 5. 内容质量评分
        scores["quality"] = validation.score
        
        # 加权计算
        total_score = sum(
            scores.get(k, 0) * self.SCORE_WEIGHTS.get(k, 0)
            for k in self.SCORE_WEIGHTS
        )
        
        return round(total_score, 3), issues[:5]
    
    def _detect_degradation(self) -> bool:
        """检测质量退化趋势"""
        if len(self._recent_scores) < self.DEGRADATION_WINDOW:
            return False
        
        avg = self._get_avg_score()
        return avg < 0.4  # 平均分低于 0.4 视为退化
    
    def _get_avg_score(self) -> float:
        """获取最近交互的平均分"""
        if not self._recent_scores:
            return 0.0
        return sum(self._recent_scores) / len(self._recent_scores)
    
    def get_quality_report(self) -> Dict:
        """获取质量报告：响应质量统计、知识库状态、改进记录"""
        scores = list(self._recent_scores)
        high_q = sum(1 for s in scores if s >= self.HIGH_QUALITY_THRESHOLD)
        low_q = sum(1 for s in scores if s < 0.4)

        return {
            "avg_score": round(self._get_avg_score(), 3),
            "min_score": round(min(scores), 3) if scores else 0.0,
            "max_score": round(max(scores), 3) if scores else 0.0,
            "high_quality_ratio": round(high_q / len(scores), 3) if scores else 0.0,
            "low_quality_ratio": round(low_q / len(scores), 3) if scores else 0.0,
            "recent_count": len(scores),
            "degradation_alerts": self._degradation_alerts,
            "improvement_log_size": len(self._improvement_log),
            "stats": dict(self._stats),
            "kb_stats": self._kb.get_stats(),
        }
    
    @property
    def stats(self) -> Dict:
        return dict(self._stats)

    # ============================================================
    # UI 信号集成
    # ============================================================

    def connect_ui_signals(self, signal_bridge: 'UISignalBridge' = None):
        """
        连接 UI 信号桥接器

        将 FeedbackLoop 的内部事件转换为 UI 可消费的信号：
        - quality_score_updated: 质量评分更新
        - degradation_alert: 退化告警
        - kb_updated: 知识库更新
        - improvement_suggested: 改进建议

        Args:
            signal_bridge: UISignalBridge 实例，若为 None 则创建默认实例
        """
        if signal_bridge is None:
            signal_bridge = UISignalBridge()
        self._ui_bridge = signal_bridge
        return signal_bridge

    def process_interaction_with_ui(self,
                                    prompt: str,
                                    response: str,
                                    engine: str,
                                    model: str,
                                    session_id: str = "default",
                                    mode: str = "build") -> Dict:
        """
        处理交互并通过 UI 信号桥接器发送通知

        与 process_interaction 相同，但额外发送 UI 信号：
        1. 质量评分更新信号
        2. 低质量告警信号
        3. 退化检测信号
        4. 知识库更新信号
        """
        result = self.process_interaction(prompt, response, engine, model, session_id, mode)

        bridge = getattr(self, '_ui_bridge', None)
        if bridge:
            # 质量评分更新
            bridge.emit('quality_score_updated', {
                'record_id': result.get('record_id'),
                'auto_score': result.get('auto_score', 0),
                'quality_level': result.get('quality_level', 'unknown'),
                'issues': result.get('issues', []),
            })

            # 低质量告警
            if result.get('auto_score', 0) < 0.4:
                bridge.emit('degradation_alert', {
                    'record_id': result.get('record_id'),
                    'score': result.get('auto_score', 0),
                    'quality_level': result.get('quality_level', 'poor'),
                    'issues': result.get('issues', []),
                    'suggestion': '建议检查模型配置或切换引擎',
                })

            # 知识库更新通知
            if result.get('kb_updated'):
                bridge.emit('kb_updated', {
                    'record_id': result.get('record_id'),
                    'quality_level': result.get('quality_level'),
                })

        return result

    def get_ui_signal_history(self, limit: int = 50) -> List[Dict]:
        """获取 UI 信号历史（用于 UI 调试和回放）"""
        bridge = getattr(self, '_ui_bridge', None)
        if bridge:
            return bridge.get_history(limit)
        return []

    def get_quality_dashboard_data(self) -> Dict:
        """
        获取质量仪表盘数据（供 UI 渲染）

        Returns:
            {
                "current_score": float,
                "quality_level": str,
                "score_trend": List[float],  # 最近 N 次评分
                "stats": Dict,
                "degradation_alerts": int,
                "improvement_suggestions": List[str],
            }
        """
        report = self.get_quality_report()
        recent_scores = list(self._recent_scores)

        # 从改进记录提取建议
        suggestions = []
        for item in self._improvement_log[-5:]:
            if item.get("issues"):
                suggestions.extend(item["issues"][:2])

        return {
            "current_score": report.get("avg_score", 0),
            "quality_level": "excellent" if report.get("avg_score", 0) >= 0.8
                              else "good" if report.get("avg_score", 0) >= 0.7
                              else "fair" if report.get("avg_score", 0) >= 0.4
                              else "poor",
            "score_trend": recent_scores[-20:],
            "stats": report.get("stats", {}),
            "degradation_alerts": report.get("degradation_alerts", 0),
            "improvement_suggestions": suggestions[:5],
            "high_quality_ratio": report.get("high_quality_ratio", 0),
            "low_quality_ratio": report.get("low_quality_ratio", 0),
        }


# ============================================================
# UI 信号桥接器
# ============================================================

class UISignalBridge:
    """
    UI 信号桥接器

    将 FeedbackLoop 内部事件转换为 UI 可消费的信号格式。
    支持多种后端：
    - Qt Signal/Slot（通过回调）
    - EventBus（通过事件总线）
    - WebSocket（实时推送）

    使用示例：
        bridge = UISignalBridge()
        bridge.on('quality_score_updated', my_handler)
        bridge.emit('quality_score_updated', {'score': 0.85})
    """

    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = defaultdict(list)
        self._history: List[Dict] = []
        self._history_lock = threading.Lock()
        self._max_history = 200

    def on(self, signal_name: str, handler: Callable):
        """注册信号处理器"""
        self._handlers[signal_name].append(handler)

    def off(self, signal_name: str, handler: Callable = None):
        """取消信号处理器"""
        if handler:
            self._handlers[signal_name] = [
                h for h in self._handlers.get(signal_name, []) if h != handler
            ]
        else:
            self._handlers.pop(signal_name, None)

    def emit(self, signal_name: str, data: Any = None):
        """发射信号"""
        event = {
            "signal": signal_name,
            "data": data,
            "timestamp": time.time(),
        }

        # 记录历史
        with self._history_lock:
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

        # 调用处理器
        for handler in self._handlers.get(signal_name, []):
            try:
                handler(data)
            except Exception as e:
                logger.debug(f"UISignalBridge handler error ({signal_name}): {e}")

    def get_history(self, limit: int = 50) -> List[Dict]:
        """获取信号历史"""
        with self._history_lock:
            return list(self._history[-limit:])

    def clear_history(self):
        """清除信号历史"""
        with self._history_lock:
            self._history.clear()


# 全局单例
_loop_instance: Optional[FeedbackLoop] = None
_loop_lock = threading.Lock()


def get_feedback_loop() -> FeedbackLoop:
    global _loop_instance
    if _loop_instance is None:
        with _loop_lock:
            if _loop_instance is None:
                _loop_instance = FeedbackLoop()
    return _loop_instance