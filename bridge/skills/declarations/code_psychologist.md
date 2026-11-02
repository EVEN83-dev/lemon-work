---
name: code_psychologist
description: Analyze code quality, naming, complexity, and provide developer personality insights using AST
category: analysis
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: code: str, language: str
outputs: analysis: str, scores: dict, personality: str
capabilities: code-analysis, naming-evaluation, complexity-scoring
namespace: bridge
tags: code-analysis, naming-evaluation, complexity-scoring
---

# code_psychologist

Analyze code quality, naming, complexity, and provide developer personality insights using AST.

## Inputs
- code: str
- language: str

## Outputs
- analysis: str
- scores: dict
- personality: str

## Capabilities
- code-analysis
- naming-evaluation
- complexity-scoring
