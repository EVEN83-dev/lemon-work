---
name: multi_model_debater
description: Structured multi-perspective debate with difflib-based analysis
category: debate
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: topic: str, perspectives: int
outputs: debate: dict, summary: str
capabilities: multi-perspective, structured-debate, cross-examination
namespace: bridge
tags: multi-perspective, structured-debate, cross-examination
---

# multi_model_debater

Structured multi-perspective debate with difflib-based analysis.

## Inputs
- topic: str
- perspectives: int

## Outputs
- debate: dict
- summary: str

## Capabilities
- multi-perspective
- structured-debate
- cross-examination
