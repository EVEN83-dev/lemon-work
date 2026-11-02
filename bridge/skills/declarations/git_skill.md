---
name: git_skill
description: Git operations: status, diff, log, add, commit, checkout, push, branch, stash via subprocess
category: code
version: 2.0.0
risk_level: low
timeout: 30
dependencies: 
needs_llm: false
inputs: action: str, message: str, target: str
outputs: output: str, stats: dict
capabilities: git-status, git-diff, git-log, git-commit, git-branch
namespace: bridge
tags: git-status, git-diff, git-log, git-commit, git-branch
---

# git_skill

Git operations: status, diff, log, add, commit, checkout, push, branch, stash via subprocess.

## Inputs
- action: str
- message: str
- target: str

## Outputs
- output: str
- stats: dict

## Capabilities
- git-status
- git-diff
- git-log
- git-commit
- git-branch
