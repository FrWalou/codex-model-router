---
name: codex-model-router
description: Use when a Codex task needs an explicit GPT-5.6 or GPT-6 Astra model and reasoning-effort choice, spans planning, implementation, testing, or QA phases, should delegate work automatically by difficulty or volume, or needs evidence-based escalation from a prior model choice.
---

# Codex Model Router

## Purpose

Keep one visible coordinator conversation while routing bounded work to the smallest capable worker. GPT-6 Astra is a final evidence-gated escalation tier, not a default. Do not claim the active task changed models; prove which worker actually ran.

## Classify each substantial phase

Assign a non-sensitive hyphen-case `task_family`, a `phase` (`plan`, `build`, `test`, `qa`), and:

- `verifiable`: `yes`, `partial`, `no`
- `failcost`: `low`, `mid`, `high`
- `volume`: `low`, `mid`, `high`
- `depth`: `shallow`, `medium`, `deep`
- `decomposable`: `yes` only for independently verifiable workstreams
- `workstreams`: independent workstream count

For a supplied structured task card, first run `scripts/advisor.py classify --task-file PATH`. The local classifier returns conservative axes, confidence, and non-sensitive signal labels without calling a model. Use `recommend-from-task` or `dispatch-from-task` to pass those axes to the advisor without retyping them. Otherwise run `scripts/advisor.py dispatch --help`, then call `dispatch` with explicit axes and `task_scope` (`micro`, `phase`, `workflow`).

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
- `pas_sol_max_worker`: explicit/manual-only Sol Max work
- `pas_astra_low_worker`: first bounded Astra escalation after a named Sol High failure
- `pas_astra_medium_worker`: bounded Astra escalation after an Astra Low failure
- `pas_astra_high_worker`: bounded Astra escalation after named lower-tier failures

Route from the axes, not the phase name alone. Astra is not statically selected; its automatic chain is Sol High → Astra Low → Astra Medium → Astra High. Astra xhigh/max, Sol Max, and Ultra are explicit/manual-only and never selected automatically.

## Escalate and record

Escalate only after a named check fails. Attach the failure evidence to the next worker; the history policy must move away from the failed model/effort combination. Stop when the escalation chain is exhausted or the same failure repeats without new information.

After verification, use `record` with the actual `model`, `effort`, `phase`, `agent_name`, `dispatch_mode`, command, and result. Never record raw prompts, customer names, source text, credentials, or confidential data. A history override requires a registered exact model-effort agent, two recent verified passes, no verified failure, the same axes, and the same model generation; Max and Ultra never qualify.

Accept session identity only from runtime environment variables; otherwise use `unknown`. Never infer the current task from the globally newest rollout. Verified history may record Astra outcomes, but history overrides require an exact registered worker and never select Astra xhigh/max.
