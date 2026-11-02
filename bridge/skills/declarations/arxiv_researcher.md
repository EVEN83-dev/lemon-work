---
name: arxiv_researcher
description: Search ArXiv for academic papers with HTTPS, retry logic, and pagination
category: research
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: query: str, max_results: int
outputs: papers: list, summary: str
capabilities: paper-search, abstract-extraction, author-lookup
namespace: bridge
tags: paper-search, abstract-extraction, author-lookup
---

# arxiv_researcher

Search ArXiv for academic papers with HTTPS, retry logic, and pagination.

## Inputs
- query: str
- max_results: int

## Outputs
- papers: list
- summary: str

## Capabilities
- paper-search
- abstract-extraction
- author-lookup
