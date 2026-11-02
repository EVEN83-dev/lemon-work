---
name: office_generator
description: Generate office documents (Word/PPT/Excel) from structured content (DEPRECATED)
category: office
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: doc_type: str, title: str, content: str
outputs: document: str, format: str
capabilities: doc-generation, ppt-generation, spreadsheet-generation
namespace: bridge
tags: doc-generation, ppt-generation, spreadsheet-generation
---

# office_generator

Generate office documents (Word/PPT/Excel) from structured content (DEPRECATED).

## Inputs
- doc_type: str
- title: str
- content: str

## Outputs
- document: str
- format: str

## Capabilities
- doc-generation
- ppt-generation
- spreadsheet-generation
