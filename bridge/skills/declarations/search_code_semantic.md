---
name: search_code_semantic
description: Semantic code search with relevance ranking and pattern matching
category: code
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: query: str, directory: str, language: str
outputs: matches: list, relevance_scores: dict
capabilities: code-search, relevance-ranking, pattern-matching
namespace: bridge
tags: code-search, relevance-ranking, pattern-matching
---

# search_code_semantic

Semantic code search with relevance ranking and pattern matching.

## Inputs
- query: str
- directory: str
- language: str

## Outputs
- matches: list
- relevance_scores: dict

## Capabilities
- code-search
- relevance-ranking
- pattern-matching
