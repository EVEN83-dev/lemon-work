---
name: image_analyzer
description: Analyze images: metadata extraction, color analysis, brightness detection via Pillow
category: vision
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: image_path: str, image_url: str, question: str
outputs: image_info: dict, analysis: str
capabilities: metadata-extraction, color-analysis, brightness-detection
namespace: bridge
tags: metadata-extraction, color-analysis, brightness-detection
---

# image_analyzer

Analyze images: metadata extraction, color analysis, brightness detection via Pillow.

## Inputs
- image_path: str
- image_url: str
- question: str

## Outputs
- image_info: dict
- analysis: str

## Capabilities
- metadata-extraction
- color-analysis
- brightness-detection
