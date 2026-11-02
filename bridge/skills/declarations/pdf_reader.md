---
name: pdf_reader
description: Read and extract text, summaries, tables from PDF files with PyPDF2 or raw binary fallback
category: file
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: file_id: str, path: str, pages: str, extract_type: str
outputs: text: str, metadata: dict, tables: list
capabilities: text-extraction, summary-generation, table-extraction
namespace: bridge
tags: text-extraction, summary-generation, table-extraction
---

# pdf_reader

Read and extract text, summaries, tables from PDF files with PyPDF2 or raw binary fallback.

## Inputs
- file_id: str
- path: str
- pages: str
- extract_type: str

## Outputs
- text: str
- metadata: dict
- tables: list

## Capabilities
- text-extraction
- summary-generation
- table-extraction
