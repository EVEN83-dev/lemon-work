---
name: browser_automation
description: Web scraping and automation with requests+BS4+optional Playwright dual-layer architecture
category: automation
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: url: str, action: str, selector: str
outputs: content: str, status: int
capabilities: web-scraping, page-navigation, data-extraction
namespace: bridge
tags: web-scraping, page-navigation, data-extraction
---

# browser_automation

Web scraping and automation with requests+BS4+optional Playwright dual-layer architecture.

## Inputs
- url: str
- action: str
- selector: str

## Outputs
- content: str
- status: int

## Capabilities
- web-scraping
- page-navigation
- data-extraction
