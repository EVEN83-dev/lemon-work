---
name: code_reviewer
description: AST-based code review with security/performance/style analysis and severity scoring (DEPRECATED)
category: code
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: code: str, language: str, focus: str
outputs: findings: list, score: int, report: str
capabilities: security-analysis, performance-review, style-check
namespace: bridge
tags: security-analysis, performance-review, style-check
---

# code_reviewer

AST-based code review with security/performance/style analysis and severity scoring (DEPRECATED).

## Inputs
- code: str
- language: str
- focus: str

## Outputs
- findings: list
- score: int
- report: str

## Capabilities
- security-analysis
- performance-review
- style-check
