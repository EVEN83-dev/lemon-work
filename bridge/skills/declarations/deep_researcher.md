---
name: deep_researcher
description: Multi-source deep research with web search, sub-topic generation, and structured reports
category: research
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: topic: str, depth: int, sources: int
outputs: report: str, sources_count: int
capabilities: multi-source-research, sub-topic-generation, report-generation
namespace: bridge
tags: multi-source-research, sub-topic-generation, report-generation
---

# deep_researcher

Multi-source deep research with web search, sub-topic generation, and structured reports.

## Inputs
- topic: str
- depth: int
- sources: int

## Outputs
- report: str
- sources_count: int

## Capabilities
- multi-source-research
- sub-topic-generation
- report-generation
