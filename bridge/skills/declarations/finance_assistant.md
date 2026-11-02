---
name: finance_assistant
description: Financial analysis: loan calculation, compound interest, ROI, depreciation with pure Python
category: finance
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: analysis_type: str, principal: float, rate: float, periods: int
outputs: result: dict, schedule: list
capabilities: loan-calculation, compound-interest, roi, depreciation
namespace: bridge
tags: loan-calculation, compound-interest, roi, depreciation
---

# finance_assistant

Financial analysis: loan calculation, compound interest, ROI, depreciation with pure Python.

## Inputs
- analysis_type: str
- principal: float
- rate: float
- periods: int

## Outputs
- result: dict
- schedule: list

## Capabilities
- loan-calculation
- compound-interest
- roi
- depreciation
