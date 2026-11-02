---
name: info_debater
description: Multi-source information debate with pro/con analysis and consensus detection (DEPRECATED)
category: debate
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: topic: str, sources: str, mode: str
outputs: debate_result: dict, consensus: str
capabilities: pro-con-analysis, consensus-finding, overlap-detection
namespace: bridge
tags: pro-con-analysis, consensus-finding, overlap-detection
---

# info_debater

Multi-source information debate with pro/con analysis and consensus detection (DEPRECATED).

## Inputs
- topic: str
- sources: str
- mode: str

## Outputs
- debate_result: dict
- consensus: str

## Capabilities
- pro-con-analysis
- consensus-finding
- overlap-detection
