# -*- coding: utf-8 -*-
"""
Response Validator — P12 蒸馏 Step 6
======================================
验证本地 Agent 输出质量，确保回复可用。

验证维度：
1. 完整性检查 — 回复是否截断/空/过短
2. 格式检查 — 代码块是否正确闭合
3. 内容检查 — 是否包含明显错误/幻觉
4. 工具调用检查 — 工具调用结果是否合理
5. 语言检查 — 中英文混合是否合理

自动修复策略：
- 截断回复 → 标记为不完整，触发续写
- 空回复 → 触发重试（最多 3 次）
- 格式错误 → 自动修复代码块闭合
- 幻觉检测 → 标记为低质量，建议 API 处理
"""

import re
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ValidationLevel(Enum):
    """验证级别"""
    PASS = "pass"           # 通过
    WARN = "warn"           # 警告（可使用但需注意）
    FAIL = "fail"           # 失败（不可使用）
    RETRY = "retry"         # 需要重试
    FALLBACK = "fallback"   # 需要回退到 API


@dataclass
class ValidationResult:
    """验证结果"""
    level: ValidationLevel
    score: float  # 0.0 ~ 1.0
    issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    fixed_response: Optional[str] = None  # 自动修复后的回复
    needs_retry: bool = False
    needs_fallback: bool = False


