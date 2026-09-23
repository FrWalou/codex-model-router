# R0.03 correction — Purify router to decision-only

Status: CORRECTION REQUIRED

## Architectural boundary

`codex-model-router` is a pure decision component.

It may:
- classify a bounded task descriptor
- read routing policy
- optionally read previously produced outcome/history data
- choose model + reasoning effort
- expose exact registered worker mapping
- expose the next bounded escalation candidate
- return machine-readable routing JSON

It must NOT:
- launch Codex or call `codex exec`
- spawn subprocesses
- execute tests
- inspect or mutate Git/repositories
- record outcomes or write telemetry/statistics
- decompose prompts
- call Graphify
- orchestrate/schedule/parallelize workers
- auto-learn or rewrite policy

Execution, outcome collection, graph inspection, planning/decomposition, learning, and orchestration will be separate composable tools.

## Review finding

Commit `8a02f2879ed4880005e84aaf9bd054c769e2dedc` added `run-task`, subprocess execution, post-execution scope checks, and outcome recording. Those behaviors are outside the router responsibility.

Remove that execution behavior while preserving routing functionality from R0.01–R0.02.1.

## Objective

End with: bounded task card -> classifier -> routing policy + eligible read-only history -> routing decision JSON.

## Allowed paths

- .agents/skills/codex-model-router/scripts/**
- .agents/skills/codex-model-router/tests/**
- .agents/skills/codex-model-router/SKILL.md
- .agents/skills/codex-model-router/README.md
- README.md
- CHANGELOG.md

Do not modify policy.json, .codex/agents/**, CI, or .github/CODEX_TASK.md.

## Remove execution behavior

Remove:
- `run-task` CLI
- `subprocess` use for Codex execution
- child-output parsing used only by execution
- post-execution changed-path enforcement
- execution-status/result handling
- automatic outcome recording caused by execution
- `test_run_task.py`
- docs claiming the router launches Codex

No router production code path may spawn a process.

## Stable routing interface

Expose or normalize a routing-only command, for example:

    python3 .agents/skills/codex-model-router/scripts/advisor.py route-task --task-file .github/CODEX_TASK.md --phase build

It must only read/classify the task, apply existing GPT-6 routing, expose model+effort+agent, expose dispatch capability metadata without execution, expose next escalation, and return JSON.

## Routing JSON contract

Return at least:
- schema_version
- task_family
- classification
- phase
- model
- effort
- model_version
- policy_version
- rule_id
- agent_name or null
- automatic
- next_escalation {model, effort} or null
- reason_labels
- dispatch_capability metadata only

Do not echo raw task text.

## Read-only history boundary

The router may consume eligible historical outcome records because history can influence routing.

The router must not create or append outcome records as part of routing.

If the existing standalone `record` command is retained temporarily for compatibility, mark it deprecated and document that outcome writing will move to a separate component. Prefer removing router-side writing now if this can be done without breaking history-reading compatibility.

`route-task` must always be side-effect free. Existing GPT-5.6 history remains readable and GPT-6 generation isolation remains intact.

## Preserve

Preserve the R0.02 classifier, GPT-6 policy, manual-only xhigh/max/ultra safeguards, generation isolation, bounded escalation logic, exact worker mappings, and explicit-axis recommendation compatibility.

## Tests

Cover at least:
1. normal bounded task -> GPT-6 Sol Medium
2. repeatable/verifiable task -> GPT-6 Luna Medium
3. deep/high-risk task -> GPT-6 Sol High
4. Astra not statically selected
5. exact agent mapping returned
6. Luna Medium -> Sol Medium escalation
7. Sol Medium -> Sol High escalation
8. Sol High -> Astra Low escalation
9. Astra High -> no next automatic escalation
10. GPT-5.6 history cannot influence GPT-6 routing
11. manual-only xhigh/max/ultra remain non-automatic
12. same input + policy + history -> JSON-equivalent result
13. `route-task` never calls subprocess
14. `route-task` creates/modifies no files
15. `route-task` does not append outcomes
16. raw task prose is not emitted
17. missing/malformed task file fails safely
18. existing classifier/policy/history tests remain passing

Delete execution-specific tests that no longer belong in this repository.

## Documentation

State prominently: `codex-model-router = routing decision engine only`.

Document the future composition, without implementing it here:

    task/planner -> router -> routing JSON -> executor -> validator/outcome collector -> history/stats

Graph inspection, learning, and orchestration are separate components around this contract.

## Non-goals

Do not build executor, prompt input, decomposition, Graphify, stats aggregation, learning, quota accounting, orchestration, parallel workers, or change GPT-6 policy.

## Validation

Run:

    python3 -m unittest discover -s .agents/skills/codex-model-router/tests -v
    python3 -m py_compile .agents/skills/codex-model-router/scripts/advisor.py
    git diff --check

Also prove no router production module imports or invokes `subprocess`.

## Commit

Commit exactly:

    refactor: keep router decision-only

Push normally to `dev`. Never force-push.

Then STOP and report files changed, removed execution behavior, route-task interface, routing JSON examples, history read/write boundary, proof of no subprocess execution, tests/checks, commit SHA, and push result.