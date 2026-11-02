---
name: env_checker
description: Check Python environment: version, platform, installed packages, system info
category: system
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: (none required)
outputs: environment: dict, packages: list
capabilities: environment-info, package-listing, version-check
namespace: bridge
tags: environment-info, package-listing, version-check
---

# env_checker

Check Python environment: version, platform, installed packages, system info.

## Inputs
- (none required)

## Outputs
- environment: dict
- packages: list

## Capabilities
- environment-info
- package-listing
- version-check