class ResponseValidator:
    """
    响应校验器 — 确保本地 Agent 输出质量
    
    使用方式：
        validator = ResponseValidator()
        result = validator.validate(response, prompt)
        if result.level == ValidationLevel.PASS:
            use(response)
        elif result.level == ValidationLevel.FAIL:
            retry_or_fallback()
    """
    
    # 最小回复长度
    MIN_RESPONSE_LENGTH = 10
    
    # 截断检测关键词
    TRUNCATION_PATTERNS = [
        r'[。，；！？,.;!?]\s*$',              # 以标点结尾（正常）
        r'(?:等等|\.\.\.|…)\s*$',              # 省略号结尾
        r'(?:未完|待续|to be continued)',       # 未完待续
        r'[a-zA-Z]\s*$',                       # 以英文字母结尾（可能截断）
        r'[（(]\s*$',                           # 以左括号结尾（截断）
        r'```\s*$',                             # 以代码块起头结尾（截断）
    ]
    
    # 幻觉检测关键词（7B 模型常见幻觉）
    HALLUCINATION_PATTERNS = [
        r'作为(?:一个|AI|语言模型|大型语言模型)',
        r'我无法(?:访问|执行|回答|提供)',
        r'抱歉.*?(?:无法|不能|没有)',
        r'很抱歉',
        r'请(?:注意|理解|知悉)',
        r'I (?:apologize|cannot|don\'t have)',
        # 虚构URL/版本号
        r'https?://(?:example|fake|dummy|test)\.\w+',
        r'版本\s*\d+\.\d+\.\d+\s*(?:已发布|最新|推荐)',
        # 虚构API/函数名
        r'(?:api|function|method)_\w{20,}',  # 过长的函数名（可能是幻觉）
        # 虚构引用
        r'根据.*?(?:研究|论文|报告).*?显示',
        r'据统计.*?\d+%.*?(?:的|以上)',
        # 无意义重复
        r'(.)\1{10,}',  # 同一字符重复10次以上
        # 自相矛盾
        r'是.*?不是.*?是.*?不是',
    ]

    # 上下文相关性检测 — 检测回复是否包含与prompt完全无关的内容
    IRRELEVANT_PATTERNS = [
        r'我.*?不知道.*?但是.*?我可以',
        r'虽然.*?但是.*?作为一个.*?AI',
        r'请注意.*?我.*?不能.*?保证',
    ]
    
    # 代码块完整性检查
    CODE_BLOCK_PATTERN = re.compile(r'```(\w*)\n?(.*?)```', re.DOTALL)
    UNCLOSED_CODE_BLOCK = re.compile(r'```(?!`)')
    
    def __init__(self):
        self._stats = {
            'total_validations': 0,
            'passed': 0,
            'warnings': 0,
            'failures': 0,
            'retries': 0,
            'fallbacks': 0,
        }
    
    def validate(self, response: str, prompt: str = "", expected_tools: int = 0) -> ValidationResult:
        """
        验证响应质量
        
        Args:
            response: AI 回复内容
            prompt: 原始用户输入
            expected_tools: 预期的工具调用次数
        
        Returns:
            ValidationResult
        """
        self._stats['total_validations'] += 1
        
        issues = []
        suggestions = []
        score = 1.0
        
        # 1. 空响应检查
        if not response or not response.strip():
            self._stats['failures'] += 1
            return ValidationResult(
                level=ValidationLevel.RETRY,
                score=0.0,
                issues=["响应为空"],
                suggestions=["触发重试"],
                needs_retry=True,
            )
        
        # 2. 过短响应检查
        if len(response.strip()) < self.MIN_RESPONSE_LENGTH:
            issues.append(f"响应过短 ({len(response.strip())} 字符)")
            score -= 0.3
            suggestions.append("考虑增加 num_predict 参数")
        
        # 3. 截断检测
        truncated = self._check_truncation(response)
        if truncated:
            issues.append(f"响应可能截断: {truncated}")
            score -= 0.2
            suggestions.append("触发续写或增加 num_predict")
        
        # 4. 代码块闭合检查
        code_blocks_ok, fixed = self._check_code_blocks(response)
        if not code_blocks_ok:
            issues.append("代码块未正确闭合")
            score -= 0.15
            suggestions.append("自动修复代码块闭合")
            if fixed:
                response = fixed
        
        # 5. 幻觉检测
        hallucinations = self._check_hallucinations(response, prompt)
        if hallucinations:
            issues.append(f"检测到幻觉内容: {hallucinations}")
            score -= 0.25
            suggestions.append("建议使用 API 引擎处理此问题")
        
        # 6. 内容质量检查
        quality_issues = self._check_content_quality(response)
        if quality_issues:
            issues.extend(quality_issues)
            score -= 0.1 * len(quality_issues)
        
        # 7. 中英文混合检查
        lang_issues = self._check_language_mix(response)
        if lang_issues:
            issues.append(lang_issues)
            score -= 0.05
        
        score = max(0.0, min(1.0, score))
        
        # 确定验证级别
        needs_retry = False
        needs_fallback = False
        if score >= 0.8:
            level = ValidationLevel.PASS
            self._stats['passed'] += 1
        elif score >= 0.5:
            level = ValidationLevel.WARN
            self._stats['warnings'] += 1
        elif score >= 0.3:
            level = ValidationLevel.RETRY
            self._stats['retries'] += 1
            needs_retry = True
        else:
            level = ValidationLevel.FALLBACK
            self._stats['fallbacks'] += 1
            needs_fallback = True
        
        return ValidationResult(
            level=level,
            score=score,
            issues=issues,
            suggestions=suggestions,
            fixed_response=response if code_blocks_ok or fixed else fixed,
            needs_retry=needs_retry,
            needs_fallback=needs_fallback,
        )
    
    def _check_truncation(self, text: str) -> Optional[str]:
        """检查响应是否被截断"""
        for pattern in self.TRUNCATION_PATTERNS:
            if re.search(pattern, text.strip()[-50:]):
                # 省略号等是正常截断信号
                if '...' in text.strip()[-20:] or '…' in text.strip()[-5:]:
                    return "省略号结尾"
                # 以未闭合代码块结尾
                if text.strip().endswith('```'):
                    return "未闭合代码块结尾"
                # 以英文字母结尾（可能是截断）
                if re.search(r'[a-zA-Z]$', text.strip()):
                    return "英文单词结尾（可能截断）"
        return None
    
    def _check_code_blocks(self, text: str) -> Tuple[bool, Optional[str]]:
        """检查代码块是否完整闭合，自动修复"""
        # 计数 ``` 出现次数
        backtick_count = len(re.findall(r'```', text))
        
        if backtick_count % 2 == 0:
            return True, None
        
        # 奇数个 ``` → 未闭合，自动添加闭合
        fixed = text.rstrip() + "\n```"
        logger.info(f"[Validator] 自动修复未闭合代码块")
        return False, fixed
    
    def _check_hallucinations(self, text: str, prompt: str) -> Optional[str]:
        """检测幻觉内容"""
        hallucinations = []

        # 基础幻觉模式检测（不依赖prompt）
        for pattern in self.HALLUCINATION_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                hallucinations.append(match.group(0))

        # 上下文相关性检测（需要prompt）
        if prompt and len(prompt) >= 10:
            for pattern in self.IRRELEVANT_PATTERNS:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    hallucinations.append(f"上下文无关: {match.group(0)[:30]}")

            # 检测回复是否包含prompt中完全没提到的技术术语（简单启发式）
            prompt_terms = set(re.findall(r'[a-zA-Z_]{5,}', prompt.lower()))
            response_terms = set(re.findall(r'[a-zA-Z_]{10,}', text.lower()))
            # 过滤常见通用词
            common_words = {'import', 'function', 'return', 'class', 'def', 'self', 'none', 'true', 'false'}
            novel_terms = response_terms - prompt_terms - common_words
            if len(novel_terms) > 8 and len(response_terms) > 15:
                hallucinations.append(f"可能虚构术语: {list(novel_terms)[:3]}")

        if hallucinations:
            return "; ".join(hallucinations[:5])
        return None
    
    def _check_content_quality(self, text: str) -> List[str]:
        """检查内容质量"""
        issues = []
        
        # 重复内容检测
        lines = text.split('\n')
        if len(lines) > 3:
            # 检查连续重复行
            for i in range(len(lines) - 2):
                if lines[i].strip() == lines[i+1].strip() == lines[i+2].strip() and len(lines[i].strip()) > 10:
                    issues.append("检测到连续重复内容")
                    break
        
        # 过短行过多
        short_lines = sum(1 for l in lines if len(l.strip()) < 3 and l.strip())
        if short_lines > len(lines) * 0.5 and len(lines) > 5:
            issues.append("过多短行（可能格式混乱）")
        
        return issues
    
    def _check_language_mix(self, text: str) -> Optional[str]:
        """检查中英文混合是否合理"""
        # 去除代码块和行内代码
        clean = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
        clean = re.sub(r'`[^`]+`', '', clean)
        # 去除URL和文件路径
        clean = re.sub(r'https?://\S+', '', clean)
        clean = re.sub(r'[A-Za-z]:[\\/]\S+', '', clean)

        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', clean))
        english_chars = len(re.findall(r'[a-zA-Z]', clean))

        total = chinese_chars + english_chars
        if total == 0:
            return None

        chinese_ratio = chinese_chars / total

        # 中英文混杂度检查（预期中文为主，英文为辅）
        if 0.3 < chinese_ratio < 0.7:
            return "中英文混合比例异常"

        # 检测句中混杂：中文句子中间突然出现长英文片段
        # 如 "我们使用 the configuration file to setup"
        mixed_sentences = re.findall(r'[\u4e00-\u9fff]+\s+[a-zA-Z]{10,}\s+[\u4e00-\u9fff]+', clean)
        if len(mixed_sentences) > 2:
            return f"句中中英文混杂 ({len(mixed_sentences)} 处)"

        # 检测中英文交替频率（每句话中英切换次数过多）
        sentences = re.split(r'[。！？\n]', clean)
        for sent in sentences:
            sent = sent.strip()
            if len(sent) < 10:
                continue
            # 统计中英切换次数
            switches = 0
            prev_is_chinese = None
            for ch in sent:
                is_chinese = '\u4e00' <= ch <= '\u9fff'
                if prev_is_chinese is not None and is_chinese != prev_is_chinese:
                    switches += 1
                prev_is_chinese = is_chinese
            if switches > 5 and len(sent) > 20:
                return f"单句中英切换过多 ({switches} 次)"

        return None
    
    @property
    def stats(self) -> Dict:
        return dict(self._stats)


# 全局单例
_validator_instance: Optional[ResponseValidator] = None


def get_response_validator() -> ResponseValidator:
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = ResponseValidator()
    return _validator_instance