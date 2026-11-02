---
name: image_processor
description: Image processing: resize, convert, extract metadata (DEPRECATED)
category: vision
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: path: str, operation: str
outputs: result: dict, metadata: dict
capabilities: image-resize, image-convert, image-metadata
namespace: bridge
tags: image-resize, image-convert, image-metadata
---

# image_processor

Image processing: resize, convert, extract metadata (DEPRECATED).

## Inputs
- path: str
- operation: str

## Outputs
- result: dict
- metadata: dict

## Capabilities
- image-resize
- image-convert
- image-metadata
