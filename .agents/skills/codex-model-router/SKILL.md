---
name: codex-model-router
description: Use when a Codex task needs an explicit GPT-6 Luna, Sol, or Astra model and reasoning-effort choice, spans planning, implementation, testing, or QA phases, or needs evidence-based escalation from a prior model choice.
---

# Codex Model Router

## Purpose

codex-model-router = routing decision engine only. It classifies a bounded task descriptor and returns model, effort, exact registered worker, and bounded escalation metadata. It does not execute a worker, inspect Git, validate results, or write outcomes. Do not claim the active task changed models or that a recommendation proves execution.

## Route one task

For a structured task card, run `scripts/advisor.py route-task --task-file PATH --phase build`. This reads the card, uses the deterministic R0.02 classifier, applies the GPT-6 policy and eligible read-only history, and emits schema-versioned JSON. It never echoes raw task prose. Use `classify` or `recommend-from-task` for narrower inspection, or `recommend` for explicit-axis compatibility.

The axes are `verifiable` (yes/partial/no), `failcost` (low/mid/high), `volume` (low/mid/high), `depth` (shallow/medium/deep), `decomposable` (yes/no), and independent `workstreams` count. A phase is `plan`, `build`, `test`, or `qa`. Route from these axes, not the phase name alone. Never infer a task from the globally newest rollout.

## Decision boundary

`route-task` returns `schema_version`, `task_family`, `classification`, `phase`, `model`, `effort`, `model_version`, `policy_version`, `rule_id`, `agent_name`, `automatic`, `next_escalation`, `reason_labels`, and `dispatch_capability`. Capability metadata is not a launch. Existing `dispatch` and `dispatch-from-task` remain advisory compatibility interfaces; their `fallback_command` is a proposal, never executed by the router.

The exact automatic chain is Luna Medium → Sol Medium → Sol High → Astra Low → Astra Medium → Astra High → blocked. Astra is not statically selected. xhigh, max, and ultra remain manual-only. A verified failure of the current exact pair is required before advancing. GPT-5.6 records remain readable but cannot alter a GPT-6 decision. Verified history overrides require the same task family, axes, phase, and generation, an exact automatic worker mapping, two recent verified passes, and no verified failure.

## Composition outside the router

task/planner → router → routing JSON → executor → validator/outcome collector → history/stats

A separate executor chooses how to use `pas_luna_worker`, `pas_sol_worker`, `pas_sol_analyst`, or a bounded Astra worker. `pas_sol_max_worker` is explicit/manual-only. That executor—not this router—must preserve the parent's approval policy, use the same or stricter sandbox, respect mutable paths, and report the actual `dispatch_mode` (`native_custom_agent`, `codex_exec`, `main_task_direct`, or `main_task_fallback`). If `task_scope=micro`, an external coordinator may keep it in the main task. `codex_exec_ready` is advisory boundary metadata, not evidence that Codex ran. Reject the worker result as out-of-scope before integration if changed paths exceed the task boundary.

The separate validator/outcome collector owns verification and outcome writing. The router only consumes previously produced history. Graph inspection, learning, decomposition, and orchestration are separate components; this skill does not implement them.
