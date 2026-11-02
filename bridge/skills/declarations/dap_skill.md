---
name: dap_skill
description: Debug Adapter Protocol skill with breakpoint/variable/step debugging support
category: code
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: action: str, breakpoint: str, expression: str
outputs: debug_result: dict, variables: dict
capabilities: debug-breakpoint, variable-inspection, step-execution
namespace: bridge
tags: debug-breakpoint, variable-inspection, step-execution
---

# dap_skill

Debug Adapter Protocol skill with breakpoint/variable/step debugging support.

## Inputs
- action: str
- breakpoint: str
- expression: str

## Outputs
- debug_result: dict
- variables: dict

## Capabilities
- debug-breakpoint
- variable-inspection
- step-execution
