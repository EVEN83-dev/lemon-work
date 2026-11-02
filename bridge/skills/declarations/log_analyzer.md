---
name: log_analyzer
description: Analyze log files: error counting, pattern extraction, keyword statistics
category: system
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: path: str, max_lines: int
outputs: stats: dict, patterns: list
capabilities: error-counting, pattern-extraction, log-statistics
namespace: bridge
tags: error-counting, pattern-extraction, log-statistics
---

# log_analyzer

Analyze log files: error counting, pattern extraction, keyword statistics.

## Inputs
- path: str
- max_lines: int

## Outputs
- stats: dict
- patterns: list

## Capabilities
- error-counting
- pattern-extraction
- log-statistics
