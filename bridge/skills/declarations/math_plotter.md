---
name: math_plotter
description: Mathematical visualization: function plots, ASCII charts, data visualization (DEPRECATED)
category: math
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: expression: str, plot_type: str
outputs: plot_data: dict, ascii_plot: str
capabilities: function-plot, ascii-visualization, data-chart
namespace: bridge
tags: function-plot, ascii-visualization, data-chart
---

# math_plotter

Mathematical visualization: function plots, ASCII charts, data visualization (DEPRECATED).

## Inputs
- expression: str
- plot_type: str

## Outputs
- plot_data: dict
- ascii_plot: str

## Capabilities
- function-plot
- ascii-visualization
- data-chart
