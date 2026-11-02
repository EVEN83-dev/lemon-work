---
name: academic_writer
description: Generate structured academic writing outlines with citation templates per style (APA/MLA/Chicago)
category: research
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: topic: str, style: str, sections: list
outputs: outline: str, sections: list
capabilities: outline-generation, citation-formatting, section-structuring
namespace: bridge
tags: outline-generation, citation-formatting, section-structuring
---

# academic_writer

Generate structured academic writing outlines with citation templates per style (APA/MLA/Chicago).

## Inputs
- topic: str
- style: str
- sections: list

## Outputs
- outline: str
- sections: list

## Capabilities
- outline-generation
- citation-formatting
- section-structuring
