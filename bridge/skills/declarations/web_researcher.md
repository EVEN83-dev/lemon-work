---
name: web_researcher
description: Web search via DuckDuckGo API with result formatting and keyword analysis (DEPRECATED)
category: research
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: query: str, max_results: int
outputs: results: list, summary: str
capabilities: web-search, result-formatting, keyword-analysis
namespace: bridge
tags: web-search, result-formatting, keyword-analysis
---

# web_researcher

Web search via DuckDuckGo API with result formatting and keyword analysis (DEPRECATED).

## Inputs
- query: str
- max_results: int

## Outputs
- results: list
- summary: str

## Capabilities
- web-search
- result-formatting
- keyword-analysis
