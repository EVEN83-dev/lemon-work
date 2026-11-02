---
name: physics_experiment
description: Physics simulation and formula calculation for common experiments
category: math
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: experiment: str, parameters: dict
outputs: results: dict, analysis: str
capabilities: simulation, formula-calculation, experiment-analysis
namespace: bridge
tags: simulation, formula-calculation, experiment-analysis
---

# physics_experiment

Physics simulation and formula calculation for common experiments.

## Inputs
- experiment: str
- parameters: dict

## Outputs
- results: dict
- analysis: str

## Capabilities
- simulation
- formula-calculation
- experiment-analysis
