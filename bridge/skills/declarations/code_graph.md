---
name: code_graph
description: Build dependency graphs, call trees, and structure diagrams from Python code using AST
category: code
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: code: str, language: str, graph_type: str
outputs: graph: dict, visualization: str
capabilities: dependency-graph, call-tree, structure-diagram
namespace: bridge
tags: dependency-graph, call-tree, structure-diagram
---

# code_graph

Build dependency graphs, call trees, and structure diagrams from Python code using AST.

## Inputs
- code: str
- language: str
- graph_type: str

## Outputs
- graph: dict
- visualization: str

## Capabilities
- dependency-graph
- call-tree
- structure-diagram
