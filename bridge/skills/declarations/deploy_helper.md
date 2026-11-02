---
name: deploy_helper
description: Generate deployment config files (Dockerfile, Procfile, app.yaml) and checklists
category: system
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: project_type: str, target: str, config: dict
outputs: config_files: dict, checklist: list
capabilities: dockerfile-generation, deploy-config, checklist-generation
namespace: bridge
tags: dockerfile-generation, deploy-config, checklist-generation
---

# deploy_helper

Generate deployment config files (Dockerfile, Procfile, app.yaml) and checklists.

## Inputs
- project_type: str
- target: str
- config: dict

## Outputs
- config_files: dict
- checklist: list

## Capabilities
- dockerfile-generation
- deploy-config
- checklist-generation
