---
name: test_generator
description: Generate test code via AST analysis for pytest/jest/junit frameworks (DEPRECATED)
category: code
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: code: str, language: str, framework: str
outputs: test_code: str, framework: str
capabilities: test-code-generation, edge-case-detection, framework-support
namespace: bridge
tags: test-code-generation, edge-case-detection, framework-support
---

# test_generator

Generate test code via AST analysis for pytest/jest/junit frameworks (DEPRECATED).

## Inputs
- code: str
- language: str
- framework: str

## Outputs
- test_code: str
- framework: str

## Capabilities
- test-code-generation
- edge-case-detection
- framework-support
