---
name: code_formatter
description: Format Python code using AST analysis, detect naming/style violations, output formatted code
category: code
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: code: str, language: str, style: str
outputs: formatted_code: str, issues: list
capabilities: code-formatting, style-enforcement, import-sorting
namespace: bridge
tags: code-formatting, style-enforcement, import-sorting
---

# code_formatter

Format Python code using AST analysis, detect naming/style violations, output formatted code.

## Inputs
- code: str
- language: str
- style: str

## Outputs
- formatted_code: str
- issues: list

## Capabilities
- code-formatting
- style-enforcement
- import-sorting
