---
name: super_researcher
description: Multi-round deep research with source compilation and term analysis
category: research
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: topic: str, rounds: int
outputs: findings: str, sources_count: int
capabilities: multi-round-research, source-compilation, term-analysis
namespace: bridge
tags: multi-round-research, source-compilation, term-analysis
---

# super_researcher

Multi-round deep research with source compilation and term analysis.

## Inputs
- topic: str
- rounds: int

## Outputs
- findings: str
- sources_count: int

## Capabilities
- multi-round-research
- source-compilation
- term-analysis
