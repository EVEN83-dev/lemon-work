---
name: pomodoro_skill
description: Pomodoro timer with start/pause/resume/stop, completion callbacks, and daily stats
category: productivity
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: action: str, task_id: str, minutes: int
outputs: task: dict, status: str
capabilities: timer-start, timer-pause, timer-stop, daily-stats
namespace: bridge
tags: timer-start, timer-pause, timer-stop, daily-stats
---

# pomodoro_skill

Pomodoro timer with start/pause/resume/stop, completion callbacks, and daily stats.

## Inputs
- action: str
- task_id: str
- minutes: int

## Outputs
- task: dict
- status: str

## Capabilities
- timer-start
- timer-pause
- timer-stop
- daily-stats
