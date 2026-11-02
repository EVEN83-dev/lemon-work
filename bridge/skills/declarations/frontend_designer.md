---
name: frontend_designer
description: Generate HTML/Vue/React/ArkTS frontend code from component descriptions
category: code
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: framework: str, component_type: str, description: str
outputs: code: str, framework: str
capabilities: html-generation, vue-generation, react-generation, arkts-generation
namespace: bridge
tags: html-generation, vue-generation, react-generation, arkts-generation
---

# frontend_designer

Generate HTML/Vue/React/ArkTS frontend code from component descriptions.

## Inputs
- framework: str
- component_type: str
- description: str

## Outputs
- code: str
- framework: str

## Capabilities
- html-generation
- vue-generation
- react-generation
- arkts-generation
