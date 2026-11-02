# -*- coding: utf-8 -*-
"""364章 T5.1: 成本报表 — API调用量/Token消耗/费用统计"""

import json
import os
import time
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from collections import defaultdict


class CostReporter:
    def __init__(self, data_dir: str = ""):
        if not data_dir:
            data_dir = os.path.join(os.getcwd(), "data", "cost")
        self.data_dir = os.path.expanduser(data_dir)
        os.makedirs(self.data_dir, exist_ok=True)
        self._log_path = os.path.join(self.data_dir, "cost_log.jsonl")
        self._pricing = {
            "deepseek-chat": {"input": 0.0014, "output": 0.0028},
            "deepseek-reasoner": {"input": 0.004, "output": 0.016},
            "gpt-4o": {"input": 0.005, "output": 0.015},
            "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
            "claude-3.5-sonnet": {"input": 0.003, "output": 0.015},
            "qwen-plus": {"input": 0.0008, "output": 0.002},
            "qwen-turbo": {"input": 0.0003, "output": 0.0006},
        }

    def log_call(self, model: str, input_tokens: int, output_tokens: int,
                 duration: float = 0, engine: str = "") -> Dict:
        pricing = self._pricing.get(model, {"input": 0.001, "output": 0.002})
        input_cost = (input_tokens / 1000) * pricing["input"]
        output_cost = (output_tokens / 1000) * pricing["output"]
        total_cost = input_cost + output_cost

        entry = {
            "timestamp": time.time(),
            "datetime": datetime.now().isoformat(),
            "model": model,
            "engine": engine,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "duration": duration,
            "input_cost": round(input_cost, 6),
            "output_cost": round(output_cost, 6),
            "total_cost": round(total_cost, 6),
        }

        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        return entry

    def generate_report(self, days: int = 7) -> Dict:
        cutoff = time.time() - days * 86400
        entries = []
        if os.path.isfile(self._log_path):
            with open(self._log_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if entry.get("timestamp", 0) >= cutoff:
                            entries.append(entry)
                    except json.JSONDecodeError:
                        continue

        by_model = defaultdict(lambda: {"calls": 0, "input_tokens": 0,
                                         "output_tokens": 0, "cost": 0.0})
        for e in entries:
            model = e.get("model", "unknown")
            bucket = by_model[model]
            bucket["calls"] += 1
            bucket["input_tokens"] += e.get("input_tokens", 0)
            bucket["output_tokens"] += e.get("output_tokens", 0)
            bucket["cost"] += e.get("total_cost", 0)

        total_cost = sum(b["cost"] for b in by_model.values())
        total_calls = sum(b["calls"] for b in by_model.values())

        report_text = f"成本报表 (近{days}天)\n{'='*50}\n"
        report_text += f"总调用: {total_calls}\n总费用: ${total_cost:.4f}\n\n"
        for model, bucket in sorted(by_model.items(), key=lambda x: -x[1]["cost"]):
            report_text += f"  {model}:\n"
            report_text += f"    调用: {bucket['calls']}\n"
            report_text += f"    Input: {bucket['input_tokens']:,} tokens\n"
            report_text += f"    Output: {bucket['output_tokens']:,} tokens\n"
            report_text += f"    费用: ${bucket['cost']:.4f}\n\n"

        return {
            "total_calls": total_calls,
            "total_cost": round(total_cost, 4),
            "by_model": dict(by_model),
            "days": days,
            "report_text": report_text,
        }

    def set_pricing(self, model: str, input_per_1k: float, output_per_1k: float):
        self._pricing[model] = {"input": input_per_1k, "output": output_per_1k}
