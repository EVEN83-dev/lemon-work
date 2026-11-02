---
name: lsp_skill
description: Language Server Protocol integration: diagnostics, completions, symbol lookup
category: code
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: action: str, file_path: str, position: dict
outputs: diagnostics: list, completions: list
capabilities: code-diagnostics, auto-completion, symbol-lookup
namespace: bridge
tags: code-diagnostics, auto-completion, symbol-lookup
---

# lsp_skill

Language Server Protocol integration: diagnostics, completions, symbol lookup.

## Inputs
- action: str
- file_path: str
- position: dict

## Outputs
- diagnostics: list
- completions: list

## Capabilities
- code-diagnostics
- auto-completion
- symbol-lookup
