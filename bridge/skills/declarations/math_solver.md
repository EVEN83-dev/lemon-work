---
name: math_solver
description: Mathematical expression solving with safe eval: solve, simplify, evaluate, derivative (DEPRECATED)
category: math
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: expression: str, operation: str
outputs: result: str, steps: list
capabilities: solve, simplify, evaluate, derivative, integral
namespace: bridge
tags: solve, simplify, evaluate, derivative, integral
---

# math_solver

Mathematical expression solving with safe eval: solve, simplify, evaluate, derivative (DEPRECATED).

## Inputs
- expression: str
- operation: str

## Outputs
- result: str
- steps: list

## Capabilities
- solve
- simplify
- evaluate
- derivative
- integral
