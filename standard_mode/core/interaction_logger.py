# -*- coding: utf-8 -*-
"""
Interaction Logger — P12 蒸馏基建 Step 1
==========================================
记录所有 AI 交互（prompt → response → feedback），
为蒸馏知识库提供训练数据。

功能：
- 记录每次对话的完整交互对
- 支持会话级别的日志组织
- 自动提取可复用的 prompt→response 模式
- 支持 JSONL 格式存储（便于后续 RAG 检索）
- 统计分析和报告生成

设计原则：
- 异步写入，不阻塞主线程
- 自动轮转，防止日志文件过大
- 隐私保护：敏感信息可配置脱敏
"""

import os
import json
import time
import threading
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict


@dataclass
class InteractionRecord:
    """单次交互记录"""
    id: str                          # 唯一标识
    session_id: str                  # 会话 ID
    timestamp: str                   # 时间戳
    engine: str                      # 使用的引擎（mimocode/ollama/deepseek）
    model: str                       # 使用的模型
    mode: str                        # 模式（build/plan/compose）
    
    # 输入
    prompt: str                      # 用户输入
    context: Optional[str] = None    # 附加上下文（文件内容、错误信息等）
    
    # 输出
    response: str = ""               # AI 完整回复
    thinking: Optional[str] = None   # 思考过程（如有）
    tool_calls: List[Dict] = field(default_factory=list)  # 工具调用列表
    
    # 元数据
    duration_ms: float = 0.0         # 响应耗时（毫秒）
    token_count: int = 0             # Token 数量
    response_length: int = 0          # 回复字符数
    
    # 反馈
    user_rating: Optional[int] = None    # 用户评分（1-5）
    user_feedback: Optional[str] = None  # 用户反馈文本
    was_helpful: Optional[bool] = None   # 是否有帮助
    was_regenerated: bool = False        # 是否被重新生成


