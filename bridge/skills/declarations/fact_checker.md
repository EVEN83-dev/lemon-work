---
name: fact_checker
description: Cross-reference claims against web sources with automated verification scoring
category: research
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: claim: str, sources: int
outputs: verification: dict, sources_found: int
capabilities: claim-verification, cross-referencing, source-analysis
namespace: bridge
tags: claim-verification, cross-referencing, source-analysis
---

# fact_checker

Cross-reference claims against web sources with automated verification scoring.

## Inputs
- claim: str
- sources: int

## Outputs
- verification: dict
- sources_found: int

## Capabilities
- claim-verification
- cross-referencing
- source-analysis
