---
name: config_manager
description: Read, write, and validate application configuration files
category: system
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: action: str, key: str, value: str
outputs: config: dict, status: str
capabilities: config-read, config-write, config-validate
namespace: bridge
tags: config-read, config-write, config-validate
---

# config_manager

Read, write, and validate application configuration files.

## Inputs
- action: str
- key: str
- value: str

## Outputs
- config: dict
- status: str

## Capabilities
- config-read
- config-write
- config-validate
