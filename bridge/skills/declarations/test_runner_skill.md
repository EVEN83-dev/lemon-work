---
name: test_runner_skill
description: Execute test suites with result collection and coverage reporting
category: code
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: action: str, test_path: str, framework: str
outputs: results: dict, summary: str
capabilities: test-execution, result-collection, coverage-report
namespace: bridge
tags: test-execution, result-collection, coverage-report
---

# test_runner_skill

Execute test suites with result collection and coverage reporting.

## Inputs
- action: str
- test_path: str
- framework: str

## Outputs
- results: dict
- summary: str

## Capabilities
- test-execution
- result-collection
- coverage-report