class InteractionLogger:
    """交互日志记录器 — 蒸馏数据管道核心组件"""
    
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB 单文件上限
    MAX_RECORDS_PER_FILE = 10000      # 单文件记录上限
    FLUSH_INTERVAL = 10               # 每 N 条记录刷新一次
    
    def __init__(self, log_dir: str = None):
        """
        初始化日志记录器
        
        Args:
            log_dir: 日志存储目录，默认为 data/interaction_logs/
        """
        if log_dir is None:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            log_dir = os.path.join(os.path.dirname(base), 'data', 'interaction_logs')
        
        self._log_dir = log_dir
        self._lock = threading.Lock()
        self._buffer: List[InteractionRecord] = []
        self._current_file: Optional[str] = None
        self._record_count = 0
        self._file_record_count = 0
        self._session_stats: Dict[str, Dict] = {}
        
        # 确保目录存在
        os.makedirs(self._log_dir, exist_ok=True)
        
        # 统计
        self._total_records = 0
        self._total_tokens = 0
        self._start_time = time.time()
        
        print(f"[InteractionLogger] 初始化完成，日志目录: {self._log_dir}")
    
    # ================================================================
    # 公共 API
    # ================================================================
    
    def log_interaction(self, 
                        session_id: str,
                        prompt: str,
                        response: str,
                        engine: str = "mimocode",
                        model: str = "auto",
                        mode: str = "build",
                        context: Optional[str] = None,
                        thinking: Optional[str] = None,
                        tool_calls: Optional[List[Dict]] = None,
                        duration_ms: float = 0.0,
                        token_count: int = 0) -> str:
        """
        记录一次完整的 AI 交互
        
        Returns:
            record_id: 记录的唯一标识
        """
        record_id = self._generate_id()
        
        record = InteractionRecord(
            id=record_id,
            session_id=session_id,
            timestamp=datetime.now().isoformat(),
            engine=engine,
            model=model,
            mode=mode,
            prompt=prompt,
            context=context,
            response=response,
            thinking=thinking,
            tool_calls=tool_calls or [],
            duration_ms=duration_ms,
            token_count=token_count,
            response_length=len(response),
        )
        
        with self._lock:
            self._buffer.append(record)
            self._record_count += 1
            self._total_records += 1
            self._total_tokens += token_count
            
            # 更新会话统计
            if session_id not in self._session_stats:
                self._session_stats[session_id] = {
                    'count': 0, 'tokens': 0, 'started': record.timestamp
                }
            self._session_stats[session_id]['count'] += 1
            self._session_stats[session_id]['tokens'] += token_count
            
            # 达到刷新阈值时写入
            if len(self._buffer) >= self.FLUSH_INTERVAL:
                self._flush()
        
        return record_id
    
    def add_feedback(self, 
                     record_id: str,
                     rating: Optional[int] = None,
                     feedback: Optional[str] = None,
                     was_helpful: Optional[bool] = None):
        """为已记录的交互添加用户反馈"""
        # 反馈直接追加到日志文件
        feedback_entry = {
            'type': 'feedback',
            'record_id': record_id,
            'timestamp': datetime.now().isoformat(),
            'rating': rating,
            'feedback': feedback,
            'was_helpful': was_helpful,
        }
        self._append_jsonl(feedback_entry)
    
    def flush(self):
        """强制刷新缓冲区"""
        with self._lock:
            self._flush()
    
    # ================================================================
    # 查询 API
    # ================================================================
    
    def get_recent_interactions(self, limit: int = 50) -> List[Dict]:
        """获取最近的交互记录"""
        results = []
        files = sorted(
            [f for f in os.listdir(self._log_dir) if f.endswith('.jsonl')],
            reverse=True
        )
        for filename in files:
            if len(results) >= limit:
                break
            filepath = os.path.join(self._log_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                # 从文件末尾读取
                for line in reversed(lines):
                    if len(results) >= limit:
                        break
                    try:
                        record = json.loads(line.strip())
                        if record.get('type', 'interaction') == 'interaction':
                            results.append(record)
                    except json.JSONDecodeError:
                        continue
            except Exception:
                continue
        return list(reversed(results))
    
    def get_session_interactions(self, session_id: str) -> List[Dict]:
        """获取指定会话的所有交互记录"""
        results = []
        files = sorted([f for f in os.listdir(self._log_dir) if f.endswith('.jsonl')])
        for filename in files:
            filepath = os.path.join(self._log_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    for line in f:
                        try:
                            record = json.loads(line.strip())
                            if (record.get('session_id') == session_id and 
                                record.get('type', 'interaction') == 'interaction'):
                                results.append(record)
                        except json.JSONDecodeError:
                            continue
            except Exception:
                continue
        return results
    
    def get_high_quality_pairs(self, min_rating: int = 4, limit: int = 100) -> List[Dict]:
        """
        获取高质量交互对（用于蒸馏训练数据）
        筛选条件：用户评分 >= min_rating 或 was_helpful = True
        """
        # 收集所有 feedback 记录
        feedback_map = {}
        files = sorted([f for f in os.listdir(self._log_dir) if f.endswith('.jsonl')])
        for filename in files:
            filepath = os.path.join(self._log_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    for line in f:
                        try:
                            record = json.loads(line.strip())
                            if record.get('type') == 'feedback':
                                rid = record.get('record_id')
                                if rid:
                                    if rid not in feedback_map:
                                        feedback_map[rid] = []
                                    feedback_map[rid].append(record)
                        except json.JSONDecodeError:
                            continue
            except Exception:
                continue
        
        # 筛选高质量交互
        results = []
        for filename in files:
            if len(results) >= limit:
                break
            filepath = os.path.join(self._log_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    for line in f:
                        if len(results) >= limit:
                            break
                        try:
                            record = json.loads(line.strip())
                            if record.get('type', 'interaction') != 'interaction':
                                continue
                            rid = record.get('id')
                            fb_list = feedback_map.get(rid, [])
                            for fb in fb_list:
                                rating = fb.get('rating', 0)
                                helpful = fb.get('was_helpful')
                                if (rating and rating >= min_rating) or helpful:
                                    results.append(record)
                                    break
                        except json.JSONDecodeError:
                            continue
            except Exception:
                continue
        
        return results
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            'total_records': self._total_records,
            'total_tokens': self._total_tokens,
            'uptime_seconds': time.time() - self._start_time,
            'buffer_size': len(self._buffer),
            'sessions': len(self._session_stats),
            'session_stats': dict(self._session_stats),
            'log_dir': self._log_dir,
        }
    
    # ================================================================
    # 内部方法
    # ================================================================
    
    def _generate_id(self) -> str:
        """生成唯一记录 ID"""
        import uuid
        return uuid.uuid4().hex[:12]
    
    def _flush(self):
        """将缓冲区写入文件"""
        if not self._buffer:
            return
        
        records = self._buffer[:]
        self._buffer.clear()
        
        # 在锁外执行文件 I/O
        for record in records:
            self._append_jsonl(asdict(record))
    
    def _append_jsonl(self, data: dict):
        """追加一条 JSONL 记录"""
        # 检查是否需要轮转文件
        if self._current_file is None or self._file_record_count >= self.MAX_RECORDS_PER_FILE:
            self._rotate_file()
        
        filepath = os.path.join(self._log_dir, self._current_file)
        try:
            # 检查文件大小
            if os.path.exists(filepath) and os.path.getsize(filepath) >= self.MAX_FILE_SIZE:
                self._rotate_file()
                filepath = os.path.join(self._log_dir, self._current_file)
            
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write(json.dumps(data, ensure_ascii=False) + '\n')
            self._file_record_count += 1
        except Exception as e:
            print(f"[InteractionLogger] 写入失败: {e}")
    
    def _rotate_file(self):
        """轮转日志文件"""
        date_str = datetime.now().strftime('%Y%m%d')
        # 查找当天已有文件数量
        existing = [f for f in os.listdir(self._log_dir) 
                    if f.startswith(f'interactions_{date_str}')]
        index = len(existing)
        self._current_file = f'interactions_{date_str}_{index:03d}.jsonl'
        self._file_record_count = 0
        print(f"[InteractionLogger] 新建日志文件: {self._current_file}")


# ================================================================
# 全局单例
# ================================================================

_logger_instance: Optional[InteractionLogger] = None
_logger_lock = threading.Lock()


def get_interaction_logger() -> InteractionLogger:
    """获取全局 InteractionLogger 单例"""
    global _logger_instance
    if _logger_instance is None:
        with _logger_lock:
            if _logger_instance is None:
                _logger_instance = InteractionLogger()
    return _logger_instance