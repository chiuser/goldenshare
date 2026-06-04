---
name: goldenshare-dev-intake
description: Use when starting any Goldenshare development, bug fix, refactor, architecture, contract, dispatcher, worker, service, or plan-driven task. 适用于开发、修复、重构、按计划推进、契约调整、影响面审计和开工前目标澄清。
---

# Goldenshare Dev Intake

Use this skill before making code or documentation changes in this repository.

## Workflow

1. Read the nearest applicable `AGENTS.md` files before acting.
2. State the development intake in the user update:
   - goal
   - source documents or current code evidence
   - intended change scope
   - expected impact surface
3. If any item cannot be confirmed from the repo, stop and report the missing fact instead of coding.
4. If the task touches architecture, dependency boundaries, shared contracts, `dispatcher`, `worker`, `service`, `TaskRun`, `DatasetDefinition`, or resolver/planner behavior, use CodeGraph before edits.
5. If the user says "按计划开发", "按文档推进", or similar, convert the plan into hard constraints first:
   - extract "must / must not / only / default / boundary / acceptance"
   - map each constraint to real code, SQL, API, UI, config, or tests
   - include positive and negative tests for each hard constraint
6. Keep each round to one clear goal. Do not introduce unrelated features, compatibility layers, temporary fixes, or broad cleanup.

## Delivery Gate

Before final response, report:

1. target and evidence
2. changed files
3. boundary or dependency impact
4. validation results
5. risks and next steps
6. CodeGraph scope when CodeGraph was required

