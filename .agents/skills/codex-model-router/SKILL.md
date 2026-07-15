---
name: codex-model-router
description: Use when a Codex task needs an explicit GPT-5.6 model or reasoning-effort choice, spans planning, implementation, testing, or QA phases, should delegate work automatically by difficulty or volume, or needs evidence-based escalation from a prior model choice.
---

# Codex Model Router

## Purpose

Keep one visible coordinator conversation while routing bounded work to the smallest capable GPT-5.6 worker. Do not claim the active task changed models; prove which worker actually ran.

## Classify each substantial phase

Assign a non-sensitive hyphen-case `task_family`, a `phase` (`plan`, `build`, `test`, `qa`), and:

- `verifiable`: `yes`, `partial`, `no`
- `failcost`: `low`, `mid`, `high`
- `volume`: `low`, `mid`, `high`
- `depth`: `shallow`, `medium`, `deep`
- `decomposable`: `yes` only for independently verifiable workstreams
- `workstreams`: independent workstream count

Run `scripts/advisor.py dispatch --help`, then call `dispatch` with those values and `task_scope` (`micro`, `phase`, `workflow`).

## Execute the dispatch

Use this ordered contract:

1. If `task_scope=micro`, keep it in the main task and report `dispatch_mode=main_task_direct`.
2. Otherwise, spawn the returned `agent_name` only when `native_custom_agent_ready=true` and the runtime preserves the parent boundary. Its fixed model and effort exactly match the recommendation. Report `dispatch_mode=native_custom_agent`.
3. If native selection is unavailable, identify the parent sandbox and approval policy. Request the same or stricter child sandbox, pass the exact parent approval policy, and explicitly confirm the boundary when calling `dispatch`. Run the bounded `codex exec` command only when `codex_exec_ready=true`; it pins that policy explicitly. Include exact cwd, mutable paths, acceptance criteria, and `--json`. Report `dispatch_mode=codex_exec`.
4. If neither mechanism is available, continue in the main task and report `dispatch_mode=main_task_fallback` plus the capability gap.

Run write-dependent phases sequentially. Parallelize only independent read-heavy work. Use a fresh worker for independent QA when it materially improves confidence.

After every worker returns, compare its reported changed paths and the actual diff with the allowed mutable paths. Reject the worker result as an out-of-scope violation before integration or recording if any path exceeds that boundary.

The project agents are:

- `pas_luna_worker`: repeatable, validator-backed, high-volume, or deterministic test work
- `pas_terra_worker`: ordinary Terra Medium analysis and implementation
- `pas_terra_builder`: normal implementation, integration, and moderately complex debugging
- `pas_sol_analyst`: architecture, ambiguous high-failure-cost work, and independent high-risk QA
- `pas_sol_max_worker`: one bounded escalation after a named Sol High failure

Route from the axes, not the phase name alone. Ultra is only an explicit parallel-decomposition option; never select it automatically.

## Escalate and record

Escalate only after a named check fails. Attach the failure evidence to the next worker; the history policy must move away from the failed model/effort combination. Stop when the escalation chain is exhausted or the same failure repeats without new information.

After verification, use `record` with the actual `model`, `effort`, `phase`, `agent_name`, `dispatch_mode`, command, and result. Never record raw prompts, customer names, source text, credentials, or confidential data. A history override requires a registered exact model-effort agent, two recent verified passes, no verified failure, the same axes, and the same model generation; Max and Ultra never qualify.

Accept session identity only from runtime environment variables; otherwise use `unknown`. Never infer the current task from the globally newest rollout.
